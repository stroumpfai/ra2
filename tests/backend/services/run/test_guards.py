"""The three things the worker refuses, the one it tolerates, and what it says
about an endpoint that stopped it.

Each of these is a state a caller can reach and the worker has to answer for:
a config it does not implement, an evaluation that was never launched, and a
snapshot it cannot read. None of them is allowed to become a half-written run.

The endpoint cases at the end are about the *answer* rather than the state:
the run is `interrupted` either way, and the only thing separating "the model
is slower than the bound" from "nothing is listening" is the reason stored on
the row — which is why it also has to survive the read model.
"""

import pytest
from tests.backend.services.run.conftest import WEATHER, answer
from tests.fixtures.fake_llm import DEFAULT_ENDPOINT, FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.domain.llm import EndpointStatus, LlmEndpointError
from ra2.infra.config import Settings
from ra2.infra.tasks import TaskStatus
from ra2.services.errors import FeatureValidationError

pytestmark = pytest.mark.backend


async def test_run_concurrency_above_one_is_refused_not_silently_ignored(
    seed, make_run_service, task_runner, backend_settings, extractions_of
):
    """`RA2_RUN_CONCURRENCY` exists so lifting the serial limit is a config
    line rather than a rewrite (§15 F7) — and until something implements it,
    a host that sets it is told, not quietly given serial execution anyway."""
    seeded = await seed(records=2)
    parallel = Settings(data_dir=backend_settings.data_dir, run_concurrency=2, _env_file=None)
    service = make_run_service(FakeLLMClient(response=answer()), settings=parallel)

    task_id = await service.launch_runs(seeded.evaluation_id)

    assert task_runner.progress(task_id).status is TaskStatus.FAILED
    assert await extractions_of(seeded.run_id) == []
    assert (await service.get(seeded.run_id)).status is RunStatus.QUEUED


async def test_a_run_whose_evaluation_has_no_snapshot_fails_before_any_call(
    seed, make_run_service, reporter, extractions_of, run_row
):
    """The `evaluation_feature` snapshot is the authority on what the model is
    asked (§15.2). Without one there is no question to ask, and falling back
    to the draft's current feature set would ask a different one than the
    run's fingerprints claim."""
    seeded = await seed(records=3, snapshot=False)
    client = FakeLLMClient(response=answer())
    service = make_run_service(client)

    with pytest.raises(FeatureValidationError):
        await service.execute_run(seeded.run_id, reporter)

    assert client.call_count == 0
    assert await extractions_of(seeded.run_id) == []
    run = await run_row(seeded.run_id)
    assert RunStatus(run.status) is RunStatus.FAILED
    assert run.error is not None and "snapshot" in run.error


async def test_an_unreadable_codelist_snapshot_does_not_stop_the_run(
    seed, make_run_service, reporter, extractions_of
):
    """A snapshot this module cannot read means "nothing to check against".

    Raising `ENUM_CODE_NOT_IN_CODELIST` against a codelist it had guessed at
    would be a finding about its own parsing, not about the model's answer —
    and dropping the record would be a repair (Do-NOT #6).
    """
    seeded = await seed(records=1, codelist_json="[not json at all")
    service = make_run_service(FakeLLMClient(response=answer(weather="99")))

    await service.execute_run(seeded.run_id, reporter)

    row = (await extractions_of(seeded.run_id))[0]
    values = {value.feature_id: value for value in row.values}
    assert values[seeded.feature_ids[WEATHER]].value_raw == "99"
    assert row.parse_ok is True
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


async def test_a_snapshot_of_the_wrong_json_shape_is_treated_the_same_way(
    seed, make_run_service, reporter, extractions_of
):
    seeded = await seed(records=1, codelist_json='["01", "02"]')
    service = make_run_service(FakeLLMClient(response=answer(weather="99")))

    await service.execute_run(seeded.run_id, reporter)

    row = (await extractions_of(seeded.run_id))[0]
    assert row.parse_ok is True
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


@pytest.mark.parametrize(
    ("status", "other"),
    [
        (EndpointStatus.TIMED_OUT, EndpointStatus.UNREACHABLE),
        (EndpointStatus.UNREACHABLE, EndpointStatus.TIMED_OUT),
    ],
)
async def test_an_endpoint_failure_is_reported_as_the_one_it_was(
    status, other, seed, make_run_service, reporter
):
    """Two endpoint failures, two answers — and neither wearing the other's.

    Asserted on `EndpointStatus`' own value rather than on wording: the value
    is the stable identifier the way a `FindingCode` is, and it is what
    `LlmEndpointError` puts in the sentence the worker stores. What must not
    happen is the two reading alike — an analyst told "unreachable" goes to
    look at Ollama, the port and the firewall, none of which is the problem
    when the endpoint is answering and merely slow.

    Both directions are run, so this cannot pass by hard-coding either word.
    """
    seeded = await seed(records=3)
    service = make_run_service(
        FakeLLMClient(
            response=answer(),
            fail_from=0,
            failure=LlmEndpointError(DEFAULT_ENDPOINT, status),
        )
    )

    await service.execute_run(seeded.run_id, reporter)

    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.INTERRUPTED
    assert view.error is not None
    assert status.value in view.error
    assert other.value not in view.error


async def test_an_interrupted_runs_reason_survives_the_read_model(
    seed, make_run_service, reporter, run_row
):
    """The reason is stored **and** handed on.

    `_run_view` used to null `error` for anything but `FAILED`, so `_finish`
    wrote why a run stopped and the read model dropped it one layer before the
    only screen that could show it. An interrupted run is precisely the case
    that needs it: the row offers Resume either way, and the reason is what
    decides whether pressing it will achieve anything.
    """
    seeded = await seed(records=4)
    service = make_run_service(
        FakeLLMClient(
            response=answer(),
            fail_from=1,
            failure=LlmEndpointError(DEFAULT_ENDPOINT, EndpointStatus.TIMED_OUT),
        )
    )

    await service.execute_run(seeded.run_id, reporter)

    stored = await run_row(seeded.run_id)
    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.INTERRUPTED
    assert view.error == stored.error


async def test_a_run_that_finished_cleanly_carries_no_reason(seed, make_run_service, reporter):
    """The other half of the change: passing `run.error` through unconditionally
    must not invent one. A `done` run has nothing to explain, and a "log"
    action on it would be an affordance opening an empty dialog."""
    seeded = await seed(records=2)
    service = make_run_service(FakeLLMClient(response=answer()))

    await service.execute_run(seeded.run_id, reporter)

    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.DONE
    assert view.error is None


async def test_a_first_record_that_fails_at_the_endpoint_stops_the_run_at_once(
    seed, make_run_service, reporter, extractions_of
):
    """A run that has never produced a row has no evidence the configuration
    works, so the first endpoint failure is the verdict, not a flake.

    The bound matters because of what each of these costs. An
    `LlmEndpointError` reaching the worker means the adapter already exhausted
    its own retries, so the record has spent up to `RA2_LLM_TIMEOUT_S` — 600 s
    since that bound was measured against a reasoning model. Tolerating three
    was half an hour to be told what the first one said.
    """
    seeded = await seed(records=5)
    client = FakeLLMClient(
        response=answer(),
        fail_from=0,
        failure=LlmEndpointError(DEFAULT_ENDPOINT, EndpointStatus.TIMED_OUT),
    )
    service = make_run_service(client)

    await service.execute_run(seeded.run_id, reporter)

    assert client.call_count == 1
    assert await extractions_of(seeded.run_id) == []
    assert (await service.get(seeded.run_id)).status is RunStatus.INTERRUPTED


async def test_a_run_that_has_committed_a_row_still_tolerates_three(
    seed, make_run_service, reporter, extractions_of
):
    """The other side of the bound, and the reason it is two numbers rather
    than one.

    An endpoint that has answered *for this run* — this model, this prompt,
    this schema — has demonstrated the configuration works, so a failure now
    is plausibly transient and worth asking again. One committed row is the
    whole of that evidence, and it is enough.
    """
    seeded = await seed(records=6)
    client = FakeLLMClient(response=answer(), fail_from=1)
    service = make_run_service(client)

    await service.execute_run(seeded.run_id, reporter)

    # One answered, then three asked and refused before the worker stopped.
    assert client.call_count == 4
    assert len(await extractions_of(seeded.run_id)) == 1
    assert (await service.get(seeded.run_id)).status is RunStatus.INTERRUPTED


async def test_a_resume_of_a_run_with_rows_keeps_the_larger_tolerance(
    seed, make_run_service, reporter, extractions_of
):
    """The bound counts committed rows for the **run**, not calls in this
    execution.

    So a resume inherits the evidence its earlier attempt produced: a run with
    rows is a configuration that has worked, whichever process proved it. A
    resume of a run with no rows gets the strict bound, because it has none —
    which is what `tests/backend/api/runs/test_runs_resume.py` exercises from
    the other end.
    """
    seeded = await seed(records=6)
    await make_run_service(FakeLLMClient(response=answer(), fail_from=2)).execute_run(
        seeded.run_id, reporter
    )
    assert len(await extractions_of(seeded.run_id)) == 2

    # The resumed attempt fails from its very first call, and still gets three.
    resumed_client = FakeLLMClient(response=answer(), fail_from=0)
    await make_run_service(resumed_client).execute_run(seeded.run_id, reporter)

    assert resumed_client.call_count == 3
    assert len(await extractions_of(seeded.run_id)) == 2

"""The three things the worker refuses, and the one it tolerates.

Each of these is a state a caller can reach and the worker has to answer for:
a config it does not implement, an evaluation that was never launched, and a
snapshot it cannot read. None of them is allowed to become a half-written run.
"""

import pytest
from tests.backend.services.run.conftest import WEATHER, answer
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
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

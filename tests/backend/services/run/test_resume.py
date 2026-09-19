"""The headline criterion: kill a run mid-corpus, then resume it.

`mvp-spec.md` §19.5 / N5 / N6, `sw-design.md` §15.3: **every record has exactly
one extraction and no record was extracted twice**. `UNIQUE (run_id,
record_id)` is the resume key, and the set of missing records is a query
(`pending_record_ids`), not bookkeeping.

Two kills, because they leave different wreckage:

- the endpoint stops answering **mid-corpus**, leaving a hole in the *middle*
  of an already-fixed scope — the case a "continue after the last extraction"
  query would miss entirely;
- the **process dies**, leaving a row that still says `running` although
  nothing is executing it.

Both are picked up by a **second app built over the same database**, which is
what makes the claim about a restart rather than about one long-lived object.
"""

import pytest
from fastapi import FastAPI
from tests.backend.services.run.conftest import answer
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import EvaluationId, RunId
from ra2.domain.llm import EndpointStatus, LlmEndpointError
from ra2.infra.tasks import TaskStatus
from ra2.services.errors import NotFoundError
from ra2.services.run_service import RunService

pytestmark = pytest.mark.backend

ENDPOINT_DOWN = LlmEndpointError("http://127.0.0.1:11434/v1", EndpointStatus.UNREACHABLE)


def _run_service(app: FastAPI) -> RunService:
    service: RunService = app.state.services.run
    return service


async def test_a_hole_in_the_middle_is_found_and_filled_by_resume(
    seed, build_app, extractions_of, resolver
):
    """The headline test.

    The endpoint refuses the **third** record of six and answers everything
    after it, so the run ends with a hole in the middle of its scope rather
    than a truncated tail. A second app, built over the same database, resumes
    it and extracts that one record — and only that one.
    """
    seeded = await seed(records=6)
    first_client = FakeLLMClient(
        responses={marker: answer(note=marker) for marker in seeded.markers},
        failures={2: ENDPOINT_DOWN},
    )

    # --- process one: run until the endpoint refuses record three ----------
    first_app = await build_app(llm_client=first_client, seed=1)
    task_id = await _run_service(first_app).launch_runs(seeded.evaluation_id)

    assert first_app.state.task_runner.progress(task_id).status is TaskStatus.OK
    assert first_client.call_count == 6  # every record attempted, one refused
    after_first = await extractions_of(seeded.run_id)
    assert [row.record_id for row in after_first] == [
        record_id for record_id in seeded.record_ids if record_id != seeded.record_ids[2]
    ]
    interrupted = await _run_service(first_app).get(seeded.run_id)
    assert interrupted.status is RunStatus.INTERRUPTED
    assert interrupted.is_resumable is True

    # --- process two: a new app over the same database ---------------------
    resolved_before_resume = len(resolver.calls)
    second_client = FakeLLMClient(
        responses={marker: answer(note=marker) for marker in seeded.markers}
    )
    second_app = await build_app(llm_client=second_client, seed=500)
    resume_task = await _run_service(second_app).resume(seeded.run_id)

    assert second_app.state.task_runner.progress(resume_task).status is TaskStatus.OK
    # Exactly the hole, and nothing else: one call, one prompt, one record.
    assert second_client.call_count == 1
    assert seeded.markers[2] in second_client.prompts[0]
    assert [call[1] for call in resolver.calls[resolved_before_resume:]] == [seeded.record_ids[2]]

    rows = await extractions_of(seeded.run_id)
    assert [row.record_id for row in rows] == list(seeded.record_ids)
    assert len({row.record_id for row in rows}) == len(seeded.record_ids)
    assert len(rows) == 6
    # 6 records attempted in process one + the one refused record retried in
    # process two = 7 model calls for 6 records. Nothing was extracted twice.
    assert first_client.call_count + second_client.call_count == 7

    finished = await _run_service(second_app).get(seeded.run_id)
    assert finished.status is RunStatus.DONE
    assert finished.records_done == 6


async def test_a_dead_process_leaves_the_run_interrupted_not_running(
    seed, build_app, set_run_status, extractions_of
):
    """A process that dies mid-record updates no status on its way down.

    The row still says `running` on the next start although nothing is
    executing it. A new app relabels it **honestly** — and relabels it only:
    nothing auto-restarts (§15 F8).
    """
    seeded = await seed(records=5)
    first_client = FakeLLMClient(
        responses={marker: answer(note=marker) for marker in seeded.markers},
        fail_from=2,
    )
    first_app = await build_app(llm_client=first_client, seed=1)
    await _run_service(first_app).launch_runs(seeded.evaluation_id)
    # The status the worker itself wrote is replaced by the one a killed
    # process leaves behind: the last thing that happened was a commit, and
    # then the process was gone.
    await set_run_status(seeded.run_id, RunStatus.RUNNING)

    second_app = await build_app(llm_client=FakeLLMClient(), seed=500)
    view = await _run_service(second_app).get(seeded.run_id)

    assert view.status is RunStatus.INTERRUPTED
    assert view.is_resumable is True
    # Relabelled, never restarted: no new extraction appeared.
    assert len(await extractions_of(seeded.run_id)) == 2
    assert view.records_done == 2


async def test_resume_after_a_dead_process_extracts_every_missing_record_once(
    seed, build_app, set_run_status, extractions_of
):
    seeded = await seed(records=5)
    first_client = FakeLLMClient(
        responses={marker: answer(note=marker) for marker in seeded.markers},
        fail_from=2,
    )
    first_app = await build_app(llm_client=first_client, seed=1)
    await _run_service(first_app).launch_runs(seeded.evaluation_id)
    await set_run_status(seeded.run_id, RunStatus.RUNNING)

    second_client = FakeLLMClient(
        responses={marker: answer(note=marker) for marker in seeded.markers}
    )
    second_app = await build_app(llm_client=second_client, seed=500)
    await _run_service(second_app).resume(seeded.run_id)

    rows = await extractions_of(seeded.run_id)
    assert [row.record_id for row in rows] == list(seeded.record_ids)
    assert len(rows) == len({row.record_id for row in rows}) == 5
    # The three records process one never committed, and not one more.
    assert second_client.call_count == 3
    assert (await _run_service(second_app).get(seeded.run_id)).status is RunStatus.DONE


async def test_the_worker_stops_asking_a_dead_endpoint_but_keeps_what_committed(
    seed, make_run_service, reporter, extractions_of
):
    """`fail_from` kills the endpoint for good after two records.

    The run stops rather than grinding every remaining record through the
    adapter's bounded retries, keeps everything already committed, and lands
    in `interrupted` — the state Resume acts on.
    """
    seeded = await seed(records=12)
    client = FakeLLMClient(response=answer(), fail_from=2)
    service = make_run_service(client)

    await service.execute_run(seeded.run_id, reporter)

    assert len(await extractions_of(seeded.run_id)) == 2
    # Two answered, then three refusals in a row and no further asking.
    assert client.call_count == 5
    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.INTERRUPTED
    assert view.records_done == 2


async def test_resuming_a_finished_run_is_a_no_op_not_a_second_pass(
    seed, make_run_service, reporter, extractions_of, task_runner
):
    """Nothing pending means nothing to do — and certainly not a re-extraction
    (Do-NOT #2: a re-run is a new `run`, never a second write here)."""
    seeded = await seed(records=3)
    client = FakeLLMClient(response=answer())
    service = make_run_service(client)
    await service.execute_run(seeded.run_id, reporter)
    assert client.call_count == 3

    task_id = await service.resume(seeded.run_id)

    assert task_runner.progress(task_id).status is TaskStatus.OK
    assert client.call_count == 3
    assert len(await extractions_of(seeded.run_id)) == 3
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


async def test_resume_and_launch_and_get_reject_an_unknown_id(run_service, reporter):
    missing_run = RunId("no-such-run")
    with pytest.raises(NotFoundError):
        await run_service.resume(missing_run)
    with pytest.raises(NotFoundError):
        await run_service.execute_run(missing_run, reporter)
    with pytest.raises(NotFoundError):
        await run_service.get(missing_run)
    with pytest.raises(NotFoundError):
        await run_service.progress(missing_run)
    with pytest.raises(NotFoundError):
        await run_service.launch_runs(EvaluationId("no-such-evaluation"))

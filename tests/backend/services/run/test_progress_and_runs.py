"""Progress derived from committed rows, the runs table, and provenance.

`plan-phase-3.md` §15 F6: **progress is derived from committed `extraction`
rows, never from a counter column**. Every number the progress card renders is
asserted here against the rows it claims to describe — a counter that drifted
from them would pass a test written the other way round.

Also here: the dev marker (F9), serial execution (F7), and provenance written
at run **start** rather than at completion (§15.4).
"""

import pytest
from tests.backend.services.run.conftest import DEFAULT_MODEL, answer
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.infra.tasks import TaskStatus
from ra2.services.readmodels import SortDir

pytestmark = pytest.mark.backend

SECOND_MODEL = "qwen2.5:14b-instruct-q6_K"


async def test_progress_counts_match_the_committed_rows(
    seed, make_run_service, reporter, extractions_of
):
    seeded = await seed(records=4)
    service = make_run_service(
        FakeLLMClient(
            script=[answer(), "not json", answer(), answer()],
            latencies=[10, 20, 30, 40],
            retry_count=1,
        )
    )

    await service.execute_run(seeded.run_id, reporter)

    rows = await extractions_of(seeded.run_id)
    view = await service.progress(seeded.run_id)
    assert (view.done, view.total) == (len(rows), 4)
    assert view.parse_failures == sum(1 for row in rows if not row.parse_ok)
    assert view.retries == sum(row.retry_count for row in rows)
    assert view.prompt_tokens == sum(row.prompt_tokens or 0 for row in rows)
    # The lower median of 10/20/30/40 — a latency actually observed, not an
    # average of two.
    assert view.median_latency_ms == 20
    assert view.percent == 100.0
    assert view.has_metrics is True
    assert view.model_tag == DEFAULT_MODEL
    assert view.status is RunStatus.DONE


async def test_progress_of_an_interrupted_run_counts_only_what_committed(
    seed, make_run_service, reporter
):
    seeded = await seed(records=6)
    service = make_run_service(FakeLLMClient(response=answer(), fail_from=2))

    await service.execute_run(seeded.run_id, reporter)

    view = await service.progress(seeded.run_id)
    assert (view.done, view.total) == (2, 6)
    assert view.status is RunStatus.INTERRUPTED
    assert view.percent == pytest.approx(100 * 2 / 6)


async def test_a_queued_run_has_a_total_and_no_metrics(seed, run_service):
    seeded = await seed(records=5)

    view = await run_service.progress(seeded.run_id)

    assert (view.done, view.total) == (0, 5)
    assert view.status is RunStatus.QUEUED
    assert view.has_metrics is False
    assert view.percent == 0.0
    assert view.median_latency_ms is None
    assert (view.elapsed_ms, view.eta_ms) == (None, None)


async def test_reported_progress_follows_the_committed_rows(seed, make_run_service, reporter):
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer()))

    await service.execute_run(seeded.run_id, reporter)

    assert [(done, total) for done, total, _ in reporter.reports] == [
        (0, 3),
        (1, 3),
        (2, 3),
        (3, 3),
    ]
    assert {message for _, _, message in reporter.reports} == {DEFAULT_MODEL}


async def test_a_dev_sized_selection_runs_the_first_n_records_and_is_marked_dev(
    seed, make_run_service, dev_settings, reporter, extractions_of
):
    """`RA2_DEV_RECORD_MAX` is 2 here, over five records: the **first two by
    id**, deterministically (§15 F9), and every view of it says `dev`."""
    seeded = await seed(records=5, size=EvaluationSize.DEV)
    service = make_run_service(FakeLLMClient(response=answer()), settings=dev_settings)

    await service.execute_run(seeded.run_id, reporter)

    rows = await extractions_of(seeded.run_id)
    assert [row.record_id for row in rows] == list(seeded.record_ids[:2])
    view = await service.get(seeded.run_id)
    assert view.is_dev is True
    assert view.status is RunStatus.DONE
    assert (await service.progress(seeded.run_id)).total == 2


async def test_a_full_run_over_the_same_corpus_is_not_marked_dev(
    seed, make_run_service, dev_settings, reporter, extractions_of
):
    seeded = await seed(records=5, size=EvaluationSize.FULL)
    service = make_run_service(FakeLLMClient(response=answer()), settings=dev_settings)

    await service.execute_run(seeded.run_id, reporter)

    assert len(await extractions_of(seeded.run_id)) == 5
    assert (await service.get(seeded.run_id)).is_dev is False


async def test_a_dev_sized_corpus_marks_its_runs_dev_too(seed, run_service):
    """`evaluation.is_dev` is the other way in: a corpus below
    `RA2_EVAL_RECORD_MIN` is a smoke test whatever the size selection says."""
    seeded = await seed(records=2, is_dev=True)

    assert (await run_service.get(seeded.run_id)).is_dev is True


async def test_provenance_is_written_at_run_start_not_at_completion(
    seed, make_run_service, reporter, run_row, extractions_of, backend_settings
):
    """The endpoint refuses the very first record, so nothing is committed —
    and the run is still self-describing (mvp-spec.md §19.8)."""
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer(), fail_from=0))

    await service.execute_run(seeded.run_id, reporter)

    assert await extractions_of(seeded.run_id) == []
    run = await run_row(seeded.run_id)
    assert run.host_platform != ""
    assert run.gpu_name == "RTX 4090"
    assert run.llm_endpoint == backend_settings.llm_base_url
    assert run.started_at is not None
    assert RunStatus(run.status) is RunStatus.INTERRUPTED
    # Interrupted is not terminal: a human moves it out of that state.
    assert run.finished_at is None


async def test_launching_an_evaluation_runs_its_models_serially(
    seed, make_run_service, task_runner, extractions_of
):
    """One model at a time (§15 F7): every call of the first run precedes
    every call of the second."""
    seeded = await seed(records=3, models=(DEFAULT_MODEL, SECOND_MODEL))
    client = FakeLLMClient(response=answer())
    service = make_run_service(client)

    task_id = await service.launch_runs(seeded.evaluation_id)

    progress = task_runner.progress(task_id)
    assert progress.status is TaskStatus.OK
    assert (progress.done, progress.total) == (6, 6)
    assert [call[1] for call in client.calls] == [DEFAULT_MODEL] * 3 + [SECOND_MODEL] * 3
    assert len(await extractions_of(seeded.run_ids[0])) == 3
    assert len(await extractions_of(seeded.run_ids[1])) == 3


async def test_launching_skips_runs_that_are_not_queued(
    seed, make_run_service, set_run_status, extractions_of
):
    """A `done` run is not re-executed by a second launch — a re-run is a new
    `run`, never a second write over an existing one (Do-NOT #2)."""
    seeded = await seed(records=2, models=(DEFAULT_MODEL, SECOND_MODEL))
    client = FakeLLMClient(response=answer())
    service = make_run_service(client)
    await set_run_status(seeded.run_ids[0], RunStatus.DONE)

    await service.launch_runs(seeded.evaluation_id)

    assert await extractions_of(seeded.run_ids[0]) == []
    assert len(await extractions_of(seeded.run_ids[1])) == 2
    assert client.call_count == 2


async def test_the_runs_table_pages_and_sorts_on_service_call_parameters(
    seed, run_service, make_run_service
):
    seeded = await seed(records=1, models=(DEFAULT_MODEL, SECOND_MODEL, "mistral:7b"))

    page = await run_service.list_runs(seeded.evaluation_id, page=1, page_size=2)

    assert page.total == 3
    assert len(page.items) == 2
    assert (page.page, page.page_size) == (1, 2)
    assert page.sort_key == "started_at"
    assert page.sort_dir is SortDir.DESC
    second = await run_service.list_runs(seeded.evaluation_id, page=2, page_size=2)
    assert len(second.items) == 1
    by_model = await run_service.list_runs(
        seeded.evaluation_id, sort_key="model_tag", sort_dir=SortDir.ASC
    )
    assert [view.model_tag for view in by_model.items] == sorted(
        [DEFAULT_MODEL, SECOND_MODEL, "mistral:7b"]
    )
    # An unknown key is not an error; it falls back to the table's default.
    fallback = await run_service.list_runs(seeded.evaluation_id, sort_key="nonsense")
    assert fallback.sort_key == "started_at"


async def test_the_runs_table_shows_records_done_from_the_rows(
    seed, make_run_service, reporter, extractions_of
):
    seeded = await seed(records=4, models=(DEFAULT_MODEL, SECOND_MODEL))
    service = make_run_service(FakeLLMClient(response=answer(), fail_from=3))

    await service.execute_run(seeded.run_ids[0], reporter)

    page = await service.list_runs(seeded.evaluation_id)
    views = {view.run_id: view for view in page.items}
    assert views[seeded.run_ids[0]].records_done == len(await extractions_of(seeded.run_ids[0]))
    assert views[seeded.run_ids[0]].status is RunStatus.INTERRUPTED
    # A queued run sorts last in a DESC ordering — it has no `started_at`.
    assert page.items[-1].run_id == seeded.run_ids[1]
    assert views[seeded.run_ids[1]].records_done == 0
    assert views[seeded.run_ids[1]].status is RunStatus.QUEUED


async def test_elapsed_and_eta_come_from_the_clock_and_the_committed_rows(
    seed, make_run_service, reporter, clock
):
    """Halfway through a six-record run, one minute in: the ETA is the minute
    per three records extrapolated over the three that are left."""
    seeded = await seed(records=6)
    service = make_run_service(FakeLLMClient(response=answer(), fail_from=3))
    await service.execute_run(seeded.run_id, reporter)
    clock.advance(seconds=60)

    view = await service.progress(seeded.run_id)

    assert view.done == 3
    assert view.elapsed_ms == 60_000
    assert view.eta_ms == 60_000

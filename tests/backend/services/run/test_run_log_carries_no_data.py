"""The run log carries ids, counts and durations — and nothing out of a delivery.

`data-handling.md` §5 accepted "no audit trail" for a reason that is about
**content**: *keeping narrative text out of log files*. `infra/logging.py` holds
that reason as a rule while letting a half-hour job say it is working, and this
is what makes the rule a gate rather than a sentence in a document.

It is worth having as a test rather than as review vigilance for three reasons.
The resolved prompt and `response.raw_output_text` are both in scope at call
sites that log. The narrative is the most useful thing to reach for when a
record goes wrong, so the pressure to add it is real and will recur. And
CLAUDE.md #13 forbids an agent reading `data/` at all because a transcript
leaves this machine — so if this log ever carried content, pasting it into a bug
report would be the leak, by someone following the rules.

The method is deliberately blunt: drive a **real** run against the seeded
fixture, capture every record the `ra2` logger emits, and look for the
fixture's own narrative and keys in the formatted output. No allow-list of
approved fields — a new log line is covered the day it is written, without
anybody remembering to extend a list.

It also guards a trap that cost an hour to find. These fixtures run the
migrations in-process, and `logging.config.fileConfig` **disables every logger
that already exists** unless told otherwise. `alembic.ini` names only alembic's
own loggers, so the default silently set `disabled = True` on `ra2` — no
handler, no level, no error, just nothing. Each test here asserts that lines
*were* emitted before asserting what is not in them, so a return of that
default fails here rather than in six months on a run nobody could explain.
"""

import logging
from collections.abc import Iterator

import pytest
from tests.backend.services.run.conftest import answer
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.domain.llm import EndpointStatus, LlmEndpointError
from ra2.infra.logging import LOGGER_NAME

pytestmark = pytest.mark.backend

#: The seed writes `text_raw=f"Der Unfall {marker} geschah bei Regen."`, so
#: these are the words that must never appear. `markers` are the `unfall_uid`
#: values, which are delivery keys and equally out of bounds — the narrative is
#: the obvious leak and the key is the quiet one.
NARRATIVE_WORDS = ("Der Unfall", "geschah bei Regen")


class _Capture(logging.Handler):
    """Every record the `ra2` logger emits, formatted as it would be read.

    Attached to the `ra2` logger by name rather than taken from `caplog`:
    `configure_logging` turns propagation off, so a test that reached for the
    root logger's handler would quietly capture nothing the day production
    wiring runs first — and a guard that silently stops guarding is worse than
    no guard.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def run_log() -> Iterator[list[str]]:
    logger = logging.getLogger(LOGGER_NAME)
    handler = _Capture()
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler.lines
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _assert_no_delivery_content(lines: list[str], markers: tuple[str, ...]) -> None:
    blob = "\n".join(lines)
    for word in NARRATIVE_WORDS:
        assert word not in blob, f"narrative reached the log: {word!r}"
    for marker in markers:
        assert marker not in blob, f"a delivery key reached the log: {marker!r}"


async def test_a_completed_run_logs_progress_and_no_delivery_content(
    seed, make_run_service, reporter, run_log
):
    """The ordinary path, which is where the volume is: one line per record,
    twice — before the call and after it."""
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer()))

    await service.execute_run(seeded.run_id, reporter)

    assert (await service.get(seeded.run_id)).status is RunStatus.DONE
    # The log is the point of the exercise: a run that reported nothing would
    # pass the content assertions trivially.
    assert len(run_log) >= 3, run_log
    assert any("3 pending" in line for line in run_log)
    assert any("record 1/3" in line for line in run_log)
    _assert_no_delivery_content(run_log, seeded.markers)


async def test_an_endpoint_failure_logs_its_status_and_no_delivery_content(
    seed, make_run_service, reporter, run_log
):
    """The failing path, which is the one somebody reads.

    `EndpointStatus` is the code — `timed_out` and `unreachable` are two
    different repairs (amendment item 1) — and it is what the line carries
    rather than the adapter's sentence about the host.
    """
    seeded = await seed(records=3)
    failure = LlmEndpointError("http://127.0.0.1:11434/v1", EndpointStatus.TIMED_OUT, attempts=1)
    service = make_run_service(FakeLLMClient(response=answer(), failures={0: failure}))

    await service.execute_run(seeded.run_id, reporter)

    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.INTERRUPTED
    assert any(EndpointStatus.TIMED_OUT.value in line for line in run_log), run_log
    _assert_no_delivery_content(run_log, seeded.markers)


async def test_the_reclaim_verdict_is_logged_loudly(
    seed, make_run_service, run_log, db_session_factory
):
    """`reclaim_orphans` writes "the process died while this run was executing"
    about processes that are not there to answer, and the rows alone cannot say
    when it decided that. The line can, which is what lets a reader set it
    beside uvicorn's own "Reloading" — the cause of the reported one.

    It logs a count rather than a line per run: at startup a reader wants to
    know *whether* anything was left behind, and the rows carry which.
    """
    from ra2.persistence.repositories.run_repo import RunRepository

    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer()))

    # A row left `running` by a process that is gone: exactly what a reloader
    # killing the worker mid-record leaves behind.
    async with db_session_factory() as session:
        await RunRepository(session).set_status(seeded.run_id, RunStatus.RUNNING)
        await session.commit()

    assert await service.reclaim_orphans() == 1
    assert (await service.get(seeded.run_id)).status is RunStatus.INTERRUPTED
    assert any("left running by a process that died" in line for line in run_log), run_log
    _assert_no_delivery_content(run_log, seeded.markers)

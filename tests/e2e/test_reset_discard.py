"""Discard a run from the browser (plan-reset-and-discard.md §8,
sw-design.md §18).

> Seed a scored evaluation, open the Evaluation view, discard one of its two
> runs through the row action and the confirm dialog, and assert: the row is
> gone, the **other** run is untouched, the evaluation and its corpus survive,
> and the API agrees with the screen.

**Seeded directly into the session server's database**, for
`test_results_j11_to_j13.py`'s reason: a scored run needs `extraction`,
`score` and `mismatch` rows, and nothing in the product writes those except
the run worker and the scoring pass. The seeded corpus carries its own
`jdis` suffix and a prompt-template version far from every other journey's, so
it is inert for all of them.

The one thing this journey has to do that the others do not is **make itself
the evaluation on screen**. The view has no switcher and shows the newest
evaluation (`_current_evaluation`), and the fixture's rows share the frozen
clock's instant with J10's — so the `created_at` is pushed forward after
seeding. That is fixture setup making a query deterministic, not a product
behaviour being worked around.

No journey number is claimed here; the lead assigns one (§8).
"""

import asyncio
import threading
from datetime import UTC, datetime
from itertools import count

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus, seed_scored_corpus

from ra2.infra.config import Settings
from ra2.persistence.models import Evaluation
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.persistence.session import create_engine
from ra2.services.scoring_service import ScoringService
from ra2.ui.components.discard_dialog import (
    DISCARD_IRREVERSIBLE,
    DISCARD_KEEPS,
    EXPORT_LEAVES_RA2,
)

pytestmark = pytest.mark.e2e

TIMEOUT_MS = 30_000

#: Later than the frozen clock every other journey stamps its rows with, so
#: `_current_evaluation`'s "newest" is unambiguously this one.
_NEWEST = datetime(2026, 12, 31, 23, 59, tzinfo=UTC)


class _Ids:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"jdis-mismatch-{next(self._counter):04d}"


@pytest.fixture(scope="session")
def discardable_evaluation(e2e_settings: Settings, server_url: str) -> ScoredCorpus:
    async def _seed() -> ScoredCorpus:
        engine = create_engine(e2e_settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            corpus = await seed_scored_corpus(
                session, suffix="jdis", records=40, template_version=9201
            )
            await session.commit()
        scoring = ScoringService(
            session_factory=factory,
            ground_truth=GroundTruthRepository(),
            task_runner=None,  # type: ignore[arg-type]
            clock=None,  # type: ignore[arg-type]
            id_factory=_Ids(),
        )
        for run_id in corpus.run_ids:
            await scoring.score_run(run_id)
        async with factory() as session:
            await session.execute(
                update(Evaluation)
                .where(Evaluation.id == corpus.evaluation_id)
                .values(created_at=_NEWEST)
            )
            await session.commit()
        await engine.dispose()
        return corpus

    # Its own loop on its own thread: `asyncio.run` cannot re-enter the loop
    # pytest already has running (`tests/ui/conftest.py`'s `migrated_db`).
    result: list[ScoredCorpus] = []
    error: list[BaseException] = []

    def _run() -> None:
        try:
            result.append(asyncio.run(_seed()))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join(timeout=120)
    if error:
        raise error[0]
    if not result:
        raise RuntimeError("seeding the discardable evaluation did not finish")
    return result[0]


def test_discarding_a_run_removes_its_row_and_leaves_the_rest(
    page: Page, server_url: str, discardable_evaluation: ScoredCorpus
) -> None:
    page.goto(f"{server_url}/evaluation")
    expect(page.locator('[data-testid="view-title"]')).to_have_text("Evaluation")

    rows = page.locator('[data-testid="run-link"]')
    expect(rows).to_have_count(len(discardable_evaluation.run_ids), timeout=TIMEOUT_MS)
    # The link's **title**, not its text. The text is the run's ordinal within
    # the evaluation ("run 2"), which is what a person needs and what fits the
    # column; the id is what identifies a run to the API, and it rides the
    # title for exactly this. Reading the text here would not fail loudly — it
    # would make the 404 below pass because "run 1" is not a run id either.
    before = [str(rows.nth(i).get_attribute("title")) for i in range(rows.count())]
    doomed = before[0]

    # --- the row action, in the status cell (no sixth column) ---------------
    discard = page.locator('[data-testid="run-discard"]')
    expect(discard).to_have_count(len(discardable_evaluation.run_ids))
    discard.first.click()

    # --- the dialog says what it costs -------------------------------------
    dialog = page.locator('[data-testid="discard-dialog"]')
    expect(dialog).to_be_visible()
    expect(page.locator('[data-testid="discard-loss"]')).to_contain_text("extractions")
    expect(page.locator('[data-testid="discard-loss"]')).to_contain_text("scores")
    expect(page.locator('[data-testid="discard-keeps"]')).to_have_text(DISCARD_KEEPS)
    expect(page.locator('[data-testid="discard-irreversible"]')).to_have_text(DISCARD_IRREVERSIBLE)
    # Something to export, so both buttons are offered (§18.5) — and the
    # sentence saying what leaving with it costs (§18.7).
    expect(page.locator('[data-testid="discard-export"]')).to_be_visible()
    expect(page.locator('[data-testid="discard-export-warning"]')).to_have_text(EXPORT_LEAVES_RA2)

    page.locator('[data-testid="discard-confirm"]').click()

    # --- the row is gone, the other run is not ------------------------------
    expect(rows).to_have_count(len(before) - 1, timeout=TIMEOUT_MS)
    remaining = [str(rows.nth(i).get_attribute("title")) for i in range(rows.count())]
    assert doomed not in remaining
    assert set(remaining) == set(before) - {doomed}

    # --- the API agrees with the screen -------------------------------------
    listed = page.request.get(
        f"{server_url}/api/v1/runs?evaluation_id={discardable_evaluation.evaluation_id}"
    )
    assert listed.ok, listed.text()
    items = listed.json()["items"]
    assert [str(run["run_id"]) for run in items] == remaining

    # The evaluation and the corpus it cites are `RESTRICT` and untouched.
    corpus = page.request.get(f"{server_url}/api/v1/corpora/{discardable_evaluation.corpus_id}")
    assert corpus.ok, corpus.text()
    gone = page.request.get(f"{server_url}/api/v1/runs/{doomed}")
    assert gone.status == 404


def test_cancelling_the_dialog_discards_nothing(
    page: Page, server_url: str, discardable_evaluation: ScoredCorpus
) -> None:
    """The escape hatch. A confirm dialog whose Cancel is not tested is a
    confirm dialog with one button."""
    page.goto(f"{server_url}/evaluation")
    rows = page.locator('[data-testid="run-link"]')
    expect(rows.first).to_be_visible(timeout=TIMEOUT_MS)
    before = rows.all_text_contents()

    page.locator('[data-testid="run-discard"]').first.click()
    expect(page.locator('[data-testid="discard-dialog"]')).to_be_visible()
    page.locator('[data-testid="discard-cancel"]').click()
    expect(page.locator('[data-testid="discard-dialog"]')).not_to_be_visible()

    page.reload()
    expect(rows).to_have_count(len(before), timeout=TIMEOUT_MS)
    assert rows.all_text_contents() == before

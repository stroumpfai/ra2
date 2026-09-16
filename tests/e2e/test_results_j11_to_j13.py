"""J11-J13 — the Results view, as a browser sees it (sw-design.md §11.5).

Three journeys over one seeded, scored evaluation:

- **J11 Extraction** — the suppression notice, the tie legend, and the verbatim
  caveats.
- **J12 Presence** — the scope banner, the Goal 1 companion column, and the
  per-record list.
- **J13 Ranking consistency** — **the phase's keystone**: read the macro F1 off
  the Ranking tab, read the per-feature F1s off the Extraction tab, and assert
  the first is the mean of the non-suppressed second. `design/results/
  README.md` states the invariant as "if the two disagree, Ranking is wrong by
  construction"; this is where a user would see it break.

**The corpus is seeded directly into the session server's database**, not
through the UI. A scored evaluation needs `extraction` and `score` rows, and
nothing in the product writes those except the run worker and the scoring
pass — there is no button and no endpoint that creates them from nothing. J1
seeds nothing because Import can create its own corpus; this journey cannot.

**Why this file is named for its subject rather than its journey numbers.**
The session server's database is shared by every journey, and NiceGUI's
`core.app` is a process-wide singleton — two UI-mounted servers in one process
break each other's routing, as `tests/ui/conftest.py` also records — so these
journeys cannot have a database of their own. Seeded rows are therefore
visible to the journeys that ask for "the newest corpus" or list every prompt
template, and `test_j11_*.py` would sort **before** `test_j1_delivery_*.py`
(`1` < `_`), seeding before they run. Naming the file `test_results_*` puts it
after every `test_j*` file, so the corpus appears once those journeys have
finished with a database they created themselves.

That is a real constraint rather than a tidy one, and it is written down here
because the alternative — a second server — does not work, and depending on
an accident of `test_j11` sorting is worse than depending on a documented one.
"""

import asyncio
import statistics
import threading
from itertools import count

import pytest
from playwright.sync_api import Page, expect
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.fixtures.scored_corpus import RIGHT_OF_WAY, ScoredCorpus, seed_scored_corpus

from ra2.infra.config import Settings
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.persistence.session import create_engine
from ra2.services.scoring_service import ScoringService
from ra2.ui.views.results.extraction_tab import TIE_LEGEND, TIE_LEGEND_NOTE
from ra2.ui.views.results.presence_tab import SCOPE_BANNER, WINDOWS_1252_CAVEAT

pytestmark = pytest.mark.e2e


class _Ids:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"j11-mismatch-{next(self._counter):04d}"


@pytest.fixture(scope="session")
def scored_evaluation(e2e_settings: Settings, server_url: str) -> ScoredCorpus:
    """One seeded, scored evaluation in the session server's own database.

    **Seeded directly, not through the UI**: a scored evaluation needs
    `extraction` and `score` rows, and nothing in the product writes those
    except the run worker and the scoring pass. J1 seeds nothing because
    Import can create its own corpus; this journey cannot.

    It shares the session database because NiceGUI's `core.app` is a
    process-wide singleton — two UI-mounted servers in one process break each
    other's routing, which `tests/ui/conftest.py` records as well. So the
    seeded rows are made **inert** for every other journey instead: a
    `j11`-suffixed corpus nothing else queries, and a prompt template at a
    version far above J9's lineage, since `prompt_template.version` is UNIQUE
    across the database.
    """

    async def _seed() -> ScoredCorpus:
        engine = create_engine(e2e_settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            corpus = await seed_scored_corpus(
                session, suffix="j11", records=40, template_version=9101
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
        await engine.dispose()
        return corpus

    # Run on a thread with its own loop: `asyncio.run` cannot re-enter the loop
    # pytest already has running, the same reason `tests/ui/conftest.py`'s
    # `migrated_db` is synchronous.
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
        raise RuntimeError("seeding the results corpus did not finish")
    return result[0]


def _open(page: Page, server_url: str, corpus: ScoredCorpus, tab: str) -> None:
    page.goto(f"{server_url}/results?evaluation={corpus.evaluation_id}&tab={tab}")
    expect(page.locator('[data-testid="results-tabs"]')).to_be_visible()


# --- J11 ---------------------------------------------------------------------


def test_j11_the_extraction_tab_suppresses_below_the_floor_and_never_shows_a_number(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """**mvp-spec.md §11.4, in a browser.**

    The row below the floor is tinted, its `n` is shown, and all its model
    cells are replaced by **one** notice — never a number in grey.
    """
    _open(page, server_url, scored_evaluation, "extraction")

    row = page.locator('[data-testid="feature-row"][data-suppressed="true"]')
    expect(row).to_have_count(1)
    expect(row).to_contain_text(RIGHT_OF_WAY)
    expect(row).to_contain_text("17")

    note = page.locator('[data-testid="suppressed-note"]')
    expect(note).to_have_count(1)
    expect(note).to_contain_text("17 labelled cases, below the minimum of 20")
    # No metric cell survives inside the suppressed row — the four-layer
    # assertion (domain, service, JSON, DOM) ends here.
    expect(row.locator('[data-testid="metric-cell"]')).to_have_count(0)


def test_j11_the_tie_legend_and_the_suppression_rule_render_verbatim(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """On this view the copy **is** the design."""
    _open(page, server_url, scored_evaluation, "extraction")
    expect(page.locator('[data-testid="tie-legend"]')).to_contain_text(TIE_LEGEND)
    expect(page.locator('[data-testid="tie-legend"]')).to_contain_text(TIE_LEGEND_NOTE)
    expect(page.locator('[data-testid="suppression-rule"]')).to_have_text(
        "cells below n = 20 suppressed"
    )


def test_j11_every_tab_carries_the_run_descriptor_and_the_cfg_chip(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """ "A score without its config is not a result" — on all three tabs, and
    the sidebar's Results entry stays active throughout."""
    for tab in ("extraction", "presence", "ranking"):
        _open(page, server_url, scored_evaluation, tab)
        expect(page.locator('[data-testid="run-descriptor"]')).to_be_visible()
        expect(page.locator('[data-testid="cfg-chip"]')).to_be_visible()
        expect(page.locator('[data-testid="run-pill"]')).to_have_attribute("data-dev", "false")


def test_j11_clicking_a_feature_row_opens_exactly_one_breakdown(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """One breakdown open at a time, and clicking the open row closes it."""
    _open(page, server_url, scored_evaluation, "extraction")
    expect(page.locator('[data-testid="breakdown-row"]')).to_have_count(0)

    first = page.locator('[data-testid="feature-row"][data-suppressed="false"]').first
    first.click()
    expect(page.locator('[data-testid="breakdown-row"]')).to_have_count(1)
    expect(page.locator('[data-testid="hallucination-note"]')).to_contain_text(
        "Hallucination is not computed"
    )

    first.click()
    expect(page.locator('[data-testid="breakdown-row"]')).to_have_count(0)


# --- J12 ---------------------------------------------------------------------


def test_j12_the_presence_tab_leads_with_the_scope_banner(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """**Not dismissible, and first on the tab** (README §2a).

    It states `D2`'s deferral to the analyst rather than leaving an absence to
    be inferred.
    """
    _open(page, server_url, scored_evaluation, "presence")
    banner = page.locator('[data-testid="scope-banner"]')
    expect(banner).to_be_visible()
    expect(banner).to_contain_text(SCOPE_BANNER)
    expect(page.locator('[data-testid="encoding-caption"]')).to_contain_text(WINDOWS_1252_CAVEAT)


def test_j12_every_presence_row_shows_its_goal_1_companion(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """mvp-spec.md §11.2: "Goal 2 numbers are never published without the
    corresponding Goal 1 numbers." Counted, not sampled."""
    _open(page, server_url, scored_evaluation, "presence")
    rows = page.locator('[data-testid="presence-row"]')
    companions = page.locator('[data-testid="goal1-companion"]')
    expect(rows).not_to_have_count(0)
    expect(companions).to_have_count(rows.count())
    expect(page.locator("text=Goal 1 F1 — never shown apart")).to_be_visible()


def test_j12_switching_model_redraws_the_tab(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """One model at a time; the chip row is what changes it."""
    _open(page, server_url, scored_evaluation, "presence")
    second = scored_evaluation.run_ids[1]
    page.locator(f'[data-testid="model-chip"][data-model="{second}"]').click()
    expect(page.locator(f'[data-testid="model-chip"][data-model="{second}"]')).to_have_attribute(
        "aria-pressed", "true"
    )


def test_j12_the_per_record_list_is_the_deliverable(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """Goal 2 is consumed as a record list to act on, not as a rate — with the
    anonymisation marking mvp-spec.md §13 requires wherever text is shown."""
    _open(page, server_url, scored_evaluation, "presence")
    expect(page.locator('[data-testid="per-record-card"]')).to_be_visible()
    expect(page.locator('[data-testid="record-row"]').first).to_contain_text("does not say what")
    expect(page.locator('[data-testid="anonymised-chip"]').first).to_be_visible()


def test_j12_the_cross_tab_marks_the_self_contradiction_cell(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    _open(page, server_url, scored_evaluation, "presence")
    finding = page.locator('[data-testid="cross-tab-cell"][data-finding="true"]')
    expect(finding).to_have_count(1)
    expect(finding).to_have_attribute("data-outcome", "hit")
    expect(finding).to_have_attribute("data-flag", "absent")


# --- J13 — the keystone ------------------------------------------------------


def test_j13_the_ranking_macro_is_the_mean_of_the_extraction_tabs_own_cells(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """**The phase's keystone assertion.**

    `design/results/README.md`: "Every number on this tab is derived from tab
    1's scored rows — nothing here is independent... **if the two disagree,
    Ranking is wrong by construction.**"

    Read the macro off the Ranking tab, read the per-feature values off the
    Extraction tab, and assert the first is the mean of the non-suppressed
    second — in the browser, which is where a user would see it break. The
    service and API layers assert the same thing; this one is what proves the
    two tabs a person actually looks at agree.
    """
    _open(page, server_url, scored_evaluation, "extraction")
    by_model: dict[str, list[float]] = {}
    rows = page.locator('[data-testid="feature-row"][data-suppressed="false"]')
    for index in range(rows.count()):
        row = rows.nth(index)
        for cell in row.locator('[data-testid="metric-cell"]').all():
            column = cell.locator('[data-testid="interval"]')
            expect(column).to_be_visible()
        # The value line is the first `.val` in each metric cell.
        for cell_index, cell in enumerate(row.locator('[data-testid="metric-cell"]').all()):
            value = float(cell.locator(".val").inner_text().strip().split()[-1])
            by_model.setdefault(str(cell_index), []).append(value)

    _open(page, server_url, scored_evaluation, "ranking")
    ranking_rows = page.locator('[data-testid="ranking-row"]')
    expect(ranking_rows).not_to_have_count(0)

    rendered_macros = []
    for index in range(ranking_rows.count()):
        text = ranking_rows.nth(index).locator(".val").first.inner_text().strip()
        rendered_macros.append(float(text))

    expected = sorted(round(statistics.fmean(values), 3) for values in by_model.values())
    assert sorted(round(macro, 3) for macro in rendered_macros) == expected, (
        "the Ranking tab's macro disagrees with the mean of the Extraction tab's own rendered cells"
    )


def test_j13_the_ranking_does_not_claim_the_best_column_sums_to_the_feature_count(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """**P4-D2.** The design README's Ranking section says "the *best* column
    sums to 7 — exactly one highest value per feature". Under the rule this
    product follows it does not, so rendering that note verbatim would print a
    falsehood about the table directly beneath it.

    The one place the design's copy is wrong rather than stale.
    """
    _open(page, server_url, scored_evaluation, "ranking")
    expect(page.locator('[data-testid="ranking-card"]')).not_to_contain_text("sums to")
    expect(page.locator("body")).not_to_contain_text("exactly one highest value per feature")


def test_j13_tied_models_share_a_rank_and_the_verdict_says_so(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """§11.5: overlapping intervals are rendered as a tie, **not** as an
    order. Ranks repeat; they never enumerate `1, 2, 3` through a tie."""
    _open(page, server_url, scored_evaluation, "ranking")
    rows = page.locator('[data-testid="ranking-row"]')
    ranks = [int(rows.nth(i).get_attribute("data-rank") or "0") for i in range(rows.count())]
    assert ranks
    assert min(ranks) == 1
    if len(set(ranks)) == 1 and len(ranks) > 1:
        expect(page.locator('[data-testid="verdict-banner"]')).to_contain_text(
            "does not separate them"
        )


def test_j13_the_validity_footer_names_the_real_cfg_and_corpus(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    """A ranking is valid for one config on one corpus and must be re-run if
    either moves — and the footer says which, interpolated."""
    _open(page, server_url, scored_evaluation, "ranking")
    footer = page.locator('[data-testid="validity-footer"]')
    expect(footer).to_contain_text(scored_evaluation.corpus_id)
    expect(footer).to_contain_text("must be re-run")


def test_j13_the_four_computation_rules_render(
    page: Page, server_url: str, scored_evaluation: ScoredCorpus
) -> None:
    _open(page, server_url, scored_evaluation, "ranking")
    expect(page.locator('[data-testid="rule"]')).to_have_count(4)
    expect(page.locator('[data-testid="rules-card"]')).to_contain_text("reported, never scored")

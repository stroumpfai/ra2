"""Layer 3 — the Results view's three tabs (V1, V2, V3).

`design/results/README.md` is explicit that on this view **the copy is the
design**: "the suppression notices, the caveat panels and the tie language are
the product's honesty guarantees, not decoration. Reproduce them verbatim
unless the team changes the statistics."

So the copy is asserted verbatim here, from the module constants — a
paraphrase changes what the product claims, and a test that matched a
substring would not notice.
"""

import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from itertools import count

import httpx
import pytest
from fastapi import FastAPI
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import WEATHER, ScoredCorpus, seed_scored_corpus

from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.persistence.models import Run
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.container import Services
from ra2.services.scoring_service import ScoringService
from ra2.ui.components import format_latency_ms
from ra2.ui.views.results.chrome import DEV_PILL, RUN_PILL
from ra2.ui.views.results.extraction_tab import (
    ENCODING_CAVEAT,
    EXPLORATORY_FOOTER,
    HALLUCINATION_NOTE,
    TIE_LEGEND,
    TIE_LEGEND_NOTE,
)
from ra2.ui.views.results.presence_tab import (
    GOAL1_NEVER_APART,
    SCOPE_BANNER,
    WINDOWS_1252_CAVEAT,
)
from ra2.ui.views.results.ranking_tab import COMPUTATION_RULES, PARALLEL_NOTE, VALIDITY_FOOTER


class _Ids:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"ui-mismatch-{next(self._counter):04d}"


@dataclass(frozen=True)
class Scored:
    """A running UI app whose database already holds a **scored** corpus."""

    user: User
    corpus: ScoredCorpus
    #: The app's own services, so a test can ask what the view was handed
    #: rather than restate it. The descriptor is built from three rows the
    #: fixture does not carry — the corpus name and count, and the frozen
    #: per-feature fingerprints — so restating it here would just be a
    #: second, driftable copy of `build_descriptor`.
    services: Services
    #: To change a stored row between two renders, as a test that asserts a
    #: rendering *reacts* to that row has to.
    session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture
async def scored(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Scored]:
    """Seed and score inside the app under test, then hand back a browser.

    The same shape `test_prompts_view.py` uses: the app is built here so the
    fixture can reach `app.state.session_factory`, which is the only way to
    put rows in the database the view will read.
    """
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            session_factory = app.state.session_factory
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                async with session_factory() as session:
                    corpus = await seed_scored_corpus(session, records=40)
                    await session.commit()
                scoring = ScoringService(
                    session_factory=session_factory,
                    ground_truth=GroundTruthRepository(),
                    task_runner=None,  # type: ignore[arg-type]
                    clock=frozen_clock,
                    id_factory=_Ids(),
                )
                for run_id in corpus.run_ids:
                    await scoring.score_run(run_id)
                yield Scored(User(client), corpus, app.state.services, session_factory)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)


async def test_results_without_an_evaluation_shows_the_picker(user: User) -> None:
    """The design draws no picker; the view needs one (C7)."""
    await user.open("/results")
    await user.should_see(marker="results-empty")


async def test_the_tab_strip_offers_all_three_tabs(scored: Scored) -> None:
    """One route, three tabs, one sidebar entry."""
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}")
    tabs = scored.user.find(marker="results-tab").elements
    assert {e.props["data-tab"] for e in tabs} == {"extraction", "presence", "ranking"}


async def test_every_tab_carries_the_run_descriptor(scored: Scored) -> None:
    """ "A score without its config is not a result" — and the same descriptor
    on all three, so they cannot drift into three headers (R11)."""
    for tab in ("extraction", "presence", "ranking"):
        await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab={tab}")
        await scored.user.should_see(marker="run-descriptor")
        await scored.user.should_see(marker="cfg-chip")


async def test_a_full_sized_run_shows_the_run_pill_not_the_dev_marker(scored: Scored) -> None:
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}")
    (pill,) = scored.user.find(marker="run-pill").elements
    assert pill.props["data-dev"] == "false"
    await scored.user.should_see(RUN_PILL)
    await scored.user.should_not_see(DEV_PILL)


# --- tab 1 ------------------------------------------------------------------


async def test_the_extraction_tab_renders_a_row_per_scored_feature(scored: Scored) -> None:
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}")
    await scored.user.should_see(marker="extraction-card")
    await scored.user.should_see(WEATHER)


async def test_a_suppressed_row_shows_one_notice_and_never_a_number(scored: Scored) -> None:
    """**mvp-spec.md §11.4, at the DOM.** The fourth and last layer this is
    asserted at: domain, service, JSON, and here.

    All model cells are replaced by **one** `colspan` notice — never a number
    in grey, and never the same sentence three times.
    """
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}")
    rows = [
        e
        for e in scored.user.find(marker="feature-row").elements
        if e.props.get("data-suppressed") == "true"
    ]
    assert len(rows) == 1
    (note,) = scored.user.find(marker="suppressed-note").elements
    assert note.props["colspan"] == "2"
    await scored.user.should_see("17 labelled cases, below the minimum of 20")


async def test_the_suppression_rule_states_the_evaluations_own_floor(scored: Scored) -> None:
    """Interpolated, never a literal — the floor is per-evaluation (SD19)."""
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}")
    await scored.user.should_see("cells below n = 20 suppressed")


async def test_the_tie_legend_renders_verbatim(scored: Scored) -> None:
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}")
    await scored.user.should_see(TIE_LEGEND)
    await scored.user.should_see(TIE_LEGEND_NOTE)


async def test_an_expanded_breakdown_carries_the_hallucination_note_verbatim(
    scored: Scored,
) -> None:
    """The note is a **spec guarantee**, not a caption (`D1`, mvp-spec.md
    §11.1: "reports must not present a hallucination rate as if it were
    measured").

    It renders even though the mismatch list it points at is phase 5 — a
    promise the product keeps by not making a claim. Driven through the URL
    rather than a click, so the assertion is about what renders rather than
    about NiceGUI's scheduler.
    """
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=extraction")
    rows = scored.user.find(marker="feature-row").elements
    assert rows, "no feature rows to expand"
    # The breakdown is absent until a row is expanded, and its note with it.
    await scored.user.should_not_see(HALLUCINATION_NOTE)


async def test_the_breakdown_renders_its_note_and_its_stored_counts(user: User) -> None:
    """Rendered directly from a read model, the way `test_components.py`
    exercises a component: the note and the six columns are the contract, and
    a click would only be testing the scheduler."""
    from nicegui import ui

    from ra2.services.readmodels import (
        BreakdownRowView,
        BreakdownView,
        ExtractionTabView,
        FeatureScoreRow,
        MetricCell,
        ModelColumnView,
        Page,
        RunDescriptorView,
        SortDir,
    )
    from ra2.ui.views.results.extraction_tab import render_extraction_tab

    # The breakdown renders **nested inside its own feature row**, which is
    # what makes "one open at a time" a property of the table rather than of a
    # separate panel somebody has to keep in sync.
    row = FeatureScoreRow(
        feature_id="f1",  # type: ignore[arg-type]
        name="Weather",
        source_label="Witter0Ausw · enum",
        n=1842,
        suppressed=False,
        cells={"m1": MetricCell(value=0.842, ci_low=0.825, ci_high=0.858, n=1842)},
    )
    view = ExtractionTabView(
        descriptor=RunDescriptorView(
            evaluation_id="eval-x",  # type: ignore[arg-type]
            corpus_label="corpus-x",
            record_count=40,
            model_count=1,
            config_fingerprint="cfg12345678",
            is_dev=False,
            min_cell_count=20,
        ),
        models=(ModelColumnView(model_id="m1", tag="qwen3:14b", digest="abc12345"),),
        features=Page(
            items=(row,), total=1, page=1, page_size=10, sort_key="name", sort_dir=SortDir.ASC
        ),
        breakdown=BreakdownView(
            feature_id="f1",  # type: ignore[arg-type]
            feature_name="Weather",
            rows=(
                BreakdownRowView(
                    model_id="m1",
                    precision=0.887,
                    recall=0.802,
                    f1=0.842,
                    hit=1477,
                    wrong=188,
                    missing=177,
                ),
            ),
        ),
    )

    @ui.page("/t/breakdown")
    def _view() -> None:
        render_extraction_tab(view=view)

    await user.open("/t/breakdown")
    await user.should_see(HALLUCINATION_NOTE)
    # Stored counts, not back-derived from P and R (SD18).
    await user.should_see("1477")
    await user.should_see("188")
    await user.should_see("177")


# --- tab 2 ------------------------------------------------------------------


async def test_the_presence_tab_leads_with_the_scope_banner_verbatim(scored: Scored) -> None:
    """**First on the tab and not dismissible** (README §2a).

    It states the deferral to the analyst rather than leaving an absence to be
    inferred (§11.2, `D2`).
    """
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=presence")
    await scored.user.should_see(marker="scope-banner")
    await scored.user.should_see(SCOPE_BANNER)


async def test_the_goal_1_column_header_is_part_of_the_design(scored: Scored) -> None:
    """ "Never shown apart" is the header text, because presence numbers are
    never published without the Goal 1 numbers beside them (§11.2)."""
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=presence")
    await scored.user.should_see(GOAL1_NEVER_APART)


async def test_every_presence_row_renders_its_goal_1_companion(scored: Scored) -> None:
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=presence")
    rows = scored.user.find(marker="presence-row").elements
    companions = scored.user.find(marker="goal1-companion").elements
    assert rows
    assert len(companions) == len(rows), "a presence row without its Goal 1 cell"


async def test_the_windows_1252_caveat_renders_verbatim(scored: Scored) -> None:
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=presence")
    await scored.user.should_see(WINDOWS_1252_CAVEAT)


async def test_the_cross_tab_marks_the_self_contradiction_cell(scored: Scored) -> None:
    """ "That cell is the whole point of the card — style it as the finding.\""""
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=presence")
    findings = [
        e for e in scored.user.find(marker="cross-tab-cell").elements if "finding" in e.classes
    ]
    assert len(findings) == 1
    assert findings[0].props["data-outcome"] == "hit"
    assert findings[0].props["data-flag"] == "absent"


async def test_the_per_record_list_marks_anonymisation(scored: Scored) -> None:
    """Required wherever text is shown (mvp-spec.md §13), and this list shows
    the record's value."""
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=presence")
    await scored.user.should_see(marker="per-record-card")
    assert scored.user.find(marker="anonymised-chip").elements


# --- tab 3 ------------------------------------------------------------------


async def test_the_ranking_tab_renders_its_verdict_and_rules(scored: Scored) -> None:
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=ranking")
    await scored.user.should_see(marker="verdict-banner")
    assert len(scored.user.find(marker="rule").elements) == 4
    for rule in COMPUTATION_RULES:
        await scored.user.should_see(rule)


async def test_the_validity_footer_names_the_real_cfg_and_corpus(scored: Scored) -> None:
    """A ranking is valid for one config on one corpus, and the footer says
    which — interpolated, never a placeholder.

    It used to assert the corpus **id** and the first eight characters of the
    feature config **id**, because that is what the descriptor carried: three
    services each held an identical stub returning `record_count=0` and the two
    ids where the design asks for a name and a hash. The intent in the sentence
    above was always right; the values it pinned were the placeholder it was
    written to catch.

    `cfg` is now `compute_set_fingerprint` over the frozen per-feature
    fingerprints, which is what makes the chip answer "do these two boards
    describe the same question" rather than "are these two rows the same row".
    """
    descriptor = (await scored.services.ranking.ranking_tab(scored.corpus.evaluation_id)).descriptor

    assert descriptor.corpus_label.startswith("scored corpus")
    assert descriptor.config_fingerprint != scored.corpus.feature_config_id

    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=ranking")
    await scored.user.should_see(
        VALIDITY_FOOTER.format(
            cfg=descriptor.config_fingerprint[:8], corpus=descriptor.corpus_label
        )
    )


async def test_tied_models_repeat_their_rank(scored: Scored) -> None:
    """§11.5: overlapping intervals are a tie, not an order. `1, 1, 3` — never
    `1, 2, 3`."""
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=ranking")
    ranks = [int(e.props["data-rank"]) for e in scored.user.find(marker="ranking-row").elements]
    assert ranks
    assert min(ranks) == 1
    assert ranks == sorted(ranks), "rows render in rank order"


async def test_the_ranking_header_does_not_claim_the_best_column_sums_to_the_feature_count(
    scored: Scored,
) -> None:
    """**P4-D2.** The design README's Ranking section says "the *best* column
    sums to 7 — exactly one highest value per feature". Under the rule this
    product follows it does not: a model is best only when no rival interval
    overlaps it.

    Rendering that note verbatim would print a falsehood about the table
    directly beneath it — the one place the design's copy is wrong rather than
    stale.
    """
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=ranking")
    await scored.user.should_not_see("sums to")
    await scored.user.should_not_see("exactly one highest value per feature")


async def test_the_ranking_latency_column_reads_in_seconds(scored: Scored) -> None:
    """Reported, never scored (SD20) — and in the same unit as every other
    latency on screen. The expectation comes from the read model, so this
    asserts the *rendering*, not a number this test chose."""
    view = await scored.services.ranking.ranking_tab(scored.corpus.evaluation_id)
    expected = {format_latency_ms(row.median_latency_ms) for row in view.rows}
    assert expected

    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=ranking")
    rendered = [
        str(getattr(e, "text", ""))
        for row in scored.user.find(marker="ranking-row").elements
        for e in row.descendants()
    ]
    assert expected <= set(rendered)
    assert not any(text.endswith(" ms") for text in rendered)


async def test_a_serial_ranking_carries_no_parallel_mark(scored: Scored) -> None:
    """Every run at 1 — the default — renders the table as before SD38: no
    `×N` anywhere and no note explaining one."""
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=ranking")
    assert scored.user.find(marker="ranking-row").elements
    await scored.user.should_not_see(marker="parallel-mark")
    await scored.user.should_not_see(marker="parallel-note")


async def test_a_parallel_run_marks_its_latency_and_reports_time_per_record(
    scored: Scored,
) -> None:
    """SD38. The run at 4 gets the `×4` mark beside its median latency, the
    note says what the mark means, and every row renders its time per record
    in the same seconds format as the latency (SD37)."""
    parallel = scored.corpus.run_ids[0]
    async with scored.session_factory() as session:
        await session.execute(update(Run).where(Run.id == parallel).values(llm_parallel_calls=4))
        await session.commit()
    view = await scored.services.ranking.ranking_tab(scored.corpus.evaluation_id)

    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=ranking")
    marks = [str(getattr(e, "text", "")) for e in scored.user.find(marker="parallel-mark").elements]
    assert marks == ["×4"]
    await scored.user.should_see(PARALLEL_NOTE)
    per_record = {
        str(getattr(e, "text", ""))
        for cell in scored.user.find(marker="ms-per-record").elements
        for e in cell.descendants()
    }
    assert {format_latency_ms(row.ms_per_record) for row in view.rows} <= per_record


async def test_each_ranking_row_sums_to_the_scored_feature_count(scored: Scored) -> None:
    """The number that *is* safe to state: each row's best/tied/worse."""
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}&tab=ranking")
    assert scored.user.find(marker="ranking-row").elements


async def test_the_language_breakdown_carries_its_standing_caveat_verbatim(
    user: User,
) -> None:
    """**mvp-spec.md §13 requires it**: the language breakdown carries "a
    standing caveat that encoding loss affects French more than German and
    cannot be quantified".

    It is part of the card rather than of the page, so a breakdown cannot be
    rendered somewhere else without it.
    """
    from nicegui import ui

    from ra2.services.readmodels import (
        ByLanguageRow,
        ByLanguageView,
        ExtractionTabView,
        MetricCell,
        ModelColumnView,
        Page,
        RunDescriptorView,
        SortDir,
    )
    from ra2.ui.views.results.extraction_tab import render_extraction_tab

    view = ExtractionTabView(
        descriptor=RunDescriptorView(
            evaluation_id="eval-x",  # type: ignore[arg-type]
            corpus_label="corpus-x",
            record_count=40,
            model_count=1,
            config_fingerprint="cfg12345678",
            is_dev=False,
            min_cell_count=20,
        ),
        models=(ModelColumnView(model_id="m1", tag="qwen3:14b", digest="abc12345"),),
        features=Page(
            items=(), total=0, page=1, page_size=10, sort_key="name", sort_dir=SortDir.ASC
        ),
        by_language=ByLanguageView(
            feature_id="f1",  # type: ignore[arg-type]
            feature_name="Weather",
            model_id="m1",
            rows=(
                ByLanguageRow(
                    language="fr",
                    cell=MetricCell(value=0.774, ci_low=0.735, ci_high=0.809, n=498),
                ),
            ),
        ),
    )

    @ui.page("/t/by-language")
    def _view() -> None:
        render_extraction_tab(view=view)

    await user.open("/t/by-language")
    await user.should_see(ENCODING_CAVEAT)


async def test_the_exploratory_card_says_a_discovery_rate_is_not_a_score(
    user: User,
) -> None:
    """mvp-spec.md §11.3: "discovery rates are **never compared between
    models** as a quality signal. A freely hallucinating model wins this
    metric."

    The card's footer is how that reaches the analyst rather than staying an
    architectural note nobody reads.
    """
    from nicegui import ui

    from ra2.services.readmodels import (
        ExploratoryRow,
        ExtractionTabView,
        ModelColumnView,
        Page,
        RunDescriptorView,
        SortDir,
    )
    from ra2.ui.views.results.extraction_tab import render_extraction_tab

    view = ExtractionTabView(
        descriptor=RunDescriptorView(
            evaluation_id="eval-x",  # type: ignore[arg-type]
            corpus_label="corpus-x",
            record_count=40,
            model_count=1,
            config_fingerprint="cfg12345678",
            is_dev=False,
            min_cell_count=20,
        ),
        models=(ModelColumnView(model_id="m1", tag="qwen3:14b", digest="abc12345"),),
        features=Page(
            items=(), total=0, page=1, page_size=10, sort_key="name", sort_dir=SortDir.ASC
        ),
        exploratory=(
            ExploratoryRow(
                attribute_key="a1",  # type: ignore[arg-type]
                name="Phone use mentioned",
                discovery_rate=0.041,
                evidence_span_count=41,
            ),
        ),
    )

    @ui.page("/t/exploratory")
    def _view() -> None:
        render_extraction_tab(view=view)

    await user.open("/t/exploratory")
    await user.should_see(EXPLORATORY_FOOTER)
    await user.should_see("no ground truth · not ranked")
    # The reviewed counter defers with mismatch tagging (C6) — never a fake 0.
    await user.should_see("—")


async def test_a_dev_sized_run_replaces_the_run_pill_with_the_smoke_test_marker(
    user: User,
) -> None:
    """**mvp-spec.md §13**: "Required on every dev-sized result: the 'smoke
    test, not a result' marker."

    It *replaces* the run pill rather than sitting beside it, so there is no
    state in which a dev number renders unmarked.
    """
    from nicegui import ui

    from ra2.services.readmodels import RunDescriptorView
    from ra2.ui.views.results.chrome import run_descriptor

    @ui.page("/t/dev-pill")
    def _view() -> None:
        run_descriptor(
            RunDescriptorView(
                evaluation_id="eval-x",  # type: ignore[arg-type]
                corpus_label="corpus-x",
                record_count=40,
                model_count=2,
                config_fingerprint="cfg12345678",
                is_dev=True,
                min_cell_count=20,
            )
        )

    await user.open("/t/dev-pill")
    (pill,) = user.find(marker="run-pill").elements
    assert pill.props["data-dev"] == "true"
    await user.should_see(DEV_PILL)
    await user.should_not_see(RUN_PILL)

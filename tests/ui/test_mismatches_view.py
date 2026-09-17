"""Layer 3 — the Mismatches view (Z1, plan-phase-5.md §10).

**There was no design handoff for this screen** (C1). `plan-phase-5.md` §3.2
stands in for one, and it is a *boundary* rather than a starting point (R2) —
so what is asserted here is that the view is assembled from components, copy
and states that already exist, and that the four things §12 and §19's criterion
7 actually ask for are on screen: a flat list, the evidence span, inline
tagging, and a per-feature tally.

The three empty states get their own tests, and the third is the one that
matters: **"no mismatches" is a good result and must not read like an error.**
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from itertools import count

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.element import Element
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction
from sqlalchemy import delete
from tests.fixtures.scored_corpus import WEATHER, ScoredCorpus, seed_scored_corpus

from ra2.domain.mismatch import MismatchTag
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.persistence.models import Mismatch
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.scoring_service import ScoringService
from ra2.ui.views.mismatches_view import (
    NO_MATCHES_MESSAGE,
    NO_MISMATCHES_BODY,
    NO_MISMATCHES_TITLE,
    NOT_SCORED_TITLE,
    NOTHING_REVIEWED,
    OTHER_LABEL,
    TAG_LABELS,
    tally_sentence,
)


class _Ids:
    def __init__(self) -> None:
        self._counter = count(1)

    def new_id(self) -> str:
        return f"ui-mismatch-{next(self._counter):04d}"


@dataclass(frozen=True)
class Seeded:
    """A running UI app whose database holds a corpus in a known state."""

    user: User
    corpus: ScoredCorpus


async def _app(
    app_factory: Callable[..., FastAPI],
    frozen_clock: Clock,
    *,
    score: bool,
    wipe_mismatches: bool = False,
) -> AsyncIterator[Seeded]:
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
                if score:
                    scoring = ScoringService(
                        session_factory=session_factory,
                        ground_truth=GroundTruthRepository(),
                        task_runner=None,  # type: ignore[arg-type]
                        clock=frozen_clock,
                        id_factory=_Ids(),
                    )
                    for run_id in corpus.run_ids:
                        await scoring.score_run(run_id)
                if wipe_mismatches:
                    async with session_factory() as session:
                        await session.execute(delete(Mismatch))
                        await session.commit()
                yield Seeded(User(client), corpus)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)


@pytest.fixture
async def scored(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """A scored evaluation with real mismatches — the ordinary case."""
    async for seeded in _app(app_factory, frozen_clock, score=True):
        yield seeded


@pytest.fixture
async def unscored(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """A finished evaluation nobody has scored."""
    async for seeded in _app(app_factory, frozen_clock, score=False):
        yield seeded


@pytest.fixture
async def flawless(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """A scored evaluation with **no mismatches at all**.

    Produced by scoring and then removing the `mismatch` rows, which leaves
    exactly the database state a run that got everything right would leave:
    `score` rows present, zero mismatches. The fixture corpus has deliberate
    wrong answers and no knob to turn them off, and seeding a second, perfect
    corpus to reach the same two facts would be a second hazard set to keep in
    step with this one.
    """
    async for seeded in _app(app_factory, frozen_clock, score=True, wipe_mismatches=True):
        yield seeded


# --- helpers ------------------------------------------------------------------
#
# The same three `tests/ui/test_census_view.py` needs, and for the same reasons:
# `UserInteraction.elements` is a **set**, so anything positional has to sort;
# and **a click's handler is dispatched but not awaited** by `.click()`, so an
# async handler's effect — a tag written, a filter applied, a page turned — is
# not guaranteed to be on screen the instant it returns.


def _ordered(elements: Iterable[Element]) -> list[Element]:
    """NiceGUI hands out ids in creation order, which is document order here."""
    return sorted(elements, key=lambda e: e.id)


def _own_text(element: Element) -> str:
    return str(getattr(element, "text", ""))


def _one(user: User, element: Element) -> UserInteraction[Element]:
    """An interaction with exactly one element — `.click()` otherwise picks
    the lowest id among everything the marker matched."""
    return UserInteraction(user, {element}, None)


def _find(user: User, testid: str) -> list[Element]:
    return _ordered(
        e for e in user.find(kind=ui.element).elements if e._props.get("data-testid") == testid
    )


def _marked(user: User, marker: str) -> list[Element]:
    """Every element carrying `marker`, or an empty list.

    Not `user.find(marker=...)`: that **raises** when nothing matches, which
    makes "did this list empty out?" unaskable — and emptying out is exactly
    what a filter test waits for.
    """
    return _ordered(e for e in user.find(kind=ui.element).elements if marker in e._markers)


async def _until(predicate: Callable[[], bool], what: str) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{what} never became true")


def _pressed(user: User) -> list[Element]:
    """Every tag segment showing as chosen, across every row."""
    return [e for e in _find(user, "seg-option") if e._props.get("aria-pressed") == "true"]


async def _tag_first_row(seeded: Seeded, label: str) -> None:
    """Click one segment of the **first** row's control and wait for the write.

    The row redraws from the database, so "the effect landed" is "a segment
    somewhere now reads as pressed" — which is exactly what the analyst sees.
    """
    marker = f"seg-{label.lower().replace(' ', '-')}"
    _one(seeded.user, _marked(seeded.user, marker)[0]).click()
    await _until(lambda: bool(_pressed(seeded.user)), f"the {label} tag")


async def _pick(seeded: Seeded, chip: str, value: str) -> None:
    """Open a dropdown chip and choose the option carrying `value`."""
    _one(seeded.user, _marked(seeded.user, f"chip-{chip}")[0]).click()
    await _until(lambda: bool(_find(seeded.user, f"menu-{chip}")), f"the {chip} menu")
    option = next(
        e for e in _find(seeded.user, f"option-{chip}") if e._props.get("data-option") == value
    )
    _one(seeded.user, option).click()
    await _until(lambda: not _find(seeded.user, f"menu-{chip}"), f"the {chip} menu closing")


def _url(corpus: ScoredCorpus, **params: str) -> str:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return f"/mismatches?evaluation={corpus.evaluation_id}" + (f"&{query}" if query else "")


# --- the list ---------------------------------------------------------------


async def test_the_list_is_one_flat_table_of_the_runs_mismatches(scored: Seeded) -> None:
    """mvp-spec.md §12's first word is the instruction: "Presented as a
    **flat**, sortable, exportable list"."""
    await scored.user.open(_url(scored.corpus))
    await scored.user.should_see(marker="table-mismatches")
    rows = scored.user.find(marker="mismatch-feature").elements
    assert rows, "the fixture's wrong answers must produce mismatches"
    await scored.user.should_see(WEATHER)


async def test_every_row_shows_the_evidence_span(scored: Seeded) -> None:
    """`mvp-spec.md` §19's criterion 7 names this field explicitly, and `Q6`
    settles how: in the table, wrapped, never behind a hover — which is out of
    reach of a keyboard and a screen reader."""
    await scored.user.open(_url(scored.corpus))
    spans = scored.user.find(marker="mismatch-span").elements
    assert spans
    assert any(_own_text(span) not in ("", "—") for span in spans)


async def test_the_anonymisation_chip_is_on_every_row_that_shows_text(scored: Seeded) -> None:
    """**mvp-spec.md §13**: "required everywhere text is shown", and every row
    here shows an evidence span.

    The fixture's records are anonymised, so every row must carry the marking —
    one chip per row, not one per page and not one on a detail view somebody
    has to open.
    """
    await scored.user.open(_url(scored.corpus))
    records = scored.user.find(marker="mismatch-record").elements
    chips = scored.user.find(marker="anonymised-chip").elements
    assert records
    assert len(chips) == len(records)


async def test_the_table_carries_the_designs_widths_and_one_flexible_column(
    scored: Seeded,
) -> None:
    """§3.2's column table, and **no Model column**: the list is one run at a
    time and the toolbar names it (`SD26`, §17.6)."""
    await scored.user.open(_url(scored.corpus))
    (table,) = scored.user.find(marker="table-mismatches").elements
    widths = [
        e._style.get("width")
        for e in _ordered(table.descendants())
        if e.tag == "th" and "data-column" in e._props
    ]
    assert widths == ["180px", "190px", "110px", "110px", None, "270px", "96px"]
    assert widths.count(None) == 1


async def test_the_toolbar_says_when_the_run_finished(scored: Seeded) -> None:
    """`SD25`, §17.7. A re-score can delete a tagged row under an analyst and
    nothing guards that; what the view owes is a **visible reason for a list
    that changed**, and this is the closest honest thing RA2 records."""
    await scored.user.open(_url(scored.corpus))
    await scored.user.should_see(marker="run-finished-at")
    await scored.user.should_see(marker="run-descriptor")


# --- inline tagging ---------------------------------------------------------


@pytest.mark.parametrize("tag", list(MismatchTag), ids=lambda t: t.value)
async def test_each_of_the_three_tags_can_be_applied_from_the_row(
    scored: Seeded, tag: MismatchTag
) -> None:
    """`Q2`/`P3-D22`: the judgement is made **while scanning**, so the control
    is in the row. §12's own example — "of 40 reviewed" — describes bulk
    review, not forty modal round trips.

    One case per value, because the vocabulary is only closed *on the screen*
    if every member of it is reachable from the screen.
    """
    await scored.user.open(_url(scored.corpus))
    await _tag_first_row(scored, TAG_LABELS[tag])

    pressed = [
        e
        for e in scored.user.find(marker="seg-option").elements
        if e._props.get("aria-pressed") == "true"
    ]
    assert len(pressed) == 1
    assert scored.user.find(marker="mismatch-reviewed").elements


async def test_a_tag_survives_a_reload(scored: Seeded) -> None:
    """It is written to the database, not held in the page."""
    await scored.user.open(_url(scored.corpus))
    await _tag_first_row(scored, TAG_LABELS[MismatchTag.HALLUCINATION])

    await scored.user.open(_url(scored.corpus))
    pressed = [
        e
        for e in scored.user.find(marker="seg-option").elements
        if e._props.get("aria-pressed") == "true"
    ]
    assert len(pressed) == 1


async def test_a_tag_can_be_cleared(scored: Seeded) -> None:
    """`Q4`: a judgement made on the wrong row must be correctable, or the
    first mis-click is permanent in the one table a human writes to."""
    await scored.user.open(_url(scored.corpus))
    await _tag_first_row(scored, TAG_LABELS[MismatchTag.UNCLEAR])
    assert _pressed(scored.user)

    enabled = next(e for e in _marked(scored.user, "seg-clear") if "disabled" not in e.classes)
    _one(scored.user, enabled).click()
    await _until(lambda: not _pressed(scored.user), "the tag clearing")


async def test_an_untagged_row_offers_a_disabled_clear(scored: Seeded) -> None:
    """Disabled rather than hidden, so the control does not change width as an
    analyst works down the list and the row under the cursor does not move."""
    await scored.user.open(_url(scored.corpus))
    clears = _marked(scored.user, "seg-clear")
    assert clears
    assert all("disabled" in e.classes for e in clears)


# --- the filters ------------------------------------------------------------


async def test_filtering_by_feature_round_trips_through_the_toolbar(scored: Seeded) -> None:
    """The chip shows what the service was asked for, so a deep link and the
    controls cannot disagree."""
    await scored.user.open(_url(scored.corpus, feature=scored.corpus.feature_ids[WEATHER]))
    (chip,) = scored.user.find(marker="chip-feature").elements
    assert WEATHER in " ".join(_own_text(e) for e in chip.descendants())
    assert {_own_text(e) for e in _marked(scored.user, "mismatch-feature")} == {WEATHER}


async def test_filtering_by_tag_state_narrows_the_list_through_the_toolbar(
    scored: Seeded,
) -> None:
    """The analyst's work queue is `untagged`; what they have done is
    `tagged`. One closed field, because the toolbar is one control — and this
    drives it through the control rather than through the URL, so the chip and
    the service are asserted to agree about what was asked for.
    """
    await scored.user.open(_url(scored.corpus))
    before = len(_marked(scored.user, "mismatch-feature"))
    assert before > 1
    await _tag_first_row(scored, TAG_LABELS[MismatchTag.UNCLEAR])

    await _pick(scored, "tag", "untagged")
    await _until(
        lambda: len(_marked(scored.user, "mismatch-feature")) == before - 1,
        "the tagged row leaving the work queue",
    )
    assert not _pressed(scored.user), "the tagged row is the one that left"


async def test_a_filter_that_matches_nothing_says_so_without_sounding_broken(
    scored: Seeded,
) -> None:
    """Distinct from "no mismatches in this run", and deliberately so: a filter
    that matches nothing is a fact about the **filter**, not a result about the
    run — so it renders inside the table rather than replacing it.

    The tag filter is toolbar-only: the route carries `evaluation`, `run` and
    `feature` (§17.6) and not this, so the filter is driven through the control
    that owns it.
    """
    await scored.user.open(_url(scored.corpus))
    await _pick(scored, "tag", "unclear")
    await _until(lambda: not _marked(scored.user, "mismatch-feature"), "the list emptying")

    await scored.user.should_see(NO_MATCHES_MESSAGE)
    await scored.user.should_not_see(NO_MISMATCHES_TITLE)


async def test_the_run_chip_offers_the_evaluations_runs_and_no_all_option(
    scored: Seeded,
) -> None:
    """`SD26`, §17.6 — there is no "all runs" value, because a list mixing two
    models' mismatches for one record and feature **is** the cross-model
    agreement §16.9 defers."""
    await scored.user.open(_url(scored.corpus))
    _one(scored.user, _marked(scored.user, "chip-run")[0]).click()
    await _until(lambda: bool(_find(scored.user, "menu-run")), "the run menu")

    options = _find(scored.user, "option-run")
    #: Exactly the evaluation's runs, and nothing standing for all of them.
    #: Asserted on the values rather than on the labels, because a model tag
    #: can contain any word — `mistral-small` contains "all".
    assert {str(e._props["data-option"]) for e in options} == set(scored.corpus.run_ids)
    assert "" not in {str(e._props["data-option"]) for e in options}


# --- the tally strip --------------------------------------------------------


async def test_the_tally_strip_agrees_with_the_rendered_rows(scored: Seeded) -> None:
    """§17.4. The strip and the table come from one filter shape, so they
    cannot end up answering different questions — two numbers on one screen
    with no way to tell which is the lie."""
    await scored.user.open(_url(scored.corpus))
    rows = len(scored.user.find(marker="mismatch-feature").elements)
    cards = scored.user.find(marker="tally-sentence").elements
    assert cards

    await _tag_first_row(scored, TAG_LABELS[MismatchTag.STRUCTURED_DATA_ERROR])
    sentences = [_own_text(e) for e in scored.user.find(marker="tally-sentence").elements]
    assert any("1 record error" in sentence for sentence in sentences)
    assert len(scored.user.find(marker="mismatch-feature").elements) == rows


async def test_the_tally_uses_the_specs_own_words(scored: Seeded) -> None:
    """`C4`. mvp-spec.md §12's example says **"record error"** where the enum
    says `structured_data_error`, and both have to be right at once — which is
    only possible if the identifier and the wording are different things."""
    await scored.user.open(_url(scored.corpus))
    await _tag_first_row(scored, TAG_LABELS[MismatchTag.STRUCTURED_DATA_ERROR])
    sentences = " ".join(_own_text(e) for e in scored.user.find(marker="tally-sentence").elements)
    assert "record error" in sentences
    assert "structured_data_error" not in sentences


def test_the_tally_sentence_is_the_specs_own_shape() -> None:
    """Pure, so it is asserted directly: *"of 40 reviewed, 32 hallucination,
    8 record error"*."""
    from ra2.domain.mismatch import tally

    result = tally({MismatchTag.HALLUCINATION: 32, MismatchTag.STRUCTURED_DATA_ERROR: 8})
    assert tally_sentence(result) == "of 40 reviewed, 32 hallucination, 8 record error"
    #: A bucket at zero is left out — the spec's example names two of three.
    assert "unclear" not in tally_sentence(result)
    #: Nothing reviewed is its own phrase, not "of 0 reviewed, ".
    assert tally_sentence(tally({None: 6})) == NOTHING_REVIEWED
    #: And a value the enum does not name is counted, under its own heading.
    assert OTHER_LABEL.lower() in tally_sentence(tally({"fourth_thing": 2}))


# --- the three empty states -------------------------------------------------


async def test_without_an_evaluation_the_view_offers_the_picker(scored: Seeded) -> None:
    """The first state: nothing is selected. The same empty card the Results
    view uses, so the two read as one app."""
    await scored.user.open("/mismatches")
    await scored.user.should_see(marker="results-empty")
    await scored.user.should_not_see(marker="table-mismatches")


async def test_an_unscored_evaluation_says_it_is_not_scored_yet(unscored: Seeded) -> None:
    """The second state. **Not** the same as "no mismatches": scoring has not
    run, so nothing is known yet either way (§16.7's three states, applied to
    this list)."""
    await unscored.user.open(_url(unscored.corpus))
    await unscored.user.should_see(NOT_SCORED_TITLE)
    await unscored.user.should_not_see(NO_MISMATCHES_TITLE)


async def test_a_run_with_no_mismatches_reads_as_a_good_result(flawless: Seeded) -> None:
    """**The third state, and the one that matters** (Z1's exit criterion).

    A run with nothing wrong in it is the best outcome this product can report.
    It must not render like a failure, an error or a missing page — so it gets
    its own wording rather than an empty table, and the words say what
    happened rather than what is absent.
    """
    await flawless.user.open(_url(flawless.corpus))
    await flawless.user.should_see(NO_MISMATCHES_TITLE)
    await flawless.user.should_see(NO_MISMATCHES_BODY)
    await flawless.user.should_not_see(NOT_SCORED_TITLE)
    await flawless.user.should_not_see(NO_MATCHES_MESSAGE)
    #: And not an empty table pretending to be a result.
    await flawless.user.should_not_see(marker="table-mismatches")


# --- the deep link from Results ---------------------------------------------


async def test_the_results_feature_row_links_here_filtered(scored: Seeded) -> None:
    """`C2`, and §6.1's second declared exception.

    `design/results/README.md` asks for it — "mismatch drill-downs open the
    Mismatches view filtered to that run × feature" — and phase 4 had nowhere
    to point it. Phase 5 builds both ends.
    """
    await scored.user.open(f"/results?evaluation={scored.corpus.evaluation_id}")
    links = _marked(scored.user, "mismatch-link")
    assert links

    target = str(links[0]._props["href"])
    assert target.startswith("/mismatches?")
    assert f"evaluation={scored.corpus.evaluation_id}" in target
    assert "run=" in target
    assert "feature=" in target

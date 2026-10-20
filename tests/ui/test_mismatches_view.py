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
from typing import Final

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.element import Element
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fixtures.scored_corpus import (
    FRENCH_LOSSY,
    LIGHT,
    WEATHER,
    ScoredCorpus,
    seed_scored_corpus,
)

from ra2.domain.code_label import LabelState
from ra2.domain.codes import CodeValue
from ra2.domain.mismatch import MismatchTag
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.persistence.models import EvaluationFeature, Mismatch
from ra2.persistence.repositories.ground_truth_repo import GroundTruthRepository
from ra2.services.evaluation_service import snapshot_to_json
from ra2.services.scoring_service import ScoringService
from ra2.ui.views.mismatches_view import (
    EMPTY_BODY,
    NO_MATCHES_MESSAGE,
    NO_MISMATCHES_BODY,
    NO_MISMATCHES_TITLE,
    NOT_SCORED_TITLE,
    NOTHING_REVIEWED,
    OTHER_LABEL,
    SPAN_MIN_WIDTH_PX,
    TABLE_MIN_WIDTH,
    TAG_LABELS,
    tally_sentence,
)
from ra2.ui.views.scoring_states import STALLED_TITLE


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
    snapshots: bool = False,
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
                    if snapshots:
                        _add_snapshots(session, corpus)
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


#: The launch snapshots `labelled` adds (`SD70`): weather 1-4 in German and 5
#: only in French; light without 99, so `s06`'s answer is in no table.
WEATHER_SNAPSHOT: Final = {
    "1": {"de": "trocken"},
    "2": {"de": "nass"},
    "3": {"de": "Schnee"},
    "4": {"de": "Eis"},
    "5": {"fr": "brouillard"},
}
LIGHT_SNAPSHOT: Final = {"1": {"de": "Tag"}, "2": {"de": "Dämmerung"}, "3": {"de": "Nacht"}}


def _add_snapshots(session: AsyncSession, corpus: ScoredCorpus) -> None:
    for key, labels in ((WEATHER, WEATHER_SNAPSHOT), (LIGHT, LIGHT_SNAPSHOT)):
        session.add(
            EvaluationFeature(
                evaluation_id=corpus.evaluation_id,
                feature_id=corpus.feature_ids[key],
                enum_codelist_json=snapshot_to_json(
                    [
                        CodeValue(attribute_key=key, code=code, label=label)
                        for code, label in labels.items()
                    ]
                ),
                fingerprint="e" * 64,
            )
        )


@pytest.fixture
async def scored(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """A scored evaluation with real mismatches — the ordinary case."""
    async for seeded in _app(app_factory, frozen_clock, score=True):
        yield seeded


@pytest.fixture
async def labelled(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """The ordinary case, launched with codelist snapshots (`SD70`)."""
    async for seeded in _app(app_factory, frozen_clock, score=True, snapshots=True):
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


def _markers_in(element: Element) -> set[str]:
    """Every marker on `element` or anything inside it."""
    return {marker for e in (element, *element.descendants()) for marker in e._markers}


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

    Every row carries a chip in **every** state (SD50): a row with none would
    read as "not anonymised" when the truth is usually "unknown". One chip
    per row, not one per page and not one on a detail view somebody has to
    open.
    """
    await scored.user.open(_url(scored.corpus))
    records = scored.user.find(marker="mismatch-record").elements
    chips = scored.user.find(marker="anonymised-chip").elements
    assert records
    assert len(chips) == len(records)
    # SD50, risk B5: the fixture's mix reaches the list, and a delivered
    # narrative nobody has vouched for says so rather than showing nothing.
    assert {chip.props["data-marking"] for chip in chips} == {"anonymised_column", "unknown"}


async def test_the_record_cell_shows_the_whole_unfall_uid(scored: Seeded) -> None:
    """mvp-spec.md §12's record key, whole (`SD70`). The cell used to show 14
    characters of the surrogate `record.id`, which is in no delivery; a cut
    key cannot be searched for in the source system either."""
    await scored.user.open(_url(scored.corpus))
    texts = [_own_text(e) for e in scored.user.find(marker="mismatch-record").elements]
    assert texts
    for text in texts:
        assert len(text) == 32, text
        assert text.startswith("Us"), "the fixture's UIDs, not its rec-… ids"


async def test_each_code_carries_what_it_means_under_it(labelled: Seeded) -> None:
    """`SD70`: the label the model was shown, in the prompt language, under
    the code; and when there is none, words saying why, never a blank. Run 1's
    wrong answers cover all three: labelled weather codes, `5` labelled only
    in French, and `s06`'s light `99`, which is in no table."""
    await labelled.user.open(_url(labelled.corpus))
    record_labels = labelled.user.find(marker="mismatch-record-value-label").elements
    extracted_labels = labelled.user.find(marker="mismatch-extracted-value-label").elements

    assert {_own_text(e) for e in record_labels} >= {"trocken", "nass"}
    by_state = {e.props["data-label-state"]: _own_text(e) for e in extracted_labels}
    assert by_state[LabelState.NOT_IN_TABLE.value] == "not in code table"
    assert by_state[LabelState.NO_LABEL.value] == "no de label"
    assert LabelState.LABELLED.value in by_state


async def test_a_value_with_nothing_to_decode_has_no_line_under_it(scored: Seeded) -> None:
    """The ordinary fixture launched without snapshots: every value is
    `not_enum`, and nothing is invented under it."""
    await scored.user.open(_url(scored.corpus))
    assert scored.user.find(marker="mismatch-record-value").elements
    await scored.user.should_not_see(marker="mismatch-record-value-label")
    await scored.user.should_not_see(marker="mismatch-extracted-value-label")


# --- the detail row (SD70) -----------------------------------------------------


def _weather_url(corpus: ScoredCorpus, run: int) -> str:
    """Weather only, on one run: its rows come in record order, so the first
    is record 0 (`s05`'s lossy French) and, on the second run, the next is
    record 4 (German, "Schneefall, Strasse nass.")."""
    return _url(corpus, run=corpus.run_ids[run], feature=corpus.feature_ids[WEATHER])


def _text_of(element: Element) -> str:
    """The text an element shows, in document order."""
    return "".join(_own_text(e) for e in _ordered((element, *element.descendants())))


async def _toggle(seeded: Seeded, index: int) -> None:
    """Click one row's toggle and wait for **that** toggle to flip: the page
    redraws, so the element is found again by the row it controls."""
    toggles = _marked(seeded.user, "mismatch-toggle")
    target = str(toggles[index]._props["aria-controls"])
    before = toggles[index]._props["aria-expanded"]
    _one(seeded.user, toggles[index]).click()

    def flipped() -> bool:
        return any(
            t._props["aria-controls"] == target and t._props["aria-expanded"] != before
            for t in _marked(seeded.user, "mismatch-toggle")
        )

    await _until(flipped, "the toggle to flip")


async def test_no_detail_is_open_until_a_row_asks(scored: Seeded) -> None:
    """Fetched on open, never with the page: no narrative on first draw."""
    await scored.user.open(_weather_url(scored.corpus, 1))
    toggles = _marked(scored.user, "mismatch-toggle")
    assert toggles
    assert {t._props["aria-expanded"] for t in toggles} == {"false"}
    assert not _marked(scored.user, "mismatch-detail")


async def test_a_row_opens_onto_its_narrative_with_the_span_marked_where_it_is(
    scored: Seeded,
) -> None:
    """Record 4's text holds the span and it is marked; record 0's lossy
    French does not, and nothing is marked **or said** about it (`D1`)."""
    await scored.user.open(_weather_url(scored.corpus, 1))

    await _toggle(scored, 0)
    await _until(lambda: bool(_marked(scored.user, "detail-narrative")), "the narrative")
    (narrative,) = _marked(scored.user, "detail-narrative")
    assert _text_of(narrative) == FRENCH_LOSSY
    assert not _marked(scored.user, "detail-highlight")

    await _toggle(scored, 1)
    await _until(lambda: bool(_marked(scored.user, "detail-highlight")), "the marked span")
    (narrative,) = _marked(scored.user, "detail-narrative")
    assert _text_of(narrative) == "Schneefall, Strasse nass."
    (mark,) = _marked(scored.user, "detail-highlight")
    assert mark.tag == "mark"
    assert _text_of(mark) == "Schneefall"


async def test_one_detail_at_a_time_and_its_toggle_closes_it(scored: Seeded) -> None:
    await scored.user.open(_weather_url(scored.corpus, 1))
    await _toggle(scored, 0)
    await _toggle(scored, 1)
    (detail,) = _marked(scored.user, "mismatch-detail")
    expanded = [
        t for t in _marked(scored.user, "mismatch-toggle") if t._props["aria-expanded"] == "true"
    ]
    assert len(expanded) == 1
    assert expanded[0]._props["aria-controls"] == detail._props["id"]

    await _toggle(scored, 1)
    await _until(lambda: not _marked(scored.user, "mismatch-detail"), "the detail closing")


async def test_tagging_the_open_row_leaves_its_detail_open(scored: Seeded) -> None:
    """The judgement is made while reading the narrative; the write must not
    take the text away."""
    await scored.user.open(_weather_url(scored.corpus, 1))
    await _toggle(scored, 0)
    await _tag_first_row(scored, TAG_LABELS[MismatchTag.HALLUCINATION])
    assert len(_marked(scored.user, "mismatch-detail")) == 1
    assert _marked(scored.user, "detail-narrative")


async def test_sorting_closes_the_detail(scored: Seeded) -> None:
    """The open row may not be on the re-sorted page."""
    await scored.user.open(_weather_url(scored.corpus, 1))
    await _toggle(scored, 0)
    assert _marked(scored.user, "mismatch-detail")
    _one(scored.user, _marked(scored.user, "sort-tag")[0]).click()
    await _until(lambda: not _marked(scored.user, "mismatch-detail"), "the detail closing")


async def test_the_detail_carries_the_marking_and_the_language(scored: Seeded) -> None:
    """mvp-spec.md §13: the chip wherever text is shown, and the detail is
    the most text this screen shows."""
    await scored.user.open(_weather_url(scored.corpus, 1))
    await _toggle(scored, 0)
    (detail,) = _marked(scored.user, "mismatch-detail")
    assert "anonymised-chip" in _markers_in(detail)
    (language,) = _marked(scored.user, "detail-language")
    assert _own_text(language) == "fr · 0.41"


async def test_the_facts_say_what_was_compared_and_what_the_codes_mean(labelled: Seeded) -> None:
    """Record 0 on the first run: the record says 1, the model said 2."""
    await labelled.user.open(_weather_url(labelled.corpus, 0))
    await _toggle(labelled, 0)
    (facts,) = _marked(labelled.user, "detail-facts")
    assert facts.tag == "dl"
    (source,) = _marked(labelled.user, "detail-source-value")
    assert _own_text(source) == WEATHER
    assert "exact" in _text_of(facts)
    (record,) = _marked(labelled.user, "detail-record-label")
    (extracted,) = _marked(labelled.user, "detail-extracted-label")
    assert (_own_text(record), _own_text(extracted)) == ("trocken", "nass")


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


async def test_the_table_scrolls_rather_than_collapsing_the_evidence_span(
    scored: Seeded,
) -> None:
    """`SD54`. The six fixed columns are 956px, and `table-layout:fixed` gave
    the span whatever was left, about 46px at a 1280px window. A floor on the
    table makes a narrow window scroll the well sideways instead."""
    await scored.user.open(_url(scored.corpus))
    (table,) = scored.user.find(marker="table-mismatches").elements
    assert table._style["min-width"] == TABLE_MIN_WIDTH
    assert int(TABLE_MIN_WIDTH.removesuffix("px")) - 956 == SPAN_MIN_WIDTH_PX


async def test_the_two_value_headers_fit_their_columns(scored: Seeded) -> None:
    """`SD54`. "Extracted value" ran into "Evidence span" in a 110px column;
    the shorter labels fit, and the column keys, which the CSV and the sort
    use, did not move."""
    await scored.user.open(_url(scored.corpus))
    await scored.user.should_see("In record")
    await scored.user.should_see("Extracted")
    await scored.user.should_not_see("Extracted value")


async def test_the_toolbar_is_an_identity_row_then_a_filter_row(scored: Seeded) -> None:
    """`SD54`. One wrapping row of two wrapping groups broke wherever the
    widths fell. Now the first row says what the list is, and the second
    which part of it is shown and what acts on that part."""
    await scored.user.open(_url(scored.corpus))
    (identity,) = _find(scored.user, "toolbar-identity")
    (filters,) = _find(scored.user, "toolbar-filters")
    assert {"chip-evaluation", "chip-run", "run-finished-at", "run-descriptor"} <= _markers_in(
        identity
    )
    assert {"chip-feature", "chip-tag", "export-csv"} <= _markers_in(filters)
    assert "chip-run" not in _markers_in(filters)


async def test_the_evaluation_chip_switches_to_another_evaluation(scored: Seeded) -> None:
    """`SD54`. Every way into this screen used to go through Results; the chip
    is the way to another evaluation from here. Its options are links, so
    choosing one is the same navigation the picker makes, and `build` resets
    the filters a different evaluation invalidates."""
    evaluation_id = str(scored.corpus.evaluation_id)
    await scored.user.open(_url(scored.corpus))
    await scored.user.should_not_see(marker="option-evaluation")
    _one(scored.user, _marked(scored.user, "chip-evaluation")[0]).click()
    await scored.user.should_see(marker="option-evaluation")
    (option,) = _marked(scored.user, "option-evaluation")
    assert option._props["href"] == f"/mismatches?evaluation={evaluation_id}"
    assert option._props["aria-current"] == "true"


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


async def test_each_tally_sentence_is_inside_its_own_card(scored: Seeded) -> None:
    """`SD54`. The sentence was built after the card's `with` had closed, so it
    rendered as a loose item between the cards. It belongs to the card that
    names its feature."""
    await scored.user.open(_url(scored.corpus))
    cards = [e for e in _find(scored.user, "card") if e._props.get("data-card") == "tally"]
    assert cards
    for tally_card in cards:
        (sentence,) = [e for e in tally_card.descendants() if "tally-sentence" in e._markers]
        assert sentence._props["data-feature"] == tally_card._props["data-feature"]
    assert len(_marked(scored.user, "tally-sentence")) == len(cards)


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
    view uses, so the two read as one app — **and the list under it**
    (`SD54`). This asserted the card alone, and the card alone was the
    defect: the sidebar entry always arrives here, and the card told the
    analyst to go somewhere else."""
    await scored.user.open("/mismatches")
    await scored.user.should_see(marker="results-empty")
    await scored.user.should_see(EMPTY_BODY)
    await scored.user.should_not_see(marker="table-mismatches")
    links = scored.user.find(marker="picker-evaluation").elements
    assert {e.props["href"] for e in links} == {
        f"/mismatches?evaluation={scored.corpus.evaluation_id}"
    }


async def test_a_finished_run_nobody_scored_says_the_pass_did_not_finish(
    unscored: Seeded,
) -> None:
    """The second state, **split** (`plan-scoring-visibility-follow-ups.md`
    Part 1).

    This asserted `NOT_SCORED_TITLE` — "Not scored yet." — for a run that is
    `done` with no `score` rows, and that sentence was right only while
    nothing chained scoring off a finished run. Since `6dbe6e0`'s `SD17`
    chain, a finished run whose pass never wrote anything is a pass that
    **crashed or never ran**, and "not scored yet" tells the analyst to wait
    for something that is not coming. What it must not say is still the
    important half: not "no mismatches".
    """
    await unscored.user.open(_url(unscored.corpus))
    await unscored.user.should_see(STALLED_TITLE)
    await unscored.user.should_not_see(NO_MISMATCHES_TITLE)
    await unscored.user.should_not_see(NOT_SCORED_TITLE)
    # And the state carries the control that moves it, as Results' does.
    await unscored.user.should_see(marker="rescore")


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

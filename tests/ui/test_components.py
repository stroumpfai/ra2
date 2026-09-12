"""Layer 3 — the component kit.

`DataTable` is the one table component every view is built from
(sw-design.md §8.1.3), so what is asserted here is what every future table
inherits: exact widths, `table-layout: fixed`, a sort affordance that
**reports** rather than sorts, and an indeterminate select-all.

The last group is the architectural one. A component that quietly grew a
`sorted()` call would pass a rendering test and fail these.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from nicegui import ui
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction

from ra2.domain.feature import (
    AnyObjectMatches,
    AnyPersonMatches,
    CountObjects,
    CountPersons,
    DerivationSpec,
    DistinctCount,
    Filter,
    MaxOrdinal,
    MinOrdinal,
    Operator,
)
from ra2.domain.ids import FeatureConfigId
from ra2.services.readmodels import FeatureSetSummary, SortDir
from ra2.ui.components import (
    ColumnSpec,
    bar,
    card,
    card_header,
    chip,
    data_table,
    distribution_bar,
    footnote,
    format_count,
    long_tail_bar,
    pagination_row,
    tick,
)
from ra2.ui.components.derivation_builder import derivation_builder
from ra2.ui.components.feature_sets_table import feature_sets_table
from ra2.ui.components.primitives import (
    field_select,
    fingerprint_badge,
    frozen_readout,
    master_detail_split,
    pill,
    segmented_control,
)
from ra2.ui.state import TableState, set_table_state, table_state
from ra2.ui.theme import STYLESHEET

pytestmark = pytest.mark.ui


@dataclass(frozen=True)
class Row:
    name: str
    rows: int
    state: str


ROWS = (
    Row("vum_AG_unfall.txt", 1204, "ok"),
    Row("vum_BE_objekt.txt", 4402, "2 rejected"),
)

#: The Import file table's columns, widths verbatim from design README §1a.
COLUMNS: tuple[ColumnSpec[Row], ...] = (
    ColumnSpec(
        key="selection",
        width="30px",
        cell_style="padding-right:0;",
        header_style="padding-right:0;",
        header_render=lambda: tick(checked=False, indeterminate=True, label="Select all"),
        render=lambda row: tick(checked=True, label=f"Select {row.name}"),
    ),
    ColumnSpec(
        key="name",
        label="File",
        sortable=True,
        render=lambda row: ui.label(row.name).classes("mono").mark("filename"),
    ),
    ColumnSpec(
        key="rows",
        label="Rows",
        width="52px",
        align="right",
        sortable=True,
        render=lambda row: ui.label(format_count(row.rows)).classes("mono"),
    ),
    ColumnSpec(
        key="state",
        label="State",
        width="86px",
        sortable=True,
        render=lambda row: ui.label(row.state),
    ),
    ColumnSpec(key="action", width="46px", align="right", cell_style="padding-right:14px;"),
)


def page(path: str, build: Callable[[], object]) -> None:
    """Register a throwaway route that renders `build()` and nothing else."""

    @ui.page(path)
    def _view() -> None:
        build()


# --- DataTable --------------------------------------------------------------


async def test_the_table_is_fixed_layout_with_the_designs_widths(user):
    page("/t/widths", lambda: data_table(columns=COLUMNS, rows=ROWS, state=TableState("name")))
    await user.open("/t/widths")

    (table,) = user.find(marker="data-table").elements
    assert table._style["table-layout"] == "fixed"

    widths = {
        e._props["data-column"]: e._style.get("width")
        for e in _all(user)
        if e.tag == "th" and "data-column" in e._props
    }
    assert widths["selection"] == "30px"
    assert widths["rows"] == "52px"
    assert widths["state"] == "86px"
    assert widths["action"] == "46px"
    # The File column is the flexible one: it takes all remaining width and is
    # the only column allowed to truncate (README §1a).
    assert widths["name"] is None


async def test_every_row_the_caller_passed_is_rendered_in_order(user):
    page("/t/rows", lambda: data_table(columns=COLUMNS, rows=ROWS, state=TableState("name")))
    await user.open("/t/rows")
    assert _row_names(user) == ["vum_AG_unfall.txt", "vum_BE_objekt.txt"]
    await user.should_see("1 204")
    await user.should_see("4 402")


async def test_the_sort_arrow_shows_the_state_it_was_given(user):
    page(
        "/t/sort",
        lambda: data_table(
            columns=COLUMNS,
            rows=ROWS,
            state=TableState("rows", SortDir.DESC),
            on_sort=lambda key: None,
        ),
    )
    await user.open("/t/sort")
    (active,) = user.find(marker="sort-rows").elements
    (inactive,) = user.find(marker="sort-name").elements
    assert _text(active) == "Rows ▼"
    assert _text(inactive) == "File ▲▼"
    assert active._props["aria-sort"] == "descending"
    assert inactive._props["aria-sort"] == "none"


async def test_activating_a_sort_header_reports_the_key_and_sorts_nothing(user):
    """The component never decides a direction; the caller does, because the
    direction is part of the **service call** (§8.1.4)."""
    seen: list[str] = []
    page(
        "/t/onsort",
        lambda: data_table(
            columns=COLUMNS, rows=ROWS, state=TableState("name"), on_sort=seen.append
        ),
    )
    await user.open("/t/onsort")
    before = _row_names(user)
    user.find(marker="sort-state").click()
    assert seen == ["state"]
    assert _row_names(user) == before, "the table re-ordered itself"


async def test_an_empty_page_renders_one_line_not_a_broken_table(user):
    page(
        "/t/empty",
        lambda: data_table(
            columns=COLUMNS, rows=(), state=TableState("name"), empty_message="No files."
        ),
    )
    await user.open("/t/empty")
    await user.should_see("No files.")


# --- tick, chip, bars, pagination -------------------------------------------


async def test_the_tick_reports_all_three_states(user):
    def build() -> None:
        tick(checked=False, label="off")
        tick(checked=True, label="on")
        tick(checked=True, indeterminate=True, label="partial")

    page("/t/tick", build)
    await user.open("/t/tick")
    ticks = _ordered(user.find(marker="tick"))
    assert [t._props["aria-checked"] for t in ticks] == ["false", "true", "mixed"]
    assert "on" in ticks[1].classes
    assert "mixed" in ticks[2].classes


async def test_the_bar_draws_the_rate_it_is_given_and_clamps_the_impossible(user):
    def build() -> None:
        bar(fill_pct=81.3)
        bar(fill_pct=140.0)

    page("/t/bar", build)
    await user.open("/t/bar")
    fills = [e for e in _all(user) if e.tag == "i"]
    assert fills[0]._style["width"] == "81.3%"
    assert fills[1]._style["width"] == "100%"


async def test_the_distribution_bar_shades_segments_in_rank_order(user):
    page(
        "/t/dist",
        lambda: distribution_bar(segments=(62, 26, 9, 3), legend="2 · 62 %  1 · 26 %  3 · 9 %"),
    )
    await user.open("/t/dist")
    await user.should_see("2 · 62 %")
    segments = [e for e in _all(user) if e.tag == "i"]
    assert len(segments) == 4
    assert segments[0]._style["background"] == "var(--dist-1)"
    assert segments[3]._style["background"] == "var(--dist-4)"


async def test_a_long_tail_column_renders_24_equal_segments(user):
    page("/t/tail", lambda: long_tail_bar(legend="long tail · 1 461 distinct, no value over 1 %"))
    await user.open("/t/tail")
    assert len([e for e in _all(user) if e.tag == "i"]) == 24
    await user.should_see("long tail · 1 461 distinct, no value over 1 %")


async def test_pagination_disables_rather_than_hides(user):
    page(
        "/t/page",
        lambda: pagination_row(state=TableState("name", page_size=10), total=9, shown=7),
    )
    await user.open("/t/page")
    await user.should_see("1–7 of 9")
    assert "disabled" in _ordered(user.find(marker="page-prev"))[0]._props
    assert "disabled" in _ordered(user.find(marker="page-next"))[0]._props


async def test_pagination_enables_next_when_a_page_is_missing(user):
    seen: list[int] = []
    page(
        "/t/page2",
        lambda: pagination_row(
            state=TableState("name", page_size=10), total=25, shown=10, on_page=seen.append
        ),
    )
    await user.open("/t/page2")
    await user.should_see("1–10 of 25")
    assert "disabled" not in _ordered(user.find(marker="page-next"))[0]._props
    user.find(marker="page-next").click()
    assert seen == [2]


async def test_the_card_header_is_the_strip_with_its_count(user):
    def build() -> None:
        with card(), card_header(title="Structured sets", count="9 files · 9 selected"):
            pass

    page("/t/card", build)
    await user.open("/t/card")
    await user.should_see("Structured sets")
    await user.should_see("9 files · 9 selected")


async def test_the_chip_and_the_footnote_render_their_copy(user):
    def build() -> None:
        chip("table · all 162")
        footnote("Deselected files stay in the list.", tone="muted")

    page("/t/chip", build)
    await user.open("/t/chip")
    await user.should_see("table · all 162")
    await user.should_see("Deselected files stay in the list.")


def test_format_count_uses_the_designs_thousands_separator():
    assert format_count(4978) == "4 978"
    assert format_count(162) == "162"


# --- Phase 2 (Codelists, Features) component-kit additions ------------------
#
# design/code-feature/README.md, "New utility classes worth naming in the
# implementation": `.seg`, `.rof`/`.ro`, `.fp`, `.pill`, and the master/detail
# split both screens share.


async def test_the_segmented_control_is_real_buttons_with_one_active(user):
    seen: list[str] = []

    def build() -> None:
        segmented_control(
            options=["Labelled", "Exploratory"],
            value="Labelled",
            label="Kind",
            on_change=seen.append,
        )

    page("/t/seg", build)
    await user.open("/t/seg")

    (group,) = user.find(marker="seg").elements
    assert group._props["role"] == "group"
    labelled, exploratory = _ordered(user.find(marker="seg-option"))
    assert labelled._props["aria-pressed"] == "true"
    assert "on" in labelled.classes
    assert exploratory._props["aria-pressed"] == "false"
    assert "on" not in exploratory.classes

    user.find(marker="seg-exploratory").click()
    assert seen == ["Exploratory"]


async def test_field_select_is_a_real_button_the_caller_can_click(user):
    seen: list[str] = []

    def build() -> None:
        field_select("Accident level", label="Grain", on_click=lambda: seen.append("clicked"))

    page("/t/rof-click", build)
    await user.open("/t/rof-click")

    (editable,) = user.find(marker="rof").elements
    assert editable.tag == "button"
    assert "disabled" not in editable.classes
    assert "▾" in _text(editable)

    user.find(marker="rof").click()
    assert seen == ["clicked"]


async def test_field_select_disabled_and_frozen_readout_are_not_interactive(user):
    def build() -> None:
        field_select("n/a — no ground truth", disabled=True)
        frozen_readout("Accident level")

    page("/t/rof-frozen", build)
    await user.open("/t/rof-frozen")

    (disabled,) = user.find(marker="rof").elements
    assert disabled.tag == "span"
    assert "disabled" in disabled.classes
    assert "▾" not in _text(disabled)

    (readout,) = user.find(marker="ro").elements
    assert readout.tag == "span"
    assert "▾" not in _text(readout)
    await user.should_see("Accident level")


async def test_the_fingerprint_badge_truncates_to_six_chars_and_flags_a_preview(user):
    def build() -> None:
        fingerprint_badge("a91f4c9e2b77")
        fingerprint_badge("7e551190aa22", preview=True)

    page("/t/fp", build)
    await user.open("/t/fp")

    final, draft = _ordered(user.find(marker="fp"))
    assert _text(final) == "a91f4c"
    assert _text(draft) == "7e5511 · preview"
    (qualifier,) = user.find(marker="fp-preview").elements
    assert "fp-preview" in qualifier.classes
    assert "fp-preview{color:var(--warn)" in STYLESHEET.replace(" ", "").replace("\n", "")


async def test_the_pill_is_one_component_across_three_tones(user):
    def build() -> None:
        pill("100%", tone="ok")
        pill("no codes", tone="danger")
        pill("LOCKED · 2 evals", tone="accent")

    page("/t/pill", build)
    await user.open("/t/pill")

    ok, danger, accent = _ordered(user.find(marker="pill"))
    assert "pill-ok" in ok.classes and ok._props["data-tone"] == "ok"
    assert "pill-danger" in danger.classes and danger._props["data-tone"] == "danger"
    assert "pill-accent" in accent.classes and accent._props["data-tone"] == "accent"
    await user.should_see("100%")
    await user.should_see("no codes")
    await user.should_see("LOCKED · 2 evals")


def test_the_pill_rejects_an_unknown_tone():
    with pytest.raises(ValueError, match="unknown pill tone"):
        pill("???", tone="purple")


async def test_the_master_detail_split_never_wraps_and_floors_both_panes(user):
    """`tests/ui` runs against NiceGUI's in-process `User` — there is no real
    browser here to resize a page down to 1024px and measure boxes, the way
    `tests/e2e/test_j4_layout.py` does for the Import view's two cards
    (README, "Responsive behaviour": "the Features split and the Codelists
    split must never wrap; the list shrinks to 300px, the edit zone to
    360px"). The equivalent check at this layer: the container carries the
    right classes, and `flex-wrap:nowrap` plus both panes' floor widths are
    wired into the one shared stylesheet every page injects (`theme.inject`).
    """

    def build() -> None:
        list_pane, detail_pane = master_detail_split()
        with list_pane:
            ui.label("18 columns")
        with detail_pane:
            ui.label("WitterungAusw")

    page("/t/split", build)
    await user.open("/t/split")

    (split,) = user.find(marker="split").elements
    (list_pane_el,) = user.find(marker="split-list").elements
    (detail_pane_el,) = user.find(marker="split-detail").elements
    assert "split" in split.classes
    assert "split-list" in list_pane_el.classes
    assert "split-detail" in detail_pane_el.classes
    await user.should_see("18 columns")
    await user.should_see("WitterungAusw")

    assert ".split{flex:1;min-height:0;display:flex;flex-wrap:nowrap;}" in STYLESHEET
    assert "--split-list-floor:300px;" in STYLESHEET
    assert "--split-detail-floor:360px;" in STYLESHEET
    assert "min-width:var(--split-list-floor)" in STYLESHEET
    assert "min-width:var(--split-detail-floor)" in STYLESHEET


# --- derivation_builder (G3) -------------------------------------------------
#
# design/code-feature/README.md, Screen 2 · Case C: a tinted box of `.tok`
# chips for the closed derivation catalogue. Every one of the seven
# `DerivationSpec` shapes must round-trip through the chips without loss —
# render with a given `value`, simulate one edit, and check `on_change` got a
# new, fully-formed spec with the edited field changed and everything else
# untouched.


async def test_derivation_builder_round_trips_count_objects_operator_edit(user):
    seen: list[DerivationSpec] = []
    original = CountObjects(filter=Filter(column="AnzObjFeld", operator=Operator.EQ, value="3"))
    page(
        "/t/deriv/count-objects",
        lambda: derivation_builder(value=original, on_change=seen.append),
    )
    await user.open("/t/deriv/count-objects")

    user.find(marker="filter-operator").click()

    assert seen == [
        CountObjects(filter=Filter(column="AnzObjFeld", operator=Operator.NE, value="3"))
    ]


async def test_derivation_builder_adds_a_filter_starting_from_none(user):
    """`CountPersons(filter=None)` is a valid, fully-formed spec on its own —
    the "+ filter" chip is the edit that gives it one."""
    seen: list[DerivationSpec] = []
    original = CountPersons(filter=None)
    page(
        "/t/deriv/count-persons",
        lambda: derivation_builder(value=original, on_change=seen.append),
    )
    await user.open("/t/deriv/count-persons")

    user.find(marker="filter-add").click()

    assert seen == [CountPersons(filter=Filter(column="", operator=Operator.EQ, value=""))]


async def test_derivation_builder_round_trips_any_object_matches_add_code(user):
    """The design's own example: `M12 ×  M13 ×  + code` on an `in` filter."""
    seen: list[DerivationSpec] = []
    original = AnyObjectMatches(
        filter=Filter(column="objekt.FahrzeugartAusw", operator=Operator.IN, value=("M12", "M13"))
    )
    page(
        "/t/deriv/any-object",
        lambda: derivation_builder(value=original, on_change=seen.append),
    )
    await user.open("/t/deriv/any-object")

    user.find(marker="filter-value-add").click()

    assert seen == [
        AnyObjectMatches(
            filter=Filter(
                column="objekt.FahrzeugartAusw",
                operator=Operator.IN,
                value=("M12", "M13", ""),
            )
        )
    ]


async def test_derivation_builder_round_trips_any_person_matches_column_edit(user):
    seen: list[DerivationSpec] = []
    original = AnyPersonMatches(
        filter=Filter(column="person.VerletzungsgradAusw", operator=Operator.EQ, value="1")
    )
    page(
        "/t/deriv/any-person",
        lambda: derivation_builder(value=original, on_change=seen.append),
    )
    await user.open("/t/deriv/any-person")

    user.find(marker="filter-column").trigger("change", args="person.AlterVFeld")

    assert seen == [
        AnyPersonMatches(filter=Filter(column="person.AlterVFeld", operator=Operator.EQ, value="1"))
    ]


async def test_derivation_builder_round_trips_max_ordinal_table_edit(user):
    seen: list[DerivationSpec] = []
    original = MaxOrdinal(
        table="person", column="VerletzungsgradAusw", ordered_codes=("1", "2", "3")
    )
    page(
        "/t/deriv/max-ordinal",
        lambda: derivation_builder(value=original, on_change=seen.append),
    )
    await user.open("/t/deriv/max-ordinal")

    user.find(marker="ordinal-table-chip").click()

    assert seen == [
        MaxOrdinal(table="objekt", column="VerletzungsgradAusw", ordered_codes=("1", "2", "3"))
    ]


async def test_derivation_builder_round_trips_min_ordinal_code_removal(user):
    seen: list[DerivationSpec] = []
    original = MinOrdinal(table="objekt", column="SchadenAusw", ordered_codes=("A", "B"))
    page(
        "/t/deriv/min-ordinal",
        lambda: derivation_builder(value=original, on_change=seen.append),
    )
    await user.open("/t/deriv/min-ordinal")

    user.find(marker="ordinal-code-0-remove").click()

    assert seen == [MinOrdinal(table="objekt", column="SchadenAusw", ordered_codes=("B",))]


async def test_derivation_builder_round_trips_distinct_count_table_edit(user):
    seen: list[DerivationSpec] = []
    original = DistinctCount(table="objekt", column="FahrzeugartAusw")
    page(
        "/t/deriv/distinct",
        lambda: derivation_builder(value=original, on_change=seen.append),
    )
    await user.open("/t/deriv/distinct")

    user.find(marker="distinct-table-chip").click()

    assert seen == [DistinctCount(table="person", column="FahrzeugartAusw")]


async def test_derivation_builder_renders_every_shape_faithfully(user):
    """The "Saved as" mono line is assembled from `value` alone (design, Case
    C) — one render per shape is enough to prove every field made it in."""
    specs: list[DerivationSpec] = [
        CountObjects(filter=None),
        CountPersons(filter=Filter(column="col", operator=Operator.NOT_IN, value=("X", "Y"))),
        AnyObjectMatches(
            filter=Filter(
                column="objekt.FahrzeugartAusw", operator=Operator.IN, value=("M12", "M13")
            )
        ),
        AnyPersonMatches(filter=Filter(column="person.col", operator=Operator.IS_EMPTY)),
        MaxOrdinal(table="person", column="VerletzungsgradAusw", ordered_codes=("1", "2")),
        MinOrdinal(table="objekt", column="SchadenAusw", ordered_codes=("A",)),
        DistinctCount(table="objekt", column="FahrzeugartAusw"),
    ]

    def build() -> None:
        for spec in specs:
            derivation_builder(value=spec, on_change=lambda _: None)

    page("/t/deriv/all-shapes", build)
    await user.open("/t/deriv/all-shapes")

    expressions = [str(e.text) for e in _ordered(user.find(marker="derivation-expression"))]
    assert expressions == [
        "count_objects",
        "count_persons · col not in X, Y",
        "any_object_matches · objekt.FahrzeugartAusw in M12, M13",
        "any_person_matches · person.col is empty",
        "max_ordinal · person.VerletzungsgradAusw (1, 2)",
        "min_ordinal · objekt.SchadenAusw (A)",
        "distinct_count · objekt.FahrzeugartAusw",
    ]


# --- feature_sets_table (G3) --------------------------------------------------
#
# design/code-feature/README.md, Screen 2 · "Feature sets table": a
# `table-layout:fixed` strip with a trailing filler column, and a locked row
# whose rename/delete controls are **absent**, not disabled.

_DRAFT_SET = FeatureSetSummary(
    feature_config_id=FeatureConfigId("fc-draft"),
    name="Weather & conditions",
    version=3,
    description="Conditions + probes",
    created_at=datetime(2026, 9, 4, 14, 22, tzinfo=UTC),
    feature_count=14,
    frozen_at=None,
)
_LOCKED_SET = FeatureSetSummary(
    feature_config_id=FeatureConfigId("fc-locked"),
    name="Weather & conditions",
    version=2,
    description="v3 predecessor",
    created_at=datetime(2026, 8, 21, 9, 7, tzinfo=UTC),
    feature_count=11,
    frozen_at=datetime(2026, 8, 21, 9, 30, tzinfo=UTC),
    locked_by_evaluations=2,
)


def _noop_rename(_feature_config_id: str, _name: str) -> None:
    return None


async def test_feature_sets_table_filler_column_absorbs_width_not_a_gap(user):
    """Mirrors `test_the_table_is_fixed_layout_with_the_designs_widths` above
    and the Import view's own flexible-column pattern
    (`tests/e2e/test_j4_layout.py`): every named column carries the design's
    exact pixel width, and the trailing filler carries none, so `table-
    layout:fixed` hands it all the slack instead of opening a gap."""
    page(
        "/t/fs/widths",
        lambda: feature_sets_table(
            sets=[_DRAFT_SET],
            selected_id=None,
            on_select=lambda _: None,
            on_rename=_noop_rename,
            on_delete=lambda _: None,
            on_new_set=lambda: None,
        ),
    )
    await user.open("/t/fs/widths")

    (table,) = user.find(marker="feature-sets-table").elements
    assert table._style["table-layout"] == "fixed"

    widths = {
        e._props["data-column"]: e._style.get("width")
        for e in _all(user)
        if e.tag == "th" and "data-column" in e._props
    }
    assert widths["set"] == "164px"
    assert widths["description"] == "132px"
    assert widths["created"] == "126px"
    assert widths["features"] == "66px"
    assert widths["state"] == "138px"
    assert widths["action"] == "72px"
    assert widths["filler"] is None


async def test_feature_sets_table_locked_row_has_no_rename_or_delete_controls(user):
    """Exit criterion: absent, not `disabled=True` (README, "Feature sets
    table"; task brief)."""
    page(
        "/t/fs/locked",
        lambda: feature_sets_table(
            sets=[_LOCKED_SET],
            selected_id=None,
            on_select=lambda _: None,
            on_rename=_noop_rename,
            on_delete=lambda _: None,
            on_new_set=lambda: None,
        ),
    )
    await user.open("/t/fs/locked")

    assert _with_marker(user, "rename-button") == []
    assert _with_marker(user, "delete-button") == []
    assert _with_marker(user, "rename-input") == []

    (pill_element,) = user.find(marker="pill").elements
    assert "pill-accent" in pill_element.classes
    await user.should_see("LOCKED · 2 evals")


async def test_feature_sets_table_draft_row_rename_and_delete_are_wired(user):
    renamed: list[tuple[str, str]] = []
    deleted: list[str] = []
    page(
        "/t/fs/draft",
        lambda: feature_sets_table(
            sets=[_DRAFT_SET],
            selected_id=None,
            on_select=lambda _: None,
            on_rename=lambda feature_config_id, name: renamed.append((feature_config_id, name)),
            on_delete=deleted.append,
            on_new_set=lambda: None,
        ),
    )
    await user.open("/t/fs/draft")
    await user.should_see("draft · never run")

    (rename_input,) = user.find(marker="rename-input").elements
    assert rename_input._style.get("display") == "none"

    user.find(marker="rename-button").click()
    assert rename_input._style.get("display") == "inline-block"

    user.find(marker="rename-input").trigger("change", args="Weather & conditions (renamed)")
    assert renamed == [("fc-draft", "Weather & conditions (renamed)")]

    user.find(marker="delete-button").click()
    assert deleted == ["fc-draft"]


async def test_feature_sets_table_row_select_and_new_set_button(user):
    selected: list[str] = []
    created: list[bool] = []
    page(
        "/t/fs/select",
        lambda: feature_sets_table(
            sets=[_DRAFT_SET],
            selected_id=_DRAFT_SET.feature_config_id,
            on_select=selected.append,
            on_rename=_noop_rename,
            on_delete=lambda _: None,
            on_new_set=lambda: created.append(True),
        ),
    )
    await user.open("/t/fs/select")

    (row,) = user.find(marker="feature-set-row").elements
    assert row._props["aria-pressed"] == "true"

    user.find(marker="feature-set-row").click()
    assert selected == [_DRAFT_SET.feature_config_id]

    user.find(marker="new-set-button").click()
    assert created == [True]


# --- state ------------------------------------------------------------------


def test_toggling_the_active_column_flips_direction_and_resets_the_page():
    assert TableState("name", SortDir.ASC, page=4).toggled("name") == TableState(
        "name", SortDir.DESC, 1, 10
    )


def test_toggling_another_column_sorts_it_ascending():
    assert TableState("name", SortDir.DESC, page=4).toggled("rows") == TableState(
        "rows", SortDir.ASC, 1, 10
    )


async def test_two_tables_on_one_page_keep_independent_sort_state(user):
    """README, Interactions: "sort state is per-table and independent between
    the two tables". It lives in `app.storage.client`, never a module global
    (§12.8)."""
    captured: dict[str, TableState] = {}

    def build() -> None:
        table_state("left", sort_key="name")
        table_state("right", sort_key="name")
        set_table_state("left", table_state("left", sort_key="name").toggled("rows"))
        captured["left"] = table_state("left", sort_key="name")
        captured["right"] = table_state("right", sort_key="name")

    page("/t/state", build)
    await user.open("/t/state")
    assert captured["left"].sort_key == "rows"
    assert captured["right"].sort_key == "name"


# --- helpers ----------------------------------------------------------------


def _all(user: User) -> list[ui.element]:
    """Every element on the page, in creation order.

    `UserInteraction.elements` is a **set**, so anything asserting order has to
    sort. NiceGUI hands out ids in creation order, which is document order for
    the structures here.
    """
    return _ordered(user.find(kind=ui.element))


def _ordered[T: ui.element](interaction: UserInteraction[T]) -> list[T]:
    return sorted(interaction.elements, key=lambda e: e.id)


def _text(element: ui.element) -> str:
    parts = [getattr(child, "text", "") for child in element.descendants()]
    return " ".join(p for p in parts if p).strip()


def _row_names(user: User) -> list[str]:
    return [str(e.text) for e in _ordered(user.find(kind=ui.label, marker="filename"))]


def _with_marker(user: User, marker: str) -> list[ui.element]:
    """Elements carrying `marker`, or `[]` if none do.

    `user.find(marker=...)` raises when nothing matches — the right default
    for "select something to interact with", wrong for "prove this control
    was never rendered" (the locked-row exit criterion). This is `_all`
    filtered by marker instead of routed through `find`.
    """
    return [e for e in _all(user) if marker in e._markers]

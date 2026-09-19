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
from typing import cast

import pytest
from nicegui import ui
from nicegui.elements.label import Label
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction

from ra2.domain.extraction import RunStatus
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
from ra2.domain.ids import FeatureConfigId, RunId
from ra2.domain.llm import EndpointStatus, ProbeCode
from ra2.domain.stats import TieMark
from ra2.services.readmodels import (
    ConnectionProbeView,
    ConnectionView,
    CrossTabView,
    FeatureSetSummary,
    MetricCell,
    ResolvedPromptView,
    RunProgressView,
    SortDir,
    SuppressedCell,
)
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
from ra2.ui.components.contingency_table import contingency_table
from ra2.ui.components.derivation_builder import derivation_builder
from ra2.ui.components.feature_sets_table import feature_sets_table
from ra2.ui.components.ollama_settings import (
    ENDPOINT_INVALID_MESSAGE,
    PROBE_WORDS,
    ollama_settings_dialog,
    probe_sentence,
)
from ra2.ui.components.primitives import (
    field_select,
    fingerprint_badge,
    frozen_readout,
    labeled_field,
    master_detail_split,
    pill,
    radio_option,
    scroll_well,
    segmented_control,
    slot_highlighted_block,
    step_label,
)
from ra2.ui.components.progress_card import progress_card
from ra2.ui.components.prompt_preview import prompt_preview_panel
from ra2.ui.components.stat_cells import insufficient_cell, metric_cell, tie_marker
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


# --- Phase 3 (Prompts, Evaluation) component-kit additions (H5) -------------
#
# design/prompt-evaluation/README.md §1 (Prompts) and §2 (Evaluation): the
# label-above-field pair, the radio-style `.sel` option, the scroll well, the
# slot-highlighting mono block, the numbered step label, and the parameter
# `master_detail_split` gained for the Evaluation view's narrower split.


async def test_labeled_field_draws_the_label_above_the_control(user):
    """Step 5's Temperature/Seed pair, drawn with the label above the field
    "so input and label can't be confused" — never beside it."""

    def build() -> None:
        with labeled_field("Temperature"):
            ui.label("0.0").mark("temp-value")

    page("/t/labeled-field", build)
    await user.open("/t/labeled-field")

    (wrapper,) = user.find(marker="labeled-field").elements
    assert wrapper._style["display"] == "flex"
    assert wrapper._style["flex-direction"] == "column"

    label_el = next(e for e in _all(user) if "lbl" in e.classes)
    (value_el,) = _ordered(user.find(marker="temp-value"))
    assert label_el.id < value_el.id, "the label must render above the field, not beside it"
    assert label_el._style["margin-bottom"] == "4px"
    await user.should_see("Temperature")
    await user.should_see("0.0")


async def test_radio_option_shows_the_selected_and_unselected_glyphs(user):
    """Step 6's full/dev choice: a filled `●` and `border-color:--ink` when
    selected, an outline `○` in `--ink3` otherwise (Evaluation README §2)."""

    def build() -> None:
        radio_option("Evaluation · all 4 978", selected=True)
        radio_option("Dev · 40 records", selected=False)

    page("/t/radio", build)
    await user.open("/t/radio")

    selected_el, unselected_el = _ordered(user.find(marker="sel-radio"))
    assert selected_el._props["aria-checked"] == "true"
    assert unselected_el._props["aria-checked"] == "false"
    assert "●" in _text(selected_el)
    assert "○" in _text(unselected_el)
    assert selected_el._style["border-color"] == "var(--ink)"
    assert unselected_el._style["color"] == "var(--ink3)"


async def test_radio_option_reports_its_click(user):
    """Which option is selected is the caller's decision — this only reports
    that the option was clicked, exactly like `field_select`."""
    seen: list[str] = []
    page(
        "/t/radio-click",
        lambda: radio_option(
            "Dev · 40 records", selected=False, on_click=lambda: seen.append("dev")
        ),
    )
    await user.open("/t/radio-click")

    user.find(marker="sel-radio").click()
    assert seen == ["dev"]


async def test_scroll_well_caps_height_in_pixels_for_models_and_version_list(user):
    """The design's own arithmetic: the models card's 4 rows = 196px, the
    Prompts version list's 10 × 53px rows = 530px (Evaluation README §2 step
    4; Prompts README §1). Asserted in pixels, not in a row count this
    component never receives."""

    def build() -> None:
        with scroll_well(max_height_px=196):
            ui.label("6 models")
        with scroll_well(max_height_px=530):
            ui.label("4 versions")

    page("/t/scroll-well", build)
    await user.open("/t/scroll-well")

    models_well, versions_well = _ordered(user.find(marker="scroll-well"))
    assert models_well._style["max-height"] == "196px"
    assert versions_well._style["max-height"] == "530px"
    assert models_well._style["overflow-y"] == "auto"
    await user.should_see("6 models")
    await user.should_see("4 versions")


async def test_slot_highlighted_block_picks_out_every_slot_token(user):
    """The Source card body: `{{slot}}` tokens on `--accent-soft`, plain text
    everywhere else, single-pass — a `{{` inside plain text that is not a
    closed `{{name}}` shape is left untouched (README §1, "Source card")."""

    def build() -> None:
        slot_highlighted_block("Hello {{narrative}} and {{feature_block}} end")

    page("/t/slot-block", build)
    await user.open("/t/slot-block")

    tokens = [str(e.text) for e in _ordered(user.find(marker="slot-token"))]
    assert tokens == ["{{narrative}}", "{{feature_block}}"]
    for token_el in _ordered(user.find(marker="slot-token")):
        assert token_el._style["background"] == "var(--accent-soft)"
    await user.should_see("Hello")
    await user.should_see("end")


async def test_step_label_renders_the_numbered_title(user):
    """The setup column's "N · Title" header, one string not two (Evaluation
    README §2)."""
    page("/t/step-label", lambda: step_label(4, "Models"))
    await user.open("/t/step-label")

    (label_el,) = user.find(marker="step-label").elements
    assert str(label_el.text) == "4 · Models"
    assert "lbl" in label_el.classes
    assert label_el._style["margin-bottom"] == "6px"


async def test_master_detail_split_can_take_the_evaluations_narrower_setup_floor(user):
    """The Evaluation view's setup/progress split is not Codelists/Features/
    Prompts's 452px/300px + 520px/360px geometry — it floors its left pane
    10px narrower and sizes it to its own content (Evaluation README §2,
    "Layout"). Rather than a sibling split component, `master_detail_split`
    takes an inline-style override per pane; the test above (with no
    override) proves the old geometry is unaffected."""

    def build() -> None:
        setup_pane, progress_pane = master_detail_split(
            list_extra="flex:0 1 430px;min-width:320px;align-self:flex-start;",
            detail_extra="flex:1 1 520px;min-width:360px;",
        )
        with setup_pane:
            ui.label("6 steps")
        with progress_pane:
            ui.label("progress")

    page("/t/split-eval", build)
    await user.open("/t/split-eval")

    (split_el,) = user.find(marker="split").elements
    (setup_el,) = user.find(marker="split-list").elements
    (progress_el,) = user.find(marker="split-detail").elements

    assert "split" in split_el.classes
    assert ".split{flex:1;min-height:0;display:flex;flex-wrap:nowrap;}" in STYLESHEET
    assert setup_el._style["flex"] == "0 1 430px"
    assert setup_el._style["min-width"] == "320px"
    assert setup_el._style["align-self"] == "flex-start"
    assert progress_el._style["flex"] == "1 1 520px"
    assert progress_el._style["min-width"] == "360px"
    await user.should_see("6 steps")
    await user.should_see("progress")


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


# --- progress_card (L3) ------------------------------------------------------
#
# design/prompt-evaluation/README.md §2, "Per-model progress card": model
# tag, a right-aligned status line, a 6px `.bar`, and — for active/finished
# runs only — a metrics line. Rendered from `RunProgressView` alone, no
# service call inside the component (Do-NOT #7). Numbers below are chosen to
# keep every derived percentage a clean, unambiguous figure rather than
# reproducing the design's own fixtures verbatim.

_QUEUED_PROGRESS = RunProgressView(
    run_id=RunId("r-queued"), model_tag="phi4:14b-q8_0", status=RunStatus.QUEUED, done=0, total=5000
)
_RUNNING_PROGRESS = RunProgressView(
    run_id=RunId("r-running"),
    model_tag="llama3.1:8b-instruct-q8_0",
    status=RunStatus.RUNNING,
    done=2500,
    total=5000,
    parse_failures=5,
    median_latency_ms=800,
    prompt_tokens=1_500_000,
    eta_ms=38 * 60_000,
)
_DONE_PROGRESS = RunProgressView(
    run_id=RunId("r-done"),
    model_tag="qwen2.5:14b-instruct-q6_K",
    status=RunStatus.DONE,
    done=5000,
    total=5000,
    parse_failures=15,
    retries=11,
    median_latency_ms=1340,
    elapsed_ms=72 * 60_000,
)
_FAILED_PROGRESS = RunProgressView(
    run_id=RunId("r-failed"),
    model_tag="gemma2:27b-instruct-q5_K_M",
    status=RunStatus.FAILED,
    done=1000,
    total=4000,
    parse_failures=3,
    elapsed_ms=15 * 60_000,
)


async def test_progress_card_renders_all_four_states_from_the_read_model_alone(user):
    """Exit criterion: all four states (`queued`, `running`, `done`,
    `failed`) render correctly from `RunProgressView` alone. `queued` gets a
    0 % bar and no metrics line — "there is nothing honest to put in one
    yet" (README §2)."""
    page(
        "/t/progress/all",
        lambda: [
            progress_card(progress=p)
            for p in (_QUEUED_PROGRESS, _RUNNING_PROGRESS, _DONE_PROGRESS, _FAILED_PROGRESS)
        ],
    )
    await user.open("/t/progress/all")

    statuses = [str(e.text) for e in _ordered(user.find(marker="progress-card-status"))]
    assert statuses == [
        "queued",
        "2 500 / 5 000 · running · ETA 38 m",
        "5 000 / 5 000 · done · 1 h 12 m",
        "1 000 / 4 000 · failed · 15 m",
    ]

    fills = [e for e in _all(user) if e.tag == "i"]
    assert [f._style["width"] for f in fills] == ["0%", "50%", "100%", "25%"]
    # The bar's own *container* always spans the card, in every state — only
    # the fill inside it (asserted above) carries the percentage.
    bars = _ordered(user.find(marker="bar"))
    assert all(b._style["width"] == "100%" for b in bars)

    metrics = [str(e.text) for e in _ordered(user.find(marker="progress-card-metrics"))]
    assert metrics == [
        "parse failures 5 (0.2 %) · median latency 800 ms · 1.5 M prompt tok",
        "parse failures 15 (0.3 %) · retries 11 (bounded, counted) · median latency 1 340 ms",
        "parse failures 3 (0.3 %)",
    ], "queued must be the only card without a metrics line"

    model_labels = _ordered(user.find(marker="progress-card-model"))
    assert model_labels[0]._style["color"] == "var(--ink2)", "queued is dimmed"
    assert all(label._style["color"] == "var(--ink)" for label in model_labels[1:])

    status_labels = _ordered(user.find(marker="progress-card-status"))
    assert status_labels[3]._style["color"] == "var(--danger)", "failed reads as an error"
    assert all(label._style["color"] == "var(--ink3)" for label in status_labels[:3])


async def test_a_running_card_with_nothing_committed_still_shows_it_is_working(user):
    """The state the Evaluation screen could not describe.

    `_eta_ms` returns `None` until one record has committed — deliberately,
    because an ETA from zero records is "a guess wearing a number's clothes"
    (`run_service`). On a model that takes minutes per record that is the
    whole of the first stretch of a run, during which this line read
    `0 / 12 · running` over a bar at zero and did not change. Nothing on the
    screen separated a worker that was extracting from one whose process had
    died, which is what mvp-spec.md N6's "progress is visible" has to mean
    while the first record is still in flight.

    `elapsed_ms` was in the read model the whole time; only the finished
    branch rendered it.
    """
    progress = RunProgressView(
        run_id=RunId("r-fresh"),
        model_tag="qwen3.5:latest",
        status=RunStatus.RUNNING,
        done=0,
        total=12,
        elapsed_ms=4 * 60_000,
    )
    page("/t/progress/fresh", lambda: progress_card(progress=progress))
    await user.open("/t/progress/fresh")

    (status,) = _ordered(user.find(marker="progress-card-status"))
    assert str(status.text) == "0 / 12 · running · 4 m"
    assert "ETA" not in str(status.text), "nothing has committed to extrapolate from"


async def test_a_running_card_shows_elapsed_and_eta_once_it_has_both(user):
    """Elapsed first, then the ETA — time spent before time guessed."""
    progress = RunProgressView(
        run_id=RunId("r-going"),
        model_tag="qwen3.5:latest",
        status=RunStatus.RUNNING,
        done=3,
        total=12,
        elapsed_ms=12 * 60_000,
        eta_ms=36 * 60_000,
    )
    page("/t/progress/going", lambda: progress_card(progress=progress))
    await user.open("/t/progress/going")

    (status,) = _ordered(user.find(marker="progress-card-status"))
    assert str(status.text) == "3 / 12 · running · 12 m · ETA 36 m"


async def test_progress_card_never_calls_a_service(user):
    """Do-NOT #7, mechanically: the component's only input is the read
    model, and rendering it twice with the same value produces the same
    output — nothing here reaches out for fresher data on its own."""
    page(
        "/t/progress/pure",
        lambda: [
            progress_card(progress=_RUNNING_PROGRESS),
            progress_card(progress=_RUNNING_PROGRESS),
        ],
    )
    await user.open("/t/progress/pure")

    statuses = [str(e.text) for e in _ordered(user.find(marker="progress-card-status"))]
    assert statuses[0] == statuses[1]


# --- prompt_preview_panel (L3) ------------------------------------------------
#
# design/prompt-evaluation/README.md §1, "Resolved card" (C4): one component,
# two entry points (Prompts' "Preview with record 1", Evaluation's "Preview
# prompt"), rendering byte-identical output for the same `ResolvedPromptView`.

_RESOLVED = ResolvedPromptView(
    text="You extract structured facts. --- narrative --- Car left the road, weather clear.",
    token_estimate=1842,
    record_key="R-2026-0031",
    feature_count=13,
)

#: One golden string both entry points must reproduce exactly (exit
#: criterion). `_text()` joins every descendant label's own text with " ".
_GOLDEN_PREVIEW_TEXT = (
    "Resolved — record R-2026-0031, all 13 features "
    "≈ 1 842 tokens "
    "You extract structured facts. --- narrative --- Car left the road, weather clear."
)


async def test_prompt_preview_panel_renders_the_header_and_the_token_estimate(user):
    """The header assembles "record " + the read model's own key + "all N
    features" — `record_key` itself is a raw record identifier (e.g. an
    `unfall_uid`), not a pre-formatted sentence (`services/prompt_service.py`).
    The token figure is `≈ N tokens`, an estimate and labelled as one (C6),
    and the body sits in a well capped at the design's 210px."""
    page("/t/preview/one", lambda: prompt_preview_panel(resolved=_RESOLVED))
    await user.open("/t/preview/one")

    (title,) = user.find(marker="prompt-preview-title").elements
    assert str(title.text) == "Resolved — record R-2026-0031, all 13 features"
    (tokens,) = user.find(marker="prompt-preview-tokens").elements
    assert str(tokens.text) == "≈ 1 842 tokens"
    (well,) = user.find(marker="scroll-well").elements
    assert well._style["max-height"] == "210px"
    assert well._style["overflow-y"] == "auto"
    await user.should_see("Car left the road")


async def test_prompt_preview_panel_renders_identically_from_both_entry_points(user):
    """Exit criterion: Prompts' and Evaluation's calls into this component
    must render byte-identical output for the same `ResolvedPromptView`,
    asserted against one golden string — not merely "look similar"."""
    page(
        "/t/preview/both",
        lambda: [
            prompt_preview_panel(resolved=_RESOLVED),  # Prompts' "Preview with record 1"
            prompt_preview_panel(resolved=_RESOLVED),  # Evaluation's "Preview prompt"
        ],
    )
    await user.open("/t/preview/both")

    panels = _ordered(user.find(marker="prompt-preview"))
    assert len(panels) == 2
    rendered = [_text(p) for p in panels]
    assert rendered[0] == rendered[1] == _GOLDEN_PREVIEW_TEXT


# --- ollama_settings_dialog (L3) ----------------------------------------------
#
# plan-phase-3.md Q4 / sw-design.md §15.8: an undesigned dialog built to this
# plan's own design. M17 specified three controls — endpoint, timeout, "refresh
# model list". Two more were added once the dialog met the job of actually
# *configuring* Ollama (P3-D19): a loopback check on the endpoint as you type
# it, and a connection test that names why the endpoint did not answer. The
# assertions below are on codes and structure, never on the sentences — those
# live in `PROBE_WORDS` and must be rewritable without touching this file.

_CONNECTION = ConnectionView(
    endpoint="http://127.0.0.1:11434/v1", status=EndpointStatus.REACHABLE, timeout_s=120
)

_OFF_HOST = "http://192.168.1.5:11434/v1"


def _probe(
    code: ProbeCode = ProbeCode.OK,
    *,
    detail: str | None = None,
    latency_ms: int | None = None,
    model_count: int | None = None,
    http_status: int | None = None,
    probe_timeout_s: int = 5,
) -> ConnectionProbeView:
    return ConnectionProbeView(
        endpoint="http://127.0.0.1:11434/v1",
        code=code,
        detail=detail,
        latency_ms=latency_ms,
        model_count=model_count,
        http_status=http_status,
        probe_timeout_s=probe_timeout_s,
    )


async def _ok_probe(endpoint: str, timeout_s: int) -> ConnectionProbeView:
    """The default `on_test` for the tests that are not about testing."""
    return _probe(latency_ms=12, model_count=3)


def _card_elements(user: User) -> list[ui.element]:
    return [e for e in _all(user) if e.tag == "section" and e._props.get("data-testid") == "card"]


async def test_ollama_settings_dialog_has_exactly_the_five_controls(user):
    """Endpoint, timeout, test, refresh, save — and only those five.

    Still no VRAM control: that judgement needs the GPU probe and is rendered
    on the Models card, not in here (sw-design.md §15.6). The count is asserted
    because "three controls, and only three" was a real decision and its
    replacement should be just as deliberate."""
    page(
        "/t/ollama/controls",
        lambda: ollama_settings_dialog(
            settings=_CONNECTION,
            on_save=lambda *_: None,
            on_refresh=lambda: None,
            on_test=_ok_probe,
        ),
    )
    await user.open("/t/ollama/controls")

    assert len(user.find(marker="ollama-endpoint").elements) == 1
    assert len(user.find(marker="ollama-timeout").elements) == 1
    assert len(user.find(marker="ollama-refresh").elements) == 1
    assert len(user.find(marker="ollama-test").elements) == 1
    assert len(user.find(marker="ollama-save").elements) == 1
    (endpoint_input,) = user.find(marker="ollama-endpoint").elements
    (timeout_input,) = user.find(marker="ollama-timeout").elements
    assert endpoint_input._props["value"] == "http://127.0.0.1:11434/v1"
    assert timeout_input._props["value"] == "120"


async def test_ollama_settings_dialog_save_emits_the_edited_endpoint_and_timeout(user):
    """Exit criterion: save emits the (possibly edited) endpoint and
    timeout, and closes the dialog."""
    saved: list[tuple[str, int]] = []
    dialogs: list[ui.dialog] = []

    def build() -> None:
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=_CONNECTION,
                    on_save=lambda endpoint, timeout_s: saved.append((endpoint, timeout_s)),
                    on_refresh=lambda: None,
                    on_test=_ok_probe,
                ),
            )
        )

    page("/t/ollama/save", build)
    await user.open("/t/ollama/save")
    dialogs[0].open()

    user.find(marker="ollama-endpoint").trigger("change", args="http://127.0.0.1:9999/v1")
    user.find(marker="ollama-timeout").trigger("change", args="45")
    user.find(marker="ollama-save").click()

    assert saved == [("http://127.0.0.1:9999/v1", 45)]
    assert dialogs[0].value is False, "save closes the dialog"


async def test_ollama_settings_dialog_refresh_reasks_the_catalogue_without_saving(user):
    """ "Refresh model list" and "Save" are two different gestures — refresh
    must not emit `on_save` or close the dialog."""
    saved: list[tuple[str, int]] = []
    refreshed: list[bool] = []
    dialogs: list[ui.dialog] = []

    def build() -> None:
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=_CONNECTION,
                    on_save=lambda endpoint, timeout_s: saved.append((endpoint, timeout_s)),
                    on_refresh=lambda: refreshed.append(True),
                    on_test=_ok_probe,
                ),
            )
        )

    page("/t/ollama/refresh", build)
    await user.open("/t/ollama/refresh")
    dialogs[0].open()

    user.find(marker="ollama-refresh").click()

    assert refreshed == [True]
    assert saved == []
    assert dialogs[0].value is True, "refresh must not close the dialog"


async def test_ollama_settings_dialog_state_is_scoped_to_its_own_instance(user):
    """Do-NOT #8: no module global. Two dialogs built in the same process
    must not leak an edit from one into the other's `on_save`."""
    saved_a: list[tuple[str, int]] = []
    saved_b: list[tuple[str, int]] = []
    dialogs: list[ui.dialog] = []

    def build() -> None:
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=ConnectionView(
                        endpoint="http://127.0.0.1:11434/v1",
                        status=EndpointStatus.REACHABLE,
                        timeout_s=120,
                    ),
                    on_save=lambda endpoint, timeout_s: saved_a.append((endpoint, timeout_s)),
                    on_refresh=lambda: None,
                    on_test=_ok_probe,
                ),
            )
        )
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=ConnectionView(
                        endpoint="http://127.0.0.1:22222/v1",
                        status=EndpointStatus.REACHABLE,
                        timeout_s=60,
                    ),
                    on_save=lambda endpoint, timeout_s: saved_b.append((endpoint, timeout_s)),
                    on_refresh=lambda: None,
                    on_test=_ok_probe,
                ),
            )
        )

    page("/t/ollama/scoped", build)
    await user.open("/t/ollama/scoped")
    for dialog in dialogs:
        dialog.open()

    # `.trigger`/`.click` act on every matched element, so this edits both
    # dialogs' endpoint fields identically — that is fine: `.click()` always
    # picks the lowest-id (first-built) match deterministically, so only
    # dialog A's `on_save` can possibly fire, which is exactly what this
    # test needs to tell the two instances apart.
    user.find(marker="ollama-endpoint").trigger("change", args="http://127.0.0.1:9999/v1")
    user.find(marker="ollama-save").click()

    assert saved_a == [("http://127.0.0.1:9999/v1", 120)]
    assert saved_b == [], "the second dialog's on_save must never fire from the first's edit"


async def test_ollama_settings_dialog_opens_without_clipping_at_1024px(user):
    """Phase 2's dialog-clipping fix (`dialog_card`'s docstring): the direct
    child of `.q-dialog__inner` carries its own `max-width:96vw` and the card
    derives its cap from that wrapper rather than an independent guess, which
    is what stopped a wide card from clipping under Quasar's hardcoded
    560px rule. `tests/ui` has no real viewport to resize to 1024px and
    measure (that belongs to a later `tests/e2e` addition, once a view wires
    the gear button that opens this dialog) — the structural check available
    here is that this dialog is built on that fix, and that its own card is
    comfortably narrower than 1024px's 96vw allowance (983px)."""
    page(
        "/t/ollama/clip",
        lambda: ollama_settings_dialog(
            settings=_CONNECTION,
            on_save=lambda *_: None,
            on_refresh=lambda: None,
            on_test=_ok_probe,
        ),
    )
    await user.open("/t/ollama/clip")

    wrapper = next(e for e in _all(user) if e.tag == "div" and e._style.get("max-width") == "96vw")
    assert wrapper is not None
    (card_el,) = _card_elements(user)
    assert card_el._style["max-width"] == "100%"
    width_px = int(str(card_el._style["width"]).removesuffix("px"))
    assert width_px < 1024 * 0.96


# --- ollama_settings_dialog: the loopback gate and the connection test --------
#
# The two additions of P3-D19. Both are about the same rule reached two ways:
# locally, per keystroke, to disable Save, and through the service, on the
# button, to say why the endpoint did not answer.


async def test_a_non_loopback_endpoint_disables_save_and_says_why(user):
    """N1 at the point of entry.

    `require_loopback` has always refused a LAN address — at *startup*, long
    after the analyst typed it. The dialog applies the identical rule
    (`domain.llm.is_loopback_url`, which is why the rule moved down out of
    `infra/`) while the value is still editable.
    """
    saved: list[tuple[str, int]] = []
    dialogs: list[ui.dialog] = []

    def build() -> None:
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=_CONNECTION,
                    on_save=lambda endpoint, timeout_s: saved.append((endpoint, timeout_s)),
                    on_refresh=lambda: None,
                    on_test=_ok_probe,
                ),
            )
        )

    page("/t/ollama/invalid", build)
    await user.open("/t/ollama/invalid")
    dialogs[0].open()

    user.find(marker="ollama-endpoint").trigger("change", args=_OFF_HOST)

    (save_button,) = user.find(marker="ollama-save").elements
    assert "disabled" in save_button._props
    (error,) = user.find(marker="ollama-endpoint-error").elements
    assert error.text == ENDPOINT_INVALID_MESSAGE
    # Pressing it anyway emits nothing: a disabled button is a UI state, not
    # a guarantee, so the handler checks too.
    user.find(marker="ollama-save").click()
    assert saved == []
    assert dialogs[0].value is True, "a refused endpoint must not close the dialog"


async def test_a_loopback_endpoint_re_enables_save(user):
    """The gate lets go again — an analyst who mistypes and corrects it must
    not have to reopen the dialog."""
    saved: list[tuple[str, int]] = []
    dialogs: list[ui.dialog] = []

    def build() -> None:
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=_CONNECTION,
                    on_save=lambda endpoint, timeout_s: saved.append((endpoint, timeout_s)),
                    on_refresh=lambda: None,
                    on_test=_ok_probe,
                ),
            )
        )

    page("/t/ollama/revalid", build)
    await user.open("/t/ollama/revalid")
    dialogs[0].open()

    user.find(marker="ollama-endpoint").trigger("change", args=_OFF_HOST)
    user.find(marker="ollama-endpoint").trigger("change", args="http://localhost:11434/v1")

    (save_button,) = user.find(marker="ollama-save").elements
    assert "disabled" not in save_button._props
    # `user.find()` raises when nothing matches and skips invisible elements,
    # so "hidden" is asserted over the full tree instead.
    assert _marked(user, "ollama-endpoint-error").visible is False
    user.find(marker="ollama-save").click()
    assert saved == [("http://localhost:11434/v1", 120)]


async def test_the_reason_is_hidden_until_the_endpoint_is_actually_invalid(user):
    """A dialog opened on a healthy endpoint shows no error. (The converse —
    opening on an already-broken configured endpoint — is why `_sync_validity`
    runs once at build time rather than only on `change`.)"""
    page(
        "/t/ollama/clean",
        lambda: ollama_settings_dialog(
            settings=_CONNECTION,
            on_save=lambda *_: None,
            on_refresh=lambda: None,
            on_test=_ok_probe,
        ),
    )
    await user.open("/t/ollama/clean")

    # `user.find()` raises when nothing matches and skips invisible elements,
    # so "hidden" is asserted over the full tree instead.
    assert _marked(user, "ollama-endpoint-error").visible is False


async def test_a_dialog_opened_on_a_bad_configured_endpoint_says_so_immediately(user):
    """`RA2_LLM_BASE_URL` cannot actually hold a non-loopback value — the app
    would not have started — but the dialog must not depend on that to be
    correct, and the analyst should not have to touch the field to find out."""
    page(
        "/t/ollama/prebad",
        lambda: ollama_settings_dialog(
            settings=ConnectionView(
                endpoint=_OFF_HOST, status=EndpointStatus.REFUSED_NOT_LOOPBACK, timeout_s=120
            ),
            on_save=lambda *_: None,
            on_refresh=lambda: None,
            on_test=_ok_probe,
        ),
    )
    await user.open("/t/ollama/prebad")

    (error,) = user.find(marker="ollama-endpoint-error").elements
    assert error.text == ENDPOINT_INVALID_MESSAGE
    (save_button,) = user.find(marker="ollama-save").elements
    assert "disabled" in save_button._props


async def test_test_connection_probes_the_typed_endpoint_not_the_configured_one(user):
    """The whole point of the button. Probing `settings.endpoint` would re-ask
    a question the line outside the dialog already answers."""
    probed: list[tuple[str, int]] = []
    dialogs: list[ui.dialog] = []

    async def on_test(endpoint: str, timeout_s: int) -> ConnectionProbeView:
        probed.append((endpoint, timeout_s))
        return _probe(latency_ms=12, model_count=3)

    def build() -> None:
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=_CONNECTION,
                    on_save=lambda *_: None,
                    on_refresh=lambda: None,
                    on_test=on_test,
                ),
            )
        )

    page("/t/ollama/test-typed", build)
    await user.open("/t/ollama/test-typed")
    dialogs[0].open()

    user.find(marker="ollama-endpoint").trigger("change", args="http://127.0.0.1:9999/v1")
    user.find(marker="ollama-timeout").trigger("change", args="30")
    user.find(marker="ollama-test").click()
    await user.should_see(marker="ollama-test-sentence")

    assert probed == [("http://127.0.0.1:9999/v1", 30)]
    assert dialogs[0].value is True, "test must not close the dialog"


async def test_test_connection_renders_the_sentence_and_the_raw_cause(user):
    """Both lines. The sentence is what an analyst acts on; the detail is what
    they paste into a bug report, and neither substitutes for the other."""
    dialogs: list[ui.dialog] = []

    async def on_test(endpoint: str, timeout_s: int) -> ConnectionProbeView:
        return _probe(ProbeCode.CONNECTION_REFUSED, detail="[Errno 111] Connection refused")

    def build() -> None:
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=_CONNECTION,
                    on_save=lambda *_: None,
                    on_refresh=lambda: None,
                    on_test=on_test,
                ),
            )
        )

    page("/t/ollama/test-refused", build)
    await user.open("/t/ollama/test-refused")
    dialogs[0].open()
    user.find(marker="ollama-test").click()
    await user.should_see(marker="ollama-test-sentence")

    (sentence,) = user.find(marker="ollama-test-sentence").elements
    (detail,) = user.find(marker="ollama-test-detail").elements
    # Asserted through `PROBE_WORDS`, not against a literal: the wording lives
    # in that one table and must be rewritable without touching this test
    # (CLAUDE.md: findings, not prose).
    assert sentence.text == PROBE_WORDS[ProbeCode.CONNECTION_REFUSED]
    assert detail.text == "[Errno 111] Connection refused"
    assert "danger" in sentence._classes


async def test_a_successful_test_reads_as_success(user):
    dialogs: list[ui.dialog] = []

    async def on_test(endpoint: str, timeout_s: int) -> ConnectionProbeView:
        return _probe(latency_ms=38, model_count=4)

    def build() -> None:
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=_CONNECTION,
                    on_save=lambda *_: None,
                    on_refresh=lambda: None,
                    on_test=on_test,
                ),
            )
        )

    page("/t/ollama/test-ok", build)
    await user.open("/t/ollama/test-ok")
    dialogs[0].open()
    user.find(marker="ollama-test").click()
    await user.should_see(marker="ollama-test-sentence")

    (sentence,) = user.find(marker="ollama-test-sentence").elements
    assert "ok" in sentence._classes
    assert "4 models" in sentence.text and "38" in sentence.text
    assert _find_marked(user, "ollama-test-detail") is None


async def test_test_connection_works_on_an_endpoint_save_refuses(user):
    """The Test button stays enabled for a non-loopback host.

    Disabling it would withhold the clearest explanation the dialog can give.
    Nothing is dialled — the service refuses before opening a socket — so
    what reaches the analyst is the refusal itself, with its reason.
    """
    probed: list[str] = []
    dialogs: list[ui.dialog] = []

    async def on_test(endpoint: str, timeout_s: int) -> ConnectionProbeView:
        probed.append(endpoint)
        return _probe(ProbeCode.REFUSED_NOT_LOOPBACK)

    def build() -> None:
        dialogs.append(
            cast(
                ui.dialog,
                ollama_settings_dialog(
                    settings=_CONNECTION,
                    on_save=lambda *_: None,
                    on_refresh=lambda: None,
                    on_test=on_test,
                ),
            )
        )

    page("/t/ollama/test-refused-host", build)
    await user.open("/t/ollama/test-refused-host")
    dialogs[0].open()

    user.find(marker="ollama-endpoint").trigger("change", args=_OFF_HOST)
    user.find(marker="ollama-test").click()
    await user.should_see(marker="ollama-test-sentence")

    assert probed == [_OFF_HOST]
    (sentence,) = user.find(marker="ollama-test-sentence").elements
    assert sentence.text == PROBE_WORDS[ProbeCode.REFUSED_NOT_LOOPBACK]


async def test_no_verdict_is_shown_before_the_button_is_pressed(user):
    """The dialog opens with no result rather than a stale one: the last
    answer was about whatever URL was in the field at the time."""
    page(
        "/t/ollama/test-pristine",
        lambda: ollama_settings_dialog(
            settings=_CONNECTION,
            on_save=lambda *_: None,
            on_refresh=lambda: None,
            on_test=_ok_probe,
        ),
    )
    await user.open("/t/ollama/test-pristine")

    assert _marked(user, "ollama-test-result").visible is False
    assert _find_marked(user, "ollama-test-sentence") is None


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, "1 model,"), (3, "3 models,"), (0, "no models,"), (None, "unknown number")],
)
def test_the_success_sentence_counts_models_grammatically(count, expected):
    assert expected in probe_sentence(_probe(ProbeCode.OK, model_count=count, latency_ms=15))


def test_every_probe_code_has_a_sentence():
    """A code with no wording would reach an analyst as a bare identifier.

    `probe_sentence` falls back rather than raising, so this is the check that
    the fallback never actually fires in production.
    """
    assert set(PROBE_WORDS) == set(ProbeCode)


def test_probe_sentences_fill_in_their_numbers():
    """The templates carry `{}` placeholders; nothing may reach the screen
    with a brace still in it."""
    for code in ProbeCode:
        text = probe_sentence(
            _probe(code, latency_ms=12, model_count=3, http_status=404, probe_timeout_s=5)
        )
        assert "{" not in text and "}" not in text, code


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


def _find_marked(user: User, marker: str) -> ui.element | None:
    """The one element carrying `marker`, **visible or not**, or `None`.

    `user.find()` raises when nothing matches and skips invisible elements, so
    it cannot express "this is present but hidden" or "this was never built" —
    both of which are exactly what a dialog's error line and its empty result
    slot need asserted. This walks the client's own element registry instead.
    """
    client = user.client
    assert client is not None, "no page is open"
    found = [e for e in client.elements.values() if marker in e._markers]
    assert len(found) <= 1, f"{marker} matched {len(found)} elements"
    return found[0] if found else None


def _marked(user: User, marker: str) -> ui.element:
    element = _find_marked(user, marker)
    assert element is not None, f"no element marked {marker}"
    return element


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


# --- Results statistical cells (phase 4, S5) --------------------------------


def _cross_tab_text(user: User) -> dict[tuple[str, str], str]:
    """`(outcome, flag) -> rendered number`, read off the DOM."""
    return {
        (element.props["data-outcome"], element.props["data-flag"]): cast(
            Label, element.default_slot.children[0]
        ).text
        for element in user.find(marker="cross-tab-cell").elements
    }


_CROSS_TAB = CrossTabView(
    feature_key="weather_code",
    model_id="llama3.1:8b",
    hit_present=2190,
    hit_absent=114,
    wrong_present=301,
    wrong_absent=62,
    missing_present=94,
    missing_absent=1286,
)


async def test_the_tie_marker_distinguishes_its_three_states_by_shape(user: User) -> None:
    """**Q6 / §15 F9, asserted structurally so it cannot be reverted into a
    colour.**

    The design README defines a blue `--accent` for this family; `theme.py`
    already records that the prototypes' blue is "left over from an earlier
    pass", under "colour carries **only** state and severity". The three states
    are three shapes — filled, outlined, empty — which read without hue, on a
    greyscale print, and for a colour-blind reader.

    This test reads classes and `data-mark`, never a colour. A change that
    swapped the shapes for three hues would pass a screenshot and fail here.
    """
    page(
        "/t/mk/all",
        lambda: [tie_marker(mark) for mark in (TieMark.BEST, TieMark.TIED, TieMark.NONE)],
    )
    await user.open("/t/mk/all")
    markers = _ordered(user.find(marker="tie-marker"))
    assert [m.props["data-mark"] for m in markers] == ["best", "tied", "none"]
    assert "mk-best" in markers[0].classes
    assert "mk-tied" in markers[1].classes
    assert "mk-none" in markers[2].classes


async def test_every_tie_marker_state_is_named_for_a_screen_reader(user: User) -> None:
    """The marker is the only thing separating a best cell from a tied one. A
    reader that saw just the numbers would find a table with no winner."""
    page("/t/mk/aria", lambda: [tie_marker(mark) for mark in TieMark])
    await user.open("/t/mk/aria")
    labels = {m.props["aria-label"] for m in user.find(marker="tie-marker").elements}
    assert labels == {"best", "statistically tied with best", "neither best nor tied"}


async def test_a_metric_cell_renders_the_value_over_its_interval(user: User) -> None:
    """§11.4: "every metric is rendered with its **n** and its interval"."""
    cell = MetricCell(value=0.842, ci_low=0.824, ci_high=0.858, n=1842, mark=TieMark.BEST)
    page("/t/cell/metric", lambda: metric_cell(cell))
    await user.open("/t/cell/metric")
    await user.should_see("0.842")
    await user.should_see(".824–.858")


async def test_a_metric_cell_that_leads_nothing_is_dimmed(user: User) -> None:
    """Design README §1a: "a model that is neither best nor tied is
    `color:--ink2`" — the eye lands on what leads."""
    page(
        "/t/cell/dim",
        lambda: [
            metric_cell(MetricCell(value=0.9, ci_low=0.88, ci_high=0.92, n=500, mark=m))
            for m in (TieMark.BEST, TieMark.NONE)
        ],
    )
    await user.open("/t/cell/dim")
    values = _ordered(user.find(marker="metric-cell"))
    assert "dim" not in values[0].default_slot.children[0].classes
    assert "dim" in values[1].default_slot.children[0].classes


async def test_a_suppressed_cell_renders_the_notice_and_never_a_number(user: User) -> None:
    """mvp-spec.md §11.4: "cells with n below the minimum count render as
    'insufficient data', **never as a number**".

    `metric_cell` takes the `Cell` union rather than `MetricCell`, so there is
    no call site that can render a cell without having decided what to do
    about suppression.
    """
    page("/t/cell/suppressed", lambda: metric_cell(SuppressedCell(n=17, floor=20)))
    await user.open("/t/cell/suppressed")
    (chip,) = user.find(marker="insufficient").elements
    assert chip.props["data-n"] == "17"
    assert chip.props["data-floor"] == "20"
    # There is no metric cell on this page at all — `SuppressedCell` has no
    # `value` field, so the number does not exist to be rendered.
    with pytest.raises(AssertionError):
        user.find(marker="metric-cell")


async def test_the_suppression_notice_states_both_numbers_from_the_data(user: User) -> None:
    """The floor is **per evaluation** (`SD19`), so a literal `20` in the copy
    would be wrong the first time someone changed it."""
    page("/t/cell/floor", lambda: insufficient_cell(n=12, floor=30))
    await user.open("/t/cell/floor")
    await user.should_see("12 labelled cases, below the minimum of 30")


async def test_the_contingency_table_renders_the_designs_cross_tab(user: User) -> None:
    """`design/results/README.md` §2d's fixture, cell for cell."""
    page("/t/xtab", lambda: contingency_table(view=_CROSS_TAB))
    await user.open("/t/xtab")
    cells = _cross_tab_text(user)
    assert cells[("hit", "present")] == "2 190"
    assert cells[("hit", "absent")] == "114"
    assert cells[("missing", "absent")] == "1 286"


async def test_the_self_contradiction_cell_is_styled_as_the_finding(user: User) -> None:
    """ "That cell is the whole point of the card — style it as the finding."

    `hit x present = false`: the model said the text does not contain the
    feature and then extracted the record's exact value from it.
    """
    page("/t/xtab/finding", lambda: contingency_table(view=_CROSS_TAB))
    await user.open("/t/xtab/finding")
    findings = [e for e in user.find(marker="cross-tab-cell").elements if "finding" in e.classes]
    assert len(findings) == 1
    assert findings[0].props["data-outcome"] == "hit"
    assert findings[0].props["data-flag"] == "absent"


async def test_the_cross_tab_totals_are_the_sums_of_its_own_cells(user: User) -> None:
    """A total that disagreed with the cells above it would be a second source
    of truth in a nine-cell table."""
    page("/t/xtab/totals", lambda: contingency_table(view=_CROSS_TAB))
    await user.open("/t/xtab/totals")
    cells = _cross_tab_text(user)
    assert cells[("total", "total")] == "4 047"
    assert cells[("hit", "total")] == "2 304"


# --- Phase 5 (W2): the two additions the Mismatches view needs --------------
#
# sw-design.md §17, plan-phase-5.md §3.2. That section is a **boundary**, not
# a starting point (R2): the screen is assembled from components, tokens and
# widths that already exist. What did not exist was a style, twice — the
# trailing clear of a three-way tag control, and a wrapped evidence-span cell.
# No new component, no new colour, no second table scale.

#: mvp-spec.md §12's three, in the words the view renders (C4). These tests
#: assert on structure, so what the strings *say* does not matter here — what
#: matters is that there are three of them and a clear beside.
TAG_OPTIONS = ["Hallucination", "Record error", "Unclear"]


async def test_the_tag_control_is_three_values_and_a_clear_that_is_not_a_fourth(user):
    """`Q2`/`Q5`: three segments plus a clear, and the clear must not read as a
    fourth tag anywhere — not in the DOM, not in the accessibility tree.

    "How many values does this control have" has to have the same answer as
    `len(MismatchTag)`, or the screen and the tally disagree about what an
    analyst is able to say.
    """

    def build() -> None:
        segmented_control(
            options=TAG_OPTIONS,
            value="Hallucination",
            label="Tag",
            on_change=lambda _: None,
            on_clear=lambda: None,
        )

    page("/t/seg3", build)
    await user.open("/t/seg3")

    values = _ordered(user.find(marker="seg-option"))
    assert len(values) == 3
    assert [e._props["aria-pressed"] for e in values] == ["true", "false", "false"]
    assert [("on" in e.classes) for e in values] == [True, False, False]

    (clear,) = user.find(marker="seg-clear").elements
    #: An action, not a value: no `aria-pressed`, and not a `seg-option`.
    assert "aria-pressed" not in clear._props
    assert clear._props["data-testid"] == "seg-clear"
    assert clear._props["aria-label"] == "Clear"


async def test_every_tag_value_can_be_chosen_and_reports_itself(user):
    """All three, one click each — the vocabulary is only closed *on the
    screen* if every member of it is reachable from the screen."""
    seen: list[str] = []

    def build() -> None:
        segmented_control(options=TAG_OPTIONS, value=None, label="Tag", on_change=seen.append)

    page("/t/seg3/pick", build)
    await user.open("/t/seg3/pick")

    user.find(marker="seg-hallucination").click()
    user.find(marker="seg-record-error").click()
    user.find(marker="seg-unclear").click()
    assert seen == ["Hallucination", "Record error", "Unclear"]


async def test_an_untagged_row_renders_as_a_real_cleared_state(user):
    """`value=None` is **the normal state of a row nobody has reviewed**, not a
    missing value.

    Every segment reports `aria-pressed="false"`, which is what a screen reader
    should hear — and none carries `on`, so nothing on screen suggests a
    judgement that was never made.
    """

    def build() -> None:
        segmented_control(options=TAG_OPTIONS, value=None, label="Tag", on_clear=lambda: None)

    page("/t/seg3/none", build)
    await user.open("/t/seg3/none")

    values = _ordered(user.find(marker="seg-option"))
    assert [e._props["aria-pressed"] for e in values] == ["false", "false", "false"]
    assert not [e for e in values if "on" in e.classes]


async def test_the_clear_is_disabled_rather_than_hidden_when_there_is_nothing_to_clear(user):
    """The `pagination_row` rule, one control over: disabled, not hidden.

    A clear that appeared and vanished would change the control's width as an
    analyst worked down the list, so the row under the cursor would move — and
    tagging happens inline, while scanning (`Q2`).
    """
    cleared: list[str] = []

    def build() -> None:
        segmented_control(
            options=TAG_OPTIONS, value=None, label="Tag", on_clear=lambda: cleared.append("x")
        )

    page("/t/seg3/clear-off", build)
    await user.open("/t/seg3/clear-off")

    (clear,) = user.find(marker="seg-clear").elements
    assert "disabled" in clear.classes
    assert "disabled" in clear._props
    #: And it does nothing: a cleared row has no tag and no `tagged_at`, so a
    #: second clear would be a write with nothing to write.
    user.find(marker="seg-clear").click()
    assert cleared == []


async def test_clearing_a_tagged_row_reports_once(user):
    """`Q4`: a judgement made on the wrong row must be correctable, or the
    first mis-click is permanent in the one table a human writes to."""
    cleared: list[str] = []

    def build() -> None:
        segmented_control(
            options=TAG_OPTIONS, value="Unclear", label="Tag", on_clear=lambda: cleared.append("x")
        )

    page("/t/seg3/clear-on", build)
    await user.open("/t/seg3/clear-on")

    (clear,) = user.find(marker="seg-clear").elements
    assert "disabled" not in clear.classes
    assert "disabled" not in clear._props
    user.find(marker="seg-clear").click()
    assert cleared == ["x"]


def test_the_two_segment_control_keeps_its_phase_2_defaults():
    """Phase 2's `Labelled | Exploratory` is the same call it always was.

    `value` widened to `str | None` and `on_clear` defaults to `None`, so the
    Features edit zone renders no clear and gains no segment. Asserted on the
    signature as well as on the rendering below, because a *default* that
    changed would be a silent edit to another phase's screen.
    """
    import inspect

    parameters = inspect.signature(segmented_control).parameters
    assert parameters["on_clear"].default is None
    assert parameters["value"].default is inspect.Parameter.empty
    assert parameters["clear_label"].default == "Clear"


async def test_the_features_kind_field_still_renders_two_values_and_no_clear(user):
    """The regression the signature test cannot see: what a caller that passes
    neither `on_clear` nor `None` actually draws."""

    def build() -> None:
        segmented_control(options=["Labelled", "Exploratory"], value="Labelled", label="Kind")

    page("/t/seg2/regression", build)
    await user.open("/t/seg2/regression")

    assert len(user.find(marker="seg-option").elements) == 2
    #: `user.find` raises when nothing matches, so the absence is asserted over
    #: the page rather than through it.
    assert not [e for e in _all(user) if e._props.get("data-testid") == "seg-clear"]


def test_the_evidence_span_cell_wraps_to_three_lines_at_the_existing_table_scale():
    """`Q6`. The span is the one field `mvp-spec.md` §19's criterion 7 names
    explicitly, and it is free text of unbounded length.

    One line would hide the thing the criterion asks for; a hover reveal would
    put it out of reach of a keyboard and a screen reader. Three lines at the
    `.td` scale this family already has — **no second table scale**, which is
    the R2 failure mode this rule sits closest to.
    """
    assert ".td-wrap{" in STYLESHEET
    rule = STYLESHEET.split(".td-wrap{")[1].split("}")[0]
    #: `.td` is `nowrap`; the modifier is what undoes it, so a cell without it
    #: behaves exactly as every other table cell in the app does.
    assert "white-space:nowrap" in STYLESHEET.split(".td{")[1].split("}")[0]
    assert "white-space:normal;" in rule
    assert "-webkit-line-clamp:3;" in rule
    assert "line-clamp:3;" in rule
    #: The clamp is by line count; `max-height` bounds the row wherever the
    #: clamp does not apply. Either way three lines, never four.
    assert "max-height:calc(3 * 1.35em);" in rule
    #: No new font size. If this ever fails, §3.2's boundary has been crossed.
    assert "font-size" not in rule


def test_the_clear_segment_reuses_the_segment_box_and_adds_no_colour():
    """R2, as a test. `.seg-clear` differs from `.seg-btn` in ink only — it
    carries both classes, so the segments keep one height and one border — and
    every colour it names is a token that already existed."""
    rule = STYLESHEET.split(".seg-clear{")[1].split("}")[0]
    assert "background" not in rule
    assert "border" not in rule
    #: Tokens only. A literal colour here would be the fourth colour §3.2
    #: forbids, arriving in the smallest possible increment.
    assert "oklch(" not in rule
    assert "#" not in rule
    assert "var(--ink3)" in rule


#: §3.2's column table, verbatim. The span is the one flexible column.
#: §3.2's column table, as `P5-D5` corrects it: the tag column holds a control
#: that renders 290px wide, so it takes 60px back from the two value columns
#: and the fixed total stays 956px.
MISMATCH_WIDTHS: tuple[tuple[str, str | None], ...] = (
    ("feature", "180px"),
    ("record", "190px"),
    ("record_value", "110px"),
    ("extracted_value", "110px"),
    ("evidence_span", None),
    ("tag", "270px"),
    ("reviewed", "96px"),
)


@dataclass(frozen=True)
class SpanRow:
    feature: str
    span: str


async def test_the_mismatch_table_does_not_wrap_at_1024px(user):
    """`tests/ui` has no real viewport, so this is the layer-3 equivalent of
    `tests/e2e/test_j4_layout.py` — the same substitution
    `test_the_master_detail_split_never_wraps_and_floors_both_panes` makes.

    What *can* be asserted here is the mechanism: the table is
    `table-layout:fixed`, **exactly one column is flexible**, and a long
    evidence span lands in a `.td-wrap` cell. Under fixed layout that is what
    makes a 200-character span wrap inside its own column instead of widening
    the table — so the six fixed widths hold and nothing reflows, at 1024px as
    at 1920.
    """
    row = SpanRow(
        "weather",
        "the driver stated that it had been raining heavily for some time before "
        "the collision, and that the road surface was standing in water across "
        "both lanes where the vehicle left the carriageway",
    )
    columns: tuple[ColumnSpec[SpanRow], ...] = tuple(
        ColumnSpec(
            key=key,
            label=key,
            width=width,
            cell_class="td-wrap" if key == "evidence_span" else "",
            render=(
                (lambda r: ui.label(r.span).mark("span"))
                if key == "evidence_span"
                else (lambda r: ui.label(r.feature))
            ),
        )
        for key, width in MISMATCH_WIDTHS
    )

    page(
        "/t/mismatch/widths",
        lambda: data_table(columns=columns, rows=[row], state=TableState("feature"), wide=True),
    )
    await user.open("/t/mismatch/widths")

    (table,) = user.find(marker="data-table").elements
    assert table._style["table-layout"] == "fixed"

    widths = [
        e._style.get("width") for e in _all(user) if e.tag == "th" and "data-column" in e._props
    ]
    assert widths == [width for _, width in MISMATCH_WIDTHS]
    #: Exactly one flexible column. Two would make the layout ambiguous, and
    #: §3.2 names the span as the one that takes the rest.
    assert widths.count(None) == 1

    wrapped = [e for e in _all(user) if e.tag == "td" and "td-wrap" in e.classes]
    assert len(wrapped) == 1
    await user.should_see("standing in water")

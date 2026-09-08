"""Layer 3 — the component kit.

`DataTable` is the one table component every view is built from
(sw-design.md §8.1.3), so what is asserted here is what every future table
inherits: exact widths, `table-layout: fixed`, a sort affordance that
**reports** rather than sorts, and an indeterminate select-all.

The last group is the architectural one. A component that quietly grew a
`sorted()` call would pass a rendering test and fail these.
"""

from dataclasses import dataclass

import pytest
from nicegui import ui

from ra2.services.readmodels import SortDir
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
from ra2.ui.state import TableState, set_table_state, table_state

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


def page(path, build):
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


def _all(user):
    """Every element on the page, in creation order.

    `UserInteraction.elements` is a **set**, so anything asserting order has to
    sort. NiceGUI hands out ids in creation order, which is document order for
    the structures here.
    """
    return _ordered(user.find(kind=ui.element))


def _ordered(interaction):
    return sorted(interaction.elements, key=lambda e: e.id)


def _text(element) -> str:
    parts = [getattr(child, "text", "") for child in element.descendants()]
    return " ".join(p for p in parts if p).strip()


def _row_names(user) -> list[str]:
    return [e.text for e in _ordered(user.find(marker="filename"))]

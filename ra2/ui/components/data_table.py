# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
"""The **one** `DataTable` every table in the app is built from.

Structured files, text files, corpora and census all render through this
(sw-design.md §8.1.3). It takes `list[ColumnSpec]` and a `TableState` and
emits `table-layout: fixed` with the design's exact widths.

**It has no business logic and never will** (§8.1.1, §8.1.4):

- it does not sort — `rows` arrive in the order the service returned them;
- it does not page — `rows` are the page the service returned;
- it does not filter, count or derive a rate;
- clicking a sortable header calls `on_sort(key)` and nothing else. Deciding
  the next direction is the caller's, because the next direction is part of
  the **service call**, not of the rendering.

`table-layout: fixed` is why the two Import cards can never exceed their card
or wrap: the flexible column absorbs all shrinkage and ellipsizes (README
§1a).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from nicegui import ui
from nicegui.element import Element

from ra2.services.readmodels import SortDir
from ra2.ui.state import TableState

__all__ = ["ASC_GLYPH", "DESC_GLYPH", "UNSORTED_GLYPH", "Align", "ColumnSpec", "data_table"]

type Align = Literal["left", "right", "center"]

#: Text glyphs, exactly as the design files render them (README, Assets).
UNSORTED_GLYPH: Final = "▲▼"
ASC_GLYPH: Final = "▲"
DESC_GLYPH: Final = "▼"


@dataclass(frozen=True, slots=True)
class ColumnSpec[T]:
    """One column. `width` is the design's verbatim value (`"30px"`, `"86px"`)
    or `None` for the single flexible column that takes the rest.

    `render` is handed the row and draws into the cell's slot. It is the only
    place a row's shape is known, which is what keeps this component generic.
    """

    key: str
    label: str = ""
    width: str | None = None
    align: Align = "left"
    sortable: bool = False
    #: Draws the cell's contents. Its return value is ignored — most
    #: renderers are a one-liner that hands back the element they made.
    render: Callable[[T], object] | None = None
    #: Draws the header cell instead of the label — the select-all tick.
    header_render: Callable[[], object] | None = None
    cell_class: str = ""
    cell_style: str = ""
    header_style: str = ""


def _sort_glyph(key: str, state: TableState) -> tuple[str, bool]:
    """(glyph, is-active) for a sortable header. Pure display mapping."""
    if key != state.sort_key:
        return UNSORTED_GLYPH, False
    return (ASC_GLYPH if state.sort_dir is SortDir.ASC else DESC_GLYPH), True


def data_table[T](
    *,
    columns: Sequence[ColumnSpec[T]],
    rows: Sequence[T],
    state: TableState,
    on_sort: Callable[[str], None] | None = None,
    row_class: Callable[[T], str] | None = None,
    row_style: Callable[[T], str] | None = None,
    empty_message: str = "No rows.",
    wide: bool = False,
    testid: str = "data-table",
) -> Element:
    """Render one page of rows.

    :param rows: **already sorted and already paged** by a service.
    :param state: the sort key, direction, page and page size that produced
        them — rendering input, not a source of truth this component owns.
    :param on_sort: called with a column key when a sortable header is
        activated. The caller decides the resulting direction.
    :param wide: 12px cell padding (full-width tables) instead of 9px
        (half-width tables). README §2b.
    """
    table = (
        ui.element("table")
        .props(f'data-testid="{testid}"')
        .mark(testid)
        .style("table-layout:fixed;width:100%;border-collapse:collapse;")
    )
    if wide:
        table.classes("wide")
    with table:
        with ui.element("thead"), ui.element("tr"):
            for column in columns:
                _header_cell(column, state=state, on_sort=on_sort)
        with ui.element("tbody"):
            if not rows:
                _empty_row(columns=columns, message=empty_message)
            for row in rows:
                _body_row(row, columns=columns, row_class=row_class, row_style=row_style)
    return table


def _header_cell[T](
    column: ColumnSpec[T],
    *,
    state: TableState,
    on_sort: Callable[[str], None] | None,
) -> None:
    style = column.header_style
    if column.width is not None:
        style += f"width:{column.width};"
    if column.align != "left":
        style += f"text-align:{column.align};"
    with (
        ui.element("th").classes("th").props(f'scope="col" data-column="{column.key}"').style(style)
    ):
        if column.header_render is not None:
            column.header_render()
        elif column.sortable:
            _sort_header(column, state=state, on_sort=on_sort)
        elif column.label:
            ui.label(column.label)


def _sort_header[T](
    column: ColumnSpec[T],
    *,
    state: TableState,
    on_sort: Callable[[str], None] | None,
) -> None:
    glyph, active = _sort_glyph(column.key, state)
    direction = "none"
    if active:
        direction = "ascending" if state.sort_dir is SortDir.ASC else "descending"
    button = (
        ui.element("button")
        .classes("sorth")
        .props(
            f'type="button" aria-sort="{direction}" '
            f'aria-label="Sort by {column.label}" data-testid="sort-{column.key}"'
        )
        .mark(f"sort-{column.key}")
        .style(
            "background:none;border:none;padding:0;font:inherit;color:inherit;"
            "letter-spacing:inherit;text-transform:inherit;"
        )
    )
    if on_sort is not None:
        button.on("click", lambda _: on_sort(column.key))
    else:
        button.props("disabled")
    with button:
        ui.label(column.label)
        ui.label(glyph).classes("sarr on" if active else "sarr")


def _body_row[T](
    row: T,
    *,
    columns: Sequence[ColumnSpec[T]],
    row_class: Callable[[T], str] | None,
    row_style: Callable[[T], str] | None,
) -> None:
    tr = ui.element("tr")
    if row_class is not None:
        tr.classes(row_class(row))
    if row_style is not None:
        tr.style(row_style(row))
    with tr:
        for column in columns:
            _body_cell(row, column=column)


def _body_cell[T](row: T, *, column: ColumnSpec[T]) -> None:
    style = column.cell_style
    if column.width is not None:
        style += f"width:{column.width};"
    if column.align != "left":
        style += f"text-align:{column.align};"
    with ui.element("td").classes(f"td {column.cell_class}".strip()).style(style):
        if column.render is not None:
            column.render(row)


def _empty_row[T](*, columns: Sequence[ColumnSpec[T]], message: str) -> None:
    """The empty state: a single centred `--ink2` line inside the well.

    Undesigned in the mock; README's "Loading / empty / error" section
    suggests exactly this, so it is what the one table component does.
    """
    with (
        ui.element("tr"),
        ui.element("td")
        .classes("td")
        .props(f'colspan="{len(columns)}"')
        .style("text-align:center;color:var(--ink2);padding:18px 9px;"),
    ):
        ui.label(message)

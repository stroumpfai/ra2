"""Component kit — STUBS owned by A5 (feat/m5-shell). Not frozen.

card · `DataTable` driven by `list[ColumnSpec]` + `TableState` ·
pagination row · tick checkbox with an indeterminate state · chip · `.bar` ·
distribution bar.

`DataTable` takes sort and page as **parameters** and renders. It never
computes a rate (§8.1).
"""

from ra2.ui.components.data_table import Align, ColumnSpec, data_table
from ra2.ui.components.primitives import (
    PAGE_SIZES,
    add_button,
    bar,
    card,
    card_header,
    chip,
    distribution_bar,
    footnote,
    format_count,
    icon_button,
    long_tail_bar,
    pagination_row,
    tick,
)

__all__ = [
    "PAGE_SIZES",
    "Align",
    "ColumnSpec",
    "add_button",
    "bar",
    "card",
    "card_header",
    "chip",
    "data_table",
    "distribution_bar",
    "footnote",
    "format_count",
    "icon_button",
    "long_tail_bar",
    "pagination_row",
    "tick",
]

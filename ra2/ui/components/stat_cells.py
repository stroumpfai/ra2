# STUB — signatures only at M27, bodies owned by S5 (feat/p4-components).
"""The statistical cells all three Results tabs share
(design/results/README.md, "Design Tokens").

Declared at M27 so Wave 1 builds them while Wave 4 is still three waves away —
the same reasoning `progress_card` / `ollama_settings` / `prompt_preview` got
at M17, applied a wave earlier because all three tabs need these.

**The tie marker is shape-coded, not colour-coded** (plan-phase-4.md §1 Q6,
§15 F9). Filled = best, 1.5px outline = statistically tied with best, empty =
neither — on the **neutral** accent. The design README defines a blue
`--accent` for this family; `ui/theme.py` already records that the prototypes'
blue is "a blue left over from an earlier pass", under the standing rule that
colour carries only state and severity and never a decorative hue. Three shapes
read without hue, survive a greyscale print and survive a colour-blind reader,
which is a better answer than a fourth colour anyway.

S5's tests assert the three states **structurally** — fill, border, neither —
so the decision cannot be quietly reverted into a colour.

**Do not introduce a second table scale**: `.th` mono 10px uppercase, `.td`
12.5px, ~8x12px padding, 24x24 pagination buttons, 42-46px card headers,
everywhere.
"""

from typing import Final

from nicegui import ui
from nicegui.element import Element

from ra2.domain.stats import TieMark
from ra2.services.readmodels import Cell, SuppressedCell
from ra2.ui.components.primitives import data_props

__all__ = ["INSUFFICIENT_TEXT", "insufficient_cell", "metric_cell", "tie_marker"]

#: The design's own wording (`design/results/README.md` §1a), with both numbers
#: interpolated. One rendering table, the way `FindingCode` wording works.
INSUFFICIENT_TEXT: Final = (
    "Insufficient data \u2014 {n} labelled cases, below the minimum of {floor}."
)

#: What the marker means, spoken. The shapes carry it visually; this carries it
#: for everyone else.
_LABELS: Final = {
    TieMark.BEST: "best",
    TieMark.TIED: "statistically tied with best",
    TieMark.NONE: "neither best nor tied",
}


def tie_marker(mark: TieMark) -> Element:
    """The 7x7 `.mk`: filled, outlined, or empty. Never a colour swap.

    The three states are three **shapes**, and `data-mark` carries the name so
    a test can assert the distinction structurally rather than by reading a
    colour off a stylesheet (plan-phase-4.md §7, S5).

    `aria-label` is not decoration either: the marker is the only thing
    distinguishing a best cell from a tied one, and a screen reader that saw
    just the number would read a table with no winner.
    """
    return data_props(
        ui.element("span")
        .classes(f"mk mk-{mark.value}")
        .props(f'data-testid="tie-marker" data-mark="{mark.value}"')
        .mark("tie-marker"),
        {"aria-label": _LABELS[mark]},
    )


def metric_cell(cell: Cell) -> Element:
    """A `.val` point estimate over its `.ci` interval line — or, for a
    `SuppressedCell`, `insufficient_cell`.

    Takes the union rather than `MetricCell`, so there is no call site that can
    render a cell without having decided what to do about suppression. The
    interval line is `padding-left:13px` so it aligns under the value.
    """
    if isinstance(cell, SuppressedCell):
        return insufficient_cell(n=cell.n, floor=cell.floor)
    container = ui.element("div").props('data-testid="metric-cell"').mark("metric-cell")
    with container:
        # A cell that is neither best nor tied renders `--ink2` (design README
        # §1a): the eye should land on what leads, and dimming the rest is how
        # a three-model row stays readable without inventing a second colour.
        dim = " dim" if cell.mark is TieMark.NONE else ""
        with ui.element("div").classes(f"val{dim}").style("display:flex;align-items:center;"):
            tie_marker(cell.mark)
            ui.label(f"{cell.value:.3f}")
        interval = ui.element("div").classes("ci").props('data-testid="interval"').mark("interval")
        with interval:
            # The design drops the leading zero on the interval line ("
            # .824-.859") so the two mono lines align on the decimal point.
            ui.label(f"{_bare(cell.ci_low)}\u2013{_bare(cell.ci_high)}")
    return container


def _bare(value: float) -> str:
    """`0.824` -> `.824`, the design's interval rendering. `1.000` keeps its
    digit — there is no `.1000`, and a bound that reached 1 should look like
    it did."""
    text = f"{value:.3f}"
    return text[1:] if text.startswith("0.") else text


def insufficient_cell(*, n: int, floor: int) -> Element:
    """The `.ins` chip: italic mono `--ink3`, stating the count and the rule.

    **Never a number in grey** (mvp-spec.md §11.4). Both numbers are rendered
    from the data — the floor is per-evaluation (`SD19`), so a literal `20`
    here would be wrong the first time someone changes it.
    """
    element = (
        ui.element("span")
        .classes("ins")
        .props(f'data-testid="insufficient" data-n="{n}" data-floor="{floor}"')
        .mark("insufficient")
    )
    with element:
        ui.label(INSUFFICIENT_TEXT.format(n=n, floor=floor))
    return element

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

from nicegui.element import Element

from ra2.domain.stats import TieMark
from ra2.services.readmodels import Cell

__all__ = ["insufficient_cell", "metric_cell", "tie_marker"]


def tie_marker(mark: TieMark) -> Element:
    """The 7x7 `.mk`: filled, outlined, or empty. Never a colour swap."""
    raise NotImplementedError


def metric_cell(cell: Cell) -> Element:
    """A `.val` point estimate over its `.ci` interval line — or, for a
    `SuppressedCell`, `insufficient_cell`.

    Takes the union rather than `MetricCell`, so there is no call site that can
    render a cell without having decided what to do about suppression. The
    interval line is `padding-left:13px` so it aligns under the value.
    """
    raise NotImplementedError


def insufficient_cell(*, n: int, floor: int) -> Element:
    """The `.ins` chip: italic mono `--ink3`, stating the count and the rule.

    **Never a number in grey** (mvp-spec.md §11.4). Both numbers are rendered
    from the data — the floor is per-evaluation (`SD19`), so a literal `20`
    here would be wrong the first time someone changes it.
    """
    raise NotImplementedError

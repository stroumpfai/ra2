# STUB — signature only at M27, body owned by S5 (feat/p4-components).
"""The Goal 1 x presence cross-tab (design/results/README.md §2d).

A 3x3 contingency table with row and column totals in `--ink3`, and **one cell
styled as the finding**: `hit x present = false`. The model said the text does
not contain the feature and then extracted the record's exact value from it.
That is self-contradiction, it is automatically countable, and it is the whole
point of the card — mvp-spec.md §11.2 lists it as one of the three things
Goal 2 can honestly report.

Cases where the model gave no presence flag appear in **no** cell, so the
totals can be less than the feature's `n`. The component renders what the read
model hands it and does not make the rows add up.

**M27 freezes the signature. S5 writes the body.**
"""

from typing import Final

from nicegui import ui
from nicegui.element import Element

from ra2.services.readmodels import CrossTabView

__all__ = ["FINDING_NOTE", "contingency_table"]

#: `design/results/README.md` §2d, verbatim. On this view the copy **is** the
#: design: this sentence is what makes the cell a finding rather than a number.
FINDING_NOTE: Final = (
    "The {count} in hit \u00d7 present = false is self-contradiction: the model said "
    "the text does not contain the feature and then extracted the record's exact "
    "value from it."
)

_OUTCOMES: Final = ("hit", "wrong", "missing")


def contingency_table(*, view: CrossTabView) -> Element:
    cells = {
        "hit": (view.hit_present, view.hit_absent),
        "wrong": (view.wrong_present, view.wrong_absent),
        "missing": (view.missing_present, view.missing_absent),
    }
    container = ui.element("div").props('data-testid="cross-tab"').mark("cross-tab")
    with container, ui.element("table").classes("xtab"):
        with ui.element("thead"), ui.element("tr"):
            for heading in ("", "present = true", "present = false", "total"):
                with ui.element("th").classes("th"):
                    ui.label(heading)
        with ui.element("tbody"):
            for outcome in _OUTCOMES:
                present, absent = cells[outcome]
                with ui.element("tr"):
                    with ui.element("td").classes("td"):
                        ui.label(outcome)
                    _cell(present, outcome=outcome, flag="present")
                    # `hit x present = false` is the card's whole point and is
                    # styled as the finding, not as another number.
                    _cell(absent, outcome=outcome, flag="absent", finding=outcome == "hit")
                    _cell(present + absent, outcome=outcome, flag="total", total=True)
            with ui.element("tr"):
                with ui.element("td").classes("td total"):
                    ui.label("total")
                for flag, value in (
                    ("present", sum(pair[0] for pair in cells.values())),
                    ("absent", sum(pair[1] for pair in cells.values())),
                    ("total", sum(sum(pair) for pair in cells.values())),
                ):
                    _cell(value, outcome="total", flag=flag, total=True)
    return container


def _cell(
    value: int, *, outcome: str, flag: str, finding: bool = False, total: bool = False
) -> None:
    classes = "td"
    if total:
        classes += " total"
    if finding:
        classes += " finding"
    element = (
        ui.element("td")
        .classes(classes)
        .mark("cross-tab-cell")
        .props(
            f'data-testid="cross-tab-cell" data-outcome="{outcome}" data-flag="{flag}"'
            + (' data-finding="true"' if finding else "")
        )
    )
    with element:
        ui.label(f"{value:,}".replace(",", "\u202f"))

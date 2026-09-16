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

from nicegui.element import Element

from ra2.services.readmodels import CrossTabView

__all__ = ["contingency_table"]


def contingency_table(*, view: CrossTabView) -> Element:
    raise NotImplementedError

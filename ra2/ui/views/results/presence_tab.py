# STUB — signature only at M27, body owned by V2 (feat/p4-results-presence).
"""Tab 2 — Goal 2, presence (design/results/README.md §2).

A populated record column says nothing about whether the officer *wrote* it in
the narrative. **That gap is the finding.**

The **scope banner is first, verbatim, and not dismissible**. It states the
deferral to the analyst rather than leaving an absence to be inferred: there is
no gold label for presence, deriving one from Goal 1 correctness would be
circular, so this tab reports rate, cross-tab and flag inconsistency, and
`Presence precision / recall / F1 are deferred` until a human-labelled subset
exists (mvp-spec.md §11.2, `D2`).

The **Goal 1 column is not optional**. Its header text — "never shown apart" —
is part of the design, because "Goal 2 numbers are never published without the
Goal 1 numbers beside them: a weak extractor manufactures false 'missing'
flags". `PresenceRow.goal1` makes dropping it a type error; the test that
asserts it on every row is what makes it a fact.

The cross-tab's **`hit × present = false`** cell is the card's whole point and
is styled as the finding: the model said the text does not contain the feature
and then extracted the record's exact value from it.

The per-record list is **the deliverable** — Goal 2 is consumed as a record
list to act on, not as a rate — with the standard pagination and a CSV export.

**M27 freezes the signature. V2 writes the body.**
"""

from ra2.services.readmodels import PresenceTabView

__all__ = ["render_presence_tab"]


def render_presence_tab(*, view: PresenceTabView) -> None:
    raise NotImplementedError

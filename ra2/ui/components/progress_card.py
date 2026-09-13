# STUB — signature only at M17, body owned by L3 (feat/p3-evaluation-components).
"""The per-model progress card (design/prompt-evaluation/README.md §2).

Declared at M17 (plan-phase-3.md §3.1) so L2 (the Evaluation view) and L3
(this component) build in Wave 4 in parallel: L2 places it and passes a
`RunProgressView`; L2 never reaches inside it.

**No service call inside the component** (Do-NOT #7). It renders all four
states — `queued`, `running`, `done`, `failed` — from the read model alone,
and a `queued` card has a 0 % bar and **no metrics line**, because there is
nothing honest to put in one yet.
"""

from nicegui.element import Element

from ra2.services.readmodels import RunProgressView

__all__ = ["progress_card"]


def progress_card(*, progress: RunProgressView) -> Element:
    """Model tag, a right-aligned status line, a 6px `.bar` at the completion
    percentage, and — for active and finished runs only — the metrics line
    ("parse failures 14 (0.3 %) · median latency 812 ms · 2.1 M prompt tok")."""
    raise NotImplementedError

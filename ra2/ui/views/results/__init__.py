# STUB — bodies owned by V1 (feat/p4-results-extraction, phase 4 Wave 4).
"""Results — one route, three tabs (design/results/README.md).

**The first view in the repo that is a package rather than a module**
(`SD22`). Three tabs of one screen get built by three agents in one wave;
three files is what makes that parallel, and a single `results_view.py` would
serialise the wave for no architectural gain. The route, the shell and the tab
strip live here and belong to V1; the tab bodies belong to V1, V2 and V3.

`design/results/README.md` is explicit that on this view **the copy is the
design**: "the suppression notices, the caveat panels and the tie language are
the product's honesty guarantees, not decoration. Reproduce them verbatim
unless the team changes the statistics." Every one of them is asserted verbatim
at the UI layer.

**The evaluation picker the design does not draw.** The boards render one run
descriptor and no way to choose it. `/results?evaluation=<id>`, with the
standard empty card listing launched evaluations when the parameter is absent
or unknown (plan-phase-4.md C7) — and phase 3's Evaluation view left its
runs-table run-id link pointing at a deliberate placeholder route, which is the
link that lands here.

Three states that must not share a rendering (§16.7): **not scored yet**,
**scoring…** (polled through `GET /api/v1/tasks/{id}` exactly as import and
runs are), and **nothing scoreable** — the last one says *which*, because
"no results" and "not enough data for results" are different facts.

The usual rules: no business logic (Do-NOT #7) — every number, interval, mark
and suppression decision arrives already made from `ResultsService` and
`RankingService`; no module-level mutable state (Do-NOT #8) — the active tab,
the expanded feature, the page and the sort live in `app.storage.client`.

**M27 freezes the signature. V1 writes the body.**
"""

from ra2.services.container import Services

__all__ = ["register"]


def register(services: Services) -> None:
    """Register `/results`. V1 owns this body, the tab strip and tab 1."""
    raise NotImplementedError

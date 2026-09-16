# STUB — bodies owned by V1 (feat/p4-results-extraction, phase 4 Wave 4).
"""Chrome the three Results tabs share (design/results/README.md,
"Shared chrome").

**A fourth module in the package, added by V1.** `plan-phase-4.md` §6 names
`__init__`, `extraction_tab`, `presence_tab` and `ranking_tab`; the descriptor
and the empty card are needed by all four and importing them from `__init__`
makes a cycle, because `__init__` imports the tabs. Shared chrome in its own
module is the answer the cycle was pointing at.

Everything here exists once rather than three times for the reason R11 names:
the three tabs must not drift into three slightly different headers on one
screen.
"""

from typing import Final

from nicegui import ui
from nicegui.element import Element

from ra2.services.readmodels import RunDescriptorView

__all__ = ["DEV_PILL", "RUN_PILL", "empty_card", "run_descriptor"]

#: mvp-spec.md §13: "**Required on every dev-sized result**: the 'smoke test,
#: not a result' marker." On these boards it *replaces* the run pill rather
#: than sitting beside it, so there is no state in which a dev number renders
#: unmarked.
DEV_PILL: Final = "DEV · smoke test, not a result"
RUN_PILL: Final = "Evaluation run"


def run_descriptor(view: RunDescriptorView) -> Element:
    """The identity line every tab carries.

    "**Every tab must carry the corpus + config identity**: a score without its
    config is not a result" (README, Shared chrome).
    """
    row = (
        ui.element("div")
        .props('data-testid="run-descriptor"')
        .mark("run-descriptor")
        .style("margin-left:auto;display:flex;align-items:center;gap:10px;")
    )
    with row:
        summary = (
            ui.element("span")
            .classes("mono")
            .props('data-testid="run-summary"')
            .mark("run-summary")
            .style("font-size:11px;color:var(--ink3);")
        )
        with summary:
            ui.label(
                f"Corpus {view.corpus_label} · {view.record_count} records · "
                f"{view.model_count} models"
            )
        pill = (
            ui.element("span")
            .classes("pill pill-danger" if view.is_dev else "pill pill-ok")
            .props(f'data-testid="run-pill" data-dev="{str(view.is_dev).lower()}"')
            .mark("run-pill")
        )
        with pill:
            ui.label(DEV_PILL if view.is_dev else RUN_PILL)
        chip = ui.element("span").classes("chip").props('data-testid="cfg-chip"').mark("cfg-chip")
        with chip:
            ui.label(f"cfg {view.config_fingerprint[:8]}")
    return row


def empty_card(title: str, body: str) -> Element:
    """The standard empty card — the phase-1/2 pattern, no new idiom.

    §16.7's three states each get their own wording through this one shape, so
    "not scored yet", "scoring…" and "nothing scoreable" look like three
    answers rather than three components.
    """
    card = (
        ui.element("div")
        .classes("card")
        .props('data-testid="results-empty"')
        .mark("results-empty")
        .style("padding:18px;display:flex;flex-direction:column;gap:6px;")
    )
    with card:
        ui.label(title).style("font-size:13.5px;font-weight:600;color:var(--ink);")
        ui.label(body).style("font-size:12.5px;color:var(--ink2);")
    return card

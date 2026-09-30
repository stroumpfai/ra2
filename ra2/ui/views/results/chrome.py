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

from ra2.services.readmodels import ReadingQuality, RunDescriptorView

__all__ = [
    "CONTEXT_NOT_RECORDED",
    "DETERMINISM_CAVEAT",
    "DEV_PILL",
    "QUALITY_TITLE",
    "RUN_PILL",
    "SYNTHETIC_PILL",
    "empty_card",
    "quality_text",
    "run_descriptor",
]

#: mvp-spec.md §13: "**Required on every dev-sized result**: the 'smoke test,
#: not a result' marker." On these boards it *replaces* the run pill rather
#: than sitting beside it, so there is no state in which a dev number renders
#: unmarked.
DEV_PILL: Final = "DEV · smoke test, not a result"
RUN_PILL: Final = "Evaluation run"
#: `SD45`, risk D8. Beside the run pill, not instead of it: a synthetic corpus
#: can be dev-sized or not, and both facts are worth stating. Provenance is
#: the one a screenshot must not lose.
SYNTHETIC_PILL: Final = "SYNTHETIC · invented data, not a result"


#: `SD48`, risks D1 and D2. Both failures score `missing` on every feature of
#: the record, which is indistinguishable from a model that reads badly unless
#: it is shown beside the numbers. Reported, never scored.
QUALITY_TITLE: Final = (
    "Unreadable: answers that were not valid JSON, so every feature of that record "
    "scored missing. At limit: prompts that reached 95 % of the context the model "
    "was loaded with, which the server truncates rather than refuses. Reported, "
    "never scored."
)
#: `SD48`, risk D3: stated once, plainly, wherever a run is presented as
#: reproducible or ranked. The provenance is necessary, not sufficient.
#: Rendered on the Evaluation view's reproducibility card and under the
#: ranking's validity footer, and repeated in `docs/evaluation-report-template.md`.
DETERMINISM_CAVEAT: Final = (
    "Not bit-identical. The same model, prompt, temperature and seed can still change "
    "a few answers between runs: GPU batching, cache reuse and floating-point order "
    "vary, and so do a different Ollama version or context size. A re-run is a check "
    "of these numbers, not a guarantee of them."
)

#: The run did not record the context it was loaded with: *unknown*, never 0.
CONTEXT_NOT_RECORDED: Final = "context not recorded"


def quality_text(quality: ReadingQuality | None) -> str:
    """`unreadable 2.1 % · 3 at limit` — the one wording for `ReadingQuality`.

    An absent figure is said to be absent: no rate without extractions, and no
    at-limit count without a recorded context. Neither is ever printed as 0.
    """
    if quality is None:
        return "—"
    rate = quality.parse_failure_rate
    unreadable = "unreadable —" if rate is None else f"unreadable {100 * rate:.1f} %"
    if quality.at_context_limit is None:
        return f"{unreadable} · {CONTEXT_NOT_RECORDED}"
    return f"{unreadable} · {quality.at_context_limit} at limit"


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
        if view.is_synthetic:
            synthetic = (
                ui.element("span")
                .classes("pill pill-danger")
                .props('data-testid="synthetic-pill"')
                .mark("synthetic-pill")
            )
            with synthetic:
                ui.label(SYNTHETIC_PILL)
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

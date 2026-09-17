# STUB — signature only at M27, body owned by V1 (feat/p4-results-extraction).
"""Tab 1 — Goal 1, extraction (design/results/README.md §1).

The only tab with ground truth, and the input every other tab is read against.

Renders from `ExtractionTabView` alone. Three things it must get right, each
with a named test behind it:

- a **suppressed row** is tinted, its `n` is in `--danger`, and all three model
  cells are replaced by **one** `colspan` notice stating the count and the
  floor. Never a number in grey.
- the **breakdown** expands one feature at a time, and carries the
  "Hallucination is *not* computed — it is a review tag on the mismatch list"
  note **verbatim**. That is `D1` and §11.1's warning, not a caption: it
  renders even though the mismatch list is phase 5, which is how the product
  keeps a promise by not making a claim.
- the **by-language card's footer** is reproduced verbatim: the upstream
  encoding conversion drops characters commoner in French than in German,
  "**This cannot be quantified** — do not read the gap as a model weakness."
  mvp-spec.md §13 requires that standing caveat on the language breakdown.

`.mk` markers are **shape-coded** — filled / outlined / empty — on the neutral
accent (plan-phase-4.md §1 Q6, F9). Do not reach for a hue.

**M27 freezes the signature. V1 writes the body.**
"""

from collections.abc import Awaitable, Callable
from typing import Final
from urllib.parse import urlencode

from nicegui import ui

from ra2.domain.stats import TieMark
from ra2.services.readmodels import ExtractionTabView, FeatureScoreRow
from ra2.ui.components.stat_cells import insufficient_cell, metric_cell, tie_marker
from ra2.ui.views.results.chrome import run_descriptor

__all__ = [
    "ENCODING_CAVEAT",
    "EXPLORATORY_FOOTER",
    "HALLUCINATION_NOTE",
    "SUPPRESSION_RULE",
    "TIE_LEGEND",
    "TIE_LEGEND_NOTE",
    "render_extraction_tab",
]

# --- Verbatim copy. On this view **the copy is the design** (README,
# "Fidelity"): these are the product's honesty guarantees, not decoration, and
# paraphrasing one changes what the product claims. Each is asserted verbatim.

#: mvp-spec.md §11.1's warning and `D1`, in one line. It renders even though
#: the mismatch list it points at is phase 5 — a promise the product keeps by
#: not making a claim.
HALLUCINATION_NOTE: Final = (
    "Hallucination is not computed — it is a review tag on the mismatch list."
)

#: mvp-spec.md §13 requires this standing caveat on the language breakdown.
ENCODING_CAVEAT: Final = (
    "The upstream encoding conversion drops characters that are commoner in "
    "French than in German. French input may simply be noisier. This cannot be "
    "quantified — do not read the gap as a model weakness."
)

#: §11.3: "a freely hallucinating model wins it".
EXPLORATORY_FOOTER: Final = (
    "A discovery rate is a screening signal, not a score. A freely "
    "hallucinating model wins it — never compare these between models."
)

TIE_LEGEND: Final = "● Best · ○ Statistically tied with best — intervals overlap"
TIE_LEGEND_NOTE: Final = "Ties are shown as ties. No strict order is implied."

#: Interpolated from the evaluation, never a literal — the floor is
#: per-evaluation (SD19).
SUPPRESSION_RULE: Final = "cells below n = {floor} suppressed"


def render_extraction_tab(
    *,
    view: ExtractionTabView,
    on_toggle_feature: Callable[[str], Awaitable[None]] | None = None,
) -> None:

    with ui.element("div").style(
        "flex:1;min-height:0;padding:18px 28px 22px;display:flex;flex-direction:column;gap:16px;"
    ):
        card = (
            ui.element("div")
            .classes("card")
            .props('data-testid="extraction-card"')
            .mark("extraction-card")
            .style("display:flex;flex-direction:column;overflow:hidden;")
        )
        with card:
            _header(view)
            _table(view, on_toggle_feature)
            _legend()
        if view.by_language is not None:
            _by_language_card(view)
        if view.exploratory:
            _exploratory_card(view)


def _header(view: ExtractionTabView) -> None:

    with ui.element("div").style(
        "padding:11px 14px;border-bottom:1px solid var(--rule);display:flex;"
        "align-items:center;gap:10px;"
    ):
        ui.label("Per feature × model").classes("lbl").style("font-size:12.5px;font-weight:500;")
        ui.label("F1, Wilson 95% · n = labelled cases").classes("mono").style(
            "font-size:11px;color:var(--ink2);"
        )
        rule = (
            ui.element("span")
            .classes("mono")
            .props('data-testid="suppression-rule"')
            .mark("suppression-rule")
            .style("margin-left:auto;font-size:11px;color:var(--ink3);")
        )
        with rule:
            ui.label(SUPPRESSION_RULE.format(floor=view.descriptor.min_cell_count))
        run_descriptor(view.descriptor)


def _table(
    view: ExtractionTabView, on_toggle_feature: Callable[[str], Awaitable[None]] | None
) -> None:
    """The wide table lives in an `overflow:auto` well with the design's
    `min-width`, so it scrolls rather than bleeding past the card."""
    with (
        ui.element("div").style("overflow:auto;"),
        ui.element("table").style(
            "min-width:738px;width:100%;border-collapse:collapse;table-layout:fixed;"
        ),
    ):
        with ui.element("thead"), ui.element("tr"):
            _th("Feature", "246px")
            _th("n", "78px")
            for model in view.models:
                _th(model.tag, None)
        with ui.element("tbody"):
            for row in view.features.items:
                _row(row, view, on_toggle_feature)


#: Where the "wrong" answers behind this row are reviewed. **The one link
#: plan-phase-5.md §6.1 permits this file**, and the one
#: `design/results/README.md` asks for: "mismatch drill-downs open the
#: Mismatches view filtered to that run × feature". Phase 4 had nowhere to
#: point it; phase 5 built both ends (C2).
MISMATCH_LINK: Final = "review mismatches"
MISMATCHES_PATH: Final = "/mismatches"


def _mismatch_link(row: FeatureScoreRow, view: ExtractionTabView) -> None:
    """The drill-down, carrying `evaluation`, `run` and `feature`.

    **The run is the leftmost model column.** This row spans every model and
    §6.1 permits exactly one link, so it names the first run — which is the one
    the Mismatches view would have picked for itself anyway (`SD26`,
    sw-design.md §17.6), and its Run chip switches from there. A link per model
    cell would be three links in a row that is already a click target, and it
    would be an amendment rather than the declared exception.

    `stop_propagation` because the row itself toggles the breakdown: without
    it, following the link would also expand a panel the analyst is leaving.
    """
    if not view.models:
        return
    query = urlencode(
        {
            "evaluation": str(view.descriptor.evaluation_id),
            "run": view.models[0].model_id,
            "feature": str(row.feature_id),
        }
    )
    link = (
        ui.link(MISMATCH_LINK, f"{MISMATCHES_PATH}?{query}")
        .classes("mono")
        .props('data-testid="mismatch-link"')
        .mark("mismatch-link")
        .style("display:block;font-size:10.5px;color:var(--accent);margin-top:2px;")
    )
    link.on("click", js_handler="(e) => e.stopPropagation()")


def _th(label: str, width: str | None) -> None:
    cell = (
        ui.element("th")
        .classes("th")
        .style(
            "text-align:left;padding:8px 12px;font-size:10px;text-transform:uppercase;"
            "color:var(--ink3);border-bottom:1px solid var(--rule);"
            + (f"width:{width};" if width else "")
        )
    )
    with cell:
        ui.label(label)


def _row(
    row: FeatureScoreRow,
    view: ExtractionTabView,
    on_toggle_feature: Callable[[str], Awaitable[None]] | None,
) -> None:
    tr = (
        ui.element("tr")
        .props(
            f'data-testid="feature-row" data-feature="{row.feature_id}" '
            f'data-suppressed="{str(row.suppressed).lower()}"'
        )
        .mark("feature-row")
        .style("cursor:pointer;" + ("background:oklch(0.985 0.002 260);" if row.suppressed else ""))
    )
    if on_toggle_feature is not None:
        tr.on("click", lambda _e, fid=str(row.feature_id): on_toggle_feature(fid))
    with tr:
        with ui.element("td").classes("td").style("padding:8px 12px;"):
            ui.label(row.name).style("font-weight:500;font-size:12.5px;")
            ui.label(row.source_label).classes("mono").style("font-size:10.5px;color:var(--ink3);")
            _mismatch_link(row, view)
        count = (
            ui.element("td")
            .classes("td mono")
            .style(
                "padding:8px 12px;text-align:right;font-size:12.5px;"
                + ("color:var(--danger);" if row.suppressed else "")
            )
        )
        with count:
            ui.label(str(row.n))
        if row.suppressed:
            # **All model cells replaced by one notice** (README §1a). Never a
            # number in grey, and never one cell per model saying the same
            # thing three times.
            note = (
                ui.element("td")
                .props(f'colspan="{len(view.models)}" data-testid="suppressed-note"')
                .mark("suppressed-note")
                .style("padding:8px 12px;")
            )
            with note:
                insufficient_cell(n=row.n, floor=view.descriptor.min_cell_count)
            return
        for model in view.models:
            cell = row.cells.get(model.model_id)
            with ui.element("td").classes("td").style("padding:8px 12px;"):
                if cell is not None:
                    metric_cell(cell)

    if view.breakdown is not None and view.breakdown.feature_id == row.feature_id:
        _breakdown_row(view)


def _breakdown_row(view: ExtractionTabView) -> None:
    assert view.breakdown is not None
    tr = (
        ui.element("tr")
        .props('data-testid="breakdown-row"')
        .mark("breakdown-row")
        .style("background:var(--accent-soft);")
    )
    with (
        tr,
        ui.element("td").props(f'colspan="{len(view.models) + 2}"').style("padding:12px 14px;"),
    ):
        ui.label(f"Breakdown · {view.breakdown.feature_name}").classes("lbl").style(
            "font-size:12.5px;font-weight:500;"
        )
        note = (
            ui.element("div")
            .props('data-testid="hallucination-note"')
            .mark("hallucination-note")
            .style("font-size:11.5px;color:var(--ink2);margin:4px 0 8px;")
        )
        with note:
            ui.label(HALLUCINATION_NOTE)
        with ui.element("table").style("width:100%;border-collapse:collapse;"):
            with ui.element("thead"), ui.element("tr"):
                for label in ("Model", "Precision", "Recall", "F1", "Hit", "Wrong", "Missing"):
                    _th(label, None)
            with ui.element("tbody"):
                for brow in view.breakdown.rows:
                    with (
                        ui.element("tr")
                        .props('data-testid="breakdown-model"')
                        .mark("breakdown-model")
                    ):
                        for text, colour in (
                            (brow.model_id, "var(--ink)"),
                            (f"{brow.precision:.3f}", "var(--ink)"),
                            (f"{brow.recall:.3f}", "var(--ink)"),
                            (f"{brow.f1:.3f}", "var(--ink)"),
                            (str(brow.hit), "var(--ink)"),
                            (str(brow.wrong), "var(--warn)"),
                            (str(brow.missing), "var(--ink2)"),
                        ):
                            with (
                                ui.element("td")
                                .classes("td mono")
                                .style(f"padding:8px 12px;font-size:12.5px;color:{colour};")
                            ):
                                ui.label(text)


def _legend() -> None:
    strip = (
        ui.element("div")
        .props('data-testid="tie-legend"')
        .mark("tie-legend")
        .style(
            "display:flex;align-items:center;gap:12px;padding:9px 14px;"
            "border-top:1px solid var(--rule2);"
        )
    )
    with strip:
        tie_marker(TieMark.BEST)
        ui.label(TIE_LEGEND).style("font-size:11px;color:var(--ink2);")
        ui.label(TIE_LEGEND_NOTE).style("margin-left:auto;font-size:11px;color:var(--ink3);")


def _by_language_card(view: ExtractionTabView) -> None:
    assert view.by_language is not None
    card = (
        ui.element("div")
        .classes("card")
        .props('data-testid="by-language-card"')
        .mark("by-language-card")
        .style("display:flex;flex-direction:column;")
    )
    with card:
        with ui.element("div").style("padding:11px 14px;border-bottom:1px solid var(--rule);"):
            ui.label(f"By language · {view.by_language.feature_name}").classes("lbl").style(
                "font-size:12.5px;font-weight:500;"
            )
        with ui.element("table").style("width:100%;border-collapse:collapse;"):
            with ui.element("thead"), ui.element("tr"):
                for label in ("Language", "F1 · 95% CI"):
                    _th(label, None)
            with ui.element("tbody"):
                for lrow in view.by_language.rows:
                    with ui.element("tr").props('data-testid="language-row"').mark("language-row"):
                        with ui.element("td").classes("td mono").style("padding:8px 12px;"):
                            ui.label(lrow.language)
                        with ui.element("td").classes("td").style("padding:8px 12px;"):
                            metric_cell(lrow.cell)
        footer = (
            ui.element("div")
            .props('data-testid="encoding-caveat"')
            .mark("encoding-caveat")
            .style(
                "padding:10px 14px;background:var(--warn-soft);color:var(--warn-ink);"
                "font-size:11.5px;"
            )
        )
        with footer:
            ui.label(ENCODING_CAVEAT)


def _exploratory_card(view: ExtractionTabView) -> None:
    card = (
        ui.element("div")
        .classes("card")
        .props('data-testid="exploratory-card"')
        .mark("exploratory-card")
        .style("display:flex;flex-direction:column;")
    )
    with card:
        with ui.element("div").style(
            "padding:11px 14px;border-bottom:1px solid var(--rule);display:flex;gap:10px;"
        ):
            ui.label("Goal 3 — Exploratory").classes("lbl").style(
                "font-size:12.5px;font-weight:500;"
            )
            ui.label("no ground truth · not ranked").classes("mono").style(
                "font-size:10.5px;color:var(--danger);"
            )
        with ui.element("tbody"):
            for erow in view.exploratory:
                with (
                    ui.element("tr").props('data-testid="exploratory-row"').mark("exploratory-row")
                ):
                    with ui.element("td").classes("td").style("padding:8px 12px;"):
                        ui.label(erow.name)
                    with ui.element("td").classes("td mono").style("padding:8px 12px;"):
                        ui.label(f"{erow.discovery_rate:.1%}")
                    with (
                        ui.element("td")
                        .classes("td mono")
                        .style("padding:8px 12px;color:var(--ink3);")
                    ):
                        # The reviewed counter defers with mismatch tagging
                        # (C6) — `— / n`, never a fake zero.
                        total = erow.review_total
                        ui.label("—" if total is None else f"— / {total}")
        footer = (
            ui.element("div")
            .props('data-testid="exploratory-footer"')
            .mark("exploratory-footer")
            .style("padding:10px 14px;color:var(--ink3);font-size:11.5px;")
        )
        with footer:
            ui.label(EXPLORATORY_FOOTER)

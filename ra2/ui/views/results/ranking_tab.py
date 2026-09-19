# STUB — signature only at M27, body owned by V3 (feat/p4-results-ranking).
"""Tab 3 — Ranking (design/results/README.md §3).

The one question the other tabs do not answer, answered honestly: usually "two
models are tied, pick on cost".

**Tied models repeat their rank** — `1, 1, 3`, never `1, 2, 3`. mvp-spec.md
§11.5 renders overlapping intervals as a tie, not as an order, and a dense
enumeration would imply the order the spec refuses to claim.

**The `best` column does not sum to the feature count** (`P4-D2`). The design
README says it does — "exactly one highest value per feature" — but that is its
*fixture counts* speaking, and its own stated rule, which `stats.mark_ties`
follows, says a model is best only when no rival interval overlaps it. On the
README's own numbers the column sums to 3, not 7. **Do not render that note.**
Each row still sums to the scored-feature count; that one is safe to state.

**Every number here is derived from tab 1's rows** and arrives already computed
in `RankingTabView`; this file computes nothing. J13 reads the macro off this
tab and the per-feature values off tab 1 and asserts the first is the mean of
the non-suppressed second — in the browser, which is where a user would see it
break.

The **presence rate column is reported, never scored** (`SD20`), sitting with
median latency and VRAM under the design's own rule 4: "the tie-breaker you
apply, not one the tool applies".

"How this ranking is computed" — the four numbered rules and the
`--warn-soft` validity footer — renders verbatim, with the **real** `cfg` hash
and corpus label interpolated. A ranking is valid for one config on one corpus
and must be re-run if either moves.

**M27 freezes the signature. V3 writes the body.**
"""

from typing import Final

from nicegui import ui

from ra2.services.readmodels import RankingTabView
from ra2.ui.components.primitives import data_props
from ra2.ui.views.results.chrome import run_descriptor

__all__ = ["COMPUTATION_RULES", "VALIDITY_FOOTER", "render_ranking_tab"]

#: "How this ranking is computed" — the four numbered rules, verbatim.
COMPUTATION_RULES: Final = (
    "Per labelled feature, F1 with a Wilson 95 % interval; empty source "
    "columns leave the denominator (§8.6).",
    "Features averaged with equal weight — not weighted by n, so a feature "
    "with many cases does not outvote one with few.",
    "Models whose macro intervals overlap share a rank. Exploratory features "
    "are excluded — no ground truth, cannot be scored.",
    "Latency and VRAM are reported, never scored — the tie-breaker you apply, "
    "not one the tool applies.",
)

#: Interpolated with the **real** cfg and corpus. A ranking is valid for one
#: config on one corpus and must be re-run if either moves.
VALIDITY_FOOTER: Final = (
    "This ranking is valid for cfg {cfg} on corpus {corpus} only. Change a "
    "feature, a codelist label or the prompt template and it must be re-run."
)


def render_ranking_tab(*, view: RankingTabView) -> None:
    with ui.element("div").style(
        "flex:1;min-height:0;padding:18px 28px 22px;display:flex;flex-direction:column;gap:16px;"
    ):
        _verdict(view)
        if view.rows:
            _table(view)
            _separating(view)
        _rules(view)


def _verdict(view: RankingTabView) -> None:
    banner = (
        ui.element("div")
        .classes("card")
        .props('data-testid="verdict-banner"')
        .mark("verdict-banner")
        .style(
            "background:var(--accent-soft);border-color:oklch(0.86 0.006 260);"
            "padding:12px 14px;display:flex;align-items:flex-start;gap:12px;"
        )
    )
    with banner:
        with ui.element("div").style("display:flex;flex-direction:column;gap:3px;"):
            ui.label(view.verdict_headline).style(
                "font-size:13.5px;font-weight:600;color:var(--ink);"
            )
            if view.verdict_detail:
                ui.label(view.verdict_detail).style("font-size:12.5px;color:var(--ink2);")
        run_descriptor(view.descriptor)


def _table(view: RankingTabView) -> None:
    card = (
        ui.element("div")
        .classes("card")
        .props('data-testid="ranking-card"')
        .mark("ranking-card")
        .style("display:flex;flex-direction:column;overflow:hidden;")
    )
    with card:
        with ui.element("div").style(
            "padding:11px 14px;border-bottom:1px solid var(--rule);display:flex;gap:10px;"
        ):
            ui.label("Ranking").classes("lbl").style("font-size:12.5px;font-weight:500;")
            ui.label(
                f"macro F1 across {view.scored_feature_count} scored features · Wilson 95%"
            ).classes("mono").style("font-size:11px;color:var(--ink2);")
            # **Not** "the best column sums to N" — under P4-D2 it does not,
            # and the design's note on that is the one place its copy is wrong
            # rather than stale. Each ROW sums to the scored-feature count,
            # which is the number stated here.
            ui.label(f"equal weight · {view.unscored_feature_count} features unscored").classes(
                "mono"
            ).style("margin-left:auto;font-size:11px;color:var(--ink3);")
        with (
            ui.element("div").style("overflow:auto;"),
            ui.element("table").style(
                "min-width:900px;width:100%;border-collapse:collapse;table-layout:fixed;"
            ),
        ):
            with ui.element("thead"), ui.element("tr"):
                for label, width in (
                    ("#", "44px"),
                    ("Model", "186px"),
                    ("Macro F1 · extraction", "196px"),
                    ("Presence rate", "92px"),
                    ("Best / tied / worse", "120px"),
                    ("Median latency", "104px"),
                    ("Prompt tokens", "104px"),
                    ("Verdict", "134px"),
                ):
                    _th(label, width)
            with ui.element("tbody"):
                for row in view.rows:
                    tinted = "background:var(--accent-soft);" if row.rank == 1 else ""
                    with data_props(
                        ui.element("tr")
                        .props(f'data-testid="ranking-row" data-rank="{row.rank}"')
                        .mark("ranking-row")
                        .style(tinted),
                        {"data-model": row.model_id},
                    ):
                        # **Tied models repeat the number** — `1, 1, 3`, never
                        # `1, 2, 3` (§11.5).
                        _td_mono(str(row.rank), size="13px")
                        with ui.element("td").classes("td").style("padding:8px 12px;"):
                            ui.label(row.tag).classes("mono").style("font-size:12px;")
                            ui.label(row.digest[:8]).classes("mono").style(
                                "font-size:10.5px;color:var(--ink3);"
                            )
                        with ui.element("td").classes("td").style("padding:8px 12px;"):
                            ui.label(f"{row.macro_f1:.3f}").classes("val")
                            ui.label(f"[{row.ci_low:.3f}–{row.ci_high:.3f}]").classes("ci")
                        # Reported, never scored (SD20) — and neither are the
                        # two after it.
                        _td_mono(f"{row.presence_rate:.3f}", testid="presence-rate")
                        _td_mono(f"{row.best} / {row.tied} / {row.worse}")
                        _td_mono(f"{row.median_latency_ms} ms")
                        _td_mono(f"{row.prompt_tokens}")
                        with ui.element("td").classes("td").style("padding:8px 12px;"):
                            pill = (
                                ui.element("span")
                                .classes(
                                    "pill pill-accent" if row.rank == 1 else "pill pill-neutral"
                                )
                                .props('data-testid="verdict-pill"')
                                .mark("verdict-pill")
                            )
                            with pill:
                                ui.label(row.verdict)


def _td_mono(text: str, *, size: str = "12px", testid: str | None = None) -> None:
    cell = ui.element("td").classes("td mono").style(f"padding:8px 12px;font-size:{size};")
    if testid:
        cell.props(f'data-testid="{testid}"').mark(testid)
    with cell:
        ui.label(text)


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


def _separating(view: RankingTabView) -> None:
    card = (
        ui.element("div")
        .classes("card")
        .props('data-testid="separating-card"')
        .mark("separating-card")
        .style("display:flex;flex-direction:column;overflow:hidden;")
    )
    with card:
        with ui.element("div").style(
            "padding:11px 14px;border-bottom:1px solid var(--rule);display:flex;gap:10px;"
        ):
            ui.label("Where they actually differ").classes("lbl").style(
                "font-size:12.5px;font-weight:500;"
            )
            ui.label(
                f"{len(view.separating)} of {view.scored_feature_count} scored features"
            ).classes("mono").style("font-size:11px;color:var(--ink2);")
            ui.label("non-overlapping intervals").classes("mono").style(
                "margin-left:auto;font-size:11px;color:var(--ink3);"
            )
        if not view.separating:
            # An empty list is a **result**, not a gap.
            note = (
                ui.element("div")
                .props('data-testid="no-separation"')
                .mark("no-separation")
                .style("padding:12px 14px;font-size:12.5px;color:var(--ink2);")
            )
            with note:
                ui.label(
                    "On every scored feature the two leaders' intervals overlap, so neither leads."
                )
            return
        with (
            ui.element("div").style("overflow:auto;"),
            ui.element("table").style("min-width:560px;width:100%;border-collapse:collapse;"),
        ):
            with ui.element("thead"), ui.element("tr"):
                for label, width in (
                    ("Feature", None),
                    ("n", "56px"),
                    ("Δ", "58px"),
                    ("Reading", "172px"),
                ):
                    _th(label, width)
            with ui.element("tbody"):
                for row in view.separating:
                    with (
                        ui.element("tr")
                        .props('data-testid="separating-row"')
                        .mark("separating-row")
                    ):
                        with ui.element("td").classes("td").style("padding:8px 12px;"):
                            ui.label(row.name)
                            ui.label(row.source_label).classes("mono").style(
                                "font-size:10.5px;color:var(--ink3);"
                            )
                        _td_mono(str(row.n))
                        with (
                            ui.element("td")
                            .classes("td mono")
                            .style("padding:8px 12px;color:var(--ok);font-size:12px;")
                        ):
                            ui.label(f"+{row.delta:.3f}")
                        with ui.element("td").classes("td").style("padding:8px 12px;"):
                            ui.label(row.reading)


def _rules(view: RankingTabView) -> None:
    card = (
        ui.element("div")
        .classes("card")
        .props('data-testid="rules-card"')
        .mark("rules-card")
        .style("display:flex;flex-direction:column;overflow:hidden;")
    )
    with card:
        with ui.element("div").style("padding:11px 14px;"):
            ui.label("How this ranking is computed").classes("lbl").style(
                "font-size:12.5px;font-weight:500;margin-bottom:8px;"
            )
            for index, rule in enumerate(COMPUTATION_RULES, start=1):
                with (
                    ui.element("div")
                    .props('data-testid="rule"')
                    .mark("rule")
                    .style("display:flex;gap:10px;padding:3px 0;")
                ):
                    ui.label(str(index)).classes("mono").style(
                        "width:16px;color:var(--ink3);font-size:11px;"
                    )
                    ui.label(rule).style("font-size:12.5px;color:var(--ink2);")
        footer = (
            ui.element("div")
            .props('data-testid="validity-footer"')
            .mark("validity-footer")
            .style(
                "padding:10px 14px;background:var(--warn-soft);color:var(--warn-ink);"
                "font-size:11.5px;"
            )
        )
        with footer:
            ui.label(
                VALIDITY_FOOTER.format(
                    cfg=view.descriptor.config_fingerprint[:8],
                    corpus=view.descriptor.corpus_label,
                )
            )

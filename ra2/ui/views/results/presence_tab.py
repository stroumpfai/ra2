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

from collections.abc import Awaitable, Callable
from typing import Final

from nicegui import ui

from ra2.domain.scoring import ALL_LANGUAGES
from ra2.services.readmodels import PresenceTabView
from ra2.ui.components.contingency_table import contingency_table
from ra2.ui.components.primitives import data_props
from ra2.ui.components.stat_cells import metric_cell
from ra2.ui.views.results.chrome import run_descriptor

__all__ = [
    "GOAL1_NEVER_APART",
    "SCOPE_BANNER",
    "SCOPE_LABEL",
    "WINDOWS_1252_CAVEAT",
    "render_presence_tab",
]

SCOPE_LABEL: Final = "GOAL 2 SCOPE"

#: **Verbatim, first on the tab, and not dismissible** (README §2a). It states
#: the deferral to the analyst rather than leaving an absence to be inferred:
#: mvp-spec.md §11.2 and `D2`.
SCOPE_BANNER: Final = (
    "There is no gold label for presence. A populated record column says "
    "nothing about whether the officer wrote it in the narrative — that gap is "
    "the finding. Deriving gold presence from Goal 1 correctness would be "
    "circular, so this tab reports presence rate, the Goal 1 × presence "
    "cross-tab, and flag inconsistency. Presence precision / recall / F1 are "
    "deferred until a human-labelled subset (≈50 records × features) exists."
)

#: The last column's header. "**Presence numbers are never published without
#: the Goal 1 numbers beside them**, because a weak extractor manufactures
#: false 'missing' flags" (§11.2). The header text is part of the design.
GOAL1_NEVER_APART: Final = "Goal 1 F1 — never shown apart"

WINDOWS_1252_CAVEAT: Final = (
    "The loss is real but cannot be quantified — it is never corrected for and never a column."
)

_FINDING_NOTE: Final = (
    "Goal 2 numbers are never published without the Goal 1 numbers beside them "
    "— a weak extractor manufactures false 'missing' flags."
)


def render_presence_tab(
    *,
    view: PresenceTabView,
    on_select_model: Callable[[str], Awaitable[None]] | None = None,
) -> None:
    with ui.element("div").style(
        "flex:1;min-height:0;padding:16px 28px 24px;display:flex;flex-direction:column;gap:14px;"
    ):
        _scope_banner()
        _model_row(view, on_select_model)
        _rate_table(view)
        _cards(view)
        if view.records is not None:
            _per_record(view)


def _scope_banner() -> None:
    banner = (
        ui.element("div")
        .props('data-testid="scope-banner"')
        .mark("scope-banner")
        .style(
            "border:1px solid var(--warn);background:var(--warn-soft);"
            "border-radius:3px;padding:11px 14px;display:flex;gap:12px;"
        )
    )
    with banner:
        ui.label(SCOPE_LABEL).classes("mono").style("font-size:10.5px;color:var(--warn);flex:none;")
        ui.label(SCOPE_BANNER).style("font-size:12.5px;color:var(--warn-ink);")


def _model_row(
    view: PresenceTabView, on_select_model: Callable[[str], Awaitable[None]] | None
) -> None:
    """**One model at a time** — presence is per-flag, and a three-model grid
    would not be readable (README §2b)."""
    with ui.element("div").style("display:flex;align-items:center;gap:8px;"):
        for model in view.models:
            active = model.model_id == view.model_id
            chip = data_props(
                ui.element("button")
                .classes("chip")
                .props(
                    f'type="button" data-testid="model-chip" aria-pressed="{str(active).lower()}"'
                )
                .mark(f"model-chip-{model.model_id}")
                .style(
                    "cursor:pointer;"
                    + ("border-color:var(--ink);color:var(--ink);" if active else "")
                ),
                {"data-model": model.model_id},
            )
            if on_select_model is not None:
                chip.on("click", lambda _e, mid=model.model_id: on_select_model(mid))
            with chip:
                ui.label(model.tag)
        ui.label(
            f"n = labelled cases · Wilson 95 % · cells under n = "
            f"{view.descriptor.min_cell_count} suppressed"
        ).classes("mono").style("margin-left:auto;font-size:11px;color:var(--ink3);")
        run_descriptor(view.descriptor)


def _rate_table(view: PresenceTabView) -> None:
    ui.label(
        "Presence rate — share of labelled cases where the model flags the text "
        "as containing the feature"
    ).classes("lbl").style("font-size:12.5px;font-weight:500;margin-bottom:7px;")
    card = (
        ui.element("div")
        .classes("card")
        .props('data-testid="presence-card"')
        .mark("presence-card")
        .style("display:flex;flex-direction:column;overflow:hidden;")
    )
    languages = sorted({lang for row in view.rows for lang in row.rates if lang != ALL_LANGUAGES})
    with (
        card,
        ui.element("div").style("overflow:auto;"),
        ui.element("table").style("width:100%;border-collapse:collapse;"),
    ):
        with ui.element("thead"), ui.element("tr"):
            _th("Feature", "200px")
            _th("All · presence rate", None)
            for language in languages:
                _th(language, None)
            # The header text is part of the design (§11.2).
            _th(GOAL1_NEVER_APART, "230px")
        with ui.element("tbody"):
            for row in view.rows:
                with data_props(
                    ui.element("tr").props('data-testid="presence-row"').mark("presence-row"),
                    {"data-feature": row.feature_key},
                ):
                    with ui.element("td").classes("td mono").style("padding:8px 12px;"):
                        ui.label(row.feature_key)
                    for language in (ALL_LANGUAGES, *languages):
                        with ui.element("td").classes("td").style("padding:8px 12px;"):
                            cell = row.rates.get(language)
                            if cell is not None:
                                metric_cell(cell)
                    goal1 = (
                        ui.element("td")
                        .classes("td")
                        .props('data-testid="goal1-companion"')
                        .mark("goal1-companion")
                        .style("padding:8px 12px;")
                    )
                    with goal1:
                        ui.label(f"{row.goal1.f1:.3f}").classes("val").style("font-size:12.5px;")
                        ui.label(f"P {row.goal1.precision:.2f} · R {row.goal1.recall:.2f}").classes(
                            "ci"
                        )
    caption = (
        ui.element("div")
        .props('data-testid="encoding-caption"')
        .mark("encoding-caption")
        .style("font-size:11.5px;color:var(--ink2);")
    )
    with caption:
        ui.label(WINDOWS_1252_CAVEAT)


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


def _cards(view: PresenceTabView) -> None:
    with ui.element("div").style("display:flex;gap:14px;"):
        cross = ui.element("div").classes("card").style("flex:1.15;padding:12px 14px;")
        with cross:
            if view.cross_tab is not None:
                ui.label(
                    f"Goal 1 × presence cross-tab · {view.cross_tab.feature_key} · "
                    f"{view.cross_tab.model_id}"
                ).classes("lbl").style("font-size:12.5px;font-weight:500;")
                contingency_table(view=view.cross_tab)
                note = (
                    ui.element("div")
                    .props('data-testid="cross-tab-note"')
                    .mark("cross-tab-note")
                    .style("font-size:11.5px;color:var(--ink2);margin-top:8px;")
                )
                with note:
                    ui.label(
                        f"The {view.cross_tab.hit_absent} in hit × present = false is "
                        "self-contradiction: the model said the text does not contain "
                        "the feature and then extracted the record's exact value from it."
                    )
        flags = (
            ui.element("div")
            .classes("card")
            .style("flex:.85;padding:12px 14px;display:flex;flex-direction:column;")
        )
        with flags:
            ui.label("Flag inconsistency rate").classes("lbl").style(
                "font-size:12.5px;font-weight:500;"
            )
            ui.label(
                "present = false, yet the extracted value matched. Automatically "
                "countable — a genuine quality signal on the flag itself."
            ).style("font-size:11.5px;color:var(--ink2);margin-bottom:8px;")
            for row in view.flag_inconsistency:
                with data_props(
                    ui.element("div")
                    .props('data-testid="flag-row"')
                    .mark("flag-row")
                    .style("display:flex;align-items:center;gap:10px;padding:4px 0;"),
                    {"data-model": row.model_id},
                ):
                    ui.label(row.model_id).classes("mono").style(
                        "font-size:11px;color:var(--ink2);"
                    )
                    with ui.element("div").style("margin-left:auto;"):
                        metric_cell(row.cell)
            footer = (
                ui.element("div")
                .props('data-testid="goal2-footer"')
                .mark("goal2-footer")
                .style("margin-top:auto;font-size:11.5px;color:var(--ink3);")
            )
            with footer:
                ui.label(_FINDING_NOTE)


def _per_record(view: PresenceTabView) -> None:
    """**This list is the deliverable** — Goal 2 is consumed as a record list
    to act on, not as a rate (README §2e)."""
    assert view.records is not None
    with ui.element("div").style("display:flex;align-items:center;gap:10px;"):
        ui.label("Per-record output — the actionable form of Goal 2").classes("lbl").style(
            "font-size:12.5px;font-weight:500;"
        )
        ui.label(
            f"{view.records.total} records where the value is recorded but not written"
        ).classes("mono").style("margin-left:auto;font-size:11px;color:var(--ink3);")
    card = (
        ui.element("div")
        .classes("card")
        .props('data-testid="per-record-card"')
        .mark("per-record-card")
    )
    with card, ui.element("table").style("width:100%;border-collapse:collapse;"):
        with ui.element("thead"), ui.element("tr"):
            for label, width in (
                ("Record", "250px"),
                ("Record value", "150px"),
                ("Finding", None),
                ("Language", "110px"),
            ):
                _th(label, width)
        with ui.element("tbody"):
            for row in view.records.items:
                with ui.element("tr").props('data-testid="record-row"').mark("record-row"):
                    with ui.element("td").classes("td mono").style("padding:8px 12px;"):
                        ui.label(row.record_id[:18])
                        if row.anonymised:
                            # Required wherever text is shown (mvp-spec.md §13).
                            chip = (
                                ui.element("span")
                                .classes("chip")
                                .props('data-testid="anonymised-chip"')
                                .mark("anonymised-chip")
                            )
                            with chip:
                                ui.label("anonymised")
                    with ui.element("td").classes("td mono").style("padding:8px 12px;"):
                        ui.label(row.record_value)
                    with ui.element("td").classes("td").style("padding:8px 12px;"):
                        ui.label(row.finding)
                    with ui.element("td").classes("td mono").style("padding:8px 12px;"):
                        ui.label(f"{row.language} · {row.language_confidence:.2f}")

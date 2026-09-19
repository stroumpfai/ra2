# NEW — reset and discard (sw-design.md §18.5). Not frozen.
"""The confirm dialog behind every discard.

**One dialog, two states, not two dialogs** (§18.5). The states are "nothing to
export" — a run that produced no `score` and no `mismatch` row, where Discard
is enabled immediately — and "something to export", where the dialog says what
will be lost and offers **Export** beside **Discard**.

A third rendering rides on the same shape rather than forking it: when the
preview carries tagged mismatches, the count goes in the lead sentence and
Discard carries the `force` call. That is G2's "warn and allow" (`R-D3`) made
visible — a hard block leaves an analyst no way to clean up, and the workaround
for a tool that cannot clean up is editing the database by hand.

**This component holds no state and no business logic** (§8.1.1). It renders a
`DiscardPreviewView` the service computed and calls back; whether the discard
is permitted is `preview.blocked`, decided in `lifecycle_service`, never
re-derived here.
"""

from collections.abc import Awaitable, Callable

from nicegui import ui
from nicegui.element import Element

from ra2.services.readmodels import DiscardPreviewView
from ra2.ui.components.primitives import dialog_card

__all__ = [
    "DISCARD_IRREVERSIBLE",
    "DISCARD_KEEPS",
    "EXPORT_LEAVES_RA2",
    "EXPORT_PER_RUN",
    "EXPORT_PROMPT",
    "discard_dialog",
    "loss_line",
    "tagged_sentence",
]

#: Narrow enough to open without clipping at the 1024px viewport this app
#: supports (sw-design.md §8.2), wide enough for the loss line on one row.
_DIALOG_WIDTH_PX = 420

#: Said plainly, every time. A discard is the one irreversible thing this app
#: does, and nothing anywhere records that it happened (§18.3).
DISCARD_IRREVERSIBLE = "This cannot be undone."

#: What a discard does **not** take, because the fear is that it takes
#: everything. Runs are regenerable from immutable inputs; the corpus, the
#: feature set and the prompt versions are the curated half (§1).
DISCARD_KEEPS = "The corpus, the feature set and the prompt versions are kept."

#: Why the Export button is there at all.
EXPORT_PROMPT = "Export first if you want to keep the numbers — nothing else records them."

#: And what the export **costs**, said at the moment it is offered.
#:
#: The mismatch file carries `evidence_span` — verbatim narrative — and lands
#: in the analyst's Downloads folder, outside `RA2_DATA_DIR`, outside
#: `just reset`, and outside every rule this application enforces. The one
#: destructive verb in the product is also the one place it invites a person
#: to make a copy of the most sensitive artefact it produces, and saying so
#: costs a string (risk-assesment.md B2, B3 §8.6; the pattern `D6` asks for on
#: Results — load-bearing copy, asserted in a test).
EXPORT_LEAVES_RA2 = (
    "The file carries verbatim narrative and leaves RA2's control — "
    "nothing the app deletes can reach it again."
)
#: What Export produces when the target holds **more than one run** — the
#: evaluation case (`SD35`). `lifecycle_service.run_export` is per run and
#: there is no evaluation-wide export; merging several runs' rows into one
#: file would need a `run_id` column and a decision about how two tables
#: combine, which is a service's judgement and not this layer's (Do-NOT #7).
#: So the honest answer is N pairs of files, and the dialog says so before the
#: analyst presses rather than after N downloads have started.
EXPORT_PER_RUN = "One pair of files per run — its scores and its mismatches, named by run id."


def loss_line(preview: DiscardPreviewView) -> str:
    """ "412 extractions · 96 scores · 14 mismatches" — what goes.

    Zero-valued parts are dropped rather than printed as "0 scores": a run that
    was never scored should not read as one that scored nothing.
    """
    parts: list[str] = []
    if preview.runs:
        parts.append(f"{preview.runs} run" if preview.runs == 1 else f"{preview.runs} runs")
    for count, noun in (
        (preview.extractions, "extraction"),
        (preview.scores, "score"),
        (preview.mismatches, "mismatch"),
        (preview.files, "file"),
    ):
        if not count:
            continue
        plural = "es" if noun == "mismatch" else "s"
        parts.append(f"{count} {noun}" if count == 1 else f"{count} {noun}{plural}")
    return " · ".join(parts) if parts else "nothing recorded yet"


def tagged_sentence(preview: DiscardPreviewView) -> str:
    """G2's lead sentence. `analyst_tag` is the only human-authored column in
    the pipeline, and the only thing here a re-run cannot produce again."""
    count = preview.tagged_mismatches
    noun = "tagged mismatch" if count == 1 else "tagged mismatches"
    return f"{count} {noun} would be destroyed — review work a re-run cannot recreate."


def discard_dialog(
    *,
    preview: DiscardPreviewView,
    on_discard: Callable[[bool], Awaitable[None]],
    on_export: Callable[[], Awaitable[None]] | None = None,
) -> Element:
    """Build (and return) the dialog. **The caller opens it** — with
    `dialog.value = True`, not `.open()`, because the N4 gate scans `ra2/` for
    `.open(` and wants an `encoding=` beside it (Do-NOT #4).

    Both callbacks are **awaitable**, like `ollama_settings_dialog`'s
    `on_test` and unlike its `on_save`: each one is a service call, and a
    handler that merely *returns* a coroutine has done nothing — NiceGUI awaits
    what a handler returns, and a discarded coroutine is a button that closes a
    dialog and changes no data.

    :param on_discard: receives `force` — `True` only when the analyst pressed
        through the tagged-work warning. The service still checks; a button is
        a UI state, not a guarantee (`ollama_settings_dialog`'s own note).
    :param on_export: `None` where there is nothing to export, which is also
        the state in which no Export button is drawn.
    """
    forced = preview.tagged_mismatches > 0

    async def _discard() -> None:
        # Closed **before** the await, not after: the caller's handler reloads
        # the view that owns this dialog, and a dialog closing itself after its
        # parent has been redrawn is a close on an element that is gone.
        if preview.blocked:
            return
        dialog.close()
        await on_discard(forced)

    with (
        ui.dialog().props('data-testid="discard-dialog"').mark("discard-dialog") as dialog,
        dialog_card(extra=f"width:{_DIALOG_WIDTH_PX}px;max-height:88vh;overflow:auto;"),
        ui.element("div").style("padding:16px;display:flex;flex-direction:column;gap:12px;"),
    ):
        ui.label(f"Discard {preview.kind}").classes("lbl")
        ui.label(preview.label).classes("mono ink2").props('data-testid="discard-target"').mark(
            "discard-target"
        ).style("font-size:11.5px;word-break:break-all;")

        ui.label(loss_line(preview)).classes("mono").props('data-testid="discard-loss"').mark(
            "discard-loss"
        ).style("font-size:11.5px;color:var(--ink);")

        if preview.active and preview.active_detail:
            # G1, rendered rather than raised: the analyst can see why the
            # button is dead without pressing it (§18.2).
            ui.label(f"{preview.active_detail}. Let it finish, or interrupt it first.").classes(
                "danger"
            ).props('data-testid="discard-blocked"').mark("discard-blocked").style(
                "font-size:12px;"
            )
        elif preview.cited_by:
            ui.label(
                f"A corpus was frozen from this delivery ({preview.cited_by}). "
                "Discard the corpus first."
            ).classes("danger").props('data-testid="discard-blocked"').mark(
                "discard-blocked"
            ).style("font-size:12px;")
        elif forced:
            ui.label(tagged_sentence(preview)).classes("danger").props(
                'data-testid="discard-tagged"'
            ).mark("discard-tagged").style("font-size:12px;")

        if preview.has_exportable:
            ui.label(EXPORT_PROMPT).classes("ink2").props(
                'data-testid="discard-export-prompt"'
            ).mark("discard-export-prompt").style("font-size:12px;")
            ui.label(EXPORT_LEAVES_RA2).classes("ink2").props(
                'data-testid="discard-export-warning"'
            ).mark("discard-export-warning").style("font-size:12px;")
            if preview.runs > 1:
                # Read off the view, like everything else here: `runs` is a
                # count the service computed, not a judgement made in `ui/`.
                ui.label(EXPORT_PER_RUN).classes("ink2").props(
                    'data-testid="discard-export-per-run"'
                ).mark("discard-export-per-run").style("font-size:12px;")

        ui.label(DISCARD_KEEPS).classes("ink2").props('data-testid="discard-keeps"').mark(
            "discard-keeps"
        ).style("font-size:12px;")
        ui.label(DISCARD_IRREVERSIBLE).classes("ink2").props(
            'data-testid="discard-irreversible"'
        ).mark("discard-irreversible").style("font-size:12px;")

        with ui.element("div").style(
            "display:flex;gap:8px;align-items:center;justify-content:flex-end;"
        ):
            cancel = (
                ui.element("button")
                .classes("btn secondary")
                .props('type="button" data-testid="discard-cancel"')
                .mark("discard-cancel")
            )
            cancel.on("click", lambda _: dialog.close())
            with cancel:
                ui.label("Cancel")

            if preview.has_exportable and on_export is not None:
                export = (
                    ui.element("button")
                    .classes("btn secondary")
                    .props('type="button" data-testid="discard-export"')
                    .mark("discard-export")
                )
                # The coroutine **function**, not a lambda handing back a
                # coroutine object: NiceGUI awaits a handler it can see is
                # async (`ollama_settings_dialog`'s "Test connection" note).
                # The dialog stays open — exporting is a step *before* the
                # decision, not the decision.
                export.on("click", on_export)
                with export:
                    ui.label("Export")

            confirm = (
                ui.element("button")
                .classes("btn primary")
                .props('type="button" data-testid="discard-confirm"')
                .mark("discard-confirm")
                .style("background:var(--danger);")
            )
            if preview.blocked:
                confirm.props("disabled")
            confirm.on("click", _discard)
            with confirm:
                # The label carries the override, so pressing through the
                # warning is a deliberate act and not the same click.
                ui.label("Discard anyway" if forced else "Discard")
    return dialog

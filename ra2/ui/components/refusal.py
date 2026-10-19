# NEW — plan-refusal-messages.md. Not frozen.
"""How a service refusal reaches the screen.

`FeatureValidationError` stringifies to a count ("2 feature validation
error(s)"), which is the right shape for a log line and the wrong one for a
person; the sentences that name the cause and the repair are in
`validation_errors`. `refusal_text` is the one place that knows that, so a
view never has to remember it (F2 of the plan was thirty-six places that did
not).

**This component holds no state and no business logic** (Do-NOT #7): it words
what a service already decided.
"""

from nicegui import ui

from ra2.services.errors import FeatureValidationError
from ra2.ui.components.primitives import dialog_card

__all__ = ["REFUSAL_HINT", "refusal_dialog", "refusal_reasons", "refusal_text"]

#: Under the list. The sentences name what to change; this says what to do next.
REFUSAL_HINT = "Fix the above, then try again."

_DIALOG_WIDTH_PX = 480


def refusal_reasons(exc: BaseException) -> tuple[str, ...]:
    """The sentences behind a refusal — one per cause."""
    if isinstance(exc, FeatureValidationError):
        return exc.validation_errors
    return (str(exc),)


def refusal_text(exc: BaseException) -> str:
    """One line for a toast: every reason, space-joined."""
    return " ".join(refusal_reasons(exc))


def refusal_dialog(*, title: str, reasons: tuple[str, ...]) -> ui.dialog:
    """Build (and return) the dialog; **the caller opens it** with
    `dialog.value = True` (the N4 gate scans for `.open(`)."""
    with (
        ui.dialog().props('data-testid="refusal-dialog"').mark("refusal-dialog") as dialog,
        dialog_card(extra=f"width:{_DIALOG_WIDTH_PX}px;max-height:88vh;overflow:auto;"),
        ui.element("div").style("padding:16px;display:flex;flex-direction:column;gap:12px;"),
    ):
        ui.label(title).classes("lbl").props('data-testid="refusal-title"').mark("refusal-title")
        with ui.element("ul").style("margin:0;padding-left:18px;display:grid;gap:8px;"):
            for reason in reasons:
                with ui.element("li"):
                    ui.label(reason).classes("danger").props('data-testid="refusal-reason"').mark(
                        "refusal-reason"
                    ).style("font-size:12.5px;")
        ui.label(REFUSAL_HINT).classes("ink2").style("font-size:12px;")
        with ui.element("div").style("display:flex;justify-content:flex-end;"):
            close = (
                ui.element("button")
                .classes("btn primary")
                .props('type="button" data-testid="refusal-close"')
                .mark("refusal-close")
            )
            close.on("click", lambda _: dialog.close())
            with close:
                ui.label("Close")
    return dialog

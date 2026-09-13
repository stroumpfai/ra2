# STUB — signature only at M17, body owned by L3 (feat/p3-evaluation-components).
"""The Ollama connection settings dialog, behind the Models card's gear button.

**Undesigned** — `design/prompt-evaluation/README.md`'s open question 1. Built
to this plan's own design instead of waiting for a round trip
(plan-phase-3.md Q4), the way phase 2 settled the undrawn Add-feature panel.

**Three controls, and only three**: endpoint, timeout, "refresh model list".
They are exactly the three settings the adapter takes, which is why there are
not four (sw-design.md §15.8). VRAM reporting inside this dialog stays out
until the probe has met a machine that is not the target one. Endpoint
reachability is shown next to the Models card, outside this dialog (README
§2 step 4) — not duplicated in here.

Built on the existing `dialog_card` pattern, with phase 2's dialog-clipping
fix respected (it must open without clipping at 1024px).
"""

import html
from collections.abc import Callable

from nicegui import ui
from nicegui.element import Element

from ra2.services.readmodels import ConnectionView
from ra2.ui.components.primitives import dialog_card, labeled_field

__all__ = ["ollama_settings_dialog"]

#: Narrow enough that even the narrowest viewport this app supports (1024px,
#: sw-design.md §8.2) never needs `dialog_card`'s 96vw escape hatch to do any
#: real work — this dialog only ever has two fields and two buttons in it.
_DIALOG_WIDTH_PX = 400


def ollama_settings_dialog(
    *,
    settings: ConnectionView,
    on_save: Callable[[str, int], None],
    on_refresh: Callable[[], None],
) -> Element:
    """`on_save` receives the endpoint and the timeout in seconds; `on_refresh`
    re-asks the endpoint for its catalogue and its reachability.

    Touches no global: the dialog owns nothing the view does not hand it
    (Do-NOT #8) — `endpoint_value`/`timeout_value` below are plain locals
    closed over by this call, scoped to this one dialog instance, not module
    state.
    """
    # Two plain closed-over locals, not a dict: `on_save` takes `(str, int)`
    # precisely, and a `dict[str, str | int]` would widen both back to
    # `str | int` at the call site for no benefit.
    endpoint_value = settings.endpoint
    timeout_value = settings.timeout_s

    def _set_endpoint(value: str) -> None:
        nonlocal endpoint_value
        endpoint_value = value

    def _set_timeout(value: int) -> None:
        nonlocal timeout_value
        timeout_value = value

    def _save() -> None:
        on_save(endpoint_value, timeout_value)
        dialog.close()

    with (
        ui.dialog()
        .props('data-testid="ollama-settings-dialog"')
        .mark("ollama-settings-dialog") as dialog,
        dialog_card(extra=f"width:{_DIALOG_WIDTH_PX}px;max-height:88vh;overflow:auto;"),
        ui.element("div").style("padding:16px;display:flex;flex-direction:column;gap:14px;"),
    ):
        ui.label("Ollama connection").classes("lbl")
        ui.label(
            "The endpoint and timeout the local adapter uses, and a way to "
            "re-ask it for its current model list."
        ).style("font-size:12px;color:var(--ink2);")
        with labeled_field("Endpoint"):
            endpoint_input = (
                ui.element("input")
                .classes("chip")
                .props(
                    f'type="text" value="{html.escape(settings.endpoint)}" '
                    'aria-label="Endpoint" data-testid="ollama-endpoint"'
                )
                .mark("ollama-endpoint")
                .style("width:100%;")
            )
            # `change` (not `input`): the value is read once, on
            # blur/Enter, exactly like `derivation_builder._text_chip` —
            # there is no live validation here for a value to react to
            # mid-keystroke.
            endpoint_input.on(
                "change",
                lambda event: _set_endpoint(str(event.args)),
                js_handler="(e) => emit(e.target.value)",
            )
        with labeled_field("Timeout (seconds)"):
            timeout_input = (
                ui.element("input")
                .classes("chip")
                .props(
                    f'type="number" min="1" step="1" value="{settings.timeout_s}" '
                    'aria-label="Timeout in seconds" data-testid="ollama-timeout"'
                )
                .mark("ollama-timeout")
                .style("width:100%;")
            )
            timeout_input.on(
                "change",
                lambda event: _set_timeout(int(float(str(event.args)))),
                js_handler="(e) => emit(e.target.value)",
            )
        refresh_button = (
            ui.element("button")
            .classes("btn secondary")
            .props('type="button" data-testid="ollama-refresh"')
            .mark("ollama-refresh")
        )
        refresh_button.on("click", lambda _: on_refresh())
        with refresh_button:
            ui.label("Refresh model list")
        save_button = (
            ui.element("button")
            .classes("btn primary")
            .props('type="button" data-testid="ollama-save"')
            .mark("ollama-save")
        )
        save_button.on("click", lambda _: _save())
        with save_button:
            ui.label("Save")
    return dialog

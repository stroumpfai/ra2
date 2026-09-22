# STUB — signature only at M17, body owned by L3 (feat/p3-evaluation-components).
"""The Ollama connection settings dialog, behind the Models card's gear button.

**Undesigned** — `design/prompt-evaluation/README.md`'s open question 1. Built
to this plan's own design instead of waiting for a round trip
(plan-phase-3.md Q4), the way phase 2 settled the undrawn Add-feature panel.

**Five controls.** M17 specified three — endpoint, timeout, "refresh model
list" — on the reasoning that they are exactly the three settings the adapter
takes, and that endpoint reachability belongs beside the Models card (README §2
step 4) rather than duplicated in here. Two of those three still hold. What did
not survive contact is the assumption that a dialog whose only job is to *show*
the current settings is enough to get Ollama configured: the endpoint accepted
any string with no feedback at all, and the one bit rendered outside could not
distinguish "Ollama is not running" from "that is the wrong port". So the
dialog gains, deliberately (P3-D19):

- **A loopback check on the endpoint as you type it.** The same rule the app
  enforces at startup — `domain.llm.is_loopback_url`, moved down out of
  `infra/` precisely so this file can share it rather than keep a second copy
  of the one thing standing between this codebase and N1. Save is disabled
  while it fails.
- **"Test connection"**, which probes the endpoint **currently in the field**
  and names the cause. Testing the *configured* endpoint would be useless here
  — that is what the line outside already says, and the value you want to
  check while setting up is the one you have not committed to yet.

"Refresh model list" and "Test connection" are **not** the same button and are
deliberately not merged: refresh re-asks the configured endpoint and closes the
dialog to reload the view, while test asks about a typed value and stays open
to report on it. Merging them would conflate "diagnose" with "apply".

Built on the existing `dialog_card` pattern, with phase 2's dialog-clipping fix
respected (it must open without clipping at 1024px).
"""

from collections.abc import Awaitable, Callable
from typing import Final

from nicegui import ui
from nicegui.element import Element

from ra2.domain.llm import ProbeCode, is_loopback_url
from ra2.services.readmodels import ConnectionProbeView, ConnectionView
from ra2.ui.components.primitives import (
    data_props,
    dialog_card,
    format_latency_ms,
    labeled_field,
)

__all__ = ["ENDPOINT_INVALID_MESSAGE", "PROBE_WORDS", "ollama_settings_dialog", "probe_sentence"]

#: Narrow enough that even the narrowest viewport this app supports (1024px,
#: sw-design.md §8.2) never needs `dialog_card`'s 96vw escape hatch to do any
#: real work.
_DIALOG_WIDTH_PX = 400

#: The **one rendering table** for `ProbeCode` (CLAUDE.md: findings, not prose).
#: Tests assert on the code; the wording lives here and nowhere else, so it can
#: be reworded without a single test changing. Each sentence says what is wrong
#: **and** what to do about it — a connection test that only reports failure
#: has done half the job it exists for.
#:
#: The `{}` placeholders are filled by `probe_sentence` from the view's own
#: numbers; a code whose sentence takes no number simply has none.
PROBE_WORDS: Final[dict[ProbeCode, str]] = {
    ProbeCode.OK: "Reachable — {models}, {latency}.",
    ProbeCode.REFUSED_NOT_LOOPBACK: (
        "That host is not this machine, so RA2 refuses it without connecting. "
        "The endpoint must be 127.0.0.1, ::1 or localhost."
    ),
    ProbeCode.MALFORMED_URL: (
        "Not a URL RA2 can read. It should look like http://127.0.0.1:11434/v1."
    ),
    ProbeCode.CONNECTION_REFUSED: (
        "Nothing is listening there. Start Ollama with “ollama serve”, then test again."
    ),
    ProbeCode.TIMEOUT: (
        "The connection was accepted but nothing answered within {probe_timeout_s} s."
    ),
    ProbeCode.HTTP_ERROR: (
        "Something answered with HTTP {http_status}. Check the path — "
        "RA2 expects the /v1 root, as in http://127.0.0.1:11434/v1."
    ),
    ProbeCode.BAD_PAYLOAD: ("Something answered, but it is not an Ollama API. Check the port."),
}

#: Shown under the endpoint field the moment a non-loopback value is entered,
#: before any button is pressed. Deliberately the same ground as
#: `REFUSED_NOT_LOOPBACK`'s sentence: they are the same rule, reached without
#: and with a round trip, and an analyst should not have to notice that.
ENDPOINT_INVALID_MESSAGE: Final = (
    "Must be on this machine — 127.0.0.1, ::1 or localhost. RA2 never sends data off the host."
)


def probe_sentence(view: ConnectionProbeView) -> str:
    """One `ConnectionProbeView` as the sentence an analyst reads.

    The numbers come from the view; the words come from `PROBE_WORDS`. A code
    with no entry (one added later and not yet worded) falls back to the code
    itself rather than raising — a settings dialog that crashed on an
    unfamiliar diagnosis would be worse than one that prints it.
    """
    template = PROBE_WORDS.get(view.code)
    if template is None:
        return str(view.code)
    return template.format(
        models=_model_count_phrase(view.model_count),
        latency=("?" if view.latency_ms is None else format_latency_ms(view.latency_ms)),
        http_status=view.http_status if view.http_status is not None else "?",
        probe_timeout_s=view.probe_timeout_s,
    )


def _model_count_phrase(count: int | None) -> str:
    """ "1 model", "3 models", "no models".

    A success line reading "1 models" undermines the one thing this sentence
    is for — telling an analyst, at a glance, that the endpoint is healthy.
    "no models" rather than "0 models" because a freshly installed Ollama with
    nothing pulled is exactly the case, and it is reachable.
    """
    if count is None:
        return "an unknown number of models"
    if count == 0:
        return "no models"
    return f"{count} model" if count == 1 else f"{count} models"


def ollama_settings_dialog(
    *,
    settings: ConnectionView,
    on_save: Callable[[str, int], None],
    on_refresh: Callable[[], None],
    on_test: Callable[[str, int], Awaitable[ConnectionProbeView]],
) -> Element:
    """`on_save` receives the endpoint and the timeout in seconds; `on_refresh`
    re-asks the *configured* endpoint for its catalogue; `on_test` probes the
    endpoint **in the field** and answers with a `ConnectionProbeView`.

    `on_test` is the kit's one genuinely asynchronous callback: it has to
    *return* a value for this dialog to render, so the `Callable[..., None]`
    plus `_sync` cast every other handler uses does not apply. The click
    handler below is `async def` and NiceGUI awaits it.

    Touches no global: the dialog owns nothing the view does not hand it
    (Do-NOT #8) — the values below are plain locals closed over by this call,
    scoped to this one dialog instance, not module state.
    """
    endpoint_value = settings.endpoint
    timeout_value = settings.timeout_s

    def _endpoint_is_valid() -> bool:
        return is_loopback_url(endpoint_value)

    def _sync_validity() -> None:
        """Reflect the loopback rule into the two things that depend on it.

        Save is disabled rather than hidden, and the reason is stated inline —
        a control that vanishes tells an analyst nothing about why.
        """
        valid = _endpoint_is_valid()
        endpoint_error.set_visibility(not valid)
        if valid:
            save_button.props(remove="disabled")
        else:
            save_button.props("disabled")

    def _set_endpoint(value: str) -> None:
        nonlocal endpoint_value
        endpoint_value = value
        _sync_validity()

    def _set_timeout(value: int) -> None:
        nonlocal timeout_value
        timeout_value = value

    def _save() -> None:
        # Belt and braces: the button is disabled, and the handler checks
        # anyway. A disabled button is a UI state, not a guarantee.
        if not _endpoint_is_valid():
            return
        on_save(endpoint_value, timeout_value)
        dialog.close()

    async def _test() -> None:
        """Probe what is in the field. Enabled even when the endpoint fails the
        loopback rule: the service refuses it without opening a socket and
        returns `REFUSED_NOT_LOOPBACK`, which is a more useful thing to show
        than a dead button."""
        test_result.clear()
        with test_result:
            ui.label("Testing…").classes("ink3").style("font-size:12px;").mark("ollama-testing")
        test_result.set_visibility(True)
        view = await on_test(endpoint_value, timeout_value)
        test_result.clear()
        with test_result:
            (
                ui.label(probe_sentence(view))
                .classes("ok" if view.ok else "danger")
                .style("font-size:12px;")
                .props('data-testid="ollama-test-sentence"')
                .mark("ollama-test-sentence")
            )
            if view.detail:
                # The provider's or the OS's verbatim words, under the
                # sentence and never instead of it: the sentence is what an
                # analyst acts on, this is what they paste into a bug report.
                (
                    ui.label(view.detail)
                    .classes("mono ink3")
                    .style("font-size:11px;word-break:break-word;")
                    .props('data-testid="ollama-test-detail"')
                    .mark("ollama-test-detail")
                )

    with (
        ui.dialog()
        .props('data-testid="ollama-settings-dialog"')
        .mark("ollama-settings-dialog") as dialog,
        dialog_card(extra=f"width:{_DIALOG_WIDTH_PX}px;max-height:88vh;overflow:auto;"),
        ui.element("div").style("padding:16px;display:flex;flex-direction:column;gap:14px;"),
    ):
        ui.label("Ollama connection").classes("lbl")
        ui.label(
            "The endpoint and timeout the local adapter uses, a way to test it, "
            "and a way to re-ask it for its current model list."
        ).style("font-size:12px;color:var(--ink2);")
        with labeled_field("Endpoint"):
            # `RA2_LLM_BASE_URL` is the environment, which is precisely the
            # provenance that broke the header's data-directory chip (SD31):
            # through the props *string* a Windows-shaped value would have been
            # read as Python source. Through the mapping it is not parsed at
            # all, and it is not `html.escape`d either — Vue binds the
            # attribute, so escaping here would show `&amp;` in the field.
            endpoint_input = data_props(
                ui.element("input")
                .classes("chip")
                .props('type="text" data-testid="ollama-endpoint"')
                .mark("ollama-endpoint")
                .style("width:100%;"),
                {"value": settings.endpoint, "aria-label": "Endpoint"},
            )
            # `change` (not `input`): the value is read on blur/Enter, exactly
            # like `derivation_builder._text_chip`. The loopback check is
            # cheap enough to run per keystroke, but validating a URL while it
            # is still half-typed would flag every endpoint on the way in.
            endpoint_input.on(
                "change",
                lambda event: _set_endpoint(str(event.args)),
                js_handler="(e) => emit(e.target.value)",
            )
            endpoint_error = (
                ui.label(ENDPOINT_INVALID_MESSAGE)
                .classes("danger")
                .style("font-size:11px;margin-top:4px;")
                .props('data-testid="ollama-endpoint-error"')
                .mark("ollama-endpoint-error")
            )
        with labeled_field("Timeout (seconds)"):
            timeout_input = data_props(
                ui.element("input")
                .classes("chip")
                .props('type="number" min="1" step="1" data-testid="ollama-timeout"')
                .mark("ollama-timeout")
                .style("width:100%;"),
                {"value": str(settings.timeout_s), "aria-label": "Timeout in seconds"},
            )
            timeout_input.on(
                "change",
                lambda event: _set_timeout(int(float(str(event.args)))),
                js_handler="(e) => emit(e.target.value)",
            )
        test_button = (
            ui.element("button")
            .classes("btn secondary")
            .props('type="button" data-testid="ollama-test"')
            .mark("ollama-test")
        )
        # The coroutine **function**, not `lambda _: _test()`: NiceGUI awaits a
        # handler it can see is async, and a lambda handing back a coroutine
        # object is fire-and-forget — the verdict would land whenever it landed.
        test_button.on("click", _test)
        with test_button:
            ui.label("Test connection")
        #: Empty until the button is pressed — the dialog opens with no verdict
        #: rather than a stale one, because the last answer is about whatever
        #: URL was in the field at the time.
        test_result = (
            ui.element("div")
            .style("display:flex;flex-direction:column;gap:3px;")
            .props('data-testid="ollama-test-result"')
            .mark("ollama-test-result")
        )
        test_result.set_visibility(False)
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
        # After both elements exist: a dialog opened on an already-invalid
        # configured endpoint shows the reason immediately, without waiting
        # for the analyst to touch the field.
        _sync_validity()
    return dialog

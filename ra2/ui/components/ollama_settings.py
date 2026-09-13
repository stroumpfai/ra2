# STUB — signature only at M17, body owned by L3 (feat/p3-evaluation-components).
"""The Ollama connection settings dialog, behind the Models card's gear button.

**Undesigned** — `design/prompt-evaluation/README.md`'s open question 1. Built
to this plan's own design instead of waiting for a round trip
(plan-phase-3.md Q4), the way phase 2 settled the undrawn Add-feature panel.

**Three controls, and only three**: endpoint, timeout, "refresh model list".
They are exactly the three settings the adapter takes, which is why there are
not four (sw-design.md §15.8). VRAM reporting inside this dialog stays out
until the probe has met a machine that is not the target one.

Built on the existing `dialog_card` pattern, with phase 2's dialog-clipping
fix respected (it must open without clipping at 1024px).
"""

from collections.abc import Callable

from nicegui.element import Element

from ra2.services.readmodels import ConnectionView

__all__ = ["ollama_settings_dialog"]


def ollama_settings_dialog(
    *,
    settings: ConnectionView,
    on_save: Callable[[str, int], None],
    on_refresh: Callable[[], None],
) -> Element:
    """`on_save` receives the endpoint and the timeout in seconds; `on_refresh`
    re-asks the endpoint for its catalogue and its reachability.

    Touches no global: the dialog owns nothing the view does not hand it
    (Do-NOT #8).
    """
    raise NotImplementedError

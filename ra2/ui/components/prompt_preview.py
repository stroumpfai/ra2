# STUB — signature only at M17, body owned by L3 (feat/p3-evaluation-components).
"""The shared resolved-prompt preview panel.

**One component, two entry points** (plan-phase-3.md C4): Prompts' "Preview
with record 1" resolves the current template against the *active* feature set
and record 1; Evaluation's "Preview prompt" resolves against its own pinned
inputs. Both make **no model call**, and both must render identically — L3's
exit criteria assert that against one golden string.

The token figure renders as `≈ N tokens`. It is an **estimate** and the label
says so: an exact count needs the model's tokeniser and every tokeniser
package downloads its vocabulary, which is egress (N1, C6). The real
`prompt_tokens` come back from the endpoint per call and are stored per
extraction.

Declared at M17 so L1, L2 and L3 build in Wave 4 in parallel.
"""

from nicegui import ui
from nicegui.element import Element

from ra2.services.readmodels import ResolvedPromptView
from ra2.ui.components.primitives import format_count, scroll_well

__all__ = ["prompt_preview_panel"]

#: The Prompts/Evaluation Resolved card's body cap (README §1, "Resolved
#: card" — "intentional — a resolved prompt is long").
_RESOLVED_BODY_MAX_HEIGHT_PX = 210


def prompt_preview_panel(*, resolved: ResolvedPromptView) -> Element:
    """The design's Resolved card: a 42px tinted header carrying
    "Resolved — record 1, all 13 features" and the token estimate, over a
    mono 11.5px `white-space:pre-wrap` body capped at **210px** with
    `overflow:auto` — a resolved prompt is long, and that cap is deliberate.

    The header text is assembled from `resolved.record_key` and
    `resolved.feature_count` — the read model carries the record's own key
    (e.g. an `unfall_uid`), not a pre-formatted sentence, so "record " and
    "all N features" are this component's wording, applied the same way on
    both entry points.
    """
    element = (
        ui.element("div")
        .classes("prompt-preview")
        .props('data-testid="prompt-preview"')
        .mark("prompt-preview")
        .style(
            "display:flex;flex-direction:column;min-width:0;"
            "border:1px solid var(--rule);border-radius:3px;overflow:hidden;"
        )
    )
    with element:
        with ui.element("div").style(
            "display:flex;align-items:baseline;justify-content:space-between;gap:10px;"
            "flex:none;height:42px;padding:0 14px;background:var(--strip-tint);"
            "border-bottom:1px solid var(--rule2);"
        ):
            ui.label(
                f"Resolved — record {resolved.record_key}, all {resolved.feature_count} features"
            ).classes("lbl").props('data-testid="prompt-preview-title"').mark(
                "prompt-preview-title"
            )
            ui.label(f"≈ {format_count(resolved.token_estimate)} tokens").classes("mono").props(
                'data-testid="prompt-preview-tokens"'
            ).mark("prompt-preview-tokens").style("font-size:10.5px;color:var(--ink3);flex:none;")
        with scroll_well(max_height_px=_RESOLVED_BODY_MAX_HEIGHT_PX):
            ui.label(resolved.text).props('data-testid="prompt-preview-body"').mark(
                "prompt-preview-body"
            ).style(
                "display:block;white-space:pre-wrap;font-family:var(--mono);"
                "font-size:11.5px;color:var(--ink2);padding:12px 14px;"
            )
    return element

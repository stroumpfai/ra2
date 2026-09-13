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

from nicegui.element import Element

from ra2.services.readmodels import ResolvedPromptView

__all__ = ["prompt_preview_panel"]


def prompt_preview_panel(*, resolved: ResolvedPromptView) -> Element:
    """The design's Resolved card: a 42px tinted header carrying
    "Resolved — record 1, all 13 features" and the token estimate, over a
    mono 11.5px `white-space:pre-wrap` body capped at **210px** with
    `overflow:auto` — a resolved prompt is long, and that cap is deliberate."""
    raise NotImplementedError

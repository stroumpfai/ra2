# STUB — bodies owned by L2 (feat/p3-evaluation-view, phase 3 Wave 4).
"""Evaluation view — one corpus and one feature set, run across several models.

`design/prompt-evaluation/README.md` §2 (`Evaluation.dc.html`): a setup column
of six numbered steps beside a progress column of per-model cards, the runs
table and the reproducibility card.

Three things the README calls out as **past regressions**, all worth asserting:

- the setup column is `align-self:flex-start` — without it the `margin-top:auto`
  launch row is pushed to the bottom of a stretched column;
- the split **never wraps**; both columns shrink to their min-widths
  (320px / 360px);
- the toolbar's right group uses `margin-left:auto`, never a `flex:1` spacer.

And one place the **design file is stale**: step 2's note reads "Freezes when
the first run executes". That was true before phase 2; `mvp-spec.md` §9 now
says a feature set is already frozen from the moment it was created, and an
evaluation only ever cites an already-frozen config. Render the corrected copy
(plan-phase-3.md C5, R6).

Progress polls `GET /api/v1/tasks/{id}` with `ui.timer`, exactly as the Import
view does. No websocket, no SSE.

L2 also flips this view's own `built` flag in `ui/shell.py` and adds its own
line to `views/register_all` — **those two lines and nothing else** (§6.1).
"""

from ra2.services.container import Services

__all__ = ["register"]


def register(services: Services) -> None:
    """Register `/evaluation`."""
    raise NotImplementedError

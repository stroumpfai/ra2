# Amendment: `feat/evaluation-switcher` (SD59)

> **APPLIED in the same commit**, as the other post-phase slices were. No
> wave is running. **No schema change, no migration, no API change.**

Reported in use. Analysts change a parameter or two and launch again, and the
evaluations they no longer care about pile up. The discard existed (`SD35`)
but reached only the evaluation on screen, and the Evaluation screen could show
only the newest: it had no switcher and no `?evaluation=`, and
`app.storage.client` starts empty on every load (`SD54`). The confirm dialog
named its target as `"{name} · N run(s)"`, and names repeat (`SD32`).

Decided with the project owner: propositions P1 and P2 of
`plan-delete-evaluation.md`. `sw-design.md` `SD59` has the reasoning and what
was rejected.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/services/readmodels.py` | + three defaulted fields on `DiscardPreviewView`. Additive: every existing construction is unchanged |
| `ra2/ui/views/evaluation_view.py` | `?evaluation=` on the page function; `_EvaluationPage(services, *, requested="")`; `_current_evaluation` returns `(view, drafts)`; the evaluation chip at the head of the toolbar's left group; `_follow_in_url`; two constants |

```diff
# ra2/services/readmodels.py — DiscardPreviewView
     cited_by: int = 0
+    launched_at: datetime | None = None
+    models: tuple[str, ...] = ()
+    inputs: str = ""
```

```diff
# ra2/ui/views/evaluation_view.py
     @ui.page(_ITEM.path)
-    async def _page() -> None:
-        page = _EvaluationPage(services)
+    async def _page(evaluation: str = "") -> None:
+        page = _EvaluationPage(services, requested=evaluation)
```

The API keeps `DiscardPreview` as it is: `api/v1/discard.py` builds it field
by field, so the new fields do not reach it and the OpenAPI snapshot is
unchanged.

## Overlap

`feat/evaluation-rename` (`SD58`), in progress beside this branch, puts an
`evaluation-name` field at the head of the same left group. Whichever merges
second resolves `_render_toolbar`: chip, then the name field, then the pinned
inputs (`plan-delete-evaluation.md` §4.4).

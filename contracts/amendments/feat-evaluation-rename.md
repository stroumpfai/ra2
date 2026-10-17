# Amendment: `feat/evaluation-rename` (SD58)

> **APPLIED in the same commit**, as the other post-phase slices were. No
> wave is running. **No schema change, no migration, no API change.**

Reported in use. A new evaluation is named after its feature set, which tells
evaluations apart only until a set has several. After that, every row in the
Results and Mismatches pickers (`SD54`) reads the same, and only the launch time
separates them. The service could already rename a draft, but no screen offered
it, and the Evaluation screen did not show the name at all.

Decided with the project owner: options 1 and 2 of the proposal. There is a
name field on the Evaluation screen, and renaming works before and after the
launch. `sw-design.md` `SD58` has the reasoning and what was rejected.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/services/evaluation_service.py` | + `rename(evaluation_id, *, name) -> EvaluationDraftView`: draft or launched, under `_draft_lock`, through `_require` rather than `_editable`. + `_checked_name`, `_NAME_MAX_CHARS`, `EVAL_ERROR_NAME_BLANK`, `EVAL_ERROR_NAME_TOO_LONG`. `save_draft` and `update_draft` check the name through `_checked_name` too, so a name is stored stripped and is never blank or longer than 200. Additive: no existing signature changes. `update_draft(name=...)` stays draft-only |
| `ra2/ui/views/evaluation_view.py` | + `_name_input`, `_rename`, `NAME_PREFIX`, `NAME_LABEL`, `NAME_MAX_CHARS`, `NAME_STYLE`; − `PINNED_SUFFIX`. Whenever an evaluation is on screen, the toolbar's left group is a `name:` label and an `evaluation-name` field, **in place of** the pinned-inputs line, which now renders only `NO_SETUP_MESSAGE` in the empty state. The field is never disabled and saves on `change` through `rename`, then `redraw()`s (no endpoint ask, `SD56`). The toolbar still holds one button (`SD32`) |
| `ra2/persistence/models.py` | Docstring only: `Evaluation`'s "every edit path raises" names the rename exception |
| `ra2/services/errors.py` | Docstring only: `EvaluationLockedError` says `rename` never raises it |
| `ra2/services/readmodels.py` | Docstrings only: `EvaluationDraftView` names the rename exception; `EvaluationView.feature_config_label` is no longer the toolbar's line, and stays for the API |

```diff
# ra2/services/evaluation_service.py
+    async def rename(self, evaluation_id: EvaluationId, *, name: str) -> EvaluationDraftView:
```

The API keeps `PATCH /api/v1/evaluations/{id}` draft-only, and `rename` is not
exposed over HTTP. The OpenAPI snapshot is unchanged. A `PATCH` whose name is
only whitespace was stored as given and is now refused with the service's
sentence (`FeatureValidationError`), like a floor below 1.

## Not frozen, changed

| Path | What |
|---|---|
| `sw-design.md` | `SD58`; §15.2's "every edit path raises" and the §5 schema comment name the exception |
| `mvp-spec.md` | §5's schema comment: "immutable after (SD13), except name, which pins nothing (SD58)" |
| `CONTRACTS.md` | Rows beside `SD56`'s |

## Tests

| Layer | File | What |
|---|---|---|
| backend | `tests/backend/services/evaluation/test_rename.py` *(new)* | A draft is renamed and keeps its other steps. A launched evaluation is renamed, and its draft view (less the name), `launched_at` and every pinned column of every run are unchanged, while `update_draft(name=...)` still raises `EvaluationLockedError`. The name is stored stripped. Blank (three forms) and 201 characters are refused and change nothing, and exactly 200 is accepted. `update_draft` and `save_draft` follow the same rule. An unknown id is `NotFoundError` |
| ui | `tests/ui/test_evaluation_view.py` | The left group is exactly the `name:` label and the field, the field carries the stored name, its accessible label and `maxlength`, the toolbar's only texts are `name:` and "Save draft", and it still has one button. The toolbar test no longer asserts the pinned line, and the first-paint test reads the name field instead. Renaming a draft stores the stripped name and puts it back in the field. On a launched evaluation the field is live, Seed stays disabled, and the rename lands. A blank name shows `EVAL_ERROR_NAME_BLANK` and the stored name stays. With no evaluation there is no field |
| e2e | `tests/e2e/test_j10_evaluation.py` | After the launch, J10 types a new name and presses Enter in a real browser. The API returns the new name, Corpus stays disabled, and the Results picker lists the evaluation under the new name |

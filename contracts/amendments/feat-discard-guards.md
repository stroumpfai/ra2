# Amendment: `feat/discard-guards` (SD60, SD61)

> **APPLIED in the same commit**, as the other post-phase slices were. No
> wave is running. **One schema change and one migration**
> (`3ce2190bd859`, `evaluation.kept_at`), **one new route**
> (`PUT /api/v1/evaluations/{id}/kept`).

With every evaluation reachable from the Evaluation screen (`SD59`), clearing
debris became quick, and so did clearing the wrong thing. Two guards close
that:

- **`SD60`**: pressing through tagged work takes typing the tagged count. The
  dialog alone; no frozen file.
- **`SD61`**: an analyst can mark an evaluation to keep, and discard refuses
  it and every run of it until it is released. This is G3 in §18.2, and it is
  what this amendment is for.

Decided with the project owner: P3 and P4 of `plan-delete-evaluation.md`,
which is deleted with this slice. `sw-design.md` `SD60`, `SD61` and §18.6
carry its reasoning, and what it proposed and rejected.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/persistence/models.py` | + `Evaluation.kept_at: Mapped[datetime \| None]`, nullable, no backfill. The class docstring names `set_kept` beside `rename` as exempt from the launch lock |
| `ra2/services/errors.py` | + `EvaluationKeptError(evaluation_id)`, 409, not overridable |
| `ra2/services/readmodels.py` | + `EvaluationDraftView.kept_at` (defaulted `None`) and `.is_kept`; + `DiscardPreviewView.kept` (defaulted `False`), and `blocked` includes it |
| `ra2/api/schemas.py` | + `KeepEvaluationRequest(kept: bool)`; + `EvaluationDraftResponse.kept_at`; + `DiscardPreview.kept`. All additive; the OpenAPI snapshot is regenerated |
| `ra2/services/evaluation_service.py` | + `set_kept(evaluation_id, *, kept) -> EvaluationDraftView`. Additive: no existing signature changes |
| `ra2/ui/views/evaluation_view.py` | + the keep control beside "Discard evaluation" in the runs card header, and four constants |

```diff
# ra2/persistence/models.py — Evaluation
     min_cell_count: Mapped[int] = mapped_column(default=20)
+    kept_at: Mapped[datetime | None] = mapped_column(default=None)
```

```diff
# ra2/services/errors.py
+class EvaluationKeptError(ServiceError):
+    def __init__(self, evaluation_id: str) -> None: ...
```

```diff
# ra2/services/readmodels.py
 class EvaluationDraftView:
     min_cell_count: int = 20
+    kept_at: datetime | None = None
+    @property
+    def is_kept(self) -> bool: ...

 class DiscardPreviewView:
     inputs: str = ""
+    kept: bool = False
     @property
     def blocked(self) -> bool:
-        return self.active or self.cited_by > 0
+        return self.active or self.cited_by > 0 or self.kept
```

```diff
# ra2/services/evaluation_service.py
+    async def set_kept(self, evaluation_id: EvaluationId, *, kept: bool) -> EvaluationDraftView:
```

## The migration

`20261017_1200_3ce2190bd859_keep_an_evaluation.py`, revising `b4f2c81e6d37`:
one nullable `DateTime(timezone=True)` column on `evaluation`, no backfill.
`NULL` means "nobody marked it", which is true of every row that exists before
it. Registered in `tests/test_p5_contract.py`'s `POST_PHASE_5_REVISIONS`; one
head.

## Why the route, when a rename has none

`SD58` kept the rename off the wire. G3 cannot follow it: `DELETE` answers a
kept evaluation, or a run of one, with 409, and a guard an API caller cannot
get past is a defect rather than a guard.

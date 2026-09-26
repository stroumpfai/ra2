# Amendment — `fix/ranking-vram`

> **Applied file by file in the stage whose code needs it**, as
> `feat-model-choice` was. No wave is running.

`plan-ranking-vram.md`, design `sw-design.md` **SD41**. Six frozen files and
one revision. The defect: `mvp-spec.md` §11.5, `design/results/README.md` §3b
and §3d, `sw-design.md` §16.5 and `plan-phase-4.md` T3 all promise a **VRAM**
figure on the Ranking tab; `ranking_service.py:140` writes `vram_bytes=0`, no
column is rendered, the Model column's `digest · size` sub-line lost its size
with it, and rule 4 prints the promise verbatim above the table.

**Why it was never built:** T3's named source,
`evaluation.selected_models_json`, is a JSON array of model **tags**, and `run`
had no size column — the instruction was unbuildable as written.

---

## 1. `ra2/persistence/models.py` — `+ Run.model_size_bytes` *(Stage 2)*

```diff
     llm_parallel_calls: Mapped[int] = mapped_column(default=1, server_default="1")
+    #: SD41. The catalogue's `size_bytes` for this tag at launch — the number
+    #: the Models card showed beside the tick. NULLABLE and **not**
+    #: backfilled: a run from before this revision recorded no size, and `0`
+    #: is the defect being repaired.
+    model_size_bytes: Mapped[int | None] = mapped_column(default=None)
```

**Nullable, unlike `llm_parallel_calls`.** That column's `1` was a *fact* about
every earlier row — no code before it could put two records in flight. There
is no equivalent fact here: a run launched last week recorded no size, and any
default would be a number nobody measured. `SD41` and D5 of the plan.

## 2. `ra2/services/readmodels.py` — `RankingRow.vram_bytes` renamed *(Stage 2)*

```diff
-    vram_bytes: int
+    #: SD41. The run's pinned `model_size_bytes`; `None` for a run launched
+    #: before that column existed, rendered `—` rather than `0`.
+    model_size_bytes: int | None = None
```

**A rename, not an addition.** The field name has to say which datum it
carries: the screen keeps the analyst's word (`VRAM`, which `fits_vram`,
`RA2_GPU_VRAM_GB` and the Models card all already use for this number), and the
schema keeps the datum's. A name that said the wrong thing is how `vram_bytes=0`
survived a whole phase.

It moves to the end of the reported-never-scored group, after `parallel_calls`,
because it now carries a default like the two `SD38` added.

## 3. `ra2/api/schemas.py` — the same on `RankingRowResponse` *(Stage 2)*

```diff
-    vram_bytes: int
+    model_size_bytes: int | None = None
```

**Not additive**, and `tests/api/openapi_snapshot.json` is regenerated
accordingly. Nothing is lost: the field it replaces was the constant `0` for
every row ever served, so no client can have read a meaning out of it. The
snapshot test is what makes the change reviewed rather than drift.

## 4. `ra2/ui/components/primitives.py` — `+ format_gigabytes` *(Stage 3)*

An **addition**, the mechanism the frozen list sanctions for this file.
`evaluation_view._gigabytes` moves here and is deleted there; two callers now
render a model size, and `primitives` is where `format_count`,
`format_latency_ms`, `format_local` and `format_tokens` each state their one
rule. The same move `format_tokens` made in `fix-ranking-token-format`.

## 5. `ra2/ui/views/results/ranking_tab.py` — the two cells *(Stage 3)*

- a **VRAM** column, 78px, after Prompt tokens and before Verdict
  (`data-testid="vram"`), and `min-width` 900px → 978px;
- the Model column's sub-line becomes `digest · size` as §3b draws it
  (`data-testid="model-size"`), `digest` alone when there is no size;
- `—` in both cells for a run with no pinned size (D5);
- `VRAM_NOTE` under the table, beside `PARALLEL_NOTE`'s slot, saying what the
  number is.

`COMPUTATION_RULES[3]` is **unchanged** — it already names VRAM, and the table
now keeps what it says.

## 6. `ra2/ui/views/evaluation_view.py` — `_gigabytes` deleted *(Stage 3)*

Imports `format_gigabytes` instead. **No rendered output changes**: the size
line and the VRAM-limit message read exactly as before.

---

## The revision *(Stage 2)*

`…_pin_the_model_size_on_the_run.py` — `run.model_size_bytes`, `Integer`,
nullable, additive, no existing row touched. Registered in
`tests/test_p5_contract.py`'s `POST_PHASE_5_REVISIONS`. **One author**, this
branch's implementer; no parallel head.

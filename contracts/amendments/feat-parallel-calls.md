# Amendment — `feat/parallel-calls`

> **PROPOSED in Stage 1 of [`plan-parallel-calls.md`](../../plan-parallel-calls.md);
> applied in Stage 2, in the same commit as the code that needs it**, as
> `fix-evaluation-timeout-and-progress` was. No wave is running.

The design is `sw-design.md` §15.4 and **SD38**. The measurements behind it
are `plan-parallel-calls.md` §1.1–1.2. In short, `qwen3:8b` runs 2.3–2.5×
faster with four records in flight and its answers stay inside serial noise,
while other models change 14–29 of 48 answers under the same setting. So the
setting is a per-model map, the run pins its value, and the ranking gains a
cost column that stays comparable across parallelism.

Five frozen files, one schema change, one migration. Nothing here is removed
or renamed. Every new field on a frozen read model or schema is defaulted, so
existing constructions keep compiling.

---

## 1. `ra2/infra/config.py` — `llm_parallel_calls` and its refusal

```diff
+#: The ceiling on one model's records in flight. Above it the KV caches of
+#: that many slots outgrow any single-GPU host this runs on, and the gain
+#: had flattened by four in every measurement (`plan-parallel-calls.md` §1.2).
+MAX_PARALLEL_CALLS: Final = 8
+
-__all__ = ["REASONING_EFFORTS", "Settings"]
+__all__ = ["MAX_PARALLEL_CALLS", "REASONING_EFFORTS", "Settings"]
```

```diff
     llm_reasoning_effort: str = DEFAULT_REASONING_EFFORT
 
+    #: sw-design.md §15.4, SD38 — how many records of one run are in flight
+    #: at once, **per model tag**: `{"qwen3:8b": 4}`. A model not in the map
+    #: runs serially, and the default `{}` is exactly the behaviour before
+    #: this setting existed. The launch pins `map.get(tag, 1)` on the run, and
+    #: Resume executes at the pin, never at the current map.
+    #:
+    #: **An entry is a measurement, not a preference.** Batched decoding is
+    #: not guaranteed bit-identical to batch size 1. Measured on this host,
+    #: `qwen3:8b` changed 0–2 of 48 answers at four calls, and `granite4.1:8b`
+    #: changed 14–15. Add a tag only after it has passed
+    #: `plan-parallel-calls.md` §4.1's gate here, and record the result in
+    #: `docs/performance.md` §5.3 (model, digest, Ollama version, date,
+    #: differ counts). Code can't check that; this sentence is the check.
+    #:
+    #: Two things RA2 cannot read and so cannot refuse:
+    #:
+    #: - **Ollama's own slot count.** `OLLAMA_NUM_PARALLEL` must be at least
+    #:   the largest value here. It is server-wide, so raising it applies to
+    #:   every model the service loads, and each loaded model reserves that
+    #:   many KV caches (`gemma4:12b`: 8.1 → 10.4 GB at four).
+    #: - **Ollama's per-architecture refusals.** Ollama 0.34 serves `qwen35`
+    #:   one request at a time whatever the setting.
+    #:
+    #: Either way the excess calls **queue** rather than fail, and the queue
+    #: wait counts against `llm_timeout_s`. The run-start log line prints
+    #: `parallel=N` beside `timeout=` for that reason.
+    llm_parallel_calls: dict[str, int] = Field(default_factory=dict)
+
```

```diff
+    @model_validator(mode="after")
+    def _check_parallel_calls(self) -> Self:
+        """Refuse an unusable map **at construction**, for the reason
+        `_check_reasoning_effort` gives: a value that can be refused before the
+        first call should be, rather than one `RA2_LLM_TIMEOUT_S` into a run.
+        """
+        for tag, calls in self.llm_parallel_calls.items():
+            if not tag.strip():
+                raise ValueError("RA2_LLM_PARALLEL_CALLS names an empty model tag")
+            if not 1 <= calls <= MAX_PARALLEL_CALLS:
+                raise ValueError(
+                    f"RA2_LLM_PARALLEL_CALLS[{tag!r}] must be 1..{MAX_PARALLEL_CALLS}; "
+                    f"got {calls}"
+                )
+        return self
+
     @model_validator(mode="after")
     def _default_db_path(self) -> Self:
```

`Final` joins the `typing` import. The value type is `int`, not `StrictInt`,
which matches every other integer setting here. pydantic-settings reads the
environment variable as JSON.

**Why.** Without it there is nothing for the launch to pin. The alternatives are
refused in SD38: one host-wide number would parallelise models the gate
failed, and an evaluation input would let two evaluations of one model differ
by a number nobody measured.

## 2. `ra2/persistence/models.py` — `Run.llm_parallel_calls`

```diff
     llm_reasoning_effort: Mapped[str | None] = mapped_column(String(16), default=None)
+    #: sw-design.md §15.4, SD38 — records this run keeps in flight, pinned at
+    #: launch from `RA2_LLM_PARALLEL_CALLS[model_name]`, 1 when unmapped.
+    #: Resume executes at this value, never at the current map, so one run's
+    #: rows never mix two latency regimes. It is also the divisor in the
+    #: ranking's time per record (`mean latency ÷ parallel calls`), which is
+    #: why it's a column and not a log line.
+    #:
+    #: **NOT NULL, backfilled 1**, unlike `llm_reasoning_effort` above: every
+    #: run before this column executed one record at a time, because no code
+    #: could do anything else, so `1` records a fact rather than a guess. The
+    #: `server_default` is the migration's backfill, declared here too so
+    #: `alembic check` sees one truth (`Evaluation.reasoning_effort`'s rule).
+    llm_parallel_calls: Mapped[int] = mapped_column(default=1, server_default="1")
```

**Migration.** One revision, `down_revision` the current head, single head,
additive: `batch_alter_table("run")` adding `sa.Column("llm_parallel_calls",
sa.Integer(), nullable=False, server_default="1")`, with the server default
**kept**, for the reason `3b7c1d5a92e4` gives. The branch's implementer is the
migration author for this branch; nobody else runs `alembic revision` on it.

## 3. `ra2/services/readmodels.py` — two read models

```diff
 class ProvenanceView:
     ...
     llm_reasoning_effort: str | None = None
+    #: Records this run kept in flight (SD38). Always known, because the
+    #: column is NOT NULL, and `1` on every run from before it existed.
+    llm_parallel_calls: int = 1
```

```diff
 class RankingRow:
     """One model's row of the ranking table.
 
     `rank` **repeats on a tie** (`1, 1, 3`), never enumerates (`1, 2, 3`):
     §11.5 renders overlapping intervals as a tie, not as an order.
 
-    The last three fields are **reported, never scored** — the design's own
-    rule 4, "the tie-breaker you apply, not one the tool applies". The presence
-    rate joins them (`SD20`): §11.2 is unambiguous that presence has no gold
-    label, and a model that flags everything present maximises it. None of the
-    three takes any part in `rank`.
+    Everything from `presence_rate` on is **reported, never scored** — the
+    design's own rule 4, "the tie-breaker you apply, not one the tool
+    applies". The presence rate joins them (`SD20`): §11.2 is unambiguous that
+    presence has no gold label, and a model that flags everything present
+    maximises it. So do time per record and parallel calls (`SD38`). None of
+    them takes any part in `rank`.
     """
     ...
     vram_bytes: int
+    #: `mean(latency_ms) ÷ parallel_calls`, by Little's law. It is the cost
+    #: per record at this run's parallelism, and it stays comparable across
+    #: runs whose `median_latency_ms` doesn't (SD38). `0` when no row carries a
+    #: latency, the convention `median_latency_ms` already follows.
+    ms_per_record: int = 0
+    #: The run's pinned `llm_parallel_calls`. `> 1` marks the median latency
+    #: cell `×N`.
+    parallel_calls: int = 1
```

## 4. `ra2/api/schemas.py` — the same two, on the wire

```diff
 class ProvenanceResponse(_Schema):
     ...
     llm_reasoning_effort: str | None = None
+    #: Records this run kept in flight (SD38); `1` on every earlier run.
+    llm_parallel_calls: int = 1
```

```diff
 class RankingRowResponse(_Schema):
     ...
     vram_bytes: int
+    #: Reported, never scored (SD38): mean latency ÷ parallel calls.
+    ms_per_record: int = 0
+    parallel_calls: int = 1
```

## 5. `tests/conftest.py` — the environment scrub

```diff
         "RA2_LLM_TIMEOUT_S",
         "RA2_LLM_MAX_RETRIES",
+        "RA2_LLM_PARALLEL_CALLS",
         "RA2_RUN_CONCURRENCY",
```

**Why.** A developer who has set the variable to use it would otherwise change
the result of every test that launches a run. The scrub exists for exactly
this.

**Found while here, not proposed:** `RA2_LLM_REASONING_EFFORT` is missing from
the same list. It has the same hazard, and it belongs to its own change.

## 6. `CONTRACTS.md` — the change log, on application

One row in the style of the `llm_reasoning_effort` entry, naming
`ra2/infra/config.py`, `ra2/persistence/models.py`,
`ra2/services/readmodels.py`, `ra2/api/schemas.py` and `tests/conftest.py`,
with the Stage 0b measurement as its reason. Then a second row for the
revision, as `090e7fdc12c5` has.

---

## What this does not touch

- **`run_concurrency`** keeps its meaning (models in parallel) and its
  refusal above 1, and `test_run_concurrency_above_one_is_refused_not_silently_ignored`
  stays as it is.
- **`ra2/domain/llm.py` and `OllamaLLMClient`**: `AsyncOpenAI` is already safe
  to share across coroutines, and `SD27`'s transport flags belong to the one
  client, whatever N is.
- **`RunView`**: the pin is an input, and it's shown where the other inputs are,
  on the reproducibility card.
- **`ranking_service.py`, `ranking_tab.py`, `run_service.py`,
  `evaluation_service.py`** are not frozen. They change in Stages 2–3 under the
  ownership rule.

No shim and no `xfail` is left behind: nothing is built against these files
until the amendment is applied.

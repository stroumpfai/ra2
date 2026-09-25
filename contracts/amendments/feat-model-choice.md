# Amendment — `feat/model-choice`

> **PROPOSED in Stage 1 of [`plan-model-choice.md`](../../plan-model-choice.md)**
> (2026-09-25). **Applied file by file, in the stage whose code needs it**, and
> recorded in `CONTRACTS.md` under "Model choice" as each is applied. No wave
> is running.
>
> | § | File | Applied |
> |---|---|---|
> | 1 | `ra2/domain/ids.py` | Stage 2 |
> | 3 | `ra2/persistence/models.py` | Stage 2, plus `QualificationId: String(36)` in the type map, which SQLAlchemy requires for a `NewType` |
> | 2, 5, 6, 8 | `domain/llm.py`, `container.py`, `main.py`, `justfile` | Stage 3 |
> | 9 | `ra2/infra/config.py` | Stage 4 |
> | 4, 7 | `readmodels.py`, `schemas.py` | Stage 5 |

The design is `sw-design.md` **SD40** (§15.2, §15.4, §15.5, §15.7). In short:
a model's fitness on this host becomes a stored, append-only
**qualification** per (tag, digest), taken by `just qualify-model`. The launch
honours an `RA2_LLM_PARALLEL_CALLS` entry only with a matching passing gate,
and the Models card shows the measured facts.

Nine frozen files and one new table, so one migration. Nothing is removed or
renamed. Every new field on a frozen read model or schema is defaulted, so
existing constructions keep compiling. The two new `ModelCatalog` methods do
break structural conformance, and that's intended: `OllamaModelCatalog` and
`tests/fixtures/fake_llm.py::StaticModelCatalog` both gain them in the same
commit.

---

## 1. `ra2/domain/ids.py` — one id

```diff
 MismatchId = NewType("MismatchId", str)
+
+#: SD40 — one `model_qualification` row. uuid7 like every other id here.
+QualificationId = NewType("QualificationId", str)
```

and `"QualificationId"` in `__all__`.

## 2. `ra2/domain/llm.py` — `ModelCatalog` answers two more questions

```diff
     async def reachable(self) -> EndpointStatus:
         """Ask the endpoint, now. Re-checked on view load and when the
         settings dialog's "refresh" is pressed — never on a timer."""
         ...
+
+    async def version(self) -> str | None:
+        """The endpoint's Ollama version (`/api/version`), verbatim, or `None`
+        when it does not answer. **Never raises.** Asked once per launch
+        (SD40): a parallel-calls gate holds only on the Ollama version it was
+        measured on, and `None` matches nothing."""
+        ...
+
+    async def loaded(self) -> tuple[str, ...]:
+        """The tags currently loaded (`/api/ps`). **Empty when unreachable**,
+        never an exception. The qualifier refuses to measure while another
+        model is resident, because that hides the speedup (SD40)."""
+        ...
```

## 3. `ra2/persistence/models.py` — `ModelQualification`

```diff
+class ModelQualification(Base):
+    """This host's measurement of one model (tag, digest) over the synthetic
+    seed (sw-design.md SD40, `plan-model-choice.md`).
+
+    **Append-only.** Re-qualifying adds a row, and the newest per
+    (tag, digest) wins, the way a re-run adds runs. Nothing updates or deletes
+    one except `just reset`, which wipes the database with it.
+
+    **Numbers only.** Written by `just qualify-model` from a throwaway data dir
+    over the synthetic seed. No delivery content can reach it, and no other
+    table references it.
+
+    The two summaries are JSON because they are read whole and never queried
+    inside. A new figure then costs a field, not a migration.
+    """
+
+    __tablename__ = "model_qualification"
+    __table_args__ = (
+        Index("ix_model_qualification_tag_digest", "model_tag", "model_digest", "measured_at"),
+        CheckConstraint("seed_records > 0", name="seed_records_positive"),
+    )
+
+    id: Mapped[QualificationId] = mapped_column(primary_key=True)
+    model_tag: Mapped[str] = mapped_column(String(200))
+    model_digest: Mapped[str] = mapped_column(String(64))
+    #: Compared at launch (SD40). `None` only when the endpoint did not say.
+    ollama_version: Mapped[str | None] = mapped_column(String(64), default=None)
+    #: Recorded, **not** compared (SD40): often unknown, and a name misses the
+    #: driver and CUDA versions that matter more.
+    gpu_name: Mapped[str | None] = mapped_column(String(200), default=None)
+    ra2_version: Mapped[str | None] = mapped_column(String(64), default=None)
+    measured_at: Mapped[datetime]
+    seed_records: Mapped[int]
+    #: `domain.qualification.QualitySummary`, serialised.
+    quality_json: Mapped[str]
+    #: `list[domain.qualification.GateResult]`; `[]` when not gated.
+    gate_json: Mapped[str] = mapped_column(default="[]")
```

and `QualificationId` added to the `ra2.domain.ids` import.

## 4. `ra2/services/readmodels.py` — the card's qualification

```diff
+@dataclass(frozen=True, slots=True)
+class QualificationCardView:
+    """The third line of a Models card row (SD40). Numbers and a state;
+    the wording lives in `ui/`'s rendering table.
+
+    `estimated_ms` is `None` when neither an evaluation scope nor a corpus
+    size is known. `parallel_calls` is what the launch *would* pin today,
+    from `domain.qualification.parallel_decision`, not the map's value.
+    """
+
+    state: QualificationState
+    measured_digest: str
+    seed_macro_f1: float
+    ms_per_record: float
+    entity_fill: float
+    parallel_calls: int
+    estimated_ms: int | None = None
+
+
 @dataclass(frozen=True, slots=True)
 class ModelChoiceView:
@@
     fits_vram: bool | None
     selected: bool = False
+    #: SD40. `None` means never qualified on this host: the row still ticks.
+    qualification: QualificationCardView | None = None
```

`QualificationState` (`QUALIFIED | STALE_DIGEST | SERVER_SENSITIVE`) is
imported from `ra2.domain.qualification`, which isn't frozen. "Unmeasured" is
`qualification is None`, not a fourth value, so it can't be constructed with
numbers attached.

## 5. `ra2/services/container.py` — the service joins the bundle

```diff
     lifecycle: LifecycleService
+    # --- model choice (SD40) ---
+    #: `summarise` in the qualifier's throwaway app, `record` on the target.
+    #: Neither adapter serves a write; the API only reads, through
+    #: `evaluation`.
+    qualification: QualificationService
```

## 6. `ra2/main.py` — wiring only

```diff
+    qualification_service = QualificationService(
+        session_factory=session_factory,
+        ranking=ranking_service,
+        clock=clock,
+        ids=ids,
+    )
     services = Services(
@@
+        qualification=qualification_service,
     )
```

`EvaluationService` takes no new argument. It reads `model_qualification`
through `QualificationRepository` with its own `session_factory`, and it
already holds the `ModelCatalog` that `version()` is asked of (SD40).

## 7. `ra2/api/schemas.py` — the response mirrors the view

```diff
+class QualificationCardResponse(_Schema):
+    """SD40. Read-only: there is no endpoint that records a qualification."""
+
+    state: QualificationState
+    measured_digest: str
+    seed_macro_f1: float
+    ms_per_record: float
+    entity_fill: float
+    parallel_calls: int
+    estimated_ms: int | None = None
+
+
 class ModelChoiceResponse(_Schema):
@@
     fits_vram: bool | None = None
     selected: bool = False
+    qualification: QualificationCardResponse | None = None
```

## 8. `justfile` — `qualify-model`

```diff
+# SD40: measure one model on this host over the synthetic seed, in a throwaway
+# data dir, and record the numbers in RA2_DATA_DIR's database. `--gate 2,4
+# --n-slot URL` adds the parallel-calls gate against a second, N-slot Ollama
+# the operator started (docs/performance.md §5.4). Never starts Ollama.
+qualify-model tag *args:
+    uv run python scripts/qualify_model.py {{tag}} {{args}}
```

## 9. `ra2/infra/config.py` — the docstring's rule moves into code

Documentation only. No field, default or validator changes.

```diff
-    #: changed 14–15. Add a tag only after it has passed
-    #: `plan-parallel-calls.md` §4.1's gate here, and record the result in
-    #: `docs/performance.md` §5.3 (model, digest, Ollama version, date,
-    #: differ counts). Code can't check that; this sentence is the check.
+    #: changed 14–15. **The launch checks it** (SD40): an entry applies only
+    #: while the newest `model_qualification` for the tag and its current
+    #: digest passed the gate at this N or above on the running Ollama
+    #: version. Otherwise the run is pinned to 1 and the log line says why.
+    #: `just qualify-model <tag> --gate 4` records a gate.
```

---

## Not frozen, listed so the owner knows

| File | Change |
|---|---|
| `ra2/domain/qualification.py` | New. Pure |
| `ra2/persistence/repositories/qualification_repo.py` | New. `add`, `latest_for`; no update or delete |
| `ra2/persistence/migrations/versions/<rev>_model_qualification.py` | New. The plan's implementer is its only author |
| `ra2/services/qualification_service.py` | New |
| `ra2/services/evaluation_service.py` | `_new_run` pins `parallel_decision(...).n`; `_model_choices` attaches the card |
| `ra2/infra/ollama_client.py` | `OllamaModelCatalog.version()`, `.loaded()` |
| `ra2/ui/views/evaluation_view.py` | The third line; `MODELS_WELL_PX` 196 → 252 |
| `scripts/qualify_model.py` | New. Wiring |
| `tests/fixtures/fake_llm.py` | `StaticModelCatalog.version()`, `.loaded()` |

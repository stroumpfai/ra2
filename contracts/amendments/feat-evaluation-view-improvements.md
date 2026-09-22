# Amendment — `feat/evaluation-view-improvements`

> **APPLIED in the same commits**, as `fix-evaluation-timeout-and-progress`
> and `fix-results-visibility` were. No wave is running.

From five requests made against the running Evaluation screen
([`plan-evaluation-view-improvements.md`](../../plan-evaluation-view-improvements.md)).
Four are presentation and touch nothing frozen. The fifth — **reasoning effort
becomes a per-evaluation pinned input** — is a new setup column, and a setup
column travels through four frozen files.

The argument in one paragraph: `090e7fdc12c5` pinned
`RA2_LLM_REASONING_EFFORT` on the `run` row because two runs that asked
different questions must not record identical provenance (§19.8). But the
setting stayed in the environment, so the comparison its own docstring
prescribes — *"set `high` and launch a second evaluation to compare"* —
required editing the environment and restarting the app **between two
evaluations that are meant to be comparable**. An input that decides the
answer as much as temperature does, and that the analyst is expected to vary
between evaluations, is a column on `evaluation` and a control in step 5.

---

## 1. `ra2/persistence/models.py` — `evaluation.reasoning_effort`

```diff
     temperature: Mapped[float] = mapped_column(default=0.0)
     seed: Mapped[int] = mapped_column(default=42)
+    #: Step 5, beside temperature and seed and for the same reason: it decides
+    #: the answer, and it travels in every run's provenance (§19.8). One of
+    #: `domain.llm.REASONING_EFFORTS`.
+    #:
+    #: **NOT NULL with a default, where `run.llm_reasoning_effort` is
+    #: nullable.** The two say different things. A `run` written before
+    #: `090e7fdc12c5` genuinely does not know what effort it used, and a
+    #: guess there would be invented provenance. An `evaluation` is a
+    #: *setup*: every existing row ran under the process default, so `none`
+    #: is a fact about them and not a guess.
+    reasoning_effort: Mapped[str] = mapped_column(String(16), default=_DEFAULT_REASONING_EFFORT)
     size: Mapped[EvaluationSize] = mapped_column(default=EvaluationSize.FULL)
```

Migration `20260922_….py`, `add_reasoning_effort_to_evaluation`, one
`batch_alter_table` with `server_default="none"` so existing rows backfill in
the same statement.

## 2. `ra2/services/readmodels.py` — `EvaluationDraftView.reasoning_effort`

```diff
     temperature: float
     seed: int
+    #: Step 5's third control. One of `domain.llm.REASONING_EFFORTS`; pinned
+    #: onto every run this evaluation launches.
+    reasoning_effort: str = DEFAULT_REASONING_EFFORT
     size: EvaluationSize
```

Defaulted, so nothing that constructs one positionally or partially breaks —
the same discipline every additive read-model field here has followed.

## 3. `ra2/api/schemas.py` — the field on the request and both responses

```diff
 class UpdateEvaluationRequest(_Schema):
     temperature: float | None = Field(default=None, ge=0.0, le=2.0)
     seed: int | None = None
+    reasoning_effort: str | None = None

 class EvaluationDraftResponse(_Schema):
     temperature: float = 0.0
     seed: int = 42
+    reasoning_effort: str = DEFAULT_REASONING_EFFORT
```

Validated in the **service**, not with a `Literal` here: the refusal an
unmappable effort deserves is the one `update_draft` already raises for a
model that does not fit VRAM (422 `FeatureValidationError`, a sentence an
analyst can read), and a `Literal` would answer with a pydantic error shape
that names the field and not the repair.

## 4. `ra2/domain/llm.py` — the vocabulary, and one keyword on the seam

```diff
+#: The reasoning efforts Ollama maps onto its own `think` levels, **in
+#: ascending order** — the order step 5's select offers them in.
+#:
+#: Here rather than in `infra/config.py`, where it was: `ui/` may not import
+#: `infra` (the layer rule) and step 5 needs the list, while `Settings` still
+#: needs it to refuse an unmappable value at construction. `domain` is the one
+#: package all three may read — the move `is_loopback_url` already made, for
+#: exactly this reason. `infra.config` re-exports it, so
+#: `RA2_LLM_REASONING_EFFORT`'s refusal is unchanged.
+REASONING_EFFORTS: Final[tuple[str, ...]] = ("none", "low", "medium", "high")
+DEFAULT_REASONING_EFFORT: Final = "none"

 class LLMClient(Protocol):
     async def extract[T](
         self, text: str, schema: type[T], model: str,
-        *, temperature: float, seed: int,
+        *, temperature: float, seed: int, reasoning_effort: str | None = None,
     ) -> Extraction[T]: ...
```

**Why the protocol changes at all**, when M17 confirmed it was "exactly
adequate" and the effort was deliberately put on client *construction* three
commits ago. Both were right about a value that belongs to the process. This
one no longer does: it is pinned per evaluation, so two runs in one process
ask with different efforts, and a constructed value cannot express that
without a second client per run — which would mean a second loopback guard, a
second connection pool and a construction inside the record loop.

`None` means *the constructed default*, so `main.py`'s wiring, every existing
caller and every test double that does not care are unchanged, and a run
queued before this migration still asks the question `Settings` says.

## 5. `ra2/infra/config.py` — unchanged in shape

`llm_reasoning_effort` stays exactly as it is: the **default a new draft is
created with**, and the value a pre-migration run falls back to. Its validator
now imports `REASONING_EFFORTS` from `domain.llm` rather than defining it
(`infra` may import `domain`), and `infra.config` re-exports the name so
`from ra2.infra.config import REASONING_EFFORTS` keeps working.

---

## Documents corrected in the same commit (CLAUDE.md's rule for a stale *how*)

- `sw-design.md` §15.2 — the `evaluation` schema block gains the column.
- `sw-design.md` §15.5 — the sentence asserting `LLMClient` is "unchanged
  since phase 1" is no longer true, and says what changed and why.
- `sw-design.md` §13 — **`SD36`** (this amendment's argument) and **`SD37`**
  (the three presentation rules that depart from the design files: latency in
  seconds, local time, the two deleted paragraphs).
- `mvp-spec.md` §3 — the protocol snippet.
- `mvp-spec.md` §5 — the `evaluation` table, and the `run` table's
  `llm_reasoning_effort`, which `090e7fdc12c5` added without updating the
  spec.
- `mvp-spec.md` §19.8 — "every run stores …" gains the reasoning effort.

The design READMEs are **not** edited: they record what was drawn, and a
deviation from them belongs in `SD37` (the `SD3` precedent — vendored fonts
against the README's Google Fonts).

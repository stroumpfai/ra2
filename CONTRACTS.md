# CONTRACTS.md — what is frozen

Everything that crosses an agent boundary was written once, at M0, before any
parallel work started. **After the `m0-frozen` tag these files change only by
amendment** (plan-m0-m5.md §1).

Every frozen module carries `# FROZEN — see CONTRACTS.md` on its first line.
`tests/test_m0_contract.py` asserts that, and that this file lists every one of
them.

**If you need a frozen file changed:** write
`contracts/amendments/<your-branch>.md` with the file, the reason and the exact
proposed diff; do **not** edit the file; shim locally or `xfail` that one test;
name the amendment in your final report. The lead applies accepted amendments
and rebases the branches that have not merged yet.

---

## The frozen list

### Packaging and gates — owner: M0, locked for every wave

| File | Contents |
|---|---|
| `pyproject.toml` | uv, Python 3.14, **every M0-M8 dependency pinned**; ruff (`PLW1514` on), mypy `strict` on `ra2/`, coverage `fail_under = 85` scoped to `ra2/domain` + `ra2/services`, all seven pytest markers |
| `justfile` | `dev test e2e lint fmt migrate revision census-export setup-e2e eval` — final |
| `.importlinter` | the §1.1 layer contract, api/ui independence, the pure-domain and one-LLM-seam contracts |
| `.pre-commit-config.yaml` | ruff, ruff-format, mypy, import-linter, the `no-real-data` hook |
| `scripts/check_no_real_data.py` | the hook's implementation; stdlib only |
| `.github/workflows/ci.yml` | layers 1-3 on `ubuntu-latest` **and** `windows-latest`; E2E linux-only with traces on failure; `alembic check` |
| `alembic.ini` | script location, UTC file template, ruff post-write hook. No URL — `env.py` reads `Settings` |

### The contract — owner: M0, amendment only

| File | Contents |
|---|---|
| `ra2/domain/ids.py` | `DeliveryId FileId CorpusId RecordId TaskId` plus `ObjektRowId PersonRowId CensusColumnId EvaluationId`, all `NewType(str)` |
| `ra2/domain/findings.py` | `Severity`, `Finding`, the complete `FindingCode` enum, `DEFAULT_SEVERITY` |
| `ra2/domain/delivery.py` | `FileKind Encoding Dialect FileAnalysis DeliveryAnalysis RowOutcome`, plus `SourceKind DeliveryStatus STRUCTURED_KINDS UNFALL_UID_PATTERN` |
| `ra2/domain/census.py` | `TypeHint ValueCount ColumnCensus CensusBucket CensusBucketLabel` — **types and signatures only**; `compute_census` / `compute_buckets` bodies are A2's |
| `ra2/domain/language.py` | `Language`, `LanguageGuess`, the `LanguageDetector` protocol |
| `ra2/domain/llm.py` | `Extraction[T]`, the `LLMClient` protocol (no callers in phase 1) |
| `ra2/infra/config.py` | the sw-design.md §10 settings table, `RA2_` prefix |
| `ra2/infra/clock.py` | the `Clock` protocol |
| `ra2/infra/idgen.py` | the `IdFactory` protocol |
| `ra2/infra/tasks.py` | `TaskStatus TaskProgress ProgressReporter TaskWork`, the `TaskRunner` protocol |
| `ra2/infra/filestore.py` | `StoredFile`, the `FileStore` protocol, `FileStoreError` / `ReadOnlyFileStoreError` |
| `ra2/persistence/models.py` | **the whole phase-1 schema** — mvp-spec.md §5 tables in scope plus SD1, SD2, SD4 |
| `ra2/persistence/session.py` | async engine, the three connect-time PRAGMAs, session factory, `session_scope` |
| `ra2/persistence/migrations/env.py` | async Alembic env reading `RA2_DB_PATH` through `Settings` |
| `ra2/services/errors.py` | `ServiceError NotFoundError BlockingFindingsError CorpusLockedError DeliveryNotAnalysedError` |
| `ra2/services/readmodels.py` | `SortDir Page[T] DeliveryFileView DeliveryView CorpusView CensusColumnView CensusSummary` |
| `ra2/services/protocols.py` | `CensusInput CensusTableInput`, the **`CensusMaterialiser` seam** |
| `ra2/services/container.py` | `Services` — the bundle both adapters get |
| `ra2/services/delivery_service.py` | constructor + typed signatures; bodies B1 |
| `ra2/services/corpus_service.py` | constructor + typed signatures; bodies B1 |
| `ra2/services/census_service.py` | constructor + typed signatures; bodies B2 |
| `ra2/services/export_service.py` | constructor + typed signatures, `CSV_BOM`, `CSV_DELIMITER`; bodies B2 |
| `ra2/api/schemas.py` | every request/response model for the four routers, complete |
| `ra2/api/deps.py` | the typed `Depends` that reach `app.state` |
| `ra2/api/v1/router.py` | the `/api/v1` router; C1 and C2 never touch the same file |
| `ra2/main.py` | `create_app()` — **final**; every adapter a defaulted keyword argument |
| `ra2/cli.py` | the `just census-export` entry point |
| `tests/conftest.py` | root fixtures only: `settings tmp_data_dir frozen_clock seeded_ids app_factory` |
| `CLAUDE.md` | the Do-NOT list, the layer rule, the ownership rule |
| `CONTRACTS.md` | this file |

### Stubs — a body is expected; the file is **not** frozen

Each carries `# STUB — bodies owned by <agent>`.

| Path | Owner |
|---|---|
| `ra2/domain/parsing/**`, `ra2/domain/validation.py`, `ra2/domain/canary.py` | A1 |
| `ra2/domain/census.py` *(bodies)*, `ra2/domain/typehint.py` | A2 |
| `ra2/persistence/repositories/**`, `ra2/persistence/migrations/versions/**` | A3 |
| `ra2/infra/files.py`, `lingua_detector.py`, and the implementation classes inside `filestore.py` / `tasks.py` / `clock.py` / `idgen.py` | A4 |
| `ra2/ui/**` (`theme.py`, `shell.py`, `state.py`, `components/`, `views/`) | A5 |
| `ra2/api/v1/{deliveries,corpora}.py` | C1 |
| `ra2/api/v1/{census,tasks}.py` | C2 |

Note the mixed files: `filestore.py`, `tasks.py`, `clock.py` and `idgen.py`
hold a **frozen protocol** and an **A4-owned implementation** in the same
module, exactly as sw-design.md §2 lays them out. Change the class bodies;
leave the protocols alone.

---

## Phase 2 — owner: M9 (Wave 0), amendment only

Re-established at tag `p2-frozen`, the same way M0 established the list
above at `m0-frozen`. **Wave 0 of phase 2 may edit any file this document
already lists**, including phase-1 files — re-establishing the frozen
baseline for a new phase is Wave 0's job (plan-phase-2.md §4). After
`p2-frozen`, everything below is frozen for Waves 1-4 exactly as the phase-1
list is.

**One migration author, one per phase.** A3 was phase 1's; **D3 is phase
2's**. Nobody else runs `alembic revision` against a chain phase 2 has
touched. No parallel heads (CLAUDE.md).

### New files

| File | Contents |
|---|---|
| `ra2/domain/codes.py` | `CodeAttribute`, `CodeValue`, `CodeImportError`, `CodeTableImportResult`, the `CodelistImportSchema` Pydantic shape matching `codes-2018.json` — **types and schema only**; `validate_import`'s body is D1's |
| `ra2/domain/codelist_coverage.py` | `CoverageStatus`, `CodeUsage`, `ColumnCoverage` — **types and signature only**; `compute_coverage`'s body is D1's. Split from `codes.py` per sw-design.md §14.3 (see "Documented deviations" below) |
| `ra2/domain/feature.py` | `Kind`, `Grain`, `ValueType`, `MatchingRuleKind`, `MatchingRule`, `Operator`, `Filter`, the seven `DerivationType`s and their dataclasses, `DerivationSpec`, `EXPLORATORY_FEATURE_CAP` — **shape only, no evaluator** (Q1) |
| `ra2/domain/fingerprint.py` | `FingerprintInput` and the `compute_fingerprint` **signature only**; the body is D2's |
| `ra2/services/codelist_service.py` | constructor + typed method signatures; bodies E1 |
| `ra2/services/feature_service.py` | constructor + typed method signatures; bodies E2 |
| `ra2/api/v1/codelists.py` | constructor-free stub router; bodies F1 |
| `ra2/api/v1/features.py` | constructor-free stub router; bodies F2 |
| `ra2/ui/components/derivation_builder.py` | **signature only** — the Wave 4 seam (plan-phase-2.md §3); body G3 |
| `ra2/ui/components/feature_sets_table.py` | **signature only** — same seam; body G3 |
| `ra2/persistence/migrations/versions/20260912_0000_4995824acfe4_*.py` | empty stub revision wired into the chain; D3 fills it in |

### Amended files (already frozen at M0; re-frozen here)

| File | What changed |
|---|---|
| `ra2/domain/ids.py` | + `CodeTableImportId`, `CodeAttributeId`, `ColumnMappingId`, `FeatureConfigId`, `FeatureId` |
| `ra2/persistence/models.py` | + `CodeTableImport`, `CodeAttribute`, `CodeValue`, `ColumnMapping`, `FeatureConfig`, `Feature` ORM classes; `Evaluation.feature_config_id` becomes a real `ForeignKey("feature_config.id")` |
| `ra2/services/protocols.py` | + `EnumCodeTableProvider` (the Wave 2 seam, plan-phase-2.md §3 / E6-style) |
| `ra2/services/container.py` | + `codelist: CodelistService`, `feature: FeatureService` |
| `ra2/services/errors.py` | + `CodelistImportError`, `FeatureValidationError`, `FeatureConfigFrozenError` |
| `ra2/services/readmodels.py` | + `CodeAttributeView`, `ColumnMappingView`, `CodelistImportResult`, `FeatureView`, `FeatureConfigView`, `FeatureSetSummary`; `CensusColumnView.in_config`'s docstring now says phase 2 makes it real |
| `ra2/api/schemas.py` | + every request/response model for the two new routers |
| `ra2/api/deps.py` | + `CodelistServiceDep`, `FeatureServiceDep` |
| `ra2/api/v1/router.py` | + the two new routers |
| `ra2/infra/config.py` | + `Settings.codelists_dir` |
| `ra2/main.py` | + `codelist_service`, `feature_service` construction and wiring into `Services` |

### Stubs — a body is expected; the file is **not** frozen (phase 2)

| Path | Owner |
|---|---|
| `ra2/domain/codes.py` *(`validate_import` body)*, `ra2/domain/codelist_coverage.py` *(`compute_coverage` body)* | D1 |
| `ra2/domain/feature.py` *(catalogue validation helpers)*, `ra2/domain/fingerprint.py` *(body)* | D2 |
| `ra2/persistence/repositories/{codelist,feature}_repo.py`, `ra2/persistence/migrations/versions/**` | D3 |
| `ra2/ui/components/{seg,rof,readout,fingerprint_badge}.py` (or additions to `primitives.py`) | D4 |
| `ra2/services/codelist_service.py` | E1 |
| `ra2/services/feature_service.py` | E2 |
| `ra2/api/v1/codelists.py` | F1 |
| `ra2/api/v1/features.py` | F2 |
| `ra2/ui/views/codelists_view.py` | G1 |
| `ra2/ui/views/features_view.py`, `ra2/ui/state.py` *(additions)* | G2 |
| `ra2/ui/components/{derivation_builder,feature_sets_table}.py` *(bodies)* | G3 |

---

## Phase 3 — owner: M17 (Wave 0), amendment only

Re-established at tag `p3-frozen`, the same way M9 established the phase-2
list at `p2-frozen`. **Wave 0 of phase 3 may edit any file this document
already lists**, including phase-1 and phase-2 files — re-establishing the
frozen baseline for a new phase is Wave 0's job (plan-phase-3.md §4). After
`p3-frozen`, everything below is frozen for Waves 1-4 exactly as the two
lists above are.

**One migration author, one per phase.** A3 was phase 1's, D3 phase 2's;
**H3 is phase 3's**. Nobody else runs `alembic revision` against a chain
phase 3 has touched. No parallel heads (CLAUDE.md).

**This is the commit where the codebase gains the ability to make an outbound
request at all.** `pyproject.toml` gains `openai` and `nvidia-ml-py`;
`.importlinter`'s `one-llm-seam` contract gains `pynvml`; `ra2/infra/
ollama_client.py` is the first module in the repo allowed to import `openai`
and `ra2/infra/gpu.py` the first allowed `pynvml`. The loopback guard lives in
`OllamaLLMClient.__init__` and has **no opt-out** (mvp-spec.md §19.10,
sw-design.md §15.5, plan-phase-3.md §15 F4).

### New files

| File | Contents |
|---|---|
| `ra2/domain/prompt.py` | `SlotName`, `Slot`, `SLOTS`, `REQUIRED_SLOTS`, `PromptValidationCode`, `PromptValidationError`, `PromptTemplateDraft`, `FeatureBlockEntry`, `ResolvedPrompt` — **types and signatures only**; `validate_template` / `render_feature_block` / `resolve_template` / `estimate_tokens` / `compute_template_fingerprint` bodies are H1's |
| `ra2/domain/extraction.py` | `RunStatus`, `EvaluationSize`, the mvp-spec.md §10.3 shapes (`FeatureAnswer`, `EntityAnswer`, `ExtractionOutput`), `ParseIssueCode`, `ParseIssue`, `ParsedValue`, `ParsedExtraction`, `ParseFailure` — **types and signatures only**; `build_output_schema` / `parse_output` bodies are H2's |
| `ra2/infra/gpu.py` | `GpuInfo`, the `GpuProbe` protocol, `StaticGpuProbe`, `probe_for` — frozen; `NvmlGpuProbe`'s body is H4's |
| `ra2/services/prompt_service.py` | constructor + typed signatures; bodies I1. **No `update_template` — the absence is the contract** (sw-design.md §15.1) |
| `ra2/services/evaluation_service.py` | constructor + typed signatures; bodies I2 |
| `ra2/services/run_service.py` | constructor + typed signatures; bodies I3 |
| `ra2/api/v1/prompt_templates.py` | stub router; bodies K1. **No `PATCH`/`PUT` route, ever** |
| `ra2/api/v1/evaluations.py`, `ra2/api/v1/runs.py`, `ra2/api/v1/models.py` | stub routers; bodies K2 |
| `ra2/infra/ollama_client.py` | `OllamaLLMClient`, `OllamaModelCatalog`, `LOOPBACK_HOSTS` — stub; bodies H4. The **only** module that may import `openai` |
| `ra2/ui/views/prompts_view.py` | stub; body L1 |
| `ra2/ui/views/evaluation_view.py` | stub; body L2 |
| `ra2/ui/components/progress_card.py`, `ra2/ui/components/ollama_settings.py`, `ra2/ui/components/prompt_preview.py` | **signatures only** — the Wave 4 seam (plan-phase-3.md §3.1); bodies L3 |
| `ra2/persistence/migrations/versions/20260913_0000_9e90e50a151f_phase_3_prompts_and_runs.py` | the **whole** phase-3 schema — not the stub plan-phase-3.md §5.1 originally asked for (P3-D11). H3 still owns `migrations/versions/**` from Wave 1 |
| `tests/test_p3_contract.py` | this wave's exit criteria as tests — lead-owned, frozen |
| `tests/fixtures/fake_llm.py` | `FakeLLMClient`, `StaticModelCatalog`, `DEFAULT_MODELS` — seeded with a minimal working body so the root fixtures do not wait on Wave 1; **owned and extended by H4** |

### Amended files (already frozen; re-frozen here)

| File | What changed |
|---|---|
| `ra2/domain/ids.py` | + `PromptTemplateId`, `RunId`, `ExtractionId` |
| `ra2/domain/llm.py` | + `ModelInfo`, `EndpointStatus`, `ModelCatalog`, and (by amendment) `Extraction.retry_count` and `LlmEndpointError`. `LLMClient` **unchanged** — confirming that was part of this wave's job (plan-phase-3.md §5.1) |
| `ra2/persistence/models.py` | + `PromptTemplate`, `EvaluationFeature`, `Run`, `Extraction`, `ExtractionValue`, `ExtractionEntity`; `Evaluation` gains `prompt_template_id`, `prompt_language`, `temperature`, `seed`, `size`, `selected_models_json`, `launched_at` |
| `ra2/services/protocols.py` | + `PromptResolver` (the Wave 2 seam, plan-phase-3.md §3.1) |
| `ra2/services/container.py` | + `prompt: PromptService`, `evaluation: EvaluationService`, `run: RunService` |
| `ra2/services/errors.py` | + `PromptTemplateInvalidError`, `PromptTemplateCitedError`, `EvaluationLockedError`, `LlmEndpointError`. **No new `FindingCode`s** |
| `ra2/services/readmodels.py` | + `PromptTemplateView`, `SlotView`, `ResolvedPromptView`, `ModelChoiceView`, `ConnectionView`, `EvaluationDraftView`, `RunProgressView`, `RunView`, `ProvenanceView`, `EvaluationView` |
| `ra2/api/schemas.py` | + every request/response model for the four new routers |
| `ra2/api/deps.py` | + `PromptServiceDep`, `EvaluationServiceDep`, `RunServiceDep` |
| `ra2/api/v1/router.py` | + the four new routers |
| `ra2/infra/config.py` | + `llm_timeout_s`, `llm_max_retries`, `run_concurrency`, `gpu_vram_gb`, `gpu_name`; `llm_base_url` defaults to `http://127.0.0.1:11434/v1` |
| `ra2/main.py` | + `llm_client`, `model_catalog`, `gpu_probe` keyword arguments and the three new services' construction |
| `ra2/ui/shell.py` | + the eighth `NavItem`: `prompts`, group `Configure`, `/prompts`, after `features`, `built=False` |
| `ra2/ui/components/icons.py` | + `ALIGN_LEFT`, wired into `NAV_ICONS` |
| `tests/conftest.py` | + `fake_llm`, `fake_model_catalog`, `static_gpu` root fixtures, and `app_factory` now substitutes all three by default — **no test in layers 1-4 talks to a live endpoint or a real GPU** |
| `pyproject.toml` | + `openai`, + `nvidia-ml-py` |
| `.importlinter` | `one-llm-seam`'s forbidden list gains `pynvml`, and (by amendment) `allow_indirect_imports = True` — `ra2.services` legitimately imports the `GpuProbe` protocol from `ra2.infra.gpu`, so without it a static `import pynvml` in the probe reads as three broken chains. The AST gates in `tests/test_p3_contract.py` are what actually hold the seam. |
| `mvp-spec.md` | §3 (PydanticAI dropped), §5 (+ `prompt_template`, + `evaluation_feature`, `evaluation`/`run`/`extraction` columns), §8.5 (the snapshot lives on `evaluation_feature`), §10.2 (a row, not a file), §14 N3 (the probe is a library load) |
| `CLAUDE.md` | the third migration author; "no egress at all in phase 1" -> loopback only |

### Stubs — a body is expected; the file is **not** frozen (phase 3)

| Path | Owner |
|---|---|
| `ra2/domain/prompt.py` *(bodies)* | H1 |
| `ra2/domain/extraction.py` *(bodies)* | H2 |
| `ra2/persistence/repositories/{prompt,evaluation,run,extraction}_repo.py`, `ra2/persistence/migrations/versions/**` | H3 |
| `ra2/infra/ollama_client.py`, `ra2/infra/gpu.py` *(`NvmlGpuProbe`)*, `tests/fixtures/fake_llm.py` | H4 |
| `ra2/ui/components/primitives.py` *(additions)* | H5 |
| `ra2/services/prompt_service.py` | I1 |
| `ra2/services/evaluation_service.py` | I2 |
| `ra2/services/run_service.py` | I3 |
| `ra2/api/v1/prompt_templates.py` | K1 |
| `ra2/api/v1/{evaluations,runs,models}.py` | K2 |
| `ra2/ui/views/prompts_view.py` | L1 |
| `ra2/ui/views/evaluation_view.py`, `ra2/ui/state.py` *(additions)* | L2 |
| `ra2/ui/components/{progress_card,ollama_settings,prompt_preview}.py` *(bodies)* | L3 |

### The two-line nav exception

`ra2/ui/shell.py` and `ra2/ui/views/__init__.py` stay frozen through Wave 4
with **one exception each, declared up front** (plan-phase-3.md §6.1): L1 and
L2 may each flip exactly their own `built` flag and add exactly their own line
to `register_all`. Nothing else in either file. L3 touches neither. Phase 2
left this implicit and paid for it with a lead fix-up commit (`e386a66`).

---

## Documented deviations phase 3 (M17) introduces

| # | Decision | Why |
|---|---|---|
| **P3-D1** | The service-layer exception is `PromptTemplateInvalidError`, not `PromptValidationError` | plan-phase-3.md §5.1 names `PromptValidationError` **twice** — once as `domain/prompt.py`'s payload type and once as `services/errors.py`'s exception. Two different things cannot share one name across two modules without an aliased import at every call site. The phase-2 precedent settles which keeps it: `domain.codes.CodeImportError` (payload) versus `services.errors.CodelistImportError` (exception). The domain keeps the plan's name; the exception is renamed. |
| **P3-D2** | `RunStatus` and `EvaluationSize` live in `ra2/domain/extraction.py`, not in a module of their own | sw-design.md §15 is silent on where they go, so CLAUDE.md's "follow the nearest existing pattern" applies: `DeliveryStatus` sits in `domain/delivery.py`, the domain module for its area. A fifth domain module would also belong to no wave — plan-phase-3.md §6's ownership matrix names exactly four (`ids`, `prompt`, `extraction`, `llm`). |
| **P3-D3** | `extraction.retry_count` and `run.error` — additive beyond mvp-spec.md §5 | sw-design.md §15.4 requires the retry count to be "carried back on the `Extraction` and rendered in the progress card's metrics line", and the design's failed-run row offers a "log" action that needs something to show. Same pattern as SD4's additive `corpus` columns. |
| **P3-D4** | `run.prompt_template_fingerprint` is stored on the run, though it is derivable through `prompt_template_id` | mvp-spec.md §19.8 requires a run's **own record** to be sufficient to reproduce it, and the design's reproducibility card renders the fingerprint beside the model digest. A join is not a record. |
| **P3-D5** | `evaluation.prompt_template_id` is **nullable**; `run.prompt_template_id` is not | The design has a "Save draft" button, so the row exists before the inputs are final — and a draft saved on a database with no template yet must still be savable. The launch transaction is what requires one, and a `run` always cites exactly one. |
| **P3-D6** | Launching an evaluation whose `feature_config` is not frozen raises `FeatureValidationError`, not a new error type | plan-phase-3.md §5.1's error list does not name one, K2 wants 422, and "the set this launch cites is not frozen" is exactly a blocking validation message with exactly that status. `FeatureConfigFrozenError` means the opposite (an edit of a set that *is* frozen) and would have read backwards. |
| **P3-D7** | `extraction_entity` has a plain string primary key, not a composite `(extraction_id, entity_kind, entity_ref)` | Entities are **captured, never scored** (mvp-spec.md §10.3). A model that repeats `(kind, ref)` would violate a composite key and cost the run a record — for output nothing reads. Same treatment `code_value` gets (P2-D6): no dedicated id `NewType`, because nothing joins against one by id outside its own extraction. |
| **P3-D8** | `tests/conftest.py`'s `app_factory` substitutes `llm_client`, `model_catalog` and `gpu_probe` by **default** | plan-phase-3.md §11: "everything inside `just test` and `just e2e` must pass on a machine with no GPU and nothing listening on 11434". Leaving the real adapters as the default would make that a per-test discipline instead of a property of the suite. The real ones are still reachable — H4's adapter tests construct them directly against a local stub. |
| **P3-D9** | `ra2/infra/gpu.py` exposes `probe_for(name, vram_gb)` beyond the three names plan-phase-3.md §5.1 lists | "The override wins, else NVML" is one rule and belongs in one place. Putting the conditional in `create_app()` instead would have put logic in a composition root that is meant to be wiring only (sw-design.md §3). |
| **P3-D12** | `LlmEndpointError` lives in `ra2/domain/llm.py`, not in `services/errors.py`, and is **not** a `ServiceError` | H4's amendment (`contracts/amendments/feat-p3-llm-adapter.md`, item 3) found that M17 put the error in `services/errors.py` and documented it as "raised by `OllamaLLMClient` at construction" — an import `ra2/infra/` may not make. H4 recommended an `ignore_imports` edge, the mirror of M0-D4; that was **declined**, because unlike M0-D4 there is a clean alternative. The exception belongs with the protocol it guards, the same shape `domain.codes.CodeImportError` has, and `services/errors.py` re-exports it so both adapters keep one import site. It is not a `ServiceError` because nothing catches it: a non-loopback endpoint fails `create_app()` outright, and "unreachable" is deliberately not an exception at all (200 with `reachable: false`). |
| **P3-D11** | M17 writes the **real** phase-3 migration, not the empty stub plan-phase-3.md §5.1 asked for | That instruction was written from phase 2's shape, where Wave 0 added only *new* tables: an empty revision left a gap that broke nothing and D3 filled it in. Phase 3 also **alters `evaluation`** — the moment `models.py` declares the seven new columns, every phase-1 and phase-2 test that seeds an evaluation row fails with `no such column`. §5.2 is explicit that "every phase-1 and phase-2 test still green — this wave adds surface, it does not change behaviour", and that is the stricter criterion. plan-phase-3.md §5.1/§6/§7 are corrected in the same commit. **H3 remains phase 3's one migration author** and still owns `migrations/versions/**` from Wave 1; its brief becomes "verify this one, and add your own revision on top if Wave 1 needs more". |
| **P3-D10** | `openai>=3.0` pulls in `httpx2`, not `httpx` | Noted rather than decided: the SDK's own dependency. It means H4 stubs the endpoint with `httpx2.MockTransport` / `ASGITransport` passed as `http_client`, **not** with `respx` (which targets `httpx` 0.x). Recorded here because `pyproject.toml` is frozen after this wave, and an agent discovering it mid-Wave-1 would otherwise need an amendment to add a test dependency it does not actually need. |

---

## The census seam

The one that lets Wave 2 run in parallel (plan-m0-m5.md E6):

```python
# ra2/services/protocols.py
class CensusMaterialiser(Protocol):
    async def materialise(
        self, session: AsyncSession, corpus_id: CorpusId, cells: CensusInput
    ) -> None: ...
```

`corpus_service.freeze()` calls it inside the freeze's single transaction.
**B1 calls it, B2 implements it, neither waits.** Until B2 ships,
`create_app()` defaults to `_MissingCensusMaterialiser`, which raises rather
than silently writing an empty census.

---

## Documented deviations M0 introduces

Additive, cheap to reverse, and none of them silent. SD1-SD10 are
sw-design.md's own and were signed off on 2026-09-07 (P2).

| # | Decision | Why |
|---|---|---|
| **M0-D1** | `evaluation` is in `models.py`, with `feature_config_id` as a plain string and **no FK** | sw-design.md §6.3 and J3 need the corpus delete guard tested against a seeded row. Pulling `feature_config` forward would freeze a phase-2 schema nobody has reviewed. Phase 2 adds the FK in its own migration. |
| **M0-D2** | `ra2/domain/ids.py` declares nine `NewType`s, not the five plan-m0-m5.md §3.1 lists | `ObjektRowId`, `PersonRowId`, `CensusColumnId` and `EvaluationId` are needed by `models.py` on day one; declaring them now costs nothing and saves four amendments. |
| **M0-D3** | `ra2/services/{readmodels,errors,protocols,container}.py` exist and are frozen | Services must not return ORM objects (§12.7) and `ra2/ui/` cannot import `ra2/api/`, so the read models cannot live in `api/schemas.py`. They are not domain concepts either, so they live in `services/`. |
| **M0-D4** | `ra2.api` may import `ra2.infra.tasks` — the **protocols only** | `GET /api/v1/tasks/{id}` (sw-design.md §9) has no service in front of it, and inventing one would buy nothing. Declared as three `ignore_imports` lines in `.importlinter`; every infra *adapter* stays out of reach. |
| **M0-D5** | Views expose `register(services)`, not sw-design.md §8.1.5's `register(app)` | NiceGUI's `ui.page` registers on `nicegui.core.app`, the sub-application `create_app()` mounts, so passing our own `FastAPI` would be decorative. Services are what a view actually needs, and it gets them explicitly rather than reaching into `app.state`. |
| **M0-D6** | `create_app(mount_ui: bool = True)` | NiceGUI's `core.app` is a **process-wide singleton**: `ui.run_with` adds middleware to it, and Starlette refuses that once an app has served a request. Building two UI-mounted apps in one pytest session therefore raises. This is a composition-root parameter, like `settings` or `clock` — nothing downstream of `create_app()` can tell which value was used, so §12.12 is intact. |
| **M0-D7** | `record.language` is `String(16)` holding a `Language` value, not a DB enum | mvp-spec.md §4.5 requires low confidence to be stored as `mixed`; a fourth language in a future delivery should be a value, not a migration. |
| **M0-D8** | `*_json` columns are `Text`, holding an app-serialised JSON string | B1's golden import report is asserted byte-for-byte, so the application must control key order and separators. A JSON-typed column would not let it. |
| **M0-D9** | `compute_census(table_name, cells, *, columns, record_count, top_n)` takes `columns` explicitly | In EAV a column that is empty in every row can be absent from the scan entirely. h08 requires it to appear at 0 %, so the canonical header is an input, not an inference. |
| **M0-D10** | `FindingCode` has 16 members, four beyond plan-m0-m5.md §3.1's list | `DIALECT_DETECTED`, `ROW_REJECTED_PARSE_ERROR`, `SET_UNRESOLVED` and `CP1252_CANARY_ZERO` are each required by a rule in mvp-spec.md §4.2-§4.4 or by SD6, and h09's canary expectation has no other code to assert on. |

---

## Documented deviations phase 2 (M9) introduces

| # | Decision | Why |
|---|---|---|
| **P2-D1** | `feature_config.description` — additive beyond mvp-spec.md §5 | The design's feature-sets table has a "Description" column (e.g. "Conditions + probes") mvp-spec never named. Same pattern as SD4's additive `corpus` columns. |
| **P2-D2** | `feature_config.version` — additive beyond mvp-spec.md §5 | The design shows "Weather & conditions v3" beside older v2/v1 sets sharing a name — the same monotonic-per-name shape `corpus.version` already has. Design fidelity is a requirement (sw-design.md §8.2). |
| **P2-D3** | `compute_coverage` (and `ColumnCoverage`/`CoverageStatus`) live in a new `domain/codelist_coverage.py`, not in `domain/codes.py` | sw-design.md §14.3's package layout names two files with two concerns; plan-phase-2.md §5.1 named both bodies as `codes.py`'s. sw-design.md wins ties on *how* (CLAUDE.md, plan-phase-2.md line 13) — the split is followed as drawn. |
| **P2-D4** | The features router is rooted at `/api/v1/feature-configs`, not `/api/v1/features` | plan-phase-2.md's own §3 (P17) and §9 (F2) name different base paths for the same router. `/feature-configs` matches the resource the router actually roots on (`feature_config`) and §9's F2 section is the more specific of the two statements. |
| **P2-D5** | `ui/components/feature_sets_table.py`'s `sets` parameter is typed `FeatureSetSummary`, not `FeatureSetView` | plan-phase-2.md §3's snippet named `FeatureSetView` informally; the read model this wave actually defines (services/readmodels.py, matching the design's `FeatureSet` shape) is `FeatureSetSummary`. One type, not two to reconcile later. |
| **P2-D6** | `code_value` has no dedicated id `NewType` | plan-phase-2.md §5.1 names five new ids, not six; nothing joins against a `code_value` by id outside its own attribute. Its ORM primary key is a plain `String`, same treatment as `delivery_file.set_key`. |
| **P2-D7** | `services/readmodels.py` gains `CodelistImportResult`, beyond the five view types plan-phase-2.md §5.1 names | `codelist_service.import_file`'s return type needs a shape carrying `no_change` alongside the import's identity — same reasoning as M0-D2: declaring it now costs nothing and saves an amendment. |
| **P2-D8** | `ra2/api/deps.py` gains `CodelistServiceDep`/`FeatureServiceDep`, though plan-phase-2.md §5.1 does not list `deps.py` as a Wave 0 deliverable | F1/F2 (Wave 3) do not own `deps.py` (§6's ownership matrix has no row for it) and cannot amend a frozen file to get their routers' dependency injection — Wave 0 is the only wave that can add it without an amendment. |
| **P2-D9** | `features_view.py`'s `_visible_features` filters, sorts and pages the already-fetched feature list itself, rather than pushing those into a `FeatureService.get()` parameter | A post-close code review flagged this against sw-design.md §8.1.4 ("sort/page parameters are always part of the service call signature, even when the dataset is small enough to sort in memory"). `FeatureService.get()` returns one whole feature set in one call — there is no server-side page to ask for, and a config tops out at a few dozen rows (`EXPLORATORY_FEATURE_CAP` alone bounds a third of it) — so this is presentation over data already handed over, not a second copy of a service's own logic, the same class of operation as `bar()`'s percentage clamp. Recorded here rather than refactored: giving `get()` a `TableState` parameter for a dataset this bounded would buy correctness nothing and cost the view an extra round trip per sort/filter click. |
| **P2-D10** | No `GET /api/v1/codelists/attributes/{id}/codes`-style "one attribute's code table" endpoint, despite plan-phase-2.md §9's F1 prose naming one | `GET /codelists/columns`'s per-column `coverage.codes` already returns the full per-code usage list (code, count, share, label, `in_codelist`) sorted by usage — everything `design/code-feature/README.md`'s edit-zone codes table needs once a corpus and column are selected. Nothing in the design shows that table rendered without corpus/column context (the "Usage" column and the "18 mapped" header line are both corpus-scoped counts, not codelist-only ones), so a second endpoint would duplicate this one for a case the design never draws. Originally reasoned only in `ra2/api/v1/codelists.py`'s module docstring; a post-close code review asked that this go through the documented-deviation path instead of living only in a docstring. |

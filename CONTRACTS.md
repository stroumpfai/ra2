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
| `justfile` | `dev test e2e lint fmt migrate revision census-export setup-e2e eval`, + `dev-agent`, `dev-reload`, `reset`, `reset-seed`, `check-data`. "Final" has been amended four times; it means *by amendment only*, not *never* |
| `.importlinter` | the §1.1 layer contract, api/ui independence, the pure-domain and one-LLM-seam contracts |
| `.pre-commit-config.yaml` | ruff, ruff-format, mypy, import-linter, the `no-real-data` hook |
| `scripts/check_no_real_data.py` | the hook's implementation; **name and content** (`fix-c1-real-data-guard`). No third-party import — it reaches `ra2.domain.parsing.headers` rather than keeping a second copy of the column vocabulary |
| `.github/workflows/ci.yml` | `no-real-data` first, on a bare interpreter; layers 1-3 on `ubuntu-latest` **and** `windows-latest`; E2E linux-only with traces on failure; `alembic check` |
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
| `ra2/persistence/session.py` | async engine, the **four** connect-time PRAGMAs (`secure_delete=ON` added by `fix-b3-deletion-path`), session factory, `session_scope` |
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
| `ra2/services/evaluation_service.py` | constructor + typed signatures; bodies I2. **Post-phase:** the constructor gains `endpoint_prober: EndpointProber` and the class gains `test_connection()` (P3-D19) and `catalogue()` (P3-D21) |
| `ra2/services/run_service.py` | constructor + typed signatures; bodies I3 |
| `ra2/api/v1/prompt_templates.py` | stub router; bodies K1. **No `PATCH`/`PUT` route, ever** |
| `ra2/api/v1/evaluations.py`, `ra2/api/v1/runs.py`, `ra2/api/v1/models.py` | stub routers; bodies K2 |
| `ra2/infra/ollama_client.py` | `OllamaLLMClient`, `OllamaModelCatalog`, `LOOPBACK_HOSTS` — stub; bodies H4. The **only** module that may import `openai` |
| `ra2/ui/views/prompts_view.py` | stub; body L1 |
| `ra2/ui/views/evaluation_view.py` | stub; body L2 |
| `ra2/ui/components/progress_card.py`, `ra2/ui/components/ollama_settings.py`, `ra2/ui/components/prompt_preview.py` | **signatures only** — the Wave 4 seam (plan-phase-3.md §3.1); bodies L3. **Post-phase:** `ollama_settings_dialog` gains an `on_test` callback and the `PROBE_WORDS` rendering table (P3-D19) |
| `ra2/persistence/migrations/versions/20260913_0000_9e90e50a151f_phase_3_prompts_and_runs.py` | the **whole** phase-3 schema — not the stub plan-phase-3.md §5.1 originally asked for (P3-D11). H3 still owns `migrations/versions/**` from Wave 1 |
| `tests/test_p3_contract.py` | this wave's exit criteria as tests — lead-owned, frozen |
| `tests/fixtures/fake_llm.py` | `FakeLLMClient`, `StaticModelCatalog`, `DEFAULT_MODELS` — seeded with a minimal working body so the root fixtures do not wait on Wave 1; **owned and extended by H4**. **Post-phase:** + `StaticEndpointProber` (P3-D19) |

### Amended files (already frozen; re-frozen here)

| File | What changed |
|---|---|
| `ra2/domain/ids.py` | + `PromptTemplateId`, `RunId`, `ExtractionId` |
| `ra2/domain/llm.py` | + `ModelInfo`, `EndpointStatus`, `ModelCatalog`, and (by amendment) `Extraction.retry_count` and `LlmEndpointError`. `LLMClient` **unchanged** — confirming that was part of this wave's job (plan-phase-3.md §5.1). **Post-phase:** + `LOOPBACK_HOSTS`, `ALLOWED_SCHEMES`, `classify_endpoint`, `is_loopback_url`, `require_loopback` (moved down from `ra2/infra/ollama_client.py`, which re-exports them), and + `PROBE_TIMEOUT_S`, `ProbeCode`, `ProbeResult`, `EndpointProber` (P3-D19, P3-D20) |
| `ra2/persistence/models.py` | + `PromptTemplate`, `EvaluationFeature`, `Run`, `Extraction`, `ExtractionValue`, `ExtractionEntity`; `Evaluation` gains `prompt_template_id`, `prompt_language`, `temperature`, `seed`, `size`, `selected_models_json`, `launched_at` |
| `ra2/services/protocols.py` | + `PromptResolver` (the Wave 2 seam, plan-phase-3.md §3.1) |
| `ra2/services/container.py` | + `prompt: PromptService`, `evaluation: EvaluationService`, `run: RunService` |
| `ra2/services/errors.py` | + `PromptTemplateInvalidError`, `PromptTemplateCitedError`, `EvaluationLockedError`, `LlmEndpointError`. **No new `FindingCode`s** |
| `ra2/services/readmodels.py` | + `PromptTemplateView`, `SlotView`, `ResolvedPromptView`, `ModelChoiceView`, `ConnectionView`, `EvaluationDraftView`, `RunProgressView`, `RunView`, `ProvenanceView`, `EvaluationView`. **Post-phase:** + `ConnectionProbeView` (P3-D19), + `CatalogueView` (P3-D21) |
| `ra2/api/schemas.py` | + every request/response model for the four new routers. **Post-phase:** + `TestConnectionRequest`, `ConnectionProbeResponse` for `POST /api/v1/models/test` (P3-D19) |
| `ra2/api/deps.py` | + `PromptServiceDep`, `EvaluationServiceDep`, `RunServiceDep` |
| `ra2/api/v1/router.py` | + the four new routers |
| `ra2/infra/config.py` | + `llm_timeout_s`, `llm_max_retries`, `run_concurrency`, `gpu_vram_gb`, `gpu_name`; `llm_base_url` defaults to `http://127.0.0.1:11434/v1` |
| `ra2/main.py` | + `llm_client`, `model_catalog`, `gpu_probe` keyword arguments and the three new services' construction. **Post-phase:** + `endpoint_prober` (P3-D19) |
| `ra2/ui/shell.py` | + the eighth `NavItem`: `prompts`, group `Configure`, `/prompts`, after `features`, `built=False` |
| `ra2/ui/components/icons.py` | + `ALIGN_LEFT`, wired into `NAV_ICONS`. **Post-phase:** + `REFRESH`, + `TRASH` for the Import row actions (P3-D22) |
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

## Phase 4 — owner: M27 (Wave 0), amendment only

Re-established at tag `p4-frozen`, the same way M17 established the phase-3
list at `p3-frozen`. **Wave 0 of phase 4 may edit any file this document
already lists**, including phase-1, phase-2 and phase-3 files —
re-establishing the frozen baseline for a new phase is Wave 0's job
(plan-phase-4.md §4). After `p4-frozen`, everything below is frozen for
Waves 1-4 exactly as the three lists above are.

**One migration author, one per phase.** A3 was phase 1's, D3 phase 2's,
H3 phase 3's; **S4 is phase 4's**. Nobody else runs `alembic revision` against
a chain phase 4 has touched. No parallel heads (CLAUDE.md).

**This is the first phase since M0 that adds no dependency and no lint
contract.** `pyproject.toml` and `.importlinter` are byte-unchanged, and
`tests/test_p4_contract.py` asserts both — a decision with no gate behind it
is a preference. The Wilson interval is a closed form over one constant, and
the layer rule already forbids everything this phase could get wrong:
`ra2/domain/ranking.py` **cannot** reach a session or a repository, which is
what makes "ranking is a derivation, not a table" structural rather than
aspirational (sw-design.md §16.5).

**`sw-design.md` §16 is this wave's first and largest deliverable.** Unlike
phases 2 and 3, phase 4 began with no architecture section — §15.8 had parked
scoring — so §16 was written before any code in this wave, and `SD16`-`SD22`
with it (plan-phase-4.md §0).

### New files

| File | Contents |
|---|---|
| `ra2/domain/stats.py` | `WILSON_Z_95`, `Interval`, `EMPTY_INTERVAL`, `TieMark`, `TiedCell` — **types and signatures only**; `wilson` / `suppressed` / `mark_ties` / `macro` bodies are S1's |
| `ra2/domain/ranking.py` | `FeatureCell`, `ModelRanking`, `SeparatingFeature` — types and signatures only; `rank_models` / `separating_features` bodies are S1's. **Imports nothing outside `domain`** — that is the §16.5 invariant, and `import-linter` is what holds it |
| `ra2/domain/matching.py` | signatures only; `is_empty` / `normalise` / `matches` bodies are S2's. **No fuzzy matching and no accent folding** — D6, and §8.4 flags accent folding as a question this phase's numbers are meant to answer |
| `ra2/domain/scoring.py` | `Outcome`, **`ScoreMetric`** (the closed 16), `COUNT_METRICS`, `ALL_LANGUAGES`, `LabelledCase`, `ExploratoryCase`, `ScoreRow`, `CrossTab` — types and signatures only; `classify` / `aggregate_goal1/2/3` bodies are S2's |
| `ra2/domain/derivation.py` | `RecordProjection`, `DerivationError` — types and signature only; `evaluate` body is S3's. **plan-phase-2.md Q1's deferral, coming due** |
| `ra2/services/scoring_service.py` | constructor + typed signatures; bodies T1. Implements `Scorer`. **No `resume` entry point — resume is implicit** in `score_run`, and a second one would be a second answer to "how far did it get" |
| `ra2/services/results_service.py` | constructor + typed signatures; bodies T2 |
| `ra2/services/ranking_service.py` | constructor + typed signature; body T3 |
| `ra2/persistence/repositories/score_repo.py` | stub; bodies S4. **No `scored_at` — do not add one** (§16.1, F5) |
| `ra2/persistence/repositories/mismatch_repo.py` | stub; bodies S4. The **tag-preserving upsert**; `DELETE`-then-`INSERT` is the wrong answer (SD21) |
| `ra2/persistence/repositories/ground_truth_repo.py` | stub; bodies S4. Implements `GroundTruthProvider`. Holds **no session** — one is passed per call, because the pass owns the transaction boundary |
| `ra2/api/v1/results.py` | stub router; bodies U1. An unscored run is **200 with `scored: false`**, never a 404 |
| `ra2/api/v1/presence.py`, `ra2/api/v1/ranking.py` | stub routers; bodies U2 |
| `ra2/ui/views/results/` | **a package, not a module** (SD22) — `__init__` (route, shell, tab strip) + `extraction_tab` V1, `presence_tab` V2, `ranking_tab` V3. Signatures only; the Wave 4 seam (plan-phase-4.md §3.1) |
| `ra2/ui/components/stat_cells.py`, `ra2/ui/components/contingency_table.py` | **signatures only**; bodies S5. The tie marker is **shape-coded on the neutral accent**, and S5's tests assert the three states structurally so it cannot be reverted into a colour |
| `ra2/persistence/migrations/versions/20260916_0501_e5145f27bf8c_phase_4_scoring_and_results.py` | the **whole** phase-4 schema, written in full for P3-D11's reason: it alters `evaluation`. S4 still owns `migrations/versions/**` from Wave 1 |
| `tests/test_p4_contract.py` | this wave's exit criteria as tests — lead-owned, frozen |

### Amended files (already frozen; re-frozen here)

| File | What changed |
|---|---|
| `ra2/domain/ids.py` | + `MismatchId`. `score` gets none — it carries mvp-spec.md §5's composite key, the same treatment `extraction_value` gets |
| `ra2/persistence/models.py` | + `Score`, `Mismatch`; `Evaluation` gains `min_cell_count`; `Run` gains the two cascading relationships. Also + **`UtcDateTime`** (P3-D15, its own commit) |
| `ra2/services/protocols.py` | + `GroundTruthProvider`, `Scorer`, `ScoringStatus` (the Wave 2 seams, plan-phase-4.md §3.1) |
| `ra2/services/container.py` | + `scoring: ScoringService`, `results: ResultsService`, `ranking: RankingService` |
| `ra2/services/errors.py` | + `RunNotScoredError`, `RunNotScoreableError`. **No new `FindingCode`s** — a suppressed cell is a rendered state, not an import defect; phases 2 and 3 set this precedent twice |
| `ra2/services/readmodels.py` | + `SuppressedCell`, `MetricCell`, `Cell`, `RunDescriptorView`, `ModelColumnView`, `BreakdownRowView`, `BreakdownView`, `FeatureScoreRow`, `ByLanguageRow`, `ByLanguageView`, `ExploratoryRow`, `ExtractionTabView`, `Goal1Companion`, `PresenceRow`, `CrossTabView`, `FlagInconsistencyRow`, `PerRecordRow`, `PresenceTabView`, `RankingRow`, `SeparatingRow`, `RankingTabView`, `ScoringStatusView` |
| `ra2/services/export_service.py` | + the `presence_records_csv` signature (plan-phase-4.md C11); body is T2's |
| `ra2/api/deps.py` | + `ScoringServiceDep`, `ResultsServiceDep`, `RankingServiceDep` |
| `ra2/api/v1/router.py` | + the three new routers |
| `ra2/main.py` | + the `ground_truth` keyword argument and the three new services' construction |
| `ra2/infra/config.py` | **unchanged.** `min_cell_count` already existed and now serves as the per-evaluation *default*, not the value itself |
| `ra2/ui/shell.py` | **unchanged.** `results` has existed as a `NavItem` with `built=False` since phase 1, icon already wired — the first phase since M0 to add no nav entry |
| `mvp-spec.md` | §5 (+ `evaluation.min_cell_count`; `score.metric` documented as a closed vocabulary carrying counts; `score.language` NOT NULL), §11.4 (the column that makes "per evaluation" true), §11.5 (presence rate is reported, never scored) |
| `CLAUDE.md` | the fourth migration author |
| `pyproject.toml`, `.importlinter` | **byte-unchanged, and asserted so** (see above) |

### Stubs — a body is expected; the file is **not** frozen (phase 4)

| Path | Owner |
|---|---|
| `ra2/domain/{stats,ranking}.py` *(bodies)* | S1 |
| `ra2/domain/{matching,scoring}.py` *(bodies)* | S2 |
| `ra2/domain/derivation.py` *(bodies)* | S3 |
| `ra2/persistence/repositories/{score,mismatch,ground_truth}_repo.py`, `ra2/persistence/migrations/versions/**` | S4 |
| `ra2/ui/components/{stat_cells,contingency_table}.py` *(bodies)*, `ra2/ui/components/primitives.py` *(additions)*, `ra2/ui/theme.py` *(additions)* | S5 |
| `ra2/services/scoring_service.py` | T1 |
| `ra2/services/results_service.py`, `ra2/services/export_service.py` *(`presence_records_csv` body, signature amended — P4-D3)* | T2 |
| `ra2/services/ranking_service.py` | T3 |
| `ra2/api/v1/results.py` | U1 |
| `ra2/api/v1/{presence,ranking}.py` | U2 |
| `ra2/ui/views/results/__init__.py`, `ra2/ui/views/results/extraction_tab.py`, `ra2/ui/state.py` *(additions)* | V1 |
| `ra2/ui/views/results/presence_tab.py` | V2 |
| `ra2/ui/views/results/ranking_tab.py` | V3 |

### The one-line nav exception

Phase 3 declared this for two agents and phase 2 paid for leaving it implicit
(`e386a66`). Phase 4 needs it for **one**: **V1 may flip exactly the `results`
`built` flag and add exactly its own line to `register_all`.** Nothing else in
either file. V2 and V3 touch neither — they render into V1's tab shell. There
is no merge conflict this phase, which is the point of saying so in advance.

---

## Reset and discard — a slice, not a phase

Landed in **one commit**, after `p4w4-green`, to
`plan-reset-and-discard.md` and `sw-design.md` §18. There is **no Wave 0 and
no new frozen baseline**: the slice is three agents' worth of work done in one
pass, it adds one service and two scripts, and it re-freezes nothing. The
frozen files it touches are amended in the ordinary way, one amendment file
per branch name (`contracts/amendments/feat-reset-*.md`).

**No migration, and that is the design.** No new table, no new column, no new
Alembic head — a direct consequence of `R-D2`: the trace a discard leaves is
an exported CSV, not an audit row (SD23, §18.3).

### New files

| File | Contents |
|---|---|
| `ra2/services/lifecycle_service.py` | The three previews, the three discards, the two guards, and a run's export rows. **The only destructive verb in this layer**, and the only place §18.2's guards are decided |
| `ra2/api/v1/discard.py` | Shared translation for the three `DELETE` routes — the two mapping functions and the 409 builder. **Not a router**: the routes stay on the resource routers they belong to |
| `ra2/ui/components/discard_dialog.py` | One dialog, two states (§18.5). Holds no state and no business logic; `blocked` and `has_exportable` are read off the view, never re-derived. Both callbacks are **awaitable** |
| `scripts/reset_data.py` | `just reset` — resolves `Settings` as the app does, prints the plan, refuses without the token, then `alembic upgrade head` in-process. Never `metadata.create_all()` (Do-NOT #10) |
| `scripts/seed_dev.py` | `just reset-seed` — drives the **services** to a delivery, a corpus, codelists, a feature set and a prompt version. Writes its own synthetic delivery; imports only column *names* from `ra2.domain.parsing.headers` |

### Amended files (already frozen)

| File | What changed | Amendment |
|---|---|---|
| `ra2/services/errors.py` | + `RunActiveError`, `TaggedWorkPresentError` (carries the count), `DeliveryCitedError`. **No new `FindingCode`s** — a refused discard is a rendered state, the fourth time this precedent applies | `feat-reset-discard-service` |
| `ra2/services/readmodels.py` | + `DiscardPreviewView`, `ScoreExportRow`, `MismatchExportRow`, `RunExportView`, `DataDirView` | `feat-reset-discard-service` |
| `ra2/services/container.py` | + `lifecycle: LifecycleService` | `feat-reset-discard-service` |
| `ra2/main.py` | + `LifecycleService` construction — wiring only, and **no host-path store**: a host-path delivery's files are the analyst's own | `feat-reset-discard-service` |
| `ra2/services/export_service.py` | + `run_scores_csv`, `run_mismatches_csv`. They **take the rows** (`P4-D3`), and the mismatch file carries `analyst_tag` — the half a re-run cannot reproduce | `feat-reset-discard-api` |
| `ra2/api/schemas.py` | + `DiscardPreview`, `DiscardResponse`. A body rather than a bare 204: nothing else records that a discard happened | `feat-reset-discard-api` |
| `ra2/api/deps.py` | + `LifecycleServiceDep` | `feat-reset-discard-api` |
| `justfile` | + `reset`, `reset-seed`. The token is positional with an **empty default**, so the bare recipe removes nothing | `feat-reset-cli` |
| `ra2/persistence/models.py` | **unchanged.** No schema change, no migration, no new head | — |
| `pyproject.toml`, `.importlinter` | **unchanged.** No dependency, no new contract — the layer rule already forbids what this slice could get wrong | — |

### Not frozen, and changed

| Path | What |
|---|---|
| `ra2/persistence/repositories/{run,evaluation,delivery}_repo.py` | `delete`, and the counts the previews and G2 need. `delivery_repo.count_citing_corpora` exists because `corpus.delivery_id` is `SET NULL` and **the database will not refuse on its own** |
| `ra2/api/v1/{runs,evaluations,deliveries}.py` | the three `DELETE` routes, the three previews, and the two run exports |
| `ra2/ui/views/evaluation_view.py` | the `discard` row action — **in the status cell**, beside `log` and `Resume`, because the runs table's five column widths are the design's own |
| `ra2/ui/shell.py` + the seven built views | `shell(data_dir=…)` and the header chip. The value is a `Settings` one and `ra2/ui/` may not import `ra2/infra/`, so it arrives through `services.lifecycle.data_dir()` — one line per view |
| `sw-design.md` | **§18 is written**, `SD23` added to §13 |
| `plan-reset-and-discard.md` | §2.1 (no delivery list exists), §6 and §7 (four frozen files the table missed) — corrected in the same commit, per CLAUDE.md |

---

## Risk remediation — a slice, not a phase

Findings from `risk-assesment.md`, the external review at `616bf2b`, landed one
at a time after `p5w4-green`. **No Wave 0 and no new frozen baseline**: each is
a fix to a control that already exists, and none adds a table, a column or an
Alembic head. The frozen files a fix touches are amended in the ordinary way,
one amendment file per branch.

Progress is tracked in `risk-assesment.md` — a `Status` column in §1 and §5,
and one §8 entry per finding closed. The register in §4 is left as written.

### Amended files (already frozen)

| File | What changed | Amendment |
|---|---|---|
| `scripts/check_no_real_data.py` | **Rewritten: content-shaped.** Keeps the `.gitignore` name patterns as defence one and adds the check that decides what a file *is*, through `ra2.domain.parsing.headers.classify_header` — the importer's own classifier, so there is no second copy of the column vocabulary to drift. A delivery-shaped file is refused unless it is under `tests/fixtures/deliveries/` **and** its keys were invented rather than delivered. + `--all` | `fix-c1-real-data-guard` |
| `.github/workflows/ci.yml` | + the `no-real-data` job, **first and depending on nothing** — no `uv sync`, no cache, no `needs`. C1's third gap was that CI never ran the guard at all | `fix-c1-real-data-guard` |
| `.pre-commit-config.yaml` | The hook's name and description say *name and content*; `entry` runs through `uv run python`, because the guard is a 3.14 source file and a hook that dies with a `SyntaxError` fails open | `fix-c1-real-data-guard` |
| `justfile` | + `check-data` | `fix-c1-real-data-guard` |
| `CLAUDE.md` | + **Do-NOT #13** (never open, query, print or paste `data/` or `RA2_DATA_DIR`), verbatim from §12, and the paragraph saying the item is addressed to the agent reading the file. **Also, retroactively:** the *Loopback only* agreement's transport half, edited in `39c72e0` without an amendment | `fix-c2-agent-data-access` |
| `ra2/domain/census.py` | + `SHAREABLE_TYPE_HINTS`, `sample_is_shareable` — the one statement of which columns' **values** may leave the corpus. In `domain` because `census_service` and `export_service` both need the same answer, the shape `classify_endpoint` has for the loopback rule | `fix-b1-census-value-samples` |
| `ra2/services/readmodels.py` | + `CensusColumnView.top_values_withheld`. Not decoration: `top_values == ()` already meant *empty in every row* (h08), which is the opposite conclusion for feature selection | `fix-b1-census-value-samples` |
| `ra2/api/schemas.py` | + `CensusColumnResponse.top_values_withheld`, so the distinction survives the wire. `tests/api/openapi_snapshot.json` regenerated — five lines, one optional boolean, additive | `fix-b1-census-value-samples` |
| `ra2/services/export_service.py` | + `CLASSIFICATION_COMMENT`, written by `_write_csv` — the one place **all six** exports pass through, so the line is guaranteed rather than remembered. `_CENSUS_CSV_HEADER` gains `top_values_withheld` | `fix-b1-census-value-samples` |
| `tests/test_m0_contract.py` | `test_claude_md_carries_the_do_not_list` counts the Do-NOT items **against `sw-design.md` §12** instead of against the literal `12`. Bumping the literal would have left the same trap: a magic number here is one that gets changed without anyone opening the other document, which is the drift the assertion exists to catch | `fix-c2-agent-data-access` |
| `ra2/persistence/session.py` | + a **fourth** connect-time PRAGMA, `secure_delete=ON`. SQLite frees a deleted row's page with its bytes intact, so a discarded run's `mismatch.evidence_span` — verbatim narrative — stayed readable in the file. Chosen over the `VACUUM`-after-discard B3 asked for: a `VACUUM` is a second thing to remember, means nothing in WAL until a checkpoint, and cannot run inside the transaction the discard holds (`SD29`) | `fix-b3-deletion-path` |
| `ra2/infra/config.py` | **− `Settings.exports_dir`.** Documented as "where CSV exports are written" and written by nothing: all six exports stream to the browser. `just reset` was clearing an empty directory while the copies that matter sat in Downloads — `Settings.host` from A4, the same shape (`SD30`) | `fix-b3-deletion-path` |
| `ra2/ui/components/discard_dialog.py` | + `EXPORT_LEAVES_RA2`, beside `EXPORT_PROMPT`. `SD23` pays for the destructive verb with an export carrying `evidence_span`, so the one place the app says *this cannot be undone* is also the one place it offers to make a copy nothing here can delete. Asserted, like the other two sentences | `fix-b3-deletion-path` |
| `scripts/reset_data.py` | − the `exports_dir` target, and a docstring saying why there is no longer one | `fix-b3-deletion-path` |
| `tests/test_p3_contract.py` | `path.relative_to(REPO_ROOT).as_posix()` in the `openai` and `pynvml` seam gates, which compared against `ra2/infra/…` and so were **permanently red on Windows with the seam intact**. The idiom already existed in `test_gpu_probe.py` and `test_ollama_client.py` | `fix-windows-paths-and-eol` |
| `ra2/infra/ollama_client.py` | **not frozen** — the transport half of the loopback rule (`SD27`). Listed here because it is the other finding closed in this slice | — |
| `ra2/domain/llm.py` | + `EndpointStatus.TIMED_OUT`. "Unreachable" and "answered but did not finish in time" are two different repairs — one is *start Ollama*, the other is *the model is slower than the bound*. `OllamaEndpointProber` has drawn this line since P3-D19 (`ProbeCode.TIMEOUT`, whose test says collapsing the two "would put the analyst on the wrong trail"); the **generation** path collapsed them because the enum had no value to say it with | `fix-evaluation-timeout-and-progress` |
| `ra2/infra/config.py` | `llm_timeout_s` **120 → 600**. 120 was never measured against a reasoning model: on the reporting host a 9.7 B thinking model answered two features over one sentence in 136 s cold / 126 s warm, almost all of it inside the response's `reasoning` field, so every call timed out and no amount of waiting produced a row. Still a bound, and a cheaper one than before: a timeout is no longer retried, so a dead endpoint costs `_MAX_CONSECUTIVE_ENDPOINT_ERRORS` intervals rather than that many × `llm_max_retries + 1` | `fix-evaluation-timeout-and-progress` |
| `ra2/services/readmodels.py` | `RunView.error` is **no longer `FAILED`-only**. `_run_view` nulled it for every other status and the view offered "log" only to a failed run, so `_finish` wrote why a run stopped and two layers discarded it before the one screen that could show it. An `interrupted` run is the case that needs it most: the row offers Resume whether the endpoint timed out, was never there, or the process died under it, and only the reason decides whether pressing it helps | `fix-evaluation-timeout-and-progress` |
| `ra2/services/readmodels.py` | + `RunView.ordinal` — the run's place in its evaluation by creation order. The ordinal is a property of the **set**: the runs table sorts on four keys and pages at ten, so a number derived from the rows on screen differs per sort. `run_service.run_ordinals` states it once, so the table cannot disagree with the discard dialog and the mismatch toolbar, which have named runs "run 2" from an `ORDER BY run.id` query since phase 4/5 | `fix-evaluation-timeout-and-progress` |
| `ra2/ui/views/evaluation_view.py` | **`DEV` becomes a chip beside the status word rather than replacing it** (design README §2 draws the replacement). Sound where a dev run is the exception; `RA2_DEV_RECORD_MAX` is 50 and the development seed is 12 records, so *every* run an analyst makes while learning the product is dev-sized and the Status column rendered one constant string — `running`, `done` and `interrupted` were the same cell. No test caught it because the cell already carried `data-status`/`data-dev`, legible to the suite and to nobody else. Row tint unchanged | `fix-evaluation-timeout-and-progress` |
| `ra2/ui/views/evaluation_view.py` | **Status column 84px → 200px**; the other four keep the design's widths and gain `.td-clip`. 84 fits what the design draws there — one word — not what the cell holds: `discard` was put here in phase 5 *to keep* the five drawn widths, `Resume` was already beside it, `log` and the `DEV` chip followed. `table-layout:fixed` does not clip, so keeping 84 drew the controls over the next column; clipping them would hide buttons, the defect `theme.py`'s `.td-clip` note describes. The `overflow:auto` well exists so the table "scrolls horizontally rather than collapsing a column" (README §2), which is what makes the widening affordable | `fix-evaluation-timeout-and-progress` |
| `ra2/ui/components/progress_card.py` | A `running` card renders `elapsed_ms`. `_eta_ms` is `None` until a record commits, so a run with nothing committed rendered `0 / 12 · running` over a bar at zero and did not change — nothing separating a worker that was extracting from one whose process had died. mvp-spec.md **N6** asks for visible progress; the number was already in `RunProgressView` and only the finished branch rendered it | `fix-evaluation-timeout-and-progress` |
| `ra2/services/evaluation_service.py` | `get()` takes optional `connection` / `models`, so a caller holding the endpoint's state hands it back rather than having it re-probed. plan-phase-3.md **C3** — "re-checked on view load and when refresh is pressed, **never on a timer**" — written at the seam instead of remembered at the call site. `models is not None`, not truthiness: an unreachable endpoint's catalogue is legitimately `()` | `fix-evaluation-timeout-and-progress` |
| `ra2/ui/views/evaluation_view.py` | **The progress poll no longer calls `reload()`.** It called `evaluation.get()`, which probed `/api/tags` twice, at a 0.2 s interval — ten requests a second at the endpoint the worker was waiting on, plus a `pynvml` probe five times a second, for the length of a run. + `refresh_progress` (progress column only), a `POLL_FAST_S`→`POLL_SETTLED_S` ladder, and polling on **page load** when a run is in flight: it started only from Launch and Resume, so a browser refresh or a second tab froze mid-run | `fix-evaluation-timeout-and-progress` |
| `ra2/ui/views/evaluation_view.py` | `_settled` reads `RunService.list_runs`, not `EvaluationView.progress`. Only `RunService` reclaims — `self._active` is the sole record of which runs *this* process executes — so off the unreclaimed statuses the view called a run abandoned by a dead process **live**. The underlying split remains: after a crash the progress cards say `running` and the runs table says `interrupted`, from one read | `fix-evaluation-timeout-and-progress` |
| `ra2/services/run_service.py` | The endpoint bound becomes two numbers: `_MAX_CONSECUTIVE_ENDPOINT_ERRORS` (3) once the run has committed a row, `_MAX_ENDPOINT_ERRORS_BEFORE_FIRST_ROW` (1) before. Three is right for an endpoint that has demonstrably answered *for this run*; a run that has never produced a row has no such evidence, so the first failure is the verdict. Each costs up to `RA2_LLM_TIMEOUT_S` (now 600 s) because the adapter's own retries are already spent — three of them was half an hour re-learning what the first said. Counted over the **run**, so a resume inherits its earlier attempt's evidence | `fix-evaluation-timeout-and-progress` |
| `ra2/services/errors.py` | + `RunNotActiveError` — `RunActiveError`'s mirror. Two verbs guard the same two statuses from opposite sides: discard refuses an **active** run because a worker is writing to it (G1), Stop refuses an **inactive** one because nothing is executing it. A Stop that quietly succeeded on a finished run would rewrite a `done` outcome as an interruption that never happened | `fix-evaluation-timeout-and-progress` |
| `ra2/services/run_service.py` | + `cancel(run_id)` and a per-run `asyncio.Task`. A stopped run is `interrupted` with `_ERROR_CANCELLED` — **no new `RunStatus`, no migration**: partial work kept, nothing auto-restarted, Resume the one way out is already exactly right, and what differs is *why*. The status is written from the **caller's** task, not the worker's `except CancelledError`, so it needs no `asyncio.shield` and is correct the moment `cancel` returns. `TaskRunner.cancel` was **not** added: the affordance is per-run, a job covers the whole evaluation, and `ra2/infra/tasks.py` is a frozen protocol | `fix-evaluation-timeout-and-progress` |
| `ra2/api/v1/runs.py` | + `POST /{run_id}/cancel`, 409 on an inactive run. Answers with the run rather than a task id: `resume` starts work and returns something to poll, this ends it. One additive path in `tests/api/openapi_snapshot.json` | `fix-evaluation-timeout-and-progress` |
| `ra2/ui/views/evaluation_view.py` | + `Stop` in the status cell for `queued`/`running` — the one case that had no action at all. G1's "nothing to offer while a worker is writing to the row" (§18.5) is right about *discard*, which destroys rows still being produced; Stop destroys nothing. **No confirmation dialog**, deliberately: discard asks because it is irreversible, and a dialog guarding a reversible act is one people learn to click through | `fix-evaluation-timeout-and-progress` |
| `ra2/domain/llm.py` | + `LlmEndpointError.attempts`. `Extraction.retry_count` counts retries for a call that **answered**; a call that exhausted its attempts writes no `extraction` row by design, so the attempts spent on the records that never answered — the most expensive in a run — were counted nowhere, against mvp-spec.md §10.4's "bounded, counted **and visible**". `None` when no call was made; `retries + 1` otherwise, since a non-retryable failure costs exactly one. Surfaced on `run.error` via `run_service._endpoint_cost`, kept separate from the records-not-extracted count because most of those were never attempted | `fix-evaluation-timeout-and-progress` |
| `justfile`, `scripts/dev_agent.py` | **`just dev` loses `--reload`; `just dev-reload` appears with `--reload-dir ra2`.** A second reproduction, after all of the above shipped: the run ended `interrupted` at `0 / 12` carrying `_ERROR_INTERRUPTED_BY_RESTART`, and the terminal said why in uvicorn's own words — `WatchFiles detected changes… Reloading`. The message was **true**; the recipe was the defect. `--reload` watches the whole working directory for `*.py`, recursively, which here includes `tests/`, `scripts/` and every `.claude/worktrees/agent-*` full copy of this project — so any edit anywhere in the tree kills a worker that runs for tens of minutes. N6's restart-safety is what made that recoverable rather than lost, and it is a guarantee about consequences, not a licence to restart. `dev-agent` drops the watcher outright: an agent is by definition writing `*.py` here, so its only reachable outcome is an agent killing the run it launched to look at | `fix-evaluation-timeout-and-progress` |
| `ra2/services/run_service.py` | **`_reclaim` stops calling live runs dead.** It runs on every read path and the Evaluation view polls those twice a tick for the length of a run, so any instant where the row says `running` and no claim is held is one a poll lands in — writing `_ERROR_INTERRUPTED_BY_RESTART`, a specific claim about a process that is fine. Two such instants: the worker claimed the run **after** `_start` committed `queued -> running` (the worker then extracted into a row marked `interrupted`, and the table offered a **Resume** that would have put a second worker on it); and `cancel` had no claim at all, because `Task.cancel()` only schedules — the worker unwinds and drops `_active` while `cancel` still awaits `_finish_cancelled`, whose status re-read then correctly declines to overwrite the reclaim, so a stop an analyst asked for is filed as a crash. The claim now precedes the `running` write, and `_stopping` covers `cancel`'s span; `_cancel_requested` could not double as it, being discarded inside the gap. Both gaps are microseconds wide, so `test_reclaim_races.py` **constructs** the interleaving through the existing `session_factory=` override rather than waiting for it | `fix-evaluation-timeout-and-progress` |
| `ra2/infra/logging.py` (new), `ra2/main.py`, `ra2/infra/config.py` | **An operational log — stderr only, ids and counts only.** A run is tens of minutes and said nothing for all of them; item 12's cause was legible only in uvicorn's own output. `data-handling.md` §5 read *"no logging and no audit trail anywhere in RA2 (`mvp-spec.md` §13)"* — but §13 is "UI surfaces" and says nothing about logging, and the claim is corroborated nowhere else. The **reason** beside it ("keeping narrative text out of log files") is sound and is about *content*, so §5.1 now states it as a rule: generated ids, counts, statuses, `EndpointStatus` codes, model tags and durations may appear; narrative, prompts, model output, column values and `unfall_uid` may never. stderr and no file, so nothing to retain, nothing for `just reset` and nothing under `RA2_DATA_DIR`. `RA2_LOG_LEVEL` is a level, **not** a `log_prompts` flag — there is no level at which narrative is logged | `fix-evaluation-timeout-and-progress` |
| `ra2/persistence/migrations/env.py` | `fileConfig(..., disable_existing_loggers=False)`. The default is **True** and `alembic.ini` names only alembic's own loggers, so applying it set `disabled = True` on `ra2` — which drops records silently, with no handler, no level and no error. Migrations run in-process in every backend and E2E fixture, so the run log worked when a developer watched it and vanished the moment a test looked. Each test in `test_run_log_carries_no_data.py` asserts lines **were** emitted before asserting what is not in them, so the default cannot come back quietly | `fix-evaluation-timeout-and-progress` |
| `ra2/services/run_service.py`, `ra2/main.py` | **Restart detection moves to process start; `_active` and `_stopping` go.** `RunRepository.list_running`'s docstring has always said a caller finds these runs *"on the next startup"* — and it had **no caller**. Reclaiming on every read path was the improvisation, and the claim discipline it needed was where the races of the row above lived. `reclaim_orphans` relabels every `running` row unconditionally, which is sound at exactly one moment: at startup this process executes nothing, so there is no set to consult and no window to get wrong. **A read never writes a status.** This also closes the split recorded against `evaluation_service.get` — progress cards and the runs table gave two answers about one run after a crash — since both now read rows already reconciled. Still relabelled, never restarted (§15 F8); still no migration | `fix-evaluation-timeout-and-progress` |
| `ra2/main.py` | `lifespan=` on the `FastAPI` constructor, holding the one `reclaim_orphans` call. Not `add_event_handler`: `on_startup` is the deprecated path and `filterwarnings = ["error"]` would make the `DeprecationWarning` a test failure. `ui.run_with` captures `app.router.lifespan_context` and calls it inside its own wrapper, so NiceGUI's lifecycle and this one compose — checked in its source, not assumed. Guarded by `tests/test_reclaim_is_called_once.py` in `test_p3_contract.py`'s `openai`/`pynvml` shape: the property is a *location*, which no behavioural test can assert, and an unguarded relabel called from anywhere but startup is the defect it replaced | `fix-evaluation-timeout-and-progress` |
| `ra2/infra/config.py`, `ra2/infra/ollama_client.py`, `ra2/persistence/models.py`, `ra2/services/readmodels.py`, `ra2/api/schemas.py` | **`+ RA2_LLM_REASONING_EFFORT`, pinned on `run`.** `plan-fix-evaluation-runs.md` §1 measured 136 s/126 s and concluded the model was slow; the measurement was of the wrong call. Same record, same schema, same resident model: **190 s** as the adapter sends it (977 completion tokens, 3 259 chars of `reasoning`) against **6 s** with `reasoning_effort: "none"` — both correct. Reasoning is a property of *how the model is asked*, not of the model, so raising `llm_timeout_s` treated a symptom that then outgrew the new bound. A **setting**, not a constant, because whether a thinking model extracts better is the question RA2 exists to answer; **pinned** on the run beside the model digest, temperature and seed, because two runs that asked different questions must not record identical provenance (§19.8). Refused at construction outside `none|low|medium|high` — Ollama maps no others and an unmappable value costs one `RA2_LLM_TIMEOUT_S` per record to discover. Verified end to end: 12/12, 0 parse failures, 0 retries, 2 min 40 s | `fix-evaluation-timeout-and-progress` |
| `ra2/persistence/migrations/versions/…090e7fdc12c5…` | **The one phase-5 revision.** `plan-phase-5.md` C7 expected none and CLAUDE.md names an author anyway "because the rule that matters is that there is exactly one". This is it: single head, additive, nullable, no data rewritten, arriving from a reproduced defect rather than a wave. No backfill — rows written before the column sent no `reasoning_effort` at all, so nothing here knows what default applied; `NULL` reads "not recorded", `run.gpu_name`'s convention | `fix-evaluation-timeout-and-progress` |
| `pyproject.toml`, `scripts/dev_agent.py` | **`+ tzdata` (dev group), and `dev-agent` migrates before serving.** `just revision` could not run on Windows at all: `alembic.ini` sets `timezone = UTC` and Windows ships no tz database, so it died on "Can't locate timezone: UTC" — `SD33`'s finding in a new place, a recipe that cannot run on the platform it is run from. (Its `ruff_format` post-write hook also fails on `console_scripts.ruff`; the file is still written, so that one is recorded and not fixed.) Separately, `dev-agent` mints a **fresh, unmigrated** dir, so once startup began reading the `run` table it stopped booting — fixed in the launcher, not by making `reclaim_orphans` tolerate a missing table, because a launcher that produces an unusable instance is the defect | `fix-evaluation-timeout-and-progress` |
| `ra2/services/protocols.py`, `ra2/services/run_service.py`, `ra2/main.py` | **`SD17`'s chain existed only in the design.** §16.1 says — *"the run worker's terminal `done` submits the scoring job; there is no Score button, and the design draws none"* — and no such code existed: `RunService` took no scorer and `ScoringService.submit` had **no caller anywhere in `ra2/`**. Measured on a real run: a finished, `is_scoreable` run with `scored_features: 0`. The Results view told the analyst *"Scoring starts automatically… use Re-score"* with no Re-score control in `ui/`, and its "scoring…" state polls a task id only the uncalled `submit` returns. `+ ScoreSubmitter` (a **new** protocol, not a method on `Scorer`: that is the results views' *read*, this is the worker's *write*), `+ run_service._chain_scoring` (re-reads the status — only `done`, never a partial corpus), and `ScoringService` now built **before** `RunService` in the composition root | `fix-evaluation-timeout-and-progress` |
| `tests/backend/services/run/test_scoring_is_chained.py` (new) | **The seam nothing crossed.** Every scoring, results, ranking and mismatch conftest calls `score_run` by hand, and `tests/e2e/conftest.py` seeds `score` rows directly — its own comment says *"nothing in the product writes those except the run worker and the scoring pass"*. Each layer was green alone. The load-bearing test goes through **`create_app`**, because a service-level test with a scorer passed in by hand would have been green throughout. Also recorded: `InlineTaskRunner` **cannot model chained work** — a job that submits another reaches the shared engine's aiosqlite connections from a second event loop, so `build_app` gained a `task_runner` override and the integration test uses `AsyncioTaskRunner`, which is what production runs | `fix-evaluation-timeout-and-progress` |
| `ra2/services/run_descriptor.py` (new), `ra2/domain/fingerprint.py` | **The results identity line was placeholder data.** `corpus_label=evaluation.corpus_id`, `record_count=0` hardcoded, `config_fingerprint=evaluation.feature_config_id` — so every Results, Ranking and Mismatches board read `Corpus 01a0bebb-… · 0 records` over numbers from thousands of them, on the line `RunDescriptorView` calls *"a score without its config is not a result"*. **The stub was triplicated** byte-identically across three services, which is why it survived four phases and why no single fix would have worked; they now share one builder. `+ compute_set_fingerprint` (**amendment**, frozen file) hashes the sorted §8.5 per-feature fingerprints — sorted because a set has no order, **not** de-duplicated because a fingerprint carries the feature's key. The id and the hash answer different questions: the id says *which row*, the hash says *whether two sets ask the same thing* | `fix-evaluation-timeout-and-progress` |
| `.gitignore` | **unchanged, deliberately.** Adding `Unfall.csv` would be the name-shaped fix again, and it would block the hazard fixtures, which carry the same names | — |
| `pyproject.toml`, `.importlinter`, `tests/conftest.py` | **unchanged.** No dependency, no new contract, no new root fixture | — |

### New files

| File | Contents |
|---|---|
| `.gitattributes` | **`* -text`** — no line-ending conversion, in either direction. `CLAUDE.md` requires byte-exact fixtures and four tests compare committed bytes; with `core.autocrlf=true` and no attributes they fail on Windows and pass everywhere else. **Not** `text=auto eol=lf`, which would rewrite the twenty delivery hazards stored *with* CRLF on purpose (`fix-windows-paths-and-eol`) |
| `data-handling.md` | **Outputs, retention, destruction, incident path, decommission condition** — recommendations 11, 14 and 20 of the review, and the page F1 says turns an accepted risk into a managed one. Every project decision in it is marked **DECISION REQUIRED** and left blank: the procedures are verifiable from the code and belong to an implementing agent, the retention period and the named owner are not (`fix-b3-deletion-path`) |
| `.claude/settings.json` | The Do-NOT #13 deny rules — `Read(./data/**)`, `Read(./var/**)`, `Bash(sqlite3 *)`, and the matching `sandbox.filesystem.denyRead`. **Committed, not ignored**: a control in an ignored directory protects the one machine it was written on (`fix-c2-agent-data-access`) |

### Not frozen, and changed

| Path | What |
|---|---|
| `.gitignore` | `.claude/` -> `.claude/*` + `!.claude/settings.json`, so the deny rules ship with the repository. Nothing else about the directory changes |
| `ra2/services/census_service.py` | `_to_view` applies the sample rule — **read time, never write time**. A corpus is immutable, so a write-time filter would leave every corpus frozen before the rule still carrying its values into every export; this covers those and needs no migration (the `SD19` shape) |
| `ra2/ui/views/census_view.py`, `ra2/api/v1/census.py` | The third bar state and the wire field. The view branches on the **flag**, not on an empty tuple, so the property holds for any caller of the read model |
| `tests/unit/census/test_sample_rule.py` *(new)*, `tests/backend/api/census/`, `tests/backend/services/census/`, `tests/ui/test_census_view.py` | The rule at four layers. Twenty-five existing tests moved by one line because every export's preamble grew |
| `tests/backend/scripts/test_check_no_real_data.py` | The guard's tests. Built by asking `generate_hazards` for a **genuine** delivery file and putting delivered-entropy keys in it — a guard tested against the author's idea of a delivery is a guard tested against nothing. No real value appears |
| `tests/backend/infra/test_ollama_client.py` | *The environment cannot move the socket* — eleven tests, with a positive control |
| `mvp-spec.md` | §6 — value samples are shown and exported only for coded columns, every aggregate survives, and every CSV opens with a classification line. A *what* change, so it lands here first (CLAUDE.md) |
| `sw-design.md` | `SD27`, `SD28` and §7's sample-rule section; §15.5's transport paragraph; **§12 gains the thirteenth invariant** and the paragraph on why it is the only one addressed to people rather than to code. Then `SD29`, `SD30`, §4.4's fourth pragma, §10's `RA2_DATA_DIR` gloss, and **§18.7 — *What a discard erases***, the section §18 was missing: §18.1 said *whole objects* and nothing said what *removed* meant (`fix-b3-deletion-path`) |
| `README.md` | The loopback rule now states both halves. Then: exports do **not** live under the data directory (two claims corrected), and the documentation map and *Real data never enters the repository* point at `data-handling.md` (`fix-b3-deletion-path`) |
| `tests/backend/services/lifecycle/test_discard_erasure.py` *(new)* | After `discard_run`, a planted evidence span is absent from the database **and its WAL** — through the real service, against the real temp-file database. A positive control before the discard, and a control with `secure_delete` off showing the bytes survive without the pragma, so neither assertion can pass vacuously (`fix-b3-deletion-path`) |
| `risk-assesment.md` | The `Status` column, and §8 |
| `ra2/ui/shell.py` | `_data_dir_chip` only — `title` moves from the props *string* to the props *mapping* (`SD31`), and `html.escape` goes with it. **Not a register finding**: a defect found while working this slice, landed the same way because it is a fix to a control that already exists (`fix-ui-windows-data-dir`) |
| `tests/ui/test_data_dir_chip.py` | Two cases the POSIX `_DATA_DIR = "/srv/ra2/var"` could never have caught — a `tempfile.mkdtemp()`-shaped Windows path (the crash) and a path of *valid* escapes (the silent rewrite). The fixture had no backslash in it, which is what CLAUDE.md's *fixtures must contain the real hazards* is about, read one hazard wider than encodings (`fix-ui-windows-data-dir`) |
| `sw-design.md` *(second entry, later branch)* | `SD31` — a prop whose value did not come from the source file is assigned through the props mapping, never through the props string (`fix-ui-windows-data-dir`) |

---

## Evaluation — the exit from a launched one, a slice

`feat-evaluation-not-a-dead-end`, landed on top of `fix-ui-windows-data-dir`.
**No Wave 0, no new frozen baseline, no migration and no amendment**: one view,
its per-client state, its two test layers, and the two documents that record
why. `ra2/services/readmodels.py` stayed byte-unchanged **deliberately** — a UI
that needs a new read-model field to answer "why is this locked" is usually a
UI about to derive something it should be reading, and
`EvaluationDraftView.is_launched` already answered it.

### Not frozen, and changed

| Path | What |
|---|---|
| `ra2/ui/views/evaluation_view.py` | + `NEW_EVALUATION_LABEL`, `LAUNCHED_MESSAGE`, `EVALUATION_CREATED_MESSAGE`; `_new_evaluation`, `_new_name`, `_can_create`, `_launched_note`, `_toolbar_button`. `_save_draft` loses its create branch and `_can_save_draft` becomes the toolbar's either/or. `NO_SETUP_MESSAGE`, `UNSAVED_MESSAGE` and `MODELS_UNSAVED_MESSAGE` name the affordance that actually unblocks them (`SD32`) |
| `ra2/ui/state.py` | `EvaluationSetup`'s docstring only — **no field added**. The sentinel that `_current_evaluation`'s fallback appears to demand is unnecessary once the row is created before the redraw, and the docstring now says so rather than leaving the next reader to re-derive it (`SD32`) |
| `tests/ui/test_evaluation_view.py` | + `_seed_launch` and the `launched` fixture — the file had **no** launched-state fixture at all, which is how a permanently frozen view survived 17 cases. + three: the lock sentence and every read-only control it describes, the clone, and the toolbar's mutual exclusion. `test_with_no_evaluation_the_view_offers_save_draft_rather_than_crashing` is renamed and **re-pointed, not deleted** — it asserts the replacement affordance and that the four inert steps name it |
| `tests/e2e/test_j10_evaluation.py` | The journey runs past the launch: the lock sentence, "New evaluation", the unlocked clone read back through `GET /api/v1/evaluations`, and a tick that takes again. It leaves one inert extra draft on the session-scoped server and the docstring says why that is safe — `test_reset_discard.py` is the only later journey that depends on being newest, and it stamps its own `created_at` past every frozen-clock row for exactly this reason |
| `sw-design.md` | `SD32`, and §15.2's closing paragraph — "every edit path raises" is a rule about the row, and the view owes the other half of it |

---

## The Windows CI leg — making a permanently red gate readable, a slice

`fix-windows-ci-gate`, landed on top of `feat-evaluation-not-a-dead-end`.
**No Wave 0, no new frozen baseline, no migration and no amendment.** CI runs
layers 1–3 on Linux **and** Windows (N3) with `fail-fast: false`; the Windows
leg carried six failures, the oldest from `0461aea`, and had essentially never
been green. The six are worth less than the leg being readable again — an
always-red gate is why `SD31`'s every-page-500 under `just dev-agent` on
Windows survived until a human found it by hand. `sw-design.md` `SD33` records
the reasoning, including why the scope is four paths and not `* text=auto`.

**No fixture byte changed.** The committed blobs were always right — the
delivery hazards CRLF, the codelist, prompt and golden fixtures LF, exactly
what each generator writes. Only the *checkout* was wrong, so `.gitattributes`
states what the bytes already are; no `git add --renormalize` was needed and
none was run.

**`.github/workflows/ci.yml` and `pyproject.toml` are unchanged.** Nothing in
the workflow was wrong: it was already running the leg, already refusing to
`fail-fast`, and already uploading the JUnit XML. The failures were in the
repository, not in the gate.

### New files

| File | Contents |
|---|---|
| `.gitattributes` | Four rules, for the four paths a test compares byte-for-byte. `tests/fixtures/deliveries/hazards/** -text diff` — CRLF by construction, and `h13`'s doubled CRLF (`\r\r\n`) is destroyed by *any* text conversion, `eol=crlf` included, so `-text` is the only correct answer and `diff` keeps it reviewable. `eol=lf` for the codelist, prompt and golden fixtures. **Not** `* text=auto eol=lf`: that rewrites every tracked file and conflicts with every pending branch |
| `tests/test_fixture_line_endings.py` | The recurrence guard. Asks **git** (`git check-attr`), not the filesystem, whether every file under `tests/fixtures/*/hazards/` is pinned at all — so it answers identically on both platforms and a new hazard family added on Linux fails *there*. It does not dictate which of the two attributes a family picks; that is its generator's business |

### Not frozen, and changed

| Path | What |
|---|---|
| `tests/test_p3_contract.py` | `.as_posix()` in place of `str()` at the three `relative_to` sites. Two of them — the `openai` and `pynvml` single-seam guards — compare against a POSIX literal and so could never pass on Windows. They failed **closed**, so Do-NOT #1 was never unguarded; but CLAUDE.md names them as what makes the loopback rule a gate rather than a promise |
| `sw-design.md` | `SD33`, and §11.4's paragraph saying that "byte-exactly" includes the line endings |

The rest of `tests/` was swept for the same shape. Four sites build a
`str(path.relative_to(...))`, all of them into an *offenders* list compared
against `[]` — `test_files_chokepoint.py`, `test_migrations.py`,
`test_m0_contract.py` and `test_no_lenient_decoding.py`. A separator there
changes a failure *message*, never a verdict, so they are left alone.
`test_check_no_real_data.py` passes one into `guard.inspect`, which normalises
with `Path(path).as_posix()` before it matches anything — that one is already
correct, and deliberately so.

---

## Props provenance — the rest of the class `SD31` opened, a slice

`fix-props-provenance`, landed on top of `fix-windows-ci-gate`. **No Wave 0,
no new frozen baseline, no migration and no amendment** — nothing this slice
touches is on the frozen list. `SD31` fixed one call site, the header's
data-directory chip; this is the other forty-eight, across seventeen files.

**It is a data bug, not an accessibility one.** Reproduced against the pinned
NiceGUI, `value="{name}"` with a feature set named `draft\` parses to
`{'type': 'text', 'data-testid': 'rename-input'}` — no exception, no warning,
and **no `value` prop**. The rename box opens empty over a name the analyst
cannot see. `sw-design.md` `SD34` records the helper, the `html.escape`
question and why the recurrence guard is only a floor.

### New files

| File | Contents |
|---|---|
| `tests/ui/test_props_provenance.py` | The hazards and the floor. Four names a person can legally type — a trailing `\` (the prop that vanishes), `Unfall\next.csv\tv2` (a newline and a tab), `C:\Users\dev\sets` (the `SD31` crash), `Weather & conditions <v3>` (what `html.escape` would corrupt on its own) — each asserted to **round-trip**, `_props[key] == value`, through `feature_sets_table`'s input and its two `icon_button`s and through `data_table`'s sort header. Plus the static floor: an `ast` walk of `ra2/ui/**` refusing an interpolation inside a text-carrying prop's value, and a case proving the floor catches the pre-`SD34` line it was written for |

### Not frozen, and changed

| Path | What |
|---|---|
| `ra2/ui/components/primitives.py` | + `data_props(element, {...})`, the one way a data-derived prop is assigned, returning the element so it composes with the kit's chained builders. Nine of its own helpers went through it — `icon_button`, `tick`, `chip`, `field_select`, `radio_option`, `segmented_control`, its clear segment, the pagination arrows and the page-size options — which is why every view inherited the bug (`SD34`) |
| `ra2/ui/components/__init__.py` | Re-exports `data_props` |
| `ra2/ui/components/data_table.py` · `derivation_builder.py` · `feature_sets_table.py` · `ollama_settings.py` · `stat_cells.py` | Column keys and labels, codes and code labels, the analyst-typed set name and `RA2_LLM_BASE_URL` move to the mapping. `import html` **goes** from three of them: it prevented none of the four parser failures and would have put `&amp;` on screen (`SD34`) |
| `ra2/ui/views/census_view.py` · `codelists_view.py` · `evaluation_view.py` · `features_view.py` · `file_report_modal.py` · `import_view.py` · `mismatches_view.py` · `prompts_view.py` · `results/extraction_tab.py` · `results/presence_tab.py` · `results/ranking_tab.py` | Filenames, corpus names, column names, codes, feature keys, model tags and option values move to the mapping. `evaluation_view._attr` — `html.escape(quote=True)` under another name, one caller — is **deleted**; `features_view`'s `from html import escape` goes the same way. `SD32` is untouched: the toolbar's either/or, `LAUNCHED_MESSAGE` and the clone are not on this slice's path |
| `sw-design.md` | `SD34`, and a pointer from `SD31` to it |

**What deliberately stays a props string.** About sixty interpolations remain
and every one is source-decided: an `int` (`colspan`, `data-rank`,
`data-max-height-px`), an enum's `.value`, a `"true"`/`"false"` chosen from a
`bool`, and the `data-testid` slots whose callers all pass literals. Provenance
is the test, not the character set — and a props string that reads like the
design's own HTML is worth keeping where nothing data-shaped can reach it.

---

## Phase 5 — owner: M35 (Wave 0), amendment only

Re-established at tag `p5-frozen`, the same way M27 established the phase-4
list at `p4-frozen`. **Wave 0 of phase 5 may edit any file this document
already lists**; after `p5-frozen`, everything below is frozen for Waves 1-4
exactly as the lists above are.

**One migration author, one per phase.** A3 was phase 1's, D3 phase 2's,
H3 phase 3's, S4 phase 4's; **W1 is phase 5's** — and the expectation is that
nobody runs `alembic revision` at all (plan-phase-5.md C7). `mismatch` has
carried its `UNIQUE (run_id, record_id, feature_id)` and its
`ix_mismatch_run_id_feature_id` since phase 4, which is what the filtered list
and the grouped tally are built on. `tests/test_p5_contract.py` asserts the
chain is still five revisions long.

**The second phase in a row that adds no dependency and no lint contract, and
the first that adds no test fixture.** `pyproject.toml` and `.importlinter` are
byte-unchanged and the contract test pins the whole dependency list;
`tests/fixtures/scored_corpus.py` already produces mismatches, because phase 4
built the hazard set that makes them. A phase that needs nothing new is the
return on having built the foundations deliberately.

**`sw-design.md` §17 is this wave's first deliverable**, written before any
code in it, the way §16 was written before phase 4's Wave 0 — and `SD24`-`SD26`
with it. §17 was reserved and deliberately empty from the reset-and-discard
slice onward; it is now written, and §16.9's "Mismatch review" bullet points at
it.

**This is the first phase in which a human writes to the database.** Everything
before it was append-only or job-owned. The whole of §17 follows from that
sentence, and two of its consequences are gates rather than prose:
`tests/test_p5_contract.py::test_review_has_no_edge_to_scoring` (mvp-spec.md
§12's "nothing is rescored", asserted on the AST because `import-linter` cannot
express a rule between two modules of one layer) and the `MismatchWrite` /
`set_tag` split that keeps each owner out of the other's columns.

### New files

| File | Contents |
|---|---|
| `ra2/domain/mismatch.py` | `MismatchTag` (the closed three), `OTHER_TAG` (a bucket, **not** an enum member), `TagState`/`TagFilter`, `MISMATCH_SORT_KEYS` (four keys, and **nothing that ranks "how wrong"**), `ReviewTally` — types and signatures only; the `tally` body is W1's. **Imports nothing from `ra2/`** — that is §17.3's absent edge, and `import-linter` holds it |
| `ra2/services/mismatch_service.py` | constructor + typed signatures; bodies Y1. Implements `MismatchTally` structurally. **Imports no scoring module**, and the contract test asserts it |
| `ra2/api/v1/mismatches.py` | stub router; bodies Y2. An evaluation with no mismatches is **200 with an empty list**, never a 404; an unknown tag is **422**, because the wire is closed even though the column is not |
| `ra2/ui/views/mismatches_view.py` | stub; body Z1. **A module, not a package** — the `SD22` reasoning read the other way (§17.9). Holds `TAG_LABELS`, the one rendering table where `structured_data_error` becomes "record error" (C4) |
| `tests/test_p5_contract.py` | this wave's exit criteria as tests — lead-owned, frozen |

### Amended files (already frozen; re-frozen here)

| File | What changed |
|---|---|
| `ra2/services/protocols.py` | + `MismatchTally` — the fifth seam (plan-phase-5.md §3.1). Keyed by `RunId`, and it **returns counts and nothing else**: the absence of any other method is the contract |
| `ra2/services/container.py` | + `mismatch: MismatchService` |
| `ra2/services/readmodels.py` | + `MismatchRowView`, `MismatchFeatureView`, `ReviewTallyView`, `MismatchFilters`, `MismatchListView`, and `TagFilter`/`TagState` re-exported. **Five, where plan-phase-5.md §5.1 named four**: `MismatchFeatureView` is the Feature filter's option list, which cannot be the tally strip because the strip is scoped to the current filter and would collapse to one entry the moment a feature was picked. *Amended at Wave 1 (`feat-p5-mismatch-domain-persistence.md`): `name` dropped from `MismatchFeatureView` and `ReviewTallyView` — `Feature` has no display name, every read model in the app resolves this as `feature.key`, and two fields that are always equal are the second source of truth this codebase refuses everywhere else* |
| `ra2/services/errors.py` | **unchanged, and asserted so.** Phases 2, 3 and 4 each added errors; a phase that adds none is a phase that introduced no new failure. An unknown mismatch is a `NotFoundError`; an unknown tag never reaches the service |
| `ra2/services/export_service.py` | + the `mismatches_csv` signature and `_MISMATCHES_CSV_HEADER`; body is Y1's. **It takes the rows** (`P4-D3`), and it carries `anonymised` where `run_mismatches_csv` does not — this file is the review list, and the span is record text (mvp-spec.md §13) |
| `ra2/api/schemas.py` | + `MismatchResponse`, `MismatchPage`, `ReviewTallyResponse`, `MismatchFeatureResponse`, `MismatchFiltersResponse`, `MismatchListResponse`, `TagMismatchRequest`. The request takes a `MismatchTag` and the response carries a plain `analyst_tag` string — `SD24` on the wire. *Same Wave 1 amendment: `name` dropped from the two responses that mirror the amended read models* |
| `ra2/api/deps.py` | + `MismatchServiceDep` |
| `ra2/api/v1/router.py` | + the mismatches router |
| `ra2/main.py` | + `MismatchService` construction. A session factory and a clock, and **no scorer** — §17.3's absent edge in the wiring as well as in the imports |
| `ra2/persistence/repositories/mismatch_repo.py` | + the `list_for` / `set_tag` / `tally_for` signatures; bodies W1, which also added **`MismatchListRow`** — the list returns detached rows carrying `feature.key` and the record's anonymisation flag out of the same `SELECT`, which is what makes the N+1 unwritable rather than merely discouraged (`R4`, §17.8). **`upsert_feature` is byte-unchanged** and must stay so: it is the scorer's half of the ownership split, and phase 4 owns the test that guards it |
| `mvp-spec.md` | §5 (`mismatch`'s comment gains the column-ownership split and names `MismatchTag`'s three values while keeping the column a string), §12 (a note that the three names are identifiers and "record error" is how `structured_data_error` renders) |
| `sw-design.md` | **§17 is written** — §17.1-§17.10. `SD24`-`SD26` added to §13; §16.9's "Mismatch review" bullet superseded |
| `CLAUDE.md` | the fifth migration author |
| `justfile` | one comment: the Reset section cited "sw-design.md §17", which is now this phase's section. It is §18 |
| `plan-phase-5.md` | §1 Q7, §3.1, §3.2, §5.1 and §7 corrected in the same commit where §17 decided differently — see "Documented deviations phase 5 introduces" |
| `ra2/ui/shell.py` | **untouched.** `mismatches` has existed as a `NavItem` with `built=False` since phase 1, icon already wired. Z1 flips one flag in Wave 4 |
| `pyproject.toml`, `.importlinter` | **byte-unchanged, and asserted so** (see above) |

### Stubs — a body is expected; the file is **not** frozen (phase 5)

| Path | Owner |
|---|---|
| `ra2/domain/mismatch.py` *(the `tally` body)*, `ra2/persistence/repositories/mismatch_repo.py` *(the three new methods)*, `ra2/persistence/migrations/versions/**` | W1 |
| `ra2/ui/components/primitives.py` *(additions)*, `ra2/ui/theme.py` *(additions)* | W2 |
| `ra2/services/mismatch_service.py`, `ra2/services/export_service.py` *(`mismatches_csv` body)* | Y1 |
| `ra2/api/v1/mismatches.py` | Y2 |
| `ra2/ui/views/mismatches_view.py`, `ra2/ui/state.py` *(additions)* | Z1 |

### The two-line exception

Phase 2 paid for leaving its nav wiring implicit (`e386a66`); every phase since
has declared it. Phase 5 needs **two lines and one link**, all Z1's:

1. **Z1 may flip exactly the `mismatches` `built` flag** in `ra2/ui/shell.py`
   and add exactly its own line to `ra2/ui/views/__init__.py`'s
   `register_all`. Nothing else in either file.
2. **Z1 may add exactly the mismatch deep link** to
   `ra2/ui/views/results/extraction_tab.py` — the one `design/results/README.md`
   asks for and phase 4 had nowhere to point (plan-phase-5.md C2). One link, in
   the feature row, carrying `evaluation`, `run` and `feature`. **Nothing else
   in that file**, which belongs to V1. This is a cross-phase edit, which is
   why it is written down rather than assumed; if it grows past one link it is
   an amendment.

### Wave 1 additions (W1, W2) — not frozen, and changed

| Path | What |
|---|---|
| `ra2/domain/mismatch.py` *(body)* | `tally`. An unrecognised stored tag is counted under `other`, never dropped; an empty input is a zero tally rather than a raise; `counts` comes back read-only, because a renderer assembling the strip is exactly who would fold two buckets together in place |
| `ra2/persistence/repositories/mismatch_repo.py` *(bodies)* | `list_for`, `set_tag`, `tally_for`, `MismatchListRow`, and the two private helpers `_filters` / `_order` that **both reads share** — which is what makes "the strip agrees with the table" a property of the module rather than a promise two call sites keep separately (§17.4) |
| `ra2/ui/components/primitives.py` | `segmented_control` takes any number of options, accepts `value=None` as a real cleared state, and grows an optional trailing `on_clear` **action** carrying no `aria-pressed`. **No new component** — W2's reportable event (R2) did not fire |
| `ra2/ui/theme.py` | `_UTILITIES_P5`: `.seg-clear` and `.td-wrap`. Two rules, no new colour, no second table scale |
| `tests/unit/mismatch/test_tally.py` *(new)*, `tests/backend/persistence/test_mismatch_repo.py`, `tests/ui/test_components.py` | W1's and W2's exit criteria |
| `ra2/persistence/migrations/versions/**` | **unchanged.** W1 is phase 5's migration author and did not need a revision (C7): the filtered list rides `ix_mismatch_run_id_feature_id`, and the bounded-statement test is what says so |

### Wave 2 additions (Y1) — not frozen, and changed

| Path | What |
|---|---|
| `ra2/services/mismatch_service.py` | `list_mismatches`, `tag`, `clear_tag`, `tally`, `export_rows`. **Imports no scoring module**, and `tests/test_p5_contract.py` asserts it on the AST. `list_mismatches` and `export_rows` differ only in how much they ask for and share one private `_view`, so a CSV cannot be assembled from a different filter, sort or run than the screen it was exported from (`P4-D3`) |
| `ra2/services/export_service.py` *(`mismatches_csv` body)* | The rows it was handed, UTF-8 with a BOM, `;`-delimited, a comment line naming the evaluation, the run and the filter. `analyst_tag` crosses **verbatim** — a stored value the enum does not name has to reach the file as itself, or the export disagrees with the screen about what an analyst wrote |
| `tests/backend/services/mismatch/**` | Y1's exit criteria, including the two this phase exists to make: a tag moves no `score` row (byte-compared across a tagging session) and the tally agrees with the list for the same filter |

**`_descriptor` is built here rather than imported from `results_service`.**
Two read services of one layer, and the Results one holds a `Scorer` this
module must not acquire (§17.3) — so the six values are read off the evaluation
again rather than reaching through a module that has an edge to scoring.

### Wave 3 additions (Y2) — not frozen, and changed

| Path | What |
|---|---|
| `ra2/api/v1/mismatches.py` | The five routes' bodies and the read-model→wire mapping. Thin translation only; `descriptor_response` is reused from `results.py` rather than copied, the same way `presence.py` and `ranking.py` reuse it |
| `tests/backend/api/mismatches/**` | Y2's exit criteria, through `httpx.ASGITransport` |
| `tests/api/openapi_snapshot.json` | **Three docstring descriptions and nothing else.** Verified by set comparison: no path added or removed, no schema added, removed or changed. Wave 0 froze the wire surface and Wave 3 filled the bodies without moving it |

**`GET .../mismatches/tally` reads through `list_mismatches`, not through
`MismatchTally`.** That protocol takes a session and a router does not own one
(§3.1) — and going through the same service call is what makes the two
endpoints' numbers the same numbers rather than two reads that agree by
convention. A test asserts the tally endpoint's body equals the list's
`tallies` field exactly.

**The filter vocabulary is closed on the wire in both directions.** An unknown
`tag_state` is 422, not a silently empty page; an unknown `tag` on the write is
422 before the service is reached, and a test re-reads the list afterwards to
confirm nothing was written (`SD24`, §17.5).

### Wave 4 additions (Z1) — not frozen, and changed

| Path | What |
|---|---|
| `ra2/ui/views/mismatches_view.py` | The view, to §3.2: the filter toolbar, one flat table with inline tagging, the tally strip, the export, and the three empty states. `TAG_LABELS` and `tally_sentence` are the **one rendering table** and the one sentence — the only copy in the phase, and the reason `structured_data_error` reads as "record error" without the identifier moving (C4) |
| `ra2/ui/state.py` *(additions)* | `MismatchesState`. `run_id` empty means "the evaluation's first run", **not** "all runs", which is not a state this view has (`SD26`) |
| `ra2/ui/theme.py` *(additions)* | `.seg-tight` and `.td-clip` — both from `P5-D5` |
| `tests/ui/test_mismatches_view.py`, `tests/e2e/test_results_j14_mismatches.py` | Z1's exit criteria, and **J14** |
| `tests/ui/test_components.py` *(one constant)* | `MISMATCH_WIDTHS`, corrected with §3.2 (`P5-D5`) |

### The two declared exceptions, taken exactly as declared

1. **`ra2/ui/shell.py`** — one character: `mismatches`' `built` flag, `False`
   to `True`. **The last one in the nav**, which is what `p5w4-green` means.
   `ra2/ui/views/__init__.py` gains its two lines (the import and the
   `register_all` call). Nothing else in either file.
2. **`ra2/ui/views/results/extraction_tab.py`** — one link in the feature row,
   carrying `evaluation`, `run` and `feature`, the one
   `design/results/README.md` asks for and phase 4 had nowhere to point (C2).
   The run it names is the **leftmost model column**: the row spans every
   model and §6.1 permits exactly one link, so it names the run the Mismatches
   view would have picked for itself anyway (`SD26`), and the Run chip
   switches from there. It stops propagation, because the row itself toggles
   the breakdown.

**A consequence worth naming**: two tests now have an empty parameter set and
skip — `tests/ui/test_shell_nav.py`'s
`test_unbuilt_views_render_the_placeholder_inside_the_real_shell` and
`tests/e2e/test_j5_nav.py`'s equivalent. Neither is a regression; both are the
signal. There are no unbuilt views left, so there is no placeholder to render,
and their siblings — `test_built_views_do_not_render_the_placeholder` and J5's
own — now cover all eight. They are left as they are rather than deleted:
they belong to phase 1's agent, and a permanently-skipped test that says "no
view is unbuilt" is a truer record of `p5w4-green` than a deleted one.

**`tests/test_p5_contract.py` gains its one planned edit.**
`test_the_nav_still_has_eight_items_and_mismatches_is_still_unbuilt` was Wave
0's exit criterion and becomes
`test_the_nav_has_eight_items_and_every_one_of_them_is_built` in the wave that
flips the flag §6.1 declared it would. It now asserts the stronger thing:
**no nav item is unbuilt**, which is the whole meaning of this tag.

---

## Documented deviations phase 5 introduces

| # | Decision | Why |
|---|---|---|
| **P5-D1** | **The Mismatches list is one run at a time** (`SD26`, sw-design.md §17.6) — the Run filter has no "all runs" option, `MismatchFilters.run_id` is required, and `MismatchTally` is keyed by `RunId` | `plan-phase-5.md` §3.2 draws seven columns and none of them is the model, while `mvp-spec.md` §12 names `run` as part of the row. Both can be right only if the run is a scope rather than a column. The scope is the better answer for a reason that is not about column widths: **a list mixing two models' mismatches for the same record and feature *is* cross-model agreement**, one of the three things §16.9 defers by name. Refusing the mixed list is not a limitation of this view, it is the deferral caught where it would otherwise have entered as a convenience — and it makes `run_finished_at` well-defined for Q7. `ResultsService.presence_records` already resolves one run the same way. **Consequence:** the plan's §3.2 column table stands unchanged, and the toolbar names the run once instead of every row repeating it |
| **P5-D2** | **`domain.mismatch.tally` takes `Mapping[str \| None, int]`** — stored tag values mapped to row counts — not a sequence of rows, a correction to `plan-phase-5.md` §7's "counting stored tag strings" | The repository's `tally_for` is specified as **one grouped query per run, never one per feature**. A domain signature taking rows would have forced the service to expand that `GROUP BY` back into individual values and recount them, which is the same N+1 the grouped query exists to avoid, one layer up and harder to see. Taking the shape `GROUP BY` produces keeps the grouping intact all the way into the domain, and a caller that genuinely holds rows spends one `Counter` to get there |
| **P5-D3** | **The staleness anchor is `run.finished_at`, and a re-score goes undated** (`SD25`, §17.7) — a correction to `plan-phase-5.md` Q7's "the view says when the run was scored" | RA2 records no scoring timestamp, and this phase does not add one. Scoring chains off the run's terminal `done` (`SD17`), so for a run scored once `finished_at` *is* when it was scored; a **re-score** moves the list without moving it. Closing that gap means a `scored_at` column, which `sw-design.md` §16.1 F5 declined so that "how far did it get" has exactly one answer and which `tests/test_p4_contract.py` asserts the absence of by name. Naming the gap is honest; adding a column against a standing decision, at the end of a phase, for a mitigation R5 already calls cheap, is not. If it bites in real use the next step is **a count of tags lost, not a lock and not a timestamp** |
| **P5-D5** | The Tag column is **270px** and the two value columns **110px**, against §3.2's 210 / 140 / 140 — the fixed total unchanged at 956px | The three-way control renders **290px** wide at the component kit's own 12px segment padding, so in a 210px column the Tag cell overflowed and the Reviewed cell beside it intercepted every click on the clear — a control that cannot be clicked is not a control. **J14 found it, and nothing below a browser could have**: `table-layout:fixed` overlaps rather than reflows, and no layer below the DOM computes a text width. Shortening the words was not available, because `mvp-spec.md` §12's own tally prints them (C4), so the fix is `.seg-tight` (7px padding, ~260px) plus 60px taken back from two columns holding enum codes. `.td-clip` lands with it so a future long value truncates visibly instead of silently killing the control beside it. This is exactly the failure `R2` predicted for a phase whose design section could specify a layout but not measure one |
| **P5-D4** | The list's **default page size is 25**, not the 10 `plan-phase-5.md` §3.2 names | §3.2 contradicts itself in one row — "`pagination_row`, 10/page, "1-25 of 162"" — and both halves come from Census, whose page size is 25 and whose "1-25 of 162" is the string being quoted. This view is the Census shape (Q1), so it takes the Census number; `PAGE_SIZES` offers 10/25/50/100 and an analyst who wants shorter pages has one click to get them |

---

## Documented deviations phase 4 introduces

| # | Decision | Why |
|---|---|---|
| **P4-D1** | The **macro interval** is the propagated standard error of the per-feature Wilson half-widths, not a Wilson interval over pooled counts (`domain/stats.py::macro_interval`) | sw-design.md §16 is silent, and there is no nearest existing pattern to follow, so S1 decided it. A macro F1 is **not a proportion over a pooled denominator**: pooling the counts and running `wilson` over the totals would weight each feature by its `n`, which is exactly what mvp-spec.md §11.5's *equal weight* refuses — and it would do it invisibly, producing a number that looks like every other Wilson bound on the page while answering a different question. So each Wilson half-width is read back as a standard error (`half / z`), combined as independent contributions to an unweighted mean, and turned back into a 95 % interval. Equal weight in, equal weight out. Independence across features is an approximation (the same model scored two features over overlapping records) and is the conservative direction to be wrong in when the correlation is positive, which it usually is. The honest reading is "these models are close", which is the only thing §11.5 uses it for. `tests/unit/stats/test_macro.py` pins the difference against the pooled alternative. |
| **P4-D3** | `ExportService.presence_records_csv` **takes the rows**, not a `(run_id, feature_key, sort)` filter to re-run — a change to the signature M27 froze | Two reasons, and the second is the one that matters. The frozen signature would have needed a `ResultsService` in `ExportService`'s constructor and a reorder of `create_app`'s wiring, for a dependency nothing else on it wants. More importantly, sw-design.md §7's rule is that an export writes "the **currently filtered, currently sorted** table" — and re-fetching inside the exporter is precisely how a CSV comes to disagree with the screen it was exported from. The caller already holds the view; it hands it over. A test asserts the exported row count equals the total the list endpoint printed. |
| **P4-D2** | A model is `BEST` **only when no rival interval overlaps it** — so the *best* column does **not** sum to the feature count, against `design/results/README.md` §3's note | **The design README contradicts itself**, and mvp-spec.md decides it. Its "Statistical conventions" section states the rule this implementation follows: "A model is marked *best* only if no other model's interval overlaps it; otherwise every overlapping model is marked *tied with best*." Its Ranking section then says the opposite: "the *best* column sums to 7 — **exactly one highest value per feature**", i.e. `BEST` = argmax regardless of overlap, with `TIED` for the overlappers — which is what its fixture rows and its `3/3/1 · 4/1/2 · 0/2/5` counts show. The second reading asserts an order on evidence that does not support one, and mvp-spec.md §11.5 is unambiguous: "**overlapping confidence intervals are rendered as a tie, not as an order**". The spec wins over the design (CLAUDE.md's authority order), and it happens to agree with the design's own stated rule. **Consequence, computed on the design's own numbers**: only 3 of the 7 scored features have a clear `BEST` (`road_condition`, `speed_limit`, `vehicles_involved`); on the other 4 the leaders overlap and nobody is best. Counts become qwen3 1/4/2, mistral 2/4/1, gemma3 0/2/5 — each row still sums to 7, but the best column sums to 3. `tests/unit/stats/test_golden_stats.py` pins this so a later drift back to argmax is a failure rather than a silent change. **The Ranking tab's copy must not repeat the "sums to 7" note** (V3). **Confirmed by the lead at the Wave 2 review**, after seeing both tables side by side: the alternative reading (`BEST` = argmax, `TIED` = overlaps it) is defensible as a per-feature reading aid, but the marks are counted into the Ranking tab's `best / tied / worse` column — so under it the product publishes a scoreboard built from differences it has just called not significant, and the tie legend's own "no strict order is implied" becomes false between the filled cell and the outlined one beside it. Not provisional; a change back needs a new deviation, not an edit to this one. |

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
| **P3-D22** | Re-parse and delete are **row actions** in the Import file tables; the action column widens from the design's 46px to 92px, and "Remove file" leaves the report modal | Both tables' rows had exactly one affordance — a clipboard opening a modal — and both of the things an analyst actually does to a bad file lived two clicks inside it. README §1a put them there on the reasoning that a row is for *reading*; what that misses is that deciding to re-run or drop a file is a judgement made **while scanning the State column**, not after opening a report. Deleting twelve unwanted files was twelve modal round trips. Three consequences, each deliberate. **(1)** The column is 92px (3×22 + 2×4 gap + the design's own 14px right padding). The File column absorbs it, which is what being the flexible column means — at 1024px filenames ellipsize ~46px earlier, and `table-layout:fixed` guarantees nothing overflows. J4's `widths["action"]` assertion moves 46 → 92, and `tests/e2e/conftest.py`'s demo table moves with it, because J4 measures that table and a demo that no longer mirrors the real column is measuring fiction. **(2)** Re-parse exists in *both* places and they are not duplicates: the modal's applies the encoding/delimiter/quote selectors — it is the only thing that does, and removing it would leave three dead controls and break J1 — while the row's passes no overrides at all, which `reparse_file` reads as "keep what is effective now". They are relabelled accordingly: "Apply & re-parse" in the modal, "Re-parse <file>" on the row. **(3)** Delete is row-**only**, so it has one home. It is guarded by an inline two-step ("Sure?" in `--danger`, disarmed by any other action, cleared in `reload()`) rather than the one-click the corpora table uses: a corpus delete is guarded by `is_locked`, a file delete has no equivalent guard, and for an `UPLOAD` delivery `remove_file` deletes the stored bytes. Cost: like P3-D19, this settles part of README's open question 1 in code ahead of a design round. An overflow menu would return the column to 46px if a later round wants that. |
| **P3-D21** | The Models card renders the endpoint's catalogue **without an evaluation**, and `ui/components/primitives.py`'s `tick` gains a `disabled` state | Bug fix, recorded because it changes what the design's step 4 shows before step 1 is complete. `_step_models` read `() if view is None else view.models`, so on any database with no `evaluation` row the card said "0 available" and "the endpoint returned an empty catalogue" — while the endpoint was reachable and offering models. "Refresh model list" could not help: `reload()` re-asked `connection_status()` but the list came from `EvaluationView`, which does not exist yet. The card mixes two owners: *which models the endpoint has* is the endpoint's fact, *which are ticked* is the evaluation's, and reaching the first through the second made the first unreachable exactly when someone is trying to find out whether Ollama is set up. `catalogue()` serves the card before an evaluation exists (one `reachable()`, one `models()` — `connection_status()` + `list_models()` would be three round trips for two facts, and `GET /api/v1/models` was paying that too). Selection stays withheld until the evaluation row exists, the design's own step order — hence `tick(disabled=...)`, because omitting `on_change` only made a tick *inert*, looking live while swallowing the click. The empty-state message also split in two: "could not be asked" is not "returned an empty catalogue", and conflating them is what made this read as a broken refresh. **Post-phase, `SD32`:** the gate recorded here is unchanged and still asserted — nothing is selectable before the evaluation row exists — but the affordance that opens it is no longer "Save draft". It is **"New evaluation"**, and step 4's withheld-selection message names that instead. A reader arriving here for *why the ticks are dead* has the same answer as before; a reader arriving for *what to press* wants `SD32`. |
| **P3-D20** | `LlmEndpointError`'s `REFUSED_NOT_LOOPBACK` is now **reached without raising**, by `EndpointProber` | `ra2/domain/llm.py` said the refusal "is not caught anywhere — an app configured this way does not start, which is the point". That stays true of the **configured** endpoint: `require_loopback` still fails `create_app()` outright and there is still no opt-out. What changed is that the settings dialog can now ask about an endpoint the analyst has merely *typed*, and the same verdict has to reach it as a `ProbeResult` rather than as an exception — a dialog that took the app down to tell you a host is not local would be useless. `classify_endpoint` is the shared decision; `require_loopback` is the raising face of it and `EndpointProber` the reporting one, so the two can never disagree. |
| **P3-D19** | The Ollama settings dialog has **five** controls, not the three M17 specified, and one of them duplicates reachability *inside* the dialog | M17's reasoning was that endpoint, timeout and refresh are exactly the three settings the adapter takes, and that reachability belongs beside the Models card (design README §2 step 4) rather than duplicated in here. Two of the three still hold; the assumption that did not survive contact is that a dialog which only *displays* settings is enough to get Ollama configured. The endpoint field accepted any string with no feedback — including a LAN address, which `require_loopback` would then refuse at the next **startup**, long after the analyst could act on it — and the one bit rendered outside cannot distinguish "Ollama is not running" from "that is the wrong port", which is the question someone setting it up actually has. So the dialog gains a loopback check on the typed value (Save disabled, reason inline) and a "Test connection" that probes the value **in the field** and names the cause. The reachability line outside is unchanged and still describes the configured endpoint: the two answer different questions about different URLs, which is also why "Refresh model list" and "Test connection" are deliberately **not** merged — refresh applies, test diagnoses. Cost: the design README's open question 1 is now settled in code ahead of a design round, and a later round may want this drawn differently. |
| **P3-D18** | J6's served-HTML scan compares loopback on **hostname**, not netloc | Applied from L2's amendment. `_host()` returns netloc, but the loopback allowlist held bare host names, so `127.0.0.1:11434` could never match `127.0.0.1` — and the Evaluation view legitimately names that URL, because the design's reproducibility card prints the configured endpoint. Confined to the **naming** scan: the request scans still pin every URL the browser actually asks for to the server under test exactly. A loopback URL cannot leave this host whatever port it carries, which is the property N1 asks about, so the gate is not weakened. |
| **P3-D17** | Saving a prompt template also **activates** it | The design draws no activate affordance anywhere, so without this, copy-on-write could never put new wording into use: you could save v5 and have no way to make new evaluations default to it. Two `PromptService` calls in sequence, nothing computed in the view. It is also what makes the previous version non-active and therefore `locked`, which J9 asserts. Recorded because it is a behavioural decision the design did not make — a later design round may well want a separate control, and this is cheap to split. |
| **P3-D16** | `CorpusRepository.first_record_id` + `CorpusService.first_record` — additive, by amendment | The design's "Preview with record 1" was unreachable from `ui/`: `PromptService.preview` needs a `RecordId`, `CorpusView` carries `record_count` and never an id, and `EvaluationService.record_scope` was the service layer's only source of one and requires an evaluation to exist. A view cannot close that gap without holding a session or calling `domain.prompt` directly, both forbidden by Do-NOT #7. Ordered by id — the same ordering `ExtractionRepository.pending_record_ids` fixes a dev scope with — so "record 1" means the same record in a preview and in the run it previews. |
| **P3-D15** | Stored timestamps are re-attached to UTC by a private `_as_utc` helper in **two** services, not fixed once in `models.py` | `Clock.now()` is always aware; SQLite's `DateTime(timezone=True)` has nowhere to keep the offset and hands the value back naive, so subtracting two stored timestamps raises. I2 and I3 hit this independently and wrote near-identical helpers — which says it belongs a layer down, as a SQLAlchemy `TypeDecorator` on the column type (same storage, no migration). **Deliberately not done in phase 3:** that change alters how every timestamp in the app loads, including the byte-asserted golden import report, and it landed at the end of a wave with two more still to run. Phase 4 should do it as its own commit with the full suite as the check, and delete both helpers. **Discharged at phase 4 Wave 0** (plan-phase-4.md P51): `models.UtcDateTime` normalises to UTC on bind and re-attaches it on load, both `_as_utc` helpers are deleted, and the seven tests that asserted `== <ts>.replace(tzinfo=None)` — i.e. that asserted the defect, one of them with a comment calling it "a dialect limitation, not a repository bug" — now assert the aware value. The golden import report moved: four timestamps gained `+00:00` and nothing else did, which is the improvement, not the cost. Same column type, same stored bytes, no migration. |
| **P3-D14** | `run_service` stops a run after **three consecutive** `LlmEndpointError`s, on a hardcoded constant | Not in the spec. One refusal is a record's problem and leaves the hole resume finds; three in a row is the endpoint's, and grinding a 5 000-record corpus through `RA2_LLM_TIMEOUT_S` × `RA2_LLM_MAX_RETRIES` apiece to discover a dead endpoint is neither honest nor bounded. The run is left `interrupted`, which is the state Resume acts on — never `failed`, which is reserved for something making the run impossible. Not a setting, because it describes "the endpoint is down" rather than anything an analyst has a basis to tune. |
| **P3-D13** | `create_app()` gains a `prompt_resolver` keyword | Added by the lead at Wave 2 integration on I3's flag. Every other adapter is a defaulted keyword argument (§12.12); `PromptResolver` was the one seam production wired but a test could not substitute, so I3's app-level tests had to set a private attribute on the built service. A seam a test cannot reach through the composition root is a seam only production uses. |
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

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
| `ra2/services/readmodels.py` | + `MismatchRowView`, `MismatchFeatureView`, `ReviewTallyView`, `MismatchFilters`, `MismatchListView`, and `TagFilter`/`TagState` re-exported. **Five, where plan-phase-5.md §5.1 named four**: `MismatchFeatureView` is the Feature filter's option list, which cannot be the tally strip because the strip is scoped to the current filter and would collapse to one entry the moment a feature was picked |
| `ra2/services/errors.py` | **unchanged, and asserted so.** Phases 2, 3 and 4 each added errors; a phase that adds none is a phase that introduced no new failure. An unknown mismatch is a `NotFoundError`; an unknown tag never reaches the service |
| `ra2/services/export_service.py` | + the `mismatches_csv` signature and `_MISMATCHES_CSV_HEADER`; body is Y1's. **It takes the rows** (`P4-D3`), and it carries `anonymised` where `run_mismatches_csv` does not — this file is the review list, and the span is record text (mvp-spec.md §13) |
| `ra2/api/schemas.py` | + `MismatchResponse`, `MismatchPage`, `ReviewTallyResponse`, `MismatchFeatureResponse`, `MismatchFiltersResponse`, `MismatchListResponse`, `TagMismatchRequest`. The request takes a `MismatchTag` and the response carries a plain `analyst_tag` string — `SD24` on the wire |
| `ra2/api/deps.py` | + `MismatchServiceDep` |
| `ra2/api/v1/router.py` | + the mismatches router |
| `ra2/main.py` | + `MismatchService` construction. A session factory and a clock, and **no scorer** — §17.3's absent edge in the wiring as well as in the imports |
| `ra2/persistence/repositories/mismatch_repo.py` | + the `list_for` / `set_tag` / `tally_for` signatures; bodies W1. **`upsert_feature` is byte-unchanged** and must stay so: it is the scorer's half of the ownership split, and phase 4 owns the test that guards it |
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

---

## Documented deviations phase 5 introduces

| # | Decision | Why |
|---|---|---|
| **P5-D1** | **The Mismatches list is one run at a time** (`SD26`, sw-design.md §17.6) — the Run filter has no "all runs" option, `MismatchFilters.run_id` is required, and `MismatchTally` is keyed by `RunId` | `plan-phase-5.md` §3.2 draws seven columns and none of them is the model, while `mvp-spec.md` §12 names `run` as part of the row. Both can be right only if the run is a scope rather than a column. The scope is the better answer for a reason that is not about column widths: **a list mixing two models' mismatches for the same record and feature *is* cross-model agreement**, one of the three things §16.9 defers by name. Refusing the mixed list is not a limitation of this view, it is the deferral caught where it would otherwise have entered as a convenience — and it makes `run_finished_at` well-defined for Q7. `ResultsService.presence_records` already resolves one run the same way. **Consequence:** the plan's §3.2 column table stands unchanged, and the toolbar names the run once instead of every row repeating it |
| **P5-D2** | **`domain.mismatch.tally` takes `Mapping[str \| None, int]`** — stored tag values mapped to row counts — not a sequence of rows, a correction to `plan-phase-5.md` §7's "counting stored tag strings" | The repository's `tally_for` is specified as **one grouped query per run, never one per feature**. A domain signature taking rows would have forced the service to expand that `GROUP BY` back into individual values and recount them, which is the same N+1 the grouped query exists to avoid, one layer up and harder to see. Taking the shape `GROUP BY` produces keeps the grouping intact all the way into the domain, and a caller that genuinely holds rows spends one `Counter` to get there |
| **P5-D3** | **The staleness anchor is `run.finished_at`, and a re-score goes undated** (`SD25`, §17.7) — a correction to `plan-phase-5.md` Q7's "the view says when the run was scored" | RA2 records no scoring timestamp, and this phase does not add one. Scoring chains off the run's terminal `done` (`SD17`), so for a run scored once `finished_at` *is* when it was scored; a **re-score** moves the list without moving it. Closing that gap means a `scored_at` column, which `sw-design.md` §16.1 F5 declined so that "how far did it get" has exactly one answer and which `tests/test_p4_contract.py` asserts the absence of by name. Naming the gap is honest; adding a column against a standing decision, at the end of a phase, for a mitigation R5 already calls cheap, is not. If it bites in real use the next step is **a count of tags lost, not a lock and not a timestamp** |
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
| **P3-D21** | The Models card renders the endpoint's catalogue **without an evaluation**, and `ui/components/primitives.py`'s `tick` gains a `disabled` state | Bug fix, recorded because it changes what the design's step 4 shows before step 1 is complete. `_step_models` read `() if view is None else view.models`, so on any database with no `evaluation` row the card said "0 available" and "the endpoint returned an empty catalogue" — while the endpoint was reachable and offering models. "Refresh model list" could not help: `reload()` re-asked `connection_status()` but the list came from `EvaluationView`, which does not exist yet. The card mixes two owners: *which models the endpoint has* is the endpoint's fact, *which are ticked* is the evaluation's, and reaching the first through the second made the first unreachable exactly when someone is trying to find out whether Ollama is set up. `catalogue()` serves the card before an evaluation exists (one `reachable()`, one `models()` — `connection_status()` + `list_models()` would be three round trips for two facts, and `GET /api/v1/models` was paying that too). Selection stays withheld until "Save draft", the design's own step order — hence `tick(disabled=...)`, because omitting `on_change` only made a tick *inert*, looking live while swallowing the click. The empty-state message also split in two: "could not be asked" is not "returned an empty catalogue", and conflating them is what made this read as a broken refresh. |
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

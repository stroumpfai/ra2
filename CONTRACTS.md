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

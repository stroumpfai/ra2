# Software Design — RA2

The architecture contract for the MVP. **Implementing agents must stay inside this
document.** Where it is silent, follow the nearest existing pattern in the codebase;
where it is wrong, raise it and change *this file first*, in the same commit.

**Document authority.** `vision.md` (why) → `ra2.md` (stack, process) →
`mvp-spec.md` (what) → **`sw-design.md` (how)**. On a *what* question `mvp-spec.md`
wins. On a *how* question this file wins. Section references like §4.2 point into
`mvp-spec.md`; §D-numbers point into its decision register.

---

## 1. Architecture in one picture

```
                      ┌──────────────┐     ┌──────────────┐
   browser ──────────>│  ui/ NiceGUI │     │ api/ FastAPI │<──── scripts, Playwright
                      └──────┬───────┘     └──────┬───────┘        seeding, later MCP
                             │  in-process        │
                             └────────┬───────────┘
                                      v
                            ┌───────────────────┐
                            │     services/     │  use cases, transactions,
                            │                   │  task orchestration
                            └───┬───────────┬───┘
                                │           │
                    ┌───────────v──┐   ┌────v──────────┐
                    │   domain/    │   │ persistence/  │
                    │ pure, no I/O │   │ SQLAlchemy 2.0│
                    └──────────────┘   └───────────────┘
                                      ^
                            ┌─────────┴─────────┐
                            │      infra/       │ config, files, tasks,
                            │  (adapters only)  │ clock, ids, lingua, LLM
                            └───────────────────┘
```

**The UI and the API are two adapters over one set of services.** NiceGUI calls
services **in-process as Python**, never over HTTP to its own API. The API exists so
that scripts, tests and Playwright can drive the same use cases without a browser.

### 1.1 Dependency rule — enforced, not suggested

| Package | May import |
|---|---|
| `ra2/domain/` | stdlib, `pydantic`, `attrs`-style plain types. **Nothing else in `ra2/`.** |
| `ra2/persistence/` | `domain`, SQLAlchemy, Alembic |
| `ra2/services/` | `domain`, `persistence`, `infra` protocols |
| `ra2/api/` | `services`, `domain` |
| `ra2/ui/` | `services`, `domain` |
| `ra2/infra/` | `domain` |

- `domain` imports **no** SQLAlchemy, **no** FastAPI, **no** NiceGUI, **no** filesystem.
- `api` never imports `ui`. `ui` never imports `api` or `persistence`.
- Enforced in CI by **`import-linter`** (`.importlinter`, contract type `layers`).
  A violation fails the build; it is not a review comment.

---

## 2. Package layout

```
ra2/
  __init__.py
  main.py                    create_app() — the composition root, wiring only
  domain/
    ids.py                   CorpusId, DeliveryId, FileId, RecordId (NewType str)
    findings.py              Finding, FindingCode, Severity — the report vocabulary
    delivery.py              FileKind, Dialect, FileAnalysis, DeliveryAnalysis
    parsing/
      encoding.py            detect_encoding(bytes) -> Encoding | Undecodable
      dialect.py             detect_dialect(text, kind) -> Dialect
      reader.py              RFC4180 read with an explicit Dialect
      recovery.py            key-anchored recovery (§4.2 step 3)
      headers.py             the three expected column sets + the text header
    validation.py            blocking + non-blocking delivery checks (§4.3)
    census.py                compute_census(cells) -> list[ColumnCensus] (pure)
    typehint.py              suffix rule + value-shape inference
    canary.py                cp1252 canary count (§4.4)
    language.py              LanguageDetector protocol, LanguageGuess
    llm.py                   LLMClient protocol (§3) — no callers in phase 1
  persistence/
    models.py                SQLAlchemy 2.0 declarative
    session.py               async engine, WAL pragmas, session factory
    repositories/
      delivery_repo.py  corpus_repo.py  census_repo.py
    migrations/              Alembic env + versions
  services/
    delivery_service.py      register, analyse, re-parse, select
    corpus_service.py        freeze a selection into a corpus, list, delete
    census_service.py        query the materialised census, profile buckets
    export_service.py        CSV writers
  api/
    v1/router.py  v1/deliveries.py  v1/corpora.py  v1/census.py  v1/tasks.py
    schemas.py               request/response models (never ORM objects)
  ui/
    theme.py                 design tokens -> CSS custom properties, one injection
    shell.py                 header + nav + route registry
    components/              card, data_table, pagination, tick, chip, bar, dist_bar
    views/import_view.py  census_view.py  placeholder_view.py
    state.py                 per-client view state
    static/fonts/            vendored IBM Plex Sans + Mono (see §8.2)
  infra/
    config.py                pydantic-settings, RA2_ prefix
    files.py                 ALL file I/O — explicit encoding, no exceptions
    filestore.py             FileStore protocol: upload adapter + host-path adapter
    tasks.py                 TaskRunner protocol + AsyncioTaskRunner
    clock.py  idgen.py       injected, so tests are deterministic
    lingua_detector.py       LanguageDetector implementation
tests/                       see §11
justfile  pyproject.toml  alembic.ini  .importlinter  .pre-commit-config.yaml
```

---

## 3. Seams

Every one of these is a `typing.Protocol` in `domain/` or `infra/`, injected into
services through the constructor. **No service reaches for a global.**

| Protocol | Why it exists | Phase 1 implementations |
|---|---|---|
| `LLMClient` | §3 invariant: nothing else imports `openai`/`ollama` | declared only; `FakeLLMClient` in tests |
| `LanguageDetector` | swap `lingua-py` (D9) without touching import | `LinguaDetector`, `StubDetector` |
| `FileStore` | upload and host-path intake behind one seam (§6.1) | `UploadedFileStore`, `HostPathFileStore` |
| `TaskRunner` | background analyse/freeze with progress; grows into the run worker (§9) | `AsyncioTaskRunner`, `InlineTaskRunner` (tests) |
| `Clock` | reproducible timestamps in tests and golden reports | `SystemClock`, `FrozenClock` |
| `IdFactory` | reproducible ids in golden reports and E2E | `Uuid7Factory`, `SeededFactory` |

`create_app()` in `main.py` takes every implementation as a defaulted keyword
argument. Tests build the app with substitutes; **there is no test-mode branch in
production code**.

---

## 4. Data model

Everything in `mvp-spec.md` §5 stands. This section adds what §5 does not cover and
phase 1 needs. All additions are **flagged in §13**.

### 4.1 New: delivery staging

The design shows files with parse state *before* a corpus exists, and a
"Create corpus · N records" button that sums the selection. That requires a staging
concept the spec does not name.

```
delivery(id, name, created_at, source_kind, root_path, status, analysed_at)
   source_kind: 'upload' | 'host_path'
   status:      'registered' | 'analysing' | 'analysed' | 'failed'

delivery_file(id, delivery_id, filename, relative_path, byte_size, sha256,
              file_kind,                 -- unfall|objekt|person|text|unknown
              set_key,                   -- groups the 3 structured files of one canton
              canton,                    -- from data, never the filename
              encoding, delimiter, quote_char,
              encoding_detected, dialect_detected,   -- what detection said, before override
              row_count, ok_count, recovered_count, rejected_count,
              header_ok, findings_json, selected, analysed_at)
```

`delivery_file` is **mutable** — re-parsing after an encoding override rewrites its
row. `corpus` and everything below it is not.

### 4.2 New: materialised census

```
census_column(id, corpus_id, table_name, column_name, type_hint,
              record_count, populated_count, populated_rate,
              distinct_count, long_tail, top_value_share)
census_value(census_column_id, rank, value_raw, count, share)   -- top 20 only
census_bucket(corpus_id, bucket_label, column_count)            -- the profile card
```

**Census is computed once, during corpus freeze, and stored.** A corpus is immutable
(§5), so a materialised census can never go stale. The alternative — aggregating
~1.5M EAV cells per page load — makes the Census view seconds slow for no gain.

### 4.3 Additive columns on spec tables

- `corpus.description` — shown in the design's Corpora table, absent from §5.
- `corpus.delivery_id`, `corpus.source_file_ids_json` — provenance of the freeze.
- `corpus.language_counts_json` — the design's "de 2 812 · fr 1 402 · it 396".

### 4.4 Storage rules

- SQLite, WAL, `foreign_keys=ON`, `busy_timeout=5000`, `secure_delete=ON`, set as
  connect-time PRAGMAs in `session.py` — nowhere else. The fourth is §18's:
  SQLite frees a deleted row's page **with its bytes intact**, so without it a
  discarded run's `mismatch.evidence_span` — verbatim narrative — stays readable
  in the file until some later write reuses that page (`SD29`).
- **`hide_parameters=True` on the engine**, which is a data-handling flag and not
  a tuning one. SQLAlchemy's default puts the bound parameters of a failing
  statement into `str(exc)`, and `run_service._error_text` stringifies every
  caught exception into `run.error` — persisted, rendered by the runs table's
  log action, and written to stderr. So a constraint violation over `record`
  published `text_raw` and `unfall_uid`, and one over `extraction` the model's
  whole answer, to the artefact §5.1 of `data-handling.md` exists to keep safe
  to paste into a bug report (`SD39`).
- **Alembic from the first commit.** `metadata.create_all()` appears nowhere, not
  even in tests (§11.3).
- EAV for the 67/77/18 wide columns (D10). Index `(record_id, column_name)` and
  `(corpus_id, column_name)` via the parent join; the census tables exist precisely
  so no view queries EAV directly.
- Values are stored **`value_raw`, verbatim**. Normalisation is a read-time domain
  function, never an in-place rewrite (§5, N5).

---

## 5. The `Finding` vocabulary

§4.2 and §4.3 require that nothing is silently repaired or dropped. One type carries
that, from the parser to the UI to the CSV export:

```python
@dataclass(frozen=True, slots=True)
class Finding:
    code: FindingCode          # stable enum, e.g. ROW_REJECTED_FIELD_COUNT
    severity: Severity         # BLOCKING | REPORTED
    file_id: FileId | None
    key: str | None            # UnfallUid / ObjektUid / PersonUid where known
    line_no: int | None
    detail: dict[str, str]     # rendered by the UI, never a pre-formatted sentence
```

Rules:
- `FindingCode` values are **stable identifiers**; tests assert on the code, never on
  prose. Message text lives in one rendering table in `ui/`, so wording changes do
  not break tests.
- **Every** rejected row, recovered row, count mismatch, orphan key, unmatched text
  key and detected encoding produces a `Finding`. A parser that drops a row without
  emitting one is a bug with a named regression test.
- The import report is `list[Finding]` serialised to `corpus.import_report_json`.

---

## 6. Import pipeline

Two phases, both idempotent, both run through `TaskRunner` with progress.

### 6.1 Intake

Both intake paths land on the same `FileStore` seam and produce the same
`delivery_file` rows:

- **Upload** — the design's `+` button, NiceGUI `ui.upload`, streamed to
  `{data_dir}/deliveries/{delivery_id}/`. Bounded by `RA2_MAX_UPLOAD_MB`.
- **Host path** — the analyst gives a directory on this machine; files are
  registered in place, not copied. The path is recorded on the delivery.

Nothing downstream knows which was used.

### 6.2 Analyse (per file, re-runnable)

```
bytes ─> detect_encoding ─> decode ─> detect_dialect ─> RFC4180 read
      ─> key-anchored recovery ─> header match ─> per-row outcome ─> Findings
```

1. **Encoding** (§4.2.1): UTF-8, then Windows-1252. Undecodable bytes **fail the
   file**. `errors="replace"` is banned — a lint rule and a test enforce it.
2. **File kind is decided by the header, never the filename** (§4.1). The header
   column set is matched case-insensitively and whitespace-trimmed against the three
   structured sets and the two-column text header. No match → `unknown`, blocking if
   the file is selected.
3. **Canton comes from the data** — `unfall.KantonAusw`. An `objekt`/`person` file is
   assigned to the structured set whose `unfall` file contains its parent keys. The
   design's collapsed "set" rows are formed from that, after analysis, never from the
   filename.
4. **Recovery** (§4.2.3): a line not starting `^[0-9A-Fa-f]{32}<delim>` is a
   continuation of the preceding record. Two-column text file → repaired, counted
   `recovered`. Wide structured table → **detected, not repaired**; the row is
   `rejected` and reported with its key.
5. Encoding and delimiter are per-file, defaulted by detection, **overridable**. An
   override re-runs step 1 onward for that file alone.

Analyse writes only to `delivery_file`. No corpus rows.

### 6.3 Freeze (create corpus)

One transaction, all-or-nothing:

1. Cross-file **blocking** validation over the *selected* files (§4.3): duplicate
   `UnfallUid`/`ObjektUid`/`PersonUid` **across the whole delivery**, orphan FKs,
   header mismatch. Any failure → nothing is written, the errors return to the UI.
2. Write `corpus`, `record`, and the EAV rows.
3. Per-record language detection (§4.5) — low confidence stored as `mixed`, never
   forced.
4. Corpus-level cp1252 canary count (§4.4). One number, no per-record markers.
5. Non-blocking findings collected into `import_report_json`.
6. Compute and store the census (§4.2 above).
7. Mark `is_dev_sized` from `RA2_DEV_RECORD_MAX` / `RA2_EVAL_RECORD_MIN`.

Deleting a corpus is refused (HTTP 409, UI "delete blocked") when any evaluation
cites it. Phase 1 has no evaluations, so the guard is implemented and tested against
a seeded row.

---

## 7. Census

- **Type hint**: the suffix rule first, then value-shape inspection — all values
  `YYYYMMDD` in a plausible range → `date`; all `HH:MM` → `time`; all integral →
  `integer`; decimal-parseable → `decimal`; else `text`. The suffix naming a
  coded column differs by format: `Ausw` in RADIS (`UnfTypAusw`), `` UAP`` in
  Astrana (`Witterung UAP`) — mvp-spec.md §4.1. Both are `enum`, and the name
  always wins over the value shape, because Astrana's UAP codes are numeric in
  some columns and alphanumeric in others. The column name is read, never the
  file's format: the rule is one suffix tuple, not a per-format vocabulary.
- **Populated** = non-empty string (§6). Empty means *no value provided*, never
  "not applicable" (§8.6) — the Census view says so in the Reminder card.
- **Top values**: 20 stored, top 3 shown in the legend, top 4 shown as stacked-bar
  segments plus a remainder — **for a coded column only** (`SD28`).
- **Long tail** is a stored boolean: `distinct > 20 and top_value_share < 0.01`.
  The design's "long tail · 1 461 distinct, no value over 1 %" is that rule rendered.
- **Profile buckets**: 100–80 / 80–60 / 60–40 / 40–20 / 20–0 / empty, over all tables.
- CSV export writes the **currently filtered, currently sorted** table, UTF-8 with
  BOM (Excel on Windows, N3), `;` delimiter, a classification line, and a header
  comment line naming the corpus id and version.

**Whose values may be shown** (**SD28**). The census stores the top 20 raw
values of every column, and the census CSV is the week-one deliverable — the
artefact most *meant* to be shown to other people. Over the working corpus that
put verbatim LV95 coordinates at metre precision and verbatim record UIDs into
that file, with 16 to 20 of each column's 20 stored values occurring exactly
once. A value that occurs once is one accident.

So `domain/census.py` states the rule once — `sample_is_shareable(type_hint)`,
true only for `ENUM` — and two callers read it: `census_service` builds the read
model the Census view and the API render, and `export_service` writes the CSV. A
rule stated twice is a rule that drifts, and the half that drifts is the half
nobody looks at.

Three properties make it usable rather than merely safe:

- **Only the raw values go.** Populated count and rate, distinct count,
  top-value share, long-tail flag and type hint all survive, and those are what
  feature selection actually reads (§6). A rule that took the aggregates too
  would have made the deliverable useless instead of safe.
- **Withheld is not the same as empty**, and the read model, the wire and the
  CSV all carry `top_values_withheld` to say which. An all-empty column is a
  real delivered state (h08) that says "do not pick this as a feature";
  a withheld sample says nothing about the column at all. Collapsing them would
  hand a reader the opposite conclusion.
- **Read time, never write time.** The values stay in `census_value`. A corpus
  is immutable, so a write-time filter would leave every corpus frozen before
  the rule existed still carrying them into every export; suppressing on the way
  out fixes the corpora that already exist and needs no migration. It is the
  shape `SD19` settled for scoring cells, for the same reason.

The known cost is stated rather than discovered: a code appearing in a single
record is still exported, because the line is drawn at the **header** — the
delivery's own `Ausw`/`` UAP`` marking — rather than at a frequency. A rare code
is a far weaker identifier than a coordinate, and a header rule is one a reader
can check against the data dictionary. The mirror of it is that Astrana's
`Kanton Kürzel`, a two-letter canton code by any reading, loses its sample
because its format does not use the suffix.

**Every export carries a classification line**, written by `ExportService.
_write_csv` — the one place all six exports pass through, so it is guaranteed
rather than remembered. N1 governs the application; nothing governed its
outputs, and an export is the one artefact of this project that is meant to
travel. It states a fact about provenance rather than a classification level,
because this project has agreed no classification scheme; when the governance
page exists, a formal marking belongs in that one constant.

---

## 8. UI architecture

### 8.1 Rules

1. **The UI holds no business logic.** Sorting, filtering, paging, derived counts and
   validation are service calls or domain functions. A view function that computes a
   rate is a bug.
2. **All view state lives in `app.storage.client`**, reached through typed dataclasses
   in `ui/state.py`. Module-level mutable state leaks between browser tabs and is
   banned.
3. **One `DataTable` component** drives all three tables (structured files, text
   files, corpora, census). It takes `list[ColumnSpec]` — `key, label, width, align,
   sortable, render` — plus a `TableState(sort_key, sort_dir, page, page_size)`.
   `table-layout: fixed`, widths verbatim from the design.
4. Sort/page parameters are always part of the **service call signature**, even when
   the current dataset is small enough to sort in memory.
5. Every view is `views/<name>.py` exposing `register(app)`, rendering inside
   `shell(title=…, description=…, active=…)`. The header copy is the design's,
   verbatim.
6. Views not yet built (Codelists, Features, Evaluation, Results, Mismatches) have
   real nav entries routing to `placeholder_view`. The shell is built **once**.
   Codelists and Features now have a design package (`design/code-feature/`, §14) —
   still unbuilt, but no longer undesigned.

### 8.2 Design fidelity

The design is implemented **faithfully**: tokens, fixed sizes and layout rules from
`design/nav-import-census/README.md` (and, once that wave starts, from
`design/code-feature/README.md`, §14) are requirements, not suggestions.

- `theme.py` injects one stylesheet defining the oklch tokens as CSS custom
  properties and the utility classes (`.card .th .td .navitem .lbl .chip .btn .bar
  .tick .sorth`). Quasar's defaults are reset where they conflict; components are
  built from `ui.element` rather than `ui.table`/`ui.card` wherever the design
  diverges from Quasar.
- **Fonts are vendored.** IBM Plex Sans and Mono (400/500/600) ship in
  `ui/static/fonts/` and are served by the app with local `@font-face`.
  The design README says "loaded from Google Fonts"; **N1 forbids any CDN fetch**, and
  N1 wins. There is a test asserting no external URL appears in served HTML/CSS.
- Fixed sizes that are load-bearing and asserted in E2E (§11.5): nav 196px, card
  header 46px, Import table well 404px, the two Import cards side by side at every
  width, `.bar` 78×6px, distribution bar 8px / max-width 230px.
- Colour carries **only** state and severity. No decorative hue.
- Focus rings are undesigned in the mock; add a visible one from a single token.

### 8.3 The file report modal

The design defers it ("not yet designed") but the Import view's row action opens it,
so phase 1 specifies the minimum: per-file findings grouped by `FindingCode` with
counts and keys, the detected vs. effective encoding/delimiter/quote char with
override selectors, a re-parse button, a 20-row raw preview, remove, and
"Export findings CSV".

**Amended by P3-D22: remove is no longer in the modal.** Deleting a file is a row
action in the Import table, so it has exactly one home. Re-parse stays and is
labelled "Apply & re-parse", because it is the only thing that applies the three
override selectors above it — `DeliveryService.reparse_file`'s arguments come from
them. The row's own re-parse passes no overrides, which that method reads as "keep
what is effective now": a re-run, never a change. The two buttons call the same
service method and are not duplicates of each other.

---

## 9. Jobs

`TaskRunner` is a small in-process asyncio worker: `submit(name, coro_factory) ->
TaskId`, with `progress(done, total, message)` and terminal `ok`/`failed`. Phase 1
uses it for analyse and freeze; §9 of the spec extends the same seam to extraction
runs, which additionally persist to the `run` table and must be restart-safe.
`InlineTaskRunner` executes synchronously so backend tests need no polling.

`GET /api/v1/tasks/{id}` exposes progress; the UI polls it with `ui.timer`.

---

## 10. Configuration and platform

`infra/config.py`, pydantic-settings, `RA2_` prefix, `.env` supported:

| Setting | Default | Note |
|---|---|---|
| `RA2_DATA_DIR` | `./var` | N7 — DB, uploads and codelists under it. **Not exports**: they are streamed to the browser and never written here (`SD30`) |
| `RA2_DB_PATH` | `{data_dir}/ra2.sqlite` | |
| `RA2_LLM_BASE_URL` | `http://localhost:11434/v1` | N2 — present from commit 1, unused in phase 1 |
| `RA2_HOST` / `RA2_PORT` | `127.0.0.1` / `8080` | bind to loopback by default |
| `RA2_MAX_UPLOAD_MB` | `512` | |
| `RA2_DEV_RECORD_MAX` / `RA2_EVAL_RECORD_MIN` | `50` / `200` | §9 |
| `RA2_MIN_CELL_COUNT` | `20` | D3, unused until scoring |
| `RA2_LLM_TIMEOUT_S` / `RA2_LLM_MAX_RETRIES` | `600` / `2` | §15.5. 600 is measured, not chosen — a thinking model answered one record in 136 s on the reporting host |
| `RA2_LLM_REASONING_EFFORT` | `none` | §15.5. How hard the model is asked to think, pinned on the `run` row. `none` is measured, not preferred: 190 s → 6 s on the same record |
| `RA2_LLM_PARALLEL_CALLS` | `{}` | §15.4, SD38. JSON map of model tag → records in flight (`1..8`), pinned on the `run` row at launch; an unmapped model runs serially. **An entry applies only while a passing parallel gate for the model's current digest and Ollama version is on record** (SD40); otherwise the launch pins 1 and says why. `just qualify-model <tag> --gate 4` is how a gate gets on record |
| `RA2_LOG_LEVEL` | `INFO` | §5.1 of `data-handling.md` — the level of the `ra2` stderr logger. A level, **not** a switch on what may be logged: no level puts narrative in a log record |

- **Every file operation specifies `encoding=`** (N4). Enforced by ruff `PLW1514`
  plus the rule that all file I/O goes through `infra/files.py`.
- **No POSIX-only paths, no shell-outs** (N3). `pathlib` everywhere; CI runs the
  suite on Windows and Linux.
- **No egress.** No CDN, no telemetry, no crash reporting, no font fetch (N1).

---

## 11. Testing architecture

Five layers. **The first four gate every commit.** A pull request that adds
behaviour without a test at the right layer is not complete.

```
tests/
  conftest.py
  unit/        pure domain — no DB, no network, no server, milliseconds
  backend/     services + repositories on temp SQLite; API via httpx ASGITransport
  ui/          NiceGUI User fixture, in-process, headless, no browser
  e2e/         Playwright chromium against a real server on a random port
  eval/        @pytest.mark.eval — phase 3, not phase 1
  fixtures/
    deliveries/hazards/     synthetic, byte-crafted, committed
    generate_hazards.py     regenerates them, readable and reviewable
    factories.py            corpus/record/census builders for backend + e2e seeding
    golden/                 committed golden import reports
```

Markers: `unit` (default) · `backend` · `ui` · `e2e` · `eval` · `realdata`.

### 11.1 Layer 1 — unit

Everything in `domain/`, tested without a database: encoding detection, dialect
detection, RFC4180 reading, key-anchored recovery, header matching, delivery
validation, canary counting, type-hint inference, census computation, language-guess
handling. Property-based tests (Hypothesis) for the recovery rule — a round trip of
"split a record across N lines, recover it" must reconstruct the original for all N.

### 11.2 Layer 2 — backend

Services and repositories against a **real temporary SQLite file** (not in-memory —
WAL and cross-connection behaviour must be exercised), plus the API through
`httpx.ASGITransport` with no network.

- The schema fixture runs **`alembic upgrade head`**, never `metadata.create_all`.
  Every migration is therefore executed on every backend run — **once per run**,
  into a template database that each test copies. The chain costs ~220 ms and the
  copy ~0.1 ms, and 1050 of the gate's 2460 tests need a schema, so per-test
  migration was a third of the serial suite and nothing about it varied between
  tests. `tests/backend/persistence/test_migrations.py` keeps a genuine per-test
  upgrade (`freshly_migrated`): a test named "upgrade head creates every table"
  must not be asserting against a file copy.
- A dedicated test runs `alembic check` and fails when models and migrations have
  drifted.
- Covers: analyse → select → freeze → census, the 409 on a locked corpus, transaction
  rollback when a blocking check fails (assert **zero** corpus rows afterwards),
  re-parse after an encoding override, CSV export bytes.

### 11.3 Layer 3 — frontend

NiceGUI's `User` fixture, in-process and headless. Fast enough to gate commits.

- shell: 7 nav items in 4 groups; active item derived from the route; title and
  description copy per view
- import: deselecting a file updates **both** the card-header count and the
  "Create corpus · N records" label; header checkbox selects all / none and shows
  indeterminate when partial; sort click flips direction; sort state is independent
  per table; pagination disables rather than hides
- census: each chip refilters and resets to page 1; default sort is Populated ▼;
  in-config rows are tinted; "use as feature" is disabled in phase 1
- markers: dev-sized corpora carry the "smoke test, not a result" marker; canary 0
  renders in `--danger`

### 11.4 Fixtures must contain the real hazards

§15 is explicit that clean fixtures are not acceptable. Real data is gitignored and
must never reach a test, so the hazards are **synthesised byte-exactly** by
`generate_hazards.py` and committed:

| Fixture | Hazard | Expected |
|---|---|---|
| `h01_cp1252` | Windows-1252 bytes | detected, decoded, reported |
| `h02_undecodable` | bytes valid in neither encoding | **file fails**, never `U+FFFD` |
| `h03_stray_delimiter` | extra `\|` in a wide `unfall` row | row **rejected**, key in report |
| `h04_embedded_newline` | newline inside a quoted narrative | **recovered**, counted |
| `h05_unquoted_newline` | newline in an unquoted field | recovered by key anchor |
| `h06_orphan_objekt` | `objekt.UnfallUid` with no parent | **blocking** |
| `h07_dup_uid_cross_canton` | same `UnfallUid` in the AG and BE sets | **blocking** |
| `h08_all_empty_column` | a column empty in every row | census 0 %, out of every denominator |
| `h09_fr_lossy` | French with `œ`/quotes already deleted upstream | contributes 0 to the canary |
| `h10_count_mismatch` | `AnzObjFeld` ≠ child count | reported, non-blocking |
| `h11_unmatched_text_key` | text row with no `unfall` row | reported, non-blocking |
| `h12_unknown_header` | header matching no table | kind `unknown`, blocking if selected |

Each has a named test asserting the exact `FindingCode` **and** that the offending
key appears in the report. One **golden report test** imports a full synthetic
delivery and diffs the serialised report against a committed file.

**Byte-exactly means the line endings too** (`SD33`). Every fixture compared
against generator output carries a `.gitattributes` entry, because
`core.autocrlf` is configured per machine and an unpinned path checks out with
whatever the developer's own git produces. The delivery hazards are `-text` —
they are CRLF by construction and `h13` carries a doubled CRLF no text
conversion survives; the codelist, prompt and golden fixtures are `eol=lf`.
The repository is **not** renormalised: only those paths are named.

`@pytest.mark.realdata` tests read `data/data/samples/` when present and skip when
absent. They are never required to pass in CI.

### 11.5 Layer 4 — E2E / journeys (Playwright)

`pytest-playwright`, **Chromium**, Python — same language as the handover audience.
A session fixture starts a real server on a random port with a temp `RA2_DATA_DIR`
and a `FrozenClock` + `SeededFactory` injected through `create_app()`; there is **no
test mode in production code**. Seeding beyond the journey under test goes through
`/api/v1`. Traces and screenshots on failure, uploaded as CI artifacts.

| # | Journey |
|---|---|
| **J1** | **Delivery to census.** Register the hazard delivery → analyse → per-file states show `ok` / `2 rejected` / `3 recovered` → open a file report → change its encoding → re-parse → state clears → deselect one file and watch both counts drop → Create corpus → the corpus row shows records, language composition and canary → Census loads, sorted Populated ▼ → filter to `unfall` → Export CSV and assert the downloaded file's header and row count. |
| **J2** | **Blocking validation.** A delivery with a `UnfallUid` duplicated across two cantonal sets: Create corpus is refused, the error names the key, and **no corpus row exists** afterwards. |
| **J3** | **Immutability.** A corpus cited by a seeded evaluation shows the `LOCKED · 1 eval` pill and a non-interactive "delete blocked"; `DELETE /api/v1/corpora/{id}` returns 409. |
| **J4** | **Layout invariants.** At 1024, 1440 and 1920 px: the two Import cards share a `y` and differ in `x` (never wrap), `scrollWidth <= clientWidth` on the document, the two card headers are the same height, and the two pagination rows share a `y`. The design calls these requirements — so they are assertions. |
| **J5** | **Navigation.** Every nav item routes; header title and description match the specified copy; the active item is derived from the route; unbuilt views render the placeholder; the nav is keyboard-reachable with a visible focus ring. |
| **J6** | **No egress.** Fail the test on any request to a host other than the server under test — this is N1 as a gate, not a policy. |

An axe-core smoke pass runs on Import and Census; critical violations fail.
Screenshot comparison is **optional and non-gating** (`@pytest.mark.visual`,
Linux/Chromium only) — antialiasing makes it flaky as a merge gate.

### 11.6 Layer 5 — eval

`tests/eval/` behind `@pytest.mark.eval`, against real Ollama, gated on
`evals/baseline.json`. Out of phase 1; the directory and marker exist so the shape is
settled.

### 11.7 Gates

| Gate | Rule |
|---|---|
| `just test` | unit + backend + ui — the commit gate, `-n auto` across every core |
| `just e2e` | Playwright journeys — the PR gate |
| Coverage | `fail_under = 85` on `ra2/domain` and `ra2/services`; no global number |
| ruff | format + check, `PLW1514` on |
| mypy | `strict` on `ra2/`, no `Any` returns from `domain/` |
| import-linter | the §1.1 layer contract |
| alembic | `alembic check` clean |
| CI | Linux **and** Windows for layers 1–3 (N3); Linux for E2E |
| pre-commit | the above, plus a hook refusing any file matching the real-data patterns in `.gitignore` |

---

## 12. Invariants — the Do-NOT list

1. **Never** import `openai` or `ollama` outside the `LLMClient` implementation.
2. **Never** mutate an `extraction`, `record` or `corpus` row. A re-run adds rows.
3. **Never** edit an applied Alembic migration. Add a new one.
4. **Never** open a file without an explicit `encoding=`, and never with
   `errors="replace"`.
5. **Never** read canton, language or table kind from a filename. All three come from
   the data.
6. **Never** silently repair or drop a row. Every one produces a `Finding` carrying
   its key.
7. **Never** put business logic in `ui/`, and never let `ui/` touch a session or an
   ORM object.
8. **Never** hold UI state in module globals; use `app.storage.client`.
9. **Never** fetch anything over the network from the UI — no CDN, no fonts, no
   telemetry.
10. **Never** use `metadata.create_all()`, in the app or in tests.
11. **Never** commit anything matching the real-data patterns in `.gitignore`.
12. **Never** add a branch to production code that exists only for tests.
13. **Never** open, query, print or paste the contents of `data/` or
    `RA2_DATA_DIR`. Reproduce the hazard in a fixture instead.

**On #13.** It is the only invariant addressed to the *people and agents*
building RA2 rather than to the code, and it is here because this project is
built with an AI coding assistant by explicit design (`vision.md` →
Environment) on the machine that holds the real corpus. Agent transcripts are
processed off the host by construction, so an agent that reads a real file to
debug an import has exported that record as surely as an upload would — and
until this rule existed, nothing said not to. Do-NOT #11 forbids *committing*
real data, which is a different act.

It is backed by `permissions.deny` rules over `data/` and `var/` in
`.claude/settings.json`, which is committed rather than ignored so the control
reaches everyone who clones. `RA2_DATA_DIR` is configurable and a deny rule can
only name a literal path, so the rule covers the default `./var` and the
sentence covers the rest — which is why the sentence is the invariant and the
configuration is the backstop, not the other way round.

---

## 13. Deviations and extensions this document introduces

Each is additive and cheap to reverse; none should change silently.

| # | Item | Rationale |
|---|---|---|
| SD1 | `delivery` / `delivery_file` tables, absent from spec §5 | The Import view needs per-file parse state before a corpus exists |
| SD2 | Census materialised at freeze into `census_*` tables | Corpora are immutable, so it cannot go stale; aggregating ~1.5M EAV cells per page load is seconds slow |
| SD3 | IBM Plex **vendored locally**, not from Google Fonts | The design README says Google Fonts; N1 forbids CDN fetches, and N1 wins |
| SD4 | `corpus.description`, `.delivery_id`, `.source_file_ids_json`, `.language_counts_json` | Shown in the design's Corpora table, absent from §5 |
| SD5 | File **kind** determined by header match, not filename | §4.1 bans filename inference but §4.3 presupposes we know the table |
| SD6 | Structured **sets** inferred by FK reachability from the `unfall` file | Same reason; the design's collapsed set rows need a data-driven grouping |
| SD7 | `TaskRunner` seam introduced in phase 1 for import | The spec needs it in §9 anyway; retrofitting progress onto a synchronous import is worse |
| SD8 | Long tail defined as `distinct > 20 and top_value_share < 0.01` | The design states the rendering, not the threshold |
| SD9 | Minimum spec for the file report modal (§8.3) | The design defers it, but the Import row action opens it. **Amended by P3-D22** — remove left the modal for the row |
| SD10 | The API is built in phase 1, not deferred | It is how E2E seeds state, and it is the same services either way |
| SD11 | `prompt_template` is a **table**, not the on-disk template `mvp-spec.md` §10.2 describes (§15.1) | Citation counts, an active flag and "delete only when uncited" are enforceable only where the citations are |
| SD12 | `evaluation_feature` — the per-evaluation `enum_codelist_json` snapshot and final fingerprint, which `mvp-spec.md` §5 puts on `feature` (§15.2) | A frozen `feature_config` is corpus-independent, so the snapshot cannot resolve until an evaluation fixes a corpus |
| SD13 | `evaluation` gains the draft/decoding columns, `run` gains `prompt_template_id` and `status` (§15.2) | The design's "Save draft" means the row exists before the inputs are final; a version integer alone cannot resolve exact text |
| SD14 | The `openai` SDK alone; **PydanticAI dropped** from `mvp-spec.md` §3's stack (§15.5) | One call, one schema, one response — and a second provider client is what Do-NOT list #1 exists to prevent |
| SD15 | VRAM and GPU name **probed** via NVML library bindings, with a config override (§15.6) | The design disables models that exceed VRAM; Ollama does not report it. A `ctypes` library load is not the shell-out N3 forbids |
| SD16 | `score.language` is **`NOT NULL`** with `'*'` for the all-languages row, where `mvp-spec.md` §5 writes `language|NULL` (§16.1) | SQL treats two NULLs as distinct in a unique constraint, so a composite key over a nullable column permits exactly the duplicate rows it looks like it prevents — and "rewrite this feature's rows" would orphan the old ones on every re-score |
| SD17 | Scoring is **chained off the run worker's terminal `done`**; there is no Score control anywhere (§16.1) | Every input is immutable from the launch commit, so there is no moment between a run finishing and its scores existing in which a user could decide anything. The design draws no such button |
| SD18 | `score.metric` is a **closed vocabulary carrying raw counts as well as rates** (§16.3) | The breakdown row needs hit/wrong/missing and the cross-tab needs six cells. Back-deriving counts from three rounded floats is off-by-one precisely at small n, where the number matters most; a second table for them is a join and a migration |
| SD19 | **Suppression is applied at read time** from stored `n`, never as a write-time filter (§16.4) | It is what makes `mvp-spec.md` §11.4's "configurable per evaluation" cheap enough to honour as a column: changing the floor never requires a re-score. Every cell is computed and stored; the read model substitutes the typed insufficient-data shape |
| SD20 | Ranking's presence figure is a **macro presence rate, reported and never scored** — `mvp-spec.md` §11.5 corrected (§16.5) | The design renders it as `0.907` in a ranking table, where it reads as a quality score. §11.2 is unambiguous that presence has no independent gold label, and §11.3's reasoning applies directly: a model that flags everything present maximises it |
| SD21 | `mismatch` is the **first mutable row** in the pipeline, and a re-score **upserts** it preserving `analyst_tag` (§16.6) | Tagging is the whole of F11. `DELETE`-then-`INSERT` is the obvious implementation and it destroys review work silently, at the moment a developer is most confident — they just fixed the scorer |
| SD22 | `ra2/ui/views/results/` is a **package**, the first view in the repo that is (§16.8) | Three tabs of one screen get built by three agents in one wave; three files is what makes that parallel, and a single `results_view.py` would serialise the wave for no architectural gain |
| SD23 | The one **destructive verb** in an append-only pipeline — whole-object discard of a `run`, an `evaluation` or a `delivery` — paid for with an **export**, not an audit trail (§18) | Three inconclusive evaluations are debris an analyst cannot clear, and the workaround for a tool that cannot clean up is editing the SQLite file by hand. Everything discarded is regenerable from immutable inputs; the one thing that is not is `mismatch.analyst_tag`, which is why G2 counts it and announces it. An audit table would have cost a migration and produced rows nobody reads |
| SD24 | `MismatchTag` is a **closed domain enum over a column that stays `String(32)`**, with an `other` bucket for a value it does not name (§17.5) | Both halves are load-bearing and the asymmetry is the point. The enum makes the list, the tally, the CSV and the wire agree on three identifiers and makes a typo a lint error — `FindingCode` is the precedent. The string column keeps `models.py`'s promise that "a fourth tag must be a value, not a migration". The bucket is what stops the asymmetry becoming a crash: a stored value the enum does not name renders as itself and counts under `other`, because a tally that silently omitted those rows would report "of 40 reviewed" over 38 |
| SD25 | Review's staleness anchor is the run's **`finished_at`**; **no `scored_at` column is added**, and a re-score therefore goes undated (§17.7) | A re-score can delete a tagged row under an analyst, so the view owes a visible reason for a list that changed. `run.finished_at` is the closest honest thing that exists: scoring chains off the run's terminal `done` (`SD17`), so for a run scored once it *is* the moment it was scored. Recording a re-score would mean a `scored_at` column, which §16.1 F5 declined so that "how far did it get" has exactly one answer and which `tests/test_p4_contract.py` asserts the absence of by name. The gap is named rather than papered over, and the next step if it bites is a **count of tags lost, not a lock** |
| SD26 | The Mismatches list is scoped to **one run at a time**, with no "all runs" option (§17.6) | `mvp-spec.md` §12 names `run` as part of the row, and a list mixing two models' mismatches for the same record and feature **is** cross-model agreement — one of the three things §16.9 defers by name. Refusing it is not a limitation of the view; it is the deferral, caught where it would otherwise have entered as a convenience. `ResultsService.presence_records` already resolves one run the same way |
| SD27 | The adapter builds its own HTTP transport, with `trust_env=False` and `follow_redirects=False` (§15.5) | The loopback guard reasons about the URL; the transport decides which socket that URL is dialled over, and the `openai` SDK builds its own with `trust_env=True`. On a managed workstation with a machine-wide `HTTP_PROXY` and no `NO_PROXY` for localhost, a request for `http://127.0.0.1:11434/v1` therefore left for the proxy host with the guard satisfied — reproduced on the pinned versions. A redirect is the same hole read the other way: a `307` preserves the body, so the endpoint could hand the narrative to an off-host URL the guard never saw. Both are refused for the same reason the guard has no opt-out |
| SD28 | **Census value samples are exported and rendered only for `ENUM` columns**, and every export carries a classification line (§7) | The census stores the top 20 raw values of *every* column and the census CSV is the week-one deliverable, the artefact most meant to be shared. Measured over the working corpus, the four `Koordinate` columns and the three UID columns held 20 stored values each with 16 to 20 occurring exactly once — a coordinate that occurs once is one accident, at metre precision. The rule is one line in `domain/census.py` read by both callers; only the raw values are withheld, every aggregate survives, and `top_values_withheld` keeps *withheld* distinguishable from *empty*, which are opposite conclusions for feature selection. Applied at read time (the `SD19` shape), so corpora frozen before the rule are covered without a migration |
| SD29 | A **fourth** connect-time PRAGMA, `secure_delete=ON` (§4.4, §18.7) | §18 gave an append-only system one destructive verb, and `mismatch.evidence_span` is verbatim narrative. SQLite's `DELETE` moves the page to the freelist without clearing it, so *discarded* meant *unreachable through SQL*, not *gone* — reproduced at 572 readable occurrences of a deleted span. Chosen over a `VACUUM` after each discard, which is a second thing to remember, means nothing in WAL mode until a checkpoint, and cannot run inside the transaction the discard holds. The default is a compile-time property of the bundled SQLite and reads back `0` here, so it is set rather than assumed |
| SD30 | **`Settings.exports_dir` is removed; no export is ever written to disk** (§7, §10) | It was documented as "where CSV exports are written" and read by nothing but `scripts/reset_data.py` — so `just reset` cleared an empty directory while the exports that matter sat in the analyst's Downloads folder. Building it out was the other option and is worse: a server-side copy does not *replace* the downloaded one, it adds a second copy at rest, of the artefact `B2` says nothing governs. All six exports stay in memory, and where the copies actually are is a sentence in `data-handling.md`, not a directory |
| SD31 | **A prop whose value did not come from this file is assigned through the props *mapping*, never through the props *string*** — `element.props["title"] = value`, not `.props(f'title="{value}"')` (§8.2; the mapping write is spelt `data_props(...)` everywhere but this one site — `SD34`) | NiceGUI's `.props("k=v")` is a parser, not a formatter. `Props.parse` hands every quoted value to `ast.literal_eval`, so the value is read as **Python source**, and the two ways that goes wrong are not equally visible. `_data_dir_chip` interpolated `RA2_DATA_DIR` into a `title=` that way; on Windows `scripts/dev_agent.py` sets that variable to a `tempfile.mkdtemp()` path, so the value was `C:\Users\...` and the `\U` is a truncated `\UXXXXXXXX` escape — `SyntaxError`, every page 500, and `just dev-agent` unusable on the platform. That is the *loud* half. The quiet half is worse and is why escaping the backslashes is not the fix: `C:\tmp\the\new\report` is **valid** Python, so nothing raises and the tooltip reads `C:<TAB>mp<TAB>he<LF>ew<CR>eport` — a chip that exists to tell a developer which database they are looking at, answering confidently and wrongly. Assigning into the `Props` mapping (an `ObservableDict`; the write still triggers `element.update()`) bypasses the parser entirely, and `html.escape` goes with it: the mapping is serialised as JSON and bound as an attribute by Vue, so escaping here would put a literal `&amp;` in the tooltip of any path containing `&`. **The rule is about provenance, not about backslashes.** A `data-testid` written in the source is a literal and stays a string; a filename, a column name, a code label, a corpus name or anything a user typed is not |
| SD32 | **The Evaluation toolbar carries a “New evaluation” button wherever “Save draft” cannot honestly act, and the locked setup column says why it is locked** (§15.2, §8.2) | `design/prompt-evaluation/README.md` §2 draws the toolbar's right group as a WIREFRAME stamp and one secondary “Save draft”, and its fixture shows an evaluation that already exists — so the two states *around* that fixture were never drawn, and both shipped unusable. **Launched:** §15.2 makes every setup control read-only once `launched_at` is stamped, `_can_save_draft` returned `not is_launched`, and `_current_evaluation` falls back to the newest evaluation with no switcher anywhere in `ra2/ui/` — so after the first launch the view was frozen permanently, with **nothing on screen saying why**. The exit was specified and never built: README §2 step 2 reads “editing is blocked — clone into a new evaluation instead” and `FEATURE_SET_NOTE` renders “clone the set into a new one to change it”, and there was nothing to clone into. **Empty:** four of the six steps rendered a message naming “Save draft” — a label describing an *update* to a row that does not exist — while the button itself sat in the toolbar, away from the steps pointing at it. Both sibling views already solve this the house way, with an explicit creation button: Features has “New set”, Prompts “New version”. **The deviation is one label, not one button.** The right group holds exactly one secondary button in every state and the two are **mutually exclusive** — “Save draft” on an unlaunched draft (the drawn state, the drawn label, the drawn behaviour), “New evaluation” in the other two. Two buttons side by side was the alternative and is rejected by the question it raises: `evaluation.name` has no unique constraint and `save_draft` does not dedupe, so a create button that stays on screen after it has created is a button whose second press makes a duplicate nobody asked for and which, with no switcher, cannot be navigated back to. Exclusivity removes the second press instead of guarding it, and does so without a dedupe rule in `ui/`, which would be business logic (Do-NOT #7). The cost is that a *second* draft cannot be started from an existing draft — which buys nothing, because the draft on screen is already fully editable. **No sentinel is added to `EvaluationSetup`.** The obvious design gives the client state a “starting a new one” marker, because `_current_evaluation` falls back to `drafts[0]` whenever the remembered id does not resolve, so merely clearing `evaluation_id` snaps straight back to the launched evaluation. Creating the row **immediately** deletes that problem rather than representing it: the row exists before the redraw runs, `_remember` holds its id, and there is never a “no evaluation selected, but evaluations exist” state. The three fields and the docstring stand. **The clone carries the corpus and the feature set and nothing else** — `save_draft`'s own defaults supply the rest. Copying temperature, seed, size and model selection would make “same as the last run, minus the model” a claim the controls no longer state out loud, and the whole point of six visible steps is that every pinned input is one of them. It takes the cited set's name, the rule `save_draft` has always been called with here, so a clone and its original share a name deliberately: they pin the same set, that is the only thing the name records, and a “(2)” invented in the view would be a fact about this view's history rather than about either row. Finally, `LAUNCHED_MESSAGE` covers the **column**, not step 4: step 4 already carried `MODELS_UNSAVED_MESSAGE` and was the obvious place for a second one, but the lock is not step 4's fact — five other controls are held by the same timestamp and three of them said nothing at all. P3-D21 is untouched: selection still waits for the row to exist; only the affordance that creates it changed |
| SD33 | **A path compared against a POSIX literal is built with `.as_posix()`, never `str()`; and no path is converted on checkout** — `.gitattributes` sets `* -text`, repository-wide (§11.4, §11.7) | CI runs layers 1–3 on Linux **and** Windows (N3), `fail-fast: false`, no `continue-on-error` — and the Windows leg had six failures, the oldest dating to `0461aea`. It has essentially never been green. **That** is the finding, not the six: a gate that is always red is a gate nobody reads, and it is the direct reason `SD31`'s crash — every page of the app returning 500 under `just dev-agent`, on Windows, the platform this half of the matrix exists for — survived until a human found it by hand. Two of the six are the mechanical half of Do-NOT #1: `test_openai_is_imported_in_exactly_one_module` and its `pynvml` twin built `str(path.relative_to(REPO_ROOT))`, which is `ra2\infra\gpu.py` on Windows, and compared it against `"ra2/infra/gpu.py"`. They failed **closed** — reporting a violation that was not there, rather than missing one that was — so nothing was ever unguarded; but CLAUDE.md names these two and `.importlinter`'s `one-llm-seam` contract as what makes the loopback rule a gate rather than a promise, and a guard that cannot pass on a platform it is configured to run on is not one. `Path.__str__` is the platform separator and `as_posix()` is not; every other site in `tests/` that compares a relative path to a literal already used `as_posix()`, and `scripts/check_no_real_data.py` normalises its argument the same way, so this was the exception, not the rule. The other four were **byte-identity** failures: `core.autocrlf=true` and no `.gitattributes` anywhere in the tree, so the committed fixtures checked out CRLF while the generators emit what they emit. The blobs were never wrong — the delivery hazards are stored CRLF, the codelist, prompt and golden fixtures LF, exactly what each generator writes. **Only the checkout was wrong**, so the fix changes no fixture byte and needs no `--renormalize`; it tells git what the bytes already are. **The rule is `* -text`, and the narrow alternative is worse than it looks.** `* text=auto eol=lf` is the reflex and is refused outright: it *renormalises*, rewriting every tracked file's stored bytes, which would destroy the delivery hazards. `-text` is a different attribute — it forbids conversion in both directions and changes no blob — so applying it to everything is the cheap, total answer: every file checks out with the bytes it was committed with. Naming the four asserted families individually was the other candidate, and **mixing the two is actively wrong**: `eol=lf` lines placed after `* -text` match last, and last-match-wins would re-enable conversion on precisely the paths whose bytes are asserted. One rule, or the other, never both. **The delivery hazards are why no text conversion is acceptable anywhere.** They are CRLF *by construction* — `generate_hazards.py` joins every line with CRLF because the delivery it stands in for does — and `h13_astrana_blank_row` carries Astrana's doubled CRLF (`\r\r\n`), which **no text conversion survives**: git's clean filter rewrites `\r\n` as `\n`, so it rewrites `\r\r\n` as an ordinary `\r\n` and silently deletes the hazard the fixture exists for. `eol=crlf` round-trips through LF and would do precisely that, which is why the two are not interchangeable here — `-text` converts in neither direction. `-text` is a *git-side* attribute and changes nothing about how Python opens a file, so `scripts/check_no_real_data.py` still reads all fourteen as text; `diff` is set alongside it so `git diff` renders them as text rather than as "binary files differ". **The Linux leg cannot regress**, and that is checkable rather than hopeful: no blob changed, `eol=lf` is a no-op on a runner whose checkout already produced LF, and `-text` on a path whose blob already holds its exact bytes means checkout copies them verbatim — which is what `core.autocrlf=false` was already doing. Finally, `tests/test_fixture_line_endings.py` asks **git**, through `git check-attr`, whether every file under `tests/fixtures/*/hazards/` is pinned at all. Every family resolves `text: unset`, because one rule covers them all; and because it reads the repository's declaration rather than this filesystem's bytes, it answers the same on both platforms, so a hazard family added on Linux fails there instead of six months later in a leg on the other one |
| SD34 | **`ui/components/primitives.py::data_props(element, {...})` is the one way a data-derived prop is assigned, `html.escape` is gone from every one of them, and a static test keeps *text-carrying* props out of props strings** (§8.2, §11.3) | `SD31` stated the rule and fixed one call site. The rest of the class was still there: **forty-eight** sites across seventeen files, sixty props, interpolating a filename, a column name, a code, a corpus name, a user-typed feature-set name, a model tag or `RA2_LLM_BASE_URL` into a props *string*. Nine of them are inside `primitives.py`'s own helpers, so every view inherited it. Reproduced against the pinned NiceGUI, the failure is worse than `SD31`'s crash because it is **silent**: with `value="{name}"`, a set named `draft\` parses to `{'type': 'text', 'data-testid': 'rename-input'}` — the trailing backslash escapes the closing quote, the regex resyncs on the next pair, and the `value` prop is simply **absent**. The rename box opens empty over a name the analyst cannot see, so the next keystroke renames the set to something else. A Linux-legal `Unfall\next.csv` reaches an `aria-label` with a literal newline; `colA\tname` with a tab. **A shared helper, not forty-eight `element.props[k] = v` lines.** The ad-hoc write is what `SD31` did once and is right for once; repeated it leaves the rule as an unwritten convention in seventeen files. Every one of them already imports the kit, so the helper costs one name where the convention costs a reviewer's memory. It returns the element, so it drops into the chained builders the kit is written in rather than breaking them into statements, and its docstring is where the parser trap is explained once instead of in seventeen comments. **`html.escape` comes off, and that was checked rather than assumed.** `SD31` removed it from a `title=`; the same argument was re-verified for `value=` on a Quasar input and for `data-*`, where it might not have held. It does: `nicegui.js` `renderRecursively` spreads `element.props` straight into `Vue.h(tag, props, slots)`, and Vue sets those through `setAttribute`/DOM properties. **No HTML parser sits anywhere on that path**, so an escaped value is not unescaped by anything — `A & B` would reach the screen as `A &amp; B`. Escaping was also never load-bearing: it prevented none of the four parser failures, including at the two sites (`feature_sets_table`, `derivation_builder`) that already called it. `evaluation_view._attr` was `html.escape(quote=True)` under another name, had exactly one caller, and is **deleted** rather than kept — a helper named for the thing it does not accomplish is how this came back. **The recurrence guard is a floor, deliberately.** Provenance is semantic: nothing static can decide whether the string in a variable came from a delivery or from the line above it. A check that tried would either miss the harmful cases — `data-testid="sort-{column.key}"` is a delivery column name in a structural-looking key — or reject the ~50 legitimate `colspan="{len(columns)}"` sites and be switched off within a month. `tests/ui/test_props_provenance.py` therefore checks the one thing that *is* decidable and that no legitimate site needs: a **text-carrying** attribute (`aria-label`, `title`, `value`, `placeholder`, `alt`, `label`, three `aria-*` text twins) never carries an interpolation in a props string. Those are also where corruption is invisible — a mangled `data-testid` fails an E2E selector loudly, a mangled `aria-label` fails nothing and lies to a screen reader. It adds no branch to production code (Do-NOT #12): it reads `ra2/ui/**` with `ast`, the way `test_p3_contract.py` reads the import graph, and it costs a legitimate future site one mapping entry. The remaining ~60 interpolations are `int`s, enum `.value`s, `"true"`/`"false"` chosen from a `bool`, and `data-testid` slots whose callers pass source literals — all of them source-decided, none of them reachable by a delivery |
| SD35 | **The evaluation-scoped discard is the runs card's header control, not a toolbar button; it stays on screen while a run is active; and Export before it is one pair of files per run, never one merged file** (§18.5, §18.2, `SD32`, Do-NOT #7) | §18 specified whole-object discard for a `run`, an `evaluation` and a `delivery`, and for the evaluation the service, the route and the read model all shipped — `evaluation_preview`, `DELETE /api/v1/evaluations/{id}`, `DiscardPreviewView.runs` summing the counts across an evaluation's runs. **Nothing in `ra2/ui/` ever called them.** §18.6 names the *delivery* affordance as deliberately deferred and says nothing about this one, so the gap read as an oversight rather than a decision, and it was: the analyst's only route to clearing an evaluation was the per-run `discard`, one row at a time, which leaves the `evaluation` row itself behind permanently — with no switcher anywhere in the view (`SD32`), a debris row that `_current_evaluation` can fall back to forever. **Placement is the decision, so containment is the assertion.** `SD32` settled that the toolbar's right group holds exactly one secondary button in every state and that the one it holds is the *creation* affordance — “Save draft” or “New evaluation” — pressed routinely and by habit. A destructive verb one gap from a habitual one is a mis-click, and §18 gave this pipeline exactly one destructive verb without giving it an undo. The runs card's header is also the one place the **scope** reads off the screen without a sentence explaining it: the card whose every row carries a bare `discard` gets, in its header, the one that takes the whole list. Two alternatives are rejected. A row-level “discard all” is a bulk verb over a destructive operation, which §18.6 already refuses. A toolbar button behind an extra confirm guards the second press instead of removing it — the same move `SD32` rejected for the duplicate-draft problem, and for the same reason. **It stays on screen while a run is active, which is the one place it departs from the row version.** A row hides its `discard` while `queued` or `running` because *that row is the obstacle* and there is nothing further to say. An evaluation's obstacle is a different row in the same table, so hiding the action would remove the only route to it and explain nothing; instead the action opens and the dialog renders G1's refusal naming the run that caused it (`DiscardPreviewView.active_detail`, §18.2). That is §15.5's argument about an unreachable endpoint applied one scope up: a state the UI can only discover by provoking an error is not a state it can render. **Export stays per run, and the dialog says so rather than apologising afterwards.** `LifecycleService.run_export` is per run and there is no evaluation-wide export. Merging several runs' rows into one file needs a `run_id` column, a rule for how two runs' score rows sit beside each other, and a header naming an evaluation rather than a run — three decisions about what the data *means*, which is `export_service`'s business and not this layer's (Do-NOT #7). Making them in the view would also give the CSV obtained from the header a different shape from the one the same analyst gets from a row, for no reason but which button was pressed. So the honest answer is N pairs, and `EXPORT_PER_RUN` states it while the dialog is still open instead of after N downloads have started. It renders only when `preview.runs > 1` — read off the view's own count, not a judgement made in `ui/` — and a run that recorded neither a score nor a mismatch is skipped rather than written as two header-only files, the rule `loss_line` and `has_exportable` already apply to their zero counts. The downloaded name is taken from `RunExportView.run_id` rather than the id the caller asked for: identical for a row press, and the only correct one for a bundle, so a set of files from one evaluation is still self-describing once it is on disk |
| SD36 | **The reasoning effort is a per-evaluation pinned input — `evaluation.reasoning_effort`, step 5's third control — and `LLMClient.extract` takes it per call** (§15.2, §15.5, mvp-spec.md §19.8) | `090e7fdc12c5` pinned `RA2_LLM_REASONING_EFFORT` on the `run` row because two runs that asked different questions must not record identical provenance: measured on the reporting host, the same record costs **190 s** at the model's own default and **6 s** at `none`, and both answer correctly. It left the *choice* in the environment, so the comparison that column exists for — its own docstring's "set `high` and launch a second evaluation to compare" — meant editing an environment variable and restarting the app between two evaluations that are meant to be comparable. An input that decides the answer as much as the temperature does, and that the analyst is expected to vary *between* evaluations, is a column and a control. **The vocabulary moves to `domain/llm.py`** (`REASONING_EFFORTS`, ordered): `ui/` may not import `infra` and the select needs the list, while `Settings` still needs it to refuse an unmappable value at construction — `domain` is the one package all three may read, the move `is_loopback_url` already made. **`extract` grows a keyword rather than the client growing a second instance:** the effort now varies between two runs executing in one process, and a constructed value could only express that with a client per run — a second loopback guard, a second connection pool, constructed inside the record loop. `None` means "the client's default", so `main.py`'s wiring is unchanged and a run queued before the column existed still asks what `Settings` says. **NOT NULL with a `none` backfill, where the run column is nullable with none:** a `run` written before that revision genuinely does not know what it asked, and a guess would be invented provenance; an `evaluation` is a *setup*, and every row that predates the column ran under the process default, so `none` is a fact about them. The choice is refused in the **service**, not by a `Literal` on the request schema: the repair is "pick one of these four" and the sentence that says so is `EVAL_ERROR_UNKNOWN_REASONING_EFFORT`'s, where a schema error would name the field instead |
| SD37 | **Three presentation rules the design files state differently: a latency renders in seconds to two decimals, every timestamp renders in the host's zone, and two explanatory paragraphs on the Evaluation screen are not rendered at all** (§8.2) | All three are `plan-evaluation-view-improvements.md`, and each is a case where the drawn copy was right about the fact and wrong about the rendering. **Latency in seconds** (`primitives.format_latency_ms`, one formatter for the progress card's metrics line, Ranking's Median latency column and the connection probe): the design writes `812 ms` and `1 340 ms`, but the figure is a *measurement compared between models*, and the range it has to span on real hosts is 0.4 s to 190 s. One unit and one precision is what makes a column of them comparable; `_format_duration_ms` is deliberately **not** reused, because it is for spans a person waits out and renders a sub-second value as `0 s`. A value above zero that rounds to `0.00` renders `< 0.01 s` — a probe answers in single-digit milliseconds, and `0.00 s` there reads as *zero* rather than as *instant*, which is `SuppressedCell`'s rule one layer down. **Local time** (`primitives.format_local`, at all eight render sites): every stored instant is aware UTC and stays that way in the database, the exports and the API — the only thing a shared instant can mean across two hosts — while the screen is read by a person sitting at *this* host. RA2 is loopback-only (N1), so `astimezone()` with no argument is that person's zone and no setting, browser round trip or `Settings` field is needed to find it. A naive value is read as UTC, which is what `UtcDateTime` and `Clock.now()` both guarantee; reading it as local would shift it silently. **The two paragraphs** — step 2's "already frozen" note and the reproducibility card's prompt-template explainer — were true, stayed true, and stopped being *new* on the twentieth viewing, in a 430px column six steps deep where every line pushes Launch further down. What made each load-bearing survives elsewhere: `launch` refuses an unfrozen config (`EVAL_ERROR_CONFIG_NOT_FROZEN`), and the card still renders the template version and fingerprint the explainer was describing. The design READMEs are left as the drawn board — they are the handoff record, not a live spec — and the argument against reinstating each from the mock lives in `evaluation_view`'s own docstring, where the next reader of that file will meet it |
| SD38 | **Records run in parallel per model, by a measured map; the run pins its value; and the ranking reports time per record beside a marked latency** — `RA2_LLM_PARALLEL_CALLS`, `run.llm_parallel_calls`, `RankingRow.ms_per_record` (§15.4, §16.5, `plan-parallel-calls.md`) | An evaluation's wall time is `records × models × time per call`, and every call was awaited one record at a time. Scoring 48 records × 7 features takes 0.14 s, so the calls are the whole cost. `plan-parallel-calls.md` §1 measured the alternative on this host's own prompts. `qwen3:8b` runs **2.3–2.5× faster at four calls in flight, with answers inside serial noise**, while `gemma3:4b` and `granite4.1:8b` get the same speed-up and change 14–29 of 48 answers. So the answer is **per model, and a setting, not an evaluation input**. Whether a model tolerates batching is a calibration of this host, this Ollama build and this model, measured once. It isn't a question an analyst asks per evaluation, and an input would let two evaluations of one model differ by a number nobody chose on evidence. **A JSON map from tag to count, default `{}`**, values `1..8`, refused at construction like `RA2_LLM_REASONING_EFFORT`. The tag is the key because it's what the analyst selects. The run already records the digest, so a re-pull is visible in provenance. Enforcing it was left out here and is `SD40`'s: the entry now applies only with a matching passing gate. **Pinned on the run, NOT NULL, backfilled `1`.** Unlike `llm_reasoning_effort`'s nullable column, the backfill is a fact: no code before this revision ever put two records in flight. Resume reads the pin, not the map, so one run's rows never mix two latency regimes. It rides on `ProvenanceView` beside temperature and seed, not on `RunView`: it's a pinned input, and the runs table has no column for inputs. **One code path.** N=1 is one worker in the same pool, not a surviving serial loop kept for safety. Two loops would be one tested and one trusted, and a branch that exists only because tests drive N=1 is Do-NOT #12. **The ranking can't keep median latency as the only cost column.** Per-call latency *rises* with parallelism, 1.7 → 2.7 s for `qwen3:8b` at four, even as throughput doubles, so in a table mixing one run at 1 and one at 4, the faster model reads as the slower one. Wall-clock throughput was the first answer and is refused: `started_at` is restamped by every Resume and `extraction` carries no timestamp, so committed rows over `finished_at − started_at` divides a whole run's rows by its *last* stretch and overstates any resumed run. **Little's law** gives the figure without either: with N calls kept in flight, throughput is N ÷ mean latency, so time per record is `mean(latency_ms) ÷ llm_parallel_calls`. It's computed over the same rows the median already reads and survives Resume by construction. It is also honest where Ollama queues instead of batching: the queue wait is inside each call's latency, so a refused architecture at N=4 reports its serial rate, not a quarter of it. Checked against measurement: 48 × 2.72 s ÷ 4 = 32.6 s predicted, 32.4 s measured. Reported, never scored (`SD20`), and the median latency cell carries `×N` when N > 1, because the number is true but no longer comparable down its column |
| SD39 | **`create_engine` passes `hide_parameters=True`; the log's content rule is enforced at the engine as well as at the call sites** (§4.4, `data-handling.md` §5.1, risk-assesment.md A5) | `data-handling.md` §5.1 names `record.text_raw`, model output and `unfall_uid` on a **"may never appear"** list, and puts `run.error` on the other side as *this application's own sentence about a run*. That description was true of every error this code **writes** and false of the ones it merely **catches**. `run_service._error_text` is `f"{type(exc).__name__}: {exc}"` for anything that is not a `FeatureValidationError`, and SQLAlchemy's `hide_parameters` defaults to `False` — so `str(exc)` carries the bound parameters of the statement that failed. For an insert over `record` those are the narrative and the delivery key; for one over `extraction`, `raw_output_text`, the model's entire answer. That string is persisted on the row, rendered by the runs table's log action **and written to stderr**, which is the artefact `infra/logging.py` exists to keep safe for an agent to paste into a bug report — so the leak arrived at the moment somebody was asked to look, and via somebody following the rules (Do-NOT #13). Reproduced through the real service: a provoked `IntegrityError` logged the whole JSON answer at `WARNING`. **Why the engine and not the call site.** No call site was wrong. `_error_text` is a reasonable function, `_finish` logs a reasonable line, and a reviewer reading either would have seen nothing — the content was appended by the driver, below both. A rule enforced only where lines are *written* cannot reach that, so the flag is set once, on the one engine factory §4.4 already says owns the connection's configuration, and nothing has to be remembered per call site. **Why not filter `_error_text` instead**, which was the other candidate: it would mean matching SQLAlchemy's `[parameters: ...]` formatting with a regex — a parser for a format nobody promised, defeated by any other driver or a future SQLAlchemy, and silent when it missed. It would also leave `echo=` untouched, which prints the same parameters by a different path. `hide_parameters` covers both and is the vendor's own switch. **The cost is real and accepted**: a constraint violation no longer says which values caused it, so a genuine data bug is diagnosed from the constraint name and a query the developer runs on the machine. That is the trade `data-handling.md` §5 already makes everywhere else, and §9.1.1's finding is that the diagnostic path is the egress path. **The control is what makes the test a test**: `test_engine_hides_parameters.py` asserts absence, which passes for a suppressed exception, an unplanted value or a statement that never failed, so a sibling runs the same insert through a default-built engine and fails if the narrative is **not** there |
| SD40 | **A model's fitness is a stored measurement, a qualification per (tag, digest) on this host, taken by a command; the launch honours a parallel-calls entry only with a matching passing gate; and the Models card shows the facts, never a verdict** — `model_qualification`, `ra2/domain/qualification.py`, `QualificationService`, `just qualify-model`, `ModelCatalog.version()` / `loaded()` (§15.2, §15.4, §15.5, §15.7, `plan-model-choice.md`) | Everything RA2 knew about which model to run was in two documents, and the one setting that depends on a measurement, `RA2_LLM_PARALLEL_CALLS`, was guarded by a docstring sentence ("Code can't check that; this sentence is the check"). SD38 keyed that map by tag and left enforcement out, so `ollama pull` could replace the weights behind `qwen3:8b` and the old entry kept applying to weights nobody had gated. And the scripts that produced every number in `docs/choosing-models.md` no longer exist, so qualifying a new model meant three GPU-hours of work redone by hand. **A qualification is a row, not a file.** It is this host's calibration, it wants the backup, reset and locking the rest of the data has, and a second persistence mechanism would need its own rules for all three. It is **append-only** like `extraction` (Do-NOT #2 treated as a rule, though the table isn't named in it): re-qualifying adds a row and the newest per (tag, digest) wins. `just reset` wipes it with everything else (plan-model-choice.md Q3). It carries **numbers only**, measured over the synthetic seed in a throwaway data dir: no delivery content reaches it, by construction, because the qualifier never opens a corpus of the target database. **The command is wiring.** `scripts/qualify_model.py` seeds a throwaway `RA2_DATA_DIR` through `seed_dev`'s own functions, drives ordinary evaluations through `create_app(mount_ui=False)` exactly as `seed_dev.py` does, lets `QualificationService.summarise` derive the figures there, then records the result through `QualificationService.record` on the configured app. Repeated passes are clones (SD32), so no pass shares a run. It refuses to start a pass while any other model is loaded on the endpoint (`ModelCatalog.loaded()`, `/api/ps`), because a resident model hides the speedup entirely (`plan-parallel-calls.md` §1.1 point 3). It never starts or stops Ollama: two servers, one at one slot and one at N, are the operator's to name, and RA2 records what it was told, because it cannot read `OLLAMA_NUM_PARALLEL`. Both endpoints go through `OllamaLLMClient`, so both are loopback-only with no opt-out (§15.5). **The gate is one pure function** (`gate_verdict`), stated once where `plan-parallel-calls.md` §4.1 stated it in prose: the noise band is the largest differ count among three one-slot serial passes, **floored at 2 of 48** and scaled to seed size (three passes is too small a sample; a 0-0 baseline would fail `qwen3:8b` on one flipped token, and 2 of 48 is the difference `docs/performance.md` §6 already calls noise between two ordinary runs; a constant, not a setting, so the gate cannot be loosened until a model passes). A pass differs on a record when its canonical JSON does; an unparseable answer is its own answer, and two passes over different record sets are refused, not counted. **The launch decides with `parallel_decision(mapped, qualification, digest, ollama_version)`**, the only place the rule exists: the map entry applies when the newest qualification for this tag *and digest* passed at an N' ≥ N **on the same Ollama version**; anything else pins **1**, never a lower non-1 value nobody configured (Q5), and the run-start log names the reason (`gate=missing|digest|ollama_version|failed`). The Ollama version is compared because its bundled llama.cpp decides both whether batched answers move and which architectures it refuses to batch, and both change between patch releases; the full string, from one `/api/version` call per launch, not per record. **The GPU name is recorded, not compared**: qualifications live in the database of the host that measured them, so a different GPU is a hardware swap under one install; the name is often unknown, and an unknown cannot be compared without either blocking every non-NVIDIA host or checking nothing; and it misses the driver and CUDA versions that matter more. Falling back to serial rather than refusing the launch is deliberate: a serial run is always correct, only slower, and a refusal would block an evaluation over a performance setting. **The Models card shows facts, never a verdict.** Each row gains one mono line (seed F1, time per record, entity fill, the scope's estimated duration, `parallel ×N` when the launch would honour it), or a stale-digest, server-sensitive or not-measured state. The service hands over numbers and an enum; wording lives in `ui/`. There is no "recommended" badge: the seed puts a perfect reader at ~90 % and the leaders at that ceiling, so any badge the data could produce would rank ties; the recommendation stays in `docs/choosing-models.md` §1, a human judgement with its reasons. `EvaluationService` reads qualifications through their repository, not through `QualificationService`, so no new cross-service protocol is needed. The API mirrors the card on `ModelChoiceResponse` and offers **no write**: recording a qualification is the command's job, and a `POST` taking numbers would let anything claim a measurement |

**Note on the design's fixture column names.** `UnfallTypAusw`, `WitterungAusw`,
`LichtverhaeltnisAusw` and `UnfallDatumFeld` do not exist in the delivery; the real
columns are `UnfTypAusw`, `Witter0Ausw`, `LichtVerhAusw`, `UnfDatumFeld`. The design's
fixtures are illustrative. **Column names are only ever read from the header.**
The design's "162 columns" does check out: 67 + 77 + 18.

---

## 14. Codelists (F3)

**Not yet built** — Import and Census are the only shipped views (§8.1). This
section exists so the wave that builds Codelists starts from an architecture,
not a blank page, now that `design/code-feature/README.md` (Screen 1) and
`mvp-spec.md` §5/§7 exist. It also resolves the design's open question 1
("codelist JSON schema... confirm against the real VUM export"): the schema
below is the one actually produced by `data/Codes/codes-2018.json` and is
taken as settled unless a real VUM export proves otherwise.

### 14.1 Import is an upload, not a seed

The design's "Import Codes as JSON" button (one file, all attributes) goes
through the **same `FileStore` seam as delivery intake** (§6.1), not a
baked-in app resource: `{RA2_DATA_DIR}/codelists/{code_table_import_id}/`.
This matches how delivery files work — externally-sourced, versioned by
upload, never committed to the repo — and it is why `data/Codes/*.json`
being gitignored (per `.gitignore`'s blanket `data/` rule) is *correct*, not
an oversight: it is the analyst's working copy, uploaded through the view
like any other input, not a shipped resource under `ra2/`.

Validated shape (Pydantic, `domain/codes.py`), matching `codes-2018.json`:

```jsonc
{
  "<attribute_key>": {                    // e.g. "accident_type", "road_type"
    "chapter": "4.1.4",                   // optional — absent for non-chapter attributes
    "name": { "de": "...", "fr": "...", "it": "..." },   // languages present may vary
    "codes": {
      "<code>": { "de": "...", "fr": "...", "it": "..." }  // languages present may vary per code
    }
  }
}
```

Import is a single transaction (mirrors corpus freeze, §6.3):

1. Parse and validate against the schema above; any structural error **fails
   the whole import** with a `Finding`-style report — no partial import, no
   best-effort row skipping (Do-NOT list #6 applies to this data the same as
   to a delivery row).
2. Hash the uploaded file (`sha256`) into an additive column,
   `code_table_import.source_hash`, absent from mvp-spec.md §5 (same pattern
   as §4.3's additive columns on spec tables). If it matches the most recent
   import's hash, the upload is a no-op (reported as "already current"), not
   a duplicate generation.
3. Otherwise, write one new `code_table_import` row plus its `code_attribute`
   and `code_value` children — additive, per mvp-spec.md §5's "never edit
   `code_value` or `code_attribute`" rule. Existing `column_mapping` rows are
   left pointing at the old generation until an analyst re-points them.

### 14.2 Mapping and coverage

`column_mapping` (mvp-spec.md §5) is the only editable state this feature
introduces — a `(corpus_id, source_column) → code_attribute_id` pointer nothing
else reads destructively.

**Coverage cannot be read off the materialised census.** `census_value` keeps
only the top 20 values per column (§4.2) — enough for the Census view's
long-tail question, not enough to say *every* code in, say, a 24-code
attribute has a label, since a rare code can fall outside the top 20. Enum
column cardinality is bounded by its code table (tens, not thousands), so
`codelist_service.coverage(corpus_id, source_column)` computes a fresh
`GROUP BY value_raw` over that column's EAV cells directly — cheap at this
cardinality, and it is the only way to get an honest per-code count. This is
a deliberate departure from "the census tables exist precisely so no view
queries EAV directly" (§4.4): that rule holds for the Census view's own
numbers, not for this one, narrower, small-cardinality read.

Per mapped column, per configured prompt language:

- **missing** — no `column_mapping` row, or the mapped `code_attribute` has
  zero `code_value` rows.
- **partial** — at least one `code_value` used by a corpus row has no label
  in the configured language (the known case today: `main_cause`,
  `main_cause_subgroup`, `main_cause_group` have no `it`, mvp-spec.md §7).
- **ok** — every code appearing in the corpus has a label in that language.

A code appearing in the corpus with **no row at all** in the mapped
attribute's code table (not even in another language) is the `Finding`-grade
case mvp-spec.md §7 already names — surfaced as the design's danger row
("no label — not in the codelist"), not folded into "partial".

`enum_codelist_json` (the fingerprint input, mvp-spec.md §8.5) is this
coverage computation's `code_value` side only — the snapshot is taken once,
at evaluation creation, exactly as §8.5 already specifies.

### 14.3 Package layout additions

```
domain/
  codes.py                  Pydantic schema for the imported JSON + validation
  codelist_coverage.py       compute_coverage(cells, mapping, code_values) -> ColumnCoverage (pure)
persistence/
  repositories/
    codelist_repo.py         code_table_import / code_attribute / code_value / column_mapping
services/
  codelist_service.py        import (§14.1), map, coverage query, unmap
ui/
  views/codelists_view.py    master/detail per design/code-feature/README.md Screen 1
```

`codelist_coverage.py` sits in `domain/` like `census.py` and `typehint.py` —
pure, no SQLAlchemy — even though its caller (`codelist_service.py`) is the
one running the `GROUP BY` query and handing it plain cell values.

### 14.4 What this section deliberately does not decide

- **Features' "used by" cross-links** (design Screen 1's "used by Right of
  way") are inert until the Features view exists. `code_attribute`/
  `column_mapping` carry no FK to a feature table yet — adding one is that
  wave's job, not this one's.
- **A second code source (e.g. a real VUM export)** is out of scope until B1
  (mvp-spec.md §18) is resourced. The schema in §14.1 accommodates it: a
  second `code_table_import` with different `attribute_key`s, mapped
  independently per column.

---

## 15. Prompts and Evaluation (F5, F6)

**Contract frozen at M17, bodies from Wave 1 on.** Codelists and Features
shipped in phase 2; M17 added this section's tables, seams and stubs and the
eighth nav entry, and the nav's Run group still routes to `placeholder_view`
(§8.1) until Wave 4. This section is the architecture the phase-3 waves build
against, written before them rather than discovered inside them, now that
`design/prompt-evaluation/README.md` and `mvp-spec.md` §9/§10 exist. It is also
the first section in this document to describe code that **makes an outbound
request** and code that **runs for an hour**, which is why it spends most of its length on two boundaries: the
transaction boundary (§15.3) and the process boundary (§15.5).

It resolves three of the design's open questions: prompt language belongs to
the **evaluation** (§15.2), template naming stays a **bare integer lineage**
(§15.1), and an unreachable endpoint **blocks Launch** with the reason beside
the endpoint line (§15.5). Its own deferrals are §15.8.

### 15.1 The prompt template is a row, not a file

`mvp-spec.md` §10.2 says "a versioned **on-disk** template". That is wrong for
what the design asks of it, and this section corrects it (**SD11**): the
design's version list carries a citation count per version, an active flag, a
per-version fingerprint, and "delete only when nothing cites it". Each of
those is one foreign key in a table and one filesystem convention on disk, and
the one that matters — a cited version can never be edited or deleted — is
enforceable only where the citations are.

```
prompt_template(id, version, source, created_at, activated_at, fingerprint)
               -- IMMUTABLE. version UNIQUE. A save is a new row, never an UPDATE.
```

**Copy-on-write, not versioning-by-convention.** Saving is `INSERT` at
`version + 1`; the previous row's `source` stays **byte-identical**, because
the runs citing it must keep resolving to the exact text they used. There is
no `PATCH` route and no service method that updates a `source` — the absence
is the contract (§15.7's package list has no `update_template`). Deleting is
allowed only when no `run` cites the row; otherwise the version renders
`locked`, exactly as the design draws it. `activated_at` marks the one version
new evaluations default to; activating another clears it. One lineage,
integers `v1…vN`, **no names** — names are what a forked template needs, and
nothing in the MVP forks one.

**The slot catalogue is closed**, and lives in `domain/prompt.py`:

| Slot | Required | Resolves to |
|---|---|---|
| `{{feature_block}}` | yes | one `name — type` line per labelled feature, plus the **full code → label list** per enum feature from `enum_codelist_json` (`mvp-spec.md` §10.2), plus each exploratory attribute's description verbatim |
| `{{narrative}}` | yes | `record.text_raw`, **verbatim** |
| `{{language}}` | no | the evaluation's `prompt_language` (§15.2) |

Validation runs on save and **blocks** it: an unknown slot, a missing required
slot, or a malformed half-brace (`{{narrative}`) is an error carrying the slot
name. A duplicated slot is legal. Resolution is **single-pass** substitution —
a narrative containing `{{` is text, not a slot, and must never be
re-expanded.

**Two fingerprints, one algorithm.** `compute_template_fingerprint(source)` is
sha256 over the exact source bytes, through the same canonicalisation
`domain/fingerprint.py` already uses for features (`mvp-spec.md` §8.5), so the
two cannot drift. Whitespace is part of a prompt: a template differing by one
space is a different template, and its fingerprint says so.

**Token counts are estimates, and say so.** An exact count needs the model's
tokeniser, and every tokeniser package downloads its vocabulary — egress, N1.
`estimate_tokens()` is pure and arithmetic; the preview renders `≈ N tokens`.
The **real** counts come back from the endpoint per call and are stored per
extraction, which is where a number has to be right.

### 15.2 An evaluation pins; a launch snapshots

`mvp-spec.md` §9's "one corpus + one feature config + N models" is the whole
of what an evaluation is — but the design also has a **"Save draft"** button,
so the row exists before the inputs are final. The spec's `evaluation` table
grows the setup it was always implying (**SD13**):

```
evaluation(id, name, corpus_id, feature_config_id, prompt_template_id,
           prompt_language, temperature, seed, reasoning_effort, size,
           selected_models_json, created_at, launched_at, is_dev)
          -- reasoning_effort added post-phase-5 (SD36): step 5's third
          -- pinned input, copied onto every run the launch creates
          -- editable while launched_at IS NULL; immutable after
          -- prompt_template_id is NULLABLE: "Save draft" means the row can
          -- exist before any template does; the launch transaction requires one
run(... , prompt_template_id, prompt_template_fingerprint, status, error,
     llm_parallel_calls)
          -- status: queued | running | done | failed | interrupted
          -- no records_done column (§15.4); `error` is the design's "log" action
          -- llm_parallel_calls (SD38): records in flight, pinned at launch
          -- from RA2_LLM_PARALLEL_CALLS[model tag] when SD40's gate allows it,
          -- else 1; NOT NULL
model_qualification(id, model_tag, model_digest, ollama_version, gpu_name,
                    ra2_version, measured_at, seed_records,
                    quality_json, gate_json)
          -- SD40: this host's measurement of one (tag, digest) over the
          -- synthetic seed; append-only, the newest per (tag, digest) wins;
          -- numbers only; not referenced by any other table
```

`prompt_template_fingerprint` is stored on the run although it is reachable
through `prompt_template_id`, because `mvp-spec.md` §19.8 asks for the run's
**own record** to be sufficient to reproduce it and a join is not a record.
`RunStatus` and the `full`/`dev` `EvaluationSize` live in
`domain/extraction.py` beside the shapes a run produces, the way
`DeliveryStatus` lives in `domain/delivery.py` (P3-D2).

`run.prompt_template_version` (`mvp-spec.md` §5) stays as the human-facing
citation; `prompt_template_id` is added beside it because a version integer
alone cannot resolve exact text once a lineage is long.

**`prompt_language` lives here, not on the template.** It is the first
persistent home for a value `codelists_view` and `features_view` already
select and store nowhere, and it belongs with the other per-evaluation
resolutions for the same reason they do: the codelist labels the prompt
carries are language-specific, and which language is a property of the
question being asked, not of the wording asking it.

**The launch transaction is where fingerprints resolve.** §14.2 says
`enum_codelist_json` is snapshotted "once, at evaluation creation, exactly as
`mvp-spec.md` §8.5 already specifies", and phase 2 then decided a frozen
`feature_config` is corpus-**independent** and reusable across evaluations. Both
hold, and together they mean the snapshot cannot live on `feature`: the same
frozen config cited against two corpora has two different `column_mapping`
generations under it, and therefore two different codelist snapshots and two
different fingerprints. So a new table carries the per-evaluation resolution
(**SD12**):

```
evaluation_feature(evaluation_id, feature_id, enum_codelist_json, fingerprint)
                  -- written once, inside the launch transaction
```

"Evaluation creation" in §8.5's sense is therefore the **launch commit** — the
moment the inputs stop being editable — not the moment a draft row appears. A
draft is a saved setup; an evaluation is a pinned one. `feature.fingerprint`
(phase 2) remains the draft-time **preview**: the same function over the same
inputs minus the codelist snapshot, which is exactly why a preview badge and a
run's fingerprint can legitimately differ.

In one transaction, launch: verifies the cited `feature_config` is frozen
(refusing an unfrozen one, creating nothing), writes `evaluation_feature` for
every feature, sets `is_dev` from the size choice against
`RA2_EVAL_RECORD_MIN` / `RA2_DEV_RECORD_MAX`, stamps `launched_at`, and
creates one `queued` `run` per selected model. After it, every edit path
raises.

**After the launch, the way on is a new evaluation, not an edit.** "Every edit
path raises" is a rule about the row; the view owes the other half of it, and
for a while did not pay it — the setup column simply went dead and offered no
way back to an editable one. It now states the reason where the controls are
and carries the "clone into a new evaluation" the design's own step-2 copy
prescribes, as one toolbar button that is never on screen beside "Save draft"
(**SD32**). Nothing about this section's transaction changes: a clone is a new
draft citing the same corpus and the same frozen set, and the launched row is
read from and never written (Do-NOT #2).

**A dev run's record selection is deterministic** — the first
`RA2_DEV_RECORD_MAX` records by id. "A re-run is a check, not a new sample"
(the design's own purpose line) is false the moment the selection is random:
the seed fixes what the model does with what it sees, and determinism has to
cover what it is *shown* too.

### 15.3 Extraction — one record, one transaction

`mvp-spec.md` §10.1 fixes one LLM call per (record, model) covering all
features, and N5 makes extractions immutable. This section fixes the
**boundary**, because that is what makes N6's restart-safety true rather than
aspirational:

> One `extraction` row, its `extraction_value` children and its
> `extraction_entity` children are committed **together, per record**. Nothing
> batches across records, and nothing holds a transaction open across an LLM
> call.

```
extraction(... , retry_count) -- UNIQUE (run_id, record_id)
extraction_value(...)         -- one per (extraction, feature): composite PK
extraction_entity(...)        -- captured, never scored (mvp-spec.md §10.3)
```

`retry_count` is on the row because §15.4 renders it ("retries 11 (bounded,
counted)") and a bound nobody can see is not a bound. `extraction_entity`
keeps a plain string primary key rather than a composite `(extraction_id,
kind, ref)`: a model that repeats an entity would otherwise cost the run a
whole record over output nothing scores (P3-D7).

`UNIQUE (run_id, record_id)` **is the resume key**. Resume is "the record ids
in this run's scope with no `extraction` row", which is a query, not
bookkeeping — and the constraint means a double write raises instead of
quietly updating (Do-NOT list #2). Note the resume set can have **holes** in
the middle, not just a missing tail: a record whose retries were exhausted
leaves one, and resume must find it.

**Progress is derived, never counted.** `records_done` is
`COUNT(extraction WHERE run_id = …)` over an indexed column. A counter column
would be a second source of truth that a restart can disagree with, and being
wrong about how much work is done is the one thing this worker cannot afford.

**A parse failure is a datum, not an exception.** `parse_ok = False`,
`parse_error` set, `raw_output_text` stored verbatim, and the run
**continues** (`mvp-spec.md` §10.4). `domain/extraction.py`'s `parse_output`
never raises and never repairs: a missing key, an extra key, a non-null value
with no evidence span, an enum value outside the snapshotted codelist are each
a typed, recorded outcome. This is how Do-NOT list #6 lands on model output —
the row carrying the evidence *is* the finding, which is why this phase adds
no `FindingCode` values.

`build_output_schema(features)` builds the `mvp-spec.md` §10.3 shape for *this*
feature set with `pydantic.create_model`, and its **key order is stable**
across calls: the schema goes to the endpoint as the constrained-decoding
format, and two runs must ask the same question.

### 15.4 The run worker

The worker is the `TaskRunner` seam (SD7) with a persistent tail — one
submitted job per `run`, `ProgressReporter` for the UI, and the `run` /
`extraction` tables for everything that has to survive the process.
`GET /api/v1/tasks/{id}` (§9) is unchanged; the UI polls it with `ui.timer`
exactly as Import does. No streaming, no websocket push.

- **Models serial.** One model at a time, `RA2_RUN_CONCURRENCY` defaulting to
  1 and refused above it. The GPU is the bottleneck; two models sharing 24 GB
  is slower than two in sequence, and it is what the design draws (one
  `running`, the rest `queued`).
- **Records: up to the run's pinned `llm_parallel_calls` in flight** (**SD38**).
  `RA2_LLM_PARALLEL_CALLS` maps a model tag to a call count, and it defaults
  to `{}`, so every model runs serially. The launch pins
  `parallel_decision(...).n` on the run (SD40: the map's value when a
  matching passing gate is on record, 1 otherwise), and **Resume executes at
  the pinned value**,
  never at the current map. One code path serves every N: N worker
  coroutines in one `TaskGroup` pull from the pending list, so N=1 is one
  worker, not a separate serial branch (Do-NOT #12). Each worker resolves in
  its own closed transaction, calls, and commits one record in its own
  transaction. §15.3's boundary is unchanged: nothing batches across
  records, and no transaction spans a call. Dispatch order is scope order,
  commit order is completion order, and resume keys on holes, so nothing
  depends on the two agreeing. The endpoint-error budget counts
  *consecutive* failures in completion order. When it trips, workers stop
  taking records and in-flight calls finish, so at most N−1 more calls are
  spent, and they're counted. An unexpected exception cancels the siblings
  and fails the run with the first error. Cancel cancels every in-flight
  call. Committed rows survive both.
- **An entry in the map is a measurement, not a preference, and the launch
  checks it** (**SD40**). Batched decoding is not guaranteed bit-identical to
  batch size 1, and `OLLAMA_NUM_PARALLEL` is server-wide, so raising it can
  move *other* models' serial answers too. An entry applies only while the
  newest `model_qualification` for the tag **and its current digest** holds a
  passing gate at that N or above, **on the running Ollama version**;
  otherwise the run is pinned to 1. RA2 still can't read Ollama's slot count,
  so an entry above the server's slots queues rather than fails, and the
  queue wait runs against `RA2_LLM_TIMEOUT_S`. The run-start log line prints
  `parallel=N` beside `timeout=`, and the gate's reason when it overrode the
  map (`parallel=1 (map=4, gate=digest)`): ids, tags and a code only.
- **Retries bounded and counted.** `RA2_LLM_MAX_RETRIES`, the count carried
  back on the `Extraction` and rendered in the progress card's metrics line —
  never a retry-until-quiet loop (`mvp-spec.md` §10.4).
- **Provenance written at run start**, not at completion: model + digest,
  template version + fingerprint, temperature, seed, **reasoning effort**,
  **parallel calls**, config id, corpus id + version, host platform, GPU name, endpoint. A run
  that dies mid-corpus is still a reproducible run (`mvp-spec.md` §19.8).
- **Interrupted, then resumed explicitly.** A process death leaves the run
  `interrupted` and the view offers **Resume**. N6 asks for restart-*safe* and
  resumable, which this is; it does not ask for automatic, and a run that
  restarts itself whenever the app starts burns GPU hours on work the user may
  have abandoned.
- **Restart is detected once, at process start.** Nothing updates a `run` row
  on the way down, so a process that dies mid-run leaves it saying `running`.
  `RunService.reclaim_orphans` — the one caller of
  `RunRepository.list_running`, called from `main.py`'s lifespan and nowhere
  else — relabels those `interrupted` before anything in the new process can
  submit work. **A read never writes a status.** The unconditional relabel is
  only sound at that one moment: at startup this process is executing nothing,
  so a `running` row is stale with no claim to check and no window to get
  wrong. Asking on the read paths instead — which is what this replaced —
  meant asking at moments when the answer could be wrong, and the Evaluation
  view asks twice a tick for the length of a run.

### 15.5 The LLM adapter — the one place `openai` exists

`infra/ollama_client.py` implements both `domain/llm.py` protocols:
`LLMClient` (`extract(text, schema, model, *, temperature, seed,
reasoning_effort=None)` takes the resolved prompt as `text`, and the timeout
belongs to construction, not to a call; the signature was unchanged from
phase 1 until `SD36` made the reasoning effort a per-evaluation input, which
a constructed value cannot express) and the new `ModelCatalog`
(`models() -> tuple[ModelInfo, ...]`, `reachable() -> EndpointStatus`, and
since SD40 `version() -> str | None` from `/api/version` and
`loaded() -> tuple[str, ...]` from `/api/ps`, both `None`/empty when the
endpoint does not answer, never an exception), plus
`EndpointProber` (below). It is
the only module in the repo permitted to import `openai`, which
`import-linter`'s `one-llm-seam` contract enforces against every other
package.

**The `openai` SDK alone; PydanticAI is dropped** (**SD14**). `mvp-spec.md` §3
names both. The one call this product makes is "one prompt, one JSON Schema,
one response" — PydanticAI's value is an agent loop nobody here wants, and it
would be a *second* place a provider client gets constructed, which is what
Do-NOT list #1 exists to prevent. Pydantic model → JSON Schema → the
endpoint's constrained decoding, through `/v1`, as §3 already describes.

**The loopback guard.** The client refuses **at construction** a `base_url`
whose host is not loopback (`127.0.0.1`, `::1`, `localhost`), raising
`LlmEndpointError` naming N1. The **rule itself lives in `domain/llm.py`**, not
here: `classify_endpoint(base_url) -> ProbeCode | None` is the one statement of
"may RA2 dial this?", and it has three faces — `require_loopback` raises on it
(this guard), `is_loopback_url` answers yes/no for the settings dialog's Save
gate, and `EndpointProber` returns it as a result. The dialog needs the same
rule and `ra2/ui/` may not import `ra2/infra/`, so a rule that stayed in the
adapter would have become two copies of the one thing standing between this
codebase and N1. It is pure `urllib.parse`, so `domain` is a legal home; the
adapter re-exports it. `mvp-spec.md` §19.10 permits egress to "the
configured LLM endpoint" and N1 forbids data leaving the host; a configurable
URL with no guard satisfies neither, and a typo or a copied `.env` would ship
accident narratives to a LAN address. **There is deliberately no opt-out
setting** — an opt-out is how "no data leaves the host" becomes "no data
leaves the host by default". This is also why phase 1's "no egress at all"
posture ends here rather than lapsing: the rule becomes *loopback only*, and
the guard plus `import-linter` are what make it a gate.

**The guard is half the rule; the transport is the other half** (**SD27**).
`classify_endpoint` reasons about the **URL**. Which socket that URL is
actually dialled over is decided later, by the transport, out of the process
environment — and the `openai` SDK, left to build its own client, builds it
with `trust_env=True`. On a workstation where `HTTP_PROXY` or `ALL_PROXY` is
set machine-wide and `NO_PROXY` does not cover localhost, which is the default
on most managed estates, a request for `http://127.0.0.1:11434/v1` is handed to
the proxy host: guard satisfied, narrative attached. So `_build_client` builds
the transport itself:

- **`trust_env=False`** — no `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `.netrc`
  or `SSLKEYLOGFILE` is read. The environment cannot move the socket.
- **`follow_redirects=False`** — a `307`/`308` preserves the method and the
  body, so whatever answers on `127.0.0.1:11434` could otherwise hand the
  narrative to an off-host URL the guard never saw.

Both apply to all three classes, because all three build through
`_build_client`. The `http_client` seam is **checked, not trusted**: an
injected client with either flag on is refused at construction, so the stub the
tests drive cannot be looser than the client production builds — a seam that
could be is a guarantee true only of the path nobody runs.

The adapter tests assert this on the transport `_transport_for_url` actually
selects for the loopback URL rather than on the flag, with a positive control
that fails if the check stops discriminating: every assertion there is a
negative one, and a negative assertion that cannot fail is worse than none.

**Unreachable is a state, not an error.** `reachable()` returns a status; the
service hands the view an empty model list and a reason; the view renders it
beside the endpoint line and **disables Launch**. Never a toast, never a 502 —
a 502 would force exactly the toast the design rejects.

**The endpoint prober — diagnosing a URL nobody has committed to yet**
(**P3-D19**). `reachable()` answers about the *configured* endpoint, in one
bit, which is all the Models card renders. It cannot help someone setting
Ollama up, for two reasons: the value they care about is the one still in the
settings dialog's field, and "unreachable" cannot tell "Ollama is not running"
from "that is the wrong port". So there is a third protocol beside the other
two:

```python
# domain/llm.py
class EndpointProber(Protocol):
    async def probe(self, base_url: str, *, timeout_s: int) -> ProbeResult: ...
```

`OllamaEndpointProber` implements it. Three properties make it more than a
second `reachable()`:

- **It takes the URL per call**, so it holds no `base_url` and needs no
  settings — which is also what lets `create_app()` default it with nothing.
- **It never raises.** Every outcome is a `ProbeResult` carrying a `ProbeCode`
  — `OK`, `REFUSED_NOT_LOOPBACK`, `MALFORMED_URL`, `CONNECTION_REFUSED`,
  `TIMEOUT`, `HTTP_ERROR`, `BAD_PAYLOAD` — plus the provider's or the OS's
  verbatim `detail`. The code is the stable identifier and the wording lives in
  one rendering table in `ui/`, exactly as `FindingCode` works. A refusal that
  raised would force the toast the design rejects.
- **`classify_endpoint` runs before any client is built**, so an off-host URL
  produces no packet at all. That is the N1 property, and it is asserted
  directly: the adapter tests hand the prober a transport that fails the test
  if anything reaches it.

The bound is `min(timeout_s, PROBE_TIMEOUT_S)`. `RA2_LLM_TIMEOUT_S` is 600 —
right for a model that is thinking, wrong for a dialog waiting to learn whether
anything is listening, which would otherwise hang for ten minutes on a host
that accepts the connection and goes quiet. The bound actually used is reported
back, so the timeout sentence can name it. (It was 120 when this paragraph was
written, and the gap between the two numbers is the whole argument: a
`PROBE_TIMEOUT_S` of 5 is what keeps the dialog answerable however far the
generation bound moves.)

`POST /api/v1/models/test` is the same call through the other adapter, and is
**always 200** for the same reason `GET /models` is: a probe that found nothing
has succeeded at its job.

### 15.6 The GPU probe

The design disables a model that "exceeds 24 GB VRAM". Ollama reports tag,
digest and size; it does not report the host's VRAM. So VRAM is probed
(**SD15**), behind a protocol like every other host fact:

```python
# infra/gpu.py
class GpuProbe(Protocol):
    def describe(self) -> GpuInfo | None: ...   # None = no NVIDIA GPU, or NVML absent

def probe_for(*, name: str | None, vram_gb: float | None) -> GpuProbe: ...
                                            # the override wins, else NVML
```

`probe_for` keeps "which probe" a single rule in a single place. Putting the
conditional in `create_app()` instead would have put logic in a composition
root that is meant to be wiring only (§3).

`NvmlGpuProbe` reads GPU name and total VRAM through the **NVML library
bindings** (`nvidia-ml-py` — a `ctypes` load of `libnvidia-ml`, present
wherever the GPU is, on Windows and Linux alike). **Never `nvidia-smi`, never
any subprocess**: N3 forbids shell-outs, and a library load is not one. Read
this rule as written — the next reader reaching for `nvidia-smi` because "it
is only a probe" is the failure mode this paragraph exists to prevent.

**The catalogue is endpoint state; only the selection is evaluation state.**
The Models card shows both, which is why `EvaluationView` carries both — but
the card must render the catalogue whether or not an evaluation exists, and
`EvaluationService.catalogue()` is what serves it before one does. Reaching
the endpoint's facts *through* the evaluation's is how the card came to be
empty on every fresh install, in exactly the state where "is Ollama set up?"
is the question being asked (**P3-D21**). Selection is withheld until the
draft is saved — the design's own step order — so the ticks render `disabled`
rather than merely inert.

`StaticGpuProbe` serves both the `RA2_GPU_VRAM_GB` / `RA2_GPU_NAME` overrides
and the tests. `None` is not an error: no NVIDIA GPU means no `fits_vram`
judgement, every model selectable, and the design's disabled row simply does
not occur. Declared capability beats guessed capability, and "unknown" beats
either when it is the truth.

### 15.7 Package layout additions

```
domain/
  prompt.py                 slot catalogue, validate/resolve/render, fingerprint, estimate_tokens (pure)
  extraction.py             mvp-spec.md §10.3 shapes, build_output_schema, parse_output,
                            RunStatus, EvaluationSize (pure)
  llm.py                    + ModelInfo, EndpointStatus, ModelCatalog (LLMClient unchanged)
  qualification.py          SD40: Qualification, gate_verdict, parallel_decision (pure)
persistence/
  repositories/
    prompt_repo.py          prompt_template + citation counts
    evaluation_repo.py      evaluation, the launch transaction, evaluation_feature
    run_repo.py             run, status transitions, progress counts
    extraction_repo.py      the per-record write, and the resume query
    qualification_repo.py   SD40: add, latest_for; no update, no delete
services/
  prompt_service.py         versions, copy-on-write save, activate, delete, resolve (PromptResolver)
  evaluation_service.py     drafts, model list + VRAM fit, connection status, launch
  run_service.py            launch_runs, the worker body, resume
  qualification_service.py  SD40: summarise (in the throwaway app), record
  protocols.py              + PromptResolver — run_service never imports prompt_service
api/
  v1/prompt_templates.py  v1/evaluations.py  v1/runs.py  v1/models.py
infra/
  ollama_client.py          the only module that imports openai (§15.5)
  gpu.py                    GpuProbe, NvmlGpuProbe, StaticGpuProbe, probe_for (§15.6)
                            the only module that imports pynvml
ui/
  views/prompts_view.py     master/detail per design/prompt-evaluation/README.md §1
  views/evaluation_view.py  setup/progress split per the same README §2
  components/               progress_card, ollama_settings, prompt_preview
scripts/
  qualify_model.py          SD40: `just qualify-model`; wiring only, like seed_dev.py
```

`prompt.py` and `extraction.py` sit in `domain/` like `census.py` and
`codelist_coverage.py` — pure, no SQLAlchemy, no network — even though their
callers are the ones holding sessions and sockets.

### 15.8 What this section deliberately does not decide

- **Scoring, Results and Mismatches** (`mvp-spec.md` F7–F11). Runs produce
  `extraction*` rows and stop there; nothing reads them yet. The `score` and
  `mismatch` tables stay unbuilt.
- **Run concurrency above 1, and streaming progress.** Both are config lines
  or additive endpoints on top of what §15.4 fixes, and neither is worth
  designing before one real corpus has been run end to end. *Records* in
  flight within one run are decided (§15.4, SD38); *models* in parallel stay
  refused for the VRAM reason above.
- **Batched feature prompts** — `mvp-spec.md` §10.1's named fallback if
  adherence proves poor. The batch composition would be part of the template
  version, so this section's copy-on-write already accommodates it.
- **Template variants with names.** §15.1 assumes one lineage. A fork needs a
  name and a parent pointer; it does not need them yet.
- **The Ollama settings dialog beyond its three controls** (endpoint, timeout,
  refresh) — the design does not draw it, and three controls are the three
  settings the adapter takes. VRAM reporting inside that dialog is out until
  §15.6's probe has met a machine that is not the target one.

---

## 16. Scoring and Results (F7–F10)

**Contract frozen at M27, bodies from Wave 1 on.** Prompts and Evaluation
shipped in phase 3; runs now produce `extraction*` rows and **nothing reads
them**. This section is what phase 4 builds against, and unlike §14 and §15 it
was written *after* its plan rather than before it — `plan-phase-4.md` §0 says
so, names the ten things this section had to settle, and is subordinate to
whatever it says here.

§15.8 parked scoring with the words "the `score` and `mismatch` tables stay
unbuilt". **They are built here**, and this section supersedes that bullet.

It spends its length on one boundary and one refusal. The boundary is the
scoring transaction (§16.1), for the same reason §15.3 spent its length there:
a pass over 5 000 records × 13 features × 3 models is long enough to be
interrupted, and what it committed when it was has to be exactly what it can
resume from. The refusal is **numbers this product will not print** — a
hallucination rate (`mvp-spec.md` `D1`), a presence F1 (`D2`), a discovery rate
compared between models (§11.3), a rank where the intervals overlap (§11.5).
Every one of them is computable and every one of them would be a lie, so the
architecture has to make printing them harder than not printing them. That is
why suppression is a property of a read model rather than a CSS class, and why
Ranking is a function rather than a table.

Mismatch **review** (F11) is not here; its rows are (§16.6). §16.9 is this
section's own deferral list.

### 16.1 Scoring is a pass, not a query

A score is not computed when someone looks at it. It is computed once, by a
job, into rows — and everything the three Results tabs render is a read over
those rows.

The alternative was considered and rejected on its arithmetic: a 5 000-record
corpus with 13 labelled features across 3 models is ~195 000 classifications,
each one an EAV lookup plus a normalisation, **per page load**, before sorting
and paging. But the decisive argument is not cost. `mismatch` rows must exist
as rows regardless, because an analyst tags them (`mvp-spec.md` §12) — so the
classification pass gets written either way, and computing scores on read would
mean writing it *twice*, once to persist mismatches and once to aggregate
metrics, with two chances to disagree about what a `hit` is.

```
score(run_id, feature_id, language, metric, value, n, ci_low, ci_high)
     -- composite PK (run_id, feature_id, language, metric)
mismatch(id, run_id, record_id, feature_id, record_value, extracted_value,
         evidence_span, analyst_tag, tagged_at, note)
     -- UNIQUE (run_id, record_id, feature_id)
```

> **One `(run, feature)`, one commit.** Every `score` row for that pair — the
> all-languages row and each per-language row, every metric — plus every
> `mismatch` row that feature produced, are written **together**. Nothing
> batches across features, and no transaction is held open across the EAV read
> that feeds the next one.

This is §15.3's rule one level up, and it buys the same property. **The
features of a run that have no `score` rows are the work left**, which is a
query, not bookkeeping. An interrupted pass leaves whole features done and
whole features absent — never a feature half-scored, which is the state that
would make a resumed pass produce numbers derived from two different reads of
the corpus.

**`language` is `NOT NULL`, with `'*'` for the all-languages row** (**SD16**).
`mvp-spec.md` §5 writes `language|NULL`, which cannot carry a composite primary
key: SQL treats two NULLs as distinct in a unique constraint, so the schema
that looks like it prevents duplicate rows would silently permit them, and
"rewrite this feature's rows" would leave orphans behind every time a pass
re-ran. A sentinel makes the key real. `ALL_LANGUAGES` lives in
`domain/scoring.py` beside the metric names.

**Scoring is chained, not triggered** (**SD17**). The run worker's terminal
`done` submits the scoring job through the `ScoreSubmitter` seam
(`services/protocols.py`), which `create_app` satisfies with `ScoringService`;
there is no Score button, and the design draws none. **This paragraph
described the arrangement for four phases before anything implemented it** —
`RunService` took no scorer and `ScoringService.submit` had no caller, so a
finished run sat at "Not scored yet" forever. `test_scoring_is_chained.py` is
what makes the sentence a claim rather than an intention, and it drives the
chain through `create_app` — because every layer was green on its own the
whole time it was broken. Every input a score depends on — the corpus, the frozen config, the
codelist snapshot, the matching rules, the extractions — is immutable from the
launch commit onward, so there is no moment between a run finishing and its
scores existing in which a user could make a meaningful decision. A `failed` or
`interrupted` run is **never** scored: a partial corpus produces real-looking
numbers over an unstated denominator, which is precisely the failure §11.4's
suppression rule exists to prevent at the other end of the scale.

**No scoring-status column.** Whether a run is scored is
`COUNT(DISTINCT feature_id)` over its `score` rows against the evaluation's
labelled-feature count. §15.3 refused a `records_done` counter because a
restart can desynchronise it; the same reasoning holds here, and the same
consolation applies — the count that answers "how far did it get" is the same
one that answers "where does it resume", so the two cannot disagree.

### 16.2 Ground truth — and the rule that decides who is in the denominator

Scoring compares two values per record: what the model said
(`extraction_value.value_normalised`) and what the record already held. The
second one is the work, because for half the feature kinds it does not exist
anywhere until something computes it.

| Feature | Ground truth is |
|---|---|
| native (`source_column`) | `unfall_row.value_raw` for that record and column |
| derived (`derivation_json`) | `domain/derivation.py`'s evaluation of the closed 7-type catalogue over the record's objekt/person cells |

`plan-phase-2.md` Q1 deferred the derivation evaluator on the explicit promise
that "scoring needs to build one anyway"; phase 3 did not need it, and this is
the phase that pays. It lives in `domain/` and takes a **`RecordProjection`** —
a plain mapping of one record's cells, no session, no repository, no query — so
the catalogue is testable without a database and the EAV read stays in
`persistence/` where §1.1 requires it.

**The EAV read is one pass, not one per record** (`SD2`'s lesson in a new
place). `GroundTruthProvider.values_for(session, corpus_id, feature)` returns
the whole corpus's values for one feature; the caller iterates a mapping. A
5 000-record corpus × 13 features is 13 queries, not 65 000, and the repository
test asserts a **bounded statement count** rather than a wall-clock number,
which would be flaky.

> **`mvp-spec.md` §8.6 is the most consequential sentence in this section.**
> *"A record whose column is empty is excluded from that feature's denominator
> **entirely**, for Goal 1 and Goal 2 alike."*

It has three plausible wrong readings, and **all three produce numbers**, which
is why it is stated as code rather than as prose:

| Wrong reading | What it does | Why it is wrong |
|---|---|---|
| an empty cell is a `missing` | inflates the denominator, depresses recall | the model was never asked a question with an answer; the *data* has no label, and §8.6 says the data cannot distinguish "empty" from "not applicable" |
| an empty cell scores `0` | same, silently | a zero is a measurement |
| an empty cell is suppressed | renders an "insufficient data" cell | suppression is about *too few* labelled cases, not about *no* case — a feature with 4 000 empty cells and 30 populated ones has n = 30 and is perfectly scoreable |

`classify(record_value, model_value)` therefore returns `Outcome | None`, and
`None` means **not a labelled case**. A caller cannot accidentally count it,
because there is nothing to count. A feature whose source column is empty
across the whole corpus produces **no `score` rows at all** — not rows of
zeros, and not a suppressed cell.

The distinction that catches people is the derived one: `count_objects` over a
record with **zero objects** is `0`, and that `0` is a real labelled value in
the denominator. "No objects" is a fact the data states; "no value" is a fact
the data is missing. `domain/derivation.py` returns a value in the first case
and the caller never sees the second, because a derived feature has no source
column to be empty.

**Matching is `mvp-spec.md` §8.4's table and nothing else** (`D6`).
`domain/matching.py` normalises both sides per value type — enum compares
codes, integer strips separators, decimal rounds to the rule's precision, date
goes `YYYYMMDD` → ISO, time goes `HH:MM` → minutes with the rule's optional
tolerance, boolean maps truthily, free text goes NFKC → casefold → collapse
whitespace → strip edge punctuation — and then compares for equality. **No
fuzzy anything, and no accent folding**: §8.4 flags accent folding as "worth
evaluating" precisely because it interacts with §4.4's encoding damage, and
evaluating it means having the numbers this phase is built to produce. Turning
it on first would decide the question by assuming the answer.

### 16.3 One row shape, sixteen metric names

Spec §5 gives `score` a `metric` column and a `value`, which reads as a table
of rates. It is also, unchanged, a table of **counts** (**SD18**):

| Group | `ScoreMetric` values |
|---|---|
| Goal 1 rates | `precision` · `recall` · `f1` |
| Goal 1 counts | `hit` · `wrong` · `missing` |
| Goal 2 | `presence_rate` · `flag_inconsistency_rate` |
| Goal 2 cross-tab | `hit_present` · `hit_absent` · `wrong_present` · `wrong_absent` · `missing_present` · `missing_absent` |
| Goal 3 | `discovery_rate` · `evidence_span_count` |

The design's breakdown row renders Precision · Recall · F1 · Hit · Wrong ·
Missing, and its cross-tab renders nine cells. Both are reads over one table.

**The counts are stored, not back-derived.** They are recoverable in principle
— `hit = recall × n`, and the rest follows — but through three rounded floats,
in code nobody will look at again, producing integers that are off by one in
exactly the cases (small n) where the number matters most. Storing them costs
three rows per `(run, feature, language)` and removes a class of error that has
no symptom.

**`ScoreMetric` is a closed `StrEnum`.** A metric this table does not name
cannot be written, and a tab asking for one that does not exist is a lint
error in Wave 4 rather than a `KeyError` in front of an analyst. It lives in
`domain/scoring.py` beside `Outcome` and `ALL_LANGUAGES`, the way `RunStatus`
lives in `domain/extraction.py` (`P3-D2`).

Goal 3 takes no part in any of this beyond its own two metrics. §11.3 is
explicit: exploratory attributes are excluded from the ranking and from every
Goal 1/2 aggregate, and **discovery rates are never compared between models**,
because a freely hallucinating model wins that comparison. The read model that
serves the Goal 3 card carries no model-to-model shape at all — the comparison
is not merely undrawn, it is unrepresentable.

### 16.4 The statistics, and the one number that must never be printed

`domain/stats.py` is pure, and is the smallest, most-tested module in the
project by intent:

```python
def wilson(successes: int, n: int) -> Interval          # 95%, z = 1.959963985
def suppressed(n: int, floor: int) -> bool              # n < floor
def mark_ties(cells: Sequence[Cell]) -> tuple[TieMark, ...]
def macro(scores: Sequence[FeatureScore]) -> float      # non-suppressed only
```

**Wilson is written out, not imported** (`mvp-spec.md` `D4` chose it for
correct behaviour at small n and near 0 or 1, where the normal approximation
fails). `scipy` would be the largest dependency in the project, added for one
closed form and one constant, so `pyproject.toml` gains nothing this phase and
Wave 0's exit criteria assert it stayed byte-unchanged.

**A tie is a tie.** `mark_ties` marks a model `best` only if **no** rival's
interval overlaps its own; the moment one does, every overlapping model —
the leader included — is `tied`. `mvp-spec.md` §11.5: "overlapping confidence
intervals are rendered as a tie, **not** as an order". Ranks repeat (`1, 1, 3`)
and never enumerate (`1, 2, 3`). The marker vocabulary is three **shapes** —
filled, outlined, empty — not three colours, so the distinction survives a
greyscale print and a colour-blind reader, and `theme.py`'s standing rule
("colour carries only state and severity, no decorative hue") is not bent for
one view family.

**Suppression is a read-time rule over stored `n`, never a write-time filter**
(**SD19**). Every cell is computed and stored; `ResultsService` replaces it
with a typed insufficient-data shape when `n < evaluation.min_cell_count`. Two
things follow, and both are the point:

- Lowering or raising the floor **never requires a re-score**, which is what
  makes `mvp-spec.md` §11.4's "configurable per evaluation" cheap enough to
  honour as a column rather than quietly demote to a global constant.
- A suppressed cell is carried as a *shape carrying its `n`*, not as `None` and
  not as a number. It cannot be formatted into a string by accident, it cannot
  be sorted as zero, and `tests` assert at every layer — domain, service, JSON,
  DOM — that no number reaches a suppressed cell.

The last one has a specific failure it is guarding against: **a suppressed row
that sorts as 0 silently ranks the least-evidenced feature as the worst-
performing one.** Suppressed rows sort **last**, in both directions.

A suppressed feature is also excluded from `macro` and from tie counting
entirely. `macro` over a set where *every* feature is suppressed **raises**
rather than returning `0.0` — there is no mean of nothing, and a `0.0` there
would print as a model that scored zero.

### 16.5 Ranking is a derivation, and that is enforced structurally

`design/results/README.md` states the invariant and this section keeps it
verbatim: *"Every number on this tab is derived from tab 1's scored rows —
nothing here is independent… if the two disagree, Ranking is wrong by
construction."*

So Ranking is not a table, not a cache and not a materialised view. It is
`domain/ranking.py` — `rank_models(...)` and `separating_features(...)` — a
pure function over the same `score` rows `ResultsService` reads. **A function
cannot disagree with its own input.**

This is enforced by a contract that already exists rather than by a review
comment: `domain/` may import stdlib and `pydantic` and nothing else in `ra2/`
(§1.1, `import-linter`), so `ranking.py` **cannot** reach a session, a
repository or a second source of numbers even if an agent wanted it to.
`.importlinter` needs no new contract this phase, which is the sign the layer
rule was drawn in the right place.

Three columns on that tab are **reported, never scored** — median latency,
prompt tokens and VRAM, per §3d's own rule 4: "the tie-breaker you apply, not
one the tool applies". **Time per record and parallel calls join them**
(**SD38**). A model whose run had `llm_parallel_calls > 1` answers each call
more slowly and gets through the corpus faster, so its median latency is
marked `×N` and stops being comparable down the column. Time per record,
`mean latency ÷ parallel calls`, stays comparable, and it is what the analyst
actually pays for. **The presence figure joins them** (**SD20**). The
design renders it as `0.907` in a ranking table, where it reads as a quality
score; `mvp-spec.md` §11.2 is unambiguous that presence has no independent gold
label, and §11.3's reasoning applies to it directly — a model that flags
everything present maximises presence rate. So the column is a macro presence
**rate**, headed as one, sitting with latency and VRAM, and taking no part in
rank computation. `mvp-spec.md` §11.5 is corrected to say so. A test asserts
the negative: change the presence rate and the ranking must not move.

The reciprocal rule comes from §11.2 and is stronger than a layout note:
**Goal 2 numbers are never published without the Goal 1 numbers beside them**,
because a weak extractor manufactures false "missing" flags. That is expressed
as a *shape* — `PresenceRow` carries its `goal1` block and there is no
constructor that omits it — so a later refactor cannot drop the column and
leave the page still rendering.

### 16.6 Re-scoring, and the first mutable row in this codebase

Everything in this pipeline has been append-only. `Do-NOT #2` covers
`extraction`, `record` and `corpus`; prompt templates are copy-on-write;
code tables are superseded, never edited. **`mismatch.analyst_tag` breaks the
pattern by design** — tagging a mismatch is the whole of F11 — and it is the
one place phase 4 has to be careful (**SD21**).

`rescore_run(run_id)` exists because the *scorer's own code* can change; no
other input can. It is the explicit path, and per feature it:

1. **replaces** that feature's `score` rows — they are a pure function of
   immutable inputs, so a re-score either reproduces them byte-for-byte or the
   code changed, and in both cases replacement is correct;
2. **upserts** its `mismatch` rows on `(run_id, record_id, feature_id)`,
   rewriting the derived columns and **preserving `analyst_tag`, `tagged_at`
   and `note`**.

The obvious implementation — `DELETE` then `INSERT` — destroys review work that
phase 5 exists to collect, and it destroys it silently, at the moment a
developer is most confident (they just fixed the scorer). The `UNIQUE`
constraint above is what makes the upsert expressible; the preservation test is
what makes it true.

A re-score of the same code over the same run is **byte-identical**. The inputs
are immutable, so anything else is a bug, and that is asserted rather than
assumed.

### 16.7 The Results read models

One route, three tabs, one evaluation. `/results?evaluation=<id>`, with the
standard empty card listing launched evaluations when the parameter is absent —
the design draws a run descriptor and no picker, and phase 3's Evaluation view
left its runs-table link pointing at a deliberate placeholder route, which is
the link that lands here.

No ORM object crosses the service boundary (§1.1, unchanged since phase 1).
Every tab carries the same `RunDescriptorView` — corpus label, record count,
model count, `cfg` chip — including, per `mvp-spec.md` §13, **the dev marker on
every dev-sized result**: on these boards `DEV · smoke test, not a result`
*replaces* the "Evaluation run" pill rather than sitting beside it, so there is
no state in which a dev number renders unmarked.

| Tab | Read models |
|---|---|
| 1 · Extraction | `ExtractionTabView` — `FeatureScoreRow` × `ModelCellView` (sortable, paged, suppressed last), `BreakdownView`, `ByLanguageView`, `ExploratoryRow` |
| 2 · Presence | `PresenceTabView` — `PresenceRow` (each carrying its `goal1` block, §16.5), `CrossTabView`, `FlagInconsistencyRow`, `PerRecordRow` |
| 3 · Ranking | `RankingTabView` — `RankingRow`, `SeparatingRow`; **built by calling `domain/ranking.py` over the same rows tab 1 read** |

Three states are not "empty" and must not share a rendering:
**not scored yet** (no `score` rows), **scoring…** (a `TaskRunner` task in
flight, polled through `GET /api/v1/tasks/{id}` exactly as import and runs
are), and **nothing scoreable** (zero labelled features, or every feature below
the floor). The third says *which*, because "no results" and "not enough data
for results" are different facts about the run.

The API mirrors that: an unscored run is **200 with `scored: false`**, never a
404 — the same reasoning §15.5 used for an unreachable endpoint. A status code
forces a toast, and a toast is the wrong shape for a state the page should
simply be in.

Tab 2's per-record list is **the deliverable**, not a rate: *"this report does
not say what the weather was"*, one row per record, exportable. The CSV is
`export_service.py`'s existing conventions unchanged — UTF-8 **with BOM** for
Excel on Windows (N3), `;`-delimited, a header comment naming corpus and
version, and the **currently filtered, currently sorted** rows only (§7).

### 16.8 Package layout additions

```
domain/
  stats.py          wilson, suppressed, mark_ties, macro (pure)
  ranking.py        rank_models, separating_features — the tab-3 derivation (pure)
  matching.py       mvp-spec.md §8.4's normalise + match table (pure)
  scoring.py        Outcome, ScoreMetric, ALL_LANGUAGES, classify,
                    aggregate_goal1/2/3 (pure)
  derivation.py     RecordProjection, evaluate — the closed 7-type catalogue,
                    phase 2's deferred evaluator (pure)
persistence/
  repositories/
    score_repo.py         write a feature's rows in one commit; read a run's
    mismatch_repo.py      bulk write; the tag-preserving upsert (§16.6)
    ground_truth_repo.py  GroundTruthProvider — one pass per feature (§16.2)
services/
  scoring_service.py    the pass, the chain off run completion, rescore, status
  results_service.py    tabs 1 and 2; suppression applied here (§16.4)
  ranking_service.py    tab 3, through domain/ranking.py
  protocols.py          + GroundTruthProvider, Scorer
api/
  v1/results.py  v1/presence.py  v1/ranking.py
ui/
  views/results/        __init__ (route, shell, tab strip), extraction_tab,
                        presence_tab, ranking_tab
  components/           stat_cells (tie marker, value-over-interval, the
                        insufficient chip), contingency_table
```

**`ui/views/results/` is a package, not a module** (**SD22**) — the first view
in the repo that is. Three tabs of one screen get built by three agents in one
wave, and three files is what makes that parallel; a single `results_view.py`
would serialise the wave for no architectural gain. The route, the shell and
the tab strip are the package's `__init__.py`.

The five new `domain/` modules sit beside `census.py`, `codelist_coverage.py`,
`prompt.py` and `extraction.py` — pure, no SQLAlchemy, no session, no
filesystem — even though their callers are the ones holding sessions. That is
not tidiness: it is what makes §16.5's invariant a structural fact rather than
a promise.

### 16.9 What this section deliberately does not decide

- **Mismatch review** (`mvp-spec.md` F11, §12) — the view, the tagging
  affordance, the per-feature tally. The rows exist from this phase (§16.6) and
  `analyst_tag` stays `NULL` throughout it. Phase 5 is a view over data that is
  already there, which is the whole reason the rows are written now.
  **Superseded by §17**, which is the other half of §16.6's contract.
- **Presence precision / recall / F1** (`D2`, §16). They need a human-labelled
  presence subset of ~50 records × features, and the labelling tool for it is
  not designed. Tab 2's scope banner states the deferral to the analyst
  verbatim rather than leaving the absence to be inferred.
- **Automatic hallucination triage** (`D1`). Distinguishing a hallucination
  from a misread means adjudicating whether an evidence span supports a value.
  `hallucinated` stays a review tag, reported as a tally, and the breakdown row
  says so on the screen.
- **The Goal 3 review workflow.** The design's "12 / 15 reviewed" counter
  implies exactly the tagging machinery F11 defers; building a second one for
  exploratory attributes would duplicate it. Discovery rate, value distribution
  and the evidence-span list ship; the counter waits.
- **Cross-evaluation and cross-corpus comparison.** §11.5 confines ranking to
  within one evaluation, and §16 says every cross-corpus number, if ever shown,
  carries its corpus label. The fingerprints that make such a view possible are
  all stored; the view is not this phase's.
- **Entity scoring.** `extraction_entity` stays captured and never scored
  (§10.3), unchanged since phase 3. Set matching over object and person grain
  is a scoring view over rows that already exist.
- **Fuzzy or LLM-judge free-text matching, and accent folding** (`D6`, §8.4).
  Each needs a threshold that can be defended, and defending one wants the real
  numbers this phase is the first to produce.

---

## 17. Mismatch review (F11)

The shortest architecture section in this document, and it says so on purpose.
There is **no new table, no new column, no new outbound call, no new job and
no new statistic**. Phase 4 wrote the rows and never read them; §16.6 wrote
half of a contract and this section writes the other half.

What is genuinely new is one thing: **this is the first time a human writes to
the database.** Everything before it was append-only or job-owned. Every
decision below follows from that sentence.

### 17.1 Who owns which columns of `mismatch`

`mismatch` has two halves and two owners, and neither writes the other's.

| Half | Columns | Owner | Written by |
|---|---|---|---|
| Derived | `record_value`, `extracted_value`, `evidence_span` | the scorer | `MismatchRepository.upsert_feature`, on every score and re-score |
| Review | `analyst_tag`, `tagged_at`, `note` | review | `MismatchRepository.set_tag`, one row at a time, from a click |

`run_id`, `record_id` and `feature_id` are the key and are written once, at
insert.

The scorer's half of this contract is already built and already tested
(`SD21`, §16.6): the upsert rewrites the derived three and leaves the review
three alone. This section adds the mirror obligation — **`set_tag` writes the
review three and nothing else**, and its exit criterion is byte-equality on
the derived columns, asserted on the row rather than on a count.

Two owners over one row is the arrangement that makes a re-score survivable.
It is also the arrangement that makes a careless `UPDATE mismatch SET …`
destroy work in either direction, which is why neither side is expressed as a
general-purpose write: `MismatchWrite` cannot name a review column, and
`set_tag` takes a tag and a note and no derived value at all. The type is the
guard; the test is the proof.

### 17.2 Tagging is an `UPDATE`, and Do-NOT #2 is intact

Do-NOT #2 reads: *never mutate an `extraction`, a `record` or a `corpus` row.*
`mismatch` is none of those, and the omission is deliberate rather than
accidental — `SD21` named it "the first mutable row in this codebase" one
phase before anything mutated it.

The invariant Do-NOT #2 protects is **reproducibility of the pipeline's
inputs and outputs**: a corpus, a record and an extraction are evidence, and
evidence that can be edited is not evidence. A tag is not evidence. It is a
human's opinion *about* evidence, it is the only thing in the database no
re-run can reproduce, and §12's whole purpose is that a person writes it.

So there is no contradiction to resolve, but there is a boundary to state:
**the mutability of `mismatch` is confined to three columns and one method.**
`MismatchRepository.set_tag` is the only query anywhere that writes
`analyst_tag`, `tagged_at` or `note`, and `mismatch_service` is its only
caller; `upsert_feature` is the only thing that writes the derived three, and
`scoring_service` is its only caller. The rest of the codebase's relationship
with this table is reading it and — once, deliberately, under two guards —
deleting whole rows with the run they belong to (§18.2's G2, which counts the
tagged ones and announces them precisely because they are the half no re-run
can reproduce).

### 17.3 What a tag is worth: nothing, by construction

`mvp-spec.md` §12 is categorical — *"The tag never feeds back into a metric.
Nothing is rescored."* This is the second invariant in this codebase that is
easy to state, convenient to violate and **invisible once violated** (the
first was the loopback guard, §15.5): a number that moved because of a tag is
not visibly wrong, it is just wrong.

It is therefore expressed as an **absent edge**, not as a rule anybody has to
remember:

```
run_worker ──> scoring_service ──> score, mismatch (derived columns)
                    │
                    └── domain/scoring.py, domain/stats.py

mismatch_service ──> mismatch (review columns)
                 └─> domain/mismatch.py  (tally — counting, and nothing else)

                 ╳  no edge, in either direction
```

Three things hold it:

1. **`mismatch_service.py` imports neither `scoring_service` nor
   `ranking_service`**, and `tests/test_p5_contract.py` asserts that on the
   module's AST rather than on a linter's transitive view. `import-linter`
   cannot express "this service may not import that service" — both are one
   layer — so the assertion is a test, the same way the `openai` one-seam
   gate is an AST test on top of a contract (§15.5).
2. **The `MismatchTally` protocol returns counts and nothing else**
   (`services/protocols.py`). There is deliberately no method on it that
   could influence a score; the absence is the contract. A later Results
   surface that wants review counts calls `tally` and gets integers.
3. **`domain/mismatch.py` computes only a tally.** It has no access to
   `ScoreRow`, `Outcome` or `MetricCell`, and `domain` cannot reach a session
   to find one.

The converse edge is equally absent: a re-score reads no tag and branches on
no tag. It preserves them and is otherwise blind to them.

### 17.4 The tally, computed on read

The tally is **per feature, computed on read from stored tags, and never
stored** — the third time this phase family makes the same call (scoring
status §16.1, ranking §16.5, now this). A stored tally is a second source of
truth that both a re-score and a tag can desynchronise, and the query is one
`GROUP BY` over an indexed column.

`ix_mismatch_run_id_feature_id` already exists, so `tally_for(run_id)` is
**one grouped query per run, never one per feature**:

```sql
SELECT feature_id, analyst_tag, COUNT(*) FROM mismatch
 WHERE run_id = ? GROUP BY feature_id, analyst_tag
```

The pure half lives in `domain/mismatch.py`:

```python
def tally(counts: Mapping[str | None, int]) -> ReviewTally: ...
```

It takes **stored tag values mapped to row counts** — exactly the shape that
`GROUP BY` produces — rather than a list of rows, so the grouped query stays
grouped all the way into the domain. `None` and `""` are untagged; anything
else is a tag.

`ReviewTally` carries `total`, `reviewed`, `untagged`, `counts` (one entry
for every `MismatchTag`, always all three, so no renderer can `KeyError`) and
`other`. Two identities hold and are asserted:

    sum(counts.values()) + other == reviewed
    reviewed + untagged == total

**An empty input yields a zero tally rather than raising** — unlike
`domain/stats.py`'s `macro`, because there is nothing dishonest about
"0 reviewed" and a great deal dishonest about a macro F1 over no features.

The tally the screen shows is scoped to **the filter the list is showing**, so
the strip under the table and the table itself can never disagree. That is
`MismatchService`'s exit criterion, not a convention.

### 17.5 The vocabulary: a closed enum over an open column

`MismatchTag` is a closed `StrEnum` in `domain/mismatch.py` over
`mismatch.analyst_tag`, which stays `String(32)`. **Both halves are
load-bearing and the asymmetry is deliberate.**

- The **enum** is what makes the list, the tally, the CSV and the API agree on
  three identifiers, and what makes a typo a lint error instead of a row
  nobody can find. `FindingCode` and `ProbeCode` are the precedent: the value
  is the stable identifier and is what tests assert on.
- The **string column** keeps `models.py`'s promise that *"a fourth tag must be
  a value, not a migration"*.
- The **`other` bucket** is what stops the asymmetry becoming a crash. A
  stored value `MismatchTag` does not name is **never dropped and never
  raises**: it renders in the row as itself, it counts under `other` in the
  tally, and it travels verbatim in the CSV. A tally that silently omitted
  such rows would report "of 40 reviewed" over 38, which is the one failure
  mode this whole section exists to avoid.

`OTHER_TAG` is a plain constant and **not a `MismatchTag` member**, so no
code path can write it. It is a bucket, not a vocabulary word.

The wire is closed even though the column is not: `POST /tag` accepts only the
three and answers **422** to anything else. Nothing in the MVP can therefore
create an `other` row; the bucket exists for a value a later phase, a
migration or a hand-edited database introduces, and `R7` records honestly
that it is exercised by a fixture writing a raw string rather than by real
data.

The filter vocabulary is closed too (`TagState`: `any` · `untagged` ·
`tagged`, or one named `MismatchTag`). A fourth stored tag is visible,
counted and exported; it is simply not offered as a filter option until
somebody adds it. That is the honest boundary of the asymmetry, stated here
so it is not discovered as a bug.

### 17.6 Scope: one run at a time, and what that refuses

`/mismatches?evaluation=<id>`, with optional `&run=` and `&feature=`, and the
standard empty card listing launched evaluations when the parameter is absent
— the resolution `ui/views/results/__init__.py` already implements (§16.7).

**The list shows exactly one run.** `mvp-spec.md` §12 names `run` as part of
the row, and there are two ways to honour that: a Model column, or a scope.
The scope is right, for a reason that is not about column widths:

> A list mixing two models' mismatches for the same record and feature **is**
> cross-model agreement, which §16.9 defers by name along with clustering and
> sampling. Refusing the mixed list is not a limitation of this view; it is
> the deferral, arriving where it would otherwise have sneaked in.

So the Run filter switches between the evaluation's runs and has **no "all
runs" option**. Absent `&run=`, the view picks the evaluation's first run, the
same resolution `ResultsService.presence_records` already uses for its own
one-model-at-a-time tab. `MismatchTally.tally` is keyed by `RunId` for the
same reason.

### 17.7 Staleness: nothing guards a review, and the view says so

A re-score deletes the rows that no longer mismatch, tags included (§16.6),
because a tag describing a mismatch that no longer exists is review work
attached to nothing. **Nothing protects an analyst mid-review**, and nothing
should: this is a single-user, single-mode app with no login (§13). A lock is
machinery for a concurrency that does not exist, and optimistic versioning
would be a second source of truth about a row whose derived half a job owns.

What the view owes the analyst is a **visible reason for a list that
changed**, and it shows the closest honest thing it has: the run's
`finished_at`, beside the run label, **in the Mismatches toolbar**.

Not inside `chrome.run_descriptor`: that helper renders a `RunDescriptorView`,
which carries no timestamp, and it belongs to the Results package. This view
reuses it for corpus, record count and the dev pill, and puts the run label
and `finished_at` in its own toolbar — one line of markup here instead of one
amendment to a frozen file there.

**RA2 does not record when a run was scored, and this section does not add
it.** `run.finished_at` is when the pass ran the first time — scoring chains
off the run's terminal `done` (`SD17`), so for a run scored once they are the
same moment. A **re-score** is the one event that moves the list without
moving that timestamp, and it goes undated. Adding a `scored_at` column to
record it is refused here: §16.1 F5 declined a scoring column so that "how far
did it get" has exactly one answer, and `tests/test_p4_contract.py` asserts
the absence by name. The gap is named rather than papered over (`SD25`), and
`R5`'s next step if it proves insufficient is **a count of tags lost, not a
lock**.

### 17.8 The read model surface

No ORM object crosses the service boundary (§1.1, unchanged since phase 1),
and `ui/` holds no business logic: every count, every narrowed tag and every
"is this row reviewed" arrives already decided.

| Read model | Carries |
|---|---|
| `MismatchRowView` | one row of the table: record, feature, the three derived values, the stored tag and its narrowing, `tagged_at`, `note`, and the **`anonymised` flag** — required wherever record text is shown (`mvp-spec.md` §13), and this cell shows an evidence span |
| `MismatchFeatureView` | one option of the Feature filter: the feature, and how many mismatches it has in this run |
| `ReviewTallyView` | one feature's `ReviewTally`, for the strip under the table |
| `MismatchFilters` | what the toolbar asked for — **one shape**, so the list, the tally and the CSV cannot end up filtered differently |
| `MismatchListView` | the descriptor, the run label and its `finished_at` (§17.7), the two filter option lists, the filters, `Page[MismatchRowView]` and the tallies |

`MismatchRowView.tag` and `.is_other` are **properties over the stored
string**, not a second field. One stored value, one place it is narrowed, and
Q5's asymmetry is a property of the type rather than a rule four renderers
apply.

**One query behind the list** — filter by run, feature and tag state; sort by
one of four keys; page — and its statement count is bounded and asserted on a
1 000-row run (the `R4` lesson, one table over).

The four sort keys are **feature, record, tag and reviewed**
(`MISMATCH_SORT_KEYS`). There is no fifth, and in particular nothing sorts by
"how wrong": there is no such number, and inventing one is §16.9's
clustering / agreement / sampling deferral arriving as a helpful-looking
feature. The closed tuple is what makes that a test rather than a review
comment.

The export reuses `export_service.py`'s conventions unchanged — UTF-8 with a
BOM (N3), `;`-delimited, a comment line naming the evaluation, the run and the
filter, and the **currently filtered, currently sorted** rows only (§7).
`mismatches_csv` **takes the rows** (`P4-D3`): re-fetching inside the exporter
is how a CSV comes to disagree with the screen it was exported from. It
carries the tag and the note, because an export whose point is review has to
carry the review.

### 17.9 Package layout additions

```
domain/
  mismatch.py       MismatchTag, OTHER_TAG, TagState, TagFilter,
                    MISMATCH_SORT_KEYS, ReviewTally, tally (pure)
persistence/
  repositories/
    mismatch_repo.py  + list_for, set_tag, tally_for.
                      upsert_feature is UNCHANGED — the scorer's half
services/
  mismatch_service.py  list, tag, clear_tag, tally, export rows.
                       Imports no scoring module (§17.3)
  protocols.py         + MismatchTally
api/
  v1/mismatches.py     list, tag, clear, tally, CSV
ui/
  views/mismatches_view.py   a module, not a package — one screen, one agent
                             (the SD22 reasoning, read the other way)
```

**No new domain module beyond `mismatch.py`, no new component, no new
dependency and no new lint contract.** `pyproject.toml` and `.importlinter`
are byte-unchanged, and `tests/test_p5_contract.py` asserts it — the same gate
phase 4 introduced, for the same reason: a decision with no gate behind it is
a preference.

`ui/views/mismatches_view.py` is a **module**, deliberately, where Results is
a package (`SD22`). The reasoning there was that three tabs built by three
agents in one wave need three files; here one screen is built by one agent in
a wave of one, and a package would be ceremony.

### 17.10 What this section deliberately does not decide

- **Mismatch clustering, cross-model agreement and unbiased sampling**
  (`mvp-spec.md` §16, §16.9). Unchanged and refused twice over: §17.6's
  one-run scope is where the second of the three would otherwise have entered.
- **Automatic hallucination triage** (`D1`). `hallucinated` stays a review tag
  reported as a tally, never a metric. That is exactly what this section
  builds and exactly where it stops.
- **Bulk tagging.** One row at a time. "Tag all filtered" is one line of UI
  over the same service call, and it is also how forty rows get the wrong tag
  in one click. It waits until somebody has reviewed a real list and asked.
- **Tag history and adjudication.** §12 asks for a tally, not an audit trail,
  and *"the structured record is fully authoritative in every case. No
  adjudication step exists anywhere in the pipeline."* A tag can be changed
  and cleared; nothing is versioned; nothing reconciles.
- **A review queue, assignment or per-analyst attribution.** Single-user,
  single-mode, no login (§13). There is nobody to assign to and nobody to
  attribute to.
- **Notes as a designed affordance.** The column exists, the service writes
  it, the CSV carries it, and the view offers a single-line input — because
  nothing in §12 describes more than that.
- **Cross-evaluation review.** The same boundary §16.9 draws for results.

---

## 18. Reset and discard

The pipeline is append-only everywhere (§12.2, and `mvp-spec.md` N5). This
section is where it acquires **one destructive verb**, and the whole of it
exists to bound that verb so the invariant survives contact with a user who
has three inconclusive evaluations cluttering a screen.

The two needs that share the word "reset" are opposite and stay apart:

- **The developer** wants the data directory gone and a working state back —
  `just reset`, `just reset-seed` (`plan-reset-and-discard.md` §5). That is a
  script over `Settings`, not an app feature, and nothing in `ra2/` knows it
  exists.
- **The analyst** wants the *regenerable* half of an evaluation gone and the
  curated half kept. Everything upstream of a run — the delivery, the frozen
  corpus and its census, the codelist import, the feature config, the prompt
  versions — is hand-made and stays; `run`, `extraction*`, `score` and
  `mismatch` are derived from immutable inputs and go.

### 18.1 Whole objects only

**Discard removes a whole `run`, a whole `evaluation`, or a whole `delivery`,
and nothing else.** There is no partial delete anywhere: not "this run's
scores", not "the extractions for feature X", not "every run older than a
week".

Do-NOT #2 forbids *mutating* an `extraction`, a `record` or a `corpus`.
Deleting a whole run is not mutation — the run and everything derived from it
leave together, and what remains still reproduces. Deleting *some* of a run's
rows is mutation by another name: it leaves a run whose numbers no longer
follow from its inputs, which is precisely the state the append-only rule
exists to make impossible.

The cascade does the work, and it is declared in the schema rather than
implemented in a service: `extraction`, `extraction_value`,
`extraction_entity`, `score` and `mismatch` are `ondelete="CASCADE"` from
`run`; `run` and `evaluation_feature` are `CASCADE` from `evaluation`;
`delivery_file` is `CASCADE` from `delivery`. Everything an evaluation
*cites* — `corpus`, `feature_config`, `prompt_template` — is `RESTRICT` and
stays that way. `foreign_keys=ON` is a connect-time PRAGMA (§4.4); the backend
test that discards a run and counts the rows that went with it is what keeps
that honest.

### 18.2 Two guards, and no third one added quietly

**G1 — nothing active is discarded.** A `queued` or `running` run is refused
(`RunActiveError`, 409), and so is an evaluation holding one. `done`, `failed`
and `interrupted` are all discardable: an interrupted run is exactly the
debris this verb exists to clear, and refusing it would leave the only way to
remove one being the SQLite file.

**G2 — human work is never destroyed silently.** `mismatch.analyst_tag` is the
one human-authored column in the pipeline. SD21 already spends a paragraph
arguing that a re-score must not lose it; a discard earns the identical
argument, and gets a weaker remedy on purpose: the count of tagged mismatches
is refused with (`TaggedWorkPresentError`, 409, carrying the count) **unless
the caller passes `force`**. Warn and allow, not block — an analyst who cannot
clean up works around the app, and the workaround is editing the database by
hand.

A **cited delivery** is refused (`DeliveryCitedError`, 409). This one is not a
policy so much as a hole in the schema: `corpus.delivery_id` is
`ondelete="SET NULL"` (SD4 — a corpus outlives its delivery), so the database
would quietly null the reference rather than refuse. The guard is in the
service because that is the only place it can be.

Those are the three. **A fourth guard is not added without this section
changing first**, because each one is a rule a user has to learn from a
message.

### 18.3 Discard state is never persisted

No `deleted_at`, no soft-delete flag, no tombstone table, and no record of
what was discarded or by whom. A discarded run is *gone*; the row shape this
codebase keeps is the one that reproduces a result, and a row that records the
absence of a result reproduces nothing.

This is also why the slice needs **no migration**: no new table, no new
column, no new Alembic head.

**The trace lives outside the database, in a file the analyst chose to keep**
(**SD23**). The confirm dialog offers Export beside Discard, writing the run's
`score` and `mismatch` rows — `analyst_tag` included — through
`export_service`'s existing conventions (§7: UTF-8 with BOM, `;`-delimited, a
header comment naming what this is a list of). An audit table would have cost
a migration and produced rows nobody reads; a CSV on disk is the artefact
someone actually opens.

**The server never tracks whether an export happened.** "Has this run been
exported" would be a mutable per-run flag recording a UI event — the kind of
state §16's F5 reasoning rejects for scoring progress and this section rejects
again. The dialog offers; the analyst decides; the API discards what it is
asked to discard.

### 18.4 Package layout additions

```
services/
  lifecycle_service.py   the previews, the three discards, the two guards,
                         and the run's export rows
persistence/
  repositories/          + delete/count methods on run_repo, evaluation_repo
                         and delivery_repo — no new repository
api/
  v1/discard.py          the shared translation: the two response shapes and
                         the 409 builder. Not a router
  v1/runs.py             + DELETE, + discard-preview, + scores.csv,
                           + mismatches.csv
  v1/evaluations.py      + DELETE, + discard-preview
  v1/deliveries.py       + DELETE, + discard-preview
ui/
  components/discard_dialog.py   one dialog, two states (§18.5)
scripts/
  reset_data.py          the developer's wipe, over Settings
  seed_dev.py            wipe, then drive the services to a working state
```

`LifecycleService` is a service and not a repository method reached from three
routers because the guards are policy, not persistence: G1 reads a status, G2
counts rows in a different table, and the delivery guard asks a question about
corpora. One place answers all three, and both adapters get the same answer.

### 18.5 One dialog, two states

The affordance is a row action on a list that already exists — the Evaluation
view's runs table, in the status cell that already carries `log` and
`Resume`. The **evaluation**-scoped one sits one level up, in that same card's
header control slot rather than in the view's toolbar (`SD35`), so the two
scopes read off the screen with no word of explanation: the header takes the
whole list, a row takes its own row. **No new nav item and no new column**:
the nav is four groups and eight items asserted in E2E (§8.2), and the runs
table's five column widths are the design's own
(`design/prompt-evaluation/README.md` §2).

The dialog renders what will be lost, from one `DiscardPreviewView`:

- **nothing to export** — no `score` and no `mismatch` rows (a run that never
  produced any). Discard is enabled immediately.
- **something to export** — the counts, an Export beside Discard, and, when
  tagged mismatches exist, the count in the lead sentence with Discard
  carrying the `force` call. Over an evaluation holding more than one run,
  Export is **one pair of files per run** and the dialog says so before the
  press, not after N downloads have started (`SD35`).

It is one dialog with two states rather than two dialogs, for the same reason
the file report modal is one modal: a second dialog is a second place for the
copy to drift.

### 18.6 What this section deliberately does not decide

- **Snapshot and restore.** Deferred until discarding runs is shown to be
  insufficient. The design, if it is ever wanted, is a file-level `VACUUM
  INTO` plus a manifest carrying the Alembic revision, and a restore that
  refuses when that revision is not head — which is a permanent maintenance
  cost to take on only once someone asks for it.
- **An audit table.** Rejected in favour of export-before-discard (SD23).
- **Bulk or filtered discard.** One object at a time. A bulk verb over a
  destructive operation is how the wrong thing gets deleted.
- **A delivery discard affordance in the UI.** The Import view shows exactly
  one delivery and has no delivery list, so a row action has nothing to hang
  on, and a delivery table is a change to
  `design/nav-import-census/README.md`. The route exists; the analyst's route
  to the same end is `just reset`, and the delivery files are the expensive
  half this feature exists to *keep*.
- **Corpus discard.** It already exists, with its 409-when-cited guard and its
  `LOCKED · N eval` pill (§6.3, J3). Unchanged.

### 18.7 What a discard erases

§18.1 says a discard removes whole objects. This says what *removed* means,
because the two are not the same thing and the difference is the whole of the
risk.

**In the database: the bytes, not just the rows.** `secure_delete=ON` (§4.4,
`SD29`) zeroes a freed page as it is freed. Without it, a discarded run's
`mismatch.evidence_span` — verbatim narrative, mandatory by design — stays
readable in the SQLite file until an unrelated write happens to reuse that
page. Asserted through the real service against the real file in
`tests/backend/services/lifecycle/test_discard_erasure.py`, which searches the
database **and its WAL** for a span it planted, with a positive control before
the discard and a control showing the bytes survive with the pragma off.

**On the filesystem: an upload's bytes, and nothing else.** A host-path
delivery's files are the analyst's own and are never touched (§18.2); the
empty `{data_dir}/deliveries/{id}/` directory is left behind; `just reset`
removes the tree.

**Outside the machine: nothing, and the dialog says so.** Export-before-discard
(`SD23`) is the trace a discard leaves, and it is a CSV carrying `evidence_span`
into a Downloads folder that no RA2 verb reaches. `EXPORT_LEAVES_RA2` is
rendered beside the Export button for that reason and is asserted like every
other piece of load-bearing copy. What happens to that file afterwards is
`data-handling.md` §3, and it is a rule about people, not a predicate.

**What none of this reaches.** The blocks the filesystem freed, and every
earlier copy of the database. Destruction at that level is the disk, not the
application — which is why full-disk encryption is a deployment condition and
not a nice-to-have.

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

- SQLite, WAL, `foreign_keys=ON`, `busy_timeout=5000`, set as connect-time PRAGMAs
  in `session.py` — nowhere else.
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

- **Type hint**: the `Ausw`/`Feld` suffix rule first, then value-shape inspection —
  all values `YYYYMMDD` in a plausible range → `date`; all `HH:MM` → `time`;
  all integral → `integer`; decimal-parseable → `decimal`; else `text`. `Ausw`
  columns are `enum`.
- **Populated** = non-empty string (§6). Empty means *no value provided*, never
  "not applicable" (§8.6) — the Census view says so in the Reminder card.
- **Top values**: 20 stored, top 3 shown in the legend, top 4 shown as stacked-bar
  segments plus a remainder.
- **Long tail** is a stored boolean: `distinct > 20 and top_value_share < 0.01`.
  The design's "long tail · 1 461 distinct, no value over 1 %" is that rule rendered.
- **Profile buckets**: 100–80 / 80–60 / 60–40 / 40–20 / 20–0 / empty, over all tables.
- CSV export writes the **currently filtered, currently sorted** table, UTF-8 with
  BOM (Excel on Windows, N3), `;` delimiter, and a header comment line naming the
  corpus id and version.

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

### 8.2 Design fidelity

The design is implemented **faithfully**: tokens, fixed sizes and layout rules from
`design/nav-import-census/README.md` are requirements, not suggestions.

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
| `RA2_DATA_DIR` | `./var` | N7 — DB, uploads, exports all under it |
| `RA2_DB_PATH` | `{data_dir}/ra2.sqlite` | |
| `RA2_LLM_BASE_URL` | `http://localhost:11434/v1` | N2 — present from commit 1, unused in phase 1 |
| `RA2_HOST` / `RA2_PORT` | `127.0.0.1` / `8080` | bind to loopback by default |
| `RA2_MAX_UPLOAD_MB` | `512` | |
| `RA2_DEV_RECORD_MAX` / `RA2_EVAL_RECORD_MIN` | `50` / `200` | §9 |
| `RA2_MIN_CELL_COUNT` | `20` | D3, unused until scoring |

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
  Every migration is therefore executed on every backend run.
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
| `just test` | unit + backend + ui — the commit gate |
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
| SD9 | Minimum spec for the file report modal (§8.3) | The design defers it, but the Import row action opens it |
| SD10 | The API is built in phase 1, not deferred | It is how E2E seeds state, and it is the same services either way |

**Note on the design's fixture column names.** `UnfallTypAusw`, `WitterungAusw`,
`LichtverhaeltnisAusw` and `UnfallDatumFeld` do not exist in the delivery; the real
columns are `UnfTypAusw`, `Witter0Ausw`, `LichtVerhAusw`, `UnfDatumFeld`. The design's
fixtures are illustrative. **Column names are only ever read from the header.**
The design's "162 columns" does check out: 67 + 77 + 18.

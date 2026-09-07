# Execution Plan — M0 → M5 with Parallel Sub-Agents

How the first five milestones of [plan-phase-1.md](plan-phase-1.md) actually get
built: a serial contract freeze, then three waves of sub-agents working in isolated
git worktrees against frozen interfaces.

**Reading order for every agent:** `mvp-spec.md` (what) → `sw-design.md` (how) →
this file (who builds what, and what they may touch). On a conflict, `sw-design.md`
wins over this file; `mvp-spec.md` wins over both.

Scope here is **M0–M5 only**. M6 (Import view), M7 (Census view) and M8 (harness
completion) are out; the plan is shaped so they drop straight onto M5's component kit
and M4's API without rework.

---

## 1. The parallelisation model

Four ideas, in dependency order.

**1. One serial contract freeze (M0), then nothing blocks.** Everything that crosses
an agent boundary — ids, `Finding`, the SQLAlchemy models, the API schemas, the
service signatures, the injected protocols, `create_app()` — is written *once*, by
one agent, before any parallel work starts. After M0 those files are **frozen**: a
parallel agent that needs one changed files an amendment and works around it, it does
not edit it. This is what buys the parallelism; without it, five agents converge on
`models.py` and the wave is a merge exercise.

**2. Disjoint file ownership.** Every path in the tree has exactly one owner per wave
(§4). An agent that writes outside its owned paths has produced a defect, and the
integration check catches it mechanically (`git diff --name-only`).

**3. Isolated worktrees.** Each agent runs with `isolation: "worktree"` on its own
branch off the wave's base tag. No agent sees another's half-finished tree; the lead
merges, runs the gates, and tags the next base.

**4. Tests are the handshake.** An agent is done when its named tests are green in its
own worktree and the repo gates (`just lint`, `just test`) pass there. The lead
re-runs them post-merge rather than trusting the report.

### Waves

| Wave | Base | Agents | Milestones | Parallel? |
|---|---|---|---|---|
| **0** | `main` | 1 (`m0-foundation`) | M0 | no — everything depends on it |
| **1** | tag `m0-frozen` | 5 (A1–A5) | M1, M2, M5 | yes |
| **2** | tag `w1-green` | 2 (B1–B2) | M3 | yes |
| **3** | tag `w2-green` | 2 (C1–C2) | M4 | yes |

Ten agent runs, four integration points. Wave 1 is the wide one because M1, M2 and M5
share no code at all — the only thing linking domain, persistence and the UI shell is
the M0 contract each of them imports.

### Amendment protocol

An agent that finds a frozen contract wrong or insufficient:

1. writes `contracts/amendments/<branch>.md` — the file it needs changed, why, and the
   exact proposed diff (one file per branch, so amendments never conflict);
2. does **not** edit the frozen file;
3. keeps going: shim locally inside its own owned paths if it can, otherwise
   `pytest.mark.xfail(reason="amendment: <branch>")` on that one test and finish
   everything else;
4. names every amendment in its final report.

The lead applies accepted amendments to the contract at integration and rebases the
remaining branches. An amendment that changes `models.py` after Wave 1 costs a
migration, so schema amendments are the ones to catch at the M0 review gate.

---

## 2. Prerequisites — before Wave 0

These are human/lead actions. Wave 0 is blocked on P1–P3; Wave 1 on P4–P5.

| # | Action | Why | Owner |
|---|---|---|---|
| **P1** | Install `uv` and `just` on the host (`curl -LsSf https://astral.sh/uv/install.sh \| sh`; `uv tool install rust-just`) | Neither is present. Python here is 3.12; `uv` provisions the 3.14 the stack calls for | David |
| **P2** | ~~Review SD1–SD10 in `sw-design.md` §13 and sign off~~ **Signed off 2026-09-07** | R7. M0 freezes the schema, and SD1/SD2/SD4 *are* schema. Cheapest possible moment to say no | David |
| **P3** | ~~Decide the Windows CI story: create a git remote now, or accept that N3 is verified only on the first push~~ **Done 2026-09-07** — remote created at `github.com/stroumpfai/ra2`, wired as `origin` | No remote exists. The workflow file gets written either way, but "CI green on Windows" is not an M0 exit criterion without somewhere to run it | David |
| **P4** | ~~Vendor IBM Plex Sans + Mono (400/500/600, woff2) into `ra2/ui/static/fonts/`~~ **Done 2026-09-07** — 6 woff2 files + 2 OFL licenses, from `github.com/IBM/plex` | SD3/N1: the app may never fetch a font. Downloading them is a one-off network action an agent may be sandboxed out of, and it blocks A5's theme | Lead |
| **P5** | ~~`uv run playwright install chromium`~~ **Done 2026-09-07** — chromium cached in `~/.cache/ms-playwright/`, smoke-tested launch+render | A5's J4/J5 are E2E. If this can't run, A5 still delivers its `tests/ui` layer and the lead runs E2E once at integration | Lead |

If P4 slips: A5 defines the `--sans`/`--mono` tokens against a local fallback stack
and the `@font-face` block lands with the files. It does not unblock by pointing at
Google Fonts — that is an N1 violation and a failing test (J6).

---

## 3. Wave 0 — M0, the contract freeze

One agent, serial, `branch: m0-foundation`. This is the highest-leverage run in the
plan; everything after it is filling in bodies.

### 3.1 Deliverables

**Packaging and gates**
- `pyproject.toml` — uv, Python 3.14, **every dependency M0–M8 will need, pinned now**
  so no later agent has cause to touch this file: `fastapi`, `nicegui`, `uvicorn`,
  `sqlalchemy[asyncio]`, `aiosqlite`, `alembic`, `pydantic`, `pydantic-settings`,
  `lingua-language-detector`, `uuid-utils`; dev: `pytest`, `pytest-asyncio`,
  `pytest-cov`, `hypothesis`, `httpx`, `pytest-playwright`, `ruff`, `mypy`,
  `import-linter`, `pre-commit`. Ruff config with `PLW1514` on; mypy `strict` on `ra2/`;
  coverage `fail_under = 85` scoped to `ra2/domain` and `ra2/services`; all six pytest
  markers registered (`unit backend ui e2e eval realdata visual`).
- `justfile` — **all** recipes, final: `dev test e2e lint fmt migrate revision
  census-export setup-e2e eval`.
- `.importlinter` — the §1.1 layer contract, plus an independence contract between
  `api` and `ui`.
- `.pre-commit-config.yaml` — ruff, ruff-format, mypy, import-linter, and the
  `no-real-data` hook refusing anything matching the `.gitignore` real-data patterns.
- `.github/workflows/ci.yml` — layers 1–3 on `ubuntu-latest` **and** `windows-latest`;
  E2E on Linux only; Playwright traces uploaded on failure.
- `alembic.ini` + `ra2/persistence/migrations/env.py` (async, reads `RA2_DB_PATH`).

**The frozen contract** — after this commit, these files change only by amendment:

| File | Contents |
|---|---|
| `ra2/domain/ids.py` | `CorpusId DeliveryId FileId RecordId TaskId` as `NewType(str)` |
| `ra2/domain/findings.py` | `Severity`, `Finding` (frozen slots dataclass, §5), and the **complete** `FindingCode` enum — every code h01–h12 needs plus `ENCODING_DETECTED`, `HEADER_MISMATCH`, `DUP_KEY_CROSS_SET`, `ORPHAN_FK`, `COUNT_MISMATCH_OBJ`, `COUNT_MISMATCH_PERS`, `TEXT_KEY_UNMATCHED`, `UNFALL_WITHOUT_TEXT`, `ROW_RECOVERED`, `ROW_REJECTED_FIELD_COUNT`, `FILE_UNDECODABLE`, `UNKNOWN_HEADER` |
| `ra2/domain/delivery.py` | `FileKind`, `Encoding`, `Dialect`, `FileAnalysis`, `DeliveryAnalysis`, `RowOutcome` |
| `ra2/domain/census.py` | `TypeHint`, `ValueCount`, `ColumnCensus`, `CensusBucket` — **types only**, `compute_census` left as a signature |
| `ra2/domain/language.py` · `llm.py` | `LanguageGuess`; `LanguageDetector` and `LLMClient` protocols |
| `ra2/infra/filestore.py` `tasks.py` `clock.py` `idgen.py` | `FileStore`, `TaskRunner`, `TaskProgress`, `Clock`, `IdFactory` protocols |
| `ra2/persistence/models.py` | **The whole phase-1 schema** — spec §5 tables in scope plus SD1 (`delivery`, `delivery_file`), SD2 (`census_column`, `census_value`, `census_bucket`) and SD4 (`corpus.description`, `.delivery_id`, `.source_file_ids_json`, `.language_counts_json`) |
| `ra2/api/schemas.py` | Every request/response model for the four routers, complete |
| `ra2/services/*.py` | Class definitions with full constructor injection and typed method signatures, bodies `raise NotImplementedError` |
| `ra2/main.py` | `create_app()` **final** — every service and adapter as a defaulted keyword argument, NiceGUI mounted, routers included, views registered |
| `ra2/infra/config.py` | The §10 settings table, verbatim, `RA2_` prefix |
| `ra2/persistence/session.py` | Async engine + the three connect-time PRAGMAs, session factory |
| `tests/conftest.py` | Root fixtures only: `settings`, `tmp_data_dir`, `frozen_clock`, `seeded_ids`, `app_factory` |
| `CLAUDE.md` | The §12 Do-NOT list, the layer rule, the ownership rule, "read `sw-design.md` first" |
| `CONTRACTS.md` | The table above — the frozen list, so no agent has to guess |

**The census seam** (this one is easy to miss and it is what lets B1 and B2 run in
parallel): `services/corpus_service.freeze()` calls
`CensusMaterialiser.materialise(session, corpus_id, cells)`. Declare the protocol in
M0. B1 calls it, B2 implements it, neither waits.

### 3.2 Exit criteria

- `uv sync --frozen` succeeds; `just lint` green (ruff + mypy strict + import-linter);
- `just test` green on an empty-but-collecting suite;
- `alembic upgrade head` runs against **zero** migrations without error;
- `python -c "from ra2.main import create_app; create_app()"` builds an app whose
  routes include the seven nav routes and `/api/v1/*` (every handler 501, and that is
  fine);
- `CONTRACTS.md` lists every frozen file, and each frozen module has a
  `# FROZEN — see CONTRACTS.md` header line.

### 3.3 Review gate — do not skip

The lead reads `models.py`, `schemas.py` and `findings.py` **line by line** before
tagging `m0-frozen`. A wrong column name here costs one edit now and five rebases
later. This is also where P2's SD1–SD10 sign-off is cashed in.

---

## 4. File ownership matrix

One owner per path per wave. Anything not listed is the lead's.

| Path | W0 | W1 | W2 | W3 |
|---|---|---|---|---|
| `pyproject.toml` `justfile` `.importlinter` `.pre-commit-config.yaml` `.github/` | M0 | 🔒 | 🔒 | 🔒 |
| `CLAUDE.md` `CONTRACTS.md` `ra2/main.py` `ra2/infra/config.py` `tests/conftest.py` | M0 | 🔒 | 🔒 | 🔒 |
| `ra2/domain/{ids,findings,delivery,language,llm}.py` · `census.py` *(types)* | M0 | 🔒 | 🔒 | 🔒 |
| `ra2/api/schemas.py` · `ra2/persistence/models.py` | M0 | 🔒 | 🔒 | 🔒 |
| `ra2/domain/parsing/**` `validation.py` `canary.py` | M0 stub | **A1** | 🔒 | 🔒 |
| `ra2/domain/census.py` *(bodies)* `typehint.py` | M0 stub | **A2** | 🔒 | 🔒 |
| `ra2/persistence/{session,repositories,migrations}/**` | M0 stub | **A3** | 🔒 | 🔒 |
| `ra2/infra/{files,filestore,tasks,clock,idgen,lingua_detector}.py` *(impls)* | M0 stub | **A4** | 🔒 | 🔒 |
| `ra2/ui/**` | M0 stub | **A5** | 🔒 | 🔒 |
| `ra2/services/{delivery,corpus}_service.py` | M0 stub | 🔒 | **B1** | 🔒 |
| `ra2/services/{census,export}_service.py` | M0 stub | 🔒 | **B2** | 🔒 |
| `ra2/api/v1/{deliveries,corpora}.py` | M0 stub | 🔒 | 🔒 | **C1** |
| `ra2/api/v1/{census,tasks}.py` | M0 stub | 🔒 | 🔒 | **C2** |
| `tests/unit/{parsing,validation,canary}/**` · `tests/fixtures/deliveries/**` · `generate_hazards.py` | — | **A1** | | |
| `tests/unit/{census,typehint}/**` | — | **A2** | | |
| `tests/backend/persistence/**` | — | **A3** | | |
| `tests/backend/infra/**` | — | **A4** | | |
| `tests/ui/**` `tests/e2e/{conftest,test_j4_layout,test_j5_nav,test_j6_egress}.py` | — | **A5** | | |
| `tests/backend/services/{delivery,corpus}/**` · `tests/fixtures/golden/**` | — | | **B1** | |
| `tests/backend/services/{census,export}/**` `tests/fixtures/factories.py` | — | | **B2** | |
| `tests/backend/api/{deliveries,corpora}/**` | — | | | **C1** |
| `tests/backend/api/{census,tasks}/**` · `tests/api/openapi_snapshot.json` | — | | | **C2** |

🔒 = frozen for that wave; amendment only.

**Two conventions that remove the remaining conflicts:**
- **Per-layer conftest.** `tests/{unit,backend,ui,e2e}/conftest.py` is owned by the
  agent that owns that layer in that wave. Only `tests/conftest.py` is shared, and it
  is frozen at M0.
- **One migration author, ever, in phase 1.** A3 writes the single initial migration
  covering the whole M0 schema. Nobody else runs `alembic revision`. No parallel heads,
  no merge-of-migrations.

---

## 5. Wave 1 — five agents in parallel

Base tag `m0-frozen`. All five spawn at once, each `isolation: "worktree"`,
`run_in_background: true`.

### A1 — `feat/m1-parsing` · domain: parsing, recovery, validation *(L, opus)*

**Build**, test-first, in this order: `generate_hazards.py` and the twelve committed
hazard fixtures → `parsing/encoding.py` → `parsing/dialect.py` → `parsing/reader.py`
→ `parsing/recovery.py` → `parsing/headers.py` → `validation.py` → `canary.py`.

Load-bearing details: UTF-8 then Windows-1252, undecodable → the file fails and
`errors="replace"` appears nowhere in the tree (add the grep test); recovery anchors on
`^[0-9A-Fa-f]{32}<delim>` — two-column text is **repaired and counted `recovered`**,
wide structured rows are **detected, rejected, and reported with their key**, never
repaired; header match is case-insensitive and whitespace-trimmed, and it is the *only*
thing that decides `FileKind` (§12.5); canton comes from `unfall.KantonAusw`.

`headers.py` carries the three canonical column sets (67/77/18) and the two-column text
header. Take the **names only** from `data/data/samples/*` headers — never a data row,
never a committed fixture built from real values. Add a `@pytest.mark.realdata` test
asserting the canonical sets still match the samples when they are present.

**Exit:** h01–h12 each have a named test asserting the exact `FindingCode` *and* that
the offending key appears in the finding; the Hypothesis round-trip property for
key-anchored recovery passes for all N-line splits; `grep -rn 'errors="replace"' ra2/`
is empty and there is a test for that; `just lint` and `just test` green.

### A2 — `feat/m1-census` · domain: type hints and census compute *(M, sonnet)*

**Build:** `typehint.py` — the `Ausw`/`Feld` suffix rule first, then value-shape
inspection (`YYYYMMDD` in a plausible range → `date`; `HH:MM` → `time`; all integral →
`integer`; decimal-parseable → `decimal`; else `text`; `Ausw` → `enum`). Then
`census.py` bodies: populated = non-empty string, distinct count, top-20 values,
`long_tail = distinct > 20 and top_value_share < 0.01` (SD8), and the six profile
buckets 100–80 / 80–60 / 60–40 / 40–20 / 20–0 / empty.

Pure functions over in-memory cells — **no fixture files, no DB, no I/O**. That is why
this runs beside A1 without touching it.

**Exit:** an all-empty column is 0 % and leaves every denominator (h08's expectation);
the long-tail rule is tested at both sides of both thresholds; a hand-computed census
fixture matches exactly, including bucket counts; the `Ausw`-suffix rule beats
value-shape when they disagree, with a test that says so.

### A3 — `feat/m2-persistence` · migrations, session, repositories *(M, sonnet)*

**Build:** the **single** initial Alembic migration for the whole M0 schema;
`session.py` PRAGMA behaviour; `repositories/{delivery,corpus,census}_repo.py`.

**Exit:** the backend fixture runs `alembic upgrade head` against a **real temporary
file** SQLite (not `:memory:` — WAL and cross-connection behaviour must be exercised);
a test asserting `alembic check` is clean; a round-trip test per repository; FK
enforcement and `busy_timeout` asserted against the real file DB;
`grep -rn 'create_all' ra2/ tests/` is empty, with a test.

### A4 — `feat/m2-infra` · adapters behind the M0 protocols *(S, sonnet)*

**Build:** `files.py` (**all** file I/O in the app, every call with an explicit
`encoding=`, `pathlib` only, no shell-outs), `filestore.py` (`UploadedFileStore` +
`HostPathFileStore`), `tasks.py` (`AsyncioTaskRunner` with progress + `InlineTaskRunner`),
`clock.py` (`SystemClock`, `FrozenClock`), `idgen.py` (`Uuid7Factory`, `SeededFactory`),
`lingua_detector.py` (`LinguaDetector` + `StubDetector`; low confidence → `mixed`, never
forced to a winner).

**Exit:** both `FileStore` implementations pass the *same* parametrised contract test;
`InlineTaskRunner` completes without polling and `AsyncioTaskRunner` reports monotonic
progress to a terminal `ok`/`failed`; `FrozenClock` + `SeededFactory` produce byte-identical
output across two runs; no `open(` outside `infra/files.py`, with a test.

### A5 — `feat/m5-shell` · theme, shell, component kit *(L, opus)*

**Build:** `theme.py` (the oklch tokens from `design/nav-import-census/README.md` as CSS
custom properties in **one** injection, plus `.card .th .td .navitem .lbl .chip .btn .bar
.tick .sorth`, and local `@font-face` over the vendored Plex files); `shell.py` (full-width
header, 196px brand cell, the 4 groups × 7 items with per-view title and description copy
**verbatim** from the README, active state derived from the route, a visible focus ring
from one token); `components/` (card, `DataTable` driven by `list[ColumnSpec]` +
`TableState`, `table-layout: fixed`, pagination row, tick checkbox with an indeterminate
state, chip, `.bar`, distribution bar); `views/placeholder_view.py`.

Build from `ui.element`, not `ui.table`/`ui.card`, wherever Quasar's defaults fight the
design (R2 — this is the budgeted cost). No business logic: `DataTable` takes sort/page
as parameters and renders; it never computes a rate (§8.1).

**Exit:** `tests/ui` covers the 7 items in 4 groups, active state per route, and the
title/description copy per view; J5 (navigation, keyboard-reachable, visible focus) and
J4 (1024/1440/1920: the two Import cards share a `y` and differ in `x`, document
`scrollWidth <= clientWidth`, card headers equal height, pagination rows share a `y`)
green against a `DataTable` demo harness; **J6 green** — no external URL in any served
HTML or CSS; nav 196px, card header 46px, well 404px, `.bar` 78×6, dist bar 8px/230px max
asserted.

---

## 6. Wave 2 — services

Base tag `w1-green`. Two agents.

### B1 — `feat/m3-delivery-corpus` *(L, opus)*

`delivery_service`: register (both `FileStore` paths), analyse per file through
`TaskRunner` with progress, re-parse one file after an encoding/delimiter override,
select/deselect. `corpus_service`: freeze — cross-file blocking validation over the
**selected** files first, then one all-or-nothing transaction writing `corpus`, `record`
and the EAV rows, per-record language detection, the corpus-level canary, non-blocking
findings into `import_report_json`, the census via the M0 `CensusMaterialiser` seam, and
`is_dev_sized` from `RA2_DEV_RECORD_MAX`/`RA2_EVAL_RECORD_MIN`. Plus the delete guard.

Also owns the **golden import report** fixture (`FrozenClock` + `SeededFactory` make it
reproducible).

**Exit:** analyse → select → freeze end-to-end on the hazard delivery; a blocking failure
leaves **zero** `corpus` rows (asserted by count, not by absence of an exception);
re-parse after an override changes that file's row and no other; the golden report
matches byte-for-byte; deleting a corpus cited by a seeded evaluation raises the
409-carrying error.

### B2 — `feat/m3-census-export` *(M, sonnet)*

`CensusMaterialiser` (the freeze-time write into `census_column`/`census_value`/
`census_bucket`), `census_service` (query the materialised tables with filter + sort +
page **as service-call parameters**, §8.1/§8.4), `export_service` (CSV: UTF-8 **with
BOM** for Excel on Windows per N3, `;` delimiter, a header comment line naming the corpus
id and version, currently-filtered and currently-sorted rows only).

**Exit:** census numbers match A2's hand-computed fixture after a real freeze round-trip;
top-20 stored / top-4 segments / top-3 legend all come out of the stored rows with no
recomputation; the CSV is asserted **byte-wise** including the BOM and the comment line;
a filtered+sorted export differs from an unfiltered one in exactly the expected rows.

---

## 7. Wave 3 — API v1

Base tag `w2-green`. Two agents; thin routers over Wave 2's services, no ORM object
crossing the boundary.

- **C1 — `feat/m4-api-deliveries`**: `/api/v1/deliveries/*` (register, list, analyse,
  file override + re-parse, select) and `/api/v1/corpora/*` (list, create/freeze, get,
  delete). *Exit:* every endpoint tested through `httpx.ASGITransport` with no network;
  `DELETE` on a locked corpus returns **409**; a blocking freeze returns the findings and
  creates nothing.
- **C2 — `feat/m4-api-census`**: `/api/v1/census/*` (columns with filter/sort/page,
  profile buckets, CSV export) and `/api/v1/tasks/{id}` (progress). *Exit:* export
  asserted byte-wise through the API; the OpenAPI schema generated and **committed as a
  snapshot test**; task progress observable from submit to terminal state.

Splitting the API in two is optional — it is one milestone's worth of thin code — but the
router files are disjoint and `v1/router.py` is frozen from M0, so the split is free.

---

## 8. Integration protocol (the lead, between waves)

Per branch, in merge order — **A4, A2, A1, A3, A5** for Wave 1 (leaf-most first), then
B2, B1, then C2, C1:

1. `git diff --name-only <base>..<branch>` and check every path against §4. A path
   outside the agent's column is a hard stop, not a judgement call.
2. Read `contracts/amendments/<branch>.md` if it exists. Accept, reject, or defer —
   accepted schema amendments are applied to the frozen file by the lead, and every
   branch not yet merged is rebased.
3. Merge. Run `just lint && just test` **on the merged tree**, not on the branch.
4. Any `xfail(reason="amendment: …")` left behind is either resolved or becomes a named
   follow-up. It does not silently survive the wave.

After the last branch of a wave: `just e2e`, then tag (`w1-green`, `w2-green`,
`w3-green`) and spawn the next wave from the tag.

Prefer `SendMessage` to an agent that came back short — it still has its worktree and its
context — over re-spawning it cold.

---

## 9. Milestone coverage

| Milestone (plan-phase-1 §2) | Delivered by | Exit criteria met at |
|---|---|---|
| M0 Skeleton and gates | `m0-foundation` | tag `m0-frozen` |
| M1 Domain: parsing, recovery, validation | A1 + A2 | tag `w1-green` |
| M2 Persistence | A3 (+ A4 for the infra seams M2 assumes) | tag `w1-green` |
| M3 Services | B1 + B2 | tag `w2-green` |
| M4 API v1 | C1 + C2 | tag `w3-green` |
| M5 Shell, theme, component kit | A5 | tag `w1-green` |

M5 lands with Wave 1, three waves earlier than its number suggests — which is the point
of the second-agent note in plan-phase-1 §2, taken further.

---

## 10. Risks specific to running this in parallel

| # | Risk | Mitigation |
|---|---|---|
| X1 | **A wrong M0 contract multiplies by five.** | The §3.3 line-by-line review gate before tagging. It is cheaper than any rebase it prevents. |
| X2 | **Agents report green that isn't.** | The lead re-runs gates on the *merged* tree (§8.3). Never merge on the strength of a report. |
| X3 | **Alembic parallel heads.** | One migration author for all of phase 1 (A3). Structurally impossible rather than carefully avoided. |
| X4 | `tests/conftest.py` becomes a five-way conflict. | Per-layer conftests; the root one is frozen at M0. |
| X5 | **A5 can't verify E2E** if Chromium isn't installed (P5). | A5's `tests/ui` layer is the real gate; J4/J5/J6 are written regardless and the lead runs them once at integration. |
| X6 | **Windows is never exercised** (P3, R6). | The workflow is written at M0 and runs on the first push. Until then, N3 rests on lint rules (`PLW1514`, `pathlib`, no shell-outs) — which is weaker, and worth saying out loud. |
| X7 | **Fixtures drift from the real delivery** (R4). | A1's `@pytest.mark.realdata` header assertion is the tripwire. Real files still arrive as a hardening pass. |
| X8 | Two agents independently invent the same helper. | Accepted. Duplication inside owned paths is cheaper than a shared-utility module five agents write to; the lead folds duplicates at integration if they are genuinely identical. |

---

## 11. Decisions this plan makes

Deviations from `plan-phase-1.md`, all deliberate, all reversible.

| # | Decision | Why |
|---|---|---|
| **E1** | **`persistence/models.py` moves from M2 into M0.** M2 keeps migrations, session behaviour and repositories. | The schema is the widest contract in the codebase — A3, B1, B2, C1 and C2 all read it. Freezing it at M0 is what makes Waves 1–3 parallel at all. It also gives R7's SD-review a single, concrete gate. |
| **E2** | **`api/schemas.py` and the service signatures are complete at M0**, with `NotImplementedError` bodies. | Same reason, and it lets `create_app()` be final at M0 so no parallel agent ever edits the composition root. |
| **E3** | **`CLAUDE.md` moves from M8 into M0.** | Sub-agents read it. A Do-NOT list that arrives after the code is written is a review checklist, not an invariant. |
| **E4** | **The full dependency set is pinned at M0**, including M6–M8's. | `pyproject.toml` is the one file every agent would otherwise have a reason to touch. |
| **E5** | M1 is split across two agents (parsing/validation, census/type-hints); M3 across two (delivery+corpus, census+export). | Disjoint files, disjoint tests, no shared state — the split is free, and it halves the two longest waves. |
| **E6** | The `CensusMaterialiser` protocol is declared at M0 even though nothing implements it until Wave 2. | It is the seam that lets B1 and B2 run at the same time instead of B2 waiting on B1's freeze. |

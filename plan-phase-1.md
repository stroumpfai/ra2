# Phase 1 Plan — Shell, Import, Census

Delivers the first slice of RA2: the application shell with navigation, the Import
view, and the Census view — on a foundation and a test harness the rest of
`mvp-spec.md` is built on without rework.

**Contracts for implementing agents:** `mvp-spec.md` (what) and **`sw-design.md`
(how)**. Both are binding. A change to either is a commit that edits the document
first.

---

## 1. Scope

### In

| # | Deliverable |
|---|---|
| P1 | Project skeleton: uv, FastAPI + NiceGUI in one process, SQLite + Alembic, `just`, CI green |
| P2 | Import pipeline: encoding/dialect detection, RFC4180 parsing, key-anchored recovery, delivery validation, `Finding` reporting (§4.2, §4.3) |
| P3 | Corpus freeze: immutable corpus, EAV rows, per-record language detection, cp1252 canary, import report (§4.4, §4.5, §5) |
| P4 | Census computation and materialisation (§6) |
| P5 | `/api/v1` over deliveries, corpora, census, tasks |
| P6 | App shell — header, 7-item nav in 4 groups, theme tokens, component kit |
| P7 | Import view, to the design |
| P8 | Census view, to the design |
| P9 | The full test harness: unit, backend, frontend, E2E/Playwright, fixtures, gates, CI |

### Out of phase 1

Codelists · feature config · evaluations · runs · extraction · scoring · mismatches ·
Docker · the eval suite. Their nav entries exist and route to a placeholder; the
`LLMClient` protocol and `RA2_LLM_BASE_URL` exist with no callers, so the §3
invariant is in place from the first commit.

### Deliberately deferred inside phase 1

- Census "use as feature" — rendered, disabled, no target view yet.
- Census "in config" tint — column exists, always `false` until feature config lands.
- The corpus `LOCKED` state — implemented and tested against a seeded row, since
  evaluations do not exist yet.

---

## 2. Milestones

Each milestone's exit criterion is **named tests green**, not "code written".
M5 depends only on the theme and component kit, so **a second agent can build
M5→M6→M7 in parallel with M1→M4** against the API contract fixed in M0.

### M0 — Skeleton and gates
`pyproject.toml` (uv, Python 3.14), `ra2/main.py` with `create_app()`, NiceGUI mounted
on FastAPI, `infra/config.py`, `persistence/session.py` with the WAL pragmas, the
first Alembic migration, the `justfile`, `.importlinter`, `.pre-commit-config.yaml`,
GitHub Actions (Linux + Windows), the `tests/` tree with every marker registered, and
the API request/response schemas as empty-but-typed contracts.

*Exit:* `just test` green on an empty suite · `just lint` green · `alembic upgrade
head` creates the DB · the import-linter contract passes · CI green on both platforms.

### M1 — Domain: parsing, recovery, validation
`domain/parsing/*`, `domain/validation.py`, `domain/findings.py`, `domain/canary.py`,
`domain/typehint.py`, `domain/language.py`. Pure, no I/O. Written **test-first**
against the hazard fixtures.

*Exit:* `tests/fixtures/deliveries/generate_hazards.py` produces h01–h12 · each
hazard has a test asserting its exact `FindingCode` and key · the Hypothesis
round-trip property for key-anchored recovery passes · `errors="replace"` appears
nowhere.

### M2 — Persistence
`persistence/models.py` (spec §5 plus the §4 additions of `sw-design.md`),
migrations, repositories.

*Exit:* backend fixture runs `alembic upgrade head` · `alembic check` clean · a
round-trip test per repository · the FK/PRAGMA behaviour asserted on a real file DB.

### M3 — Services
`delivery_service` (register, analyse, re-parse, select), `corpus_service` (freeze,
list, delete-guard), `census_service`, `export_service`. `TaskRunner`, `Clock`,
`IdFactory`, `FileStore` (upload + host path), `LinguaDetector`.

*Exit:* analyse → select → freeze → census passes end-to-end on the hazard delivery ·
a blocking failure leaves **zero** corpus rows · the golden import report matches ·
re-parse after an encoding override changes only that file · census numbers match a
hand-computed fixture.

### M4 — API v1
Deliveries, corpora, census, tasks. Thin routers; no ORM object crosses the boundary.

*Exit:* every endpoint tested through `httpx.ASGITransport` · 409 on deleting a
locked corpus · CSV export asserted byte-wise · OpenAPI schema generated and
committed as a snapshot test.

### M5 — Shell, theme, component kit
`theme.py` (tokens → CSS custom properties, vendored IBM Plex), `shell.py` (header,
brand block, 4 nav groups, 7 items, active state), `components/` (card, DataTable
with `ColumnSpec`, pagination row, tick checkbox, chip, bar, distribution bar),
`placeholder_view`.

*Exit:* frontend tests for nav rendering, active state, per-view title/description
copy · J5 (navigation) and J4 (layout invariants) green · no external URL in any
served asset.

### M6 — Import view
Two side-by-side file cards with their four height-matched zones, corpora table,
create-corpus button with a live record count, the file report modal (§8.3 of
`sw-design.md`).

*Exit:* the frontend tests in `sw-design.md` §11.3 green · J1 and J2 green ·
deselecting a file updates both counts · sort state independent per table.

### M7 — Census view
Filter toolbar (three chips + caption + Export CSV), census table with the populated
bar and the distribution bar, the two summary cards.

*Exit:* default sort Populated ▼ · each chip refilters and resets to page 1 ·
long-tail rendering matches the SD8 rule · CSV export reflects the current filter and
sort · J1's census half green.

### M8 — Harness completion and handover
Playwright wired into CI with traces on failure, axe smoke, coverage gates, the
`no-real-data` pre-commit hook, `CLAUDE.md` with the §12 Do-NOT list, and ADRs for
the load-bearing choices (SD1, SD2, SD10, and the immutability rule).

*Exit:* every gate in `sw-design.md` §11.7 enforced in CI, not just documented.

---

## 3. Test setup — what gets built, concretely

| Layer | Tooling | Runs | Gate |
|---|---|---|---|
| **Unit** | pytest, Hypothesis | `tests/unit` — pure domain, milliseconds | every commit |
| **Backend** | pytest-asyncio, temp file SQLite, `alembic upgrade head`, httpx `ASGITransport` | `tests/backend` — services, repositories, API | every commit |
| **Frontend** | NiceGUI `User` fixture, in-process, headless | `tests/ui` — rendering, interaction, derived counts | every commit |
| **E2E / journey** | pytest-playwright, Chromium, real server on a random port, temp data dir, seeded through `/api/v1` | `tests/e2e` — J1–J6 | every PR |
| **Eval** | `@pytest.mark.eval`, real Ollama | `tests/eval` — phase 3 | nightly |

Fixtures are **synthetic and byte-crafted** (`generate_hazards.py`) because real data
is gitignored and must never reach a test. The twelve hazards, the journeys J1–J6,
the golden-report test and the gate table are specified in `sw-design.md` §11 — that
section is the binding version; this table is the summary.

`just` recipes: `dev` · `test` · `e2e` · `lint` · `fmt` · `migrate` · `revision` ·
`census-export` · `setup-e2e` (installs Chromium) · `eval` (phase 3).

---

## 4. Phase 1 acceptance

Mapped to `mvp-spec.md` §19 where it applies.

1. A delivery of N cantonal structured sets plus one shared text file imports into
   one corpus, with a report naming **every** recovered row, rejected row, count
   mismatch, orphan key, detected encoding and the cp1252 canary count. *(§19.1)*
2. A `UnfallUid` duplicated across two cantonal sets **blocks** the import and leaves
   no corpus behind.
3. An undecodable file fails; no `U+FFFD` is ever written.
4. Canton, language and table kind are demonstrably derived from data — renaming
   every input file changes nothing.
5. The census exports a per-column population table for all three structured tables.
   *(§19.2)*
6. The shell, Import and Census views match the design at 1024, 1440 and 1920 px,
   with the two Import cards never wrapping.
7. A dev-sized corpus is visibly marked wherever it appears. *(§19.9)*
8. No network egress occurs at all — phase 1 has no LLM endpoint to talk to.
   *(§19.10)*
9. All five gates in `sw-design.md` §11.7 pass in CI on Linux and Windows.

---

## 5. Risks and flags

| # | Flag |
|---|---|
| R1 | **The design bundle is the fixture, not the data.** Its column names (`WitterungAusw`, `UnfallTypAusw`) do not exist in the delivery. Names are read from the header, always. |
| R2 | **Faithful fidelity in NiceGUI means fighting Quasar.** Budget M5 accordingly; it is paid once and every later view reuses it. |
| R3 | **The file report modal is undesigned.** `sw-design.md` §8.3 specifies a minimum. If a design arrives, it supersedes that section. |
| R4 | **Real delivery files are still outstanding (B4).** Import hardening and census run against synthetic hazards until they arrive; expect one hardening pass afterwards. |
| R5 | **Air-gap status is open (B3).** Both intake paths are built, so the answer does not block phase 1 — but it decides which one the runbook documents. |
| R6 | **Windows CI is not optional.** N3 and N4 fail late and quietly otherwise; running it from M0 is far cheaper than retrofitting. |
| R7 | Ten extensions to the spec are introduced in `sw-design.md` §13 (SD1–SD10). They are additive and reversible, but they are **decisions**, and they want a review before M2 freezes the schema. |

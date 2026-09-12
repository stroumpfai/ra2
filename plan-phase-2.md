# Phase 2 Plan — Codelists and Features

Delivers the two remaining configuration views named in `mvp-spec.md` §1 (F3, F4)
and drawn in `design/code-feature/README.md`: **Codelists** (import
`codes-2018.json`, map corpus columns to it, show coverage) and **Features**
(assemble and freeze a feature set an evaluation will later cite). Evaluations,
runs, extraction, scoring and mismatches (F5–F11) remain out of scope — this
phase ends where a frozen feature set exists and nothing yet reads it.

**Contracts for implementing agents, in authority order:** `mvp-spec.md` (what) →
`sw-design.md` (how, including its new §14) → `design/code-feature/README.md`
(pixel/behaviour fidelity for the two screens) → this file (who builds what, and
what they may touch). On a conflict, `sw-design.md` wins over this file;
`mvp-spec.md` wins over both — same rule as `plan-m0-m5.md` §0, restated because
it is the rule that makes disjoint sub-agents safe.

This single document plays the role `plan-phase-1.md` and `plan-m0-m5.md` played
together for phase 1: scope and milestones, *and* the wave-by-wave sub-agent
breakdown. Phase 1's two-document split existed because the execution plan was
written after the phase plan had already been reviewed; here there is one
review, so there is one document.

---

## 1. Clarifications

Asked before writing the rest of this plan, because each answer changes its
shape. Recorded here rather than only in chat history, so a later reader does
not have to guess why a scope line reads the way it does.

| # | Question | Answer | Consequence |
|---|---|---|---|
| Q1 | Should derived-aggregate features (`any_object_matches`, `count_objects`, …) execute against a real corpus now, showing live preview numbers as the design mock does? | **No.** Store `derivation_json` only; the view shows a placeholder for any corpus-dependent number. | No derivation evaluator in this phase. Saves a full evaluator + its own test layer that scoring (phase 3) needs to build anyway — building it twice is waste. §5's `domain/feature.py` still defines the closed catalogue's *shape* (types, parameters, operators), just not a function that runs one. |
| Q2 | Add real `/api/v1/codelists/*` and `/api/v1/features/*` endpoints, or wire the UI straight to services? | **Add the endpoints.** | One more wave (F1/F2, §9), but keeps the established pattern: no ORM object crosses the boundary, and the two new E2E journeys (J7, J8) seed state through the API exactly as J1/J2 do. |
| Q3 | The Features design shows a fingerprint on every feature, including drafts, marked "· preview" — before an Evaluation exists to compute the real one (mvp-spec §8.5 is evaluation-time). Build a shared preview function now? | **Yes.** | `domain/fingerprint.py` implements §8.5's algorithm now; Features calls it for the draft badge, and evaluation-creation code becomes its second caller in phase 3. One implementation, not two to reconcile later. |

Smaller open items — from the design doc's own "Open questions for the team"
and `sw-design.md` §14.4 — are resolved here rather than left blocking, each
reversible:

| # | Item | Resolution |
|---|---|---|
| C1 | Design open question 1: codelist JSON schema is a placeholder | **Settled** by `sw-design.md` §14.1: the schema is whatever `codes-2018.json` actually is. No further confirmation needed unless a real VUM export disagrees (B1). |
| C2 | Design open question 2: "Add feature" panel state is undrawn | The edit zone renders in a **new-feature mode**: same layout as an existing feature's edit zone, Kind defaulted to `labelled`, every field empty, "Save" replacing the implicit autosave the mock doesn't show either way. G2's judgement call at build time; not worth a design round-trip for a state this close to the drawn ones. |
| C3 | Design open question 3: does Features still need a corpus selector? | **Yes, but not on the toolbar next to the feature set.** `feature_config` (mvp-spec §5) has no `corpus_id` — a config is corpus-independent and reusable across evaluations. The edit zone's "validate against" numbers (distinct count, coverage %) need *some* corpus's census, so the corpus choice lives as a smaller control inside the edit zone (e.g. next to "Source — native column"), scoped to validation display, not to the saved feature. |
| C4 | Design open question 5: should the frozen board's primary action read "Clone to new evaluation" or match the draft's "Create a feature set"? | **"Clone to new evaluation."** It does a different thing (copies a frozen config into a new draft) and Evaluations do not exist yet in any form the user can reach — a button promising one should not share the draft's label. |
| C5 | `sw-design.md` §14.4: Features' "used by" cross-links on Codelists rows | Stays inert, as §14.4 already says: `column_mapping` carries no FK to `feature`. Screen 1's "used by Right of way" link renders only once a feature actually exists referencing that column — computed from `feature.source_column`, not stored. |
| C6 | `sw-design.md` §14.4: a second code source (real VUM export) | Out of scope, matches B1's status unchanged. |

---

## 2. Scope

### In

| # | Deliverable |
|---|---|
| P10 | Contract freeze: new persistence tables, new ids, two new cross-agent seams, wiring |
| P11 | Codelist import (JSON upload → validated → `code_table_import`/`code_attribute`/`code_value`), idempotent on re-upload |
| P12 | Column mapping (`column_mapping`), editable, corpus-scoped |
| P13 | Codelist coverage (`missing`/`partial`/`ok`), computed live per mapped column, per configured prompt language |
| P14 | Feature domain: `Kind`, `Grain`, `ValueType`, `MatchingRule`, the closed 7-type derivation catalogue (types and parameters only — not executed, Q1) |
| P15 | Fingerprint: one pure function (§8.5's algorithm), used for both the draft "preview" badge and (later, phase 3) the real evaluation-time value |
| P16 | Feature CRUD, validation (unmapped/codeless enum column blocks; non-scalar grain blocks), feature-set freeze (immutable once cited-or-not — frozen the moment "Create a feature set" is pressed, per the design, not only once an evaluation cites it) |
| P17 | `/api/v1/codelists/*`, `/api/v1/features/*` |
| P18 | Codelists view, to the design (`Codelists.dc.html`) |
| P19 | Features view, to the design (all five `FeatureConfig*.dc.html` variants as one view) |
| P20 | Two new E2E journeys (J7 Codelists, J8 Features) and the fixture/unit/backend/UI test layers under them |

### Out of phase 2

Evaluations, runs, extraction, scoring, mismatches (F5–F11) — nav entries keep
routing to `placeholder_view`. Derivation *execution* (Q1). A second codelist
source / real VUM export (B1, C6). Cross-config or cross-evaluation views.
Docker, the eval suite.

### Deliberately deferred inside phase 2

- `CensusColumnView.in_config` (already `False`-only since phase 1, per its own
  docstring) starts reflecting real feature membership — this phase turns it on.
- The design's Features "used by" link on Codelists rows (C5) — wired, but
  necessarily empty until a feature exists to populate it; not a stub, just a
  correct answer that happens to start at zero.
- `feature_config.frozen_at` gates *editing*, not *citation* — nothing cites a
  feature set yet, so the "cited by N evaluations" lock path (design's frozen
  board) is built and tested against a **seeded** evaluation row, the same
  pattern phase 1 used for the corpus delete guard (M0-D1).

---

## 3. What's new in the data model

Full definitions are `mvp-spec.md` §5 (baseline) and `sw-design.md` §14
(codelist-specific additions); this is an orientation table, not the source of
truth.

| Table | New / existing | Note |
|---|---|---|
| `code_table_import` | new | + `source_hash` (sw-design.md §14.1, additive beyond spec) |
| `code_attribute` | new | one row per JSON top-level key |
| `code_value` | new | one row per `(attribute, code)`; `label_json` may omit languages |
| `column_mapping` | new | `(corpus_id, source_column) → code_attribute_id`, the only editable table this phase adds |
| `feature_config` | new (spec-defined, not yet in `models.py`) | `frozen_at` set at "Create a feature set" |
| `feature` | new (spec-defined, not yet in `models.py`) | carries `fingerprint`, computed by `domain/fingerprint.py` |
| `evaluation.feature_config_id` | **changed** | M0-D1's plain string becomes a real FK to `feature_config.id` — M0-D1 named this phase as the one that does it |

New `NewType`s in `ra2/domain/ids.py`: `CodeTableImportId`, `CodeAttributeId`,
`ColumnMappingId`, `FeatureConfigId`, `FeatureId`.

Two new cross-agent seams, declared at Wave 0 for the same reason
`CensusMaterialiser` was (plan-m0-m5.md E6 — so two services can be built in
parallel without one blocking on the other):

```python
# ra2/services/protocols.py (amendment)
class EnumCodeTableProvider(Protocol):
    """Feature validation needs to know a mapped column's coverage without
    feature_service depending on codelist_service directly (services/ has no
    internal layering rule, but the two are built by different Wave 2 agents
    at the same time — E2 calls this, E1 implements it)."""
    async def coverage(
        self, session: AsyncSession, corpus_id: CorpusId, source_column: str
    ) -> ColumnCoverage | None: ...  # None = no mapping at all

# ra2/ui/components/ (new file, signature only at Wave 0)
def derivation_builder(*, value: DerivationSpec | None, on_change: Callable[[DerivationSpec], None]) -> Element: ...
def feature_sets_table(*, sets: Sequence[FeatureSetView], ...) -> Element: ...
```

The derivation builder and feature-sets table signatures let G2 (the main
Features view) and G3 (these two components) build in parallel in Wave 4 —
same trick, applied to UI composition instead of a service call.

---

## 4. The parallelisation model

Same four ideas as `plan-m0-m5.md` §1: one serial contract freeze, disjoint
file ownership, isolated worktrees, tests as the handshake. Not repeated here
in full — read that section if this is the first phase you're executing.

One addition specific to a *second* contract freeze: **Wave 0 of this phase
may edit any file `CONTRACTS.md` currently lists**, including ones phase 1
froze. Re-establishing the frozen baseline for a new phase is Wave 0's job,
exactly as M0 did the first time. After Wave 0 re-tags, those files are frozen
again for Waves 1–4.

| Wave | Base | Agents | Milestones | Parallel? |
|---|---|---|---|---|
| **0** | tag `phase1-done` (= current `main`) | 1 (lead or `p2-foundation`) | M9 | no |
| **1** | tag `p2-frozen` | 4 (D1–D4) | M10, M11, M12 | yes |
| **2** | tag `p2w1-green` | 2 (E1–E2) | M13 | yes |
| **3** | tag `p2w2-green` | 2 (F1–F2) | M14 | yes |
| **4** | tag `p2w3-green` | 3 (G1–G3) | M15, M16 | yes |

Nine agent runs (including Wave 0), five integration points. Tag `main` as
`phase1-done` before starting — there is no tag for "phase 1 complete" today,
only the per-wave tags from `plan-m0-m5.md`.

---

## 5. Wave 0 — contract freeze

One agent, serial. Reads `mvp-spec.md` §5/§7/§8, `sw-design.md` §14, and
`design/code-feature/README.md` in full before writing anything.

### 5.1 Deliverables

- **`ra2/domain/ids.py`** — the five new `NewType`s (§3 above).
- **`ra2/domain/codes.py`** *(new, frozen after this wave)* — `CodeAttribute`,
  `CodeValue`, the Pydantic import schema matching `codes-2018.json`
  (`sw-design.md` §14.1), `ColumnCoverage`, `CoverageStatus` (`missing` /
  `partial` / `ok`) — **types and the schema only**; `validate_import()` and
  `compute_coverage()` bodies are D1's (Wave 1).
- **`ra2/domain/feature.py`** *(new, frozen after this wave)* — `Kind`, `Grain`,
  `ValueType`, `MatchingRule` (with parameters), the seven `DerivationType`s and
  six operators (mvp-spec §8.3/§8.4) as typed dataclasses — **shape only, no
  evaluator** (Q1). `DerivationSpec` is what `derivation_json` deserialises to.
- **`ra2/domain/fingerprint.py`** *(new, frozen after this wave)* —
  `FingerprintInput` and the function *signature*;
  `compute_fingerprint(input) -> str` body is D2's.
- **`ra2/persistence/models.py` (amendment)** — `CodeTableImport`,
  `CodeAttribute`, `CodeValue`, `ColumnMapping`, `FeatureConfig`, `Feature`
  ORM classes; change `Evaluation.feature_config_id` to a real
  `ForeignKey("feature_config.id")`.
- **`ra2/services/protocols.py` (amendment)** — `EnumCodeTableProvider` (§3).
- **`ra2/services/container.py` (amendment)** — add `codelist: CodelistService`,
  `feature: FeatureService` fields to `Services`.
- **`ra2/services/errors.py` (amendment)** — `CodelistImportError` (malformed
  upload, §14.1 step 1), `FeatureValidationError` (unmapped/codeless enum,
  non-scalar grain), `FeatureConfigFrozenError` (edit attempt on a frozen set).
- **`ra2/services/readmodels.py` (amendment)** — `CodeAttributeView`,
  `ColumnMappingView`, `FeatureView`, `FeatureConfigView`, `FeatureSetSummary`
  — the read models both adapters get; extend `CensusColumnView.in_config`'s
  docstring to say it is now real.
- **`ra2/api/schemas.py` (amendment)** — request/response models for both new
  routers.
- **`ra2/api/v1/router.py` (amendment)** — include the two new routers.
- **`ra2/services/{codelist,feature}_service.py`** *(new stubs)* — constructor +
  typed method signatures, bodies `raise NotImplementedError`.
- **`ra2/api/v1/{codelists,features}.py`** *(new stubs)* — same treatment.
- **`ra2/ui/components/derivation_builder.py`**, **`feature_sets_table.py`**
  *(new stubs)* — function signatures only (§3).
- **One migration** *(stub is fine at this wave; D3 writes the real one)* — an
  empty revision file wired into the chain, so D3's Wave 1 work is "fill this
  in," not "create the first phase-2 revision from nothing."
- **`CONTRACTS.md` (amendment)** — list every file above; note which are new
  vs. amended; restate the "one migration author" rule naming D3.
- **`CLAUDE.md` (amendment)** — the line "One migration author, ever, in phase
  1 (A3)" becomes "…, one per phase — A3 for phase 1, D3 for phase 2." No other
  change; the Do-NOT list is phase-independent already.

### 5.2 Exit criteria

- `just lint && just test` green with the new stub bodies raising
  `NotImplementedError` (existing tests untouched and still green — this wave
  adds surface, it does not change phase-1 behaviour).
- `alembic upgrade head` runs the new empty migration without error.
- `CONTRACTS.md` lists every file this wave touched, each carrying
  `# FROZEN — see CONTRACTS.md` where phase 1's convention applies.
- A fresh `create_app()` still builds; `Services` has two more fields, both
  satisfiable by the new stub classes.

### 5.3 Review gate

The lead reads `models.py`'s diff, `codes.py`, `feature.py` and
`protocols.py`'s amendment **line by line** before tagging `p2-frozen` — same
reasoning as `plan-m0-m5.md` §3.3: a wrong column name here costs one edit now,
five rebases later. This is also where the `evaluation.feature_config_id` FK
change gets a second look — it is the one change in this wave that touches a
phase-1 table.

---

## 6. File ownership matrix

| Path | W0 | W1 | W2 | W3 | W4 |
|---|---|---|---|---|---|
| `CONTRACTS.md` `CLAUDE.md` | M9 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/domain/{ids,codes,feature,fingerprint}.py` | M9 | 🔒 *(bodies open)* | 🔒 | 🔒 | 🔒 |
| `ra2/persistence/models.py` | M9 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/services/{protocols,container,errors,readmodels}.py` | M9 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/api/{schemas,v1/router}.py` | M9 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/domain/codes.py` *(bodies: `validate_import`, `compute_coverage`)* | M9 stub | **D1** | 🔒 | 🔒 | 🔒 |
| `ra2/domain/feature.py` *(catalogue helpers)*, `fingerprint.py` *(body)* | M9 stub | **D2** | 🔒 | 🔒 | 🔒 |
| `ra2/persistence/repositories/{codelist,feature}_repo.py`, `migrations/versions/**` | M9 stub | **D3** | 🔒 | 🔒 | 🔒 |
| `ra2/ui/components/{seg,rof,readout,fingerprint_badge}.py` *(or additions to `primitives.py`)* | — | **D4** | 🔒 | 🔒 | 🔒 |
| `ra2/services/codelist_service.py` | M9 stub | 🔒 | **E1** | 🔒 | 🔒 |
| `ra2/services/feature_service.py` | M9 stub | 🔒 | **E2** | 🔒 | 🔒 |
| `ra2/api/v1/codelists.py` | M9 stub | 🔒 | 🔒 | **F1** | 🔒 |
| `ra2/api/v1/features.py` | M9 stub | 🔒 | 🔒 | **F2** | 🔒 |
| `ra2/ui/views/codelists_view.py` | — | 🔒 | 🔒 | 🔒 | **G1** |
| `ra2/ui/views/features_view.py`, `ui/state.py` *(additions)* | — | 🔒 | 🔒 | 🔒 | **G2** |
| `ra2/ui/components/{derivation_builder,feature_sets_table}.py` *(bodies)* | M9 stub | 🔒 | 🔒 | 🔒 | **G3** |
| `tests/unit/{codes,coverage}/**` | — | **D1** | | | |
| `tests/unit/{feature,fingerprint}/**` | — | **D2** | | | |
| `tests/backend/persistence/test_{codelist,feature}_repo.py`, migration tests | — | **D3** | | | |
| `tests/ui/test_components.py` *(additions)* | — | **D4** | | | |
| `tests/backend/services/codelist/**`, `tests/fixtures/codelists/**` | — | | **E1** | | |
| `tests/backend/services/feature/**` | — | | **E2** | | |
| `tests/backend/api/codelists/**` | — | | | **F1** | |
| `tests/backend/api/features/**` | — | | | **F2** | |
| `tests/ui/test_codelists_view.py`, `tests/e2e/test_j7_codelists.py` | — | | | | **G1** |
| `tests/ui/test_features_view.py`, `tests/e2e/test_j8_features.py` | — | | | | **G2** |

🔒 = frozen for that wave; amendment only. Per-layer conftests follow phase 1's
rule: owned by whoever owns that layer in that wave; only `tests/conftest.py`
stays lead-owned (and is one of the files Wave 0 may extend if a shared
fixture — e.g. a seeded `code_table_import` — earns its place there).

---

## 7. Wave 1 — domain, persistence, component kit

Base tag `p2-frozen`. Four agents, isolated worktrees.

### D1 — `feat/p2-codes-domain` · codelist domain logic *(M, sonnet)*

**Build:** `domain/codes.py` bodies — `validate_import(raw_json) ->
CodeTableImportResult | list[ValidationError]` (structural validation against
the schema in `sw-design.md` §14.1; any error fails the whole import, no
partial acceptance) and `compute_coverage(cells, mapping, code_values,
language) -> ColumnCoverage` (pure — the `missing`/`partial`/`ok` derivation
in `sw-design.md` §14.2, given plain values, not a session).

**Fixtures** (mirrors the h01–h12 hazard philosophy, `CLAUDE.md`'s "fixtures
must contain the real hazards" rule — codes-2018.json is not personally
sensitive, but tests must not depend on a file that may not exist on a given
checkout, so these are synthetic, small, and committed):
`tests/fixtures/codelists/generate_codelist_hazards.py` producing:
- `c01` — a minimal valid import: two attributes, `de`/`fr`/`it` all present.
- `c02` — a code missing one language's label (drives `partial`).
- `c03` — an attribute with zero codes (drives `missing` once mapped to it).
- `c04` — structurally invalid JSON (missing `"codes"` key on one attribute) —
  the whole import must fail, not just that attribute.
- `c05` — a corpus value with no matching code in the mapped attribute at all
  (the `Finding`-grade case, `sw-design.md` §14.2, distinct from `partial`).

**Exit:** each hazard has a named test asserting the exact outcome (import
succeeds/fails, coverage status); `compute_coverage` is tested at both sides
of the `missing`/`partial`/`ok` boundary; a malformed import writes nothing
partial (asserted by the return type, not by a side effect, since this
function is pure).

### D2 — `feat/p2-feature-domain` · feature domain logic *(M, sonnet)*

**Build:** `domain/feature.py` — the closed derivation catalogue as typed
dataclasses (`CountObjects`, `AnyObjectMatches`, `MaxOrdinal`, … — mvp-spec
§8.3's seven types, six operators), `MatchingRule` per §8.4 including
tolerance parameters, and validation helpers (`is_scalar_grain`,
`requires_codelist`). `domain/fingerprint.py` — `compute_fingerprint`
implementing §8.5's exact ordering: `kind · grain · source_column ·
derivation_json · value_type · matching_rule · enum_codelist_json ·
description`, sha256 over canonical JSON.

**Exit:** every derivation type round-trips through `derivation_json`
serialisation; the fingerprint function is tested for **stability** (same
input twice → same hash) and **sensitivity** (changing any one of the eight
inputs changes the hash, one test per input — this is the property that makes
§8.5's "two runs asked the model different questions" claim true); a
hand-computed fingerprint fixture matches exactly.

### D3 — `feat/p2-persistence` · migration and repositories *(M, sonnet)*

**Build:** the **single** phase-2 migration — `code_table_import`,
`code_attribute`, `code_value`, `column_mapping`, `feature_config`, `feature`
tables, plus altering `evaluation.feature_config_id` into a real FK (backfill
strategy: phase 1 only ever seeded evaluations with a placeholder string for
the corpus-delete-guard test, per M0-D1 — confirm with the lead whether any
such row needs a real `feature_config` to point at, or whether the seeded-row
tests get a trivial one created alongside it). `repositories/codelist_repo.py`
(`code_table_import`/`code_attribute`/`code_value`/`column_mapping` CRUD +
the coverage query's `GROUP BY value_raw` per `sw-design.md` §14.2),
`repositories/feature_repo.py` (`feature_config`/`feature` CRUD, freeze).

**Exit:** `alembic upgrade head` clean on a fresh DB and on a DB already at
`w3-green` (phase 1's final state) — this migration must apply to real
phase-1 databases, not just fresh ones; `alembic check` clean; a round-trip
test per repository; the coverage query tested against a hand-built EAV
fixture with a code count high enough to matter (`> 20` distinct values) to
prove it is *not* reading the top-20-truncated `census_value` table.

### D4 — `feat/p2-components` · shared component kit additions *(S, sonnet)*

**Build:** whatever `ra2/ui/components/primitives.py` is missing for both
views per the design's "new utility classes" list (README, Design Tokens):
a segmented control (`.seg`, two-state Kind toggle), a full-width select/
readout pair (`.rof` editable / `.ro` frozen-static — same visual family,
different interactivity), a fingerprint badge (`.fp`, 6-char truncated hash
plus a "· preview" qualifier), a status pill (`.pill`, reused for "100%",
"no codes", "LOCKED · n evals"), and a master/detail split container
(`flex; nowrap` per the design's explicit "never wraps" requirement, list
pane with a floor width, edit/detail pane with its own floor — both Screen 1
and Screen 2 use the identical shape). Extend, don't replace: `card`, `chip`,
`pagination_row`, `bar` already exist and both views reuse them as-is.

**Exit:** `tests/ui/test_components.py` gains one case per new component;
a resize test asserts the master/detail split never wraps down to 1024px
(mirrors J4's existing width assertions) and that list/detail floor widths
match the design's 300px/360px.

---

## 8. Wave 2 — services

Base tag `p2w1-green`. Two agents; this is the wave the `EnumCodeTableProvider`
seam (§3) exists for.

### E1 — `feat/p2-codelist-service` *(M, sonnet)*

**Build:** `codelist_service.py` — `import_file` (through the existing
`FileStore` seam, §14.1's transaction: validate via D1's `validate_import`,
hash-dedupe against the latest `code_table_import.source_hash`, write
`code_table_import`/`code_attribute`/`code_value` atomically or no-op),
`map_column` / `unmap_column` (write `column_mapping`, no touch to code
tables), `list_columns` (per corpus: every census `enum` column, its mapping
if any, its coverage status via D1's `compute_coverage` + D3's repo query),
`coverage(corpus_id, source_column)` implementing `EnumCodeTableProvider` for
E2 to call.

**Exit:** import twice with the same file is a no-op the second time (asserted
by `code_table_import` row count, not by absence of an error); a corrected
re-upload creates a new generation and old `column_mapping` rows still point
at the previous one until explicitly re-pointed; `list_columns` status matches
D1's hazard fixtures end-to-end through a real repository.

### E2 — `feat/p2-feature-service` *(L, opus)*

**Build:** `feature_service.py` — create/edit/delete a feature (draft only),
validate (unmapped or codeless `enum` column on a mapped-required feature
blocks, per mvp-spec §7; non-scalar grain blocks per §8.2; exploratory cap of
20 per §8.1), compute the **preview** fingerprint via D2's function for every
feature in a draft set, freeze a `feature_config` (immutable once frozen —
blocks further edits, raises `FeatureConfigFrozenError`), clone a frozen set
into a new draft (the design's "Clone to new evaluation," C4).
`EnumCodeTableProvider` is injected — this service never imports
`codelist_service` directly, only the protocol.

**Exit:** a feature referencing an unmapped enum column shows as an error row
and blocks "Create a feature set" (asserted via the validation result, not the
UI); freezing computes and stores every feature's real (non-preview)
fingerprint in one transaction; editing any field of a frozen feature raises;
cloning produces a new draft with fresh feature rows and no shared mutable
state with the frozen original.

---

## 9. Wave 3 — API v1

Base tag `p2w2-green`. Two agents; thin routers, no ORM object crosses the
boundary — same rule as C1/C2 in phase 1.

- **F1 — `feat/p2-api-codelists`**: `/api/v1/codelists/*` — upload, list
  columns with status, map/unmap, get one attribute's code table. *Exit:*
  every endpoint tested through `httpx.ASGITransport`; a malformed upload
  returns 422 with the validation errors, not a 500; re-upload of an
  unchanged file returns 200 with a `"no_change": true` marker the UI can
  render as "already current."
- **F2 — `feat/p2-api-features`**: `/api/v1/feature-configs/*` — list, create
  draft, add/edit/delete feature, freeze, clone. *Exit:* freezing a config
  with a blocking error returns 422 and creates nothing; a frozen config's
  edit endpoints return 409; OpenAPI schema regenerated and the snapshot test
  updated (not silently — the snapshot diff is part of the PR).

---

## 10. Wave 4 — the two views

Base tag `p2w3-green`. Three agents. G2 and G3 both touch the Features
screen but own disjoint files, made possible by the component signatures
Wave 0 declared (§3).

### G1 — `feat/p2-codelists-view` *(L, opus)*

**Build:** `ui/views/codelists_view.py` to `design/code-feature/README.md`
Screen 1 — the three toolbar filter chips + danger chip, the grouped master
list (missing/partial/ok sections with their exact counts and markers), the
edit zone's read-only codes table with the danger/neutral footers, the
"Import Codes as JSON" upload action, the JSON-key mapping dropdown, the
prompt-preview and reminder cards. State per `ui/state.py`'s established
`app.storage.client` pattern (filters, selected column) — no module globals.

**Exit:** `tests/ui/test_codelists_view.py` covers the three status groups
rendering with D1's hazard fixtures behind them, the danger footer's exact
copy for an unlabelled-but-used code, and the coverage percentage bar;
`tests/e2e/test_j7_codelists.py` (**J7**, new): seed a corpus and an unmapped
enum column through the API, upload a codelist through the UI, map the
column, and assert the row moves from "missing" to its real status — the
first E2E journey that exercises F1's endpoints end to end.

### G2 — `feat/p2-features-view` *(L, opus)*

**Build:** `ui/views/features_view.py` — the toolbar (set selector, prompt
language, error-count chip, "Create a feature set"), the flat feature list
with type/fingerprint columns and pagination, the edit zone's shell (kind/
grain/value-type grid, description, matching-rule grid) and **three of the
four edit-zone cases** verbatim from the design: Case A (native enum, links
to Codelists for its coverage number), Case B (time with a tolerance
stepper), Case D (exploratory, with the 20-item budget bar). The frozen-state
variant (read-only, "Clone to new evaluation," the "Evaluations citing this
config" list against a seeded row per the design's deferred-lock pattern,
C4). Case C (the closed-catalogue derivation builder) is a component G3
owns — G2 places it and wires its `on_change` into the feature draft.

**Exit:** `tests/ui/test_features_view.py` covers all three built cases plus
the frozen variant against a seeded frozen `feature_config`; the exploratory
budget bar blocks a 21st exploratory feature; `tests/e2e/test_j8_features.py`
(**J8**, new): seed a corpus and its census through the API, build a labelled
enum feature and an exploratory feature through the UI, freeze the set, and
assert it now appears LOCKED and un-editable.

### G3 — `feat/p2-feature-components` *(M, sonnet)*

**Build:** `ui/components/derivation_builder.py` (Case C: the closed-catalogue
token-chip builder — pick a derivation type, its column/operator/value chips,
the "offer the native column instead where one exists" nudge from the
design's Case C note) and `feature_sets_table.py` (the full-width strip below
the split: draft rename/delete, locked rows' "open ↗" link, the fixed-plus-
filler column layout the design specifies exactly).

**Exit:** the derivation builder round-trips a `DerivationSpec` (D2's type)
through its chip UI without loss; the feature-sets table's filler column is
asserted to absorb width rather than open a gap (mirrors A5's J4 pattern for
the two Import cards); a locked row's rename/delete controls are absent, not
merely disabled.

---

## 11. Testing — cross-cutting summary

Every agent above owns its own test paths (§6); this section is the "does it
all still add up" view mvp-spec.md §15 / sw-design.md §11 already establish
the gates for.

| Layer | New in this phase |
|---|---|
| **Unit** | `domain/codes.py`, `domain/feature.py`, `domain/fingerprint.py` — pure, no I/O (D1, D2) |
| **Backend** | repositories (D3), both services (E1, E2), both routers (F1, F2) — real temp-file SQLite, `alembic upgrade head` from a phase-1-shaped DB |
| **Frontend** | `tests/ui/test_components.py` additions (D4), `test_codelists_view.py` (G1), `test_features_view.py` (G2) — NiceGUI `User` fixture, same as phase 1 |
| **E2E** | **J7** (Codelists: upload → map → coverage, G1) and **J8** (Features: build → freeze → lock, G2) join J1–J6 |
| **Fixtures** | `tests/fixtures/codelists/generate_codelist_hazards.py` (c01–c05, D1); a small feature-config fixture set (E2, for freeze/clone tests) |

No change to the five gates in `sw-design.md` §11.7 — this phase adds tests
under the existing gates, it does not add a gate. `RA2_MIN_CELL_COUNT`,
coverage thresholds, and the Windows/Linux CI matrix are all unchanged.

**No real data reaches any of it.** `codes-2018.json` itself never appears in
a test — D1's synthetic `c01`–`c05` fixtures exist precisely so tests do not
depend on a file that lives under gitignored `data/Codes/` and may not be
present on a given checkout (`sw-design.md` §14.1).

---

## 12. Integration protocol

Identical to `plan-m0-m5.md` §8: per branch, in dependency order (D-agents by
leaf-most-first — D4 has no dependents inside Wave 1, D1/D2/D3 do — then E1,
E2, then F1, F2, then G1, G3, G2 last since it imports G3's components), check
`git diff --name-only <base>..<branch>` against §6, apply or defer any
`contracts/amendments/<branch>.md`, merge, run `just lint && just test` **on
the merged tree**, resolve or name-as-follow-up any `xfail`. After the last
branch of a wave: `just e2e`, tag, spawn the next wave.

---

## 13. Milestone coverage

| Milestone | Delivered by | Exit criteria met at |
|---|---|---|
| M9 Contract freeze | Wave 0 lead | tag `p2-frozen` |
| M10 Codelist + feature domain logic | D1 + D2 | tag `p2w1-green` |
| M11 Persistence | D3 | tag `p2w1-green` |
| M12 Shared component kit | D4 | tag `p2w1-green` |
| M13 Services | E1 + E2 | tag `p2w2-green` |
| M14 API v1 | F1 + F2 | tag `p2w3-green` |
| M15 Codelists view | G1 | tag `p2w4-green` |
| M16 Features view | G2 + G3 | tag `p2w4-green` |

---

## 14. Risks and flags

| # | Flag |
|---|---|
| R1 | **Features is the larger of the two views by a wide margin** (five design files, four edit-zone cases, a frozen variant, a feature-sets table). G2 is sized `L`/opus for that reason; if it still runs long, splitting Case B/D out from Case A is the next cut, following the same disjoint-file logic that separated G3. |
| R2 | **The `evaluation.feature_config_id` FK change is the one Wave 0 edit that touches phase-1 data.** If any seeded evaluation row from phase-1 tests (corpus delete guard, `sw-design.md` §6.3) has no real `feature_config` to point at, D3 needs a trivial seeded one — flagged in D3's brief (§7), decide before Wave 1 starts, not during it. |
| R3 | **Coverage's live `GROUP BY` query is new query shape** the census tables were never meant to serve (`sw-design.md` §14.2 is explicit this is a deliberate exception). If a real corpus's enum columns turn out larger than assumed, this is the first place to look before reaching for materialisation. |
| R4 | **No derivation evaluator (Q1) means Case C's edit zone shows placeholders where the design shows real numbers.** This is a known, accepted gap versus pixel fidelity — call it out in the PR description so a reviewer comparing against the `.dc.html` doesn't file it as a bug. |
| R5 | **Two contract-freeze waves now exist** (M0 and M9), each amendable only by the next one. An agent in Wave 1+ that finds an M0-era file wrong (not just a phase-2 addition) still follows the M0 amendment protocol, not this phase's — `p2-frozen` only unlocked the *new* additions, it did not reopen phase 1's frozen files. |
| R6 | **`CLAUDE.md`'s migration-author line needs the wording amendment in §5.1** applied before D3 starts, or D3 has no rule to point to if questioned mid-wave. |

---

## 15. Decisions this plan makes

| # | Decision | Why |
|---|---|---|
| **F1** | A second full contract-freeze wave (M9/Wave 0), not amendments trickling into phase-1's frozen files | The new tables and seams are wide enough (six new tables, two new protocols, five new ids) that freezing them once beats five agents each amending `models.py` |
| **F2** | `feature_config`/`feature` freeze (immutable, no more edits) on "Create a feature set," not on first evaluation citation | Matches the design's subtitle exactly ("Draft — … never run. Creating a feature set freezes this configuration"). This is a real correction to `mvp-spec.md`'s glossary and §9, made in this same session — both said "frozen when an evaluation's first run executes," which the design's draft/frozen feature-sets table contradicts outright (a frozen set with 2 evaluations already citing it, sitting beside drafts that have never run). The **fingerprint** is a separate concern and still resolves at evaluation creation (§8.5, unchanged): a frozen config has no `corpus_id` and can be cited by evaluations against different corpora later, each with its own `column_mapping` — so the definition freezes now, but `enum_codelist_json`'s snapshot can't be taken until an evaluation fixes which corpus, and therefore which codelist generation, applies. Q3's preview fingerprint is what the draft shows before either freeze point is reached. |
| **F3** | `EnumCodeTableProvider` and the two UI component signatures are declared at Wave 0, not discovered mid-wave | Same reasoning as phase 1's `CensusMaterialiser` (E6): declaring the seam once is what lets the two sides be built by different agents at the same time |
| **F4** | G3 splits out of G2 by component file, not by feature-list vs. edit-zone | The derivation builder and feature-sets table are the two pieces of Screen 2 with no shared mutable state with the rest of the view — genuinely disjoint files, unlike an arbitrary split of the edit zone |
| **F5** | Synthetic `c01`–`c05` codelist fixtures, not a trimmed copy of the real `codes-2018.json` | Same rule phase 1 applied to delivery fixtures: real-shaped data must never be a test's dependency, even when (unlike accident records) it isn't sensitive — the file may simply not be there |

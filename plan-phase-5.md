# Phase 5 Plan — Mismatch review

Delivers **Mismatches** — the eighth and last nav entry, and the last
capability in `mvp-spec.md` §1: **F11**. Every `wrong` outcome already has a
row; this phase makes that list browsable, taggable and exportable, and
reports the tally it produces.

Phase 4 wrote the rows and never read them. `analyst_tag`, `tagged_at` and
`note` have been `NULL` since the scoring pass first ran, deliberately
(`plan-phase-4.md` §1 Q1): *"phase 5 becomes a view over data that already
exists"*. This is that phase, and it is the smallest of the five because that
decision was taken early.

**At `p5w4-green` every acceptance criterion in `mvp-spec.md` §19 that can be
met without the target machine is met, and every capability F1–F12 is built.**
What remains after it is M26 and M34 — the real-corpus passes — and the
`§16` deferrals, which are deferred on purpose and named in §2.2.

**Contracts for implementing agents, in authority order:** `mvp-spec.md` (what)
→ `sw-design.md` (how, including its new §17 — see §0 below) → this file (who
builds what, and what they may touch). On a conflict, `sw-design.md` wins over
this file; `mvp-spec.md` wins over both — same rule as `plan-m0-m5.md` §0 and
every phase plan since, restated because it is the rule that makes disjoint
sub-agents safe.

**There is no design handoff for this view.** Every phase before it had one.
§3.2 is what replaces it, and §1 C1 says what that costs.

Same shape as `plan-phase-3.md` and `plan-phase-4.md`: one document carrying
scope, milestones *and* the wave-by-wave sub-agent breakdown.

---

## 0. The architecture this plan sits under — `sw-design.md` §17, which is not yet written

Phase 4 opened the same way and the lesson held: **§17 is Wave 0's first
deliverable, and the lead should draft it before spawning Wave 0**, so that
wave transcribes an architecture into code rather than inventing one while also
freezing a dozen files.

§16.9 parks this phase explicitly: *"**Mismatch review** (`mvp-spec.md` F11,
§12) — the view, the tagging affordance, the per-feature tally. The rows exist
from this phase (§16.6) and `analyst_tag` stays `NULL` throughout it. Phase 5
is a view over data that is already there."* §17 supersedes that bullet.

§17 is **shorter than §15 or §16** and should say so. There is no new table, no
new outbound call, no new job and no new statistic. What it has to settle is
narrower, and all of it is about one thing: this is the first time a **human**
writes to the database.

| # | What §17 must settle |
|---|---|
| 1 | **Who owns which columns of `mismatch`.** The scorer owns the derived five; review owns `analyst_tag`, `tagged_at`, `note`. Neither writes the other's, and §16.6's upsert is the existing half of that contract |
| 2 | **Tagging is an `UPDATE`, and why that is not a Do-NOT #2 violation** — `mismatch` is not an `extraction`, a `record` or a `corpus`, and §12's whole point is that a human annotates it |
| 3 | **What a tag is worth**: `mvp-spec.md` §12's "the tag never feeds back into a metric. Nothing is rescored." Expressed as a call graph with no edge from review to scoring |
| 4 | **The tally** — per feature, computed on read from stored tags, never stored; the same reasoning §16.1 used for scoring status and §16.5 for ranking |
| 5 | **The vocabulary**: `MismatchTag` as a closed domain enum over a column that stays `String(32)`, and what happens to a value the enum does not name (§1 Q5) |
| 6 | **Staleness.** A re-score deletes rows that no longer mismatch, tags included (§16.6). A tally can therefore move under an analyst, and §17 says whether anything guards that (§1 Q7: nothing does, and the view says when the run was scored) |
| 7 | **The read model surface** and the one query behind it — filter, sort, page — and that no ORM object crosses the boundary |
| 8 | **§17.5 package layout additions** and **§17.6 what it deliberately does not decide** (clustering, cross-model agreement, sampling, automatic triage), in the shape of §15.8 and §16.9 |

`sw-design.md` §13 gains this phase's deviations from **`SD23`**.

**Everything below is subordinate to §17.** Where this file and §17 disagree,
§17 wins and this file gets corrected in the same commit; where §17 is silent,
an agent follows the nearest existing pattern rather than inventing one
(`CLAUDE.md`).

---

## 1. Clarifications

Asked and answered before writing the rest of this plan. **Every one of them
was answered by this plan rather than by a designer** (C1), so each is
recorded with the reasoning that produced it and each is cheap to reverse.

| # | Question | Answer | Consequence |
|---|---|---|---|
| Q1 | What shape is the screen? Every other view in this app is either a filtered table (Census) or a master/detail split (Codelists, Features, Prompts). | **A filtered table — the Census shape**, not master/detail. | `mvp-spec.md` §12's first word is the instruction: "Presented as a **flat**, sortable, exportable list." A master/detail split asserts a hierarchy the spec explicitly refuses, and Census is the existing view whose whole job is "one wide filtered sortable table with an export". Reusing its layout costs no new idiom and no new component (§3.2). |
| Q2 | Where does tagging happen — inline in the row, or in a panel the row opens? | **Inline, in the row**, as a three-way control plus a clear. | `P3-D22`'s lesson, verbatim: re-parse and delete moved *into* the Import row because "deciding to re-run or drop a file is a judgement made **while scanning the State column**, not after opening a report", and doing it for twelve files was twelve modal round trips. Tagging is that workflow exactly — §12's own example is "of **40** reviewed" — and a panel per row would be forty. |
| Q3 | Which mismatches does the view show? There is no "all mismatches ever" question anybody asks. | **`/mismatches?evaluation=<id>`**, with optional `&run=` and `&feature=`, and the standard empty card listing launched evaluations when the parameter is absent. | The same resolution `plan-phase-4.md` C7 took for Results, for the same reason — and it is what makes the Results deep link work (C2). A mismatch belongs to a run; a run belongs to an evaluation; asking the question any other way means joining across corpora nobody asked to compare. |
| Q4 | Can a tag be changed or removed once set? | **Yes.** The control is three-way plus a clear; `tagged_at` is stamped on every write and cleared with the tag. | A tag is a judgement, and a judgement made on the wrong row must be correctable — otherwise the first mis-click is permanent, in the one table a human writes to. Nothing is versioned: `mvp-spec.md` §12 asks for a tally, not an audit trail, and the tag feeds no metric so there is nothing downstream to reconcile. |
| Q5 | Is `analyst_tag` a closed enum? `models.py` says it is deliberately **not** an enum column — "a fourth tag must be a value, not a migration". | **A closed `MismatchTag` enum in `domain/`, over a column that stays `String(32)`.** A stored value the enum does not name renders as itself and is counted under `other`. | Both halves are load-bearing. The enum is what lets the UI, the tally and the CSV agree on three names and what makes a typo a lint error. The string column is what lets a fourth tag arrive without a migration — and the `other` bucket is what stops an unrecognised value crashing a tally instead of being visible in one. `FindingCode` is the precedent for the first half; `entity_kind` for the second. |
| Q6 | How is the evidence span rendered? It is the one field `mvp-spec.md` §19's criterion 7 names explicitly, and it is free text of unbounded length. | **A wrapped cell capped at three lines, with the full value in the export.** No hover-only reveal. | A span is a model-quoted narrative fragment; truncating it to one line hides the thing the criterion asks for, and revealing it on hover puts it out of reach of a keyboard and a screen reader. Three lines fits the design family's 12.5px `.td` without a second table scale. **And because this cell shows record text, the per-record anonymisation marking is required here** (`mvp-spec.md` §13, "required everywhere text is shown"). |
| Q7 | A re-score deletes mismatches that no longer mismatch, tags included (§16.6). What protects an analyst mid-review? | **Nothing, and the view says when the run was scored.** | This is a single-user, single-mode app with no login and everything permitted (§13). A lock would be machinery for a concurrency that does not exist; optimistic versioning would be a second source of truth about a row whose derived half is owned by a job. What is honest is to show the scoring timestamp beside the list, so a tally that moved has a visible reason. |

Smaller items, resolved here rather than left blocking:

| # | Item | Resolution |
|---|---|---|
| C1 | **There is no design handoff for this view**, and every phase before it had one. | **This plan is the design**, and §3.2 is the part a later handoff would overrule. Everything in §3.2 is assembled from components that already exist and tokens that already exist — no new colour, no new table scale, no new layout primitive — so a design round can restyle it without touching a service. The cost is real and is carried as `R2`. |
| C2 | `design/results/README.md`'s Interactions section says: *""Evidence"/span links and mismatch drill-downs open the Mismatches view filtered to that run × feature."* Phase 4 did not build that link, because there was nowhere for it to go. | **Phase 5 builds both ends.** The route accepts `&run=` and `&feature=` (Q3), and `ra2/ui/views/results/extraction_tab.py` gains the link. That is a frozen file belonging to another phase's agent, so it is a **named exception** (§6.1) rather than a quiet edit. |
| C3 | Which columns sort? | Feature, record key, tag, and reviewed-state. **Not** by "how wrong" — there is no such number, and inventing one would be the ordering §16's "mismatch clustering, cross-model agreement, unbiased sampling" deferral exists to refuse. |
| C4 | The tally's wording. `mvp-spec.md` §12's own example reads *"of 40 reviewed, 32 hallucination, 8 record error"* — note "record error", not `structured_data_error`. | **One rendering table in `ui/`**, exactly as `FindingCode` and `ProbeCode` work: `MismatchTag` values are the stable identifiers, asserted on in tests; the words are `ui/`'s. |
| C5 | Does the list show the narrative text itself? | **No.** It shows the record value, the extracted value and the evidence span — §12's own list. The full narrative is the Results per-record drill-down's job (`mvp-spec.md` §13 surface 6), already built. Showing it here would make a scannable list unscannable. |
| C6 | Export format. | `export_service.py`'s existing conventions, reused not re-derived: UTF-8 with a BOM (N3), `;`-delimited, a comment line naming the evaluation, and the **currently filtered, currently sorted** rows only (§7). It carries the tag and the note, because an export whose point is review has to carry the review. |
| C7 | Does anything need a migration? | **Probably not.** `mismatch` exists with its unique key and its `(run_id, feature_id)` index (phase 4). If Wave 1 finds the filtered list wants one more index, that revision belongs to **W1**, phase 5's one migration author. |

---

## 2. Scope

### 2.1 In

| # | Deliverable |
|---|---|
| P52 | Contract freeze: `sw-design.md` §17, `MismatchTag`, the read models, the new seam, the doc corrections in §2.4 |
| P53 | `domain/mismatch.py`: `MismatchTag`, the `other` bucket rule (Q5), and the pure tally function |
| P54 | Persistence: the filtered, sorted, paged list query; the tag write; the tally aggregation |
| P55 | `MismatchService`: list, tag, clear, tally, and the CSV rows — **no path from review to scoring** |
| P56 | `/api/v1/evaluations/{id}/mismatches*` — list, tag, tally, export |
| P57 | The **Mismatches view**, derived in §3.2: filter toolbar, one flat table with inline tagging, the tally strip, the export |
| P58 | The nav change: `mismatches` becomes `built`, and the Results deep link (C2) |
| P59 | One new E2E journey (**J14**) and the unit / backend / UI layers under it |

### 2.2 Out of phase 5

Everything `mvp-spec.md` §16 defers, unchanged and for its stated reasons:
**mismatch clustering, cross-model agreement and unbiased sampling** ("ordering
is a view"); **automatic hallucination triage** (`D1` — "needs a defensible
fuzzy threshold; wants real span data"); **presence P/R/F1** (`D2`);
**per-entity alignment** and **object/person-grain scoring**; **cross-evaluation
views**; **fuzzy or LLM-judge free-text matching** (`D6`); the **installer and
runbook**.

Also out: any path by which a tag changes a number. §12 is categorical —
"nothing is rescored" — and §17 expresses it as an absent edge rather than as a
rule somebody remembers.

### 2.3 Deliberately deferred inside phase 5

- **Bulk tagging.** One row at a time. A "tag all filtered" control is one line
  of UI over the same service call, and it is also how forty rows get the wrong
  tag in one click. It waits until someone has reviewed a real list and asked
  for it.
- **A review queue or assignment.** Single-user, single-mode (§13). There is
  nobody to assign to.
- **Tag history.** Q4: a tally, not an audit trail.
- **Notes as a first-class field in the UI.** The `note` column exists, the
  service writes it and the CSV carries it; the view offers it as an optional
  single-line input rather than a designed affordance, because nothing in §12
  describes one.

### 2.4 Documents this phase corrects

Same-commit corrections, per `CLAUDE.md`. All are Wave 0's, all reviewed at the
§5.3 gate.

| Document | Correction |
|---|---|
| `sw-design.md` | **§17 is written** — §0's eight items. `SD23`+ added to §13. §16.9's "Mismatch review" bullet is superseded by a pointer to §17. |
| `mvp-spec.md` §5 | `mismatch`'s comment gains the column-ownership split (§0 item 1) and names `MismatchTag`'s three values as the vocabulary, while keeping the column a string. |
| `mvp-spec.md` §12 | Unchanged in substance. A note records that `structured_data_error` renders as "record error" (C4) so the spec's own example and the screen agree. |
| `CLAUDE.md` | "One migration author, one per phase — A3 for phase 1, D3 for phase 2, H3 for phase 3, S4 for phase 4" → "…, **W1 for phase 5**" (even if no revision proves necessary — C7). |
| `CONTRACTS.md` | A "Phase 5 — owner: M35 (Wave 0)" section in the shape of the phase-4 one. |
| `pyproject.toml`, `.importlinter` | **No change, and asserted so** — the same gate phase 4 introduced (F10 there). This phase adds no dependency and no contract; the layer rule already forbids what it could get wrong. |

---

## 3. What's new in the data model — and the screen it feeds

**No new table, no new column, and probably no migration** (C7). `mismatch` has
been written since phase 4 and carries everything §12 asks for.

| Table | New / existing | Note |
|---|---|---|
| `mismatch` | existing, **first read here** | `UNIQUE (run_id, record_id, feature_id)` and `ix_mismatch_run_id_feature_id` already exist. What changes is that `analyst_tag`, `tagged_at` and `note` stop being `NULL`. |

**The column ownership split is the whole of this phase's data story.** The
scorer owns `record_value`, `extracted_value` and `evidence_span` and rewrites
them on every re-score; review owns `analyst_tag`, `tagged_at` and `note` and
the scorer preserves them (`SD21`, already built and already tested). Phase 5
is the other side of a contract phase 4 wrote alone.

New in `ra2/domain/ids.py`: **nothing.** `MismatchId` has existed since M27.

### 3.1 One new protocol, declared at Wave 0

```python
# ra2/services/protocols.py (amendment)
class MismatchTally(Protocol):
    """Per-feature review counts, without `results_service` importing
    `mismatch_service`.

    Declared for the fifth time the same trick is played (`CensusMaterialiser`,
    `EnumCodeTableProvider`, `PromptResolver`, `GroundTruthProvider`/`Scorer`).
    Y1 implements it; Z1's view and any later Results surface call it, and
    neither waits.

    **It returns counts and nothing else.** There is deliberately no method
    here that could influence a score — the absence is the contract
    (mvp-spec.md §12, "the tag never feeds back into a metric").
    """

    async def tally(
        self, session: AsyncSession, run_id: RunId
    ) -> Mapping[FeatureId, ReviewTally]: ...
```

### 3.2 The screen, derived from the views that exist

**This section replaces the design handoff** (C1). Every element below is
already built and already asserted somewhere else in this app; what is new is
the arrangement. An implementing agent should be able to build this view
without inventing a single component, colour or size — and if it finds itself
inventing one, that is the signal to stop and raise it.

The reference is **Census** (`design/nav-import-census/README.md` §2): a filter
toolbar over one wide sortable table with an export, plus summary cards. It is
the only view in the app whose job is the same as this one's.

| Requirement | Where it comes from | Built from |
|---|---|---|
| A **flat, sortable list** | `mvp-spec.md` §12 | `components/data_table.py` — `ColumnSpec` with fixed widths, `table-layout:fixed`, and sort headers that **report** rather than sort (the service sorts) |
| **Filter by run, feature, tag state** | §12's list is per run; C3 | Census's filter toolbar: `field_select` per filter, the same 12.5px row |
| **Pagination** | every table in the app | `pagination_row`, 10/page, "1–25 of 162", disabled rather than hidden |
| **Inline tagging**, three values plus clear | §12, Q2 | `segmented_control` — it is already a `role="group"` of real `<button>`s where Tab reaches every segment and the active one carries `aria-pressed="true"`. Three options instead of two; **no new component** |
| The **tag vocabulary** | §12, C4 | One rendering table in `ui/`, `MismatchTag` → words, exactly as `FindingCode` and `ProbeCode` work |
| **Evidence span**, visible | §19 criterion 7, Q6 | A `.td` cell wrapped and capped at three lines. No new scale, no hover reveal |
| **The anonymisation marking** | §13, "required everywhere text is shown" | The `chip` used by Results' per-record list, verbatim |
| **The tally**, per feature | §12, "of 40 reviewed, 32 hallucination, 8 record error" | A `card` + `card_header` strip under the table, the shape Census's summary cards already have |
| **Export CSV** | §12, §19 criterion 7 | `export_service.py`'s conventions unchanged (C6); the toolbar button Census already has |
| **Which evaluation** | Q3 | The empty card + query-parameter resolution `ui/views/results/__init__.py` already implements — **read it, do not re-derive it** |
| **Scored-at, so a moved tally has a reason** | Q7 | The `run-descriptor` line `ui/views/results/chrome.py` already exports |
| **Empty states** | phases 1–4 | `chrome.empty_card`: no evaluation · nothing scored yet · **no mismatches at all**, which is a *good* result and must not read like an error |

**Columns, in order.** Widths follow the design family's existing scale; the
one flexible column is the span.

| Column | Width | Contents |
|---|---|---|
| Feature | 180px | the feature key, mono |
| Record | 190px | truncated record id, mono, + the `anonymised` chip |
| Record value | 140px | authoritative, always (§12) |
| Extracted value | 140px | what the model said |
| Evidence span | flexible | wrapped, three lines (Q6) |
| Tag | 210px | the three-way `segmented_control` + clear |
| Reviewed | 96px | `tagged_at` date, or `—` |

**One thing this screen must not grow**: a column, sort or filter that ranks
mismatches by anything other than the facts above. That is §16's clustering /
agreement / sampling deferral, and it arrives as a helpful-looking feature.

---

## 4. The parallelisation model

Same four ideas as `plan-m0-m5.md` §1. As in every phase since, **Wave 0 may
edit any file `CONTRACTS.md` currently lists**; after it re-tags, those files
are frozen again for Waves 1–4.

**Agent letters are W, Y and Z.** Continuing from phase 4's `V`, skipping
**`X`** — `plan-m0-m5.md` §14's risk register is `X1`–`X4`, and both
`tests/conftest.py` and `tests/ui/conftest.py` cite "X4" in prose. The same
reasoning phase 3 used to skip `J` and phase 4 used to skip `M`–`R`.

| Wave | Base | Agents | Milestones | Parallel? |
|---|---|---|---|---|
| **0** | tag `p4w4-green` | 1 (lead or `p5-foundation`) | M35 | no |
| **1** | tag `p5-frozen` | 2 (W1, W2) | M36, M37 | yes |
| **2** | tag `p5w1-green` | 1 (Y1) | M38 | n/a |
| **3** | tag `p5w2-green` | 1 (Y2) | M39 | n/a |
| **4** | tag `p5w3-green` | 1 (Z1) | M40 | n/a |
| **after 4** | tag `p5w4-green` | lead | M41 | n/a |

**Seven agent runs — half of phase 4's fourteen**, and three of the five waves
have one agent in them. That is not a failure of the model; it is what a phase
looks like when the hard decisions were taken two phases earlier. Waves 2, 3
and 4 stay separate anyway, because the tag gates between them are what keep a
serial phase honest.

---

## 5. Wave 0 — contract freeze

One agent, serial. Reads `mvp-spec.md` §12/§13/§16/§19, `sw-design.md` §16.6
(the upsert this phase is the other half of), and — if the lead has not already
drafted it — writes **`sw-design.md` §17** before writing any code (§0).

### 5.1 Deliverables

- **`sw-design.md` §17**, settling §0's eight items, plus `SD23`+ in §13.
- **§2.4's document corrections** — `mvp-spec.md` §5/§12, `CLAUDE.md`,
  `CONTRACTS.md`. `pyproject.toml` and `.importlinter` are deliberately
  untouched and §5.2 checks that they stayed so.
- **`ra2/domain/mismatch.py`** *(new, frozen after this wave)* — `MismatchTag`
  (the closed three, Q5), `OTHER_TAG` (the bucket an unrecognised stored value
  falls into), `ReviewTally`, and the **signature** of `tally`. Body is W1's.
- **`ra2/services/protocols.py` (amendment)** — `MismatchTally` (§3.1).
- **`ra2/services/container.py` (amendment)** — `mismatch: MismatchService`.
- **`ra2/services/errors.py` (amendment)** — `MismatchNotFoundError` only if
  `NotFoundError` proves insufficient; **expected to add nothing**, and that
  expectation is part of what §5.3 reviews. Phases 2, 3 and 4 each added
  errors; a phase that adds none is a phase that introduced no new failure.
- **`ra2/services/readmodels.py` (amendment)** — `MismatchRowView`,
  `MismatchListView`, `ReviewTallyView`, `MismatchFilters`.
- **`ra2/services/export_service.py` (amendment)** — the `mismatches_csv`
  signature. **It takes the rows**, per `P4-D3`: an export writes the
  currently filtered, currently sorted table, and re-fetching inside the
  exporter is how a CSV comes to disagree with the screen.
- **`ra2/api/schemas.py`**, **`ra2/api/v1/router.py`**, **`ra2/api/deps.py`**
  (amendments) — request/response models, the new router, `MismatchServiceDep`.
- **`ra2/main.py` (amendment)** — construct `MismatchService`.
- **New stubs** — `ra2/services/mismatch_service.py`, `ra2/api/v1/mismatches.py`,
  `ra2/ui/views/mismatches_view.py`: constructors and typed signatures, bodies
  `raise NotImplementedError`.
- **`ra2/persistence/repositories/mismatch_repo.py` (amendment)** — the
  signatures of the filtered/sorted/paged `list_for`, `set_tag` and
  `tally_for`. Bodies are W1's. **`upsert_feature` is unchanged** and must stay
  so: it is the scorer's half of the ownership split, and the tag-preservation
  test that guards it is phase 4's.
- **`tests/test_p5_contract.py`** *(new, lead-owned)* — this wave's exit
  criteria as tests, in the shape of `test_p4_contract.py`.
- **`ra2/ui/shell.py`** — **untouched.** `mismatches` has existed as a
  `NavItem` with `built=False` since phase 1, icon already wired. Z1 flips one
  flag (§6.1).

### 5.2 Exit criteria

- `just lint && just test` green with the new stubs raising
  `NotImplementedError`; **every phase-1 through phase-4 test still green** —
  this wave adds surface, it does not change behaviour.
- `alembic check` clean and the chain unchanged, unless C7's index proves
  necessary — in which case one revision, W1's.
- `tests/test_p5_contract.py` green, including a test that `pyproject.toml`
  and `.importlinter` are byte-unchanged.
- The nav still has eight items and `mismatches` still routes to
  `placeholder_view`; **J4, J5 and J6 green, unchanged**.

### 5.3 Review gate

The lead reads **line by line** before tagging `p5-frozen`: `sw-design.md` §17
in full, `domain/mismatch.py`, and `readmodels.py`'s diff. Two things get a
second look:

1. **The absence of any edge from review to scoring.** §12's "nothing is
   rescored" is this phase's equivalent of the loopback guard: easy to state,
   easy to violate with one convenient import, and invisible once violated
   because the numbers would still look plausible.
2. **`MismatchTag` and the `other` bucket together** (Q5). A closed enum over
   an open column is a deliberate asymmetry, and it is wrong in both directions
   if only half of it lands.

---

## 6. File ownership matrix

| Path | W0 | W1 | W2 | W3 | W4 |
|---|---|---|---|---|---|
| `sw-design.md` `mvp-spec.md` `CONTRACTS.md` `CLAUDE.md` | M35 | 🔒 | 🔒 | 🔒 | 🔒 |
| `tests/test_p5_contract.py` `tests/conftest.py` | M35 | 🔒 | 🔒 | 🔒 | 🔒 |
| `pyproject.toml` `.importlinter` | **untouched** | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/services/{protocols,container,errors,readmodels,export_service}.py` | M35 | 🔒 | 🔒 *(export body: Y1)* | 🔒 | 🔒 |
| `ra2/api/{schemas,deps,v1/router}.py` `ra2/main.py` | M35 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/ui/shell.py` | untouched | 🔒 | 🔒 | 🔒 | 🔒 *(the one-line exception, §6.1)* |
| `ra2/domain/mismatch.py` *(bodies)* | M35 stub | **W1** | 🔒 | 🔒 | 🔒 |
| `ra2/persistence/repositories/mismatch_repo.py` *(the new methods)*, `migrations/versions/**` | M35 stub | **W1** | 🔒 | 🔒 | 🔒 |
| `ra2/ui/components/primitives.py` *(additions)*, `ra2/ui/theme.py` *(additions)* | — | **W2** | 🔒 | 🔒 | 🔒 |
| `ra2/services/mismatch_service.py` | M35 stub | 🔒 | **Y1** | 🔒 | 🔒 |
| `ra2/api/v1/mismatches.py` | M35 stub | 🔒 | 🔒 | **Y2** | 🔒 |
| `ra2/ui/views/mismatches_view.py`, `ui/state.py` *(additions)* | M35 stub | 🔒 | 🔒 | 🔒 | **Z1** |
| `ra2/ui/views/results/extraction_tab.py` *(the deep link only)* | 🔒 | 🔒 | 🔒 | 🔒 | **Z1** *(§6.1)* |
| `tests/unit/mismatch/**` | — | **W1** | | | |
| `tests/backend/persistence/test_mismatch_repo.py` *(additions)* | — | **W1** | | | |
| `tests/ui/test_components.py` *(additions)* | — | **W2** | | | |
| `tests/backend/services/mismatch/**` | — | | **Y1** | | |
| `tests/backend/api/mismatches/**` | — | | | **Y2** | |
| `tests/ui/test_mismatches_view.py`, `tests/e2e/test_j14_mismatches.py` | — | | | | **Z1** |

🔒 = frozen for that wave; amendment only.

### 6.1 The two exceptions, declared up front

Phase 2 left its nav wiring implicit and paid for it with a lead fix-up commit
(`e386a66`); every phase since has declared it instead.

1. **Z1 may flip exactly the `mismatches` `built` flag** in `ra2/ui/shell.py`
   and add exactly its own line to `register_all`. Nothing else in either file.
2. **Z1 may add exactly the mismatch deep link** to
   `ra2/ui/views/results/extraction_tab.py` — the one `design/results/
   README.md` asks for and phase 4 had nowhere to point (C2). One link, in the
   feature row, carrying `evaluation`, `run` and `feature`. **Nothing else in
   that file**, which belongs to V1 and is frozen.

The second is a cross-phase edit and is the reason it is written down rather
than assumed. If it grows past one link, it is an amendment.

---

## 7. Wave 1 — domain, persistence, components

Base tag `p5-frozen`. Two agents, isolated worktrees.

### W1 — `feat/p5-mismatch-domain-persistence` · the vocabulary and the query *(M, sonnet)*

**One migration author, one per phase — W1 for phase 5** (`CLAUDE.md`, as
amended at Wave 0). Nobody else runs `alembic revision`, and the expectation is
that nobody runs it at all (C7).

**Build:** `domain/mismatch.py` bodies — `tally(rows)`, pure, counting stored
tag strings into `ReviewTally`. A value `MismatchTag` does not name goes to
`other`; it is **never dropped and never crashes the count**, because a tally
that silently omitted rows would report "of 40 reviewed" over 38.

Then `mismatch_repo.py`'s three new methods: `list_for` (filter by run,
feature and tag-state; sort by C3's four keys; page), `set_tag` (write
`analyst_tag`, `tagged_at`, `note` and **nothing else**), and `tally_for` (one
grouped query per run, not one per feature).

**Exit:** `tally` counts an unknown tag under `other` and still reports the
right total; an empty input yields a zero tally rather than raising (unlike
`macro` — there is nothing dishonest about "0 reviewed"); `set_tag` leaves
`record_value`, `extracted_value` and `evidence_span` **byte-identical**,
asserted on the row rather than on a count; clearing a tag clears `tagged_at`
with it; the list query is asserted for a **bounded statement count** on a
1 000-row run (the R4 lesson, applied one table over); filtering by
`untagged` and by a specific tag both round-trip; sorting is stable on ties.

### W2 — `feat/p5-mismatch-components` · the three-way control *(S, sonnet)*

**Build:** whatever §3.2 needs that `primitives.py` lacks — which should be
**almost nothing**. `segmented_control` already renders a `role="group"` of
real buttons with `aria-pressed`; if three options and a clear fit inside it,
this agent extends it and adds no component. The multi-line `.td` cap (Q6) is
a style, not a component.

**Exit:** `tests/ui/test_components.py` gains one case per change; the
three-way control is asserted to expose all three values **and** a cleared
state, with `aria-pressed` correct in each; a resize test confirms the table
does not wrap at 1024px. **If this agent finds it needs a genuinely new
component, it says so in its report** — that is the signal C1 warned about, and
it is cheaper to hear in Wave 1 than to discover in Wave 4.

---

## 8. Wave 2 — the service

Base tag `p5w1-green`. One agent.

### Y1 — `feat/p5-mismatch-service` *(M, opus)*

**Build:** `mismatch_service.py` — `list_mismatches` (filters, sort, page, and
the read models `ui/` renders), `tag` / `clear_tag`, `tally` implementing
`MismatchTally`, and `mismatches_csv`'s body in `export_service.py`.

**This module imports nothing from `scoring_service` or `ranking_service`, and
that is the contract.** §12: "the tag never feeds back into a metric. Nothing
is rescored." The absence is what makes it true.

**Exit:** tagging a row and re-reading the list returns the tag and a
`tagged_at`; **tagging changes no `score` row** — asserted by scoring a run,
recording every `score` row, tagging every mismatch, and re-reading them
byte-identically; the tally matches the list's own tag counts for the same
filter, so the strip under the table can never disagree with the table; a
filter that matches nothing returns an empty page with a real `total` of 0
rather than raising; the CSV carries the tag and the note and honours the
filter and sort it was handed (`P4-D3`).

---

## 9. Wave 3 — API v1

Base tag `p5w2-green`. One agent; a thin router, no ORM object across the
boundary — the same rule as every phase since phase 1.

### Y2 — `feat/p5-api-mismatches`

`GET /api/v1/evaluations/{id}/mismatches` (filters, sort, page),
`POST /api/v1/mismatches/{id}/tag`, `DELETE /api/v1/mismatches/{id}/tag`,
`GET /api/v1/evaluations/{id}/mismatches/tally`, and
`GET /api/v1/evaluations/{id}/mismatches.csv`.

**Exit:** every endpoint tested through `httpx.ASGITransport`; an unknown
mismatch id is 404 and an **unknown tag value is 422**, not a silent write —
the enum is closed on the wire even though the column is not (Q5); an
evaluation with no mismatches is **200 with an empty list**, never a 404,
because "nothing was wrong" is a result (the §16.7 reasoning, reapplied);
tagging is idempotent — the same tag twice leaves one row and one `tagged_at`;
the CSV streams with the BOM; OpenAPI snapshot regenerated with the diff in
the PR, and verified **by set comparison** for removals, since the raw diff
shows reordering as churn (phase 4's lesson).

---

## 10. Wave 4 — the view

Base tag `p5w3-green`. One agent.

### Z1 — `feat/p5-mismatches-view` *(L, opus)*

**Build:** `ui/views/mismatches_view.py` to **§3.2**, which is this view's
design. The filter toolbar, the flat table with inline tagging, the tally
strip, the export button, the three empty states, and the evaluation
resolution — **read `ui/views/results/__init__.py` for the last one and reuse
its shape rather than re-deriving it**. Plus §6.1's two exceptions: the `built`
flag and the Results deep link.

State via `app.storage.client` (filters, sort, page) — no module globals
(`Do-NOT #8`). No business logic (`Do-NOT #7`): the tag vocabulary's *words*
live here (C4), every count and every row arrives made.

**Exit:** `tests/ui/test_mismatches_view.py` covers all three tag values plus
clear, the filter round-trip, the tally strip agreeing with the rendered rows,
the anonymisation chip on every row that shows text (Q6), and all three empty
states — including **"no mismatches", which must not read like an error**;
`tests/e2e/test_j14_mismatches.py` (**J14**, new): seed a scored evaluation,
open Mismatches filtered from a Results feature row (proving C2's link),
tag three rows with three different values, reload, assert the tags survived
and the tally reads "3 reviewed", then export and assert the CSV carries them.

**J14's file is named `test_results_...`-style for collection order if it
seeds into the session database** — see `tests/e2e/test_results_j11_to_j13.py`'s
docstring for why, and prefer reusing that module's already-seeded corpus over
adding a second one.

---

## 11. Testing — cross-cutting summary

| Layer | New in this phase |
|---|---|
| **Unit** | `domain/mismatch.py` (W1) — the tally, the `other` bucket, the empty case. Small, pure, and the only arithmetic this phase has |
| **Backend** | `mismatch_repo`'s three new methods (W1), `MismatchService` (Y1), the router (Y2) |
| **Frontend** | `test_components.py` additions (W2), `test_mismatches_view.py` (Z1) |
| **E2E** | **J14** joins J1–J13 |
| **Fixtures** | **None new.** `tests/fixtures/scored_corpus.py` already produces mismatches — `s02`/`s03`'s wrong answers are where they come from — and a phase that needs no new hazard is a phase built on one that did |
| **Eval** | Unchanged. Nothing here touches a model |

**The two assertions this phase exists to make**, each named and each at more
than one layer:

1. **A tag changes no number.** Asserted at the service layer by byte-comparing
   every `score` row across a tagging session, and structurally by
   `mismatch_service` importing neither scoring module.
2. **A re-score preserves a tag.** Already asserted in phase 4 (S4, T1) — J14
   re-asserts it from the analyst's side, because that is the one path where
   losing it would be discovered by a person rather than a test.

Coverage stays scoped to `ra2/domain` + `ra2/services` at `fail_under = 85`.
This phase adds little domain code and a moderate service, so the number should
barely move; if it drops, logic leaked into the view.

---

## 12. Integration protocol

Identical to `plan-m0-m5.md` §8 and every phase plan since: per branch, check
`git diff --name-only <base>..<branch>` against §6, apply or defer any
`contracts/amendments/<branch>.md`, merge, run `just lint && just test` **on
the merged tree**. After the last branch of a wave: `just e2e`, tag, spawn the
next wave.

Dependency order per wave: **Wave 1** — W2, then W1. The other three waves have
one agent each.

Manual verification runs **`just dev-agent`, never bare `just dev`**
(`CLAUDE.md`) — and in this phase that matters as much as in phase 3, because
this is the first code that **writes a human's judgement to a row**, and
`just dev` points at the developer's real `./var` database.

---

## 13. Milestone coverage

| Milestone | Delivered by | Exit criteria met at |
|---|---|---|
| M35 Contract freeze **+ `sw-design.md` §17** | Wave 0 lead | tag `p5-frozen` |
| M36 Mismatch domain + persistence | W1 | tag `p5w1-green` |
| M37 Component kit additions | W2 | tag `p5w1-green` |
| M38 `MismatchService` | Y1 | tag `p5w2-green` |
| M39 API v1 | Y2 | tag `p5w3-green` |
| M40 The Mismatches view + J14 | Z1 | tag `p5w4-green` |
| M41 The closing pass on the target machine | lead | tag `phase5-done` |

At `p5w4-green`, `mvp-spec.md` §19's criterion **7** — "the mismatch list is
browsable, taggable and exportable, with evidence spans" — is met, and **every
capability F1–F12 is built**.

**M41 is what is left of the whole MVP**, and it is the same session that owes
**M26** (phase 3's eval layer and the ≥200-record acceptance run) and **M34**
(phase 4's criterion-6 pass over a real scored corpus). All three need the
target machine and none of them needs any more code. Criteria 1, 3 and 4 also
want a real delivery to be honestly claimed.

---

## 14. Risks and flags

| # | Flag |
|---|---|
| R1 | **`sw-design.md` §17 does not exist yet.** Phase 4 carried the same risk and the mitigation held: the lead drafts §17 before spawning Wave 0. It is a smaller section than §15 or §16, which makes it *more* tempting to skip and no less load-bearing — items 1 and 3 in §0 are the ones a wave would otherwise invent. |
| R2 | **There is no design handoff, and §3.2 is standing in for one** (C1). The risk is not that the screen is ugly; it is that an agent takes §3.2's list of existing components as a starting point rather than as a boundary, and this view quietly acquires a second table scale or a fourth colour. W2's exit criteria make "I needed a new component" a reportable event for exactly this reason. |
| R3 | **"Nothing is rescored" is one import away from being false.** §12 is categorical, the violation would be convenient, and the result would still look plausible — a tally that moved a number is not visibly wrong. It gets the §5.3 line-by-line gate and a structural assertion, the way the loopback guard did in phase 3. |
| R4 | **This is the first human write in the pipeline.** Everything before it was append-only or job-owned. The ownership split (§3) is the whole defence, and half of it — the scorer's upsert — is already built and tested. The other half is Y1's `set_tag`, whose exit criterion is byte-equality on the columns it must not touch. |
| R5 | **A re-score can delete a tagged row** (Q7, §16.6). Correct, and invisible: the analyst sees a shorter list and no explanation. The scored-at line beside the list is the entire mitigation and it is cheap; if it proves insufficient in real use, the next step is a count of tags lost, not a lock. |
| R6 | **Seven agent runs makes this phase look trivial.** It is not: it is small because phases 3 and 4 wrote the rows, the constraint and the preservation test in advance. The parts that remain small are the parts somebody already decided. |
| R7 | **The `other` tag bucket is untestable against real data** until someone stores a fourth tag, which nothing in the MVP does. It is exercised by a fixture that writes a raw string; that is honest but it is a synthetic guarantee, and a later phase adding a real fourth tag should re-read Q5 rather than trusting it. |

---

## 15. Decisions this plan makes

Numbered `F1…` following every phase plan since `plan-phase-2.md` §15, and
always cited as "§15 F*n*" — `mvp-spec.md` §1 uses `F1…F12` for capabilities,
and the two must not be read into each other.

| # | Decision | Why |
|---|---|---|
| **F1** | **This plan is the design** (§3.2), because there is no handoff (C1) | Every element is assembled from components, tokens and sizes that already exist and are already asserted elsewhere, so a later design round can restyle the view without touching a service. Inventing a visual language here — with no designer to answer to — is how a seventh view stops looking like the other six. |
| **F2** | **A flat filtered table, not a master/detail split** (Q1) | `mvp-spec.md` §12's first word is "flat". Master/detail is this app's other layout and it asserts a hierarchy the spec refuses; Census is the view whose job is already "filter, sort, export one table". |
| **F3** | **Tagging is inline in the row** (Q2) | `P3-D22`'s finding, applied: the judgement is made while scanning, and forty rows through a panel is forty round trips. §12's own example — "of 40 reviewed" — describes bulk review, not a sequence of modals. |
| **F4** | **`MismatchTag` is a closed enum over a column that stays a string**, with an `other` bucket (Q5) | The enum makes three names agree across the UI, the tally and the CSV and makes a typo a lint error; the string column keeps `models.py`'s promise that "a fourth tag must be a value, not a migration". The `other` bucket is what stops the asymmetry becoming a crash. |
| **F5** | **The tally is computed on read, never stored** | The third time this phase family makes the same call: scoring status (§16.1 F5), ranking (§16.5 F3), and now this. A stored tally is a second source of truth that a re-score, or a tag, can desynchronise — and the query is one `GROUP BY` over an indexed column. |
| **F6** | **No path from review to scoring**, expressed as an absent import and an absent method (§3.1, R3) | §12 is categorical: "the tag never feeds back into a metric. Nothing is rescored." A rule nobody can violate beats a rule everybody remembers, and this one would be invisible once violated. |
| **F7** | **A tag can be changed and cleared** (Q4) | The first mis-click would otherwise be permanent in the one table a human writes to. Nothing is versioned because §12 asks for a tally, not an audit trail, and the tag feeds nothing downstream that would need reconciling. |
| **F8** | **Nothing guards a re-score against an in-flight review**; the view shows when the run was scored (Q7, R5) | Single-user, single-mode, no login (§13). A lock is machinery for a concurrency that does not exist. What an analyst actually needs is a visible reason for a list that changed, and that is one line of chrome that already exists. |
| **F9** | **Agent letters are W, Y, Z**, skipping `X` | `plan-m0-m5.md` §14's risk register is `X1`–`X4`, and two committed conftests cite "X4" in prose. Phase 3 skipped `J` and phase 4 skipped `M`–`R` for the same reason: a letter that already means something costs half an hour in every integration report. |
| **F10** | **No new dependency, no new lint contract, and no new test fixture** — all three asserted | The second phase in a row to add no dependency, and the first to add no fixture: `scored_corpus` already produces mismatches, because phase 4 built the hazard set that makes them. A phase that needs nothing new is the return on having built the foundations deliberately. |

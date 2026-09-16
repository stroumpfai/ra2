# Phase 4 Plan — Scoring and Results

Delivers the view drawn in `design/results/README.md` — **Results**, one
sidebar entry with three tabs (Goal 1 Extraction, Goal 2 Presence, Ranking) —
plus everything underneath it that has to exist before a single number can be
rendered: the matching engine, the derivation evaluator phase 2 deferred, the
statistics module, and the scoring pass that turns immutable `extraction` rows
into `score` and `mismatch` rows.

That is `mvp-spec.md` §1's **F7**, **F8**, **F9** and **F10**. Mismatch *review*
(**F11**) stays out — but the `mismatch` rows themselves are written here,
because they are a by-product of classification and building the scorer twice
is waste (§1 Q1).

This phase ends where every run in an evaluation is scored, the three Results
tabs render those scores honestly — with intervals, with suppression, with ties
shown as ties — and **nothing yet lets an analyst tag a mismatch**.

**Contracts for implementing agents, in authority order:** `mvp-spec.md` (what)
→ `sw-design.md` (how, including its new §16 — see §0 below) →
`design/results/README.md` (copy/layout/behaviour fidelity for the three tabs)
→ this file (who builds what, and what they may touch). On a conflict,
`sw-design.md` wins over this file; `mvp-spec.md` wins over both — same rule as
`plan-m0-m5.md` §0, `plan-phase-2.md` and `plan-phase-3.md`, restated because
it is the rule that makes disjoint sub-agents safe.

Same shape as `plan-phase-2.md` and `plan-phase-3.md`: one document carrying
scope, milestones *and* the wave-by-wave sub-agent breakdown.

---

## 0. The architecture this plan sits under — `sw-design.md` §16

**§16 is written** — as Wave 0's first act, before any other file in this
wave was touched. No sub-agent in any wave below has to invent a scoring
architecture in its own worktree.

That took one correction to this section, recorded here rather than quietly
applied. **When this plan was drafted, §16 did not exist**, which was the one
structural difference from phase 3 — `plan-phase-3.md` §0 could open by saying
§15 was already written, and `sw-design.md` §15.8 explicitly parked scoring:
*"Scoring, Results and Mismatches (`mvp-spec.md` F7–F11). Runs produce
`extraction*` rows and stop there; nothing reads them yet. The `score` and
`mismatch` tables stay unbuilt."* This plan therefore made §16 **Wave 0's first
and largest deliverable**, to be complete and reviewed *before any Wave-1 agent
is spawned*, and recommended the lead draft it ahead of the rest of the freeze
so that Wave 0 transcribes an architecture rather than inventing one while also
freezing twenty files. That is what happened, and §15.8's bullet is now
superseded by a pointer to §16.

§16 settles these ten things. Every one of them is a question a Wave-1 or
Wave-2 agent would otherwise have answered alone, in its own worktree,
differently:

| # | What §16 must settle |
|---|---|
| 1 | **The scoring transaction boundary** — one `(run, feature)`, one commit — and why that constraint *is* the resume key, exactly as §15.3 did for `UNIQUE (run_id, record_id)` |
| 2 | **`score.metric` as a closed vocabulary** (§3, F2): which metrics exist, that raw counts ride in the same shape, and why no second table appears |
| 3 | **Ground-truth resolution** — how a record's true value is reached for a native feature (`unfall_row`) and for a derived one (the catalogue evaluator), and the single EAV projection query that feeds both without N+1 |
| 4 | **The §8.6 denominator rule as code** — an empty source column leaves the denominator *entirely*; it is never a `missing`, never a zero, never a suppressed cell |
| 5 | **Where the statistics live** — `domain/stats.py`, pure, no persistence, and why Wilson is written out rather than imported (F10) |
| 6 | **Ranking as a derivation, not a table** (F3) — the invariant the design README states as "if the two disagree, Ranking is wrong by construction", expressed as a call graph |
| 7 | **Re-scoring semantics** — idempotent, deterministic, and `analyst_tag`-preserving; `mismatch` is the first mutable row in this codebase and the rules for it belong in one place |
| 8 | **Scoring status without a status column** — derived from committed `score` rows, the same reasoning §15.4 used for run progress (F5) |
| 9 | **The Results read-model surface** — which shapes cross the service boundary for each of the three tabs, and that no ORM object does |
| 10 | **§16.7 package layout additions** and **§16.8 what it deliberately does not decide** (Mismatch review, presence P/R/F1, cross-evaluation views, Goal 3 review workflow), in the shape of §14.4 and §15.8 |

`sw-design.md` §13 gains this phase's deviations as `SD16`–`SD22` (§2.4).

**Everything below is subordinate to §16.** Where this file and §16 disagree,
§16 wins and this file gets corrected in the same commit; where §16 is silent,
an agent follows the nearest existing pattern rather than inventing one
(`CLAUDE.md`).

---

## 1. Clarifications

Asked and answered before writing the rest of this plan, because each answer
changes its shape. Recorded here rather than only in chat history, so a later
reader does not have to guess why a scope line reads the way it does.

| # | Question | Answer | Consequence |
|---|---|---|---|
| Q1 | How far does this phase reach — the design package covers Results only and says Mismatches is "a separate sidebar entry, to be handed off later", but scoring emits mismatch rows either way, and `mvp-spec.md` §19's criterion 7 needs the list. | **Scoring + Results only.** The scorer writes `mismatch` rows because they are a classification by-product; the Mismatches **view** and analyst tagging wait for their own design handoff. | Phase 5 becomes a cheap view-only phase over data that already exists, and the scorer is written once. `analyst_tag` and `tagged_at` exist and stay `NULL` for the whole of this phase — which is exactly the phase-2 precedent of a correct answer that happens to start at zero. Acceptance criterion 7 is **not** met by this phase; criterion 6 is. |
| Q2 | `mvp-spec.md` §5 defines a `score` table, `sw-design.md` §15.8 left it unbuilt, and the design README insists Ranking must never be cached independently of tab 1. Materialise, or compute on read? | **Materialise `score` and `mismatch` in one pass**, on the phase-3 `TaskRunner` seam. Wilson, suppression, tie marking, macro-averaging and the whole of Ranking stay **pure functions over those rows**, never stored. | One classification pass, two tables, one job. Tab 3 cannot drift from tab 1 because it is a function of the same rows (F3). `mismatch` must be materialised regardless — it is a row an analyst will later tag — so computing scores on read would mean writing the pass anyway *and* paying ~195 000 classifications per page load on a 5 000-record × 13-feature × 3-model evaluation. |
| Q3 | When does a run get scored? The design draws no "score" button anywhere — Results simply exists. | **Automatic on run completion, plus an explicit re-score.** Scoring is chained after the run worker's terminal `done`. | Every input is frozen at launch, so nothing can change between run end and scoring; a button would be a control the design never drew for a decision the user cannot meaningfully make. Re-score exists for when the *scorer's own code* changes, and it preserves `analyst_tag` (F4, R5). A `failed` or `interrupted` run is never scored. |
| Q4 | `mvp-spec.md` §11.4 says the minimum cell count is "Default **20**, configurable **per evaluation**", but `infra/config.py` already carries a global `min_cell_count = 20` and the design hard-codes 20 into the rendered copy. | **A per-evaluation column now** — `evaluation.min_cell_count`, defaulting from config at draft creation. | Matches the spec verbatim, and costs one column in a migration Wave 0 is writing anyway; adding it later costs a migration of its own. **Every piece of copy reads the number from the evaluation, never as a literal** — the card header, the suppression notice and the Ranking footnote all interpolate it (F6). |
| Q5 | Phase 3's **M26** (the `tests/eval` layer and the ≥200-record acceptance run on the target machine) has not happened — there is no `phase3-done` tag, only `p3w4-green`. What does Wave 0 branch from? | **Branch from `p3w4-green` now.** M26 stays an open phase-3 item the lead closes whenever the target machine is available. | Nothing in scoring needs a GPU or a live endpoint — it reads committed `extraction` rows — so the two do not block each other. It **is** a risk and it is carried as one (R10): this phase builds a scorer over an extraction path that has not yet met a real model. |
| Q6 | The design README defines `--accent: oklch(0.52 0.13 255)` — **blue** — for the Results family, against the neutral `oklch(0.50 0.008 260)` every other view uses, and asks the team to decide deliberately. | **Keep the neutral accent. The `.mk` tie markers stay shape-coded** — filled / outlined / empty. | `ra2/ui/theme.py`'s own header already records that the prototypes' blue `--accent` is "a blue left over from an earlier pass" and that the README wins, under the standing rule *"Colour carries only state and severity. No decorative hue."* The marker vocabulary is already three distinct **shapes**, which reads without hue and survives colour-blindness; adding a decorative data hue to one view family would break a phase-1 rule for no legibility gain (F9). |

Smaller open items — the design README's own six "Open questions for the team",
plus the ones this plan's shape raises — resolved here rather than left
blocking, each reversible:

| # | Item | Resolution |
|---|---|---|
| C1 | Design open question 1: two model rosters appear in the fixtures (Evaluation's `qwen2.5:14b`/`mistral-nemo:12b`/… versus Results' `qwen3:14b`/`mistral-small:24b`/`gemma3:12b`). | **Moot in implementation.** Models come from the endpoint's catalogue and the run's stored `model_name` + `model_digest`; nothing in the codebase names a roster. The tests pick **one** roster — `qwen3:14b` / `mistral-small:24b` / `gemma3:12b`, the Results boards' — so fixtures and screenshots agree. |
| C2 | Design open question 2: the accent divergence. | Q6. |
| C3 | Design open question 3: feature-name drift (`Witter0Ausw` vs `WitterungAusw`). | **Moot, and already ruled on.** `sw-design.md` §13's closing note settles it: `WitterungAusw`/`LichtverhaeltnisAusw` do not exist in the delivery, the real columns are `Witter0Ausw`/`LichtVerhAusw`, the design's fixtures are illustrative, and **column names are only ever read from the header** (`Do-NOT #5`). The Results boards happen to use the real spellings; Census/Codelists/Features use invented ones. Neither is authored anywhere in code. |
| C4 | Design open question 4: presence precision / recall / F1 deferred pending a human-labelled subset. | **Already the spec's position** (`mvp-spec.md` §11.2, `D2`, §16). Nothing to decide. Tab 2's scope banner states the deferral **verbatim** and is not dismissible — that copy *is* the feature (§10, V2). |
| C5 | Design open question 5: the `n = 20` floor and the 200-record dev threshold are hard-coded in the copy — are they product constants? | The floor is Q4 — a per-evaluation column. The dev/eval thresholds **already live in config** (`dev_record_max = 50`, `eval_record_min = 200`) since phase 3. Both are interpolated into copy, never typed into it. The design's "Dev · 40 records" and "minimum of 20" are fixtures, not literals. |
| C6 | Design open question 6: Goal 3 (Exploratory) is only a card on tab 1, and its "0 / 15 reviewed" counter implies a review workflow. | **The counter defers with Mismatch tagging** (Q1) — it is the *same* machinery. This phase ships the discovery rate, the returned-value distribution and the **evidence-span list** (read-only, from `extraction_value.evidence_span`, which §11.3 makes mandatory). The Reviewed column renders `— / n` with a tooltip naming the deferral rather than a fake zero. |
| C7 | The design draws **no way to choose which evaluation** you are looking at: the boards render one run descriptor and a `cfg` chip with no picker. | **`/results?evaluation=<id>`**, plus a standard index card listing launched evaluations when the parameter is absent or unknown — the phase-1/2 empty-card pattern, no new idiom. Phase 3's `evaluation_view.py` left the runs-table run-id link pointing at a deliberate placeholder route; **this phase is where it lands**, carrying the evaluation id. |
| C8 | Ranking's **Presence** column ("0.907") reads as a quality score, which `mvp-spec.md` §11.2 forbids: presence has no gold label, and a model that flags everything present wins it. | Rendered as **macro presence *rate***, in the **reported-never-scored** group beside Median latency and VRAM — §3d's rule 4 vocabulary, extended to it. It takes **no part** in rank computation, and the column header says `presence rate`, not `presence` (F8). `mvp-spec.md` §11.5 is corrected to say so (§2.4). |
| C9 | "Loading / empty — not designed. A run with zero labelled features should say so rather than render an empty table." | Three states, all on the standard empty card: **not scored yet** (no `score` rows for the run), **scoring…** (a `TaskRunner` task in flight, progress polled exactly as import and runs do), and **nothing scoreable** (zero labelled features, or every feature below the floor). The third one says which, and why. |
| C10 | The breakdown row's note — "Hallucination is *not* computed — it is a review tag on the mismatch list." | **Verbatim, and it is a spec guarantee, not a caption**: `mvp-spec.md` §11.1's ⚠ paragraph and `D1`. It renders even though the mismatch list it points at is phase 5 — a promise the product keeps by not making a claim. |
| C11 | `ra2/services/export_service.py` is frozen (phase-1 B2-owned) and tab 2's per-record list needs a CSV export. | Wave 0 declares `presence_records_csv(...)` on it as a stub, the way it declares every other new signature; **T2 fills the body**. The CSV conventions are settled and reused, never re-derived: UTF-8 **with BOM**, `;`-delimited, a header comment naming corpus id and version, and the **currently filtered, currently sorted** rows only (`sw-design.md` §7). |

---

## 2. Scope

### 2.1 In

| # | Deliverable |
|---|---|
| P37 | Contract freeze: `sw-design.md` §16 (§0), `score`, `mismatch`, `evaluation.min_cell_count`, new ids, two new seams, three tab signatures, the doc corrections in §2.4 |
| P38 | **Statistics** — `domain/stats.py`: Wilson 95 % interval, the suppression predicate, tie marking (`best` = no overlapping rival; every overlapper = `tied`), macro-averaging over non-suppressed features |
| P39 | **Matching** — `domain/matching.py`: `mvp-spec.md` §8.4's normalisation-and-match table for all seven value types, strict-exact free text (`D6`) |
| P40 | **Derivation evaluation** — `domain/derivation.py`: the closed 7-type catalogue actually executed, with its 6 operators. **This closes `plan-phase-2.md` Q1**, which deferred it with the words "scoring needs to build one anyway" |
| P41 | **Classification** — `domain/scoring.py`: hit / wrong / missing per `mvp-spec.md` §11.1, the §8.6 denominator rule, Goal 2's presence rate + cross-tab + flag-inconsistency shapes, Goal 3's discovery rate |
| P42 | **Ranking** — `domain/ranking.py`: macro F1, shared ranks on overlapping intervals, separating features. Pure, derived, never stored |
| P43 | Persistence: the phase-4 migration, `score_repo`, `mismatch_repo`, and the **ground-truth projection query** (one pass over the EAV tables per corpus, not N+1) |
| P44 | `ScoringService`: the pass over a finished run, chained automatically (Q3), restartable per `(run, feature)`, with an explicit tag-preserving re-score |
| P45 | `ResultsService`: the read models for tabs 1 and 2 — per feature × model with sorting and pagination, the per-model breakdown, by-language, exploratory, presence rate, the cross-tab, flag inconsistency, and the per-record output list |
| P46 | `RankingService` + the per-record CSV export (C11) |
| P47 | `/api/v1/evaluations/{id}/results/*`, `/presence/*`, `/ranking`, and the re-score / scoring-status endpoints |
| P48 | The **Results view** — one route, three tabs, to `design/results/README.md`, with its verbatim copy |
| P49 | Component kit additions: the `.mk` tie marker, the `.val` / `.ci` value-over-interval pair, the `.ins` insufficient-data chip, the tab strip, the contingency table, the suppressed-row treatment |
| P50 | Three new E2E journeys (**J11** Extraction, **J12** Presence, **J13** Ranking consistency) and the fixture / unit / backend / UI layers under them — including the **golden-numbers fixture** (§11) |
| P51 | **`P3-D15`'s inherited obligation**: the aware-UTC `TypeDecorator` on the stored-timestamp column type, and the deletion of the two duplicated `_as_utc` helpers phase 3 left in `evaluation_service.py` and `run_service.py`. Added after the plan was first written — see §5.1 |

### 2.2 Out of phase 4

**Mismatch review (F11)** — the view, the tagging, the tally. Its nav entry keeps
routing to `placeholder_view` and its rows accumulate untagged (Q1).
Entity **scoring** (`extraction_entity` stays captured, never scored —
`mvp-spec.md` §10.3, unchanged since phase 3). Presence P/R/F1 (C4).
Cross-evaluation and cross-corpus views. Goal 3 review workflow (C6).
Fuzzy or LLM-judge free-text matching (`D6`, `mvp-spec.md` §16). Automatic
hallucination triage (`D1`). Docker and the installer.

### 2.3 Deliberately deferred inside phase 4

- **Scoring concurrency.** The pass runs one `(run, feature)` at a time on the
  existing `TaskRunner`, the same serial posture `RA2_RUN_CONCURRENCY = 1`
  takes for extraction (phase 3 F7). It is CPU-bound and short next to a run;
  nothing here parallelises it.
- **Auto-rescoring on a scorer change.** There is no version-stamp on the
  scoring code and no migration that invalidates existing `score` rows. A
  re-score is an explicit action, for the same reason a resume is
  (phase 3 F8).
- **Incremental scoring of a running run.** A run is scored when it reaches
  `done`, not as it goes. Partial scores of a partial run are a second kind of
  number that means something different, and the design has no place to show
  one.
- **Storing the returned-value distribution for Goal 3.** The discovery rate
  and the span count are stored as `score` rows; the *distribution* of returned
  values (`mvp-spec.md` §11.3) is computed on read from `extraction_value`,
  because it is a browse, not a metric.

### 2.4 Documents this phase corrects

Same-commit corrections, per `CLAUDE.md`'s "where it is wrong, raise it and
change *that file* first". All are Wave 0's, all reviewed at the §5.3 gate.

| Document | Correction |
|---|---|
| `sw-design.md` | **§16 is written** — the ten items in §0. `SD16`–`SD22` added to §13. §15.8's "the `score` and `mismatch` tables stay unbuilt" is superseded by a pointer to §16. |
| `mvp-spec.md` §5 | `evaluation` gains `min_cell_count` (Q4). `score`'s `metric` column is documented as a **closed vocabulary that also carries raw counts**, not only rates (F2). `mismatch` is unchanged — but its `analyst_tag` is documented as the one mutable column in the pipeline, and re-scoring is documented as preserving it. |
| `mvp-spec.md` §11.4 | Already says "configurable per evaluation"; the note now names the column that makes it true, so the next reader does not implement it from config. |
| `mvp-spec.md` §11.5 | Ranking reports a macro **presence rate** as a *reported-never-scored* figure beside latency and VRAM, and it takes no part in rank computation (C8, F8). |
| `CLAUDE.md` | "One migration author, one per phase — A3 for phase 1, D3 for phase 2, H3 for phase 3" → "…, **S4 for phase 4**". |
| `CONTRACTS.md` | A "Phase 4 — owner: M27 (Wave 0)" section in the shape of the existing phase-3 one. |
| `design/results/README.md` | **Not edited.** It is a handoff, read-only, like every design README before it. Its six open questions are answered in §1 (C1–C6) and the answers live *here*, where an implementing agent reads them. |
| `pyproject.toml` | **No change — and that is deliberate** (F10). The Wilson interval is a closed form over a single constant (`z = 1.959963985`); pulling in `scipy` for it would be the largest dependency in the project, added for one number. |
| `.importlinter` | **No change.** The layer rule already forbids everything this phase could get wrong: `domain/stats.py`, `matching.py`, `derivation.py`, `scoring.py` and `ranking.py` sit in `domain/` and therefore cannot import SQLAlchemy, a session or a repository. The contract that guarantees Ranking is pure is one that already exists. |

---

## 3. What's new in the data model

Full definitions are `mvp-spec.md` §5 (as corrected by §2.4) and
`sw-design.md` §16; this is an orientation table, not the source of truth.

| Table | New / existing | Note |
|---|---|---|
| `score` | new (spec-defined, never built) | `(run_id, feature_id, language\|NULL, metric, value, n, ci_low, ci_high)`. `language IS NULL` = the all-languages row. `metric` is a **closed vocabulary** (below). Written once per `(run, feature)` in one commit; a re-score replaces that feature's rows. |
| `mismatch` | new (spec-defined, never built) | `(id, run_id, record_id, feature_id, record_value, extracted_value, evidence_span, analyst_tag, tagged_at, note)`. Written by the scorer, one row per `wrong` outcome. `analyst_tag`/`tagged_at`/`note` stay `NULL` through phase 4 and are **preserved across a re-score** (F4, R5). |
| `evaluation` | **changed** | + `min_cell_count INTEGER NOT NULL`, defaulted from `config.min_cell_count` when the draft is created (Q4). Set while the draft is editable; immutable after launch, like every other pinned input. |

**No scoring-status column anywhere.** Whether a run is scored is
`COUNT(DISTINCT feature_id)` over its `score` rows against the evaluation's
labelled-feature count — the same reasoning phase 3 F6 used to refuse a
`records_done` counter, applied again. A counter is a second source of truth
that an interrupted pass can desynchronise (F5).

**`ScoreMetric` — the closed vocabulary** (`domain/scoring.py`, frozen at
Wave 0). Rates and raw counts share the one row shape, which is why no second
table appears (F2):

| Group | Metrics |
|---|---|
| Goal 1 rates | `precision` · `recall` · `f1` |
| Goal 1 counts | `hit` · `wrong` · `missing` |
| Goal 2 | `presence_rate` · `flag_inconsistency_rate` |
| Goal 2 cross-tab | `hit_present` · `hit_absent` · `wrong_present` · `wrong_absent` · `missing_present` · `missing_absent` |
| Goal 3 | `discovery_rate` · `evidence_span_count` |

The breakdown row's Precision · Recall · F1 · Hit · Wrong · Missing is
therefore six rows of one table, not a join — and `hit`/`wrong`/`missing` are
**stored, not back-derived** from P and R, because recovering counts from three
rounded floats is exactly the kind of quiet arithmetic error §11's golden
fixtures exist to catch.

New `NewType` in `ra2/domain/ids.py`: `MismatchId`. `score` keeps the spec's
composite key and needs none.

### 3.1 Two new protocols and three tab signatures, declared at Wave 0

Same reasoning as `CensusMaterialiser` (plan-m0-m5.md E6), `EnumCodeTableProvider`
(plan-phase-2.md §3) and `PromptResolver` (plan-phase-3.md §3.1): declared once
up front so the two sides get built by different agents at the same time, and
neither waits.

```python
# ra2/services/protocols.py (amendment)
class GroundTruthProvider(Protocol):
    """A feature's true value per record, resolved from the source column or
    from the derivation catalogue, in ONE pass over the EAV tables.
    S4 implements (ground_truth_repo.py); T1 calls it — so scoring_service
    never reaches into a repository's query internals."""
    async def values_for(
        self, session: AsyncSession, corpus_id: CorpusId, feature: FeatureSpec
    ) -> Mapping[RecordId, str | None]: ...

class Scorer(Protocol):
    """'Is this run scored, and how far?' — without results_service importing
    scoring_service. T1 implements, T2 and T3 call."""
    async def status(self, session: AsyncSession, run_id: RunId) -> ScoringStatusView: ...

# ra2/ui/views/results/ (new package, signatures only at Wave 0)
def render_extraction_tab(*, view: ExtractionTabView) -> None: ...
def render_presence_tab(*, view: PresenceTabView) -> None: ...
def render_ranking_tab(*, view: RankingTabView) -> None: ...
```

The three tab signatures are what let V1, V2 and V3 build the same screen in
parallel in Wave 4 — the trick phase 2 used for
`derivation_builder`/`feature_sets_table` and phase 3 used for
`progress_card`/`ollama_settings`/`prompt_preview`.

**`ra2/ui/views/results/` is a package, not a module** — a deliberate
departure from the flat `census_view.py` / `features_view.py` pattern, recorded
as `SD20`. Three agents building three tabs of one screen need three files;
one module would make Wave 4 serial for no architectural gain. The route, the
shell and the tab strip live in the package's `__init__.py` and belong to V1.

---

## 4. The parallelisation model

Same four ideas as `plan-m0-m5.md` §1: one serial contract freeze, disjoint
file ownership, isolated worktrees, tests as the handshake. Read that section
if this is the first phase you're executing. As in phases 2 and 3, **Wave 0 may
edit any file `CONTRACTS.md` currently lists**, including ones M0, M9 and M17
froze; after it re-tags, those files are frozen again for Waves 1–4.

**Agent letters continue at `S`.** Phase 1 used A/B/C, phase 2 D/E/F/G, phase 3
H/I/K/L (skipping `J`, the journey prefix). Phase 4 skips every remaining
letter that already carries a numbered vocabulary in these documents — `M`
(milestones, and every Wave-0 agent's name), `N` (non-functional requirements),
`O` (reads as zero), `P` (deliverables), `Q` (clarifications), `R` (risks) —
and uses **S, T, U, V** (F11).

| Wave | Base | Agents | Milestones | Parallel? |
|---|---|---|---|---|
| **0** | tag `p3w4-green` (= current `main`, Q5) | 1 (lead or `p4-foundation`) | M27 | no |
| **1** | tag `p4-frozen` | 5 (S1–S5) | M28, M29, M30 | yes |
| **2** | tag `p4w1-green` | 3 (T1–T3) | M31 | yes |
| **3** | tag `p4w2-green` | 2 (U1–U2) | M32 | yes |
| **4** | tag `p4w3-green` | 3 (V1–V3) | M33 | yes |
| **after 4** | tag `p4w4-green` | lead, on the target machine | M34 | n/a |

Fourteen agent runs including Wave 0 — the same size as phase 3, and for a
different reason: phase 3 was large because it built a worker and an adapter;
phase 4 is large because **three of its five Wave-1 agents build things phase 2
and phase 3 deferred** (P39, P40, P38).

---

## 5. Wave 0 — contract freeze

One agent, serial. Reads `mvp-spec.md` §5/§8/§11/§12, **`design/results/README.md`
in full**, and — if the lead has not already drafted it — writes
**`sw-design.md` §16** before writing any code (§0).

### 5.1 Deliverables

- **`sw-design.md` §16**, settling §0's ten items, plus `SD16`–`SD22` in §13.
  **This is the deliverable the rest of the phase rests on**; everything below
  transcribes it.
- **§2.4's document corrections** — `mvp-spec.md` §5/§11.4/§11.5, `CLAUDE.md`,
  `CONTRACTS.md`. `pyproject.toml` and `.importlinter` are deliberately
  untouched, and the §5.3 gate checks that they *stayed* untouched.
- **`ra2/domain/ids.py`** — `MismatchId`.
- **`ra2/domain/stats.py`** *(new, frozen after this wave)* — `Interval`,
  `TieMark`, and the **signatures** of `wilson`, `suppressed`, `mark_ties`,
  `macro`. Bodies are S1's.
- **`ra2/domain/ranking.py`** *(new, frozen)* — `ModelRanking`,
  `SeparatingFeature`, and the signatures of `rank_models` and
  `separating_features`. Bodies are S1's.
- **`ra2/domain/matching.py`** *(new, frozen)* — the signatures of
  `normalise(value, value_type, rule)` and `matches(record, model, value_type,
  rule)`. Bodies are S2's.
- **`ra2/domain/scoring.py`** *(new, frozen)* — `Outcome` (`hit`/`wrong`/
  `missing`), **`ScoreMetric`** (§3's closed vocabulary), `LabelledCase`,
  `FeatureScore`, `CrossTab`, and the signatures of `classify`,
  `aggregate_goal1`, `aggregate_goal2`, `aggregate_goal3`. Bodies are S2's.
- **`ra2/domain/derivation.py`** *(new, frozen)* — `RecordProjection` (the
  pure, session-free shape a record's objekt/person cells arrive in) and the
  signature of `evaluate(derivation, projection)`. Bodies are S3's.
- **`ra2/persistence/models.py` (amendment)** — `Score`, `Mismatch`, and
  `Evaluation.min_cell_count`.
- **`ra2/services/protocols.py` (amendment)** — `GroundTruthProvider`,
  `Scorer` (§3.1).
- **`ra2/services/container.py` (amendment)** — `scoring: ScoringService`,
  `results: ResultsService`, `ranking: RankingService`.
- **`ra2/services/errors.py` (amendment)** — `RunNotScoredError`,
  `RunNotScoreableError` (a `failed`/`interrupted` run, or one whose evaluation
  has no labelled features). **No new `FindingCode`s** — a suppressed cell and
  an unscoreable feature are *rendered states*, not import defects, and
  `Do-NOT #6` is about rows silently repaired or dropped during ingest. Phases 2
  and 3 set this precedent twice.
- **`ra2/services/readmodels.py` (amendment)** — `ExtractionTabView`,
  `FeatureScoreRow`, `ModelCellView`, `BreakdownView`, `ByLanguageView`,
  `ExploratoryRow`, `PresenceTabView`, `PresenceRow`, `CrossTabView`,
  `FlagInconsistencyRow`, `PerRecordRow`, `RankingTabView`, `RankingRow`,
  `SeparatingRow`, `ScoringStatusView`, `RunDescriptorView` (the
  corpus + record count + model count + `cfg` chip + dev marker every tab
  carries).
- **`ra2/services/export_service.py` (amendment)** — the
  `presence_records_csv(...)` signature (C11); body is T2's.
- **`ra2/infra/config.py`** — **unchanged**. `min_cell_count` already exists
  and now serves as the per-evaluation default, not as the value itself.
- **`ra2/api/schemas.py`**, **`ra2/api/v1/router.py`**, **`ra2/api/deps.py`**
  (amendments) — request/response models, the new routers, and
  `ScoringServiceDep` / `ResultsServiceDep` / `RankingServiceDep`.
- **`ra2/main.py` (amendment)** — construct the three services, each as a
  **defaulted keyword argument** so tests substitute without a test-mode branch
  (`Do-NOT #12`).
- **New stubs** — `ra2/services/{scoring,results,ranking}_service.py`,
  `ra2/persistence/repositories/{score,mismatch,ground_truth}_repo.py`,
  `ra2/api/v1/{results,presence,ranking}.py`,
  `ra2/ui/views/results/{__init__,extraction_tab,presence_tab,ranking_tab}.py`,
  `ra2/ui/components/{stat_cells,contingency_table}.py`: constructors and typed
  signatures, bodies `raise NotImplementedError`.
- **One migration — the real one, not an empty stub**, for the same reason
  phase 3's Wave 0 needed one: this wave **alters `evaluation`**, so the moment
  `models.py` declares `min_cell_count`, every phase-2 and phase-3 test that
  seeds an evaluation row fails with `no such column`. It creates `score` and
  `mismatch` and adds the column, with a server default so existing rows
  migrate. **S4 remains phase 4's one migration author** for anything Wave 1
  adds on top. Recorded in `CONTRACTS.md`.
- **`P3-D15`'s inherited obligation (P51), as its own commit.** Phase 3's
  deviation register closes with an instruction to this phase: *"Phase 4
  should do it as its own commit with the full suite as the check, and delete
  both helpers."* `Clock.now()` is always aware; SQLite's
  `DateTime(timezone=True)` has nowhere to keep the offset and returns the
  value naive, so subtracting two stored timestamps raises — and I2 and I3 hit
  it independently at the end of phase 3 and wrote near-identical private
  `_as_utc` helpers. It belongs a layer down, as a SQLAlchemy `TypeDecorator`
  on the column type: same storage, **no migration**. Phase 3 declined to do it
  mid-wave because it changes how every timestamp in the app loads, including
  the byte-asserted golden import report. **Wave 0 is the only place it can
  happen** — `models.py` is frozen for Waves 1–4 and no other wave owns it.
  Its own commit, the full suite as the check, both helpers deleted.
  *(This deliverable was missing from the plan as first written; added here in
  the same commit, per `CLAUDE.md`.)*
- **`tests/test_p4_contract.py`** *(new, lead-owned)* — this wave's exit
  criteria as tests, in the shape of `test_m0_contract.py`, `test_p2_contract.py`
  and `test_p3_contract.py`: every file §5.1 freezes carries its `# FROZEN`
  header, is listed in `CONTRACTS.md`, and imports cleanly. A Wave 1+ agent
  should never need to touch it; a failure there means a frozen contract was
  edited without an amendment.
- **`ra2/ui/shell.py`** — **untouched.** The `results` `NavItem` already exists
  with `built=False` and its `TABLE` icon already wired (phase 1). V1 flips one
  flag (§6.1).

### 5.2 Exit criteria

- `just lint && just test` green with the new stubs raising
  `NotImplementedError`; **every phase-1, phase-2 and phase-3 test still
  green** — this wave adds surface, it does not change behaviour.
- `alembic upgrade head` runs the new migration cleanly on a fresh DB **and**
  on one already at `p3w4-green`, with existing `evaluation` rows acquiring
  `min_cell_count = 20`.
- `CONTRACTS.md` lists every file this wave touched; each carries
  `# FROZEN — see CONTRACTS.md` where the convention applies.
- `tests/test_p4_contract.py` green.
- `import-linter` green with **no contract changes** — and a test asserting
  `pyproject.toml`'s dependency list is unchanged from `p3w4-green` (F10 is
  only a decision until something checks it).
- J4, J5 and J6 green, **unchanged** — the nav is already eight items; this is
  the first phase since M0 that adds none.

### 5.3 Review gate

The lead reads **line by line** before tagging `p4-frozen`: `sw-design.md`
§16 in full, `models.py`'s diff, `domain/scoring.py`'s `ScoreMetric`, and the
migration. Three things get a second look specifically:

1. **`sw-design.md` §16 itself.** It is the artefact phase 3 had and this phase
   had to write. If it is thin, five Wave-1 agents invent five architectures.
2. **`ScoreMetric`'s closed vocabulary** (§3, F2). Every number on all three
   tabs is a row with one of these names. A metric missing here is a schema
   change in Wave 2, and a metric that means two things is a wrong number
   nobody notices.
3. **The §8.6 denominator rule**, wherever it appears in §16 and in
   `domain/scoring.py`'s signatures. "An empty source column leaves the
   denominator entirely" is one sentence and three plausible wrong readings —
   as a `missing`, as a zero, as a suppressed cell. All three produce numbers.

---

## 6. File ownership matrix

| Path | W0 | W1 | W2 | W3 | W4 |
|---|---|---|---|---|---|
| `sw-design.md` `mvp-spec.md` `CONTRACTS.md` `CLAUDE.md` | M27 | 🔒 | 🔒 | 🔒 | 🔒 |
| `tests/test_p4_contract.py` `tests/conftest.py` | M27 | 🔒 | 🔒 | 🔒 | 🔒 |
| `pyproject.toml` `.importlinter` | **untouched** | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/domain/ids.py` | M27 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/persistence/models.py` | M27 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/services/{protocols,container,errors,readmodels,export_service}.py` | M27 | 🔒 | 🔒 *(export body: T2)* | 🔒 | 🔒 |
| `ra2/api/{schemas,deps,v1/router}.py` `ra2/main.py` | M27 | 🔒 | 🔒 | 🔒 | 🔒 |
| `ra2/ui/shell.py` `ra2/ui/components/icons.py` | untouched | 🔒 | 🔒 | 🔒 | 🔒 *(the one-line exception, §6.1)* |
| `ra2/domain/{stats,ranking}.py` *(bodies)* | M27 stub | **S1** | 🔒 | 🔒 | 🔒 |
| `ra2/domain/{matching,scoring}.py` *(bodies)* | M27 stub | **S2** | 🔒 | 🔒 | 🔒 |
| `ra2/domain/derivation.py` *(bodies)* | M27 stub | **S3** | 🔒 | 🔒 | 🔒 |
| `ra2/persistence/repositories/{score,mismatch,ground_truth}_repo.py`, `migrations/versions/**` | M27 *(the phase-4 revision, written in full)* | **S4** | 🔒 | 🔒 | 🔒 |
| `ra2/ui/components/{stat_cells,contingency_table}.py` *(bodies)*, `primitives.py` *(additions)* | M27 stub | **S5** | 🔒 | 🔒 | 🔒 |
| `ra2/services/scoring_service.py` | M27 stub | 🔒 | **T1** | 🔒 | 🔒 |
| `ra2/services/results_service.py` | M27 stub | 🔒 | **T2** | 🔒 | 🔒 |
| `ra2/services/ranking_service.py` | M27 stub | 🔒 | **T3** | 🔒 | 🔒 |
| `ra2/api/v1/results.py` | M27 stub | 🔒 | 🔒 | **U1** | 🔒 |
| `ra2/api/v1/{presence,ranking}.py` | M27 stub | 🔒 | 🔒 | **U2** | 🔒 |
| `ra2/ui/views/results/{__init__,extraction_tab}.py`, `ui/state.py` *(additions)* | M27 stub | 🔒 | 🔒 | 🔒 | **V1** |
| `ra2/ui/views/results/presence_tab.py` | M27 stub | 🔒 | 🔒 | 🔒 | **V2** |
| `ra2/ui/views/results/ranking_tab.py` | M27 stub | 🔒 | 🔒 | 🔒 | **V3** |
| `tests/unit/stats/**`, `tests/fixtures/scoring/golden_stats.json` | — | **S1** | | | |
| `tests/unit/matching/**`, `tests/unit/scoring/**` | — | **S2** | | | |
| `tests/unit/derivation/**` | — | **S3** | | | |
| `tests/backend/persistence/test_{score,mismatch,ground_truth}_repo.py`, migration tests, `tests/fixtures/scored_corpus.py`, `tests/fixtures/scoring/hazards/**` | — | **S4** | | | |
| `tests/ui/test_components.py` *(additions)* | — | **S5** | | | |
| `tests/backend/services/scoring/**` | — | | **T1** | | |
| `tests/backend/services/results/**` | — | | **T2** | | |
| `tests/backend/services/ranking/**` | — | | **T3** | | |
| `tests/backend/api/results/**` | — | | | **U1** | |
| `tests/backend/api/{presence,ranking}/**` | — | | | **U2** | |
| `tests/ui/test_results_extraction.py`, `tests/e2e/test_j11_results_extraction.py` | — | | | | **V1** |
| `tests/ui/test_results_presence.py`, `tests/e2e/test_j12_results_presence.py` | — | | | | **V2** |
| `tests/ui/test_results_ranking.py`, `tests/e2e/test_j13_ranking_consistency.py` | — | | | | **V3** |

🔒 = frozen for that wave; amendment only. Per-layer conftests follow phase 1's
rule: owned by whoever owns that layer in that wave; only `tests/conftest.py`
stays lead-owned. **`tests/fixtures/scored_corpus.py` is the phase's
`fake_llm.py`** — six later agents build on it, so it earns a root fixture in
`tests/conftest.py`, declared by Wave 0 and filled by S4.

### 6.1 The one-line nav exception

Phase 3 declared this for two agents (`plan-phase-3.md` §6.1) after phase 2
paid for leaving it implicit. Phase 4 needs it for **one**: `results` already
exists as a `NavItem` with `built=False`, and `ra2/ui/views/__init__.py`
carries one `register()` call per built view.

**V1 may flip exactly the `results` `built` flag and add exactly its own line
to `register_all`.** Nothing else in either file. V2 and V3 touch neither —
they render into V1's tab shell. There is no merge conflict this phase, which
is the whole point of saying so in advance.

---

## 7. Wave 1 — domain, persistence, component kit

Base tag `p4-frozen`. Five agents, isolated worktrees. **Three of the five
build things earlier phases deliberately deferred** — read each brief's opening
line for which promise it is keeping.

### S1 — `feat/p4-stats` · the statistics *(M, opus)*

*Keeps no earlier promise — this is new, and it is the phase's highest-risk
pure code: a wrong interval does not crash, it lies.*

**Build:** `domain/stats.py` and `domain/ranking.py` bodies.
- `wilson(successes, n, z=1.959963985) -> Interval` — the Wilson score
  interval, written out. `n = 0` returns an explicit empty interval, never a
  `ZeroDivisionError` and never `(0, 0)`.
- `suppressed(n, floor) -> bool` — `n < floor`, with `floor` **passed in** from
  the evaluation (Q4), never read from config inside a pure function.
- `mark_ties(cells) -> tuple[TieMark, ...]` — `best` for the highest point
  estimate **only if no rival's interval overlaps it**; every overlapper
  (including the leader) becomes `tied`; everything else `none`. The design
  README's vocabulary exactly: "Ties are shown as ties. No strict order is
  implied."
- `macro(scores) -> float` — the unweighted mean over **non-suppressed**
  features. A suppressed feature is excluded; it is never a zero.
- `rank_models(...)` — shared ranks on overlapping macro intervals
  (`1, 1, 3` — never `1, 2, 3`), and `separating_features(...)` — the features
  where the top two models' intervals do not overlap.

**Fixtures** (`tests/fixtures/scoring/golden_stats.json`, committed): every
Wilson bound, F1, macro and rank in the design README's eight fixture rows,
**computed independently in the generator and committed as expected values**.
The generator is committed beside them, in the `generate_*_hazards.py`
tradition.

**Exit:** the golden file asserted to 3 decimals against `wilson`/`macro`
(these are the numbers on the screen, and this is the only test in the project
that would catch them drifting); property tests — a Wilson interval always
lies within `[0, 1]` and always brackets `successes / n`; `mark_ties` never
marks two **disjoint** intervals as tied and never returns zero `best` marks
for a non-empty input; `macro` over a set where every feature is suppressed
raises rather than returning `0.0`; `rank_models` on three mutually
overlapping models returns `1, 1, 1`.

### S2 — `feat/p4-matching` · matching and classification *(L, sonnet)*

*Keeps `plan-phase-2.md`'s promise by implication: phase 2 stored the
`MatchingRule` shape and never compared two values with it.*

**Build:** `domain/matching.py` and `domain/scoring.py` bodies.
- `normalise(value, value_type, rule)` — `mvp-spec.md` §8.4's table, all seven
  types: `enum` none (codes compared), `integer` strip separators, `decimal`
  parse and round to the rule's precision, `date` `YYYYMMDD` → ISO, `time`
  `HH:MM` → minutes with the rule's optional tolerance, `boolean` truthy
  mapping, `free_text` NFKC → casefold → collapse whitespace → strip edge
  punctuation.
- `matches(...)` — exact on the normalised form. **No fuzzy anything** (`D6`).
- `classify(record_value, model_value) -> Outcome | None` — `hit` / `wrong` /
  `missing` per §11.1, and **`None` when the record value is empty**: §8.6's
  rule, expressed as a return value the caller cannot accidentally count.
- `aggregate_goal1` / `aggregate_goal2` / `aggregate_goal3` — the labelled
  cases of one `(run, feature[, language])` into `ScoreMetric` rows, including
  the six cross-tab cells and the flag-inconsistency count
  (`present = false` **and** the extracted value matched).

**Exit:** one named test per value type, each including its hazard — a French
record whose text is already cp1252-lossy (`h09`'s philosophy applied to a
value), a decimal at the rounding boundary, a time at the tolerance boundary,
a `free_text` pair differing only in edge punctuation and one differing only in
an accent (**must not match** — accent-folding is explicitly *not* in §8.4's
free-text chain); an empty record value returns `None` from `classify` and is
asserted **absent from the denominator** in `aggregate_goal1`, not present as a
`missing`; the flag-inconsistency count reproduces the design's "114" cell
semantics from hand-built cases.

### S3 — `feat/p4-derivation` · the derivation evaluator *(M, sonnet)*

*Keeps `plan-phase-2.md` **Q1**'s promise verbatim: "Store `derivation_json`
only… scoring (phase 3) needs to build one anyway — building it twice is
waste." Phase 3 did not need it. Phase 4 does, and this is the bill.*

**Build:** `domain/derivation.py` bodies — `evaluate(derivation, projection)`
over the closed 7-type catalogue (`count_objects`, `count_persons`,
`any_object_matches`, `any_person_matches`, `max_ordinal`, `min_ordinal`,
`distinct_count`) and the 6 operators (`eq`, `ne`, `in`, `not_in`, `is_empty`,
`is_not_empty`). Pure: it takes a `RecordProjection` — a plain mapping of the
record's objekt and person cells — and returns a value. **No session, no
repository, no query.** S4 builds the projection; S3 never sees a database.

**Exit:** one test per catalogue type × a filtered and an unfiltered case;
`count_*` over a record with **zero** objects returns `0`, and that `0` is a
real labelled value, not an empty cell (the §8.6 distinction that decides
whether the record is in the denominator — this is the single most consequential
line in the agent's brief); `max_ordinal`/`min_ordinal` over a code absent from
the `ordered_code_list` is a typed error, not a silent skip; an unknown
operator is impossible by construction (the enum), asserted; a property test
that `evaluate` never raises on an arbitrary projection.

### S4 — `feat/p4-persistence` · migration, repositories, the ground-truth query *(L, opus)*

**One migration author, one per phase — S4 for phase 4** (`CLAUDE.md`, as
amended at Wave 0). Nobody else runs `alembic revision`.

**Build:** `score_repo` (write a feature's rows in one commit; read a run's
rows; **delete-and-rewrite one feature's rows on re-score**), `mismatch_repo`
(bulk write per feature; **upsert that preserves `analyst_tag`, `tagged_at`
and `note`** on a re-score, keyed on `(run_id, record_id, feature_id)` —
R5), and `ground_truth_repo` implementing `GroundTruthProvider`: **one pass**
over `unfall_row` for a native feature, and one pass over
`objekt_row`/`objekt_cell`/`person_row`/`person_cell` assembling a
`RecordProjection` per record for a derived one. Verify M27's migration and add
its own revision on top if Wave 1 needs more — no parallel heads.

Also **`tests/fixtures/scored_corpus.py`** and
`tests/fixtures/scoring/hazards/` — the phase's `fake_llm.py` (§6). The hazard
set, synthesised and committed, in the `h01`–`h14` / `c01`–`c05` / `p01`–`p07`
tradition:

| | Hazard |
|---|---|
| `s01` | a feature at **n = 17** — below the floor, suppressed, and excluded from macro and from tie counting |
| `s02` | two models whose intervals **overlap** — a tie |
| `s03` | two models whose intervals **do not** — a separating feature |
| `s04` | an **all-empty** source column — leaves the denominator entirely (§8.6); the feature is unscoreable, not zero-scored |
| `s05` | a record whose French text is cp1252-lossy, in a language breakdown |
| `s06` | an extracted enum value **outside** the evaluation's snapshotted codelist |
| `s07` | `present = false` **and** the value matched — the flag-inconsistency / "114" case |
| `s08` | a `null` value carrying a **non-null** evidence span |
| `s09` | a **derived** feature over a record with zero objects (S3's `0`-versus-empty distinction, seen from the database) |

**Exit:** `alembic upgrade head` clean on a fresh DB **and** on a DB at
`p3w4-green`, with existing evaluations acquiring `min_cell_count`;
`alembic check` clean; a round-trip test per repository; **the re-score
preservation test** — write a mismatch, tag it by hand, re-score the feature,
assert the tag survived and the derived columns were rewritten; the
ground-truth query asserted to issue a **bounded** number of statements for a
1 000-record corpus (not one per record — R4), with the count asserted, not
eyeballed.

### S5 — `feat/p4-components` · the statistical cells *(S, sonnet)*

**Build:** the primitives the three tabs need and `primitives.py` lacks, per
the design README's class list — the **`.mk` tie marker** (7×7, `border-radius:2px`,
`margin-right:6px`; filled = best, 1.5px outline = tied, empty = neither —
**shape-coded, neutral-inked**, Q6), the **`.val` / `.ci` pair** (point estimate
over a mono 10.5px interval line, `padding-left:13px` so the interval aligns
under the value), the **`.ins` insufficient-data chip**, the **tab strip**
(the `.tab` / `.tab.on` class pair, whose active underline sits on the strip's
own bottom border via `margin-bottom:-11px`), the **contingency table** (3×3
with row and column totals, and one cell styleable as *the finding*), and the
**suppressed-row treatment** (`oklch(0.985 0.002 260)` tint + a `colspan` note).
Extend, don't replace: `card`, `card_header`, `bar`, `pill`, `pagination_row`,
`footnote` all exist and all three tabs reuse them as-is. **Do not introduce a
second table scale** — `.th` mono 10px uppercase, `.td` 12.5px, ~8×12px
padding, 24×24 pagination buttons, 42–46px card headers, everywhere.

**Exit:** `tests/ui/test_components.py` gains one case per new primitive; the
marker's three states are asserted **structurally** (fill / border / neither),
not by colour, so Q6 cannot be quietly reverted; the tab strip's active
underline is asserted to sit on the strip border; a resize test asserts the
wide-table wells keep their `min-width` (738px Goal 1, 900px Ranking, 560px
the differ card) inside `overflow:auto` and that the page body never scrolls
horizontally (mirrors J4 and phases 2/3's component agents).

---

## 8. Wave 2 — services

Base tag `p4w1-green`. Three agents. This is the wave `GroundTruthProvider` and
`Scorer` (§3.1) exist for: T2 and T3 build against **seeded** `score` rows from
S4's `scored_corpus` fixture and never wait for T1.

### T1 — `feat/p4-scoring-service` *(L, opus)*

**Build:** `scoring_service.py` — `score_run(run_id)`: for each labelled
feature of the run's evaluation, resolve ground truth through
`GroundTruthProvider`, classify every labelled case through `domain/scoring.py`,
aggregate through `domain/stats.py`, and **commit that feature's `score` rows
and `mismatch` rows in one transaction** — the boundary that makes the pass
restartable, exactly as `UNIQUE (run_id, record_id)` did for extraction.
`resume` is implicit: the features with no `score` rows are the work left.
Chained automatically off the run worker's terminal `done` (Q3);
`rescore_run(run_id)` is the explicit path and **preserves analyst tags**.
`status(run_id)` implements `Scorer`. A `failed` or `interrupted` run raises
`RunNotScoreableError` and is never scored.

**Exit:** the headline test — **kill the pass mid-evaluation and resume it**:
score with a provider that raises after N features, re-enter, assert every
labelled feature has exactly one complete set of `score` rows and no feature
was scored twice; scoring the **same run twice** produces byte-identical
`score` rows (determinism — the inputs are immutable, so anything else is a
bug); a re-score after a hand-applied `analyst_tag` preserves it (R5);
per-language rows and the all-languages row are written from **one** pass over
the cases, and the all-languages `n` equals the sum of the per-language `n`s;
a feature whose source column is entirely empty produces **no** `score` rows at
all rather than rows of zeros (§8.6, `s04`); `min_cell_count` is read from the
**evaluation**, and suppression is **not** applied at write time — every cell
is stored, suppression is a render-time rule over stored `n` (so lowering the
floor never needs a re-score).

### T2 — `feat/p4-results-service` *(L, opus)*

**Build:** `results_service.py` — the read models for tabs 1 and 2.
Tab 1: the per-feature × model table with **sorting and pagination**
(suppressed rows sort **last, never as 0** — R7), the per-model breakdown
(P · R · F1 · hit · wrong · missing), by-language for one feature × model, and
the Goal 3 exploratory rows with their evidence-span counts. Tab 2: presence
rate per feature × language, the cross-tab, flag inconsistency per model, and
the per-record output list with paging. Plus `presence_records_csv` in
`export_service.py` (C11) — UTF-8 with BOM, `;`, the header comment, the
currently filtered and sorted rows only.

Every view carries the `RunDescriptorView`: corpus label, record count, model
count, `cfg` chip, and the **dev marker** — `mvp-spec.md` §13's "required on
every dev-sized result: the 'smoke test, not a result' marker", which on these
boards replaces the "Evaluation run" pill rather than sitting beside it.

**Exit:** suppression is applied **here**, from stored `n` against the
evaluation's `min_cell_count`, and a suppressed cell returns a typed
"insufficient data" shape carrying its `n` — never a number and never `None`;
sorting by every model column is tested, with suppressed rows last in **both**
directions; a Goal 2 view **never** returns presence numbers without the Goal 1
F1/P/R beside them (§11.2 — asserted as a shape invariant, so it cannot be
dropped by a later refactor); the CSV round-trips byte-wise including the BOM
and respects the active filter and sort; an unscored run yields the
`not scored yet` state, not an empty table (C9).

### T3 — `feat/p4-ranking-service` *(M, sonnet)*

**Build:** `ranking_service.py` — tab 3's read model, **derived strictly from
the same `score` rows T2 reads**, through `domain/ranking.py`. Macro F1 with
its interval, best/tied/worse counts from the tie marks, shared ranks,
separating features, and the *reported-never-scored* group: median latency
(from `extraction.latency_ms`), prompt tokens (summed), VRAM (from the
evaluation's `selected_models_json`, which is why the design insists it "must
agree with the model sub-line"), and the **macro presence rate** (C8, F8).
Plus the verdict line — "Two models are tied at the top. This run does not
separate them." — composed from the computed ranks, never authored.

**Exit:** the invariant test — **the ranking's macro F1 equals the mean of the
per-feature F1s that tab 1 renders**, computed by calling T2's read model and
T3's independently and comparing (this is the design README's "if the two
disagree, Ranking is wrong by construction", made mechanical); suppressed
features are excluded from the macro **and** from the best/tied/worse counts,
and the counts sum to the scored-feature count for every model; three
mutually-tied models rank `1, 1, 1` and the verdict says so; the presence rate
is asserted **absent** from every rank computation — change it and the ranking
must not move.

---

## 9. Wave 3 — API v1

Base tag `p4w2-green`. Two agents; thin routers, no ORM object crosses the
boundary — the same rule as phase 1's C1/C2, phase 2's F1/F2 and phase 3's
K1/K2.

- **U1 — `feat/p4-api-results`**: `GET /api/v1/evaluations/{id}/results`
  (tab 1's table, with `sort`, `page`, `page_size`),
  `…/results/{feature_id}/breakdown`, `…/results/{feature_id}/by-language`,
  `…/results/exploratory`, plus `GET …/scoring-status` and
  `POST /api/v1/runs/{id}/rescore`. *Exit:* every endpoint tested through
  `httpx.ASGITransport`; an **unscored** run returns **200 with a
  `scored: false` status**, not a 404 — the UI renders a state, and an error
  status would make that a toast (the phase-3 K2 precedent for an unreachable
  endpoint); a suppressed cell serialises as its typed insufficient-data shape,
  and a test asserts the JSON **never** carries a number for it; re-scoring a
  `failed` run returns 409; OpenAPI snapshot regenerated with the diff in the PR.
- **U2 — `feat/p4-api-presence-ranking`**: `GET …/presence`,
  `…/presence/cross-tab`, `…/presence/flag-inconsistency`,
  `…/presence/records` (paged), `…/presence/records.csv`, and
  `GET …/ranking`. *Exit:* the presence endpoints refuse to serialise a
  presence figure without its Goal 1 companions (§11.2, asserted at the schema
  level); the CSV endpoint streams bytes with the BOM and honours filter and
  sort; `…/ranking` on a run where every feature is suppressed returns a
  well-formed "nothing scoreable" payload rather than an empty list that the UI
  would render as a blank table; OpenAPI snapshot in the PR.

---

## 10. Wave 4 — the Results view

Base tag `p4w3-green`. Three agents, one screen, three tabs, disjoint files —
made possible by the tab signatures Wave 0 declared (§3.1). The one-line nav
exception is §6.1 and belongs to V1 alone.

**The copy is the design.** `design/results/README.md` says so in its Fidelity
note, and it means it: the suppression notices, the Goal 2 scope banner, the
encoding caveat, the Goal 3 footer and the tie legend are *the product's
honesty guarantees*. Every one of them is reproduced **verbatim** and asserted
verbatim (R8). Findings-style wording tables do not apply here — this is UI
copy, and it lives in `ui/` where the rendering table already lives.

### V1 — `feat/p4-results-extraction` · the shell and Goal 1 *(L, opus)*

**Build:** `ui/views/results/__init__.py` — the `/results` route, the
evaluation resolution (C7: `?evaluation=<id>`, the index card when absent), the
header, the **tab strip**, and the `RunDescriptorView` line that "every tab must
carry" — corpus + records + models, the run pill (or the `DEV · smoke test, not
a result` marker), and the `cfg` chip. Then `extraction_tab.py` — the primary
per-feature × model table in its 738px `overflow:auto` well, the `.mk` markers
and the tie legend, the **expandable breakdown row** (one open at a time,
`colspan`, the accent-soft tint, and the "Hallucination is *not* computed" note
per C10), the suppressed-row treatment, the pagination row, and the two cards
below — "By language" with its **verbatim** encoding caveat, and "Goal 3 —
Exploratory" with its `no ground truth · not ranked` header and its **verbatim**
footer. State via `app.storage.client` (active tab, expanded feature, page,
sort) — no module globals (`Do-NOT #8`).

**Exit:** `tests/ui/test_results_extraction.py` covers the three marker states,
the suppressed row (rendered as the notice, carrying its `n`, with all three
model cells replaced by one `colspan`), the breakdown expand/collapse
one-at-a-time rule, sorting with suppressed rows last in both directions, and
both caveat footers **asserted verbatim**;
`tests/e2e/test_j11_results_extraction.py` (**J11**, new): seed a scored
evaluation through the API, open Results, expand a breakdown, sort by a model
column, and assert the `s01` feature renders its notice and **never a number**.

### V2 — `feat/p4-results-presence` · Goal 2 *(L, opus)*

**Build:** `ui/views/results/presence_tab.py` — the **non-dismissible scope
banner** (verbatim, C4: "There is no gold label for presence… `Presence
precision / recall / F1 are deferred` until a human-labelled subset exists"),
the one-model-at-a-time chip row, the presence rate table whose **last column
is the Goal 1 F1 and whose header says it is never shown apart** (§11.2, and
the column is not optional — it is the guarantee), the Windows-1252 caption,
the cross-tab card with its self-contradiction cell **styled as the finding**,
the flag-inconsistency card, and the per-record output list — *"the actionable
form of Goal 2"*, paginated, with its `anonymised` chips and its CSV export.

**Exit:** `tests/ui/test_results_presence.py` asserts the scope banner
verbatim and non-dismissible; switching the model chip re-renders **every**
number on the tab; a presence cell below the floor renders the `.ins` chip with
its `n`; the Goal 1 column is asserted **present on every row** (a test that
fails if a later change drops it); the per-record list paginates and its CSV
export downloads with the BOM; `tests/e2e/test_j12_results_presence.py`
(**J12**, new): open the tab, switch models, export the CSV, and assert the
exported row count matches the rendered "N records where … is recorded but not
written" descriptor.

### V3 — `feat/p4-results-ranking` · Ranking *(M, sonnet)*

**Build:** `ui/views/results/ranking_tab.py` — the verdict banner (composed,
never authored), the ranking table in its 900px well with **repeated rank
numbers for tied models** (`1, 1, 3` — never `1, 2, 3`), the `.bar` macro-F1
cell, the best/tied/worse triple, the reported-never-scored columns (latency,
VRAM, **presence rate** — C8), the tinted rank-1 rows, "Where they actually
differ" in ranking order with its Δ column and its plain-sentence readings, and
"How this ranking is computed" — the four numbered rules and the
`--warn-soft` validity footer naming the `cfg` hash and the corpus.

**Exit:** `tests/ui/test_results_ranking.py` asserts tied models repeat their
rank; the four rules and the validity footer render verbatim with the **real**
`cfg` and corpus interpolated; a run with two tied leaders renders the tie
verdict, and one with a clear leader renders the other;
`tests/e2e/test_j13_ranking_consistency.py` (**J13**, new) — the phase's
keystone assertion: **read the macro F1 off the Ranking tab, read the
per-feature F1s off the Extraction tab, and assert the first is the mean of the
non-suppressed second**, in the browser, against the same seeded evaluation.
The design README's invariant, proven where a user would see it break.

---

## 11. Testing — cross-cutting summary

Every agent above owns its own test paths (§6); this is the "does it all still
add up" view over the gates `mvp-spec.md` §15 / `sw-design.md` §11 already
establish.

| Layer | New in this phase |
|---|---|
| **Unit** | `domain/stats.py` + `domain/ranking.py` (S1), `domain/matching.py` + `domain/scoring.py` (S2), `domain/derivation.py` (S3) — pure, no I/O, no network. **This is the largest pure-domain surface any phase has added**, and it is where the phase's risk lives |
| **Backend** | three repositories and the migration from a phase-3-shaped DB (S4), three services (T1–T3), five routers' worth of endpoints (U1, U2) |
| **Frontend** | `test_components.py` additions (S5), one test module per tab (V1, V2, V3) — NiceGUI `User` fixture, unchanged |
| **E2E** | **J11** (Extraction: suppression, markers, breakdown, sort), **J12** (Presence: model switch, Goal 1 companions, CSV) and **J13** (Ranking consistency — the cross-tab invariant in the browser) join J1–J10. J4/J5/J6 are **unchanged**: the nav already has eight items |
| **Fixtures** | `tests/fixtures/scoring/golden_stats.json` (S1) — hand-computed statistics, the only defence against silent arithmetic drift; `tests/fixtures/scoring/hazards/s01`–`s09` + `tests/fixtures/scored_corpus.py` (S4) — the phase's `fake_llm.py`, which six later agents build on |
| **Eval** | **Unchanged.** `tests/eval` stays phase 3's (M26, still open — Q5, R10). Scoring adds no eval case: adherence is a phase-3 property and accuracy against a baseline needs the human-labelled subset that is explicitly deferred |

**The new test kind this phase introduces is the golden-numbers fixture.**
Every prior phase asserted *structure* — a row exists, a flag is set, a file is
byte-identical. This phase asserts **arithmetic**, and a wrong Wilson bound or a
mis-marked tie produces no exception, no failing assertion anywhere else, and a
screen full of plausible numbers. `golden_stats.json` — expected values computed
independently in a committed generator — is the only layer that would catch it.
Treat a diff to it the way H2's golden JSON Schema snapshot is treated: **part
of the PR, never a silent regeneration** (R2).

**Three invariants get their own named tests** because each is a one-line rule
with a plausible wrong reading that still produces numbers:

1. **An empty source column leaves the denominator entirely** (§8.6) — not a
   `missing`, not a zero, not a suppressed cell. Tested in S2 (`classify`
   returns `None`), S3 (`0` objects is a *value*, an empty column is not), T1
   (no `score` rows at all) and V1 (the row is absent, not blank).
2. **A suppressed cell is never a number** — tested at S1, T2, U1 and V1, i.e.
   at every layer it could leak through, including the JSON.
3. **Suppressed rows sort last, never as 0** (R7) — T2 and V1, in both sort
   directions.

**No live endpoint, no GPU, anywhere in layers 1–4** — unchanged from phase 3,
and easier here: scoring reads committed `extraction` rows, so nothing in this
phase needs a model at all. `just test` and `just e2e` must pass on a machine
with nothing listening on 11434. **J6 is untouched**: the browser still talks
only to the server under test, and this phase opens no socket.

No change to the five gates in `sw-design.md` §11.7. Coverage stays scoped to
`ra2/domain` + `ra2/services` at `fail_under = 85` — which this phase makes
*easier* to hold, not harder: five new pure modules are the cheapest coverage
in the project, and if the number moves the wrong way it is a signal that logic
leaked into a service that should have stayed in `domain/`.

---

## 12. Integration protocol

Identical to `plan-m0-m5.md` §8, `plan-phase-2.md` §12 and `plan-phase-3.md`
§12: per branch, in dependency order, check `git diff --name-only
<base>..<branch>` against §6, apply or defer any
`contracts/amendments/<branch>.md`, merge, run `just lint && just test` **on
the merged tree**, resolve or name-as-follow-up any `xfail`. After the last
branch of a wave: `just e2e`, tag, spawn the next wave.

Dependency order per wave (leaf-most first):

- **Wave 1** — S5 (nothing depends on it), then S1, S3, S2, S4 last (its
  migration is the file most likely to need a rebase, and the cheapest one to
  rewrite — the same reasoning that put H3 last).
- **Wave 2** — T1 (writes the rows), then T2, then T3 (which must be checked
  against T2's output, not only against its own fixtures).
- **Wave 3** — U1, then U2.
- **Wave 4** — V1 (the shell and the tab strip the other two render into),
  then V2, then V3. V1 is also the only agent touching `shell.py` and
  `views/__init__.py` (§6.1), so there is no nav conflict to resolve.

Manual verification of any merged tree runs **`just dev-agent`, never bare
`just dev`** (`CLAUDE.md`).

---

## 13. Milestone coverage

| Milestone | Delivered by | Exit criteria met at |
|---|---|---|
| M27 Contract freeze **+ `sw-design.md` §16** (§0) | Wave 0 lead | tag `p4-frozen` |
| M28 Scoring domain — statistics, matching, classification, derivation | S1 + S2 + S3 | tag `p4w1-green` |
| M29 Persistence — `score`, `mismatch`, the ground-truth query | S4 | tag `p4w1-green` |
| M30 Component kit additions | S5 | tag `p4w1-green` |
| M31 Services — the scoring pass, results, ranking | T1 + T2 + T3 | tag `p4w2-green` |
| M32 API v1 | U1 + U2 | tag `p4w3-green` |
| M33 Results view — three tabs | V1 + V2 + V3 | tag `p4w4-green` |
| M34 The acceptance pass on the target machine | lead | tag `phase4-done` |

At `p4w4-green`, `mvp-spec.md` §19's acceptance criterion **6** is met in
everything but its final proof: per-feature × per-model precision/recall/F1
with `n` and Wilson intervals, cells below the floor suppressed, ties rendered
as ties, a language breakdown carrying the encoding caveat, and Goal 3 in a
separate table. Criterion **9** (dev-sized runs visibly marked) is re-met on a
third surface. **M34** is criterion 6 against a real scored corpus on the
target machine — the same shape as phase 3's M26, and if M26 is still open
(Q5), M34 is where both get closed in one session. Criterion **7** (the
mismatch list, browsable and taggable) is **phase 5**, over rows this phase
already wrote.

---

## 14. Risks and flags

| # | Flag |
|---|---|
| R1 | **`sw-design.md` §16 does not exist yet** — the one structural difference from phase 3, whose §15 was written before its plan (§0). If Wave 0 writes §16 in the same breath as twenty frozen files, the §5.3 review gate is the *only* thing standing between five Wave-1 agents and a wrong statistical contract. **Mitigation: the lead drafts §16 before spawning Wave 0.** **Discharged at Wave 0** — §16 was written first, before any other file in the freeze (§0). The risk it names is real for the *review*, not for the drafting: the §5.3 gate still reads §16 and `models.py`'s diff together. |
| R2 | **The statistics are the product, and a wrong one is invisible.** Nothing crashes on a mis-computed Wilson bound or a mis-marked tie — the screen simply lies, plausibly, in the one view the whole project exists to produce. `golden_stats.json` (S1) is the only layer that catches it, which makes a silent regeneration of that file the most damaging single edit available in this phase. |
| R3 | **The derivation evaluator is a phase-2 deferral coming due** (S3), and it was deferred with the words "scoring (phase 3) needs to build one anyway" — phase 3 did not, so nobody has budgeted it. It is a full agent with its own test layer, and two of the design's eight fixture rows depend on it. |
| R4 | **EAV ground-truth query performance** (S4). A 5 000-record corpus × 13 features over `unfall_row` / `objekt_cell` / `person_cell` is where an N+1 becomes minutes. This is `SD2`'s lesson (census materialisation) in a new place; the exit criterion asserts a **bounded statement count**, not a wall-clock number, because the latter is a flaky test. |
| R5 | **`mismatch` is the first mutable row in this codebase.** Everything else is append-only and `Do-NOT #2` covers `extraction`/`record`/`corpus`. An agent's correct instinct on re-score — DELETE then INSERT — destroys analyst tags that phase 5 depends on. The upsert and its preservation test are called out in S4's and T1's briefs for that reason. |
| R6 | **The design's Ranking "Presence 0.907" column reads as a score** (C8). An agent building from the `.dc.html` alone will put it in the rank computation, which `mvp-spec.md` §11.2 forbids. Called out in T3's and V3's briefs and worth repeating in the PR description. |
| R7 | **Suppressed rows sorting as 0.** A one-line bug that silently ranks the least-evidenced feature as the worst-performing one. Named tests at T2 and V1, in both directions. |
| R8 | **The copy is load-bearing.** The design README says "reproduce them verbatim unless the team changes the statistics", and the strings in question are the product's honesty guarantees — the presence scope banner, the encoding caveat, the Goal 3 footer, the hallucination note. An agent paraphrasing one has changed what the product claims. Asserted verbatim at the UI layer. |
| R9 | **Two of the design README's fixture sets are internally inconsistent** — two model rosters and two spellings of the same columns (C1, C3). Both are illustrative and neither is authored in code, but an agent reading only the `.dc.html` will encode one. Resolved in §1; repeat it in each Wave-4 brief. |
| R10 | **Phase 3's M26 is still open** (Q5). This phase builds a scorer over an extraction path that has never met a real model. If real adherence is worse than the fakes assume — malformed JSON, missing evidence spans, enum values outside the snapshot — it surfaces here as *scoring* bugs. `s06` and `s08` exist to make those cases already covered rather than newly discovered, and M34 is where both phases get their reality check. |
| R11 | **Three tabs, three agents, one screen.** Wave 4's split is cleaner than phase 3's (the tab shell is V1's alone, and no two agents touch `shell.py`), but the three tabs must agree on the run descriptor, the `cfg` chip and the dev marker — all of which come from one `RunDescriptorView` Wave 0 freezes. A drift there shows up as three slightly different headers on one screen. |

---

## 15. Decisions this plan makes

Numbered `F1…` following `plan-phase-2.md` §15 and `plan-phase-3.md` §15, and
always cited as "§15 F*n*" — `mvp-spec.md` §1 uses `F1…F12` for capabilities,
and the two must not be read into each other.

| # | Decision | Why |
|---|---|---|
| **F1** | `score` and `mismatch` are **materialised in one classification pass**, with **one `(run, feature)` per transaction** | `mismatch` has to be materialised regardless — it is a row an analyst tags — so the pass gets written either way; computing scores on read would mean writing it *and* paying ~195 000 classifications per page load. The per-feature boundary makes the pass restartable without a status column, exactly as `UNIQUE (run_id, record_id)` did for extraction (§15.3). |
| **F2** | `score.metric` is a **closed vocabulary that carries raw counts as well as rates** | The breakdown row needs hit/wrong/missing and the cross-tab needs six cells. Recovering counts from three rounded floats is arithmetic that fails quietly; a second table for counts is a join and a migration. One row shape, one enum, sixteen names — and the enum is what makes a missing metric a lint error instead of a `KeyError` in Wave 4. |
| **F3** | **Ranking is a pure function over `score` rows, never stored** | The design README states the invariant as "if the two disagree, Ranking is wrong by construction". A function cannot disagree with its own input. The layer rule already forbids `domain/ranking.py` from touching a session, so the guarantee is enforced by a contract that exists rather than by a review comment — and J13 proves it in the browser. |
| **F4** | Scoring is **automatic on run completion**; re-score is **explicit and preserves `analyst_tag`** | Every input is frozen at launch, so nothing can change between a run reaching `done` and its scores existing — a Score button would be a control for a decision the user cannot make, and the design draws none. Re-score exists for when the *scorer* changes, and it must not destroy review work, which is why `mismatch` is an upsert and not a rewrite. |
| **F5** | **No scoring-status column** — state is derived from committed `score` rows | Phase 3 F6's reasoning, applied again: a counter is a second source of truth that an interrupted pass can desynchronise. "Which features have no rows" is both the progress indicator and the resume key, and it cannot be wrong. |
| **F6** | `evaluation.min_cell_count`, **per evaluation**, defaulting from config | `mvp-spec.md` §11.4 says "configurable per evaluation" and the column costs one line in a migration Wave 0 is writing anyway; adding it later costs a migration of its own. Critically, suppression is applied at **render** time from stored `n` — so changing the floor never requires a re-score, which is what makes a per-evaluation setting cheap rather than expensive. |
| **F7** | The **derivation evaluator lands here**, closing `plan-phase-2.md` Q1 | Phase 2 deferred it on the explicit promise that scoring would need it; scoring needs it, because a derived feature's ground truth does not exist anywhere until something computes it. Building it in `domain/` over a pure `RecordProjection` keeps it testable without a database and keeps the EAV query in S4 where it belongs. |
| **F8** | Ranking's presence figure is a **macro presence rate, reported and never scored** | `mvp-spec.md` §11.2 is unambiguous that presence has no gold label, and §11.3's logic applies to it directly: a model that flags everything present wins the metric. Putting it in the reported-never-scored group beside latency and VRAM keeps the number visible — it *is* informative — without letting it order anything. |
| **F9** | **The neutral accent stands; tie markers are shape-coded** | `theme.py` already records that the prototypes' blue `--accent` is "left over from an earlier pass" and that the README wins, under "colour carries only state and severity, no decorative hue". The marker vocabulary is already three shapes (filled / outlined / empty), which reads without hue and survives colour-blindness — so adopting a decorative data hue in one view family would break a phase-1 rule and buy no legibility. Asserted structurally in S5's tests so it cannot be quietly reverted. |
| **F10** | **No new dependencies** — the Wilson interval is written out, not imported | `scipy` would be the largest dependency in the project, added for one constant and one closed form. M0 pinned every dependency deliberately; this is the first phase since then that adds none, and Wave 0's exit criteria assert that `pyproject.toml` is byte-unchanged so the decision has a gate behind it. |
| **F11** | Agent letters continue **S, T, U, V** | Alphabetical continuation from phase 3's `L`, skipping every letter already carrying a numbered vocabulary in these documents: `M` (milestones, and every Wave-0 agent's own name), `N` (non-functional requirements), `O` (reads as zero), `P` (deliverables), `Q` (clarifications), `R` (risks). Phase 3 F11's reasoning, applied to a crowded alphabet. |
| **F12** | **Mismatch review is out, but mismatch rows are written** | The scorer produces them as a by-product of classification; deferring the *rows* would mean writing the classification pass twice. Phase 5 becomes a view over data that already exists, and `analyst_tag` staying `NULL` for a whole phase is the phase-2 precedent of a correct answer that happens to start at zero. |
| **F13** | Goal 3's **"reviewed" counter defers with mismatch tagging**; its evidence spans ship now | The counter implies exactly the tagging machinery F12 defers — building a second one for exploratory attributes would be the duplication F12 exists to avoid. The evidence spans are already mandatory on every Goal 3 finding (§11.3) and are a read over `extraction_value`, so they cost nothing and are the half that is actionable today. |

# plan-model-choice.md — helping the analyst choose a model

**Status.** Written 2026-09-24 against `ecc4db4`. **Stage 0 done on
2026-09-25**: `docs/choosing-models.md` now holds model choice, and
`docs/performance.md` keeps time and cost. **Stage 1 done on 2026-09-25**:
SD40 in `sw-design.md`, the Models card in the design README, and
`contracts/amendments/feat-model-choice.md` (proposed, not yet applied). Every
§9 question is answered. **Stage 2 done on 2026-09-25** on
`feat/model-choice`: the pure gate, the table, its revision `7d084d5a7dc6`
and its repository. **Stage 3 done on 2026-09-25**: `just qualify-model`,
`QualificationService` and the two new catalogue calls. Stage 4 is next. Authority as always:
`mvp-spec.md` on *what*, `sw-design.md` on *how* (CLAUDE.md). Every frozen
file the code touches is named as an amendment (§6).

**In one paragraph.** Ollama offers dozens of models, each in several
versions, and whether one can take parallel calls is a per-host measurement.
Everything RA2 knows about that is in two documents
(`docs/choosing-models.md` and `docs/performance.md`). The Models card shows a tag, a digest and a size. The one
setting that depends on a measurement, `RA2_LLM_PARALLEL_CALLS`, is guarded by
a sentence ("Code can't check that; this sentence is the check").
This plan makes the measurement a **command**, stores its result as a
**qualification** row, **enforces** the parallel gate at launch against that
row, and **shows** what is known on the Models card. The judgement stays in
the document ("which model should I use?"). The facts move into the app.

---

## 1. Why

### 1.1 What the analyst sees today

Step 4 of the evaluation view lists every model the endpoint has
([evaluation_view.py:844](ra2/ui/views/evaluation_view.py#L844)). Each row
shows the tag, `digest 8fa1c3d0 · 5.2 GB`, and a disabled state when the
model is known not to fit VRAM. That's all. To learn that `qwen3:8b` is tied
for first and 6.6× faster than `gemma4:12b`, that `qwen3.5:9b` ranks near the
bottom, that `qwen3:8b` never fills `entities`, or that `granite4.1:8b` must
stay serial, the analyst has to find and read `docs/choosing-models.md`
(before Stage 0, `docs/performance.md` §4–5).

### 1.2 Why the document isn't enough

| # | Problem | Consequence |
|---|---|---|
| a | **Measurements are tied to a digest, an Ollama version and a GPU** (`docs/performance.md` §5.4, "Adding another model") | Re-pulling a tag can quietly invalidate a verdict. Nothing notices |
| b | **The parallel map is keyed by tag and unchecked** (SD38: "enforcing it is left out") | `{"qwen3:8b": 4}` keeps applying after `ollama pull qwen3:8b` has brought in new weights that were never measured |
| c | **The measurements were made with scripts that no longer exist** (plan-parallel-calls.md, memory of 2026-09-24) | Qualifying a new model or version means doing ~3 GPU-hours of work again by hand, following §4.1 of that plan |
| d | **A new model is a blank row** | Nothing distinguishes a model that has been measured from one nobody has run |
| e | **No run-time estimate before launch** | A 3 000-record `gemma4:12b` run takes ~10 h. The analyst learns that from the progress card |

### 1.3 What the seed can and can't say

The 200-record seed puts a perfect reader at ~90 % macro-F1
(`docs/seed.md` §8), and the five leaders all sit at that ceiling
(`docs/choosing-models.md` §3). **A seed score therefore says whether a model
is usable. It can't say which leader is best.** Everything this plan puts on
screen has to be worded that way, or the Models card turns into a ranking the
data doesn't support.

---

## 2. What exists and what it means

| # | Where | What |
|---|---|---|
| a | [config.py:148](ra2/infra/config.py#L148) `llm_parallel_calls` | Map from tag to N. Validated for range only. Its docstring contains the gate rule |
| b | `EvaluationService._new_run` | Pins `map.get(tag, 1)` and `model_digest` on the run. The digest is already known at launch |
| c | `run` / `extraction` | Store `model_digest`, `raw_output_text`, `latency_ms`, `prompt_tokens` and `completion_tokens`. **Everything a qualification measures is already recorded by an ordinary run** |
| d | `scripts/seed_dev.py` | Builds a synthetic corpus (`--records N`) through the services, with `create_app(mount_ui=False)`. The model for a script that drives the app from outside |
| e | `RankingService` | Macro-F1 with Wilson interval, time per record (SD38) |
| f | `ModelCatalog` ([llm.py:168](ra2/domain/llm.py#L168)) | `models()` and `reachable()` only. It doesn't report Ollama's version |
| g | `ModelChoiceView` ([readmodels.py:466](ra2/services/readmodels.py#L466)) | `tag digest size_bytes fits_vram selected`. Frozen |
| h | `design/prompt-evaluation/README.md` l.201 | The row is "mono 12px tag over mono 10.5px `--ink3` digest … · size". E2E asserts it (§8.2) |
| i | SD32 | Evaluations can be cloned, so repeated passes over the same inputs are an existing operation |

---

## 3. Decisions

**D1. A qualification is a measurement of a (tag, digest) on this host.**
It records the tag, digest, Ollama version, GPU name (or `null`), date, seed
size and RA2's installed version, plus two optional parts:

- **Quality and cost** (always): macro-F1 with its interval, per-language
  mean F1, median and mean latency, median completion tokens, time per record
  and **entity fill** (records with ≥ 1 entity ÷ records). One serial pass
  over the **200-record** seed, like `docs/choosing-models.md` §3–4.
- **Parallel gate** (optional, per N): the counts and verdict of
  plan-parallel-calls.md §4.1, over the **48-record** seed, like Stage 0b.

The numbers are about synthetic data only. **No delivery content is involved
at any point**: the qualifier seeds its own throwaway data dir, and only the
numbers above cross into the analyst's database (§4.2).

**D2. Stored in the database, append-only.** A new `model_qualification`
table in the analyst's `RA2_DATA_DIR` database. Re-qualifying **adds a row**,
and the newest row for a (tag, digest) wins, the same as a re-run
(Do-NOT #2 treated as a rule, even though this table isn't named in it).
*Why the DB and not a JSON file:* it's this host's own calibration, it needs
the same backup and reset path as everything else, and a second persistence
mechanism would need its own path, encoding and locking rules. *Cost:* one
migration, and `just reset` wipes the qualifications along with everything
else (§9 Q3).

**D3. The command drives the app, like the seed.**
`just qualify-model <tag> [--gate 2,4] [--one-slot URL] [--n-slot URL]`
runs `scripts/qualify_model.py`. It:

1. creates a throwaway data dir in the system temp, then migrates and seeds it
   through `seed_dev`'s functions (200 records, or 48 for the gate);
2. builds `create_app(mount_ui=False)` over it with a `Settings` for each
   endpoint and parallelism, and runs evaluations through
   `EvaluationService` / `RunService` exactly as the UI does. Repeated passes
   are **clones** (SD32), so no pass shares a run. Before each pass it
   checks `/api/ps` on the endpoint in use and refuses to start while any
   other model is loaded, because that hides the speedup
   (plan-parallel-calls.md §1.1 point 3);
3. derives the figures through `QualificationService`, **inside the throwaway
   app**;
4. opens the **target** app (the configured `RA2_DATA_DIR`) and records the
   qualification through `QualificationService.record`;
5. deletes the throwaway dir and prints **counts, times and the verdict
   only**, never an answer (`data-handling.md` §5; even synthetic output
   stays out of logs by habit).

No new logic runs outside `services` and `domain`. The script is wiring, like
`seed_dev.py`. The comparisons (canonical-JSON differ counts, noise band,
verdict, speedup) are **pure functions in `ra2/domain/qualification.py`** and
get unit tests.

**D4. The endpoints are the operator's to name, and RA2 records what it was
told.** RA2 can't read `OLLAMA_NUM_PARALLEL` (plan-parallel-calls.md §2 h).
The gate needs a **one-slot** server for the baseline and an **N-slot** server
for conditions 1 and 2. `--one-slot` defaults to `RA2_LLM_BASE_URL`.
`--n-slot` has no default: without it, `--gate` is refused with a sentence
naming `docs/performance.md` §5.4's private-server recipe. Both go through
`OllamaLLMClient`, so both must be loopback (§15.5, SD27). There is no
opt-out. The script **doesn't start Ollama itself**: starting a server is a
host decision (models path, `OLLAMA_NOPRUNE`), and a script that spawns and
kills servers is the kind that killed a shell on 2026-09-24.

**D5. The gate, written down once, in code.** plan-parallel-calls.md §4.1
becomes `gate_verdict(...)`:

- **Noise band** = the largest differ count among three one-slot serial
  passes (2nd and 3rd against the 1st), **floored at 2 of 48** (≈ 4 %,
  scaled to the seed size). The floor exists because three passes is a small
  sample, and the band pooled over five models on this host was 0–2
  (§1.1 of that plan). §9 Q2.
- **Condition 1:** the N-call pass on the N-slot server vs the 1st one-slot
  pass: differ ≤ band.
- **Condition 2:** a serial pass on the N-slot server vs the 1st one-slot
  pass: differ ≤ band.
- **Condition 3:** throughput at N ≥ **1.3×** serial on the same server.

The verdict is `PASSES`, `FAILS_PARALLEL` (1 or 3), `FAILS_SERVER` (2) or
`FAILS_BOTH`. A model that fails condition 2 is flagged on the Models card
whatever its own map entry says, because it's the one a multi-slot server
disturbs (the `ministral-3:8b` case).

Checked against history: `qwen3:8b` 0–1 / 0 / 2.4× → passes; `granite4.1:8b`
15 → fails parallel; `ministral-3:8b` 6 serial → fails both;
`gemma4:12b` 4 at N=4 → fails parallel, narrowly. These are Stage 6's
acceptance numbers.

**D6. The launch honours a map entry only with a matching passing gate.**
This replaces SD38's "enforcing it is left out". `_new_run` pins N from the
map only when the newest qualification for this **tag and digest** has
`PASSES` at an N' ≥ N, **with the same Ollama version**. Otherwise it pins
**1** and logs why, with ids, the tag and a reason code only
(`parallel=1 (map=4, gate=missing|digest|ollama_version|failed)`).
Falling back **to serial** rather than refusing the launch is deliberate. A
serial run is always correct, only slower. A refusal would block an
evaluation over a performance setting. The GPU name is recorded but **not**
compared: NVML can be absent, and a name is not a calibration (§9 Q4).

This needs the Ollama version at launch: one `/api/version` call on a new
`ModelCatalog.version()` (frozen protocol → amendment). It returns `None`
when unreachable, and `None` never matches.

**D7. The Models card shows facts, not a verdict.** Each row gains **one**
mono 10.5px line under the existing size line:

| State | Line |
|---|---|
| Qualified for this digest | `seed F1 0.895 · 1.7 s/rec · entities 0 % · ~1 h 25 m for 3 000` (+ ` · parallel ×4` when D6 would honour it) |
| Qualified for another digest only | `measured on digest 500a1f06 — re-qualify` in `--warn` |
| Gate fails condition 2 | `… · changes when Ollama runs >1 slot` in `--warn` |
| Never qualified | `not measured on this host` in `--ink3` |

The estimate is time per record × the evaluation's **scope size**. With no
evaluation yet, it's the corpus size, and with no corpus the part is left
out. It carries a tooltip "on seed-sized narratives". The row's height
changes, so the design README's step 4 changes first (Stage 1), and E2E
asserts the new line. **Wording lives in `ui/`'s rendering table**. The
service hands over numbers and an enum state, never a sentence
(CLAUDE.md, "Findings, not prose").

There's deliberately **no "recommended" badge and no "suggested set" button**.
§1.3: the seed can't separate the leaders, so any badge the data could
produce would be ranking ties. The recommendation stays in
`docs/choosing-models.md` §1, a human judgement with its reasons.

**D8. The API carries what the UI carries.** `ModelChoiceResponse` gains the
same fields as `ModelChoiceView`. There's no endpoint for writing a
qualification. Recording one is the command's job, and a `POST` that takes
numbers would let anything claim a measurement.

---

## 4. The design, in detail

### 4.1 `ra2/domain/qualification.py`

Pure, stdlib + pydantic (the layer rule):

- `QualitySummary`, `GateResult(n, serial_on_n_slot_differ, parallel_differ,
  noise_band, speedup, verdict)`, `Qualification` (D1), `GateVerdict`,
  `ParallelDecision(n, reason)` and `ParallelReason`
  (`GATED | NOT_MAPPED | NO_GATE | DIGEST | OLLAMA_VERSION | FAILED`).
- `canonical_answer(raw: str) -> str`: sorted-key, compact JSON of a parsed
  response, or the raw text when it doesn't parse. It's the Stage 0 "differ"
  definition, and a parse failure counts as its own answer.
- `differ_count(a, b) -> int` over two `{record_id: canonical}` maps. It
  **refuses** maps with different keys (`ValueError`) rather than counting a
  missing record as a difference. A pass with holes is an interrupted pass,
  not a result.
- `noise_band(baseline_differs, records) -> int` (D5 floor).
- `gate_verdict(...) -> GateVerdict`.
- `parallel_decision(mapped, qualification, digest, ollama_version) -> ParallelDecision`
  (D6). The launch calls it, the Models card calls it, and it's the only
  place the rule exists.

### 4.2 Persistence

One table, one revision, one repository:

```
model_qualification
  id                 TEXT PK (uuid7)
  model_tag          TEXT NOT NULL
  model_digest       TEXT NOT NULL
  ollama_version     TEXT NULL
  gpu_name           TEXT NULL
  ra2_version        TEXT NULL
  measured_at        TIMESTAMP NOT NULL
  seed_records       INTEGER NOT NULL
  quality_json       TEXT NOT NULL     -- QualitySummary
  gate_json          TEXT NOT NULL     -- list[GateResult], [] when not gated
  INDEX (model_tag, model_digest, measured_at)
```

JSON columns for the two summaries, because they're read whole and never
queried inside, and a new figure then doesn't cost a migration. The repository
has `add` and `latest_for(tag)` / `latest_for(tag, digest)`, and **no update
or delete** (D2).

### 4.3 `QualificationService`

- `summarise(evaluation_id, gate_passes) -> Qualification`: used by the
  script **inside the throwaway app**. It reads through repositories and
  `RankingService`, then hands the raw outputs to the domain functions. Raw
  text never leaves the service.
- `record(q: Qualification) -> None`: used on the target app.
It joins the `Services` bundle (`container.py`, frozen → amendment).

`EvaluationService` doesn't call it. For the Models card and for `_new_run`
(D6), it reads `QualificationRepository.latest_for` with its own session
factory, the same way it reads every other table it needs. That avoids
adding a cross-service protocol to the frozen `protocols.py` (Stage 1
decision).

### 4.4 The launch (D6)

`_new_run` today: `parallel = settings.llm_parallel_calls.get(tag, 1)`.
After: `decision = parallel_decision(mapped, latest(tag), digest,
await catalog.version())`, pin `decision.n`, and log `decision.reason`. One
extra round trip per launch, not per record. Resume still reads the pin
(SD38 unchanged).

### 4.5 What the analyst's host has to do once

After the upgrade, a host with a non-empty `RA2_LLM_PARALLEL_CALLS` runs
**serially** until each mapped model is qualified with `--gate`. Today that's
nobody: plan-parallel-calls.md's Status says the analyst's host hasn't turned
parallel calls on. `docs/performance.md` §5.4 gains the step, *before*
"Step 3: Set up RA2", so the order is: Ollama slots → qualify → map.

---

## 5. Stages

### Stage 0 — the decision guide (docs only) ✅ (2026-09-25)

**Done, and bigger than planned.** Instead of a box inside
`docs/performance.md`, David asked for a separate document, so that each one
covers one topic:

- **`docs/choosing-models.md`** (new): the decision table (§1), a per-model
  summary with seed F1, time, entities and the parallel verdict (§2), quality
  (§3, moved), entities (§4, moved), which models can take parallel calls
  (§5), and how to try a model or a new version this page doesn't cover (§6).
  §6 is what an analyst does until Stage 3's command exists.
- **`docs/performance.md`**: §4 becomes "Model speed". §4.1, §4.4 and §4.5
  stay as one-line pointers, so `plan-parallel-calls.md`, `sw-design.md`,
  `config.py` and `CONTRACTS.md` references still resolve. No number changed.
- **`README.md`**: both documents are in the documentation map.

One thing turned up while writing §6: **RA2 stores entities but shows them
nowhere**, not on any screen and not in the API. An analyst trying a new
model can't check entity fill from the app. D1's qualification reports it,
which is one more reason for Stage 3.

### Stage 1 — the contract, first ✅ (2026-09-25)

**Done.**

- `sw-design.md`: **SD40** (D1–D8, with Q2–Q5's answers). SD38's
  "enforcing it is left out" now points to SD40. The §10 row for
  `RA2_LLM_PARALLEL_CALLS` says an entry needs a gate on record. §15.2 lists
  `model_qualification`, §15.4 describes the launch's decision, §15.5 the
  two new `ModelCatalog` calls, and §15.7 the new module, repository,
  service and script.
- `design/prompt-evaluation/README.md` step 4: the third line, its four
  states as `data-state`, the no-badge rule, and the state model.
- `contracts/amendments/feat-model-choice.md`: proposed diffs for §6's
  files. It's applied in Stage 2.

Four decisions Stage 1 made that the plan hadn't:

- **The models well grows from 196px to 252px.** The design's rule is "4
  visible rows", and the third line makes a row 63px instead of 49px.
  Keeping 196px would quietly show three rows. `test_scroll_well_caps_height…`
  in `tests/ui/test_components.py` passes its own 196 to the component and
  doesn't change. Stage 5's E2E measures the rendered row height.
- **`EvaluationService` reads the repository, not `QualificationService`**
  (§4.3), so the frozen `protocols.py` isn't touched.
- **`ra2_version` instead of `ra2_commit`.** It comes from
  `importlib.metadata`. A commit would need a `git` shell-out from `ra2/`
  (N3), and an installed copy has no `.git`.
- The amendment names **`ra2/domain/ids.py`** too (`QualificationId`), so
  §6 lists nine frozen files, not seven.

**Moved out of Stage 1:** the analyst-facing docs
(`docs/choosing-models.md` §6 and `docs/performance.md` §5.4). They would
describe a command that doesn't exist yet, so they change in Stage 4, when
the command and the enforcement both do.

### Stage 2 — domain and persistence ✅ (2026-09-25)

**Done.** `ra2/domain/qualification.py`, `model_qualification` with revision
`7d084d5a7dc6` (autogenerated against a scratch database, then hand-adjusted
as `e5145f27bf8c` explains), and `QualificationRepository`. Amendment §1
(`ids.py`) and §3 (`models.py`) are applied and recorded in `CONTRACTS.md`
under "Model choice". The revision is registered in
`tests/test_p5_contract.py`'s `POST_PHASE_5_REVISIONS`. `just lint` is clean.
`just test`: 2595 passed, 1 skipped (the existing empty nav parameter set).
Where it differed from the table below:

- **`QualificationId` needed a type-map entry**, `String(36)` like every
  other id. SQLAlchemy warns on an unmapped `NewType`, and the suite turns
  warnings into errors. The amendment's status table records it.
- **`latest_for` gained `gated=True`.** Without it, re-measuring a model's
  quality alone would hide its gate and take it back to serial. The launch
  asks for the newest *gated* qualification, and
  `test_a_later_quality_only_run_does_not_hide_the_gate` pins that.
- **The repository speaks domain, not ORM.** It takes and returns
  `Qualification`, so the JSON columns are encoded in one place.
- **Ties on `measured_at` resolve by id** (uuid7, so time-ordered), not by
  whatever SQLite returns.
- The historical-verdict test also covers `qwen3.5:2b` (1.0×, fails
  condition 3) and `FAILS_SERVER` on its own.
- Test names follow the table, except `test_noise_band_is_floored_at_two_of_48`,
  which became `…_scaled_to_seed_size` and gained the 200-record case.

§4.1 and §4.2. **One Alembic revision**, written by this plan's implementer
and nobody else, with no parallel heads. Phase 5 expected no revision, and
plan-parallel-calls.md set the precedent that a post-phase plan names its own
single author. `metadata.create_all()` is never used (Do-NOT #10).

| Test | Layer | Asserts |
|---|---|---|
| `test_canonical_answer_ignores_key_order_and_whitespace` | unit | |
| `test_an_unparseable_answer_is_its_own_answer` | unit | Two different broken texts differ; the same one doesn't |
| `test_differ_count_refuses_passes_over_different_records` | unit | `ValueError`, not a count |
| `test_noise_band_is_floored_at_two_of_48` | unit | And scales with seed size |
| `test_gate_verdicts_reproduce_the_measured_history` | unit | D5's four historical models, parametrised |
| `test_parallel_decision_needs_a_matching_passing_gate` | unit | One case per `ParallelReason` |
| `test_parallel_decision_never_runs_above_the_gated_n` | unit | Gated at 2, map 4 → 1, reason `FAILED` (§9 Q5) |
| `test_qualifications_are_appended_never_updated` | backend | Two `add`s for one (tag, digest), `latest_for` returns the newer, the older is still there |
| `test_migration_creates_model_qualification` | backend | Upgrade, downgrade, re-upgrade on a temp DB |

### Stage 3 — the command ✅ (2026-09-25)

**Done**, against fake endpoints only. Stage 6 is the first run against real
Ollama. Amendment §2 (`llm.py`), §5 (`container.py`), §6 (`main.py`) and §8
(`justfile`) are applied and recorded in `CONTRACTS.md`. `just lint` is clean.
`just test`: 2622 passed, 1 skipped. The 15 script tests take ~29 s serially.
Where it differed from the plan:

- **`summarise` became three readers:** `quality(evaluation_id)`,
  `answer_fingerprints(run_id)` and `pass_wall_ms(run_id)`. The gate's
  arithmetic went to the domain as **`gate_result(...)`**, so the script
  passes fingerprints to a pure function and holds no logic of its own.
- **Fingerprints, not answers.** The service returns the SHA-256 of each
  canonical answer, which keeps equality and drops the text. The seed is
  synthetic, but the rule then holds wherever the service is pointed.
- **The gate reuses the one seed.** The throwaway `Settings` set
  `dev_record_max` to `--gate-records` (48), and gate passes use the Dev
  scope, so a single 200-record seed serves both measurements.
- **`QualitySummary` gained `reasoning_effort`.** The effort moves time per
  record by 30× on a thinking model, so a figure without it can't be
  compared. It's a JSON field, so no migration.
- **The throwaway migration runs before the event loop.** Alembic's
  `env.py` calls `asyncio.run` itself. Every app's engine is disposed
  before its loop ends, or aiosqlite warns and the suite fails.
- **Refusals the plan didn't list:** a tag the endpoint doesn't offer, and
  two servers that disagree on digest or Ollama version.
- **Tests:** named as in the table. `test_catalog_version_is_none_when_unreachable`
  became `…_when_it_cannot_be_read`, parametrised over refused, 500, an empty
  version and a missing one. Added: pass order, the resident-model refusal,
  the server-disagreement refusal, `--gate` values below 2, and `/api/ps`.
  "Hand-computed" F1 became "the ranking's own figures, copied". The quality
  test pins records, parse failures, entity fill, effort and latency exactly.

**Found, not fixed (outside this plan):** `stats.macro_interval` (P4-D1)
centres the macro interval on the mean of the Wilson *centres*, not on the
macro point. Near 0 a Wilson centre sits above its point, so the interval can
lie entirely above the reported macro-F1: on a fake scoring 0.083 it read
0.091–…. At the leaders' ~0.9 it errs the other way, and for "tied or not"
it's harmless. But a printed interval that excludes its own point will look
like a bug to a reader.

**Stage 4 must solve one thing first.** Once the launch enforces D6, the
qualifier's own parallel passes would be pinned to 1, because the throwaway
database has no gate on record. The gate can't be measured if measuring it
needs a gate. Stage 4 adds an explicit launch option for measurement passes,
reachable in-process only and passed by no adapter, and SD40 gets a sentence
naming it as the one launch that pins the map without a gate.

`QualificationService`, `scripts/qualify_model.py` and the `qualify-model`
recipe in `justfile` (frozen → amendment). `ModelCatalog.version()` in the
adapter.

| Test | Layer | Asserts |
|---|---|---|
| `test_summarise_derives_quality_from_an_ordinary_run` | backend | Fake `LLMClient` with scripted answers: F1, latency, token and entity figures match hand-computed values |
| `test_summarise_counts_differing_answers_between_cloned_passes` | backend | Two clones, the fake changes 3 answers: differ = 3 |
| `test_the_qualifier_never_touches_the_target_data_dir_except_to_record` | backend | Target DB has exactly one new `model_qualification` row and nothing else. Its row counts per table are otherwise unchanged |
| `test_the_qualifier_deletes_its_throwaway_dir` | backend | Also on failure (`finally`) |
| `test_gate_without_an_n_slot_endpoint_is_refused_before_any_call` | backend | The fake sees zero calls |
| `test_a_non_loopback_endpoint_is_refused` | backend | Through `OllamaLLMClient`'s existing refusal, not a second check |
| `test_the_qualifier_prints_no_answer_text` | backend | A canary string in every fake answer is absent from stdout and stderr |
| `test_catalog_version_is_none_when_unreachable` | backend | |

The script is wiring. What it does is tested through the service and a
`main(argv)` entry point with injected settings, the way `ra2/cli.py` is
tested. There's no test-only branch (Do-NOT #12).

### Stage 4 — enforcement at launch (D6)

The analyst-facing docs change here, in the same commit as the enforcement,
because this is when a host's existing map starts depending on a gate:

- `docs/choosing-models.md` §6: the manual procedure becomes
  `just qualify-model`, and §6.4 ("Planned") goes.
- `docs/performance.md` §5.4: the reordered steps (§4.5), with the old
  "record the result in §5.3" replaced by "run `just qualify-model`".

| Test | Layer | Asserts |
|---|---|---|
| `test_launch_honours_the_map_for_a_gated_digest` | backend | Pinned 4 |
| `test_launch_runs_serially_after_a_re_pull` | backend | Same tag, new digest → pinned 1, log reason `digest` |
| `test_launch_runs_serially_on_a_different_ollama_version` | backend | |
| `test_launch_runs_serially_without_a_qualification` | backend | |
| `test_an_unmapped_model_is_unaffected` | backend | Pinned 1, reason `NOT_MAPPED`, no `version()` call needed |
| `test_resume_keeps_the_pin_even_after_a_new_qualification` | backend | SD38 unchanged |
| `test_launch_pins_parallel_calls` (existing) | backend | Updated to give its fake a passing qualification. **No other existing test is weakened** |

### Stage 5 — the Models card and the API (D7, D8)

`ModelChoiceView` gains `qualification: QualificationCardView | None`
(numbers, the enum state and the D6 decision). `ModelChoiceResponse` mirrors
it. `evaluation_view._model_row` renders the third line through a rendering
table.

| Test | Layer | Asserts |
|---|---|---|
| `test_model_choices_carry_the_latest_qualification_per_digest` | backend | |
| `test_estimate_uses_the_evaluation_scope_then_the_corpus` | backend | And is absent with neither |
| `test_models_api_carries_the_qualification` | backend | |
| `test_each_qualification_state_renders_its_line` | ui | The four D7 states, asserted on `data-state`, not on wording |
| `test_an_unmeasured_model_is_still_selectable` | ui | "Not measured" never disables a tick |
| E2E: the row's third line exists, 10.5px mono, and the row still fits `MODELS_WELL_PX` | e2e | Design fidelity §8.2 |

### Stage 6 — verify on this host

Throwaway everything, as plan-parallel-calls.md Stage 0b did. Unload every
model on 11434 first. The N-slot server is a private `ollama serve` on
`127.0.0.1:11435` (`docs/performance.md` §5.4), and the system service is
never reconfigured.

1. `just qualify-model qwen3:8b --gate 2,4 --n-slot http://127.0.0.1:11435/v1`
   into a **throwaway target** data dir.
2. `granite4.1:8b` and `gemma4:12b` the same way.
3. The numbers match `docs/choosing-models.md` §3–4 within the Wilson
   interval and §5.3's differ counts within the band. The verdicts are D5's.
4. `just dev-agent` on that target: the three rows show their lines, and an
   unmeasured model shows "not measured". With the map set to
   `{"qwen3:8b": 4, "granite4.1:8b": 4}`, a launch pins 4 and 1 respectively,
   and the log names `FAILED` for granite.

Expected GPU time: ~15 min quality + ~10 min gate for `qwen3:8b`, ~40 min
quality for `gemma4:12b`. About 1.5 h total.

**Done when** (3) holds, the times are in this file's §1, and the Status line
names the merge commit.

---

## 6. Frozen files touched — amendments

| File | Change |
|---|---|
| `ra2/domain/ids.py` | `+ QualificationId` |
| `ra2/domain/llm.py` | `+ ModelCatalog.version() -> str \| None` and `+ ModelCatalog.loaded() -> tuple[str, ...]` (`/api/ps`, empty when unreachable) |
| `ra2/persistence/models.py` | `+ ModelQualification` |
| `ra2/services/readmodels.py` | `+ QualificationCardView`; `+ ModelChoiceView.qualification` |
| `ra2/services/container.py` | `+ qualification: QualificationService` |
| `ra2/api/schemas.py` | `+ ModelChoiceResponse.qualification` |
| `justfile` | `+ qualify-model` |
| `ra2/main.py` | Wiring `QualificationService` into `Services` |

| `ra2/infra/config.py` | Docstring only: "this sentence is the check" becomes "the launch checks it" (SD40). No field, default or validator changes |

All nine are in `contracts/amendments/feat-model-choice.md` with their exact
diffs, and they go into `CONTRACTS.md`'s change log when Stage 2 applies
them.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| The card's numbers read as a ranking | D7 wording ("seed F1"), no badge, and §1.3 in the tooltip |
| A qualification from a bad session (another model in VRAM, §1.1 point 3 of the parallel plan) records a false speedup | The script checks `/api/ps` before each pass and refuses to start while another model is loaded on either endpoint |
| An upgrade silently slows a host that already has a map | §4.5: nobody has one today. The log line and the card both name the reason |
| `just reset` wipes the calibration | §9 Q3 |
| Seed-sized estimates understate real narratives | The tooltip says so. §8 lists a real-corpus correction |

---

## 8. Not in this plan

- **A "recommended" badge or preset** (D7). If David wants one later, it
  should come from a committed, human-written list, not from the seed.
- **Qualifying on real data.** That's an evaluation, and RA2 already does
  it. A qualification is about host and model fitness, measured on synthetic
  data so it can be repeated anywhere.
- **Architecture-based refusal** (`qwen35`). This is still plan-parallel-calls.md
  §8's reasoning. The gate measures it (speedup 1.0× → condition 3 fails).
- **Starting the private Ollama server from the script** (D4).
- **Run-time detection that parallel had no effect** (a finished run's time
  per record vs its qualification's). It's worth doing. It needs a finding
  code, which is a frozen enum, so it's a follow-up.
- **Correcting the estimate from a real run's own time per record.**
  Follow-up once the card has proved useful.
- **Shipping this dev host's measurements as reference rows.** Different GPU.
  §9 Q1.

---

## 9. Decisions for David

| # | Question | Recommendation |
|---|---|---|
| Q1 | Ship this host's measurements as read-only "reference" rows, so the card has something on day one? | **No.** They come from another GPU, five of the eight have no recorded digest, and the analyst's first `qualify-model` of the three recommended models costs ~1.5 h. A reference row would be the first number on the card that doesn't describe the host it's shown on |
| Q2 | Noise-band floor at 2 of 48 (D5)? | **Yes.** Without it, a lucky 0-0 baseline fails a model on a single flipped token |
| Q3 | Should `just reset` keep `model_qualification`? | **No, not in this plan.** A reset means "start from nothing", and exempting one table is a new rule in `plan-reset-and-discard.md`. If re-qualifying after a reset proves annoying, add `qualify-model --export/--import` (JSON, numbers only) |
| Q4 | Enforce digest + Ollama version, but not GPU name (D6)? | **Yes.** Digest and version are what `docs/performance.md` §5.4 already calls "a new measurement". The GPU name can be missing and says nothing about drivers |
| Q5 | Gated at 2, map says 4: pin 2 or 1? | **1.** The map entry is the operator's claim, and it's wrong. Pinning 2 would be RA2 picking a value nobody configured. Reason `FAILED`, and the card says "gated at ×2 only" |
| Q6 | Stage 0 now, before the rest is decided? | **Yes.** It's docs only, takes an hour, and helps right away |

**Answered 2026-09-25:**

- **Q1 no.** No reference rows. The Models card shows only what was measured
  on the host it's running on.
- **Q3: don't keep them.** `just reset` removes `model_qualification` with
  everything else, and `plan-reset-and-discard.md` is unchanged. After a
  reset, the Models card reads "not measured on this host" until
  `qualify-model` runs again, and D6 pins every model to 1.
- **Q5: 1.** A map entry above the gated N pins 1, with reason `FAILED`.
- **Q6 yes.** Done, as a separate document (Stage 0).

**Answered 2026-09-25, later:** Q3 confirmed as "don't keep". **Q2 yes**
(floor at 2 of 48) and **Q4 yes** (digest and Ollama version compared, GPU
name recorded only). Both are in SD40. For the record, here is what each one
decided.

### Q2 in detail: the noise-band floor

Two serial runs with identical settings don't always give identical answers.
GPU arithmetic isn't exactly repeatable, and at temperature 0 one rounding
difference can flip a token. On this host, repeated serial passes differed on
0, 2 and 0 of 48 records (`gemma3:4b`), 0 (`qwen3:8b`) and up to 3
(`gemma4:12b`). The gate asks whether parallel calls change more answers than
that noise already does, so it needs a number for "that noise": the **band**.

D5 measures the band from three serial passes. Three passes is a small sample:
a model whose true noise is "a record now and then" can easily show 0 and 0.
Without a floor, the band is then **0**, and a single flipped record in the
parallel pass fails the model. `qwen3:8b` differed on 0–1 of 48 in parallel
(plan-parallel-calls.md §1.2). With a band of 0, it would pass or fail
depending on the day.

| Option | Effect on the measured history | Cost |
|---|---|---|
| **(a) Floor at 2 of 48** (recommended) | `qwen3:8b` passes. `granite4.1:8b` (15), `gemma3:4b` (27–29) and `ministral-3:8b` (6 serial) fail. `gemma4:12b` fails narrowly: its own band is 3, and it differed on 4 | A model that really does change 2 of 48 answers in parallel passes. That's the difference `docs/performance.md` §6 already tells the analyst to treat as noise between two ordinary runs |
| (b) No floor, five baseline passes instead of three | Same verdicts on most days, but `qwen3:8b` can still meet a 0-0-0-0 baseline | Two more passes: ~3 min for `qwen3:8b`, ~18 min for `gemma4:12b` |
| (c) A statistical test (differences as a proportion, with an interval) | Same verdicts | 48 records is too few for an interval narrower than the effect. It adds apparent precision and no real information |

The floor scales with seed size (2 of 48 ≈ 4.2 %) so that a larger gate seed
doesn't make it relatively looser. It's a constant in
`ra2/domain/qualification.py`, not a setting, because a setting would let the
gate be relaxed until a model passes.

### Q4 in detail: what the launch compares

D6 lets a parallel-calls entry apply only when the qualification still
describes what will run. Three things could have changed since the gate was
measured:

| Compared? | What | Why |
|---|---|---|
| **Yes** | **Model digest** | It identifies the weights. `ollama pull` can replace them behind an unchanged tag, and new weights are a new model for the gate. RA2 reads the digest at launch already |
| **Yes** | **Ollama version** | The parallel behaviour belongs to Ollama's bundled llama.cpp: its batching kernels decide whether answers change, and its list of architectures it refuses to parallelise decides whether there's a speedup at all (the `qwen35` refusal, ollama#14510). Both change between releases, including patch releases, so the comparison is on the full version string. Cost: one `/api/version` call per launch |
| **No** (recorded only) | **GPU name** | Qualifications live in the database of the host they were measured on, so a different GPU means a hardware swap under the same install, which is rare. The name is also often unknown (no NVIDIA GPU, no NVML), and an unknown name can't be compared: treating it as "different" would stop every non-NVIDIA host from ever running in parallel, and treating it as "same" means the check does nothing. And a name misses what matters more, the driver and CUDA version. It's stored on the row and shown on the card, and that's the right weight for it |

**What this costs the analyst:** every Ollama upgrade quietly takes mapped
models back to serial until `just qualify-model <tag> --gate 4` has been run
again, about 10 minutes for `qwen3:8b`. It's quiet but visible: the run's log
line says `gate=ollama_version` and the Models card drops `parallel ×4`.
Nothing gives different answers without warning, and the only loss is speed.

**The alternatives rejected:** comparing only the major.minor version would
miss patch releases that bump llama.cpp. Refusing the launch instead of
running serially would block an evaluation because of a speed setting. If the
version can't be read at launch, it counts as not matching and the run is
serial. In practice Launch is already disabled when the endpoint is
unreachable.

# plan-parallel-calls.md — more than one record in flight per run

**Status.** Written 2026-09-23 against `12268ed` and revised the same day
after Stage 0. **All stages done on 2026-09-24 on branch
`feat/parallel-calls`, not yet merged.** Stage 0b (§1.2) passed `qwen3:8b` on
all three gate conditions. It stopped `ministral-3:8b`, which David replaced
with `granite4.1:8b` (§9 Q5). Stages 1–3 built the design (SD38), the
setting, the column, the display and the worker pool. Stage 4 (§1.3) found
identical scores and 2.38× on `qwen3:8b`. **Left for David:** merging, and
the host change in §7 that makes it take effect outside a private server.
Authority as always: `mvp-spec.md` on *what*, `sw-design.md` on *how*
(CLAUDE.md). Every frozen file the code touches is named as an amendment
(§6).

**What the revision changed.** The first draft had one host-wide number for
every model. Stage 0 showed the answer is **per model**: `qwen3:8b` gains ~2×
with unchanged answers, `gemma3:4b` gains ~2× but changes more than half of
its answers, and Qwen 3.5 can't run in parallel at all. So D1, D3 and the
ranking display change, and a new gate appears. Ollama's own setting is
server-wide, so raising it for one model may disturb every other model's
serial runs (§4.5).

---

## 1. Why, measured

An evaluation's wall time is `records × models × time per call`. Scoring is
not a factor: 48 records × 7 features score in **0.14 s**. Every other second
is `LLMClient.extract`, awaited **one record at a time**
(`run_service._extract_all`, [run_service.py:572](ra2/services/run_service.py#L572)).

The eight-model comparison (`docs/performance.md` §4) recommends **`qwen3:8b`**:
tied for first on the 200-record seed (macro-F1 0.895), and the fastest of the
leaders at **1.7 s per record**. That is ~1.5 h for a 3 000-record run. It is
also the model this plan helps most. **This plan is worth building only if
`qwen3:8b`, or another model that passes §4.1's gate, becomes an evaluation
model** (§9 Q1).

Host: RTX 5060 Ti 16 GB, Ollama 0.34.0, system service at
`OLLAMA_NUM_PARALLEL=1`.

### 1.1 Stage 0 results

**Method.** The 48-record dev seed in a throwaway data dir. Prompts were
resolved through `RunService._load_plan` / `_resolve_prompt` and sent through
`OllamaLLMClient.extract`, with effort `none`, temperature 0 and seed 42, at
N concurrent calls under an `asyncio.Semaphore`. The model was warmed first.
Parallel passes ran on a **private** `ollama serve` on `127.0.0.1:11435`
(`NUM_PARALLEL=4`), and the system service was never reconfigured. "Differ"
counts records whose **canonical JSON** differs from the first serial pass of
the same session. Scripts printed counts and times only.

| Model | Architecture | Ollama runs it in parallel | 1 call | 2 calls | 4 calls | Differ at 2 / 4 |
|---|---|---|---|---|---|---|
| **`qwen3:8b`** | `qwen3` | yes | 83 s | 52 s (1.61×) | **43 s (1.96×)** | **2 / 0** of 48 |
| `gemma3:4b` | `gemma3` | yes | 142 s | 89 s (1.60×) | 70 s (2.03×) | **27 / 29** of 48 |
| `qwen3.5:2b` | `qwen35` | **no**: "model architecture does not currently support parallel requests" (ollama#14510) | 111 s | 111 s | 111 s | 0 / 0 |
| `llama3.2:3b`, `granite4.1:8b`, `ministral-3:8b`, `gemma4:12b` | `llama`, `granite`, `mistral3`, `gemma4` | yes | not measured | | | |

**Serial noise, the yardstick for "differ".** Three serial passes of
`gemma3:4b` on the one-slot system server differed from the first by 0, 2 and
0 records. A serial pass of `qwen3:8b` after its parallel passes differed by
0; one of `gemma3:4b` differed by 9. **0–2 of 48 is the band a model is
allowed.**

What this says:

1. **The gate is per model.** `qwen3:8b` passes, `gemma3:4b` fails by an
   order of magnitude, and `qwen35` can't be tried. A host-wide setting
   (the first draft's D1 and D3) would parallelise models it harms.
2. **Where Ollama refuses, calls queue.** For `qwen3.5:2b`, throughput stayed
   flat and median latency went 2.3 → 4.6 → 9.1 s. That is §2 h's timeout
   hazard, measured.
3. **VRAM contention hides the gain.** A first `qwen3:8b` attempt ran while
   the system service still held `gemma4:12b`. Only 6.3 of 7.8 GB fit in
   VRAM, and N=4 was *slower* than N=1 (196 s vs 146 s).
4. **A multi-slot server may disturb serial runs.** `gemma3:4b`'s 9-record
   serial difference was on the four-slot server. Stage 0b has to quantify
   this, because production would need `OLLAMA_NUM_PARALLEL > 1` on the
   system service for every model (§4.5).
5. **Not yet explained:** `qwen3:8b`'s closing serial pass took 110 s against
   83 s for the opening one. Stage 0b re-measures it.

### 1.2 Stage 0b results (2026-09-24)

**Method.** As in §1.1, with the script rebuilt from that description. A
fresh throwaway seed (48 records, synthetic codelist). Every model on 11434
was unloaded before each model under test, and `/api/ps` confirmed
`size_vram == size` before every pass (the script refuses to measure
otherwise). "Differ" is now always counted against the **first one-slot
serial pass** (§4.1 condition 1), not the same server's own first pass.
Retries and parse failures were 0 on every pass. Ollama 0.34.0. Digests:
`qwen3:8b` `500a1f067a9f`, `ministral-3:8b` `1922accd5827`, `granite4.1:8b`
`444af1c4b2fe`, `gemma3:4b` `a2af6cc3eb7f`, `gemma4:12b` `4eb23ef187e2`.

**Serial noise band (step 1).** Three serial passes on the one-slot system
service, which differed from the first pass by:

| Model | 1 call | Differ, passes 2 / 3 |
|---|---|---|
| `qwen3:8b` | 81.4 s | 0 / 0 |
| `ministral-3:8b` | 166.0 s | 0 / 0 |
| `granite4.1:8b` | 146.1 s | 1 / 2 |
| `gemma3:4b` | 153.9 s | 2 / 0 |
| `gemma4:12b` | 482.8 s | 3 / 2 |

**The gate, per model (steps 2 and 3).** Condition 2 was measured first, on a
fresh four-slot server that had served no parallel request yet. Condition 1
was measured after it.

| Model | Cond. 2: serial on 4 slots, differ ×3 | Cond. 1: differ at 2 / 4 calls | Throughput at 2 / 4 calls | Verdict |
|---|---|---|---|---|
| **`qwen3:8b`** | **0 / 0 / 0** | **0–1 / 0–1** | 1.5× / 2.3–2.5× | **passes** |
| `ministral-3:8b` | **6 / 6 / 6** | 4 / 5 | 1.77× / 2.57× | **fails 2 and 1** |
| `granite4.1:8b` | 0 / 1 / 2 | **15 / 14** | 1.78× / 2.65× | fails 1 |
| `gemma3:4b` | 0 / 2 / 0 | not re-run (27 / 29 in §1.1) | | fails 1 |
| `gemma4:12b` | 0 / 3 / 2, **identical pass for pass** to the one-slot passes | — / 4 (one pass) | — / 2.26× | passes 2; fails 1 narrowly |

What this says:

1. **`qwen3:8b` passes all three conditions.** Eight parallel passes (N = 2,
   3 and 4) differed from the one-slot baseline on 0–2 records, which is
   inside the band. Two further N=4 passes have times only, because a
   later pass with the same label overwrote their hash files. At N=3 it
   measured 2.14× (38 s), and at N=4 four of five passes took 32–36 s
   (2.3–2.5×).
2. **`ministral-3:8b` fails condition 2, and the failure is deterministic.**
   Its three serial passes on the four-slot server are identical to *each
   other* and differ from the one-slot baseline on **the same 6 records** each
   time. This is not extra noise. A four-slot server gives it a different,
   stable answer on 12.5 % of records. Serial runs made before the setting
   changed would not reproduce after it. Runs made after it would reproduce
   among themselves. Its parallel passes then differ from that four-slot
   serial answer on 7 and 6 records, so it fails condition 1 as well.
3. **`granite4.1:8b` is the opposite case.** Serial on four slots stays in
   its band, but parallel calls change 14–15 records. It can't join the map,
   but the server setting doesn't disturb it.
4. **§1.1 point 5 did not reproduce.** A closing serial `qwen3:8b` pass after
   all the parallel passes took 81.6 s on the four-slot server and 81.3 s on
   the one-slot one. The likeliest cause of the 110 s was the VRAM contention
   in §1.1 point 3. **A new outlier appeared instead:** the first N=4 pass of
   `qwen3:8b` took 59.1 s (1.38×), and four later N=4 passes took 32–36 s.
   None of them offloaded. This is unexplained, and the gate's 1.3× floor
   still holds for it.
5. **Loaded size, 1 → 4 slots (step 5):** `qwen3:8b` 5.58 → 7.50 GB,
   `ministral-3:8b` 5.64 → 7.47, `granite4.1:8b` 5.89 → 8.01, `gemma3:4b`
   2.88 → 3.75, **`gemma4:12b` 8.06 → 10.38 GB**. Each still fits in 16 GB on
   its own. Two of them together no longer do, which makes §4.5's unload
   step mandatory, not advisory.

6. **`gemma4:12b` is untouched by the server setting** (measured after Q5).
   Its one-slot noise is 0–3, not 0–2, but the *n*-th serial pass on four
   slots matches the *n*-th pass on one slot record for record (0 / 0 / 0).
   Whatever makes its passes wobble repeats the same way on both servers.
   At 4 calls it differs on 4 records from the first one-slot pass, and on
   at least 2 from every serial pass. That is just outside its band, from a
   single pass. It stays serial, and nothing in this plan needs more.

**Not measured:** condition 2 for `llama3.2:3b`. No recommendation uses it.
If it comes back into use, it needs the same three serial passes first.

### 1.3 Stage 4 results (2026-09-24)

**Method.** A throwaway 200-record seed (`seed_dev.py --records 200`,
synthetic codelist). Every model on 11434 was unloaded first. Both
evaluations ran on a private `ollama serve` on `127.0.0.1:11435` at
`NUM_PARALLEL=4`, which Stage 0b showed leaves both models' serial answers
unchanged. Each was launched through `EvaluationService.launch` and
`RunService.launch_runs` with an `InlineTaskRunner` and scored by the chained
job. Numbers were read from `RunService.progress`, `RankingService` and
`ResultsService`. They are identical except for `RA2_LLM_PARALLEL_CALLS`.

| Evaluation | Model | Pinned | Run | Macro-F1 [Wilson 95 %] | Median latency | Time per record |
|---|---|---|---|---|---|---|
| `{}` | `qwen3:8b` | 1 | **348.8 s** | 0.895 [0.870–0.905] | 1.72 s | 1.72 s |
| `{}` | `granite4.1:8b` | 1 | 641.0 s | 0.886 [0.861–0.897] | 3.12 s | 3.17 s |
| `{"qwen3:8b": 4}` | `qwen3:8b` | 4 | **146.7 s (2.38×)** | 0.895 [0.870–0.905] | 2.76 s ×4 | **0.72 s** |
| `{"qwen3:8b": 4}` | `granite4.1:8b` | 1 | 659.0 s | 0.886 [0.861–0.897] | 3.18 s | 3.25 s |

Whole evaluation: 990 s → 806 s. The serial one reproduces the eight-model
comparison exactly (`docs/performance.md` §4.1: 0.895 and 0.886).

1. **Scores: identical.** Every one of the six scored features has the same
   F1 and `n` in both evaluations, to four decimals, for both models. The
   plan asked for "within the Wilson interval" and "macro within 0.01".
2. **Answers: 5 of 200 raw outputs differ** for `qwen3:8b` between its run
   at 1 and its run at 4, and none of them moved a score. That's 1.2 per 48,
   inside Stage 0b's 0–2 band. Raw text is a stricter comparison than the
   gate's canonical JSON. `granite4.1:8b`, serial in both, differs on 0.
3. **Time per record checks against the wall clock.** 0.72 s × 200 = 144 s,
   against 146.7 s measured. The gap is the ramp-down, when fewer than four
   records are left.
4. **Caveat, seen in the browser check: the first call of a run includes
   loading the model**, so the mean, and with it time per record, is pulled
   up on a small corpus. On 48 records `granite4.1:8b` showed 3.84 s against a
   3.11 s median. On 200 it was 3.17 against 3.12, and at corpus scale it
   vanishes. Both models pay it, so it doesn't change which is cheaper
   unless one of them loads much more slowly. This is left as it is: it is
   what the run cost.

**Browser check** (`just dev-agent` with `RA2_LLM_BASE_URL` on the private
server and `{"qwen3:8b": 4}`, a 48-record seed in the agent's own temp dir):
the progress card read `8 / 48 · running`. Stop turned the row `interrupted`
with 8 kept, and Resume took it to `done`. The provenance line ended
`reasoning none · parallel calls 4`. The ranking showed `2.76 s ×4` and
`0.95 s` for `qwen3:8b`, no mark for `granite4.1:8b`, and the note under the
table.

## 2. What exists and what it means

| # | Where | What |
|---|---|---|
| a | [config.py:121](ra2/infra/config.py#L121) `run_concurrency` | Means **runs** (models) in parallel. §15.4 and plan-phase-3 F7 rule that out: two models sharing VRAM is slower than two in sequence. **This plan does not change that.** |
| b | [run_service.py:341](ra2/services/run_service.py#L341) | Refuses `run_concurrency != 1`. `tests/backend/services/run/test_guards.py` pins the refusal. Both stay. |
| c | `_extract_all` | One loop: resolve → call → commit, then the next record. `consecutive_endpoint_errors` assumes completion order equals dispatch order. |
| d | [evaluation_service.py:1002](ra2/services/evaluation_service.py#L1002), [ranking_service.py:246](ra2/services/ranking_service.py#L246) | `extraction.latency_ms` feeds the median latency in the progress card and the **Results ranking**. Per-call latency rises with parallelism even as throughput rises: 1.7 → 3.1 s at N=4 for `qwen3:8b`. |
| e | `_eta_ms` (both services) | Extrapolates from wall-clock `elapsed_ms / done`. Already correct under parallelism. |
| f | `session.py` | WAL, `busy_timeout=5000`. Concurrent short commits wait rather than raise. |
| g | `test_transaction_boundary.py::test_each_record_is_committed_before_the_next_model_call` | True only at N=1. The invariant it guards is "no transaction spans a call"; Stage 3 restates it at any N. |
| h | Ollama | Queues requests beyond what it serves in parallel, which is `OLLAMA_NUM_PARALLEL` or 1 for a refused architecture. **The queue wait counts against `RA2_LLM_TIMEOUT_S`**, and RA2 can't read either limit over the API. |
| i | `RankingRow` ([readmodels.py:1050](ra2/services/readmodels.py#L1050)) | One evaluation's ranking puts every model's median latency side by side as a tie-breaker. **With per-model parallelism, those numbers stop being comparable inside one table.** |
| j | `ranking_service.py:140` | `vram_bytes=0`, hard-coded; no VRAM column is rendered. Not this plan's defect, but §4.5's KV growth would make that number matter. |
| k | `EvaluationService._reject_infeasible` | Judges `fits_vram` from the model's size on disk. With N slots the loaded size grows by N KV caches: `qwen3:8b` 5.6 GB at 1 slot, 7.5 GB at 4. |

## 3. Decisions

**D1. A per-model setting, not one number.** `RA2_LLM_PARALLEL_CALLS` is a
JSON **map from model tag to call count**, e.g. `{"qwen3:8b": 4}`. The default
is `{}`: every model serial, which is today's behaviour. Values outside
`1..8` and empty tags are refused at construction. `run_concurrency` keeps its
meaning and its refusal.

*Why per model:* §1.1 point 1. *Why a map in `Settings` and not an evaluation
input:* whether a model tolerates batching is a **calibration of this host,
this Ollama and this model**, measured once by §4.1's gate. It isn't a
question an analyst asks per evaluation. An evaluation input would let two
evaluations of the same model differ by a number nobody chose on evidence.
*Why the tag:* the tag is what the analyst selects. The run already pins the
digest, so a re-pull that changes the digest is visible in provenance
(§8 lists auto-invalidation as out of scope).

**D2. Pinned on the run at launch.** New column `run.llm_parallel_calls`,
NOT NULL, written by `EvaluationService._new_run` as
`settings.llm_parallel_calls.get(model_tag, 1)`. **Resume executes at the
pinned value**, not at the current map, so one run's rows never mix two
latency regimes. The migration backfills `1` onto existing rows: every run so
far executed serially, so this records a fact and repairs nothing.

**D3. Time per record joins latency in the ranking.** `RankingRow` gains
`ms_per_record` and `parallel_calls`, both **reported, never scored** (SD20).
They render beside median latency, and a latency cell whose run had
`parallel_calls > 1` is marked "×N". The cost per record is what the analyst
actually pays for, and it stays comparable across parallelism; latency
doesn't (§2 i).

*Revised in Stage 1.* The first draft had `records_per_minute`, committed rows
over run elapsed time. That figure is wrong for any resumed run:
`RunService._start` restamps `started_at` on every start, and `extraction` has no
timestamp, so it divides all of a run's rows by its last stretch. The figure
is now `mean(latency_ms) ÷ llm_parallel_calls`, which is Little's law with N
calls kept in flight. It reads only rows the median already reads, survives
Resume, and stays honest where Ollama queues rather than batches, because the
wait is inside each latency. Checked against §1.2: 48 × 2.72 s ÷ 4 = 32.6 s
predicted, 32.4 s measured. SD38 has the full argument.

**D4. One code path.** N workers pull from the pending list. N=1 is the same
code with one worker, not a separate serial branch. There's no test-only
branch either (Do-NOT #12).

**D5. Everything per record stays per record.** Each worker resolves the
prompt (its own transaction, closed), calls, and commits one `extraction` and
its children (its own transaction). Nothing batches across records, and no
transaction spans a call. §15.3 and plan-phase-3 R3 are unchanged.

**D6. No model enters the map without passing §4.1's gate.** The measurement
behind each entry is recorded in `docs/performance.md` §5.3: model, digest,
Ollama version, date, and differ counts. `config.py`'s docstring for the
setting says so and points there. An entry without a measurement is a
configuration error that code can't catch, so the rule lives where the
entries are written.

## 4. The design, in detail

### 4.1 The gate, per model

llama.cpp batches concurrent sequences, and batched kernels aren't guaranteed
to produce the same floating-point results as batch size 1. At a fixed seed
that can flip a token, and "a re-run is a check, not a new sample"
(§15 F9) would stop holding *across* parallelism settings.

A model **passes** at N when, over the 48-record seed:

1. its N-call pass differs from the **one-slot** serial baseline on no more
   records than two one-slot serial passes differ from each other (the
   serial-noise band, 0–2 of 48 so far); **and**
2. its serial pass on the **N-slot** server is also inside that band (§4.5);
   **and**
3. throughput at N is at least **1.3×** that at 1. Below that, the gain
   doesn't pay for the provenance and display this plan adds.

Condition 1 compares against the *one-slot* server, not the private server's
own first pass as Stage 0 did. That's the comparison production would make.

### 4.2 The worker pool

`_extract_all` keeps its signature. Inside:

- `pending` becomes an iterator shared by `plan.parallel_calls` worker
  coroutines in one `asyncio.TaskGroup`. Dispatch order stays scope order
  (`test_the_prompt_is_resolved_once_per_record_in_scope_order` holds).
  Commit order is completion order. Nothing reads extractions in insertion
  order, and resume keys on holes (`UNIQUE (run_id, record_id)`).
- Shared counters (`done`, `endpoint_failures`, `endpoint_attempts`,
  `consecutive_endpoint_errors`) are mutated only between awaits on one
  event loop. No lock is needed.
- **Endpoint-error budget.** "Consecutive" is counted in **completion
  order**, and any success resets it. When the budget is reached, workers
  **stop taking new records**. Calls already in flight finish and commit if
  they succeed. At most N−1 more calls are spent after the budget trips,
  which is bounded and appears in the count.
- **An unexpected failure** in one worker: the `TaskGroup` cancels the
  others and raises an `ExceptionGroup`. `_extract_all` re-raises the first
  exception and logs the rest by type (ids and counts only,
  `data-handling.md` §5.1), so `execute_run`'s `except Exception` and
  `_error_text` see what they see today.
- **Cancel** is unchanged. `cancel()` cancels the run's task, which cancels
  the `TaskGroup` and every in-flight call. Committed rows stay, the run is
  `interrupted`, and Resume continues. `_finish_cancelled` still writes from
  the caller's task.
- **Progress** stays `reporter.report(done, total)` after each commit, with
  `done` re-read from committed rows (§15 F6). The value is monotonic under
  any completion order.
- The run-start log line gains `parallel=%d`, beside `timeout=%ds`: both
  decide how long the next line can take.

### 4.3 What the adapter needs

Nothing. `openai.AsyncOpenAI` is safe to share across coroutines, and the
SDK's default connection limits exceed 8. `trust_env=False` and
`follow_redirects=False` (`SD27`) are properties of the one client and don't
change.

### 4.4 The queue hazard (§2 h, measured in §1.1 point 2)

A map entry above what Ollama will serve in parallel doesn't fail. It queues,
and the queue wait runs against `RA2_LLM_TIMEOUT_S`, which isn't retried. RA2
can't read `OLLAMA_NUM_PARALLEL`, and it can't read Ollama's per-architecture
refusals. D6 makes the gate measurement a precondition of every entry, and the
gate would catch a refused architecture (its throughput stays at 1.0×). The
run-start log prints the pinned value.

### 4.5 Ollama's setting is server-wide

`OLLAMA_NUM_PARALLEL` applies to **every** model the system service loads,
not just those in RA2's map. Raising it has three effects:

| Effect | Measured | Consequence |
|---|---|---|
| Serial runs of *other* models may change | `gemma3:4b` serial on the four-slot server: 9 of 48 differ (once, after parallel passes) | **Measured in §1.2:** `ministral-3:8b` moves by 6 of 48 (deterministic); `qwen3:8b`, `granite4.1:8b`, `gemma3:4b` and `gemma4:12b` stay in band. §9 Q5 |
| Every loaded model reserves N KV caches | `qwen3:8b` 5.6 → 7.5 GB, `gemma4:12b` 8.1 → 10.4 GB at 4 slots (§1.2 point 5) | Larger models spill to CPU sooner. On 16 GB, `gemma4:12b` (8.1 GB at 1 slot) is the one to check |
| Other models left in VRAM squeeze the next | §1.1 point 3: the gain vanished | Ollama's `keep_alive` decides residency. Stage 4's runbook note says to unload before a parallel run; §8 lists a residency check |

## 5. Stages

### Stage 0 — measure the gain ✅ (2026-09-23)

Done. The results are in §1.1. The go-ahead for `qwen3:8b` is conditional on
Stage 0b.

### Stage 0b — measure the side effects (no repo changes) · **go/no-go** ✅ (2026-09-24)

**Done.** Results are in §1.2 and `docs/performance.md` §5.3. The gate result
for each model is recorded there, as D6 asks. **Outcome:** condition 2 fails
for `ministral-3:8b` only, so go/no-go depended on whether it stays in use.
**Go**, by §9 Q5 (a): `granite4.1:8b` replaces it, and `gemma4:12b` passed
condition 2 afterwards (§1.2 point 6).

Private `ollama serve` on `127.0.0.1:11435` as in Stage 0, so the system
service stays untouched. **Unload every model on 11434 first** (§1.1 point 3),
and confirm with `/api/ps` that the model under test is fully in VRAM before
each pass. The same script, extended to compare against a baseline saved from
the one-slot server.

1. **Baseline.** On the one-slot system service, three serial passes each of
   `qwen3:8b`, `ministral-3:8b`, `granite4.1:8b` and `gemma3:4b`: the
   serial-noise band per model.
2. **Condition 1.** On the four-slot server, `qwen3:8b` at N = 2 and 4,
   compared with (1). `ministral-3:8b` and `granite4.1:8b` too: they're the
   recommended second opinions, and each could join the map.
3. **Condition 2.** On a **fresh** four-slot server, three serial passes of
   each model in (1), compared with (1). This is the one that can stop the
   plan.
4. Re-measure the unexplained 110 s serial pass (§1.1 point 5).
5. `gemma4:12b` loaded size at 4 slots, from `/api/ps`: does it still fit?

**Done when** the tables are in §1.1 and `docs/performance.md` §5.3, and each
model's gate result is recorded as D6 asks. **Stop** if condition 2 fails for
any model that stays in use: a server-wide setting that changes serial runs
costs more reproducibility than the time it saves. §8 lists the fallback
(a second endpoint) as a separate plan.

### Stage 1 — the contract, first ✅ (2026-09-24)

**Done.** `sw-design.md` §10, §15.2, §15.4, §15.8, §16.5 and **SD38**, plus
`contracts/amendments/feat-parallel-calls.md`. Two things changed from the
plan: D3's figure (see D3), and the pin is shown on the provenance card only,
not on `RunView`, because it is an input and the runs table shows no inputs.
The amendment also records a gap it doesn't fix: `RA2_LLM_REASONING_EFFORT`
is missing from `tests/conftest.py`'s scrub list.


- `sw-design.md` §15.4: the "Serial" bullet splits into *models serial*
  (unchanged) and *records: up to the model's `RA2_LLM_PARALLEL_CALLS` entry
  in flight, each in its own transactions*. §15.8's "Concurrency above 1"
  bullet narrows to run concurrency. The provenance list gains **parallel
  calls**. A new `SD` row covers D1–D6. §16's ranking section gains D3's two
  reported columns.
- `contracts/amendments/feat-parallel-calls.md` for the frozen files (§6).

**Done when** the design says what Stages 2–3 build, before they build it.

### Stage 2 — setting, column, pin, display ✅ (2026-09-24)

**Done.** The amendment is applied and recorded in `CONTRACTS.md` under
"Parallel calls". Revision `68c8b2a80ca9` was written by hand, not
autogenerated, because `just revision` would have needed a database and its
default data dir is `./var`. It passes `alembic check`, downgrade and
re-upgrade on a throwaway database. Nothing reads `_RunPlan.parallel_calls`
yet; Stage 3 does. Where the code differed from the list below: the ranking
tab's `×N` mark comes with a note under the table (`PARALLEL_NOTE`), rendered
only when some row ran at N > 1, because rule 4 of the rules text is the
design's verbatim copy. The added tests beyond the named ones: the bounds
themselves, the JSON environment form, and a serial ranking rendering no
mark.


- `Settings.llm_parallel_calls: dict[str, int] = {}`, validated in a
  `model_validator` beside `_check_reasoning_effort` (values `1..8`, no empty
  tag). Its docstring carries D6 and §4.4–4.5. The env name goes into
  `tests/conftest.py`'s scrub list (**frozen**, amendment).
- One Alembic revision: `run.llm_parallel_calls INTEGER NOT NULL`, backfilled
  `1`. The migration author for this branch is its implementer. No parallel
  heads.
- `EvaluationService._new_run` pins `map.get(tag, 1)`. `_RunPlan` carries it
  from the row.
- `ProvenanceView`, `ProvenanceResponse` and the reproducibility card show it
  beside temperature and seed.
- `RankingRow` and `RankingRowResponse` gain `ms_per_record` and
  `parallel_calls` (D3). The ranking tab renders time per record with
  `format_latency_ms` (SD37) and the "×N" latency mark.

**Done when** these pass:

- `test_settings_refuse_parallel_calls_outside_1_to_8`
- `test_settings_refuse_an_empty_model_tag`
- `test_launch_pins_each_models_own_parallel_calls` (one evaluation, a mapped
  model and an unmapped one: 4 and 1)
- `test_migration_backfills_parallel_calls_as_one`
- `test_ranking_reports_time_per_record_and_parallel_calls` (a run at 1 and a
  run at 4: `ms_per_record` is mean latency ÷ N, and neither moves `rank`)
- `tests/ui` assertions for the provenance value and the ranking's "×N" mark

`just lint` and `just test` must be green.

### Stage 3 — the pool ✅ (2026-09-24)

**Done.** `_extract_all` now starts `min(parallel_calls, pending)` workers in
one `TaskGroup`, and the loop body is `_extract_worker`. The shared counters
live on a `_RecordLoop` dataclass. The table is green, and so are `just lint`
(the old mypy error at `tests/e2e/conftest.py:97` is gone) and `just test`
(2548 passed, twice). Where it differed from the plan:

- **The N=1 commit-sequence test is kept, not replaced.**
  `test_each_record_is_committed_before_the_next_model_call` states a
  stricter property that is true at N=1, so it stays, with a docstring
  pointing at the any-N form.
- **`test_no_transaction_spans_a_model_call` holds all N calls, then counts
  the pool's checked-out connections**, which must be 0. "No session open
  while *any* call is awaited" can't be observed at N=3 in general, because a
  sibling may be committing. With every worker inside `extract`, none can be.
- **Deterministic ordering, not timing.** The tests use a scripted client
  (`ScriptedCalls` in `test_parallel_calls.py`) where each call, by the order
  it began, answers, fails, raises, or waits for the test to release it. The
  budget test therefore pins the exact story: 6 calls, 2 rows, 4 counted
  failures, 2 calls past the trip (N−1).
- **Ceilings where only timing could prove a peak.** The unmapped-model and
  resume tests assert at most 3 / exactly 1 and at most 2, with a 50 ms hold
  so a wrong ceiling shows. That N is actually *reached* is proven by the
  exact-N test with held calls. Exact peaks behind a 10 ms sleep failed once
  under load.
- **Progress is never allowed to go backwards.** Two workers' `COUNT` reads
  can resolve in either order, so `done` is `max(previous, count)`.
- **Mutation-checked.** With the code broken four ways (a session held across
  the call, no stop check, the map read instead of the pin, always one
  worker), the tests fail. That check found a real defect in the first draft
  of the tests: a held test that failed hung teardown instead of failing.
  Every held test now releases *and waits for the run* in a `finally`.
- Added: `test_the_run_start_log_line_names_the_parallelism`.

§4.2 in `run_service._extract_all`. Tests in `tests/backend/services/run/`,
driven by the gated fake client `test_in_flight.py` already uses:

| Test | Asserts |
|---|---|
| `test_parallel_calls_keeps_exactly_n_calls_in_flight` | N=3: three calls held open at once, never a fourth |
| `test_an_unmapped_model_runs_serially` | Same evaluation, second model not in the map: one call at a time |
| `test_no_transaction_spans_a_model_call` (replaces §2 g's test) | At N=1 and N=3: no session is open while any call is awaited |
| `test_a_row_and_its_children_are_committed_together` | Unchanged, now parametrised over N |
| `test_parallel_and_serial_runs_store_identical_values` | Deterministic fake: N=1 and N=3 produce the same `extraction_value` sets. This tests the code; Stage 0b tests the model |
| `test_endpoint_budget_stops_dispatch_and_lets_in_flight_calls_commit` | Budget trips, no new record starts, in-flight successes commit, run `interrupted` with the right count |
| `test_cancel_cancels_every_in_flight_call` | N=3: all three calls see `CancelledError`, committed rows kept, Resume completes the run |
| `test_an_unexpected_failure_cancels_siblings_and_fails_the_run` | One worker raises: others cancelled, run `failed` with that error, commits kept |
| `test_resume_runs_at_the_pinned_parallelism` | Run pinned at 2, map now says 4: at most two in flight |
| `test_run_concurrency_above_one_is_refused_not_silently_ignored` | Unchanged |

**Done when** the table is green and `just lint` and `just test` pass. The
pre-existing mypy error at `tests/e2e/conftest.py:97` is unrelated; say so if
it's still there.

### Stage 4 — verify end to end, at the score level ✅ (2026-09-24)

**Done**, on a private four-slot server (`127.0.0.1:11435`), so the system
service was never reconfigured. The results are in §1.3 and
`docs/performance.md` §5.3. Every per-feature F1 and both macro-F1s are
**identical to four decimals**, not just inside their intervals. `qwen3:8b`
took 349 s → 147 s for 200 records (2.38×). The browser check under
`just dev-agent` passed: progress card, Stop at 8/48, Resume to done,
`parallel calls 4` on the provenance line, `×4` and the note on the ranking.
The Status line can't name a merge commit yet, because the branch isn't
merged. That, and switching the system service, are David's (§7).

Throwaway 200-record seed. The system service, or a private server, runs at
the `OLLAMA_NUM_PARALLEL` Stage 0b approved, with all models unloaded first.
`RA2_LLM_PARALLEL_CALLS='{"qwen3:8b": 4}'`.

1. **Two evaluations**, identical except the map: `{}` and
   `{"qwen3:8b": 4}`. Both use `qwen3:8b` and `granite4.1:8b` (§9 Q5). Every
   per-feature F1 must match within its Wilson interval, and macro-F1 within
   0.01. This checks at the *score* level what Stage 0b checked at the
   JSON level.
2. Record wall times. Expected: `qwen3:8b` ~6 min → ~3 min for 200 records.
3. `just dev-agent`: the progress card, the provenance panel, the ranking's
   throughput column and "×4" mark, and Stop mid-run then Resume.

**Done when** (1)'s comparison and (2)'s times are in §1.1 and
`docs/performance.md` §5.3, the performance doc's "Parallel calls: not
implemented" row is updated, and this file's Status line names the merge
commit.

## 6. Frozen files touched — amendments

| File | Change |
|---|---|
| `ra2/infra/config.py` | `+ llm_parallel_calls: dict[str, int]` and its validator |
| `ra2/persistence/models.py` | `+ Run.llm_parallel_calls` |
| `ra2/services/readmodels.py`, `ra2/api/schemas.py` | `+ llm_parallel_calls` on the provenance view and response; `+ ms_per_record`, `parallel_calls` on `RankingRow` and its response |
| `tests/conftest.py` | `+ "RA2_LLM_PARALLEL_CALLS"` in the env scrub |

All go in `contracts/amendments/feat-parallel-calls.md`, and each is listed
in `CONTRACTS.md`'s change log in the style of the `llm_reasoning_effort`
entry. `ranking_tab.py` and `ranking_service.py` belong to whoever owns
Results in the implementing wave (`plan-m0-m5.md` §4).

## 7. Host configuration (outside the repo)

**The steps are in [`docs/performance.md` §5.4](docs/performance.md)**, for
Linux, Windows and macOS: `OLLAMA_NUM_PARALLEL=4` on Ollama,
`RA2_LLM_PARALLEL_CALLS={"qwen3:8b": 4}` in RA2's `.env`, and how to check
both took effect.

**Correction (2026-09-24).** An earlier version of this section said this
host's `ollama.service` already had an `override.conf` setting
`OLLAMA_KEEP_ALIVE=-1`. It has no drop-in at all. `systemctl cat ollama` shows
the unit alone, and `/api/ps` reports models expiring 5 minutes after use,
which is Ollama's default. §5.4 recommends keeping that default: reloading
`qwen3:8b` costs seconds per run, and `-1` would hold GPU memory
indefinitely. One Ollama server evicts its own idle models when a new one
needs the room, so two models at four slots that no longer fit together
(§1.2 point 5) are handled. The contention in §1.1 point 3 came from *two*
servers sharing one GPU.

## 8. Not in this plan

- **Runs in parallel** (`run_concurrency > 1`). Still refused, for §2 a's
  reason.
- **Detecting Ollama's refusals** from `/api/tags`'s `family` and refusing a
  map entry for `qwen35` at construction. It's tempting, but it hard-codes
  another project's list, which will change (ollama#14510). D6's gate covers
  it.
- **Auto-invalidating a map entry** when a tag's digest changes. The run
  records the digest, so a changed digest is visible; making it *enforced*
  needs a digest in the map and a refusal path. A follow-up if re-pulls
  happen.
- **A residency check** (`/api/ps`: is the model fully in VRAM at run start?)
  that would turn §1.1 point 3 into a finding instead of a silent slowdown.
  It's worth doing for serial runs as well, so it's a plan of its own.
- **A second Ollama endpoint** for parallel models only, as the fallback if
  Stage 0b condition 2 fails. That means per-model endpoints and a second
  loopback guard, which is a separate design.
- **Adaptive parallelism** (raising N until latency degrades). One pinned,
  measured number is reproducible; a controller isn't.

## 9. Decisions for David

| # | Question | Recommendation |
|---|---|---|
| Q1 | Adopt `qwen3:8b` as an evaluation model? | **Yes**, alongside `ministral-3:8b` or `granite4.1:8b` (`docs/performance.md` §4.5). Without a parallel-capable model in use, this plan has nothing to speed up |
| Q2 | Per-model map in `Settings` (D1) rather than one number or an evaluation input? | **Yes**, for the reasons under D1 |
| Q3 | If Stage 0b condition 2 fails, stop, or plan a second endpoint? | **Stop.** ~45 min saved on a 3 000-record run isn't worth serial runs that stop reproducing, or a second loopback surface |
| Q4 | Run Stage 0b now? About 1 h of GPU time, on a private server, no repo changes | **Yes**. It's the cheapest way to learn whether Stages 1–4 happen at all |

**Answered 2026-09-23:** Q1 **yes**, `qwen3:8b` is adopted. Q2 **yes**, a
per-model map. Q4 **no, not now**: Stage 0b is deferred, so Stages 1–4 stay
blocked behind it. Q3 is open and is explained in plain terms to David.

**2026-09-24:** Stage 0b ran at David's request, so Q4 is settled. It raised a new
question:

| # | Question | Recommendation |
|---|---|---|
| Q5 | `ministral-3:8b` fails condition 2. Raising `OLLAMA_NUM_PARALLEL` to 4 gives it a different but stable answer on 6 of 48 records (§1.2 point 2). Which applies: (a) drop `ministral-3:8b` and make `granite4.1:8b` the second opinion, which is unaffected by the server setting (point 3), then go ahead; (b) keep `ministral-3:8b` and accept a one-time break in its reproducibility; or (c) stop, as Q3's recommendation says? | **(a)**. `docs/performance.md` §4.5 already names either model as the second opinion. With `granite4.1:8b`, every measured model that stays in use passes condition 2, and `qwen3:8b` passes all three. Before the system service changes, condition 2 still has to be measured for `gemma4:12b` if it stays in use (§1.2, "Not measured") |

**Answered 2026-09-24:** Q5 **(a)**. `granite4.1:8b` replaces
`ministral-3:8b` as the second opinion, and `ministral-3:8b` leaves the
recommended set. Whether it can stay on the host is a separate question: it
can be pulled, but any evaluation that uses it after the server setting
changes won't reproduce one from before. `gemma4:12b`'s condition 2 was
measured afterwards and passes (§1.2 point 6).

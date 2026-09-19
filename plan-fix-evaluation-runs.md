# plan-fix-evaluation-runs.md — the evaluation run: honesty, control, cost

**Status.** Written 2026-09-19 against `03bc9fe`, from a reproduced defect on
the development seed. Branch `fix/evaluation-timeout-and-progress`.
Authority as always: `mvp-spec.md` on *what*, `sw-design.md` on *how*
(CLAUDE.md). Where this plan proposes changing a frozen file it says so and
names the amendment; nothing here edits one.

---

## 1. What went wrong, reproduced

Launching the first evaluation on the seeded corpus (`just reset-seed`,
12 records, the two seeded features) leaves the Evaluation screen locked in
`In progress` at `0 / 12 · running`, with a run in the table whose id overlaps
the Model column, and no further change for roughly twenty minutes.

Measured against the endpoint on the reporting host — `qwen3.5:latest`,
9.7 B Q4_K_M, `capabilities: [completion, vision, tools, thinking]`, no NVIDIA
GPU so inference is CPU-bound:

| Call | Prompt | Elapsed |
|---|---|---|
| cold | the two seeded features, one sentence of narrative | **136 s** |
| warm (model resident) | identical | **126 s** |

Almost all of it is the model's `reasoning` field. `Settings.llm_timeout_s`
is **120**. So on this host every call times out, always.

What follows from that, in the code as it stands:

1. `APITimeoutError` subclasses `openai.APIConnectionError`, so
   `ollama_client._is_retryable` returns `True` and the call is retried
   `llm_max_retries` (2) more times. Temperature is 0 and the seed is fixed,
   so each retry is a deterministic repeat of work already known to exceed
   the bound.
2. Three attempts later the adapter raises
   `LlmEndpointError(EndpointStatus.UNREACHABLE)`. **No row is written** —
   correct, and what `pending_record_ids` is specified to find.
3. `run_service._extract_all` tolerates `_MAX_CONSECUTIVE_ENDPOINT_ERRORS`
   (3) such records before breaking, then marks the run `interrupted` with a
   message naming the endpoint as unreachable.

Roughly 9 × ~130 s ≈ 20 minutes of a motionless screen, ending in a diagnosis
that is **false**: the endpoint answers perfectly well, it is slower than the
bound. An analyst reading "unreachable" goes to look at Ollama, the port and
the firewall — none of which is the problem.

### 1.1 Why the screen could not say so

Five separate gaps, each independently a defect:

| # | Where | What |
|---|---|---|
| a | `ui/components/progress_card.py` `_status_text` | The `RUNNING` branch renders counts and an ETA only. `_eta_ms` returns `None` until one record has committed, so a run that has committed nothing renders `0 / 12 · running` and an empty bar — forever. `elapsed_ms` **is already in `RunProgressView` and already computed for running runs**; it is simply not rendered. mvp-spec.md **N6** asks for "progress is visible". |
| b | `persistence/repositories/run_repo.py` `sum_retries` | Sums `extraction.retry_count` over **committed** rows. A record whose attempts were exhausted writes no row, so its retries are counted nowhere. mvp-spec.md §10.4 wants retries "bounded, counted, **and visible**"; that holds only for records that succeed. |
| c | `ui/views/evaluation_view.py` `_status_marker` | Returns `"DEV"` for every `is_dev` run that is not `FAILED`. The seed is 12 records and `dev_record_max` is 50, so **every** run off the seed is dev and the Status column is a constant. Its own docstring names the ambiguity and resolves it with `data-status` attributes *for tests*, leaving the human with nothing. |
| d | `ui/views/evaluation_view.py` `_render_run_id` | A 36-character UUID in a 74 px `table-layout:fixed` cell with no clipping. Fixed layout does not clip — hence the overlap. `.td-clip` exists in `theme.py`, added for precisely this defect in the Mismatches table, and this column does not use it. |
| e | `ui/views/evaluation_view.py` `_render_status` | Offers `discard` only when the run is **not** `queued`/`running`, and `RunService` has no cancel path at all. There is no way to stop a running run. This is what turned a misconfiguration into a twenty-minute lock-in with no exit but killing the process. |

### 1.2 The poll violates a documented invariant

`EvaluationService.connection_status` carries this, verbatim:

> Re-checked on view load and when the settings dialog's "refresh" is pressed
> — **never on a timer** (plan-phase-3.md C3).

`evaluation_view._start_polling` runs `ui.timer(0.2, poll)` and `poll` calls
`reload()`, which calls `evaluation.get()`, which calls `connection_status()`
**and** `_model_choices()`. Both reach `/api/tags`.

So for the whole duration of a run the UI fires **ten HTTP requests per second
at the very endpoint the worker is waiting on**, and probes `pynvml` five
times a second — against a CPU-bound Ollama mid-generation. plan-phase-3.md
C3 forbids exactly this.

No test catches it. `StaticModelCatalog.reachable_calls` exists for this claim
and is asserted at the *service* layer, where the service is being called
legitimately; it is the timer that is wrong, and no UI-layer test counts.

---

## 2. Two facts that shape the plan

**Cancellation needs no migration and no new run status.** `run.status` is
`sa.String(length=16)` with no `CHECK` constraint (phase-3 migration), so an
enum member would be free — but none is needed. `INTERRUPTED` already means
*stopped, partial work kept, resumed only by an explicit human act*;
`_finish` already withholds `finished_at` for it; `RunView.is_resumable`
already keys off it. A user-stopped run **is** that state. The distinction
from "the process died under it" lives in `run.error`, exactly as
`_ERROR_INTERRUPTED_BY_RESTART` does today, and the wording lives in `ui/`'s
rendering table (CLAUDE.md: findings, not prose).

CLAUDE.md names one migration author per phase and phase 5 expects no
revision. **This plan needs no Alembic revision.** Said explicitly so a later
reader does not have to re-derive it.

**The test harness cannot express any of the new behaviour yet.**
`FakeLLMClient` can fail a call but cannot make one slow or make one block,
and the run-service suite is wired to `InlineTaskRunner`, which drives work to
completion in a joined thread before `submit()` returns — where cancellation
is meaningless. Stage 0 exists for that reason and leads.

---

## 3. The stages

Six stages. Each is independently shippable and independently green
(`just lint` and `just test` in the worktree).

### Stage 0 — the harness, first

Three of the five remaining stages cannot be tested without it.

| File | Change |
|---|---|
| `tests/fixtures/fake_llm.py` | `FakeLLMClient(delays={i: seconds})` — a call that takes measurable time; `gate` / `gate_from` — a call that blocks until the test releases it; `wait_until_called(n)` so a test can synchronise on a call having *started* without racing. |
| `tests/backend/services/run/conftest.py` | An `AsyncioTaskRunner` fixture beside the existing `InlineTaskRunner`, and a `task_runner` override on `make_run_service`. Cancellation is only observable on a task genuinely in flight. |

`tests/conftest.py` is frozen and constructs `FakeLLMClient()` with no
arguments, so every addition is a keyword with a default that reproduces the
existing behaviour exactly — the rule the fixture's own docstring already
states. **No amendment.**

**Done when** a test can start a run, assert it is `running` with `done == 0`
while a call is in flight, release the gate and assert it completes.

### Stage 1 — the timeout tells the truth

The reported bug. Ships value alone.

| Step | File | Change | Contract |
|---|---|---|---|
| 1a | `ra2/infra/ollama_client.py` | Split `APITimeoutError` out of `_is_retryable`; raise on the first one. A connection *refusal* stays retryable. | not frozen |
| 1b | `ra2/domain/llm.py` | `+ EndpointStatus.TIMED_OUT` | **amendment** |
| 1c | `ra2/services/run_service.py`, `ra2/ui/` | The interrupted run's error carries the *code*; the sentence naming `RA2_LLM_TIMEOUT_S` lives in `ui/`'s rendering table | — |
| 1d | `ra2/infra/config.py` | `llm_timeout_s: 120 → 600` | **amendment** |

The argument for 1a is already written in this repo: `run_service`'s module
docstring says a parse failure is never retried because temperature and seed
are fixed. A timeout on that same fixed call is the same argument, never
carried across.

*Shim while 1b is pending:* the adapter keeps raising `UNREACHABLE` and
carries the distinction in the message; the guard test is
`xfail(reason="amendment: fix/evaluation-timeout-and-progress")`.

**Tests**

- `tests/backend/infra/test_ollama_client.py` — a timing-out endpoint is
  called **once** and raises `TIMED_OUT`; a refusing endpoint is still called
  `max_retries + 1` times (the positive control the file's existing eleven
  tests already establish as the pattern).
- `tests/backend/services/run/test_guards.py` — a client raising `TIMED_OUT`
  leaves the run `interrupted`, asserted on the code, never on message text.

### Stage 2 — the UI tells the truth while running

Independent of Stage 1. Smallest diff, largest perceived change.

| Step | File | Change |
|---|---|---|
| 2a | `ui/components/progress_card.py` | Render `elapsed_ms` on the `RUNNING` branch: `0 / 12 · running · 4 m`, ETA appearing once there is something to extrapolate from. No new field, no service change. |
| 2b | `ui/views/evaluation_view.py` | `_status_marker` → status word **and** a `DEV` chip. Row tint and `data-status` / `data-dev` unchanged. |
| 2c | `ui/views/evaluation_view.py`, `services/readmodels.py` | `RunView.ordinal` → render `run 1`, matching the naming the discard dialog and mismatch lists already use. `.td-clip` on every fixed-width cell in that table. |

2b departs from `design/prompt-evaluation/README.md` §2, which draws `DEV` as
*replacing* the status word — a CONTRACTS.md design deviation, with the
reasoning from §1.1 c. 2c needs a **`readmodels.py` amendment**.

**Tests**

- `tests/ui/test_components.py` — a `RUNNING` card with `done=0` renders
  elapsed and no ETA.
- `tests/ui/test_evaluation_view.py` — a dev run that is `running` and a dev
  run that is `interrupted` render **different** status cells. They do not
  today; this is the assertion that was missing.
- `tests/e2e/test_j10_evaluation.py` — the five column widths still hold and
  no cell overflows its box.

### Stage 3 — the poll stops hammering the endpoint

Independent. This is the C3 violation of §1.2.

| Step | File | Change |
|---|---|---|
| 3a | `ui/views/evaluation_view.py` | Split `reload()` into `reload()` (everything, on view load and user action) and `refresh_progress()` — runs and progress only, **no `catalogue()`, no `connection_status()`, no GPU probe**. The timer calls the latter. |
| 3b | same | Back the interval off: 0.2 s for the first seconds of a just-submitted job, then a ladder to ~2 s. A 126 s-per-record run does not need five redraws a second. |

**Tests**

- `tests/ui/test_evaluation_view.py` — **the C3 gate**: across N timer ticks
  during an active run, `StaticModelCatalog.reachable_calls` and
  `.models_calls` stay at their view-load value. This assertion exists at no
  layer today. The counters are already on the double, put there for this
  claim.
- The same test pins that progress *does* advance across ticks, so 3b cannot
  be satisfied by disabling the timer.

### Stage 4 — fail fast on the first record

Depends on Stage 1 (needs `TIMED_OUT` to tell "misconfigured" from "flaky")
and Stage 0.

`_MAX_CONSECUTIVE_ENDPOINT_ERRORS = 3` treats the first record like any other.
But a run whose *first* record fails at the endpoint has never worked — that
is a configuration verdict, not flakiness. Stop after one; keep the tolerance
of three for failures after at least one record has committed.

This is what makes 1d's raised default painless: worst case falls from 30
minutes to 10.

It contradicts a deliberately documented constant, so that constant's
docstring changes in the same commit and the reasoning goes in CONTRACTS.md.

**Tests** (`tests/backend/services/run/test_guards.py`, asserting
`FakeLLMClient.call_count`)

- First record fails at the endpoint → exactly **one** call, run `interrupted`.
- Record 1 commits, then three consecutive failures → three calls before
  stopping. The existing tolerance survives.

### Stage 5 — the user can stop a running run

The largest item. Depends on Stage 0. Best done as its own branch: it is the
only stage touching a frozen protocol and the only one with a concurrency
trap.

**The structural problem first.** `_submit` creates **one** `TaskRunner` job
covering every run in the evaluation, executed serially. Cancelling "a run" at
task level would cancel the whole evaluation. So `_execute_serially` runs each
`execute_run` as its own inner `asyncio.Task`, and one run can be cancelled
while the job proceeds to the next model.

| Step | File | Change | Contract |
|---|---|---|---|
| 5a | `ra2/infra/tasks.py` | `+ TaskRunner.cancel(task_id)`; `AsyncioTaskRunner` cancels the `asyncio.Task` it already holds; `InlineTaskRunner.cancel` is a no-op — its work is complete before `submit()` returns. | **amendment — frozen protocol, raise early** |
| 5b | `ra2/services/run_service.py` | Per-run inner task; `RunService.cancel(run_id)`. | signature addition → CONTRACTS entry |
| 5c | `ra2/services/run_service.py` | `execute_run` catches `asyncio.CancelledError` **separately** from `except Exception` — it is a `BaseException`, so today it escapes and leaves the row `running` — writes `INTERRUPTED` with a distinct error constant, and **re-raises**. | — |
| 5d | `ui/views/evaluation_view.py` | A `Stop` action in the status cell for `queued` / `running` runs — the one case `_render_status` deliberately leaves empty today. | CONTRACTS entry, same shape as the `discard` row action already recorded |
| 5e | `ra2/api/v1/runs.py` | `POST /{run_id}/cancel`, mirroring the existing `POST /{run_id}/resume`. | — |

**The trap, written down now because it will bite.** Once a task is cancelled,
every subsequent `await` inside it can re-raise `CancelledError` immediately —
including the `_finish()` write that records the cancellation. That write must
be wrapped in `asyncio.shield()`, or the run is left `running` and only
`_reclaim` rescues it, with the wrong message. This is the single most likely
way for Stage 5 to look correct and be wrong.

**Tests** (need Stage 0's gate and the `AsyncioTaskRunner` fixture)

- Cancel mid-record → `INTERRUPTED`, `finished_at` is `NULL`, `error` carries
  the cancellation code, and **already-committed extractions survive**.
- Cancel then `resume()` → the run completes and `pending_record_ids` found
  exactly the hole. Reuses `test_resume.py`'s shape.
- Cancelling run 1 of 2 → run 2 still executes. This is what proves the
  per-run inner task works.
- `tests/backend/api/` — `POST /cancel` on an already-`done` run is refused,
  not silently accepted.
- `tests/ui/test_evaluation_view.py` — `Stop` appears for `running` / `queued`
  and nowhere else; `Resume` and `discard` appear after.

### Stage 6 — exhausted retries become visible *(optional, last)*

`sum_retries` counts only committed rows (§1.1 b). A counter column is
forbidden (sw-design.md §15 F6: no second source of truth a restart can
disagree with), so the progress card reports *attempts in flight* from the
worker's live state: `attempt 2 of 3 · waiting 3 m`. Needs a
`RunProgressView` field — the same `readmodels.py` amendment as 2c.

Last deliberately: once Stage 1 stops retrying timeouts, only connection
refusals retry at all, so this shrinks from the common case to a corner.

---

## 4. Amendments, consolidated

One file, `contracts/amendments/fix-evaluation-timeout-and-progress.md`, per
the one-file-per-branch rule.

| File | Change | Stage |
|---|---|---|
| `ra2/domain/llm.py` | `+ EndpointStatus.TIMED_OUT` | 1b |
| `ra2/infra/config.py` | `llm_timeout_s` `120 → 600` | 1d |
| `ra2/services/readmodels.py` | `+ RunView.ordinal`, `+ RunProgressView` attempts field | 2c, 6 |
| `ra2/infra/tasks.py` | `+ TaskRunner.cancel` — frozen protocol | 5a |

Plus CONTRACTS.md entries for the Status-cell design deviation (2b), the
fail-fast change to a documented constant (4), and the `Stop` row action (5d).

**No Alembic revision** (§2).

---

## 5. Order, and the shortest path

Stages **0 → 1 → 2 → 3** are the block worth doing together: they fix the
reported bug, make the screen honest, and stop the endpoint hammering.
**4** is a small follow-on. **5** is a separate branch. **6** last, if at all.

The shortest path back to a working evaluation without waiting for any of it:
**2a alone** — one line, no amendment — plus `RA2_LLM_TIMEOUT_S=600` in the
environment. That gives a run that works and a screen that shows it working,
while the rest lands properly.

---

## 6. The second reproduction — what all six stages did not fix

All six stages shipped, and the next run on the seed still ended
`interrupted` at `0 / 12`, carrying *"the process died while this run was
executing"*. Three findings, none of them in the list above. The full account
and the reasoning are items **12-14** of
`contracts/amendments/fix-evaluation-timeout-and-progress.md`; in short:

1. **The message was true, and the recipe was the defect.** `just dev` ran
   uvicorn with `--reload`, which watches the whole working directory for
   `*.py` — including every `.claude/worktrees/agent-*` copy of this project.
   One file written anywhere in the tree killed the worker mid-record. The
   watcher moves to `just dev-reload`, scoped to `ra2/`; `dev` and `dev-agent`
   lose it.
2. **`_reclaim` could write that same sentence about a live run.** Two gaps —
   the worker claimed the run *after* `_start` committed `running`, and
   `cancel` held no claim at all while the worker unwound — each a few
   microseconds wide, each producing an identical row from a process that
   never died. With them open there was no reading of that message as evidence
   of anything.

   Closed twice over. First by fixing the claim discipline (item 13), then by
   **removing it**: `RunRepository.list_running`'s docstring had described
   restart detection as a thing a caller does "on the next startup" since the
   day it was written, and had no caller. Reclaiming on every read was the
   improvisation. `reclaim_orphans` runs once, from `main.py`'s lifespan, where
   the relabel needs no claim to be correct — at startup this process is
   executing nothing. **A read never writes a status** (item 15). It closes
   `evaluation_service.get`'s recorded split as a side effect.
3. **The run had no voice at all.** §1.1's five gaps were all about the
   *screen*; none of them helps when the question is *why did that stop* an
   hour later. RA2 now writes an operational log to stderr, bounded by
   `data-handling.md` §5.1 to ids, counts, statuses, model tags and durations —
   never anything out of a delivery. §5 had forbidden logging outright, citing
   `mvp-spec.md` §13, which is "UI surfaces" and says nothing about it.

**The pattern worth keeping from this.** Every stage above made the *product*
more honest and none of them made the *failure* legible to whoever has to fix
it. The second reproduction cost as much as the first, and almost all of it
went on establishing facts a single log line would have handed over.

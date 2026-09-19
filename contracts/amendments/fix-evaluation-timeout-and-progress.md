# Amendment — `fix/evaluation-timeout-and-progress`

> **APPLIED in the same commits**, as `fix-b1-census-value-samples` and
> `fix-b3-deletion-path` were. No wave is running.

From a reproduced defect rather than a review: the first evaluation on the
development seed sat at `0 / 12 · running` for about twenty minutes and then
reported the endpoint as **unreachable**, which was false. The full account is
`plan-fix-evaluation-runs.md`; the measurement that decides it is this, taken
against the reporting host's own endpoint with the two seeded features and one
sentence of narrative:

| Call | Model | Elapsed |
|---|---|---|
| cold | `qwen3.5:latest`, 9.7 B Q4_K_M, `capabilities: [… thinking]`, no NVIDIA GPU | **136 s** |
| warm, model resident | identical prompt | **126 s** |

`Settings.llm_timeout_s` was **120**. Almost all of the time is inside the
response's `reasoning` field. Every call on that host timed out, always.

Stage 1 of the plan is this amendment. Stages 2-6 touch
`ra2/services/readmodels.py` and `ra2/infra/tasks.py` further; those items will
be added to this file as they land, per the one-file-per-branch rule.

---

## 1. `ra2/domain/llm.py` — `EndpointStatus.TIMED_OUT`

```diff
     REACHABLE = "reachable"
     UNREACHABLE = "unreachable"
+    #: The endpoint answered the connection and then did not finish within
+    #: `RA2_LLM_TIMEOUT_S`.
+    TIMED_OUT = "timed_out"
     REFUSED_NOT_LOOPBACK = "refused_not_loopback"
```

**Why.** "Unreachable" and "did not finish in time" are two different repairs.
One means *start Ollama*; the other means *the model is slower than the bound*.
An analyst given the first for the second goes to look at the port, the
process and the firewall while the endpoint is answering perfectly well — which
is exactly what happened.

**This codebase had already decided this.** `OllamaEndpointProber` has told the
two apart since P3-D19, and the test that pins it says so in these words:

> `APITimeoutError` subclasses `APIConnectionError`, so order matters in the
> adapter. A host that accepted the connection and went quiet is a different
> fix from one that was never there, and **collapsing the two would put the
> analyst on the wrong trail**.

The connection *test* honoured that. The generation path collapsed them,
because `EndpointStatus` had no value to say it with. This adds the value; it
does not introduce the distinction.

`LlmEndpointError`'s docstring goes from "Two causes, one type" to three, and
the new cause is documented as the one that is a statement about the **model**
rather than about the endpoint.

## 2. `ra2/infra/config.py` — `llm_timeout_s` 120 → 600

```diff
-    llm_timeout_s: int = 120
+    llm_timeout_s: int = 600
```

**Why.** 120 was never measured against a reasoning model. The table above is
what it meets in practice: a bound the ordinary case cannot clear is not a
bound, it is an outage with a timer. Nothing in the app could have reported
this, because the per-call bound is also the only thing that ever fails — so
no amount of waiting produced a row, and the failure named the wrong cause.

**Why 600 and not "no timeout".** A bound that is never reached is the one an
operator cannot reason about. 600 s is roughly four times the measured worst
case here, which leaves room for a longer narrative and a larger feature set
without leaving a hung endpoint unbounded.

**What the raise costs, and why it is bounded.** Under item 3 a timeout is no
longer retried, and `run_service` still stops after
`_MAX_CONSECUTIVE_ENDPOINT_ERRORS` records. So a genuinely dead endpoint costs
that many intervals rather than that many × `llm_max_retries + 1`. Against the
old behaviour — three records × three attempts × 120 s — the worst case is
*shorter* in attempts and longer only in the interval each one is given.

**One consequence, tracked:** `domain.llm.PROBE_TIMEOUT_S`' comment cited the
120 default by number. Updated in the same commit, because a comment naming a
default that moved is how the next reader is misled.

## 3. `ra2/infra/ollama_client.py` — a timeout is not retried

*Not frozen*; recorded here because it is what makes items 1 and 2 coherent.

```diff
 def _is_retryable(error: Exception) -> bool:
-    if isinstance(error, openai.APIConnectionError):  # APITimeoutError subclasses this
-        return True
+    if isinstance(error, openai.APITimeoutError):
+        return False
+    if isinstance(error, openai.APIConnectionError):
+        return True
```

plus `_status_for(error)`, which picks `TIMED_OUT` or `UNREACHABLE` for the
error that has run out of attempts.

**Why.** `temperature` is 0, the seed is fixed and the prompt is unchanged, so
a generation that did not finish inside the bound will not finish inside it
next time. This is `run_service`'s own argument for never retrying a parse
failure — *"a parse failure is never retried — temperature and seed are fixed,
so the retry returns the same bytes"* — and it holds here for the same reason.
It was simply never carried across.

A connection **refusal** stays retryable; the test asserts both directions, so
this cannot be satisfied by making everything terminal.

## 4. `ra2/services/readmodels.py` — `RunView.error` is no longer `FAILED`-only

```diff
-    #: Why it failed — the "log" action's content. `None` unless `FAILED`.
+    #: Why the run stopped — `None` only when the row carries no reason.
+    #: **Not restricted to `FAILED`.**
     error: str | None = None
```

**Why this is a defect and not a preference.** `run_service._run_view` read
`error=run.error if status is RunStatus.FAILED else None`, and the Evaluation
view offered its "log" action only to a failed run. So `_finish` wrote why a
run stopped, and the read model discarded it one layer before the only screen
that could display it — twice over.

An `interrupted` run is precisely the case that needs it. The row looks
identical whether the endpoint timed out, was never there, or the process died
under it; it offers the same Resume button in all three; and the sentence that
decides whether pressing Resume will achieve anything was being thrown away.

**The cost, chosen rather than discovered.** An interrupted run's status cell
now carries `Resume`, `log` and `discard` beside the status marker, in the 84 px
the design allots it (README §2). That cell already overflowed with two — it is
`plan-fix-evaluation-runs.md` §1.1 d, and **Stage 2c owns it**. This item makes
the crowding one item worse in exchange for the reason being reachable at all;
it does not create the class of defect.

---

## What was added to guard these

Two dicts keyed on `EndpointStatus` and read with `[]` — one in `ui/`, one in
`services/` — had no exhaustiveness check, so adding a member was a `KeyError`
waiting on a load path. `PROBE_WORDS` has had exactly this check since P3-D19;
the other two now match it:

| Assertion | Where |
|---|---|
| `set(ENDPOINT_WORDS) == set(EndpointStatus)` | `tests/ui/test_evaluation_view.py` |
| `set(_CONNECTION_REASONS) == set(EndpointStatus) - {REACHABLE}` | `tests/backend/services/evaluation/test_models_and_connection.py` |

`CONNECTION_REASON_TIMED_OUT` is the new sentence, beside the two that were
already there, and it names `RA2_LLM_TIMEOUT_S` — the one thing an operator
can act on.

## The wire contract

`tests/api/openapi_snapshot.json` regenerated — **one line, purely additive**:
`EndpointStatus`' enum gains `"timed_out"`. Verified by semantic diff of the
whole schema rather than by eye; nothing else moved. `RunResponse.error` was
already `str | None` on the wire, so item 4 changes what the field *carries*
and not what the schema promises.

## No migration

`run.status` is `sa.String(length=16)` with no `CHECK` constraint, and nothing
here adds a `RunStatus` member in any case. CLAUDE.md names one migration
author per phase and phase 5 expects no revision; this branch needs none.

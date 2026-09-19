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

Stages 1-4 of the plan are in this amendment. Stages 5-6 touch
`ra2/infra/tasks.py` and `ra2/services/readmodels.py` further; those items will
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

## 5. `ra2/services/readmodels.py` — `RunView.ordinal` *(Stage 2)*

```diff
     run_id: RunId
+    #: This run's place within its own evaluation, by creation order, from 1.
+    ordinal: int
     evaluation_id: EvaluationId
```

**Why the read model and not `ui/`.** The ordinal is a property of the *set*.
The runs table sorts on four keys and pages at ten, so a number worked out
from the rows on screen would be a different number per sort — and the
discard dialog and the mismatch toolbar already name runs "run 2", from a
query that is explicitly `ORDER BY run.id`. `run_service.run_ordinals` is now
the one place that count is made, so the table and the dialog cannot disagree
about which run is run 2.

**Why by id.** uuid7 is time-ordered, so id order is creation order.
`RunRepository.list_by_evaluation` returns `started_at DESC` — the display
order, in which a run's number would change as its siblings start.
`launch_runs` already sorted by id on this reasoning.

**What it fixes.** `_render_run_id` put the 36-character id into the 74px the
design allots (README §2), where `table-layout:fixed` does not clip, so it
drew over the Model column. Clipping alone would not have been enough: uuid7
opens with a millisecond timestamp, so runs launched together share their
first eleven characters and a truncated id distinguishes nothing. The full id
stays on the link's `title`.

## 6. Two UI changes that need no amendment, recorded because they deviate

Neither file is frozen; both depart from `design/prompt-evaluation/README.md`
§2, so they belong in CONTRACTS.md as design deviations.

**The `DEV` marker becomes a chip beside the status word, not a replacement
for it.** The design's reading is sound where a dev-sized run is the
exception. `RA2_DEV_RECORD_MAX` is 50 and the development seed is 12 records,
so *every* run an analyst makes while learning the product is dev-sized, and
the Status column rendered one constant string: `running`, `done` and
`interrupted` were the same cell. The `--warn-soft` row tint is unchanged and
nothing about a dev run is quieter than it was.

The suite did not catch this, and the reason is worth keeping: the cell
already carried `data-status` and `data-dev`, so both facts were legible to a
test and to nobody else. `test_two_dev_runs_in_different_states_render_different_status_cells`
is the assertion that was missing.

**The Status column widens from 84px to 200px.** 84 is the right width for
what the design draws there — one state word. It is not what the cell holds:
phase 5 put `discard` in it rather than in a sixth column *precisely* to keep
the five drawn widths, `interrupted` runs already carried `Resume`, item 4
above added `log`, and the chip makes five things in a cell sized for one.

Keeping 84 never made them fit; it made them draw over the column beside
them. That trade preserved the number in the README and spent the thing the
number was for. Clipping is not the answer here either — three of the five
are buttons, and a control under `overflow:hidden` is one nobody can press,
which is the defect `theme.py`'s own `.td-clip` note was written about. The
other four columns keep the design's widths exactly *and* gain `.td-clip`,
because all four hold text.

The well is `overflow:auto` and the README's stated purpose for it is that the
table "scrolls horizontally rather than collapsing a column below the design
width". That is what makes the widening affordable.

## 7. `ra2/services/evaluation_service.py` — `get()` takes the endpoint state back *(Stage 3)*

*Not frozen.* Recorded because it is the seam that makes C3 enforceable.

```diff
-    async def get(self, evaluation_id: EvaluationId) -> EvaluationView:
+    async def get(
+        self,
+        evaluation_id: EvaluationId,
+        *,
+        connection: ConnectionView | None = None,
+        models: Sequence[ModelChoiceView] | None = None,
+    ) -> EvaluationView:
```

**Why.** `connection_status`' own docstring says reachability is re-checked
"on view load and when the settings dialog's refresh is pressed — **never on
a timer**" (plan-phase-3.md C3). The Evaluation view's progress poll called
`reload()`, which calls `get()`, which called `connection_status()` **and**
`_model_choices()`. Both reach `/api/tags`. At `ui.timer(0.2, …)` that is
**ten HTTP requests a second aimed at the endpoint the worker is waiting on**,
plus a `pynvml` probe five times a second, for the whole length of a run —
against an endpoint already saturated generating the answer being waited for.

A caller that already holds the endpoint's state now hands it back instead of
having it re-probed, which is C3 written at the seam rather than remembered at
the call site. `models is not None` rather than truthiness: an unreachable
endpoint's catalogue is legitimately `()`, and treating that as "nothing
supplied" would put the probe back on the timer for the endpoint least able to
answer it.

**Why no test caught it.** `StaticModelCatalog.reachable_calls` exists for
exactly this claim and is asserted at the *service* layer, where the service
was being called legitimately. It is the timer that was wrong, and nothing at
the UI layer counted. `test_the_progress_poll_never_re_probes_the_endpoint`
now does, and was checked against the old code: it fails there with
`(2, 2) == (1, 1)`.

## 8. Three more Stage 3 changes in `evaluation_view.py`

**The poll calls `refresh_progress`, not `reload`.** It re-reads the progress
cards, the runs table and the provenance line — counts over committed rows —
and redraws the progress column only. The corpora, feature sets and templates
are not re-read at all: a run in flight cannot change any of them.

**The poll slows down.** 0.2 s is `import_view`'s and right for the seconds
after a submit; it is absurd for a model answering one record every two
minutes, where it is six hundred full redraws between two numbers changing.
After `POLL_FAST_TICKS` the interval moves to `POLL_SETTLED_S` — `ui.timer`
re-reads `interval` before each sleep, so no timer is torn down.

**A page opened mid-run now polls.** `_start_polling` was reached only from
Launch and Resume, so the tab that submitted the work updated and every other
view of it did not: reload the browser mid-run, or open a second tab, and the
screen froze at whatever it read once — indistinguishable from a dead worker,
which is the confusion this branch exists for.

**And `_settled` moved to the reclaimed statuses.** It read
`EvaluationView.progress`; it now reads `RunService.list_runs`. Only
`RunService` can reclaim — `self._active` is the sole record of which runs
*this* process is executing, and `EvaluationService` builds its progress cards
straight from the rows — so off the unreclaimed statuses this property called
a run left behind by a dead process **live**, and polled a screen that could
not change until a later tick reclaimed it by another route.

That inconsistency is still there underneath: on a page loaded after a crash,
the progress cards say `running` and the runs table says `interrupted`, from
one read of the same rows. This change stops the view *acting* on the wrong
half. Closing it properly means giving `EvaluationService` a way to ask
`RunService` what it is executing, which is a seam this branch does not open.

## 9. `ra2/services/run_service.py` — the endpoint bound becomes two numbers *(Stage 4)*

*Not frozen*, but it changes a deliberately documented constant, so it is
recorded here and in CONTRACTS.md.

```diff
 _MAX_CONSECUTIVE_ENDPOINT_ERRORS: Final = 3
+_MAX_ENDPOINT_ERRORS_BEFORE_FIRST_ROW: Final = 1
```

**Why three was right and still is — after the first row.** An endpoint that
has answered *for this run*, with this model, this prompt and this schema, has
demonstrated the configuration works. A failure after that is plausibly
transient and worth asking again.

**Why one before it.** Nothing supports that reading on a run that has never
produced a row: the first failure is the only evidence there is, and it says
the configuration does not work. That is a verdict, not a flake.

**The arithmetic is the point.** An `LlmEndpointError` reaching this module
means the adapter already exhausted its own bounded retries, so each of these
records has cost up to `RA2_LLM_TIMEOUT_S` — 600 s since item 2 raised it
against a measurement. Three of them is half an hour spent being told what the
first one already said, and it is the other half of what made the reported
defect a twenty-minute silence.

**Counted over the run, not over the execution.** `done` is committed rows for
the run, from this attempt or any earlier one, so a resume inherits the
evidence its first attempt produced. A resume of a run *with* rows keeps the
tolerance of three; a resume of a run with none does not, because it has none.

**One test fixture changed rather than adapted.**
`tests/backend/api/runs/test_runs_resume.py` failed calls 0, 1 and 2 "three in
a row, the worker's own bound" to produce an interrupted run with nothing
committed. It now fails call 0. The fixture was built around the old bound and
says so; leaving it and loosening the assertion would have been the reverse of
what it is for.

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

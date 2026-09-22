# The progress poll could stop on a stale row

A bug report that arrived as a flaky test, which is the only reason it
arrived at all.

---

## 1. What was seen

`tests/ui/test_evaluation_view.py` failed about **one run in four**, always
one of two tests, always on the same line:

```
FAILED test_the_progress_poll_never_re_probes_the_endpoint
FAILED test_an_active_run_offers_stop_and_an_inactive_one_offers_discard
E   AssertionError: condition never became true
tests/ui/test_evaluation_view.py:492
```

Both do the same thing: open `/evaluation` with a `queued` run, set that run
to `done` in the database, and wait for the runs table to say so.

It was not the parallel commit gate. Running that one file in a loop, on
`f42e53f` with none of the test-suite work applied: **6 red in 25**. With it:
**5 in 16**. Same two tests, same assertion, same rate. `just test` going from
thirteen minutes to thirty seconds is what made it visible — a suite you run
often enough gets its one-in-four noticed.

It was not a timing budget either, which is the first thing anyone will try.
`_until` is `for _ in range(500): await asyncio.sleep(0.01)`, and five seconds
does look thin for a worker sharing 28 cores. Raised to sixty seconds the wait
burns all sixty and the condition is still false. **The page was stuck, not
slow**, and that is the fact that made the rest findable.

## 2. What it was

A temporary probe, sampling every 10 ms once the row had been committed:

```
i=  0 db=done  rendered=['queued']  timers_active=[True]
i=  1 db=done  rendered=['queued']  timers_active=[False]
i=399 db=done  rendered=['queued']  timers_active=[False]

view._all_runs statuses=['done']     <- what _settled judges
view._runs     statuses=['queued']   <- what the table draws
view._settled=True                   -> view._poll=None
```

`db=done` from the first sample, so nothing was stale about the read. The two
lists **disagreed**, and the timer switched itself off one tick later.

`refresh_progress` re-reads the runs twice, because the table is paged and the
settle-check is not:

```python
self._runs = await self._services.run.list_runs(evaluation_id, page=…, page_size=…, …)
self._all_runs = (await self._services.run.list_runs(evaluation_id, page=1,
                                                     page_size=RUNS_SUMMARY_CAP)).items
```

Two queries, so a tick can land **across** a commit. The paged read returns
`queued`, the worker's row is committed, the capped read returns `done`.
`_settled` judged `_all_runs` alone, so it said *everything has finished* —
and `poll()` did what it is told to do when everything has finished:

```python
if self._settled and self._poll is not None:
    self._poll.deactivate()
    self._poll = None
```

The timer stopped, leaving the table drawn from the older read. **Nothing
ticks again**, so the row stays `queued` until the page is reloaded.

## 3. Why it matters outside the test

A run ends once. The window is the gap between two queries in one tick, so the
odds of a tick landing on it are small — which is exactly why this surfaced as
a test that fails sometimes rather than as a bug report. What it does to an
analyst when it does land is not small:

- the progress header says settled and the runs table says `queued`, on one
  screen, about one run;
- `Stop` is offered for a run that finished, and `discard` — the action the
  row should now carry — is not, because §18.5 withholds it while a worker may
  still be writing;
- the state is **terminal**. The poll is the only thing that would have
  corrected it and the poll is what switched off. Only a page reload clears it,
  and nothing on the screen suggests reloading.

It is the same disease the property's own docstring already describes — *"one
screen gave two answers about the same run"* — between a different pair of
reads. That one was fixed by choosing the better source. This one cannot be:
both sources are correct, they are just from different instants.

## 4. The fix

`_settled` judges **both** lists (`ra2/ui/views/evaluation_view.py`):

```diff
-        return not any(r.status in (RunStatus.QUEUED, RunStatus.RUNNING) for r in self._all_runs)
+        paged = self._runs.items if self._runs is not None else ()
+        return not any(
+            r.status in (RunStatus.QUEUED, RunStatus.RUNNING) for r in (*self._all_runs, *paged)
+        )
```

The poll stops when nothing **the view is showing** is still expected to move,
rather than when nothing in one of its two lists is.

This does not need the two queries to be atomic, and deliberately does not try
to make them so. A torn tick leaves one list unsettled, so the timer survives
to the next tick, where both reads fall on the same side of the commit and
agree. One extra tick is what this costs. A tick that changes nothing is what
a poll is made of; a screen frozen on a stale row is not.

**Rejected: reordering the two reads** so the capped read happens first. It
fixes the observed case — the rendered rows would then never be older than the
decision — but it holds only while no *new* run can appear between the two
reads, and it leaves the invariant nowhere in the code, as an ordering that
looks arbitrary and that the next edit is free to swap back. Judging both
lists says what is meant.

## 5. The test

`test_the_poll_never_stops_on_a_tick_that_read_across_a_commit`.

The interleaving is **forced, not waited for**: the commit is made from inside
the first `list_runs` of a tick, which is precisely the window. Waiting for it
is what the suite had been doing by accident for weeks, one run in four.

It is a real gate, not a restatement of the fix — without the change it fails
in 7.8 s (the wait timing out), with it, it passes in 1.7 s.

The two tests that were flaky are left exactly as they were. They were right;
they were describing this all along.

## 6. The second bug, which the first one was hiding

Fixing `_settled` turned the failure into a different one, at half the rate:

| `tests/ui/test_evaluation_view.py` × 20 | stale-row failures | teardown errors |
|---|---|---|
| before | **4** | 0 |
| `_settled` fixed | 0 | **2** |
| both fixed | **0** | **0** |

The new errors were `ResourceWarning: <aiosqlite…Connection> was deleted
before being closed`, and its uglier cousin — aiosqlite's worker thread
landing `call_soon_threadsafe` on a loop that had already closed. Under
`filterwarnings = ["error"]` each is an error in **whichever test is running
when the collector gets to it**, which is why they appeared on tests with
nothing to do with polling.

This was not a new bug; it was a pre-existing one that the first bug had been
suppressing. A poll that used to switch itself off early now correctly runs a
tick longer, so a tick is more often still **in flight** when the fixture tears
the app down. `engine.dispose()` closes the pool's *idle* connections; a tick
holds a session, and that session's connection is checked **out** of the pool,
which is the one thing dispose cannot reach. `tests/ui`'s own `_poll_stops`
helper had described this hazard in its docstring for weeks and worked around
it one fixture at a time.

So `tests/ui/conftest.py`'s `app_factory` now cancels what is still running
and `gather`s it before disposing — giving each task the turns it needs to run
its `async with` exits and return its connection while there is still a loop to
do it on. One place, for every app the layer builds.

## 7. Afterwards

The file, run twenty times: **0 red**, neither class. It was 6 in 25 before.

Untouched, and still true: `uv run mypy` reports
`tests/e2e/conftest.py:97: Statement is unreachable` on Linux. It predates all
of this and belongs to whoever owns layer 4.

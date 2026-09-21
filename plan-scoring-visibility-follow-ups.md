# plan-scoring-visibility-follow-ups.md — the two loose ends

**Status.** Written 2026-09-21 against `1c128e4` + the working tree of
`fix/results-visibility`. Two findings that came out of
[`plan-fix-results-visibility.md`](plan-fix-results-visibility.md) and were
deliberately **not** taken in that slice: one because it is a different screen
with a different owner's copy, one because closing it properly costs an
amendment to a frozen file. Neither is urgent; both are cheap.

Authority as always: `mvp-spec.md` on *what*, `sw-design.md` on *how*
(CLAUDE.md). **No Alembic revision** for either part.

---

## Part 1 — Mismatches tells a crashed pass as a perfect score

### 1.1 What it does today

`ra2/ui/views/mismatches_view.py` decides between its empty states with one
boolean, read over the whole evaluation:

```python
statuses = await self._services.results.scoring_status(evaluation_id)
self._scored = any(status.is_scored for status in statuses)
```

and then, per run:

```python
if view.rows.total == 0 and not _is_filtered():
    empty_card(NO_MISMATCHES_TITLE, NO_MISMATCHES_BODY)
```

`NO_MISMATCHES_TITLE` is **"No mismatches in this run."** and its body is
**"Every labelled feature this model answered, it answered correctly."**
`_is_filtered()` states, correctly and deliberately, that *the run itself is
not a filter* (`SD26`, §17.6).

### 1.2 The failure

An evaluation runs several models and **each is scored by its own pass**
(`_score` is per `(run, feature)`, submitted per run). So one pass can fail
while the others succeed. Then:

| What is true | What the screen says |
|---|---|
| Run 1 scored, run 2's pass crashed. The analyst picks run 2 in the run chip. | `any(is_scored)` is `True`, so the view renders the table. Run 2 has no `mismatch` rows, and the run is not a filter — so the card reads **"No mismatches in this run. Every labelled feature this model answered, it answered correctly."** |

That is not an ambiguous sentence; it is a **false and flattering** one, about
the one screen in the product where a human is deciding which model to
believe. The Results boards for the same run draw blank cells — which
`PARTIAL_NOTE` now names — but Mismatches says the run was perfect.

The weaker half of the same defect: with **no** run scored, the view renders
`NOT_SCORED_TITLE` / *"Mismatches are written by the scoring pass. Scoring
starts automatically when a run completes."* True since `6bae3a3`, and still
unable to separate "the run is still going" from "the pass died" from "the
pass stopped part-way" — the three states `ScoringStatusView` now carries and
the Results view now renders.

### 1.3 The fix

The read model already answers all of it: `is_scored`, `scoring_stalled`,
`scoring_incomplete`, `is_finished`, `running` (added in
`fix/results-visibility`). Nothing new is needed in `services/`.

| Step | File | Change |
|---|---|---|
| 1a | `ra2/ui/views/mismatches_view.py` | Hold the **statuses**, not a boolean: `self._statuses = statuses`, and decide per **displayed run** rather than per evaluation. `self._scored` goes. |
| 1b | same | Before rendering `NO_MISMATCHES_TITLE`, check that *this* run is scored. If it is stalled or incomplete, render the matching card instead — the same two sentences Results uses, so the two screens cannot drift into two accounts of one fact. |
| 1c | same | The `NOT_SCORED_*` card splits the way Results' did: a run still going says so; a finished run with no rows says the pass did not finish; a partly-scored run says that. |
| 1d | same | A **Re-score** control on the two states that need one, calling `ScoringService.submit_rescore` exactly as `results/__init__.py` does. |
| 1e | `ra2/ui/views/results/chrome.py` *(or a small shared module)* | The four sentences live **once**. They are currently duplicated between `results/__init__.py` and `mismatches_view.py` — two copies of "Not scored yet." already exist, and this plan would make it four. `chrome.py` exists for exactly this ("Everything here exists once rather than three times… the three tabs must not drift into three slightly different headers on one screen"), and Mismatches already imports `run_descriptor` from it. |

**Why not simply hide the run chip for an unscored run.** Because the analyst
is entitled to know that run 2 exists and was not scored — that is the fact
they act on. Hiding it produces the same silence by another route.

### 1.4 Done when

- A UI test seeds an evaluation with **two** runs, scores **one**, selects the
  unscored one, and asserts the screen does **not** claim it was correct — the
  case that is wrong today.
- A second test asserts the four sentences come from one module, by importing
  them from where Results imports them.
- `tests/ui/test_mismatches_view.py`'s existing `NOT_SCORED_TITLE` assertions
  still pass, or are updated in the same commit with the reason.

---

## Part 2 — Swap detection sees the case that matters, and says so

### 2.1 What was built, and its stated limit

`fix/results-visibility` Stage 4 took **option A**: `LifecycleService` stamps
`(st_dev, st_ino)` of the database file in its constructor, `data_dir()`
compares on every call, and a mismatch puts a banner on every screen.
`scripts/reset_data.py` prints the warning with its plan.

The limit is written into the test and the plan rather than glossed:
**detection relies on the old inode still being pinned by this process.** When
something holds the file open, the filesystem cannot reuse that inode number,
so the new file gets a different one and the check fires. When nothing holds
it open, the number can be handed straight back, and the check sees no change.

That is a good trade — the pinned case *is* the dangerous case, because the
open handles are what create the split brain — but it is a probabilistic
guarantee where a structural one is available.

### 2.2 What the split brain actually is

Measured on this machine, one process, sixteen concurrent reads after a
`reset_data` + `seed_dev` under it:

```
before reset: {'01a0c4cc-5da7-…'}
after  reset: {'01a0c4cc-5da7-…', '01a0c4cc-6ef5-…'}
SPLIT BRAIN: True | stale still visible: True
```

The engine's pool is `AsyncAdaptedQueuePool`, `size=5`, `max_overflow=10`.
Connections checked out before the swap keep the deleted inode; connections
opened after it get the new file. Which one any given request sees is pool
luck.

### 2.3 Option B, the structural version

```diff
-    engine = create_async_engine(database_url, echo=echo, future=True)
+    engine = create_async_engine(database_url, echo=echo, future=True, poolclass=NullPool)
```

in `ra2/persistence/session.py`. Every session opens the file fresh, so the
process cannot hold two databases at once: after a swap it converges on the
new file, and the failure becomes a clean `NotFoundError` about rows that are
genuinely not there rather than two answers to one question.

**It is not a replacement for the banner.** Converging silently on a different
database is its own surprise; the banner is what says *why* the screen just
emptied. The two are complementary, which is why this is a follow-up rather
than a correction.

**Costs, all of which need measuring before it lands:**

- `ra2/persistence/session.py` is **frozen** → an amendment.
- A file open per session, plus the four connect-time `PRAGMA`s per session
  (`journal_mode`, `foreign_keys`, `busy_timeout`, `secure_delete`), where
  today they are paid once per pooled connection. Cheap for SQLite; not free,
  and the run worker opens a session per record and per feature.
- WAL readers get no benefit from pooling here, but the **busy_timeout**
  behaviour under a long freeze transaction is the thing to check: that is
  what `BUSY_TIMEOUT_MS` was sized for.

### 2.4 The measurement that decides it

Not a preference — a number. Before proposing the amendment, run:

1. `just test` with and without `poolclass=NullPool`, wall clock compared over
   three runs each. The suite opens thousands of sessions against temp-file
   SQLite, so it is the cheapest proxy for the per-session cost.
2. One seeded 48-record run against the real endpoint each way (the model
   dominates, so this is checking for a *regression*, not for a speedup).
3. The freeze path under a concurrent poll, which is what `busy_timeout`
   exists for: `just reset-seed yes --records 200`, freeze, and poll
   `/api/v1/tasks/{id}` while it runs.

If the cost is in the noise, take option B **and** keep the banner. If it is
not, keep option A alone and record the number here, so nobody re-opens this
on a hunch.

### 2.5 Done when

- The three measurements above are in this file.
- Either `contracts/amendments/<branch>.md` carries the `session.py` diff and
  the number that justified it, or this section carries the number that
  refused it.
- If it lands: the backend test from `tests/backend/services/lifecycle/test_database_replaced.py`
  gains a sibling asserting that a swapped file produces a `NotFoundError`
  rather than two answers — the structural claim, not the detection one.

---

## What neither part needs

No migration, no new `FindingCode`, no schema change, and no new seam. Part 1
is copy and branching over read-model properties that already exist; part 2 is
one keyword argument and the measurements that justify it.

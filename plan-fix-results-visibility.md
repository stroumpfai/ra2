# plan-fix-results-visibility.md — the run finished; the screen did not say so

**Status.** Written 2026-09-21 against `1c128e4`, from a reported symptom on the
development seed (`just reset-seed yes`, 48 records, `qwen3.5:2b`) that was
**reproduced and then found not to be a data defect**. Authority as always:
`mvp-spec.md` on *what*, `sw-design.md` on *how* (CLAUDE.md). This plan needs
**no Alembic revision**.

**Implemented** on `fix/results-visibility`, all four stages, plus one gap
found while implementing §3 f — the link that produced the reported symptom.
Three frozen files are touched, under
[`contracts/amendments/fix-results-visibility.md`](contracts/amendments/fix-results-visibility.md).
Stage 4 took **option A**; option B is recorded below as the road not taken.

---

## 1. What was reported

A run over the seeded corpus finished cleanly:

```
18:16:51 run 01a0c4bf-…: done
18:16:51 run 01a0c4bf-…: done, scoring submitted as task 01a0c4c1-…
```

and then, on screen: the evaluation still reading **In progress**, launching
another run disabled, and the **Results view empty** — while the runs table
said the run was `done`.

## 2. What was actually true

Three measurements, none of which needed the analyst's database to be opened.

**a. The scoring pass succeeded.** The task id is in the log line above, and
the app was still running, so its own progress table could be asked:

```
GET /api/v1/tasks/01a0c4c1-…  →  name score:01a0c4bf-…  status ok  done 7/7  error none
```

Seven features scored, no error. The `score` rows exist.

**b. The whole chain works against the real endpoint.** Reproduced headlessly
on a throwaway `RA2_DATA_DIR`: `reset_data.py` + `seed_dev.py` (the default
48-record seed), then `create_app()` with the **real** `OllamaLLMClient` and
`qwen3.5:2b`, launch, wait:

```
RUN TASK  : runs:… ok 48/48
TASK      : score:… ok 7/7  error=None
RUN       : … done 48 err=None
SCORING   : scored_features=7 labelled_features=6 → is_scored=True
```

**c. Scoring is not something anybody waits for.** A `rescore_run` over that
same finished run — 48 records × 7 features, EAV reads and all — takes
**0.14 s**.

So the data was right, the chain was right, and the run was scored within a
blink of the log line that announced it. **What failed is every path by which
the screen could have said so.** That is the subject of this plan.

## 3. The gaps

Each is independently a defect; together they make a scored run and a broken
one look identical.

| # | Where | What |
|---|---|---|
| a | `ra2/ui/views/results/__init__.py` | The page **never refreshes itself**. There is no `ui.timer` anywhere in the package; `reload()` runs on page build and on a tab/row click. A Results page opened while a run is in flight renders "Not scored yet" and keeps rendering it after scoring has finished. Its own copy, at line 171, says *"Progress is polled; this page refreshes itself."* It does not. |
| b | `ra2/services/scoring_service.py:149` | `ScoringStatus.running` is the literal `False`. Nothing joins the task runner to the status, so §16.7's **"Scoring…"** state is unreachable by construction — the same "unreachable by construction" the `SD17` chain commit (`6bae3a3`) found and fixed one layer up. The task id `submit` returns is logged (`run_service.py:532`) and then dropped on the floor. |
| c | `ra2/ui/views/results/__init__.py:77` | `NOT_SCORED_BODY` tells the analyst to *"use Re-score if you need to run it again"*. **There is no Re-score control in `ui/`** — only `POST /api/v1/runs/{id}/rescore` (`ra2/api/v1/results.py:245`), which nothing in the product issues. That route also `await`s the whole pass and then returns `202 Accepted` with `task_id = run_id`: a task id that is not one. |
| d | `ra2/infra/tasks.py:182` | A failed task is recorded **in memory and nowhere else** — `except Exception: self._table.mark_failed(...)`, no log line. `ScoringService` logs nothing at all: not a start, not a finish, not a failure. On this occasion the pass succeeded; the screen and the log would have looked **identical** if it had not, and a restart would have erased the only record that it ever ran. |
| e | `ra2/ui/views/evaluation_view.py:329` | `PROGRESS_TITLE = "In progress"` is a **constant column header**, rendered whatever the cards below it say. It is read as a state, because on this screen everything else is one. Nothing on that screen ever says *"scored — the boards are ready"*, so the one signal the analyst is waiting for is not on the page they are watching. |
| g | `ra2/ui/views/results/__init__.py` `_render_picker` | **Found by driving the running app, after the other five were fixed.** The picker rendered its card and nothing else, under copy reading *"Pick a launched evaluation below"* — and there was nothing below. So the **sidebar's own Results entry** — the obvious way in, and the one every test in this slice avoided by passing an id in the URL — ended on a sentence pointing at an empty space. The same defect as an empty state naming a control that does not exist, one screen further out. |
| f | `ra2/ui/views/evaluation_view.py:1869` + `ra2/ui/views/results/__init__.py:87` | **Found while implementing, and almost certainly what was clicked.** The runs table links each row to `/results?run=<run id>`; the Results page declares `evaluation` and `tab` and nothing else. FastAPI drops an undeclared query parameter without a word, so the one control in the product that takes an analyst from a finished run to its board rendered **"No evaluation selected."** — the picker, listing the evaluation they had just come from. A `done` run, a scored database, and an empty Results view, with no defect anywhere in between. |

**Not a defect, and worth writing down so it stops being re-diagnosed:** the
Launch button is disabled once the evaluation is launched, by design —
`sw-design.md` §15.2, `SD32`, and `LAUNCHED_MESSAGE` says so at the head of the
setup column. Another run means **"New evaluation"**, which clones the corpus
and the feature set into an editable draft.

### 3.1 A landmine found next door: one process, two databases

Reproduced, separately from the reported symptom and **not** its cause:

```
before reset: {'01a0c4cc-5da7-…'}
after  reset: {'01a0c4cc-5da7-…', '01a0c4cc-6ef5-…'}   ← 16 concurrent reads, one process
SPLIT BRAIN: True | stale still visible: True
```

`just reset-seed` unlinks `ra2.sqlite` and writes a new one. A **live** app
process keeps its pooled connections on the deleted inode while every
connection opened *after* the reset gets the new file. Reads and writes then
split across two databases inside one process, by pool luck.

Nothing warns about this: `scripts/reset_data.py` never mentions a running
app, and the app cannot tell that the file under it was replaced. The symptom
class it produces is exactly the one reported here — a worker that says `done`
and a view that sees nothing — which is reason enough to close it in this
plan rather than leave it to be diagnosed again from scratch.

---

## 4. The stages

Four, each independently shippable and independently green (`just lint` and
`just test` in the worktree).

### Stage 1 — the Results page tells the truth about scoring

The reported symptom. Ships value alone.

| Step | File | Change |
|---|---|---|
| 1a | `ra2/services/scoring_service.py` | The service tracks its own in-flight run ids: a `set[RunId]` added in `submit`/`_score` and discarded in a `finally`. `status()` returns `running=run_id in self._in_flight` instead of `False`. **No wiring change and no amendment** — `main.py` already hands the *same* `ScoringService` instance to `RunService` as `ScoreSubmitter` and to `ResultsService`/`RankingService` as `Scorer`. |
| 1b | `ra2/ui/views/results/__init__.py` | A `ui.timer` in `evaluation_view._start_polling`'s shape: poll while any status is `running`, or while the evaluation holds a `queued`/`running` run; deactivate when settled. **A ladder after all** — this plan said none was needed, on the grounds that a pass is 0.14 s, and that is only true of the pass. A page opened *during* a run waits hours for the run before it waits a blink for the pass, and the fast interval there would be two and a half `scoring_status` reads a second against the file the worker is committing to — §1.2's mistake, on the other screen. So: `POLL_FAST_S` while a pass is in flight, `POLL_SLOW_S` while waiting for a run, chosen from the statuses rather than counted in ticks. |
| 1c | `ra2/ui/views/results/__init__.py` | A **Re-score** control in the "Not scored yet" card and beside the descriptor, so the copy at line 77 names something that exists. It calls `ScoringService.submit` (schedules, returns a task id) — never `rescore_run`, which blocks the request for the length of the pass. |
| 1d | `ra2/api/v1/results.py` | `rescore` submits through the runner and returns the **task's** id, not the run's. 409 on `failed`/`interrupted` is unchanged. |

| 1f | `ra2/ui/views/results/__init__.py` | The picker **lists the launched evaluations** — §3 g. Launched only, newest first, each a link carrying its name, launch time and models; a different sentence when there are none, because the first one would be pointing at an empty space again. |
| 1e | `ra2/ui/views/results/__init__.py` | The page accepts **`?run=<id>`** and resolves it to its evaluation — §3 f. Accepted here rather than rewritten in the runs table, because a link that names the run is the right link: it says which board, and it is the id in every log line about that run. |

**Done as specified**, with one addition the tests forced: the Re-score strip
renders **over a drawn board** as well as instead of one. An evaluation runs
several models, each scored by its own pass, so one pass can fail while the
others succeed — and the board then draws that model's cells blank, which
reads as a model that answered nothing rather than one nobody scored
(`PARTIAL_NOTE`).

**Done when** a UI test opens Results while a run is in flight, lets the run
finish and its pass be submitted, and the boards appear **without any click**
(`test_a_page_open_while_a_run_is_going_brings_the_boards_in_by_itself`); a
backend test shows `running` is true in the same tick as `submit`, before the
loop reaches the coroutine; and following a run link lands on that run's
board rather than on the picker.

### Stage 2 — a scoring pass says what it did

`d` above. The reason this incident took a reproduction to resolve instead of
a `grep`.

| Step | File | Change |
|---|---|---|
| 2a | `ra2/services/scoring_service.py` | One line in, one line out: `run <id>: scoring N features` and `run <id>: scored N features in M ms` / `scoring failed after N features`. Ids, counts and durations only — `infra/logging.py`'s rule, the same one `run_service` keeps. |
| 2b | `ra2/infra/tasks.py` | `AsyncioTaskRunner._run`'s `except` logs the failure it is already recording: task id, name, exception **type**. Not `str(exc)` — a SQLAlchemy error embeds bound parameters, and a bound parameter here is a narrative (Do-NOT #13, `data-handling.md` §5). The message stays in the task table, where `/api/v1/tasks/{id}` can hand it to the analyst who asked. |
| 2c | `ra2/ui/views/results/__init__.py` | **Two** new empty states, not one — the plan said "a fourth" and the card it was splitting turned out to be carrying three things. `STALLED_TITLE` ("Scoring did not finish.") is a finished run with **no** rows; `INCOMPLETE_TITLE` ("Partly scored.") is `0 < scored < labelled`, which is the middle state `ScoringStatus`'s own docstring names and the UI collapsed; and what is left in "Not scored yet." is a run that has **not finished**, whose body no longer claims it has. Each of the first two offers Re-score; the third offers patience, because that is all that helps. |

**Done when** a backend test injects a scoring pass that raises, and (i) the
task table carries the failure, (ii) a log line names the run id and the
exception type and contains nothing from a delivery — `test_run_log_carries_no_data.py`'s
pattern, extended to the scoring job: the double hides a narrative in its
exception message and the test asserts no log record carries it — and (iii)
Results renders the fourth state rather than "Not scored yet".

### Stage 3 — the Evaluation screen closes the loop

| Step | File | Change |
|---|---|---|
| 3a | `ra2/ui/views/evaluation_view.py` | `PROGRESS_TITLE` stops being a state word **in the state it is wrong for**. "In progress" is the design's own header (`design/prompt-evaluation/README.md` §2) and it is kept verbatim while a run is in flight — the state the design's mock draws. Settled, the header reads "Runs". Changing the design's wording outright would have meant changing `design/…/README.md` first (CLAUDE.md); the mock says nothing about the settled state, so this is an answer to a question the design did not ask rather than a departure from it. |
| 3b | `ra2/ui/views/evaluation_view.py` | When a run is `done` **and scored**, its card carries the link the analyst is actually waiting for — `results?evaluation=<id>`. The runs table's "results" action already goes there; the card is where the eye is during a run. |

**Done when** a UI test drives a run to `done` and finds the results link on
the card, and the header no longer reads as a status anywhere in the E2E
assertions.

### Stage 4 — the reset cannot swap the file under a live process

§3.1. Two options; **A is recommended** and needs no frozen file.

**Option A — the app notices. Taken.** `LifecycleService` stamps the database
file's identity (`st_dev`, `st_ino`) in its constructor — not `create_app`,
which is frozen, and not lazily, which would adopt whatever file happened to
be there when the first page loaded. `data_dir()` compares on every call, and
every screen makes that call once to draw the header chip, which makes it the
cheapest place in the app to notice and the only one every screen passes
through. On a mismatch the shell renders a banner above the content of every
page. `reset_data.py` prints the warning with its plan, whether or not the
token was given.

**What the check cannot see, stated rather than glossed.** Detection relies on
the old inode still being pinned by this process — which is exactly the
situation worth detecting, because it is the open handles that create the
split. A process holding nothing open can be swapped under and the filesystem
may hand the same inode number back. The test holds the file open for that
reason, and says so.

**Option B — the app cannot split.** `poolclass=NullPool` on the engine, so
every session opens the file fresh and a swap converts a silent split brain
into a clean `NotFoundError`. Cheap for SQLite, but `ra2/persistence/session.py`
is **frozen** → `contracts/amendments/fix-results-visibility.md`, and it is a
narrower fix: it removes the split, not the surprise.

**Done when** a backend test reproduces the swap and asserts `database_replaced`,
with three companions for the states that are **not** a replacement: an
untouched database read twice, a database that did not exist yet and is
adopted, and the moment mid-reset when the file is simply gone. And a UI test
asserts the banner's sentence verbatim, and that it warns without hiding the
page.

---

## 4.1 Deliberately left for later

Two findings from this work are written up in
[`plan-scoring-visibility-follow-ups.md`](plan-scoring-visibility-follow-ups.md)
rather than taken here: **Mismatches** renders a run whose pass crashed as
*"No mismatches in this run. Every labelled feature this model answered, it
answered correctly."* — a false and flattering sentence on the screen where a
human decides which model to believe; and the swap detection's reliance on the
old inode still being pinned, which option B (`NullPool`) would replace with a
structural guarantee at the cost of an amendment and a measurement.

## 5. What this plan deliberately does not do

- **No migration.** Nothing here stores a new fact about a run. The "scoring
  did not finish" state is *derived* — `done` + scoreable + no rows + not in
  flight — for the reason §16.1 gives for having no status column at all: the
  count that answers "how far did it get" must be the same one that answers
  "where does it resume".
- **No Score button.** `SD17` stands: scoring is chained, not triggered.
  Stage 1c adds **Re-score**, which is a different verb and already has a
  route, a service method and an empty-state sentence promising it.
- **No change to the Launch lock.** A launched evaluation is frozen; "New
  evaluation" is the path to another run, and the screen already says so.

## 6. If this happens again before the plan lands

The run's own log line carries the scoring task id. While the app is up:

```
curl -s 127.0.0.1:8080/api/v1/tasks/<the id from "scoring submitted as task ...">
```

`ok` means the boards exist and the page is stale — reload Results, or click
the run's **results** action. `failed` means the pass raised, and the task's
`error` says what. That question is the one Stage 2 makes unnecessary.

# Amendment — `fix/results-visibility`

> **APPLIED in the same commit**, as `fix-b1-census-value-samples`,
> `fix-b3-deletion-path` and `fix-evaluation-timeout-and-progress` were.
> No wave is running.

From a reported session rather than a review: a 48-record run over the
development seed finished cleanly, scoring succeeded, and the Results view was
empty. The full account is [`plan-fix-results-visibility.md`](../../plan-fix-results-visibility.md);
the measurement that decides it is this one, taken from the live process's own
task table with the id its log line had printed:

```
GET /api/v1/tasks/01a0c4c1-…  →  name score:01a0c4bf-…  status ok  done 7/7  error none
```

The pass had **succeeded**. Nothing was wrong with the data, and every path by
which the screen could have said so was broken. Three frozen files are touched.

---

## 1. `ra2/services/readmodels.py` — `ScoringStatusView.run_status`, `ScoringStatusView.scoring_stalled`, `DataDirView.database_replaced`

```diff
 class ScoringStatusView:
     run_id: RunId
     scored_features: int
     labelled_features: int
     running: bool
+    run_status: RunStatus = RunStatus.DONE
 
     @property
     def is_scored(self) -> bool:
         return self.labelled_features > 0 and self.scored_features >= self.labelled_features
+
+    @property
+    def is_finished(self) -> bool: ...
+
+    @property
+    def scoring_stalled(self) -> bool: ...
```

```diff
 class DataDirView:
     data_dir: str
     database_path: str
+    database_replaced: bool = False
```

**Why `run_status`.** §16.7's three states are not enough, and the missing one
is the reported one. A finished run with no `score` rows and no pass in flight
was rendered as *"Not scored yet. Scoring starts automatically when a run
completes"* — a promise about the next few seconds, worn by a run whose pass
had crashed hours earlier. Separating them needs the run's own status, and
this read model did not carry it.

**Not on `ScoringStatus` (`services/protocols.py`), which is left alone.**
That protocol answers "how far did the scoring get"; "is the run over" is the
run's own column, and `results_service` already holds the row when it builds
this view. Widening the seam would have made `ScoringStatus` a second place to
ask a question `Run` answers.

**Why `database_replaced`.** `just reset-seed` unlinks the SQLite file and
writes a new one. A live process keeps its pooled connections on the deleted
inode while every connection opened afterwards gets the new file, so it reads
and writes two databases at once, by pool luck, with no error anywhere.
Measured on this machine: sixteen concurrent reads in one process returned two
different corpora. Nothing can repair that from inside the process; it can say
so, and every screen the shell draws now does.

Both fields have defaults, so every existing construction keeps compiling and
every existing behaviour is the default.

## 2. `ra2/infra/tasks.py` — `AsyncioTaskRunner` and `InlineTaskRunner` log a failed task

```diff
+def _log_failure(task_id: TaskId, name: str, exc: BaseException) -> None:
+    _log.warning("task %s (%s) failed: %s", task_id, name, type(exc).__name__)
```

**The frozen part of this module is the protocol** (`TaskStatus`,
`TaskProgress`, `ProgressReporter`, `TaskWork`, `TaskRunner`), and it is
**byte-unchanged**. The two runner classes are A4's implementations, which
CONTRACTS.md lists as stubs in the same file — the "mixed files" note. The
amendment is filed anyway because the file carries `# FROZEN`.

**Why.** A failed task was recorded in `_ProgressTable` and nowhere else: no
log line, no persistence, gone at the next restart. A scoring pass that raised
therefore produced byte-identical output to one that succeeded — the run
worker's "scoring submitted as task …", and then silence. Diagnosing which had
happened meant asking the live process before anybody restarted it, which is
exactly what this incident required.

**The type, never the message.** `str(exc)` stays out of the log because a
SQLAlchemy error interpolates the statement's bound parameters into its
message, and a bound parameter here is a narrative (Do-NOT #13,
`data-handling.md` §5). The message is still in the task table, which is
per-process memory an analyst reaches deliberately, not a file on disk.
`tests/backend/services/scoring/test_scoring_is_visible.py` hides a narrative
in an exception and asserts it reaches no log record.

## 3. `ra2/services/scoring_service.py` — `+ submit_rescore`

```diff
+    async def submit_rescore(self, run_id: RunId) -> TaskId: ...
```

Signatures in this file are frozen; the constructor is unchanged and no
existing signature moves.

**Why.** `POST /api/v1/runs/{id}/rescore` answered `202 Accepted` with
`task_id` set to the **run's** id, after awaiting the entire pass — a status
code describing work that had already finished, and an id that
`GET /api/v1/tasks/{id}` answers 404 for. Both halves of the handshake the UI
polls with were wrong, which is one reason nothing in the product ever issued
that request. The UI's new Re-score control needs the same thing the API does:
work that is scheduled, under an id that can be polled.

**`async`, unlike `submit`.** The two refusals — no such run, and a run that is
not `done` — have to reach the caller as a 404 and a 409, and an exception
raised inside a scheduled task reaches nobody but the task table. So the guard
is read before anything is submitted; `_score` reads it again inside its own
transaction, and a run that changed status in between is refused by the one
that matters.

`ScoringService.status` now answers `running` from an in-flight counter instead
of the literal `False`. That is a **body** change, not a signature one, and it
needs no wiring: `main.py` already hands the same instance to `RunService` as
`ScoreSubmitter` and to `ResultsService`/`RankingService` as `Scorer`.

---

## What was done without an amendment

- `ra2/ui/shell.py` gains a `database_replaced: bool = False` keyword and the
  banner. Not frozen (`ra2/ui/**` is A5's), and the default keeps every
  existing call site and the shell's own tests working.
- `ra2/ui/views/results/__init__.py`, `ra2/ui/views/evaluation_view.py` and the
  seven views that pass `data_dir` — all stubs with owners, bodies only.
- `ra2/api/v1/results.py` — a stub router, U1's body.
- `ra2/services/{results,lifecycle}_service.py` — bodies.
- `scripts/reset_data.py` — the running-app warning. Named in CONTRACTS.md's
  reset table as a behaviour contract (`just reset` resolves `Settings` as the
  app does, prints the plan, refuses without the token); all three still hold,
  and a printed warning is an addition to the plan it already prints.

## What needs no migration

Nothing here stores a new fact about a run. "Scoring did not finish" is
derived — `done`, scoreable, nothing in flight, no rows — for the reason
§16.1 gives for having no status column at all: the count that answers "how
far did it get" must be the same one that answers "where does it resume".

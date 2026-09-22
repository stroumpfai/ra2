# Amendment — `perf-test-suite`

> **APPLIED in the same commit**, as `feat-reset-cli` and
> `fix-evaluation-timeout-and-progress` were. No wave is running.

`just test` took **13 min 20 s** on a 28-core machine. Measured, per layer,
without coverage:

| Layer | Tests | Wall | Per test |
|---|---|---|---|
| `tests/unit` | 720 | 7.2 s | 10 ms |
| `tests/*.py` | 468 | 3.6 s | 8 ms |
| `tests/backend` | 935 | 222 s | 237 ms |
| `tests/ui` | 337 | 329 s | 976 ms |
| `just test` (adds `--cov`) | 2461 | **800 s** | |

Two numbers decide this branch. The first, from a `pytest_fixture_setup`
timer: `run_upgrade_head` cost **59.5 s across 269 backend tests**, and
`migrated_db` **74.1 s across 306 UI tests** — one `alembic upgrade head` per
test, 220 ms each, ~230 s over the run, for a chain whose output never varied
between tests. The second: the suite is one process on a machine with 28 cores.

Neither is a test worth deleting. Two frozen files are touched, and
`sw-design.md` §11.2 is reworded because it is the sentence the first change
is about.

---

## 1. `pyproject.toml` — `+ pytest-xdist` (dev group)

```diff
     "pytest>=8.3",
     "pytest-asyncio>=0.24",
     "pytest-cov>=5.0",
+    "pytest-xdist>=3.6",
```

**Not in `addopts`.** A bare `uv run pytest <path>` stays single-process: a
live `pdb`, a readable traceback and a meaningful `-x` are worth more than
parallelism when you are debugging one test. Only `just test` and CI pass
`-n`.

Measured on the real gate, coverage included — the four gating layers share no
process state, so nothing needed changing to make them parallel-safe:

| Workers | Wall | Coverage |
|---|---|---|
| 1 | 800 s | 96.2 % |
| 4 | 192 s | 96.20 % |
| 8 | 95 s | 96.20 % |
| 16 | 67 s | 96.20 % |
| 28 | **51 s** | 96.20 % |

`pytest-cov` combines the workers' data itself, so `fail_under = 85` still
sees the whole run — the column above is the check, not an assumption.

**Layer 3 is the one that could have objected and does not.** NiceGUI's
`core.app` is a process-wide singleton, which is why `app_factory` defaults to
`mount_ui=False` and why the UI layer wraps every test in
`nicegui_reset_globals()`. An xdist worker is a *process* and runs one test at
a time, so each worker has its own singleton and the existing reset still does
exactly what it did. No `--dist` grouping is required; the default round-robin
`load` is what was measured.

## 2. `justfile` — `test` gains `-n auto`

```diff
 test:
-    uv run pytest -m "not e2e and not eval and not visual" --cov=ra2/domain --cov=ra2/services
+    uv run pytest -m "not e2e and not eval and not visual" --cov=ra2/domain --cov=ra2/services -n auto
```

`.github/workflows/ci.yml`'s layers-1–3 job gains the same flag. CI runners
have 2–4 cores, so CI gains perhaps 2× from this and most of its saving from
§3 below — which is the argument for doing both rather than only the one that
looks bigger locally.

## 3. `sw-design.md` §11.2 — the migration runs once per run, not once per test

```diff
 - The schema fixture runs **`alembic upgrade head`**, never `metadata.create_all`.
-  Every migration is therefore executed on every backend run.
+  Every migration is therefore executed on every backend run — **once per run**,
+  into a template database that each test copies. …
```

The guarantee is unchanged in substance and the wording now says which one it
is. Every migration still executes on every backend run, against a real
temp-file SQLite database (never `:memory:`, §11.2), still never
`metadata.create_all()` (§12.10), and `alembic check` still has a genuinely
migrated database to check. What changes is the multiplier: once for the run
instead of once for each of the 1050 tests that need a schema. Under `-n`,
once per worker.

A migrated `ra2.sqlite` is 401 KB and the copy costs **0.113 ms** against the
chain's 220 ms. WAL and `-shm` are properties of a *connection*, not of the
schema, so there is nothing to carry across: `create_engine` re-establishes
them per test through its connect-time PRAGMAs, which is what
`tests/backend/persistence/test_session_pragmas.py` asserts and what keeps
§11.2's "not in-memory" reason intact.

**`test_migrations.py` keeps a real per-test upgrade** (`freshly_migrated`).
A test named `test_upgrade_head_creates_every_table` that asserted against a
file copy would be testing `shutil.copy`. `test_alembic_check_reports_no_drift`
takes the same fixture for the same reason.

## 4. `tests/ui/conftest.py` — `app_factory` disposes the engines it builds

Not frozen, and not a performance change: **the parallel gate was red two runs
in three until this**, and the same bug was there serially all along, winning
by luck.

```diff
+@pytest.fixture
+async def app_factory(
+    app_factory: Callable[..., FastAPI],
+) -> AsyncIterator[Callable[..., FastAPI]]:
+    built: list[FastAPI] = []
+
+    def _tracking(**overrides: object) -> FastAPI:
+        app = app_factory(**overrides)
+        built.append(app)
+        return app
+
+    yield _tracking
+
+    for app in built:
+        await app.state.engine.dispose()
```

`create_app()` builds an engine (`main.py`: `engine = engine or
create_engine(...)`, then `app.state.engine = engine`) and never disposes it —
correctly, because the process owns it for its lifetime. Nothing in layer 3
disposed it either, so every UI test left an engine behind with live pooled
aiosqlite connections, finalised later by the garbage collector:

```
E  ResourceWarning: <aiosqlite.core.Connection object …> was deleted before being closed
E  pytest.PytestUnraisableExceptionWarning: Exception ignored while calling
   deallocator <function Connection.__del__ …>
```

`filterwarnings = ["error"]` turns that into an error in **whichever test is
running when the collector gets to it**, which is why it read as flakiness in
tests that had nothing to do with it, and why the other failure mode looked
unrelated (`AssertionError: condition never became true` — a 5 s poll budget
in `test_evaluation_view.py` losing its event loop).

**Why the wrapper and not fifteen edits.** `user` is not the only app in this
layer: fifteen view-specific fixtures across eight `test_*.py` files mount
their own app with their own seeding and overrides, and each `finally` block
popped `NICEGUI_USER_SIMULATION` and disposed nothing. Wrapping the factory
they all go through is one place that is right instead of fifteen that have to
stay right. Overriding a fixture while requesting the enclosing one of the
same name is pytest's own idiom for this, so the **frozen root `app_factory`
is untouched**.

**Layer 2 needs none of it, and the reason is worth writing down.**
`tests/backend/api/conftest.py`'s `api_app` injects `session_factory=`, so the
engine `create_app` builds for it is never used: no connection is ever opened
through it, so there is nothing for the collector to complain about.
`tests/backend/conftest.py`'s `migrated_engine` already disposes the engine
the layer actually queries through, and
`tests/backend/services/run/conftest.py` disposes the two it builds itself.
Layer 3 was the one layer whose apps owned *live* engines and disposed none.

Not frozen files, so listed here only because they are the change:
`tests/fixtures/migrations.py` (new — the chain, in one place, for the two
layers that need it), `tests/backend/conftest.py`, `tests/ui/conftest.py`,
`tests/backend/persistence/test_migrations.py`.

---

## What this does not do

`tests/ui` is the residual and stays the slowest layer: with the migration
gone it is ~255 s serial for 337 tests, ~0.76 s each, essentially all of it
building and mounting a fresh FastAPI + NiceGUI app per test. That is what the
singleton and `nicegui_reset_globals()` require, and no fixture caching gets
around it; parallelism is what makes it tolerable rather than any change to
the layer. Fewer, richer UI tests would be the only other lever, and trading
away one-behaviour-per-test is not a performance decision.

Coverage costs ~42 % serially (562 s → 800 s) and is left on the gate
unchanged: at `-n auto` it is absorbed, and `fail_under = 85` scoped to
`domain` + `services` is a gate in `pyproject.toml`'s frozen block.

**`tests/ui/test_evaluation_view.py` is flaky, and it is not this branch's
doing.** Two tests — `test_the_progress_poll_never_re_probes_the_endpoint` and
`test_an_active_run_offers_stop_and_an_inactive_one_offers_discard` — fail
intermittently on `_until(lambda: _statuses(user) == {"done"})` at line 492:
the run is set to `done` in the database and the runs table never shows it.
Running that one file in a loop:

| Tree | Runs | Red |
|---|---|---|
| `f42e53f`, none of this branch | 25 | **6** |
| this branch | 16 | 5 |

The same two tests, the same assertion, the same rate. It was there before any
of this and the parallel gate did not cause it; what the gate did was make it
visible, because a suite you run in 34 seconds gets run enough times to notice
a one-in-four.

**It is not a timing budget, which is worth recording so nobody re-tries
that.** The obvious reading is that `for _ in range(500): await
asyncio.sleep(0.01)` is five seconds and a starved worker needs more. It is
not: raised to sixty seconds the wait burns the whole sixty and the condition
is still false. The page is stuck, not slow. `refresh_progress` re-reads
`_all_runs` and re-renders the progress slot, and `_settled` deactivates the
timer as soon as no run is `queued` or `running` — so a poll that stops, or a
read that keeps a stale SQLite snapshot, would both produce exactly this, and
neither is something to guess at from the outside. Diagnosing it belongs with
whoever owns that view.

**A pre-existing `just lint` failure is not touched.** `uv run mypy` reports
`tests/e2e/conftest.py:97: error: Statement is unreachable` on Linux, on
clean `main`, with no change of mine in the tree: the statement is after
`if sys.platform != "win32": return`, which mypy narrows away on the platform
it is run from. It is nothing to do with this branch, and fixing it inside a
performance branch would bury it.

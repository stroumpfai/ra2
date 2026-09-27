# Amendment — `fix/settings-with-no-reader`

> **Applied file by file in the stage whose code needs it**, as
> `fix-ranking-vram` was. No wave is running.

`plan-settings-with-no-reader.md`, design `sw-design.md` **SD42**. Five frozen
files, **no revision**. The defect is the category `docs/risk-assesment.md` G3
named — *a setting that implies a control nobody implemented* — with three live
instances:

| Setting | Documented as | Actually |
|---|---|---|
| `Settings.host` | "bind to loopback by default (N1)" | read by nothing; the `justfile`'s `--host` binds |
| `Settings.port` | the same | read by nothing; the `justfile`'s `--port` binds, and `scripts/dev_agent.py` sets `RA2_PORT` and then passes `--port` because nothing reads it |
| `Settings.min_cell_count` | the draft's default (`models.py:716`) | read by nothing; every `evaluation.min_cell_count` is the column's own `20`, and there is no control for mvp-spec.md §11.4's "configurable per evaluation" |

`run_concurrency` is **not** an instance and is not touched: it has a reader
(`run_service._execute_serially`), a tested refusal, and §15 F7's reason to
exist ahead of its use.

---

## 1. `ra2/infra/config.py` — docstrings only *(Stage 1)*

```diff
-    #: Bind to loopback by default. No egress, no external listener (N1).
+    #: The bind, read by `ra2 serve` (`SD42`) — which **refuses** a host
+    #: outside `domain.llm.LOOPBACK_HOSTS` before it opens a socket. No egress,
+    #: no external listener (N1), and deliberately no opt-out, for
+    #: `require_loopback`'s reason. The check lives in the launcher because
+    #: that is where the bind is decided; `create_app()` never knows it.
     host: str = "127.0.0.1"
```

```diff
-    #: D3 — cells below this render as "insufficient data". Unused until scoring.
+    #: mvp-spec.md §11.4 — cells below this render as "insufficient data".
+    #: **The default a new draft is seeded with** (`SD42`); the floor itself is
+    #: `evaluation.min_cell_count`, per evaluation and pinned at launch (`SD19`).
     min_cell_count: int = 20
```

**No field, default or validator changes.** The two comments were the defect's
documentation half: one promised a bind nothing performed, the other said
"unused" about a value `results_service` and `ranking_service` had been
reading off the column for a phase.

## 2. `ra2/cli.py` — `+ serve` *(Stage 3)*

A subcommand that builds `Settings`, refuses a host outside
`LOOPBACK_HOSTS`, and hands `ra2.main:create_app` to `uvicorn.run` as a factory
on `settings.host` / `settings.port`. `--reload` watches `ra2/` alone, which
is what `dev-reload`'s `--reload-dir ra2` did.

**Why here and not in `create_app()`:** the bind is decided by whoever runs the
server, and `create_app()` is handed to a server it cannot see. `cli.py` is
already a composition root outside the layers contract (`.importlinter`), so
reading `infra.config` and `domain.llm` is wiring, not a layer breach.

**Why `LOOPBACK_HOSTS` and not a new check:** it is public in `domain/llm.py`
and is "the **one** statement of the rule" `classify_endpoint` compares a URL's
host against, literally, with no DNS. Reusing it means `domain/llm.py` needs no
amendment and the egress and bind halves of N1 cannot drift apart.

**No opt-out.** A refused host exits non-zero before `uvicorn.run` is called,
with a sentence naming the value and N1.

## 3. `justfile` — `dev` and `dev-reload` call `serve` *(Stage 3)*

```diff
 dev:
-    uv run uvicorn ra2.main:create_app --factory --host 127.0.0.1 --port 8080
+    uv run python -m ra2.cli serve
```

```diff
 dev-reload:
-    uv run uvicorn ra2.main:create_app --factory --reload --reload-dir ra2 --host 127.0.0.1 --port 8080
+    uv run python -m ra2.cli serve --reload
```

The defaults are unchanged — `127.0.0.1:8080` — and now come from the one place
§10 says they do. `RA2_PORT=9001 just dev` starts working; `RA2_HOST=0.0.0.0
just dev` starts being refused. "Final" has meant *by amendment only* four
times already.

`scripts/dev_agent.py` is not frozen and changes with it: it stops passing
`--host`/`--port`, sets `RA2_HOST=127.0.0.1` and `RA2_PORT` in the child
environment, and runs `serve`. The variable it always set becomes the one that
decides.

## 4. `ra2/services/readmodels.py` — `+ EvaluationDraftView.min_cell_count` *(Stage 5)*

```diff
     reasoning_effort: str = DEFAULT_REASONING_EFFORT
+    #: mvp-spec.md §11.4's floor, per evaluation (`SD19`, `SD42`). Defaulted,
+    #: like `reasoning_effort`, so every constructor that predates it holds.
+    min_cell_count: int = 20
```

Step 5's control has to show the draft's floor, and the draft view is how the
view learns anything about a draft.

## 5. `ra2/api/schemas.py` — the same on the draft request and response *(Stage 5)*

`min_cell_count: int | None = Field(default=None, ge=1)` on the update
request, beside `temperature`, `seed` and `reasoning_effort`; `min_cell_count:
int = 20` on the draft response. **Additive**; `tests/api/openapi_snapshot.json`
is regenerated. The API and the UI are two adapters over one service, so a
field the view can set is a field a request can set.

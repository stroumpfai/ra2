# `just` is the entire command surface (ra2.md). Nothing here shells out to
# anything platform-specific: these recipes run identically on Windows and
# Linux (N3).

set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

# List the recipes.
default:
    @just --list

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

# `just` renders only the **last** comment line of a contiguous block beside a
# recipe in `just --list`, so each recipe's reasoning sits above a blank line
# and its one-line summary sits directly on top of it.
#
# **No `--reload` on `dev`.** An evaluation run is minutes per record and tens
# of minutes end to end; uvicorn's reloader watches the whole working directory
# for `*.py`, recursively, which here includes `tests/`, `scripts/` and every
# `.claude/worktrees/agent-*` full copy of this project. One file written
# anywhere in that tree kills the worker mid-record, and the run is left
# `interrupted` with "the process died while this run was executing" — true,
# and useless. N6's restart-safety is what makes that recoverable rather than
# lost; it is a guarantee about consequences, not a licence to restart. A file
# watcher and a half-hour job cannot share a process.

# Run the app on 8080 against ./var: FastAPI + NiceGUI, one process, no watcher.
dev:
    uv run uvicorn ra2.main:create_app --factory --host 127.0.0.1 --port 8080

# For UI and view work, where an iteration is seconds and nothing long-running
# is in flight. **Never with a run executing** — see the note above `dev`.
#
# `--reload-dir ra2` is the part that was always missing: an unscoped watcher
# on a repository that contains copies of itself restarts on a test file, a
# script, or an agent working in a worktree under this directory.

# `dev` with the file watcher on, scoped to `ra2/` alone.
dev-reload:
    uv run uvicorn ra2.main:create_app --factory --reload --reload-dir ra2 --host 127.0.0.1 --port 8080

# Agents verifying a change run this, never bare `dev` — sharing port 8080 or
# `./var` with a developer's own manual testing session has clobbered their
# live test data before. No watcher either, and for a sharper reason: an agent
# is by definition writing `*.py` in this tree, so the only thing a watcher
# could achieve here is an agent killing the run it launched to look at.

# `dev` on a random free port against a throwaway RA2_DATA_DIR.
dev-agent:
    uv run python scripts/dev_agent.py

# ---------------------------------------------------------------------------
# Gates (sw-design.md §11.7)
# ---------------------------------------------------------------------------

# The commit gate: unit + backend + ui.
test:
    uv run pytest -m "not e2e and not eval and not visual" --cov=ra2/domain --cov=ra2/services

# The PR gate: the Playwright journeys.
e2e:
    uv run pytest -m e2e --tracing=retain-on-failure --screenshot=only-on-failure

# Refuse any tracked file that looks like a real delivery (risk C1). The same
# check the pre-commit hook runs per file, over the whole tree — which is what
# CI runs.
check-data:
    uv run python scripts/check_no_real_data.py --all

# ruff + mypy strict + the §1.1 layer contract. All three, or it is not green.
lint:
    uv run ruff format --check .
    uv run ruff check .
    uv run mypy
    uv run lint-imports

# Apply the formatter and the autofixes.
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# ---------------------------------------------------------------------------
# Reset (sw-design.md §18, plan-reset-and-discard.md §5)
# ---------------------------------------------------------------------------

# Show what a wipe of RA2_DATA_DIR would remove. `just reset yes` carries it out.
reset token="":
    uv run python scripts/reset_data.py {{token}}

# Wipe, then seed a working state. Needs the same token: `just reset-seed yes`.
reset-seed token="":
    uv run python scripts/reset_data.py {{token}}
    uv run python scripts/seed_dev.py

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# Bring the database up to head. Reads RA2_DB_PATH / RA2_DATA_DIR.
migrate:
    uv run alembic upgrade head

# ONE migration author for all of phase 1 (A3). Never edit an applied one.
revision message:
    uv run alembic revision --autogenerate -m "{{message}}"

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

# Export a corpus's census as CSV: UTF-8 with BOM, ';' delimited (N3).
census-export corpus_id out:
    uv run python -m ra2.cli census-export --corpus-id {{corpus_id}} --out {{out}}

# Install the Chromium the E2E layer drives. Chromium only, no other browser.
setup-e2e:
    uv run playwright install chromium

# Phase 3: the eval suite against real Ollama, gated on evals/baseline.json.
eval:
    uv run pytest -m eval

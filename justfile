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

# Run the app: FastAPI + NiceGUI in one process, on one port.
dev:
    uv run uvicorn ra2.main:create_app --factory --reload --host 127.0.0.1 --port 8080

# ---------------------------------------------------------------------------
# Gates (sw-design.md §11.7)
# ---------------------------------------------------------------------------

# The commit gate: unit + backend + ui.
test:
    uv run pytest -m "not e2e and not eval and not visual" --cov=ra2/domain --cov=ra2/services

# The PR gate: the Playwright journeys.
e2e:
    uv run pytest -m e2e --tracing=retain-on-failure --screenshot=only-on-failure

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

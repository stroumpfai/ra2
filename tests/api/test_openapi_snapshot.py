"""The OpenAPI schema drift gate (plan-m0-m5.md §7's C2 exit criterion).

`tests/api/openapi_snapshot.json` is committed. This test rebuilds the app
fresh, regenerates its schema, and asserts it matches the committed file
**exactly** — the same idea as `alembic check` for the wire contract: if a
future change to any router or schema (C1's or C2's) silently changes what
the API promises, this is what catches it.

The schema depends only on route registration and Pydantic model shapes, not
on runtime state, so a `Settings` pointed at an isolated temp directory is
enough — no database is ever touched (`create_app(mount_ui=False)` builds an
engine lazily; `.openapi()` never opens a connection).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from ra2.infra.config import Settings
from ra2.main import create_app

__all__ = ["SNAPSHOT_PATH", "generate_schema", "render_schema"]

SNAPSHOT_PATH = Path(__file__).with_name("openapi_snapshot.json")

pytestmark = pytest.mark.backend


def generate_schema(tmp_data_dir: Path) -> dict[str, Any]:
    """Builds a fresh app (`mount_ui=False`, no NiceGUI, no real DB
    connection) and returns its OpenAPI schema."""
    settings = Settings(data_dir=tmp_data_dir, _env_file=None)
    app = create_app(settings=settings, mount_ui=False)
    return app.openapi()


def render_schema(schema: dict[str, Any]) -> str:
    """Canonical text form: sorted keys, stable indentation, one trailing
    newline — so the committed file is both a diffable artifact and this
    test's exact comparison target."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def test_openapi_schema_matches_the_committed_snapshot(tmp_data_dir: Path) -> None:
    fresh_schema = generate_schema(tmp_data_dir)
    fresh_text = render_schema(fresh_schema)

    committed_text = SNAPSHOT_PATH.read_text(encoding="utf-8")

    assert fresh_text == committed_text, (
        "The OpenAPI schema has drifted from tests/api/openapi_snapshot.json. "
        "If this change to the wire contract is intentional, regenerate the "
        "snapshot and commit it."
    )

"""The committed codelist hazard fixtures and their generator must not drift.

Same reasoning as `tests/unit/parsing/test_generated_fixtures.py`: the
fixtures are committed so tests do not depend on running the generator, and
that is only true while the two agree.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

GENERATOR = (
    Path(__file__).resolve().parents[2] / "fixtures" / "codelists" / "generate_codelist_hazards.py"
)


def _generator() -> ModuleType:
    """Import the generator by path — `tests/fixtures/` is not a package."""
    spec = importlib.util.spec_from_file_location("ra2_generate_codelist_hazards", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixtures_are_byte_identical_to_the_generator_output(cl):
    """Regenerating must be a no-op. If this fails, run
    `uv run python tests/fixtures/codelists/generate_codelist_hazards.py`."""
    built = _generator().build()
    for relative, expected in built.items():
        path = cl.dir / relative
        assert path.is_file(), f"{relative} is not committed"
        assert path.read_bytes() == expected, relative


def test_the_generator_is_deterministic():
    module = _generator()
    assert module.build() == module.build()


def test_no_committed_file_is_missing_from_the_generator(cl):
    built = set(_generator().build())
    committed = {f"{path.parent.name}/{path.name}" for path in cl.dir.rglob("*") if path.is_file()}
    assert committed == built


def test_every_fixture_filename_is_one_the_real_data_hook_would_allow():
    """`codes-2018.json`, `.xlsx`/`.xls`/`.zip` and anything under `data/`
    are refused by `scripts/check_no_real_data.py` — a fixture must never be
    named like the thing it stands in for."""
    forbidden_names = {"codes-2018.json"}
    forbidden_suffixes = (".xlsx", ".xls", ".zip")
    for relative in _generator().build():
        name = relative.split("/")[-1]
        assert name not in forbidden_names, relative
        assert not name.endswith(forbidden_suffixes), relative


def test_every_fixture_is_well_formed_json():
    for payload in _generator().build().values():
        json.loads(payload.decode("utf-8"))

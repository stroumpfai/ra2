"""The committed prompt hazard fixtures and their generator must not drift.

Same reasoning as `tests/unit/codes/test_generated_codelist_fixtures.py`: the
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
    Path(__file__).resolve().parents[2] / "fixtures" / "prompts" / "generate_prompt_hazards.py"
)


def _generator() -> ModuleType:
    """Import the generator by path — `tests/fixtures/` is not a package."""
    spec = importlib.util.spec_from_file_location("ra2_generate_prompt_hazards", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixtures_are_byte_identical_to_the_generator_output(ph):
    """Regenerating must be a no-op. If this fails, run
    `uv run python tests/fixtures/prompts/generate_prompt_hazards.py`."""
    built = _generator().build()
    for relative, expected in built.items():
        path = ph.dir / relative
        assert path.is_file(), f"{relative} is not committed"
        assert path.read_bytes() == expected, relative


def test_the_generator_is_deterministic():
    module = _generator()
    assert module.build() == module.build()


def test_no_committed_file_is_missing_from_the_generator(ph):
    built = set(_generator().build())
    committed = {f"{path.parent.name}/{path.name}" for path in ph.dir.rglob("*") if path.is_file()}
    assert committed == built


def test_every_fixture_filename_is_one_the_real_data_hook_would_allow():
    """No fixture may be named like the thing it stands in for, or match the
    real-data patterns `scripts/check_no_real_data.py` refuses."""
    forbidden_suffixes = (".xlsx", ".xls", ".zip")
    for relative in _generator().build():
        name = relative.split("/")[-1]
        assert not name.endswith(forbidden_suffixes), relative


def test_every_json_fixture_is_well_formed():
    for relative, payload in _generator().build().items():
        if relative.endswith(".json"):
            json.loads(payload.decode("utf-8"))


def test_p06_manifest_actually_carries_the_hazard_it_is_named_for(ph):
    """Guards the fixture itself: p06 must contain an enum code with no
    label in the manifest's own requested language, or the test asserting
    the fallback would be vacuously true."""
    manifest = ph.features_manifest("p06_enum_missing_label")
    language = manifest["language"]
    enum_features = [f for f in manifest["features"] if f["value_type"] == "enum"]
    assert enum_features, "p06 must contain at least one enum feature"
    missing = [
        code["code"]
        for feature in enum_features
        for code in feature["enum_codelist"]
        if language not in code["label"]
    ]
    assert missing, f"no code is missing a {language!r} label — the hazard fixture is vacuous"

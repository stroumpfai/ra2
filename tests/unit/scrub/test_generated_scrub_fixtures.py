"""The committed scrub fixtures and their generator must not drift.

Same reasoning as `tests/unit/codes/test_generated_codelist_fixtures.py`: the
fixtures are committed so tests do not depend on running the generator, and
that is only true while the two agree.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "scrub"
GENERATOR = FIXTURES / "generate_scrub_fixtures.py"


def _generator() -> ModuleType:
    """Import the generator by path: `tests/fixtures/` is not a package."""
    spec = importlib.util.spec_from_file_location("ra2_generate_scrub_fixtures", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixtures_are_byte_identical_to_the_generator_output() -> None:
    """Regenerating must be a no-op. If this fails, run
    `uv run python tests/fixtures/scrub/generate_scrub_fixtures.py`."""
    for relative, expected in _generator().build().items():
        path = FIXTURES / "hazards" / relative
        assert path.is_file(), f"{relative} is not committed"
        assert path.read_bytes() == expected, relative


def test_the_generator_is_deterministic() -> None:
    module = _generator()
    assert module.build() == module.build()


def test_no_committed_file_is_missing_from_the_generator() -> None:
    built = set(_generator().build())
    committed = {p.name for p in (FIXTURES / "hazards").iterdir() if p.is_file()}
    assert committed == built


def test_no_fixture_matches_the_pattern_that_keeps_real_lists_out_of_git() -> None:
    """`*.names.txt` and `scrub-lists/` are ignored so a downloaded list
    cannot be committed by accident. A fixture named that way would be
    ignored too, and silently absent from a fresh clone."""
    for relative in _generator().build():
        assert not relative.endswith(".names.txt"), relative
        assert "scrub-lists" not in relative, relative

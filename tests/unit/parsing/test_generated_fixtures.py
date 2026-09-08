"""The committed hazard fixtures and their generator must not drift apart.

`generate_hazards.py` exists so the hazards are "readable and reviewable"
(sw-design.md §11), and the files are committed so tests do not depend on
running it. Both are only true while the two agree, so that is asserted rather
than assumed.

These tests also police the rule that keeps the fixtures legal: they are
**synthetic**. Real delivery files must never reach a test (§12.11), and the
`no-real-data` pre-commit hook only filters by *filename*, so the shape of the
committed bytes is checked here as the second line of defence.
"""

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from ra2.domain.parsing.headers import CANONICAL_HEADERS

GENERATOR = Path(__file__).resolve().parents[2] / "fixtures" / "deliveries" / "generate_hazards.py"


def _generator() -> ModuleType:
    """Import the generator by path.

    It lives under `tests/fixtures/`, which is not a package and is not on
    `sys.path`; loading it by location is how a test reaches it without adding
    an `__init__.py` that would change how pytest names every module beneath.
    """
    spec = importlib.util.spec_from_file_location("ra2_generate_hazards", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixtures_are_byte_identical_to_the_generator_output(hz):
    """Regenerating must be a no-op. If this fails, run
    `uv run python tests/fixtures/deliveries/generate_hazards.py`."""
    built = _generator().build()
    for relative, expected in built.items():
        path = hz.dir / relative
        assert path.is_file(), f"{relative} is not committed"
        assert path.read_bytes() == expected, relative


def test_the_generator_is_deterministic():
    """No clock, no randomness, no dict-ordering luck."""
    module = _generator()
    assert module.build() == module.build()


def test_no_committed_file_is_missing_from_the_generator(hz):
    """A hand-edited fixture would survive the check above and silently stop
    being reproducible. Compare in both directions."""
    built = set(_generator().build())
    committed = {f"{path.parent.name}/{path.name}" for path in hz.dir.rglob("*") if path.is_file()}
    assert committed == built


def test_every_fixture_filename_is_one_the_real_data_hook_would_allow():
    """`vum_*.txt`, `AstranaExport*`, `*.xlsx`, `*.xls`, `*.zip` and anything
    under `data/` are refused by `scripts/check_no_real_data.py`. A fixture must
    never be named like the thing it stands in for."""
    forbidden_prefixes = ("vum_", "AstranaExport")
    forbidden_suffixes = (".xlsx", ".xls", ".zip")
    for relative in _generator().build():
        name = relative.split("/")[-1]
        assert not name.startswith(forbidden_prefixes), relative
        assert not name.endswith(forbidden_suffixes), relative


def test_the_fixtures_carry_only_synthetic_keys(hz):
    """Every 32-hex key in the committed bytes follows the generator's scheme:
    a short hex tag then decimal digits. A real `UnfallUid` would not."""
    key_pattern = re.compile(rb"\b[0-9a-fA-F]{32}\b")
    synthetic = re.compile(rb"^(aa|bb|cc|dd|ee|ff)0*\d+$")
    for path in sorted(p for p in hz.dir.rglob("*") if p.is_file()):
        for key in key_pattern.findall(path.read_bytes()):
            assert synthetic.match(key), (path.name, key)


@pytest.mark.parametrize("kind", list(CANONICAL_HEADERS))
def test_the_generator_builds_rows_at_the_canonical_width(kind):
    """The fixtures take their width from `CANONICAL_HEADERS`, so a 67-column
    file stays 67 columns without anybody counting."""
    module = _generator()
    row = module._row(kind, "k", {})
    assert len(row) == len(CANONICAL_HEADERS[kind])


def test_uid_refuses_a_tag_that_is_not_short_lowercase_hex():
    """The keys have to satisfy `^[0-9A-Fa-f]{32}` or the fixtures would not be
    exercising the anchor at all."""
    module = _generator()
    assert len(module.uid("aa", 1)) == 32
    with pytest.raises(ValueError, match="hex"):
        module.uid("zz", 1)

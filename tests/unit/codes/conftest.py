"""Fixtures for `ra2.domain.codes` unit tests (D1).

Mirrors `tests/unit/parsing/conftest.py`'s `hz` pattern: the committed hazard
fixtures are exposed through one fixture object rather than as importable
module-level helpers, since more than one `conftest.py` sits on the path.
"""

from pathlib import Path

import pytest

CODELIST_HAZARDS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "codelists" / "hazards"


class CodelistHazards:
    """Loading the committed codelist hazard fixtures (c01-c05)."""

    dir = CODELIST_HAZARDS_DIR

    def raw_json(self, hazard: str) -> str:
        """One committed hazard's `codelist.json`, decoded as the app would.

        `encoding="utf-8"` explicit per Do-NOT list #4 — this file was written
        as UTF-8 bytes by the generator and must be read back the same way.
        """
        path = self.dir / hazard / "codelist.json"
        assert path.is_file(), f"missing fixture {path} — run generate_codelist_hazards.py"
        return path.read_text(encoding="utf-8")


@pytest.fixture
def cl() -> CodelistHazards:
    return CodelistHazards()

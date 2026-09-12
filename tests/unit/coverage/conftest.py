"""Fixtures for `ra2.domain.codelist_coverage` unit tests (D1).

Some coverage boundaries are clearest against a hand-typed `CodeAttribute`/
`CodeValue` list; others (c02's real de/fr-only gap, c03's zero-code attribute,
c05's orphan value) are clearer read straight off the committed codelist
hazard fixtures — same rationale, and the same `cl` fixture shape, as
`tests/unit/codes/conftest.py`. Duplicated rather than imported: test modules
in sibling directories cannot reliably `from conftest import ...`, and a
fixture is what pytest guarantees.
"""

from pathlib import Path

import pytest

CODELIST_HAZARDS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "codelists" / "hazards"


class CodelistHazards:
    """Loading the committed codelist hazard fixtures (c01-c05)."""

    dir = CODELIST_HAZARDS_DIR

    def raw_json(self, hazard: str) -> str:
        path = self.dir / hazard / "codelist.json"
        assert path.is_file(), f"missing fixture {path} — run generate_codelist_hazards.py"
        return path.read_text(encoding="utf-8")


@pytest.fixture
def cl() -> CodelistHazards:
    return CodelistHazards()

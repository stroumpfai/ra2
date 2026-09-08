"""Fixtures for the parsing layer's unit tests (A1).

`tests/conftest.py` is frozen and holds root fixtures only, so anything
specific to one layer lives beside that layer's tests (sw-design.md §11).
Nothing here touches a database, a session or the network: the parsing domain
is pure and its tests are milliseconds.

Everything is exposed through the single `hz` fixture rather than as importable
module-level helpers. Test modules in sibling directories cannot reliably
`from conftest import ...` — there is more than one `conftest` on the path —
and a fixture is what pytest guarantees.
"""

from pathlib import Path

import pytest

from ra2.domain.findings import Finding, FindingCode
from ra2.domain.ids import FileId
from ra2.domain.parsing.analysis import ParsedFile, analyse_file

HAZARDS_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "deliveries" / "hazards"


class Hazards:
    """Loading and asserting over the committed hazard fixtures."""

    dir = HAZARDS_DIR

    def bytes_of(self, hazard: str, filename: str) -> bytes:
        """One committed hazard file, verbatim.

        Byte-exact matters: the fixtures encode encodings, line endings and
        stray delimiters, none of which survives a text round trip.
        """
        path = self.dir / hazard / filename
        assert path.is_file(), f"missing fixture {path} — run generate_hazards.py"
        return path.read_bytes()

    def parse(
        self,
        hazard: str,
        filename: str,
        *,
        selected: bool = True,
        **kwargs: object,
    ) -> ParsedFile:
        """Analyse one hazard file end to end.

        `file_id` names the fixture so a failing assertion reads. It is an id,
        never a source of meaning — `FileKind` still comes from the header.
        """
        return analyse_file(
            file_id=FileId(f"{hazard}/{filename}"),
            filename=filename,
            data=self.bytes_of(hazard, filename),
            selected=selected,
            **kwargs,  # type: ignore[arg-type]
        )

    def parse_all(self, hazard: str, **deselect: bool) -> list[ParsedFile]:
        """Every file of one hazard directory, in sorted order.

        `parse_all("h07…", ag_unfall=False)` deselects by file stem, for the
        tests that check a deselected file takes no part in cross-file checks.
        """
        return [
            self.parse(hazard, path.name, selected=deselect.get(path.stem, True))
            for path in sorted((self.dir / hazard).iterdir())
        ]

    @staticmethod
    def codes(findings: tuple[Finding, ...] | list[Finding]) -> list[FindingCode]:
        return [f.code for f in findings]

    @staticmethod
    def of_code(
        findings: tuple[Finding, ...] | list[Finding], code: FindingCode
    ) -> list[Finding]:
        """Every finding with `code`. Tests assert on the code, never on prose."""
        return [f for f in findings if f.code is code]

    def only(self, findings: tuple[Finding, ...] | list[Finding], code: FindingCode) -> Finding:
        matches = self.of_code(findings, code)
        assert len(matches) == 1, f"expected exactly one {code}, got {self.codes(findings)}"
        return matches[0]

    @staticmethod
    def detail_values(finding: Finding) -> set[str]:
        """Every value in `detail` — what "the key is in the report" means."""
        return set(finding.detail.values())

    @staticmethod
    def uid(tag: str, number: int) -> str:
        """The generator's key scheme, restated so a test reads on its own."""
        return f"{tag}{number:0{32 - len(tag)}d}"


@pytest.fixture
def hz() -> Hazards:
    return Hazards()

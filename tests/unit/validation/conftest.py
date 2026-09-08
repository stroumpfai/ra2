"""Fixtures for delivery validation's unit tests (A1).

Cross-file validation is about *relationships between files*, so its tests are
built from small in-memory tables rather than from the hazard fixtures — a
duplicate key is clearer as four rows than as two 67-column files. The hazard
fixtures cover the same rules end to end in
`tests/unit/parsing/test_hazards_h01_h12.py`.

Everything is exposed through one `build` fixture rather than as importable
module-level helpers: test modules in sibling directories cannot reliably
`from conftest import ...`, and a fixture is what pytest guarantees.
"""

import pytest

from ra2.domain.delivery import DeliveryAnalysis, Dialect, Encoding, FileAnalysis, FileKind
from ra2.domain.findings import Finding, FindingCode
from ra2.domain.ids import FileId
from ra2.domain.parsing.analysis import ParsedFile
from ra2.domain.parsing.headers import CANONICAL_HEADERS

PIPE = Dialect(delimiter="|")
SEMI = Dialect(delimiter=";")


class Builder:
    """Assemble `ParsedFile`s directly, without going through bytes.

    `validate_delivery` takes what analysis produced; constructing that here
    keeps a test about orphan keys from also being a test about CSV quoting.
    """

    @staticmethod
    def uid(tag: str, number: int) -> str:
        return f"{tag}{number:0{32 - len(tag)}d}"

    def file(
        self,
        kind: FileKind,
        rows: list[dict[str, str]],
        *,
        name: str | None = None,
        canton: str | None = None,
        selected: bool = True,
        columns: tuple[str, ...] | None = None,
    ) -> ParsedFile:
        """One analysed file of `kind`, carrying `rows`.

        Each row is given by column name; every other canonical column is
        filled, so the file is the right width and the positional lookups being
        tested are real ones. Unnamed **key** columns are filled with `""`
        rather than a placeholder: empty means "no value provided" (§8.6), and
        it keeps a test about orphan keys from inventing keys of its own.
        """
        header = columns if columns is not None else CANONICAL_HEADERS[kind]
        filename = name or f"{kind.value}.txt"
        cells = tuple(
            tuple(
                row.get(column, "" if column.endswith("Uid") else f"x{index}")
                for index, column in enumerate(header)
            )
            for row in rows
        )
        analysis = FileAnalysis(
            file_id=FileId(filename),
            filename=filename,
            kind=kind,
            encoding_detected=Encoding.UTF_8,
            dialect_detected=SEMI if kind is FileKind.TEXT else PIPE,
            encoding=Encoding.UTF_8,
            dialect=SEMI if kind is FileKind.TEXT else PIPE,
            header=tuple(header),
            header_ok=True,
            row_count=len(cells),
            ok_count=len(cells),
            canton=canton,
        )
        return ParsedFile(analysis=analysis, rows=cells, selected=selected)

    @staticmethod
    def codes(analysis: DeliveryAnalysis) -> list[FindingCode]:
        return [f.code for f in analysis.findings]

    @staticmethod
    def of_code(analysis: DeliveryAnalysis, code: FindingCode) -> list[Finding]:
        """Cross-file findings with `code`. Tests assert on the code, not prose."""
        return [f for f in analysis.findings if f.code is code]

    def only(self, analysis: DeliveryAnalysis, code: FindingCode) -> Finding:
        matches = self.of_code(analysis, code)
        assert len(matches) == 1, f"expected one {code}, got {self.codes(analysis)}"
        return matches[0]


@pytest.fixture
def build() -> Builder:
    return Builder()

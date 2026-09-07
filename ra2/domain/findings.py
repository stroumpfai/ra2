# FROZEN — see CONTRACTS.md
"""The report vocabulary (sw-design.md §5).

mvp-spec.md §4.2/§4.3 require that **nothing is silently repaired and nothing is
silently dropped**. One type carries that from the parser, through the services,
to the UI and the CSV export.

Two rules that make this work:

1. `FindingCode` values are **stable identifiers**. Tests assert on the code,
   never on prose. Message text lives in one rendering table in `ra2/ui/`, so
   wording changes never break a test.
2. `Finding.detail` is structured data, never a pre-formatted sentence. The UI
   renders it; the CSV export writes it.

The import report is a `list[Finding]` serialised into
`corpus.import_report_json`; per-file findings are serialised into
`delivery_file.findings_json`.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from ra2.domain.ids import FileId

__all__ = ["DEFAULT_SEVERITY", "Finding", "FindingCode", "Severity"]


class Severity(StrEnum):
    """Whether a finding stops the import or is merely reported.

    `BLOCKING` findings fail the freeze: nothing is written and the errors go
    back to the analyst (mvp-spec.md §4.3, sw-design.md §6.3.1).
    `REPORTED` findings are collected into the import report and shown, but the
    corpus is still created.
    """

    BLOCKING = "BLOCKING"
    REPORTED = "REPORTED"


class FindingCode(StrEnum):
    """Every outcome the import pipeline can report.

    Grouped by where it is raised. Hazard fixture references (h01-h12) point at
    sw-design.md §11.4.
    """

    # --- file level: encoding and dialect (mvp-spec.md §4.2.1, §4.3) ----------
    #: The encoding detection result for a file. Always emitted, always
    #: REPORTED — §4.3 requires the detected encoding to appear in the report.
    #: detail: {"encoding": "utf-8" | "cp1252", "confidence": "..."}   (h01)
    ENCODING_DETECTED = "ENCODING_DETECTED"

    #: Bytes decode under neither UTF-8 nor Windows-1252. The file **fails**;
    #: `errors="replace"` is banned and U+FFFD is never written.
    #: detail: {"byte_offset": "...", "byte": "0x9d"}                  (h02)
    FILE_UNDECODABLE = "FILE_UNDECODABLE"

    #: The delimiter/quote character detection result for a file.
    #: detail: {"delimiter": "|", "quote_char": "\\""}
    DIALECT_DETECTED = "DIALECT_DETECTED"

    # --- file level: header and kind (sw-design.md §6.2.2, SD5) ---------------
    #: The header matches none of the three structured sets nor the text file,
    #: so `FileKind` is `UNKNOWN`. Blocking only if the file is selected.
    #: detail: {"header": "col1|col2|..."}                             (h12)
    UNKNOWN_HEADER = "UNKNOWN_HEADER"

    #: The header matches a known table but not exactly — missing, extra or
    #: duplicated columns (mvp-spec.md §4.3, blocking).
    #: detail: {"file_kind": "unfall", "missing": "...", "extra": "..."}
    HEADER_MISMATCH = "HEADER_MISMATCH"

    # --- row level (mvp-spec.md §4.2.3) --------------------------------------
    #: A row was reassembled by key-anchored recovery: the line did not begin
    #: with `^[0-9A-Fa-f]{32}<delim>`, so it was a continuation of the previous
    #: record. Only the two-column text file is ever repaired.
    #: detail: {"line_no": "...", "continuation_lines": "2"}      (h04, h05)
    ROW_RECOVERED = "ROW_RECOVERED"

    #: A wide structured row whose field count differs from the header's.
    #: **Detected, never repaired** — the row is rejected and reported with its
    #: key. detail: {"expected_fields": "67", "actual_fields": "68"}  (h03)
    ROW_REJECTED_FIELD_COUNT = "ROW_REJECTED_FIELD_COUNT"

    #: A row the RFC4180 reader could not parse at all (unterminated quote and
    #: the like). Rejected and reported with its key where one is recoverable.
    #: detail: {"error": "..."}
    ROW_REJECTED_PARSE_ERROR = "ROW_REJECTED_PARSE_ERROR"

    # --- cross-file validation, blocking (mvp-spec.md §4.3) ------------------
    #: The same `UnfallUid` / `ObjektUid` / `PersonUid` appears twice **across
    #: the whole delivery** — the collision that would attach one canton's
    #: narrative to another canton's record.
    #: detail: {"key_kind": "UnfallUid", "files": "a.txt, b.txt"}      (h07)
    DUP_KEY_CROSS_SET = "DUP_KEY_CROSS_SET"

    #: `objekt.UnfallUid` or `person.ObjektUid` with no parent row.
    #: detail: {"child_table": "objekt", "parent_key": "UnfallUid"}    (h06)
    ORPHAN_FK = "ORPHAN_FK"

    #: An `objekt`/`person` file whose parent keys reach no `unfall` file in the
    #: delivery, so it cannot be assigned to a structured set (SD6).
    #: detail: {"filename": "..."}
    SET_UNRESOLVED = "SET_UNRESOLVED"

    # --- cross-file consistency, non-blocking (mvp-spec.md §4.3) -------------
    #: `unfall.AnzObjFeld` != count of child `objekt` rows.
    #: detail: {"declared": "3", "actual": "2"}                        (h10)
    COUNT_MISMATCH_OBJ = "COUNT_MISMATCH_OBJ"

    #: `unfall.BeteiligtePersTotalFeld` != count of `person` rows via `objekt`.
    #: detail: {"declared": "5", "actual": "4"}
    COUNT_MISMATCH_PERS = "COUNT_MISMATCH_PERS"

    #: A text row whose `UNFALLUID` matches no `unfall` row.               (h11)
    TEXT_KEY_UNMATCHED = "TEXT_KEY_UNMATCHED"

    #: An `unfall` row with no narrative in the shared text file.
    UNFALL_WITHOUT_TEXT = "UNFALL_WITHOUT_TEXT"

    # --- corpus level (mvp-spec.md §4.4) -------------------------------------
    #: Zero Windows-1252-only characters in a corpus containing French: proof
    #: that the lossy cp1252 -> Latin-1 conversion happened upstream. One
    #: corpus-level number, never a per-record marker.
    #: detail: {"canary_count": "0", "languages": "de,fr,it"}          (h09)
    CP1252_CANARY_ZERO = "CP1252_CANARY_ZERO"


#: The severity each code carries unless the raising site says otherwise.
#:
#: `UNKNOWN_HEADER` is the one genuinely contextual code: an unknown file that
#: nobody selected is only reported; selecting it blocks the freeze
#: (sw-design.md §6.2.2). The raiser passes the severity explicitly there.
DEFAULT_SEVERITY: Final[dict[FindingCode, Severity]] = {
    FindingCode.ENCODING_DETECTED: Severity.REPORTED,
    FindingCode.FILE_UNDECODABLE: Severity.BLOCKING,
    FindingCode.DIALECT_DETECTED: Severity.REPORTED,
    FindingCode.UNKNOWN_HEADER: Severity.REPORTED,
    FindingCode.HEADER_MISMATCH: Severity.BLOCKING,
    FindingCode.ROW_RECOVERED: Severity.REPORTED,
    FindingCode.ROW_REJECTED_FIELD_COUNT: Severity.REPORTED,
    FindingCode.ROW_REJECTED_PARSE_ERROR: Severity.REPORTED,
    FindingCode.DUP_KEY_CROSS_SET: Severity.BLOCKING,
    FindingCode.ORPHAN_FK: Severity.BLOCKING,
    FindingCode.SET_UNRESOLVED: Severity.BLOCKING,
    FindingCode.COUNT_MISMATCH_OBJ: Severity.REPORTED,
    FindingCode.COUNT_MISMATCH_PERS: Severity.REPORTED,
    FindingCode.TEXT_KEY_UNMATCHED: Severity.REPORTED,
    FindingCode.UNFALL_WITHOUT_TEXT: Severity.REPORTED,
    FindingCode.CP1252_CANARY_ZERO: Severity.REPORTED,
}


@dataclass(frozen=True, slots=True)
class Finding:
    """One reported outcome of parsing or validating a delivery.

    A parser that drops or repairs a row without emitting one of these is a bug
    with a named regression test (sw-design.md §5).
    """

    code: FindingCode
    severity: Severity
    file_id: FileId | None = None
    #: `UnfallUid` / `ObjektUid` / `PersonUid` where one is known. §4.2 requires
    #: every recovered and rejected row to be reported *with its key*.
    key: str | None = None
    line_no: int | None = None
    #: Structured payload for the UI's rendering table and the CSV export.
    #: Never a pre-formatted sentence, so wording changes do not break tests.
    detail: dict[str, str] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        return self.severity is Severity.BLOCKING

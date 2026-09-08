# NEW — owned by A1 (feat/m1-parsing). Not frozen.
"""The per-file analyse pipeline, as one pure function (sw-design.md §6.2).

    bytes -> detect_encoding -> decode -> detect_dialect -> RFC4180 read
          -> key-anchored recovery -> header match -> per-row outcome -> Findings

sw-design.md §6.2 draws that as one pipeline but M0 froze only its parts, so
the composition lives here rather than in `DeliveryService`. That keeps it
where it can be tested without a database, a file system or a session — the
whole point of `tests/unit` — and leaves the service with the I/O and the
persistence, which is all a service should have.

It is a **pure function of bytes**: no path, no filename-derived anything. The
`filename` argument is carried through onto `FileAnalysis` for display and is
never read for meaning (§12.5) — `FileKind` comes from the header, the canton
comes from `unfall.KantonAusw`.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from ra2.domain.delivery import Dialect, Encoding, FileAnalysis, FileKind, RowOutcome
from ra2.domain.findings import DEFAULT_SEVERITY, Finding, FindingCode, Severity
from ra2.domain.ids import FileId
from ra2.domain.parsing.dialect import detect_dialect
from ra2.domain.parsing.encoding import Undecodable, decode_strict, detect_encoding
from ra2.domain.parsing.headers import (
    UNFALL_CANTON_COLUMN,
    canonical_field_count,
    classify_header,
    column_index,
)
from ra2.domain.parsing.reader import read_rows
from ra2.domain.parsing.recovery import recover_rows

__all__ = ["ParsedFile", "analyse_file"]

#: `str.strip()` on a delivered value would change it, and §4.4 stores values
#: verbatim. Only the *header* is trimmed, for matching (mvp-spec.md §4.1).
_KEEP_VALUES_VERBATIM: Final = True


@dataclass(frozen=True, slots=True)
class ParsedFile:
    """One analysed file: the reportable summary plus the rows it yielded.

    `FileAnalysis` is frozen at M0 and carries counts, not cells — it is what a
    `delivery_file` row is made of. Cross-file validation needs the cells too
    (it has to see every `ObjektUid` to find a duplicate), so the two travel
    together in this bundle rather than by widening the frozen type.

    `rows` holds the `OK` and `RECOVERED` rows only. Rejected rows are *not*
    silently dropped: each one is in `analysis.findings` with its key.
    """

    analysis: FileAnalysis
    rows: tuple[tuple[str, ...], ...] = ()
    #: Deselected files stay in the delivery list and out of the corpus.
    selected: bool = True

    @property
    def kind(self) -> FileKind:
        return self.analysis.kind

    @property
    def header(self) -> tuple[str, ...]:
        return self.analysis.header

    def column(self, name: str) -> int | None:
        """Index of `name` in this file's own header, matched case-insensitively."""
        return column_index(self.analysis.header, name)

    def values(self, name: str) -> Iterator[str]:
        """Every value of `name`, verbatim. Empty when the column is absent.

        A row shorter than the column's index yields `""` — "no value
        provided" (§8.6) — rather than raising: such a row was already rejected
        and reported, so nothing here is being hidden.
        """
        index = self.column(name)
        if index is None:
            return
        for row in self.rows:
            yield row[index] if index < len(row) else ""

    def keyed(self, name: str) -> Iterator[tuple[str, tuple[str, ...]]]:
        """`(value of `name`, whole row)` pairs, for the FK and count checks."""
        index = self.column(name)
        if index is None:
            return
        for row in self.rows:
            yield (row[index] if index < len(row) else ""), row


def _finding(
    code: FindingCode,
    *,
    file_id: FileId,
    detail: dict[str, str],
    severity: Severity | None = None,
    key: str | None = None,
    line_no: int | None = None,
) -> Finding:
    if key is not None:
        detail = {"key": key, **detail}
    return Finding(
        code=code,
        severity=severity or DEFAULT_SEVERITY[code],
        file_id=file_id,
        key=key,
        line_no=line_no,
        detail=detail,
    )


def _majority_canton(rows: tuple[tuple[str, ...], ...], index: int | None) -> str | None:
    """The canton this `unfall` file is for, read from the data (§4.1).

    A cantonal file is one canton's, so this is a majority vote only to survive
    a stray blank; a genuinely mixed file would be a delivery problem the
    duplicate and orphan checks surface separately.
    """
    if index is None:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        value = (row[index] if index < len(row) else "").strip()
        if value:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    return max(sorted(counts), key=lambda value: counts[value])


def analyse_file(
    *,
    file_id: FileId,
    filename: str,
    data: bytes,
    encoding_override: Encoding | None = None,
    dialect_override: Dialect | None = None,
    selected: bool = True,
) -> ParsedFile:
    """Analyse one file's bytes end to end. Re-runnable, and pure.

    `encoding_override` / `dialect_override` are the analyst's corrections from
    the import UI (mvp-spec.md §4.1): passing one re-runs the whole pipeline for
    this file and nothing else. What *detection* said is kept alongside on
    `FileAnalysis`, so the report can show both.
    """
    findings: list[Finding] = []

    # --- 1. encoding (mvp-spec.md §4.2.1) ---------------------------------
    detected = detect_encoding(data)
    encoding_detected = detected.encoding if not isinstance(detected, Undecodable) else None

    if encoding_override is not None:
        text = decode_strict(data, encoding_override)
        encoding_used: Encoding | None = encoding_override if text is not None else None
        failure: Undecodable | None = (
            detected if text is None and isinstance(detected, Undecodable) else None
        )
        if text is None and failure is None:
            failure = Undecodable(byte_offset=0, byte_value=data[0] if data else 0)
    elif isinstance(detected, Undecodable):
        text, encoding_used, failure = None, None, detected
    else:
        text, encoding_used, failure = detected.text, detected.encoding, None

    if text is None:
        # Undecodable bytes fail the file. No U+FFFD, no partial read (§12.4).
        offset = failure.byte_offset if failure else 0
        byte_hex = failure.byte_hex if failure else "0x00"
        findings.append(
            _finding(
                FindingCode.FILE_UNDECODABLE,
                file_id=file_id,
                detail={
                    "byte_offset": str(offset),
                    "byte": byte_hex,
                    "tried": "utf-8,cp1252",
                },
            )
        )
        return ParsedFile(
            analysis=FileAnalysis(
                file_id=file_id,
                filename=filename,
                kind=FileKind.UNKNOWN,
                encoding_detected=encoding_detected,
                dialect_detected=None,
                encoding=None,
                dialect=None,
                findings=tuple(findings),
            ),
            selected=selected,
        )

    assert encoding_used is not None
    findings.append(
        _finding(
            FindingCode.ENCODING_DETECTED,
            file_id=file_id,
            detail={
                "encoding": encoding_used.value,
                "detected": encoding_detected.value if encoding_detected else "none",
                "overridden": "true" if encoding_override is not None else "false",
            },
        )
    )

    # --- 2. dialect (mvp-spec.md §4.1) ------------------------------------
    dialect_detected = detect_dialect(text, FileKind.UNKNOWN)
    dialect = dialect_override or dialect_detected
    findings.append(
        _finding(
            FindingCode.DIALECT_DETECTED,
            file_id=file_id,
            detail={
                "delimiter": dialect.delimiter,
                "quote_char": dialect.quote_char,
                "detected_delimiter": dialect_detected.delimiter,
                "overridden": "true" if dialect_override is not None else "false",
            },
        )
    )

    # --- 3. read, then header (SD5: the header decides the kind) ----------
    raw = list(read_rows(text, dialect))
    header_row = raw[0] if raw else None
    header = header_row.fields if header_row is not None and header_row.error is None else ()

    match = classify_header(header)
    kind = match.kind
    if kind is FileKind.UNKNOWN:
        findings.append(
            _finding(
                FindingCode.UNKNOWN_HEADER,
                file_id=file_id,
                # Blocking only if the analyst selected it (sw-design.md §6.2.2).
                severity=Severity.BLOCKING if selected else Severity.REPORTED,
                detail={"header": dialect.delimiter.join(header), "columns": str(len(header))},
                line_no=1,
            )
        )
    elif not match.ok:
        findings.append(
            _finding(
                FindingCode.HEADER_MISMATCH,
                file_id=file_id,
                detail={
                    "file_kind": kind.value,
                    "missing": ",".join(match.missing),
                    "extra": ",".join(match.extra),
                    "duplicated": ",".join(match.duplicated),
                },
                line_no=1,
            )
        )

    expected = canonical_field_count(kind) or len(header)

    # --- 4. recovery and per-row outcome (mvp-spec.md §4.2.3) -------------
    ok_rows: list[tuple[str, ...]] = []
    counts = dict.fromkeys(RowOutcome, 0)
    for recovered in recover_rows(
        raw[1:],
        kind=kind,
        dialect=dialect,
        expected_field_count=expected,
        file_id=file_id,
    ):
        counts[recovered.outcome] += 1
        findings.extend(recovered.findings)
        if recovered.outcome is not RowOutcome.REJECTED:
            ok_rows.append(recovered.fields)

    rows = tuple(ok_rows)

    # --- 5. canton, from the data (mvp-spec.md §4.1, §12.5) ---------------
    canton = (
        _majority_canton(rows, column_index(header, UNFALL_CANTON_COLUMN))
        if kind is FileKind.UNFALL
        else None
    )

    analysis = FileAnalysis(
        file_id=file_id,
        filename=filename,
        kind=kind,
        encoding_detected=encoding_detected,
        dialect_detected=dialect_detected,
        encoding=encoding_used,
        dialect=dialect,
        header=header,
        header_ok=match.ok,
        row_count=sum(counts.values()),
        ok_count=counts[RowOutcome.OK],
        recovered_count=counts[RowOutcome.RECOVERED],
        rejected_count=counts[RowOutcome.REJECTED],
        canton=canton,
        set_key=None,  # cross-file; assigned by validate_delivery (SD6)
        findings=tuple(findings),
    )
    return ParsedFile(analysis=analysis, rows=rows, selected=selected)

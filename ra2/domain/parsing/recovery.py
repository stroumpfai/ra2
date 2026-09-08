# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""Key-anchored recovery (mvp-spec.md §4.2.3).

A line that does not begin with `^[0-9A-Fa-f]{32}<delim>` is a **continuation
of the preceding record**, not a new row.

- Two-column text file: repairs embedded newlines unambiguously -> `RECOVERED`.
- Wide structured tables: **detects** a stray delimiter; repair is not
  attempted. The row is `REJECTED` and reported with its key.

Why the asymmetry is not an inconsistency. In the two-column file the repair is
determined: the first field is the 32-hex key, therefore *everything after the
first delimiter is the narrative*, so the continuation can only belong to the
last field and rejoining is information-preserving. In a 67-column row there is
no such argument — a stray `|` could have arrived in any of 67 fields, and any
"repair" would be a guess written into a corpus that is immutable afterwards.
So the wide row is detected, rejected, and reported with its key, and a human
decides.

The anchor is applied to the **parsed first field**, not to the raw line. That
is the same rule and a slightly stronger one: `"<32 hex>"|...` is a legitimate
row whose quoted key a literal `^[0-9A-Fa-f]{32}<delim>` regex over the raw
line would miss.

Nothing here ever drops a row and nothing here ever repairs one silently: every
`RecoveredRow` whose outcome is not `OK` carries at least one `Finding`, and
that `Finding` carries the row's key whenever the row has one (§12.6).
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Final

from ra2.domain.delivery import UNFALL_UID_PATTERN, Dialect, FileKind, RowOutcome
from ra2.domain.findings import DEFAULT_SEVERITY, Finding, FindingCode
from ra2.domain.ids import FileId
from ra2.domain.parsing.reader import RawRow

__all__ = ["KEY_ANCHOR", "RecoveredRow", "is_key_anchor", "recover_rows"]

#: `UNFALL_UID_PATTERN` is anchored at the start; a key field is the whole 32
#: hex characters and nothing else, so the match is a full one.
KEY_ANCHOR: Final = re.compile(UNFALL_UID_PATTERN.removeprefix("^") + "$")

#: How the two-column text file rejoins a continuation. The delivered files use
#: CRLF, but the *logical* separator inside a repaired narrative is one `\n`:
#: the record's own line terminator is not part of its text.
_JOIN = "\n"


@dataclass(frozen=True, slots=True)
class RecoveredRow:
    """One logical row plus what had to happen to get it."""

    line_no: int
    fields: tuple[str, ...]
    outcome: RowOutcome
    key: str | None
    findings: tuple[Finding, ...] = ()


def is_key_anchor(fields: tuple[str, ...]) -> bool:
    """True when `fields` starts a record: field 0 is a 32-hex key."""
    return bool(fields) and KEY_ANCHOR.match(fields[0]) is not None


def _finding(
    code: FindingCode,
    *,
    file_id: FileId | None,
    key: str | None,
    line_no: int,
    detail: dict[str, str],
) -> Finding:
    """One finding, with the key mirrored into `detail`.

    §4.2.4 requires the offending key to be *in the report*, and the report is
    what the UI renders from `detail`. Carrying it in both places means a
    renderer that only walks `detail` still shows it.
    """
    if key is not None:
        detail = {"key": key, **detail}
    return Finding(
        code=code,
        severity=DEFAULT_SEVERITY[code],
        file_id=file_id,
        key=key,
        line_no=line_no,
        detail=detail,
    )


@dataclass(slots=True)
class _Pending:
    """A record being assembled, and everything the report needs about it."""

    line_no: int
    fields: list[str]
    line_span: int
    #: Continuation lines glued on by the key anchor (0 for a clean record).
    continuations: int = 0
    #: Set for a wide structured record that needed a continuation. Such a
    #: record is rejected even if the field count happens to come out right.
    unrepairable: bool = False
    continuation_lines: list[int] = field(default_factory=list)

    @property
    def key(self) -> str | None:
        return self.fields[0] if self.fields and KEY_ANCHOR.match(self.fields[0]) else None


def _collapse_text_fields(fields: list[str], delimiter: str) -> tuple[list[str], bool]:
    """Force a two-column record back to two columns.

    An unquoted `;` inside a narrative splits it into extra fields. In a file
    whose first column is a 32-hex key and whose second is free text, that is
    unambiguous: everything after the first delimiter is the narrative. Returns
    the collapsed fields and whether anything actually changed, because a
    change is reported (§12.6) rather than made quietly.
    """
    if len(fields) <= 2:
        return fields, False
    return [fields[0], delimiter.join(fields[1:])], True


def recover_rows(
    rows: Iterable[RawRow],
    *,
    kind: FileKind,
    dialect: Dialect,
    expected_field_count: int,
    file_id: FileId | None = None,
) -> Iterator[RecoveredRow]:
    """Reassemble continuations, reject what cannot be repaired.

    Every recovered and every rejected row carries a `Finding` with its key.
    Nothing is silently repaired and nothing is silently dropped.
    """
    repairable = kind is FileKind.TEXT
    # The anchor *is* the 32-hex key, so a file whose kind the header could not
    # identify has nothing to anchor on. Running the rule there would call every
    # row a continuation of the one before it and bury the real finding —
    # `UNKNOWN_HEADER` — under one spurious rejection per row.
    anchored = kind is not FileKind.UNKNOWN
    pending: _Pending | None = None

    def flush(current: _Pending) -> RecoveredRow:
        fields = list(current.fields)
        collapsed = False
        if repairable:
            fields, collapsed = _collapse_text_fields(fields, dialect.delimiter)
        key = current.key
        findings: list[Finding] = []

        if current.unrepairable:
            # A wide structured record broken across lines. Detected, reported
            # with its key, never repaired (mvp-spec.md §4.2.3).
            findings.append(
                _finding(
                    FindingCode.ROW_REJECTED_FIELD_COUNT,
                    file_id=file_id,
                    key=key,
                    line_no=current.line_no,
                    detail={
                        "expected_fields": str(expected_field_count),
                        "actual_fields": str(len(fields)),
                        "reason": "continuation_line",
                        "continuation_lines": ",".join(str(n) for n in current.continuation_lines),
                    },
                )
            )
            outcome = RowOutcome.REJECTED
        elif expected_field_count > 0 and len(fields) != expected_field_count:
            findings.append(
                _finding(
                    FindingCode.ROW_REJECTED_FIELD_COUNT,
                    file_id=file_id,
                    key=key,
                    line_no=current.line_no,
                    detail={
                        "expected_fields": str(expected_field_count),
                        "actual_fields": str(len(fields)),
                    },
                )
            )
            outcome = RowOutcome.REJECTED
        elif current.continuations or current.line_span > 1 or collapsed:
            if current.continuations:
                method = "key_anchor"
            elif current.line_span > 1:
                method = "quoted"
            else:
                method = "delimiter_in_narrative"
            findings.append(
                _finding(
                    FindingCode.ROW_RECOVERED,
                    file_id=file_id,
                    key=key,
                    line_no=current.line_no,
                    detail={
                        "line_no": str(current.line_no),
                        "continuation_lines": str(max(current.line_span - 1, 0)),
                        "method": method,
                    },
                )
            )
            outcome = RowOutcome.RECOVERED
        else:
            outcome = RowOutcome.OK

        return RecoveredRow(
            line_no=current.line_no,
            fields=tuple(fields),
            outcome=outcome,
            key=key,
            findings=tuple(findings),
        )

    for row in rows:
        if row.error is not None:
            if pending is not None:
                yield flush(pending)
                pending = None
            yield RecoveredRow(
                line_no=row.line_no,
                fields=(),
                outcome=RowOutcome.REJECTED,
                key=None,
                findings=(
                    _finding(
                        FindingCode.ROW_REJECTED_PARSE_ERROR,
                        file_id=file_id,
                        key=None,
                        line_no=row.line_no,
                        detail={"error": row.error, "lines": str(row.line_span)},
                    ),
                ),
            )
            continue

        if not anchored or is_key_anchor(row.fields):
            if pending is not None:
                yield flush(pending)
            pending = _Pending(
                line_no=row.line_no,
                fields=list(row.fields),
                line_span=row.line_span,
            )
            continue

        # Not an anchor: a continuation of the preceding record.
        if pending is None:
            # Nothing to continue. The file starts with a line that is neither
            # a record nor attachable — reported, never dropped.
            yield RecoveredRow(
                line_no=row.line_no,
                fields=row.fields,
                outcome=RowOutcome.REJECTED,
                key=None,
                findings=(
                    _finding(
                        FindingCode.ROW_REJECTED_PARSE_ERROR,
                        file_id=file_id,
                        key=None,
                        line_no=row.line_no,
                        detail={"error": "continuation line with no preceding record"},
                    ),
                ),
            )
            continue

        pending.continuations += 1
        pending.line_span += row.line_span
        pending.continuation_lines.append(row.line_no)
        if repairable:
            joined = dialect.delimiter.join(row.fields)
            pending.fields[-1] = pending.fields[-1] + _JOIN + joined
        else:
            pending.unrepairable = True

    if pending is not None:
        yield flush(pending)

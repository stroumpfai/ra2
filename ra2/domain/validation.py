# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""Delivery validation: blocking and non-blocking (mvp-spec.md §4.3).

Uniqueness is checked **across the whole delivery**, not per file: the single
shared text file is the join target for every cantonal set, so a `UnfallUid`
collision between two cantons would silently attach one canton's narrative to
another canton's record.

`validate_delivery` takes `ParsedFile`s rather than the frozen `FileAnalysis`.
`FileAnalysis` carries counts, because it is what a `delivery_file` row is made
of; the checks here need the cells — you cannot find a duplicate `ObjektUid`
without looking at every `ObjektUid`. `ParsedFile` is that pair, and it lives
in `ra2.domain.parsing.analysis` beside the function that produces it. The
frozen types are untouched.

Set membership (SD6) is decided here too, for the same reason: which cantonal
set an `objekt` file belongs to is a fact about *other files*, so it cannot be
known during per-file analysis. It is resolved by FK reachability, never from a
filename (§12.5).
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace

from ra2.domain.delivery import DeliveryAnalysis, FileAnalysis, FileKind
from ra2.domain.findings import DEFAULT_SEVERITY, Finding, FindingCode
from ra2.domain.ids import FileId
from ra2.domain.parsing.analysis import ParsedFile
from ra2.domain.parsing.headers import (
    KEY_COLUMNS,
    OBJEKT_KEY_COLUMN,
    TEXT_KEY_COLUMN,
    UNFALL_KEY_COLUMN,
    UNFALL_OBJ_COUNT_COLUMN,
    UNFALL_PERS_COUNT_COLUMN,
)

__all__ = ["blocking_findings", "validate_delivery"]


def _finding(
    code: FindingCode,
    *,
    file_id: FileId | None = None,
    key: str | None = None,
    detail: dict[str, str] | None = None,
) -> Finding:
    """One finding, with the key mirrored into `detail` (§4.2.4)."""
    payload = dict(detail or {})
    if key is not None:
        payload = {"key": key, **payload}
    return Finding(
        code=code,
        severity=DEFAULT_SEVERITY[code],
        file_id=file_id,
        key=key,
        detail=payload,
    )


def _of_kind(files: Iterable[ParsedFile], kind: FileKind) -> list[ParsedFile]:
    return [f for f in files if f.kind is kind]


def _duplicate_keys(files: Sequence[ParsedFile], kind: FileKind) -> list[Finding]:
    """Duplicates of `kind`'s primary key across the **whole delivery**.

    Per-file uniqueness is not enough and is not what §4.1 asks for: the
    dangerous case is precisely the one that is fine inside each file.
    """
    column = KEY_COLUMNS[kind]
    seen: dict[str, list[str]] = {}
    for parsed in _of_kind(files, kind):
        filename = parsed.analysis.filename
        for value in parsed.values(column):
            if value:
                seen.setdefault(value, []).append(filename)

    findings: list[Finding] = []
    for value, filenames in seen.items():
        if len(filenames) > 1:
            findings.append(
                _finding(
                    FindingCode.DUP_KEY_CROSS_SET,
                    key=value,
                    detail={
                        "key_kind": column,
                        "files": ", ".join(sorted(set(filenames))),
                        "occurrences": str(len(filenames)),
                    },
                )
            )
    return findings


def _orphans(
    files: Sequence[ParsedFile],
    *,
    child_kind: FileKind,
    fk_column: str,
    parent_kind: FileKind,
) -> list[Finding]:
    """Child rows whose foreign key reaches no parent row in the delivery."""
    parent_column = KEY_COLUMNS[parent_kind]
    parents = {
        value
        for parent in _of_kind(files, parent_kind)
        for value in parent.values(parent_column)
        if value
    }
    child_column = KEY_COLUMNS[child_kind]

    findings: list[Finding] = []
    for child in _of_kind(files, child_kind):
        child_index = child.column(child_column)
        fk_index = child.column(fk_column)
        if fk_index is None:
            continue
        for row in child.rows:
            parent_value = row[fk_index] if fk_index < len(row) else ""
            if not parent_value or parent_value in parents:
                continue
            own_key = (
                row[child_index] if child_index is not None and child_index < len(row) else None
            )
            findings.append(
                _finding(
                    FindingCode.ORPHAN_FK,
                    file_id=child.analysis.file_id,
                    key=own_key,
                    detail={
                        "child_table": child_kind.value,
                        "parent_key": fk_column,
                        "parent_value": parent_value,
                        "orphan_key": parent_value,
                    },
                )
            )
    return findings


def _resolve_sets(files: Sequence[ParsedFile]) -> tuple[dict[FileId, str], list[Finding]]:
    """Group the three structured files of one canton by FK reachability (SD6).

    The `unfall` file names the set — from its own `KantonAusw`, which came
    from the data. `objekt` joins the set whose `unfall` file holds its parent
    keys; `person` joins the set of the `objekt` file holding *its* parents.
    Nothing consults a filename.
    """
    set_key: dict[FileId, str] = {}
    findings: list[Finding] = []

    unfall_files = _of_kind(files, FileKind.UNFALL)
    for parsed in unfall_files:
        analysis = parsed.analysis
        set_key[analysis.file_id] = analysis.canton or f"set:{analysis.file_id}"

    unfall_keys = {
        parsed.analysis.file_id: set(parsed.values(UNFALL_KEY_COLUMN)) for parsed in unfall_files
    }

    objekt_files = _of_kind(files, FileKind.OBJEKT)
    objekt_keys: dict[FileId, set[str]] = {}
    for parsed in objekt_files:
        own = set(parsed.values(OBJEKT_KEY_COLUMN))
        objekt_keys[parsed.analysis.file_id] = own
        parents = {v for v in parsed.values(UNFALL_KEY_COLUMN) if v}
        best = _best_overlap(parents, unfall_keys)
        if best is None:
            findings.append(
                _finding(
                    FindingCode.SET_UNRESOLVED,
                    file_id=parsed.analysis.file_id,
                    detail={
                        "filename": parsed.analysis.filename,
                        "file_kind": FileKind.OBJEKT.value,
                    },
                )
            )
            continue
        set_key[parsed.analysis.file_id] = set_key[best]

    for parsed in _of_kind(files, FileKind.PERSON):
        parents = {v for v in parsed.values(OBJEKT_KEY_COLUMN) if v}
        best = _best_overlap(parents, objekt_keys)
        if best is None or best not in set_key:
            findings.append(
                _finding(
                    FindingCode.SET_UNRESOLVED,
                    file_id=parsed.analysis.file_id,
                    detail={
                        "filename": parsed.analysis.filename,
                        "file_kind": FileKind.PERSON.value,
                    },
                )
            )
            continue
        set_key[parsed.analysis.file_id] = set_key[best]

    return set_key, findings


def _best_overlap(needles: set[str], haystacks: dict[FileId, set[str]]) -> FileId | None:
    """The file sharing the most keys with `needles`, or `None` for zero."""
    best: FileId | None = None
    best_size = 0
    for file_id, keys in haystacks.items():
        size = len(needles & keys)
        if size > best_size:
            best, best_size = file_id, size
    return best


def _count_mismatches(files: Sequence[ParsedFile]) -> list[Finding]:
    """`AnzObjFeld` and `BeteiligtePersTotalFeld` against the real child counts.

    Reported, never blocking: a declared count that disagrees with the delivered
    rows is a fact about the delivery the analyst needs, not a reason to refuse
    an import (mvp-spec.md §4.3).
    """
    objekt_per_unfall: dict[str, int] = {}
    objekt_to_unfall: dict[str, str] = {}
    for parsed in _of_kind(files, FileKind.OBJEKT):
        for row_key, row in parsed.keyed(UNFALL_KEY_COLUMN):
            if not row_key:
                continue
            objekt_per_unfall[row_key] = objekt_per_unfall.get(row_key, 0) + 1
            index = parsed.column(OBJEKT_KEY_COLUMN)
            own = row[index] if index is not None and index < len(row) else ""
            if own:
                objekt_to_unfall[own] = row_key

    person_per_unfall: dict[str, int] = {}
    for parsed in _of_kind(files, FileKind.PERSON):
        for objekt_key in parsed.values(OBJEKT_KEY_COLUMN):
            unfall_key = objekt_to_unfall.get(objekt_key)
            if unfall_key:
                person_per_unfall[unfall_key] = person_per_unfall.get(unfall_key, 0) + 1

    findings: list[Finding] = []
    for parsed in _of_kind(files, FileKind.UNFALL):
        obj_index = parsed.column(UNFALL_OBJ_COUNT_COLUMN)
        pers_index = parsed.column(UNFALL_PERS_COUNT_COLUMN)
        for key, row in parsed.keyed(UNFALL_KEY_COLUMN):
            if not key:
                continue
            findings.extend(
                _mismatch(
                    code=FindingCode.COUNT_MISMATCH_OBJ,
                    file_id=parsed.analysis.file_id,
                    key=key,
                    declared=_cell(row, obj_index),
                    actual=objekt_per_unfall.get(key, 0),
                    column=UNFALL_OBJ_COUNT_COLUMN,
                )
            )
            findings.extend(
                _mismatch(
                    code=FindingCode.COUNT_MISMATCH_PERS,
                    file_id=parsed.analysis.file_id,
                    key=key,
                    declared=_cell(row, pers_index),
                    actual=person_per_unfall.get(key, 0),
                    column=UNFALL_PERS_COUNT_COLUMN,
                )
            )
    return findings


def _cell(row: tuple[str, ...], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index]


def _mismatch(
    *,
    code: FindingCode,
    file_id: FileId,
    key: str,
    declared: str,
    actual: int,
    column: str,
) -> list[Finding]:
    """A declared-vs-actual count, when the declared value is a number at all.

    A non-numeric or empty declaration is not a mismatch — it is a census
    concern (an unparseable value in an integer column), and duplicating it
    here would report the same cell twice under a code that does not mean it.
    """
    text = declared.strip()
    if not text.lstrip("-").isdigit():
        return []
    if int(text) == actual:
        return []
    return [
        _finding(
            code,
            file_id=file_id,
            key=key,
            detail={"declared": text, "actual": str(actual), "column": column},
        )
    ]


def _text_join(files: Sequence[ParsedFile]) -> list[Finding]:
    """Text rows with no `unfall` row, and `unfall` rows with no narrative."""
    text_files = _of_kind(files, FileKind.TEXT)
    unfall_files = _of_kind(files, FileKind.UNFALL)
    if not text_files or not unfall_files:
        # With no text file in the selection there is no join to check, and
        # every `unfall` row would otherwise be reported as textless.
        return []

    unfall_keys = {v for parsed in unfall_files for v in parsed.values(UNFALL_KEY_COLUMN) if v}
    text_keys: set[str] = set()

    findings: list[Finding] = []
    for parsed in text_files:
        for value in parsed.values(TEXT_KEY_COLUMN):
            if not value:
                continue
            text_keys.add(value)
            if value not in unfall_keys:
                findings.append(
                    _finding(
                        FindingCode.TEXT_KEY_UNMATCHED,
                        file_id=parsed.analysis.file_id,
                        key=value,
                        detail={"column": TEXT_KEY_COLUMN},
                    )
                )

    for parsed in unfall_files:
        for value in parsed.values(UNFALL_KEY_COLUMN):
            if value and value not in text_keys:
                findings.append(
                    _finding(
                        FindingCode.UNFALL_WITHOUT_TEXT,
                        file_id=parsed.analysis.file_id,
                        key=value,
                        detail={"column": UNFALL_KEY_COLUMN},
                    )
                )
    return findings


def validate_delivery(files: Sequence[ParsedFile]) -> DeliveryAnalysis:
    """Cross-file validation over the **selected** files.

    Blocking: duplicate `UnfallUid`/`ObjektUid`/`PersonUid` across the whole
    delivery, orphan FKs, header mismatch.

    Reported: `AnzObjFeld` and `BeteiligtePersTotalFeld` count mismatches, text
    rows with no `unfall` row, `unfall` rows with no text, detected encodings.

    Deselected files stay in `DeliveryAnalysis.files` — the import view still
    lists them — but take no part in any cross-file check, so deselecting the
    file that carries a duplicate really does unblock the freeze.
    """
    selected = [f for f in files if f.selected]

    set_key, cross = _resolve_sets(selected)

    for kind in (FileKind.UNFALL, FileKind.OBJEKT, FileKind.PERSON):
        cross.extend(_duplicate_keys(selected, kind))

    cross.extend(
        _orphans(
            selected,
            child_kind=FileKind.OBJEKT,
            fk_column=UNFALL_KEY_COLUMN,
            parent_kind=FileKind.UNFALL,
        )
    )
    cross.extend(
        _orphans(
            selected,
            child_kind=FileKind.PERSON,
            fk_column=OBJEKT_KEY_COLUMN,
            parent_kind=FileKind.OBJEKT,
        )
    )
    cross.extend(_count_mismatches(selected))
    cross.extend(_text_join(selected))

    analyses: list[FileAnalysis] = []
    for parsed in files:
        analysis = parsed.analysis
        resolved = set_key.get(analysis.file_id)
        analyses.append(replace(analysis, set_key=resolved) if resolved else analysis)

    return DeliveryAnalysis(files=tuple(analyses), findings=tuple(cross))


def blocking_findings(analysis: DeliveryAnalysis) -> tuple[Finding, ...]:
    """The subset that must stop the freeze with nothing written."""
    return analysis.blocking

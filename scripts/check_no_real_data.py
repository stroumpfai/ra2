#!/usr/bin/env python
"""Refuse to commit a real delivery file, whatever it is called (§12.11).

The VUM delivery is classified sensitive: the structured records are not
anonymised and the joined pair is personally identifying. It must stay on the
host. `.gitignore` is defence one; this is defence two, because a `git add -f`
bypasses the first.

**Two checks, and the second is the one that matters.**

1. *Name-shaped* — the `.gitignore` delivery patterns, repeated here.
2. *Content-shaped* — what the file **is**, read from its first lines.

The name check alone was a hole worth writing down. It was built from
`.gitignore`, which lists `vum_*.txt` and `AstranaExport*`; the Astrana
delivery's real filenames are `Unfall.csv`, `Objekt.csv` and `Mitfahrende.csv`
(mvp-spec.md §4.1) and match no pattern outside `data/`. A guard that a
correctly-named file walks straight past is a guard against typos, not against
the scenario — which is a delivery file copied into the tree while debugging an
import on real data, the single most natural thing to do when a parser fails.

**The content check asks the application's own question.** It does not keep a
second copy of the column vocabulary — that duplication is exactly what made
the name check wrong in two places at once. It calls
`ra2.domain.parsing.headers.classify_header`, the same function the importer
uses to decide what a file is. That module is pure `ra2.domain`: stdlib plus
this repo, no third-party import, so this script still runs in a checkout with
no virtualenv.

**A delivery-shaped file is refused unless both hold:**

- **it is under `tests/fixtures/deliveries/`** — the one place delivery-shaped
  files are committed on purpose, and nowhere anybody drops a file they are
  debugging;
- **its keys were invented, not delivered.** `generate_hazards.uid()` builds a
  key as a short hex tag plus a zero-padded decimal counter, so a synthetic key
  holds three to five distinct characters out of thirty-two
  (`aa000000000000000000000000000001`). A real 32-hex key holds about
  thirteen. Nothing lands between the two, so `MAX_INVENTED_DISTINCT_CHARS`
  separates them exactly rather than approximately.

The second condition is the one no other control covers. CLAUDE.md requires the
hazards to be *synthesised* byte-exactly and forbids real data reaching a test;
until now that was prose. Sampling five real rows into a fixture is the
tempting, plausible mistake, and it passes every other check in this
repository.

**A known limit, stated rather than hidden.** The headerless detector keys on
the *first* field, so a RADIS tail is caught and an Astrana tail — whose key
sits at column 2, after `Jahr` and `Datum` (§4.1) — is not. Both are caught the
moment the header line is present, which is how a delivery arrives.

Run over the whole tree with `--all` (that is what CI does), or over named
paths (that is what the pre-commit hook does).
"""

from __future__ import annotations

import csv
import fnmatch
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ra2.domain.delivery import FileKind  # noqa: E402
from ra2.domain.parsing.headers import (  # noqa: E402
    ColumnSet,
    classify_header,
    column_index,
)

#: Kept in step with the "REAL DATA" and "defence in depth" blocks of
#: .gitignore. A pattern with a `/` matches the path; one without matches the
#: file name anywhere in the tree. This is defence one and it is **not** the
#: one relied on — see the module docstring.
FORBIDDEN_PATTERNS = (
    "data/*",
    "vum_*.txt",
    "AstranaExport*",
    "*.xlsx",
    "*.xls",
    "*.zip",
)

#: The one place a delivery-shaped file may be committed. The hazards under it
#: are synthesised byte-exactly and are the whole reason the parsing suite can
#: be trusted (mvp-spec.md §15, CLAUDE.md).
FIXTURE_ROOT = "tests/fixtures/deliveries/"

#: Every delimiter §4.1 names: RADIS `|`, the text file `;`, Astrana `,`.
DELIMITERS = ("|", ";", ",")

#: Enough to classify a header and sample a few keys. A real delivery is
#: hundreds of megabytes and this never reads more than this much of one.
MAX_READ_BYTES = 64 * 1024

#: How many data rows are sampled for keys. One real key is one too many, so
#: this only has to beat a file whose first rows happen to be blank.
SAMPLED_ROWS = 20

#: A key with no more distinct characters than this was counted out by
#: `generate_hazards.uid()`. Synthetic keys reach five; a real 32-hex key sits
#: near thirteen and has never been observed below ten. The gap is the point.
MAX_INVENTED_DISTINCT_CHARS = 8

_HEX = frozenset("0123456789abcdef")


def is_forbidden(path: str) -> bool:
    """Defence one: does the name match a `.gitignore` delivery pattern?"""
    posix = Path(path).as_posix()
    name = Path(path).name
    for pattern in FORBIDDEN_PATTERNS:
        target = posix if "/" in pattern else name
        if fnmatch.fnmatch(target, pattern):
            return True
    return False


def _read_head(path: Path) -> list[str] | None:
    """The first lines of `path`, or `None` when it is not text at all.

    Decoded as latin-1 because it is total — every byte maps, nothing raises
    and nothing is replaced, which matters for a fixture like `h02_undecodable`
    that is deliberately not valid UTF-8. This is a shape inspection, never a
    read of values: N4's explicit-encoding rule is about the application's own
    parsing, and no string produced here is stored, compared against data or
    shown.
    """
    try:
        raw = path.read_bytes()[:MAX_READ_BYTES]
    except OSError:
        return None
    if b"\x00" in raw:  # binary: a font, an image, a compiled artefact
        return None
    return raw.decode("latin-1").splitlines()


def _fields(line: str, delimiter: str) -> list[str]:
    """One delimited line as fields, honouring RFC4180 quoting (Astrana)."""
    try:
        return next(csv.reader([line], delimiter=delimiter, quotechar='"'))
    except csv.Error, StopIteration:
        return []


def _is_key(value: str) -> bool:
    """A 32-hex-character delivery key, however it was quoted or dashed."""
    cleaned = value.strip().strip('"').replace("-", "").casefold()
    return len(cleaned) == 32 and set(cleaned) <= _HEX


def _was_invented(key: str) -> bool:
    """Could `generate_hazards.uid()` have produced this key?"""
    cleaned = key.strip().strip('"').replace("-", "").casefold()
    return len(set(cleaned)) <= MAX_INVENTED_DISTINCT_CHARS


def _classify(lines: list[str]) -> tuple[str, ColumnSet | None] | None:
    """`(delimiter, column_set)` when these lines are a delivery file.

    Two ways to be one, in order of confidence:

    - the **header** names a known column set, which is the application's own
      test for what a file is, delimiter and all;
    - there is no header the importer would recognise, but the first field of
      the first row is a 32-hex key followed by a delivery delimiter — a tail
      of a delivery, pasted or split out of one.
    """
    body = [line for line in lines if line.strip()]
    if not body:
        return None

    for delimiter in DELIMITERS:
        header = _fields(body[0], delimiter)
        if len(header) < 2:
            continue
        match = classify_header(header)
        if match.kind is not FileKind.UNKNOWN:
            return (delimiter, match.column_set)

    for delimiter in DELIMITERS:
        fields = _fields(body[0], delimiter)
        if len(fields) >= 2 and _is_key(fields[0]):
            return (delimiter, None)
    return None


def _sampled_keys(lines: list[str], delimiter: str, column_set: ColumnSet | None) -> list[str]:
    """The keys of the first rows, from the key column the header named.

    `column_set` is `None` for the headerless case, where the key is field 0 by
    definition of how that file was detected. Otherwise the key column is
    resolved by name, never by position — Astrana's sits at column 2 (§4.1).
    """
    body = [line for line in lines if line.strip()]
    if column_set is None:
        rows, index = body[:SAMPLED_ROWS], 0
    else:
        header = _fields(body[0], delimiter)
        resolved = column_index(header, column_set.key_column)
        if resolved is None:
            return []
        rows, index = body[1 : 1 + SAMPLED_ROWS], resolved
    keys = []
    for row in rows:
        fields = _fields(row, delimiter)
        if index < len(fields) and _is_key(fields[index]):
            keys.append(fields[index])
    return keys


def inspect(path: str) -> str | None:
    """Why `path` may not be committed, or `None` when it may be."""
    if is_forbidden(path):
        return "matches a real-data name pattern from .gitignore"

    lines = _read_head(REPO_ROOT / path)
    if lines is None:
        return None
    shape = _classify(lines)
    if shape is None:
        return None
    delimiter, column_set = shape

    kind = "a delivery file" if column_set else "the tail of a delivery file"
    if not Path(path).as_posix().startswith(FIXTURE_ROOT):
        return f"looks like {kind}, and only {FIXTURE_ROOT} may hold one"

    delivered = [
        key for key in _sampled_keys(lines, delimiter, column_set) if not _was_invented(key)
    ]
    if delivered:
        return (
            f"looks like {kind} with delivered keys, not invented ones "
            f"(e.g. {delivered[0][:8]}…) — fixtures are synthesised, never sampled"
        )
    return None


def _tracked_files() -> list[str]:
    """Every file git knows about. Used by `--all` in CI, where the question is
    not "what changed" but "is any of this in here at all"."""
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return [line for line in completed.stdout.splitlines() if line]


def main(argv: list[str]) -> int:
    paths = _tracked_files() if "--all" in argv else [a for a in argv if not a.startswith("-")]
    offenders = sorted({(path, reason) for path in paths if (reason := inspect(path)) is not None})
    if not offenders:
        return 0
    print("Refusing to commit files that look like real delivery data:", file=sys.stderr)
    for path, reason in offenders:
        print(f"  {path}\n      {reason}", file=sys.stderr)
    print(
        "\nReal delivery files must never leave the host (sw-design.md §12.11).\n"
        "Synthesise the hazard instead: tests/fixtures/deliveries/generate_hazards.py",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

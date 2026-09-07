#!/usr/bin/env python
"""Refuse any file matching the real-data patterns in `.gitignore` (§12.11).

The VUM delivery is classified sensitive: the structured records are not
anonymised and the joined pair is personally identifying. It must stay on the
host. `.gitignore` is defence one; this hook is defence two, because a
`git add -f` bypasses the first.

Stdlib only, no third-party import, so it runs even in a bare checkout.
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

#: Kept in step with the "REAL DATA" and "defence in depth" blocks of
#: .gitignore. A pattern with a `/` matches the path; one without matches the
#: file name anywhere in the tree.
FORBIDDEN_PATTERNS = (
    "data/*",
    "vum_*.txt",
    "AstranaExport*",
    "*.xlsx",
    "*.xls",
    "*.zip",
)


def is_forbidden(path: str) -> bool:
    posix = Path(path).as_posix()
    name = Path(path).name
    for pattern in FORBIDDEN_PATTERNS:
        target = posix if "/" in pattern else name
        if fnmatch.fnmatch(target, pattern):
            return True
    return False


def main(argv: list[str]) -> int:
    offenders = sorted({path for path in argv if is_forbidden(path)})
    if not offenders:
        return 0
    print("Refusing to commit files matching the real-data patterns:", file=sys.stderr)
    for path in offenders:
        print(f"  {path}", file=sys.stderr)
    print(
        "\nReal delivery files must never leave the host (sw-design.md §12.11).\n"
        "Synthesise the hazard instead: tests/fixtures/deliveries/generate_hazards.py",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

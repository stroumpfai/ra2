"""No hazard fixture's line endings are left to the machine that cloned it.

`core.autocrlf` is configured per *machine*, not per repository, so a path
with no `.gitattributes` entry checks out with whatever bytes the developer's
own git config happens to produce. Every fixture under
`tests/fixtures/*/hazards/` has a test that compares its bytes against a
generator's output, which makes that a gate whose result is a property of the
runner rather than of the code — and a gate that is red on one platform and
green on another is one nobody reads (`sw-design.md` `SD33`).

This asks **git itself**, through `git check-attr`, rather than parsing
`.gitattributes` and reimplementing its pattern matching. It passes
identically on Linux and Windows: the question is what the repository
*declares*, not what this filesystem does, so a missing entry fails on the
platform where the fixture is being added rather than six months later in a
CI leg on the other one.

It deliberately does not say *which* of the two a family must choose. The
delivery hazards are CRLF by construction and carry a doubled CRLF that no
text conversion survives; the codelist and prompt hazards are LF. That is each
generator's business. What is not negotiable is that somebody decided.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every hazard family follows `tests/fixtures/<family>/hazards/`, so a family
#: added later is covered without this list being edited.
HAZARD_GLOB = "tests/fixtures/*/hazards/**/*"

#: Committed generator output that lives outside a `hazards/` directory and is
#: still compared byte-for-byte (`test_golden_import_report.py`).
EXTRA_BYTE_ASSERTED = ("tests/fixtures/golden/import_report_hazards.json",)


def _check_attr(relative: str) -> dict[str, str]:
    """`{attribute: value}` as git resolves it for `relative`.

    `git check-attr` prints one `<path>: <attribute>: <value>` line per
    attribute asked for; `unspecified` is the answer for a path no rule
    matches.
    """
    completed = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", relative],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    resolved = {}
    for line in completed.stdout.splitlines():
        if not line:
            continue
        _, attribute, value = line.rsplit(": ", 2)
        resolved[attribute] = value
    return resolved


def _byte_asserted_files() -> list[str]:
    found = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted(REPO_ROOT.glob(HAZARD_GLOB))
        if path.is_file() and path.suffix != ".py"
    ]
    found += [name for name in EXTRA_BYTE_ASSERTED if (REPO_ROOT / name).is_file()]
    return sorted(found)


def test_the_glob_finds_the_fixtures_it_is_written_for():
    """A sanity check on the checker below: it is not vacuously green."""
    found = _byte_asserted_files()
    assert len(found) > 20, found
    for family in ("deliveries", "codelists", "prompts"):
        assert any(f"/{family}/" in name for name in found), family


def test_no_byte_asserted_fixture_is_left_to_core_autocrlf():
    unpinned = [
        relative
        for relative in _byte_asserted_files()
        if _check_attr(relative) == {"text": "unspecified", "eol": "unspecified"}
    ]
    assert unpinned == [], (
        "these fixtures' bytes are asserted by a test but their line endings "
        "depend on the cloning machine's core.autocrlf — give each one a "
        "`.gitattributes` entry (`-text` to preserve bytes exactly, `eol=lf` "
        f"to pin LF): {unpinned}"
    )


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("tests/fixtures/deliveries/hazards/h13_astrana_blank_row/Unfall.csv", {"text": "unset"}),
        ("tests/fixtures/codelists/hazards/c01_minimal_valid/codelist.json", {"eol": "lf"}),
        ("tests/fixtures/prompts/hazards/p01_valid_all_slots/template.txt", {"eol": "lf"}),
        ("tests/fixtures/golden/import_report_hazards.json", {"eol": "lf"}),
    ],
)
def test_each_family_resolves_the_attribute_its_generator_needs(relative, expected):
    """One representative per family, pinned to the *specific* answer.

    `h13` is the one that makes `-text` non-negotiable rather than a
    preference: it carries Astrana's doubled CRLF (`\\r\\r\\n`), and git's
    clean filter rewrites `\\r\\n` as `\\n`, which turns that sequence into an
    ordinary `\\r\\n` and deletes the hazard. `eol=crlf` round-trips through
    LF and would do exactly that.
    """
    resolved = _check_attr(relative)
    for attribute, value in expected.items():
        assert resolved[attribute] == value, (relative, resolved)

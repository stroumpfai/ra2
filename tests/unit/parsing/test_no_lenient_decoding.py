"""`errors="replace"` appears nowhere in `ra2/` — the gate, as a test.

sw-design.md §12.4 and mvp-spec.md §4.2.1 forbid it, and plan-m0-m5.md §5 (A1)
names the check: `grep -rn 'errors="replace"' ra2/` must be empty.

This implements that check twice over, and one deviation is deliberate.

**Why not `grep`.** CI runs layers 1-3 on `windows-latest` as well as
`ubuntu-latest` (N3, sw-design.md §11.7) and Windows has no `grep`. A gate that
silently does not run on half the matrix is not a gate.

**Why the scan is over code rather than over raw lines.** A literal `grep` is
not actually satisfiable, and should not be: the frozen `ra2/domain/delivery.py`
*documents the ban in its docstring*, and so does every module here that had to
explain why it takes no `errors=` argument. Deleting the sentence that states
the rule in order to pass the test that enforces the rule would be exactly
backwards. So the forbidden pattern is looked for in **code**, with comments and
string literals tokenized away — which is stricter, because it also catches
`errors = "replace"` and `errors='ignore'`, and honest, because
`test_every_raw_hit_is_prose_not_code` pins that every raw hit really is prose.

Why it matters, restated so nobody "fixes" a decode error with it later: a
`U+FFFD` written into a narrative is indistinguishable, downstream, from a
character the analyst's source system deleted in its lossy cp1252 conversion
(§4.4). The canary would be counting our own damage.
"""

import io
import re
import tokenize
from collections.abc import Callable
from pathlib import Path

import pytest

RA2 = Path(__file__).resolve().parents[3] / "ra2"

#: What `grep -rn 'errors="replace"' ra2/` looks for, and its single-quoted twin.
FORBIDDEN_LITERALS = ('errors="replace"', "errors='replace'")

#: Anything lenient, not only `replace`. `ignore` drops the byte and
#: `surrogateescape` smuggles it through as an unpaired surrogate that explodes
#: on re-encode — the same mistake wearing a different word.
LENIENT_ERRORS = re.compile(r"""errors\s*=\s*(["'])(?!strict\b)[a-z]+\1""")

#: `errors=` with a non-literal argument: the keyword must not appear at all.
ANY_ERRORS_KEYWORD = re.compile(r"\berrors\s*=")


def _sources() -> list[Path]:
    files = sorted(p for p in RA2.rglob("*.py") if p.is_file())
    assert files, f"no sources under {RA2}"
    return files


#: Token types that mean "the next token starts a logical line", so a string
#: token following one of these is a docstring or a bare string expression —
#: prose — rather than an argument.
_LINE_STARTERS = frozenset(
    {tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING}
)


def _without_prose(path: Path) -> str:
    """`path` with comments and docstrings blanked out, arguments kept.

    Blanking *every* string literal would defeat the purpose: the thing being
    looked for, `errors="replace"`, is itself half string literal. So only prose
    goes — comments, and strings that stand alone as a statement — and
    `decode("utf-8", errors="replace")` survives intact to be caught.

    Line structure is preserved so a failure can name a line number.
    """
    text = path.read_text(encoding="utf-8")
    blanked = [list(line) for line in text.splitlines()]
    previous = tokenize.ENCODING
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        prose = token.type == tokenize.COMMENT or (
            token.type == tokenize.STRING and previous in _LINE_STARTERS
        )
        if token.type not in (tokenize.NL, tokenize.COMMENT):
            previous = token.type
        elif token.type == tokenize.NL:
            previous = tokenize.NL
        if not prose:
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            line = blanked[row - 1]
            first = start_col if row == start_row else 0
            last = end_col if row == end_row else len(line)
            for column in range(first, min(last, len(line))):
                line[column] = " "
    return "\n".join("".join(line) for line in blanked)


#: Kept under the old name so the tests below read as "scan the code".
_code_only = _without_prose


def _hits(predicate: Callable[[str], object]) -> list[str]:
    found: list[str] = []
    for path in _sources():
        for number, line in enumerate(_code_only(path).splitlines(), start=1):
            if predicate(line):
                found.append(f"{path.relative_to(RA2.parent)}:{number}")
    return found


def _raw_hits(predicate: Callable[[str], object]) -> list[tuple[Path, int, str]]:
    found: list[tuple[Path, int, str]] = []
    for path in _sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if predicate(line):
                found.append((path, number, line))
    return found


@pytest.mark.parametrize("literal", FORBIDDEN_LITERALS)
def test_errors_replace_appears_nowhere_in_ra2(literal):
    assert _hits(lambda line: literal in line) == []


def test_no_decode_or_open_call_asks_for_any_lenient_error_handler():
    """The stricter form of the same rule."""
    assert _hits(LENIENT_ERRORS.search) == []


def test_the_errors_keyword_is_not_passed_at_all():
    """Strictest, and the state the codebase is actually in: `errors=` is never
    written, so there is no expression whose value a reader has to go and check."""
    assert _hits(ANY_ERRORS_KEYWORD.search) == []


def test_the_replacement_character_is_never_written_into_the_source():
    """A literal `U+FFFD` would be a substitution made by hand."""
    assert _hits(lambda line: "�" in line) == []


def test_every_raw_hit_is_prose_not_code():
    """The literal `grep` the plan names is not empty, and must not be: the ban
    is *documented* in `ra2/domain/delivery.py` and in the parsing modules. Pin
    that every raw hit is a comment or a docstring, so this test — not luck —
    is what makes the code-only scan trustworthy."""
    raw = _raw_hits(lambda line: any(lit in line for lit in FORBIDDEN_LITERALS))
    assert raw, "expected the ban to still be documented somewhere in ra2/"
    for path, number, line in raw:
        code = _code_only(path).splitlines()[number - 1]
        assert code.strip() == "", (path.name, number, line)


def test_the_scan_would_actually_catch_a_violation(tmp_path):
    """A gate nobody has seen fail is a gate nobody knows works."""
    offender = tmp_path / "offender.py"
    offender.write_text(
        '"""A docstring mentioning errors="replace" must not trip this."""\n'
        "# nor may this comment: errors='ignore'\n"
        'text = data.decode("utf-8", errors="replace")\n',
        encoding="utf-8",
    )
    code = _code_only(offender).splitlines()
    assert code[0].strip() == ""
    assert code[1].strip() == ""
    assert LENIENT_ERRORS.search(code[2])
    assert FORBIDDEN_LITERALS[0] in code[2]

    assert LENIENT_ERRORS.search('open(p, encoding="utf-8", errors="ignore")')
    assert LENIENT_ERRORS.search("decode('cp1252', errors='surrogateescape')")
    assert not LENIENT_ERRORS.search('decode("utf-8", errors="strict")')


def test_every_open_call_in_ra2_names_its_encoding():
    """Do-NOT rule 4's other half. `ruff` has `PLW1514` on for this, so the test
    is a belt to that braces — and it fails in a way that says which line."""
    opens = _hits(lambda line: re.search(r"\.open\(|(?<![\w.])open\(", line))
    for hit in opens:
        path_name, number = hit.rsplit(":", 1)
        path = RA2.parent / path_name
        line = _code_only(path).splitlines()[int(number) - 1]
        assert "encoding=" in line or '"rb"' in line or "'rb'" in line, hit

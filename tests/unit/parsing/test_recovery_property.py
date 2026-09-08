"""The property sw-design.md §11.1 names.

    "a round trip of 'split a record across N lines, recover it' must
     reconstruct the original for all N"

Splitting is the hazard the delivery actually contains — an embedded newline in
a narrative, quoted or not — and recovery is the claim that the key anchor
undoes it. Example-based tests pin the two or three splits somebody thought of;
this pins all of them.

The record under test is the two-column text file, because that is the only
kind the spec permits to be repaired at all (§4.2.3). Wide tables are covered by
`test_recovery_rules.py`, where the property is the opposite one: they are never
reassembled.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from ra2.domain.delivery import Dialect, FileKind, RowOutcome
from ra2.domain.findings import FindingCode
from ra2.domain.parsing.reader import read_rows
from ra2.domain.parsing.recovery import is_key_anchor, recover_rows

TEXT_DIALECT = Dialect(delimiter=";")
KEY = "aa" + "0" * 29 + "1"
HEADER = "UNFALLUID;HERGANG"

#: Narrative characters. Quotes are excluded because a leading `"` opens an
#: RFC4180 quoted field — that is the *reader's* job and h04 covers it. `\r` and
#: `\n` are excluded because this test inserts the splits itself; they are the
#: independent variable, not noise.
NARRATIVE_CHARS = st.characters(
    codec="cp1252",
    exclude_characters='"\r\n',
    exclude_categories=("Cc", "Cs"),
)

segments = st.lists(
    st.text(alphabet=NARRATIVE_CHARS, min_size=0, max_size=24),
    min_size=1,
    max_size=7,
)


def _round_trip(parts: list[str]) -> tuple[str, ...] | None:
    """Write `parts` as one record split over `len(parts)` lines, then read it.

    Returns the single recovered record's fields, or `None` when the split
    produced more than one record — which the caller treats as a failure.
    """
    lines = [HEADER, f"{KEY};{parts[0]}", *parts[1:]]
    text = "\r\n".join(lines) + "\r\n"

    raw = list(read_rows(text, TEXT_DIALECT))
    recovered = list(
        recover_rows(
            raw[1:],
            kind=FileKind.TEXT,
            dialect=TEXT_DIALECT,
            expected_field_count=2,
        )
    )
    if len(recovered) != 1:
        return None
    return recovered[0].fields


@given(parts=segments)
@settings(max_examples=400)
def test_a_record_split_across_n_lines_round_trips(parts):
    """For every N: split, recover, and get the original narrative back.

    A continuation line that is itself a bare 32-hex key is genuinely
    ambiguous — it looks exactly like the start of a new record, which is what
    the anchor is *for* — so it is assumed away rather than pretended about.
    """
    for part in parts[1:]:
        if is_key_anchor(tuple(part.split(";"))):
            return

    fields = _round_trip(parts)
    assert fields is not None, parts
    assert fields == (KEY, "\n".join(parts))


@given(parts=segments)
@settings(max_examples=200)
def test_the_outcome_matches_whether_anything_was_split(parts):
    """One line is `OK`; more than one is `RECOVERED` and reported."""
    for part in parts[1:]:
        if is_key_anchor(tuple(part.split(";"))):
            return

    lines = [HEADER, f"{KEY};{parts[0]}", *parts[1:]]
    text = "\r\n".join(lines) + "\r\n"
    raw = list(read_rows(text, TEXT_DIALECT))
    (recovered,) = recover_rows(
        raw[1:], kind=FileKind.TEXT, dialect=TEXT_DIALECT, expected_field_count=2
    )

    split = len(parts) > 1 or ";" in parts[0]
    assert recovered.outcome is (RowOutcome.RECOVERED if split else RowOutcome.OK)
    if split:
        assert [f.code for f in recovered.findings] == [FindingCode.ROW_RECOVERED]
        assert recovered.findings[0].detail["key"] == KEY
    else:
        assert recovered.findings == ()


@given(
    parts=segments,
    key=st.text(alphabet="0123456789abcdefABCDEF", min_size=32, max_size=32),
)
@settings(max_examples=100)
def test_the_key_survives_recovery_whatever_its_case(parts, key):
    """Hex is case-insensitive, so the anchor is. The key is carried back out
    exactly as delivered — values are stored verbatim (§4.4)."""
    for part in parts[1:]:
        if is_key_anchor(tuple(part.split(";"))):
            return

    lines = [HEADER, f"{key};{parts[0]}", *parts[1:]]
    text = "\r\n".join(lines) + "\r\n"
    raw = list(read_rows(text, TEXT_DIALECT))
    (recovered,) = recover_rows(
        raw[1:], kind=FileKind.TEXT, dialect=TEXT_DIALECT, expected_field_count=2
    )
    assert recovered.key == key
    assert recovered.fields[0] == key


@given(parts=st.lists(st.text(alphabet=NARRATIVE_CHARS, max_size=12), min_size=2, max_size=5))
@settings(max_examples=200)
def test_a_wide_row_split_across_n_lines_is_never_reassembled(parts):
    """The mirror property. However many lines a 67-column row was split over,
    the result is one rejected row carrying its key — never a repaired one."""
    lines = ["|".join(f"c{i}" for i in range(4)), f"{KEY}|{parts[0]}", *parts[1:]]
    text = "\r\n".join(lines) + "\r\n"
    dialect = Dialect(delimiter="|")

    raw = list(read_rows(text, dialect))
    recovered = list(
        recover_rows(raw[1:], kind=FileKind.UNFALL, dialect=dialect, expected_field_count=4)
    )
    for row in recovered:
        assert row.outcome is not RowOutcome.RECOVERED
    rejected = [r for r in recovered if r.outcome is RowOutcome.REJECTED]
    assert rejected, parts
    assert any(r.key == KEY for r in rejected)

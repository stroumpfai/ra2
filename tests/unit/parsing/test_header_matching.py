"""The header is the only thing that decides what a file is (SD5, §12.5)."""

import pytest

from ra2.domain.delivery import FileKind
from ra2.domain.parsing.headers import (
    CANONICAL_HEADERS,
    KEY_COLUMNS,
    TEXT_KEY_COLUMN,
    UNFALL_KEY_COLUMN,
    canonical_field_count,
    classify_header,
    column_index,
    match_header,
    normalise_header,
)

EXPECTED_WIDTHS = {
    FileKind.UNFALL: 67,
    FileKind.OBJEKT: 77,
    FileKind.PERSON: 18,
    FileKind.TEXT: 2,
}


@pytest.mark.parametrize(("kind", "width"), EXPECTED_WIDTHS.items())
def test_the_canonical_sets_are_the_widths_the_spec_states(kind, width):
    """67 / 77 / 18 and the two-column text header (mvp-spec.md §4.1)."""
    assert len(CANONICAL_HEADERS[kind]) == width
    assert canonical_field_count(kind) == width


@pytest.mark.parametrize("kind", list(EXPECTED_WIDTHS))
def test_no_canonical_set_has_a_duplicate_column(kind):
    columns = normalise_header(CANONICAL_HEADERS[kind])
    assert len(set(columns)) == len(columns)


@pytest.mark.parametrize("kind", list(EXPECTED_WIDTHS))
def test_each_canonical_set_contains_its_own_primary_key(kind):
    assert KEY_COLUMNS[kind].casefold() in normalise_header(CANONICAL_HEADERS[kind])


@pytest.mark.parametrize("kind", list(EXPECTED_WIDTHS))
def test_the_exact_header_matches_that_kind(kind):
    assert match_header(CANONICAL_HEADERS[kind]) is kind
    assert classify_header(CANONICAL_HEADERS[kind]).ok is True


@pytest.mark.parametrize("kind", list(EXPECTED_WIDTHS))
def test_matching_is_case_insensitive_and_whitespace_trimmed(kind):
    """mvp-spec.md §4.1, and the reason the text file's upper-case
    `UNFALLUID` and the structured files' `UnfallUid` are the same column."""
    mangled = [f"  {c.upper()} " if i % 2 else f"\t{c.lower()}" for i, c in enumerate(CANONICAL_HEADERS[kind])]
    assert match_header(mangled) is kind
    assert classify_header(mangled).ok is True


def test_the_text_key_and_the_unfall_key_differ_only_in_case():
    assert TEXT_KEY_COLUMN.casefold() == UNFALL_KEY_COLUMN.casefold()


def test_a_header_matching_nothing_is_unknown():
    assert match_header(["REPORT_ID", "SUBMITTED_ON", "OFFICER_REMARKS"]) is FileKind.UNKNOWN
    assert match_header([]) is FileKind.UNKNOWN
    assert match_header([""]) is FileKind.UNKNOWN


def test_an_almost_right_header_is_a_mismatch_not_an_unknown():
    """A missing column is a `HEADER_MISMATCH` — blocking, but at least it
    names the table, so the analyst is told *what* is wrong rather than that
    the file is unrecognisable."""
    header = list(CANONICAL_HEADERS[FileKind.PERSON])[:-2]
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False
    assert match.missing == CANONICAL_HEADERS[FileKind.PERSON][-2:]


def test_an_extra_column_is_reported_as_extra():
    header = [*CANONICAL_HEADERS[FileKind.PERSON], "SomethingNew"]
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False
    assert match.extra == ("SomethingNew",)


def test_a_reordered_header_is_a_mismatch_even_with_the_right_columns():
    """Order is part of the contract: the rows are positional."""
    header = list(reversed(CANONICAL_HEADERS[FileKind.PERSON]))
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False


def test_a_duplicated_column_is_never_ok():
    """Two columns of the same name make every value under them positional
    guesswork, so the header cannot be `ok` however well it otherwise fits."""
    header = list(CANONICAL_HEADERS[FileKind.PERSON])
    repeated, header[5] = header[4], header[4]
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False
    assert match.duplicated == (repeated,)


def test_objekt_and_person_are_not_confused_despite_a_shared_key():
    """Both start with `ObjektUid`; only the whole set separates them."""
    assert match_header(CANONICAL_HEADERS[FileKind.OBJEKT]) is FileKind.OBJEKT
    assert match_header(CANONICAL_HEADERS[FileKind.PERSON]) is FileKind.PERSON


def test_a_two_column_header_sharing_one_name_with_text_is_still_unknown():
    """Half of a two-column set is below the threshold, so a file that merely
    happens to have an `UNFALLUID` column is not called the narrative file."""
    assert match_header([TEXT_KEY_COLUMN, "BEMERKUNG"]) is FileKind.UNKNOWN


def test_an_empty_canonical_set_can_never_produce_a_match(monkeypatch):
    """Empty tuples mean "not yet known", not "no columns" — the state
    `headers.py` shipped in at M0. A placeholder must never match."""
    monkeypatch.setitem(CANONICAL_HEADERS, FileKind.PERSON, ())
    assert match_header([]) is FileKind.UNKNOWN
    assert match_header(["anything"]) is FileKind.UNKNOWN
    assert match_header(CANONICAL_HEADERS[FileKind.TEXT]) is FileKind.TEXT


def test_a_bom_on_the_first_column_does_not_break_the_match():
    header = ["﻿" + TEXT_KEY_COLUMN, "HERGANG"]
    assert match_header(header) is FileKind.TEXT


def test_column_index_finds_a_column_however_it_is_cased():
    header = ["UnfallUid", " KANTONAUSW ", "AnzObjFeld"]
    assert column_index(header, "KantonAusw") == 1
    assert column_index(header, "kantonausw") == 1
    assert column_index(header, "Missing") is None


def test_canonical_field_count_is_none_for_an_unknown_kind():
    assert canonical_field_count(FileKind.UNKNOWN) is None


def test_no_canonical_column_name_contains_a_delimiter_or_a_newline():
    """A column name carrying `|`, `;` or a newline would make the header
    itself unparseable, and would mean the names came from somewhere other
    than a real header line."""
    for columns in CANONICAL_HEADERS.values():
        for name in columns:
            assert name == name.strip()
            assert not any(c in name for c in "|;\r\n\"")

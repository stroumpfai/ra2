"""The header is the only thing that decides what a file is (SD5, §12.5)."""

import pytest

from ra2.domain.delivery import FileKind
from ra2.domain.parsing.headers import (
    CANONICAL_COLUMN_SETS,
    TEXT_KEY_COLUMN,
    UNFALL_KEY_COLUMN,
    classify_header,
    column_index,
    match_header,
    normalise_header,
)

#: RADIS — index 0 of every kind's `ColumnSet` tuple, by construction.
RADIS = {kind: sets[0] for kind, sets in CANONICAL_COLUMN_SETS.items()}
#: Astrana — index 1, only present for the three structured kinds.
ASTRANA = {kind: sets[1] for kind, sets in CANONICAL_COLUMN_SETS.items() if len(sets) > 1}

RADIS_WIDTHS = {
    FileKind.UNFALL: 67,
    FileKind.OBJEKT: 77,
    FileKind.PERSON: 18,
    FileKind.TEXT: 2,
}
ASTRANA_WIDTHS = {
    FileKind.UNFALL: 67,
    FileKind.OBJEKT: 76,
    FileKind.PERSON: 21,
}


@pytest.mark.parametrize(("kind", "width"), RADIS_WIDTHS.items())
def test_the_radis_canonical_sets_are_the_widths_the_spec_states(kind, width):
    """67 / 77 / 18 and the two-column text header (mvp-spec.md §4.1)."""
    assert len(RADIS[kind].columns) == width


@pytest.mark.parametrize(("kind", "width"), ASTRANA_WIDTHS.items())
def test_the_astrana_canonical_sets_are_the_widths_from_the_real_samples(kind, width):
    """67 / 76 / 21, from `data/ASTRANA-Export/samples/*.csv`."""
    assert len(ASTRANA[kind].columns) == width


@pytest.mark.parametrize("kind", list(RADIS_WIDTHS))
def test_no_radis_canonical_set_has_a_duplicate_column(kind):
    columns = normalise_header(RADIS[kind].columns)
    assert len(set(columns)) == len(columns)


@pytest.mark.parametrize("kind", list(ASTRANA))
def test_no_astrana_canonical_set_has_a_duplicate_column(kind):
    columns = normalise_header(ASTRANA[kind].columns)
    assert len(set(columns)) == len(columns)


@pytest.mark.parametrize("kind", list(RADIS_WIDTHS))
def test_each_radis_canonical_set_contains_its_own_primary_key(kind):
    assert RADIS[kind].key_column.casefold() in normalise_header(RADIS[kind].columns)


@pytest.mark.parametrize("kind", list(ASTRANA))
def test_each_astrana_canonical_set_contains_its_own_primary_key(kind):
    assert ASTRANA[kind].key_column.casefold() in normalise_header(ASTRANA[kind].columns)


@pytest.mark.parametrize("kind", list(RADIS_WIDTHS))
def test_the_exact_radis_header_matches_that_kind(kind):
    match = classify_header(RADIS[kind].columns)
    assert match_header(RADIS[kind].columns) is kind
    assert match.ok is True
    assert match.column_set == RADIS[kind]


@pytest.mark.parametrize("kind", list(ASTRANA))
def test_the_exact_astrana_header_matches_that_kind(kind):
    match = classify_header(ASTRANA[kind].columns)
    assert match_header(ASTRANA[kind].columns) is kind
    assert match.ok is True
    assert match.column_set == ASTRANA[kind]


def test_astrana_and_radis_headers_for_the_same_kind_do_not_cross_match():
    """RADIS and Astrana share almost no literal column names, so a header
    for one must never resolve to the other's vocabulary."""
    for kind in ASTRANA:
        assert classify_header(RADIS[kind].columns).column_set == RADIS[kind]
        assert classify_header(ASTRANA[kind].columns).column_set == ASTRANA[kind]


@pytest.mark.parametrize("kind", list(RADIS_WIDTHS))
def test_matching_is_case_insensitive_and_whitespace_trimmed(kind):
    """mvp-spec.md §4.1, and the reason the text file's upper-case
    `UNFALLUID` and the structured files' `UnfallUid` are the same column."""
    mangled = [
        f"  {c.upper()} " if i % 2 else f"\t{c.lower()}" for i, c in enumerate(RADIS[kind].columns)
    ]
    assert match_header(mangled) is kind
    assert classify_header(mangled).ok is True


@pytest.mark.parametrize("kind", list(ASTRANA))
def test_astrana_matching_is_case_insensitive_and_whitespace_trimmed(kind):
    mangled = [
        f"  {c.upper()} " if i % 2 else f"\t{c.lower()}"
        for i, c in enumerate(ASTRANA[kind].columns)
    ]
    assert match_header(mangled) is kind
    assert classify_header(mangled).ok is True


def test_the_text_key_and_the_unfall_key_differ_only_in_case():
    assert TEXT_KEY_COLUMN.casefold() == UNFALL_KEY_COLUMN.casefold()


def test_a_header_matching_nothing_is_unknown():
    assert match_header(["REPORT_ID", "SUBMITTED_ON", "OFFICER_REMARKS"]) is FileKind.UNKNOWN
    assert match_header([]) is FileKind.UNKNOWN
    assert match_header([""]) is FileKind.UNKNOWN


def test_an_almost_right_radis_header_is_a_mismatch_not_an_unknown():
    """A missing column is a `HEADER_MISMATCH` — blocking, but at least it
    names the table, so the analyst is told *what* is wrong rather than that
    the file is unrecognisable."""
    header = list(RADIS[FileKind.PERSON].columns)[:-2]
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False
    assert match.column_set == RADIS[FileKind.PERSON]
    assert match.missing == RADIS[FileKind.PERSON].columns[-2:]


def test_an_almost_right_astrana_header_is_a_mismatch_naming_astrana():
    header = list(ASTRANA[FileKind.PERSON].columns)[:-2]
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False
    assert match.column_set == ASTRANA[FileKind.PERSON]
    assert match.missing == ASTRANA[FileKind.PERSON].columns[-2:]


def test_an_extra_column_is_reported_as_extra():
    header = [*RADIS[FileKind.PERSON].columns, "SomethingNew"]
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False
    assert match.extra == ("SomethingNew",)


def test_a_reordered_header_is_a_mismatch_even_with_the_right_columns():
    """Order is part of the contract: the rows are positional."""
    header = list(reversed(RADIS[FileKind.PERSON].columns))
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False


def test_a_reordered_astrana_header_is_a_mismatch_even_with_the_right_columns():
    header = list(reversed(ASTRANA[FileKind.PERSON].columns))
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False


def test_a_duplicated_column_is_never_ok():
    """Two columns of the same name make every value under them positional
    guesswork, so the header cannot be `ok` however well it otherwise fits."""
    header = list(RADIS[FileKind.PERSON].columns)
    repeated, header[5] = header[4], header[4]
    match = classify_header(header)
    assert match.kind is FileKind.PERSON
    assert match.ok is False
    assert match.duplicated == (repeated,)


def test_objekt_and_person_are_not_confused_despite_a_shared_key():
    """Both start with `ObjektUid`; only the whole set separates them."""
    assert match_header(RADIS[FileKind.OBJEKT].columns) is FileKind.OBJEKT
    assert match_header(RADIS[FileKind.PERSON].columns) is FileKind.PERSON


def test_astrana_objekt_and_mitfahrende_are_not_confused_despite_a_shared_prefix():
    """Both share `Jahr`/`Datum`/`Unfall-UID`/`Objekt-UID`/`Objekt-Nr. (intern)`;
    only the whole set separates them, same as RADIS's `objekt`/`person`."""
    assert match_header(ASTRANA[FileKind.OBJEKT].columns) is FileKind.OBJEKT
    assert match_header(ASTRANA[FileKind.PERSON].columns) is FileKind.PERSON


def test_a_two_column_header_sharing_one_name_with_text_is_still_unknown():
    """Half of a two-column set is below the threshold, so a file that merely
    happens to have an `UNFALLUID` column is not called the narrative file."""
    assert match_header([TEXT_KEY_COLUMN, "BEMERKUNG"]) is FileKind.UNKNOWN


def test_an_empty_canonical_set_can_never_produce_a_match(monkeypatch):
    """No known vocabulary for a kind means "not yet known", not "no
    columns" — a placeholder must never match."""
    monkeypatch.setitem(CANONICAL_COLUMN_SETS, FileKind.PERSON, ())
    assert match_header([]) is FileKind.UNKNOWN
    assert match_header(["anything"]) is FileKind.UNKNOWN
    assert match_header(RADIS[FileKind.TEXT].columns) is FileKind.TEXT


def test_a_bom_on_the_first_column_does_not_break_the_match():
    header = ["﻿" + TEXT_KEY_COLUMN, "HERGANG"]
    assert match_header(header) is FileKind.TEXT


def test_column_index_finds_a_column_however_it_is_cased():
    header = ["UnfallUid", " KANTONAUSW ", "AnzObjFeld"]
    assert column_index(header, "KantonAusw") == 1
    assert column_index(header, "kantonausw") == 1
    assert column_index(header, "Missing") is None


def test_no_canonical_column_name_contains_a_delimiter_or_a_newline():
    """A column name carrying `|`, `;` or a newline would make the header
    itself unparseable, and would mean the names came from somewhere other
    than a real header line."""
    for column_sets in CANONICAL_COLUMN_SETS.values():
        for column_set in column_sets:
            for name in column_set.columns:
                assert name == name.strip()
                assert not any(c in name for c in '|;\r\n"')

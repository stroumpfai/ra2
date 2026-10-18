"""Reading an imported rule file or name list (sw-design.md §19.5).

Structure only: whether the rules then *work* is `check_rules`'s job, in
`test_check_rules.py`. Every refusal is asserted by its code, never by text.
"""

import pytest
from tests.unit.scrub.conftest import fixture_bytes, name_list, rule_file

from ra2.domain.scrub import (
    MIN_ENTRY_LETTERS,
    ListKind,
    ListNoticeCode,
    NameListFile,
    RegexRuleFile,
    RuleSource,
    ScrubImportErrorCode,
    entry_key,
    entry_matches,
    parse_name_list,
    parse_regex_rules,
    search_entries,
)

pytestmark = pytest.mark.unit


def _codes(result: object) -> list[ScrubImportErrorCode]:
    assert isinstance(result, list), result
    return [e.code for e in result]


# --- rule files -----------------------------------------------------------------


def test_the_fixture_rule_file_parses_into_imported_rules_in_order() -> None:
    parsed = rule_file()
    assert [r.rule_id for r in parsed.rules] == ["iban-ch", "ahv", "date"]
    assert all(r.source is RuleSource.IMPORTED for r in parsed.rules)
    assert parsed.protected == ("Tempo 80", "am Vortag")
    assert parsed.rules[0].description == "Swiss IBAN, grouped or not."


def test_a_file_with_only_protected_strings_is_valid() -> None:
    parsed = parse_regex_rules(b'protected = ["Tempo 80"]\n')
    assert isinstance(parsed, RegexRuleFile)
    assert parsed.rules == ()


def test_a_rule_file_that_is_not_utf8_is_refused() -> None:
    assert _codes(parse_regex_rules('tag = "Ä"'.encode("cp1252"))) == [
        ScrubImportErrorCode.NOT_UTF8
    ]


def test_a_rule_file_that_is_not_toml_is_refused() -> None:
    assert _codes(parse_regex_rules(b"[[rule]\nid = ")) == [ScrubImportErrorCode.TOML_INVALID]


def test_a_misspelt_key_is_refused_rather_than_ignored() -> None:
    """`must_not_macth` silently dropped would be a rule with no
    counter-examples that looks like one with some."""
    content = b"""
[[rule]]
id = "x"
tag = "X"
pattern = 'x'
must_match = ["x"]
must_not_macth = ["y"]
"""
    errors = parse_regex_rules(content)
    assert _codes(errors) == [ScrubImportErrorCode.UNKNOWN_FIELD]
    assert isinstance(errors, list)
    assert errors[0].detail == {"field": "must_not_macth"}


def test_an_unknown_top_level_key_is_refused() -> None:
    assert _codes(parse_regex_rules(b"rules = []\n")) == [ScrubImportErrorCode.UNKNOWN_FIELD]


@pytest.mark.parametrize("missing", ["id", "tag", "pattern", "must_match"])
def test_every_required_field_is_required(missing: str) -> None:
    fields = {"id": '"x"', "tag": '"X"', "pattern": "'x'", "must_match": '["x"]'}
    del fields[missing]
    content = "[[rule]]\n" + "".join(f"{k} = {v}\n" for k, v in fields.items())
    errors = parse_regex_rules(content.encode())
    assert _codes(errors) == [ScrubImportErrorCode.FIELD_MISSING]
    assert isinstance(errors, list)
    assert errors[0].detail == {"field": missing}


@pytest.mark.parametrize(
    ("field", "value"),
    [("tag", "1"), ("pattern", "['x']"), ("must_match", '"x"'), ("must_not_match", "[1]")],
)
def test_a_field_of_the_wrong_type_is_refused(field: str, value: str) -> None:
    fields = {"id": '"x"', "tag": '"X"', "pattern": "'x'", "must_match": '["x"]'}
    fields[field] = value
    content = "[[rule]]\n" + "".join(f"{k} = {v}\n" for k, v in fields.items())
    assert _codes(parse_regex_rules(content.encode())) == [ScrubImportErrorCode.FIELD_INVALID]


def test_a_rule_file_with_a_bom_is_read_and_says_so() -> None:
    content = b'\xef\xbb\xbfprotected = ["Tempo 80"]\n'
    parsed = parse_regex_rules(content)
    assert isinstance(parsed, RegexRuleFile)
    assert [n.code for n in parsed.notices] == [ListNoticeCode.BOM]


# --- name lists -----------------------------------------------------------------


def test_an_lf_list_with_a_comment_parses_in_file_order() -> None:
    parsed = name_list(ListKind.FIRSTNAME, "s01_firstnames.txt")
    assert parsed.entries[:3] == ("Hans", "Anna", "Martin")
    assert [n.code for n in parsed.notices] == [ListNoticeCode.COMMENT_LINES]


def test_every_irregularity_of_a_list_is_counted_never_dropped_silently() -> None:
    """s02: a BOM, CRLF, a comment, a blank line, two duplicates, two
    entries too short and one with no letters — all reported (Do-NOT #6)."""
    parsed = name_list(ListKind.LASTNAME, "s02_lastnames.txt")
    notices = {n.code: n for n in parsed.notices}
    assert notices[ListNoticeCode.BOM].count == 1
    assert notices[ListNoticeCode.CRLF].count == 18
    assert notices[ListNoticeCode.COMMENT_LINES].count == 1
    assert notices[ListNoticeCode.BLANK_LINES].count == 1
    assert notices[ListNoticeCode.DUPLICATES].examples == ("MÜLLER", "Mueller")
    assert notices[ListNoticeCode.TOO_SHORT].examples == ("Li", "Le")
    assert notices[ListNoticeCode.NO_LETTERS].examples == ("123",)
    assert "Müller" in parsed.entries
    assert not {"MÜLLER", "Mueller", "Li", "Le", "123"} & set(parsed.entries)


def test_a_list_that_is_not_utf8_is_refused_with_its_byte_offset() -> None:
    errors = parse_name_list(ListKind.LASTNAME, fixture_bytes("s05_lastnames_cp1252.txt"))
    assert _codes(errors) == [ScrubImportErrorCode.NOT_UTF8]
    assert isinstance(errors, list)
    assert errors[0].detail == {"byte_offset": "1"}


def test_a_list_with_no_usable_entry_is_refused() -> None:
    assert _codes(parse_name_list(ListKind.WHITELIST, b"# nur ein Kommentar\n\nLi\n")) == [
        ScrubImportErrorCode.LIST_EMPTY
    ]


def test_a_rule_file_is_not_a_name_list() -> None:
    with pytest.raises(ValueError, match="parse_regex_rules"):
        parse_name_list(ListKind.REGEX, b"Hans\n")


def test_the_letter_floor_is_three() -> None:
    assert MIN_ENTRY_LETTERS == 3
    parsed = parse_name_list(ListKind.LASTNAME, b"Ng\nNgo\n")
    assert isinstance(parsed, NameListFile)
    assert parsed.entries == ("Ngo",)


@pytest.mark.parametrize(
    ("entry", "key"),
    [
        ("Müller", "mueller"),
        ("MUELLER", "mueller"),
        ("Mu\u0308ller", "mueller"),
        ("D'Alessandro", "d alessandro"),
        ("D’Alessandro", "d alessandro"),
        ("von  Allmen", "von allmen"),
        ("René", "rene"),
        ("Straße", "strasse"),
    ],
)
def test_an_entry_is_known_by_its_transliterated_tokens(entry: str, key: str) -> None:
    assert entry_key(entry) == key


@pytest.mark.parametrize("query", ["müll", "MÜLL", "muell", "Mull", "ller", "", "  "])
def test_a_search_finds_an_entry_the_way_the_scrubber_would(query: str) -> None:
    assert entry_matches("Müller", query)


@pytest.mark.parametrize("query", ["meier", "müllers", "x"])
def test_a_search_does_not_find_what_is_not_there(query: str) -> None:
    assert not entry_matches("Müller", query)


def test_a_search_spans_the_tokens_of_a_multi_token_entry() -> None:
    assert entry_matches("D'Alessandro", "d alessandro")
    assert entry_matches("von Allmen", "VON ALL")


_ENTRIES = ("Müller", "Mueller", "Meier", "von Allmen", "D'Alessandro", "Brunner")


@pytest.mark.parametrize("query", ["müll", "MUELL", "all", "ner", "x", "von all"])
def test_searching_a_list_finds_what_each_entry_would(query: str) -> None:
    expected = [e for e in _ENTRIES if entry_matches(e, query)]
    assert list(search_entries(_ENTRIES, query)) == expected


@pytest.mark.parametrize("query", ["", "   ", "123", "-"])
def test_a_search_with_no_letters_hands_the_list_back_untouched(query: str) -> None:
    """Not a copy: the Scrubbing screen shows a list unsearched on every
    visit, and that must not cost a pass over every entry."""
    assert search_entries(_ENTRIES, query) is _ENTRIES

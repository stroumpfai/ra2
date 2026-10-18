"""What `Scrubber.scrub` does to a narrative (sw-design.md §19.2–§19.4).

Every name below is invented and on the fixture lists; every number is
invented and has the shape of a Swiss one.
"""

import pytest

from ra2.domain.scrub import (
    BOTH_LISTS_RULE_ID,
    FIRSTNAME_RULE_ID,
    LASTNAME_RULE_ID,
    PROTECTED_STRINGS,
    RegexRule,
    Scrubber,
    ScrubRules,
    ScrubTimeoutError,
    placeholder,
)
from ra2.domain.scrub_mandatory import MANDATORY_RULES

pytestmark = pytest.mark.unit


# --- the shape of the output ------------------------------------------------


def test_a_placeholder_is_the_tag_and_its_number_in_angle_brackets() -> None:
    assert placeholder("Lastname", 1) == "<Lastname_1>"


def test_each_kind_of_personal_data_gets_its_own_tag(scrubber: Scrubber) -> None:
    text = (
        "Am 12.03.2024 rief Jörg Müller (079 123 45 67, hans@example.ch, "
        "AHV 756.1234.5678.97, IBAN CH93 0076 2011 6238 5295 7) wegen BE 123456 an."
    )
    assert scrubber.scrub(text).text == (
        "Am <Date_1> rief <Firstname_1> <Lastname_1> (<Phone_1>, <Email_1>, "
        "AHV <AHV_1>, IBAN <IBAN_1>) wegen <LicensePlate_1> an."
    )


def test_text_outside_the_replaced_spans_is_byte_identical(scrubber: Scrubber) -> None:
    text = "B1  fuhr\tmit\u00a0BE 123456 los;  Herr Meier\r\nwartete."
    result = scrubber.scrub(text)
    rebuilt = []
    cursor = 0
    for hit in result.hits:
        rebuilt.append(text[cursor : hit.start])
        rebuilt.append(hit.placeholder)
        cursor = hit.end
    rebuilt.append(text[cursor:])
    assert "".join(rebuilt) == result.text
    assert result.text == "B1  fuhr\tmit\u00a0<LicensePlate_1> los;  Herr <Lastname_1>\r\nwartete."


def test_empty_text_comes_back_unchanged(scrubber: Scrubber) -> None:
    result = scrubber.scrub("")
    assert result.text == ""
    assert result.hits == ()
    assert not result.changed


@pytest.mark.parametrize("protected", PROTECTED_STRINGS)
def test_every_protected_string_survives_the_full_rule_set(
    scrubber: Scrubber, protected: str
) -> None:
    assert scrubber.scrub(protected).text == protected


# --- determinism and idempotence ---------------------------------------------


def test_the_same_text_gives_the_same_result_twice(scrubber: Scrubber) -> None:
    text = "Herr Müller und Frau Meier, 079 123 45 67, ZH 1234."
    assert scrubber.scrub(text) == scrubber.scrub(text)


def test_scrubbing_scrubbed_text_changes_nothing(scrubber: Scrubber) -> None:
    once = scrubber.scrub("Hans Müller, 079 123 45 67, BE 123456, a@b.ch").text
    assert scrubber.scrub(once).text == once


def test_a_placeholder_is_never_matched_by_a_later_rule() -> None:
    """A rule that would match the placeholder text itself still cannot
    reach it: every candidate is collected against the original text."""
    eats_tags = RegexRule("tags", "Tag", r"<[A-Za-z]+_\d+>", must_match=("<Phone_1>",))
    scrubber = Scrubber(ScrubRules((*MANDATORY_RULES, eats_tags)))
    assert scrubber.scrub("Tel. 079 123 45 67").text == "Tel. <Phone_1>"


# --- numbering (SD64) ----------------------------------------------------------


def test_one_value_written_two_ways_is_one_number(mandatory_only: Scrubber) -> None:
    result = mandatory_only.scrub("Er rief 079 123 45 67 an, dann nochmals 0791234567.")
    assert result.text == "Er rief <Phone_1> an, dann nochmals <Phone_1>."


def test_two_values_are_two_numbers_counted_per_tag(mandatory_only: Scrubber) -> None:
    result = mandatory_only.scrub("079 123 45 67, BE 123456, 044 123 45 67, ZH 1234")
    assert result.text == "<Phone_1>, <LicensePlate_1>, <Phone_2>, <LicensePlate_2>"


def test_numbers_restart_with_every_text(mandatory_only: Scrubber) -> None:
    mandatory_only.scrub("079 123 45 67, 044 123 45 67")
    assert mandatory_only.scrub("044 123 45 67").text == "<Phone_1>"


def test_one_surname_shared_by_two_people_is_one_number(scrubber: Scrubber) -> None:
    result = scrubber.scrub("Hans Müller sprach mit Anna Müller.")
    assert result.text == "<Firstname_1> <Lastname_1> sprach mit <Firstname_2> <Lastname_1>."


# --- overlaps (§19.2) --------------------------------------------------------


def test_the_longer_match_at_the_same_start_wins() -> None:
    short = RegexRule("short", "Short", r"\d{3}", must_match=("123",))
    long = RegexRule("long", "Long", r"\d{3} \d{3}", must_match=("123 456",))
    assert Scrubber(ScrubRules((short, long))).scrub("123 456").text == "<Long_1>"


def test_the_earlier_start_wins_over_a_longer_overlapping_match() -> None:
    early = RegexRule("early", "Early", r"ab", must_match=("ab",))
    later = RegexRule("later", "Later", r"bcdef", must_match=("bcdef",))
    assert Scrubber(ScrubRules((early, later))).scrub("abcdef").text == "<Early_1>cdef"


def test_the_rule_declared_first_wins_a_tie() -> None:
    first = RegexRule("first", "First", r"\d{4}", must_match=("1234",))
    second = RegexRule("second", "Second", r"\d{4}", must_match=("1234",))
    assert Scrubber(ScrubRules((first, second))).scrub("1234").text == "<First_1>"


def test_an_ahv_number_is_claimed_by_the_ahv_rule(scrubber: Scrubber) -> None:
    assert scrubber.scrub("AHV 756.1234.5678.97").text == "AHV <AHV_1>"


def test_an_iban_is_one_placeholder_never_split(scrubber: Scrubber) -> None:
    assert scrubber.scrub("CH93 0076 2011 6238 5295 7").text == "<IBAN_1>"


def test_a_regex_match_beats_a_name_inside_it() -> None:
    """`hans.meier@example.ch` is one email, not an email with two names."""
    rules = ScrubRules(MANDATORY_RULES, firstnames=("Hans",), lastnames=("Meier",))
    assert Scrubber(rules).scrub("hans.meier@example.ch").text == "<Email_1>"


# --- names: tokens, case, accents (§19.3) ------------------------------------


@pytest.mark.parametrize(
    "spelling",
    ["Müller", "MÜLLER", "müller", "Mueller", "Muller", "Mu\u0308ller", "MUELLER"],
)
def test_a_name_matches_whatever_its_case_and_accents(scrubber: Scrubber, spelling: str) -> None:
    assert scrubber.scrub(f"Zeuge {spelling} meldete sich.").text == (
        "Zeuge <Lastname_1> meldete sich."
    )


def test_all_spellings_of_one_name_share_its_number(scrubber: Scrubber) -> None:
    result = scrubber.scrub("Herr Müller, später MUELLER, zuletzt Mu\u0308ller.")
    assert result.text == "Herr <Lastname_1>, später <Lastname_1>, zuletzt <Lastname_1>."


def test_an_nfd_list_entry_matches_nfc_text(scrubber: Scrubber) -> None:
    """`s01` carries `Jörg` decomposed; the narrative carries it composed."""
    assert scrubber.scrub("Jörg war Lenker.").text == "<Firstname_1> war Lenker."


def test_an_accent_missing_from_the_text_still_matches(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Rene und Celine").text == "<Firstname_1> und <Firstname_2>"


@pytest.mark.parametrize("word", ["Müllerstrasse", "Meierhof", "Weberei", "Brunnerweg"])
def test_a_name_inside_a_longer_word_is_not_a_name(scrubber: Scrubber, word: str) -> None:
    assert scrubber.scrub(f"Unfall an der {word}.").text == f"Unfall an der {word}."


def test_a_multi_token_entry_matches_as_one_name(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Frau von Allmen bremste.").text == "Frau <Lastname_1> bremste."


@pytest.mark.parametrize("apostrophe", ["'", "’"])
def test_an_apostrophe_name_matches_with_either_apostrophe(
    scrubber: Scrubber, apostrophe: str
) -> None:
    text = f"M. D{apostrophe}Alessandro roulait."
    assert scrubber.scrub(text).text == "M. <Lastname_1> roulait."


def test_a_hyphenated_entry_matches_whole(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Marie-Claire fuhr.").text == "<Firstname_1> fuhr."


def test_a_double_name_of_two_listed_names_is_two_placeholders(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Frau Meier-Müller").text == "Frau <Lastname_1>-<Lastname_2>"


def test_a_name_split_by_a_line_break_is_still_both_names(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Lenker Hans\nMüller").text == "Lenker <Firstname_1>\n<Lastname_1>"


def test_a_multi_token_entry_split_by_a_line_break_still_matches(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Frau von\nAllmen").text == "Frau <Lastname_1>"


def test_the_genitive_is_a_known_miss(scrubber: Scrubber) -> None:
    """Inflected forms are not on the list and are not guessed at. Recorded
    in the risk register as residual risk, not worked around (§19.8)."""
    assert scrubber.scrub("Meiers Auto").text == "Meiers Auto"


def test_a_name_whose_letters_were_deleted_upstream_is_a_known_miss() -> None:
    """h09's hazard: cp1252-only characters deleted, so `Lœwe` arrives as
    `Lwe`. Nothing can match what is not there."""
    rules = ScrubRules(MANDATORY_RULES, lastnames=("Lœwe",))
    assert Scrubber(rules).scrub("Herr Lwe").text == "Herr Lwe"


def test_the_role_codes_are_never_touched(scrubber: Scrubber) -> None:
    text = "B1 fuhr auf G1 auf; P wurde verletzt."
    assert scrubber.scrub(text).text == text


# --- the whitelist and honorifics (Q2) ---------------------------------------


def test_a_whitelisted_word_is_left_alone(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Ein Fuchs querte die Fahrbahn.").text == (
        "Ein Fuchs querte die Fahrbahn."
    )


def test_a_colour_that_is_a_surname_stays_a_colour(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Das Fahrzeug war weiss.").text == "Das Fahrzeug war weiss."


@pytest.mark.parametrize(
    "honorific", ["Herr", "Frau", "Hr.", "Fr.", "Mr.", "M.", "Mme", "Monsieur"]
)
def test_an_honorific_lifts_the_whitelist(scrubber: Scrubber, honorific: str) -> None:
    assert scrubber.scrub(f"{honorific} Fuchs bremste.").text == (
        f"{honorific} <Lastname_1> bremste."
    )


def test_an_honorific_never_makes_an_unlisted_word_a_name(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Herr Zgraggen bremste.").text == "Herr Zgraggen bremste."


def test_a_word_ending_in_an_honorific_is_not_one(scrubber: Scrubber) -> None:
    """`Bauherr Fuchs` is not `Herr Fuchs`: the lookbehind sees the `u`."""
    assert scrubber.scrub("Der Bauherr Fuchs").text == "Der Bauherr Fuchs"


# --- a name on both lists (Q1) -------------------------------------------------


def test_a_both_lists_name_before_a_surname_is_a_first_name(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Martin Müller").text == "<Firstname_1> <Lastname_1>"


def test_a_both_lists_name_after_a_first_name_is_a_surname(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Hans Martin").text == "<Firstname_1> <Lastname_1>"


def test_a_both_lists_name_alone_is_a_name(scrubber: Scrubber) -> None:
    result = scrubber.scrub("Martin kam zu spät.")
    assert result.text == "<Name_1> kam zu spät."
    assert result.hits[0].rule_id == BOTH_LISTS_RULE_ID


def test_a_both_lists_name_keeps_the_tag_it_got_earlier(scrubber: Scrubber) -> None:
    assert scrubber.scrub("Martin Simon kam. Martin rief.").text == (
        "<Firstname_1> <Lastname_1> kam. <Firstname_1> rief."
    )


def test_name_hits_report_under_the_list_they_came_from(scrubber: Scrubber) -> None:
    hits = scrubber.scrub("Anna Meier").hits
    assert [(h.rule_id, h.entry) for h in hits] == [
        (FIRSTNAME_RULE_ID, "anna"),
        (LASTNAME_RULE_ID, "meier"),
    ]


# --- failing closed (SD66) -----------------------------------------------------


def test_a_timeout_raises_and_returns_nothing() -> None:
    slow = RegexRule("slow", "Slow", r"(a|aa)+$", must_match=("aaa",))
    scrubber = Scrubber(ScrubRules((*MANDATORY_RULES, slow)), timeout_s=0.05)
    with pytest.raises(ScrubTimeoutError) as raised:
        scrubber.scrub("a" * 64 + "!")
    assert raised.value.rule_id == "slow"
    assert "a" * 64 not in str(raised.value)

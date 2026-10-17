"""The mandatory rules meet their contract (plan-text-scrubbing.md §4, `SD63`).

The patterns in `scrub_mandatory.py` are provisional until the supplied ones
arrive. **This file is the gate a supplied pattern has to pass**: the table
below is the plan's §4, transcribed, and it is asserted separately from the
rules' own example tuples, so editing a rule's examples to make a weaker
pattern pass does not weaken this test.
"""

import pytest
import regex

from ra2.domain.scrub import (
    RESERVED_TAGS,
    RuleSource,
    Scrubber,
    ScrubRules,
    check_rules,
)
from ra2.domain.scrub_mandatory import MANDATORY_RULES, MANDATORY_RULES_VERSION

pytestmark = pytest.mark.unit

#: plan-text-scrubbing.md §4, "Must match (at least)".
CONTRACT_MATCH = {
    "license-plate": ["BE 123456", "ZH 1234", "VD-123 456", "AG 12 345", "TI123456"],
    "phone": [
        "079 123 45 67",
        "+41 79 123 45 67",
        "0041 79 123 45 67",
        "044 123 45 67",
        "+41 (0)44 123 45 67",
        "0791234567",
    ],
    "email": ["a.b@example.ch", "x+y@sub.example.org"],
}

#: plan-text-scrubbing.md §4, "Must not alter". Local to the rule (§3.5).
CONTRACT_NO_MATCH = {
    "license-plate": [
        "B1",
        "G1",
        "A1",
        "N1",
        "Kanton BE",
        "Hauptstrasse 12",
        "Km 12.5",
        "im Kanton ZH 2 Verletzte",
    ],
    "phone": [
        "117",
        "144",
        "1414",
        "um 14.30 Uhr",
        "12.03.2024",
        "80 km/h",
        "756.1234.5678.97",
    ],
    "email": ["B1@", "@"],
}

_BY_ID = {rule.rule_id: rule for rule in MANDATORY_RULES}


def test_the_three_mandatory_rules_are_plates_phones_and_emails_in_that_order() -> None:
    assert [r.rule_id for r in MANDATORY_RULES] == ["license-plate", "phone", "email"]
    assert [r.tag for r in MANDATORY_RULES] == ["LicensePlate", "Phone", "Email"]
    assert all(r.source is RuleSource.MANDATORY for r in MANDATORY_RULES)
    assert MANDATORY_RULES_VERSION >= 1


def test_the_mandatory_rules_pass_every_check_an_import_must_pass() -> None:
    assert check_rules(ScrubRules(MANDATORY_RULES)) == []


def test_no_mandatory_rule_uses_a_name_tag() -> None:
    assert not {r.tag for r in MANDATORY_RULES} & set(RESERVED_TAGS)


@pytest.mark.parametrize(
    ("rule_id", "example"),
    [(rule_id, example) for rule_id, examples in CONTRACT_MATCH.items() for example in examples],
)
def test_each_contract_example_is_replaced_whole(rule_id: str, example: str) -> None:
    scrubber = Scrubber(ScrubRules(MANDATORY_RULES))
    result = scrubber.scrub(f"Vorher {example} nachher.")
    tag = _BY_ID[rule_id].tag
    assert result.text == f"Vorher <{tag}_1> nachher."


@pytest.mark.parametrize(
    ("rule_id", "example"),
    [(rule_id, example) for rule_id, examples in CONTRACT_NO_MATCH.items() for example in examples],
)
def test_each_contract_counter_example_is_left_to_other_rules(rule_id: str, example: str) -> None:
    pattern = regex.compile(_BY_ID[rule_id].pattern, regex.VERSION0)
    assert pattern.search(example) is None


def test_the_contract_examples_are_carried_by_the_rules_themselves() -> None:
    """The Scrubbing screen shows each rule's own examples. They must at
    least include the contract, so what the analyst reads is what is
    tested."""
    for rule_id, examples in CONTRACT_MATCH.items():
        assert set(examples) <= set(_BY_ID[rule_id].must_match), rule_id
    for rule_id, examples in CONTRACT_NO_MATCH.items():
        assert set(examples) <= set(_BY_ID[rule_id].must_not_match), rule_id


def test_short_emergency_numbers_survive_a_whole_sentence() -> None:
    text = "Notruf 117 und 144 alarmiert, die Rega 1414 flog."
    assert Scrubber(ScrubRules(MANDATORY_RULES)).scrub(text).text == text


def test_a_canton_named_in_a_sentence_is_not_a_plate() -> None:
    text = "Im Kanton ZH 2 Verletzte, im canton VD 3 blessés, Kt. BE 4."
    assert Scrubber(ScrubRules(MANDATORY_RULES)).scrub(text).text == text


def test_lower_case_words_are_never_plates() -> None:
    text = "il ne 12 pas, so 3 mal"
    assert Scrubber(ScrubRules(MANDATORY_RULES)).scrub(text).text == text

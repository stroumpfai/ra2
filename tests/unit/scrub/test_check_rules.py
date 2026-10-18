"""`check_rules`: every refusal of sw-design.md §19.5, one test per code.

A composed rule set is what is checked — the mandatory rules, the imported
ones and the lists together — because the protected strings are a property
of the whole scrubber, not of any one rule.
"""

import pytest
from tests.unit.scrub.conftest import fixture_bytes, rule_file

from ra2.domain.scrub import (
    BOTH_LISTS_RULE_ID,
    RegexRule,
    RegexRuleFile,
    ScrubImportErrorCode,
    ScrubRules,
    check_rules,
    parse_regex_rules,
)
from ra2.domain.scrub_mandatory import MANDATORY_RULES

pytestmark = pytest.mark.unit


def _rule(**overrides: object) -> RegexRule:
    fields: dict[str, object] = {
        "rule_id": "plz",
        "tag": "Plz",
        "pattern": r"(?<!\d)CH-\d{4}(?!\d)",
        "must_match": ("CH-3011",),
        "must_not_match": ("3011",),
    }
    fields.update(overrides)
    return RegexRule(**fields)  # type: ignore[arg-type]


def _codes(*rules: RegexRule, **lists: tuple[str, ...]) -> list[ScrubImportErrorCode]:
    return [e.code for e in check_rules(ScrubRules((*MANDATORY_RULES, *rules), **lists))]


def test_a_correct_rule_passes() -> None:
    assert _codes(_rule()) == []


def test_the_fixture_rule_set_with_every_list_passes(full_rules: ScrubRules) -> None:
    assert check_rules(full_rules) == []


@pytest.mark.parametrize("rule_id", ["Plz", "plz_code", "", "-plz", "x" * 65])
def test_a_malformed_id_is_refused(rule_id: str) -> None:
    assert ScrubImportErrorCode.ID_MALFORMED in _codes(_rule(rule_id=rule_id))


def test_two_rules_with_one_id_are_refused() -> None:
    assert _codes(_rule(), _rule(tag="Other")) == [ScrubImportErrorCode.DUPLICATE_ID]


def test_an_import_cannot_reuse_a_mandatory_id() -> None:
    """Reusing `phone` would be a way to replace the mandatory rule."""
    assert _codes(_rule(rule_id="phone")) == [ScrubImportErrorCode.ID_RESERVED]


def test_an_import_cannot_take_a_name_lists_id() -> None:
    assert _codes(_rule(rule_id=BOTH_LISTS_RULE_ID)) == [ScrubImportErrorCode.ID_RESERVED]


@pytest.mark.parametrize("tag", ["Firstname", "Lastname", "Name"])
def test_a_name_tag_is_reserved_for_the_lists(tag: str) -> None:
    assert _codes(_rule(tag=tag)) == [ScrubImportErrorCode.TAG_RESERVED]


@pytest.mark.parametrize("tag", ["plz", "P", "Post-Code", "Plz1", "A" * 33, "<Plz>"])
def test_a_malformed_tag_is_refused(tag: str) -> None:
    assert _codes(_rule(tag=tag)) == [ScrubImportErrorCode.TAG_MALFORMED]


def test_a_pattern_that_does_not_compile_is_refused() -> None:
    errors = check_rules(ScrubRules((*MANDATORY_RULES, _rule(pattern="CH-(\\d{4}"))))
    assert [e.code for e in errors] == [ScrubImportErrorCode.PATTERN_INVALID]
    assert "error" in errors[0].detail


@pytest.mark.parametrize("pattern", [r"\d*", r"(?=CH)", r"x?"])
def test_a_pattern_that_can_match_nothing_is_refused(pattern: str) -> None:
    codes = _codes(_rule(pattern=pattern, must_match=("CH-3011",)))
    assert ScrubImportErrorCode.PATTERN_EMPTY_MATCH in codes


def test_a_catastrophically_backtracking_pattern_is_refused() -> None:
    parsed = parse_regex_rules(fixture_bytes("s06_slow_rule.toml"))
    assert isinstance(parsed, RegexRuleFile)
    assert _codes(*parsed.rules) == [ScrubImportErrorCode.PATTERN_TOO_SLOW]


def test_a_rule_nobody_showed_working_is_refused() -> None:
    assert _codes(_rule(must_match=())) == [ScrubImportErrorCode.NO_MUST_MATCH]


def test_a_must_match_example_matched_only_in_part_is_refused() -> None:
    errors = check_rules(ScrubRules((*MANDATORY_RULES, _rule(must_match=("CH-3011 Bern",)))))
    assert [e.code for e in errors] == [ScrubImportErrorCode.MUST_MATCH_FAILED]
    assert errors[0].detail == {"example": "CH-3011 Bern"}


def test_a_must_not_match_example_its_own_rule_hits_is_refused() -> None:
    errors = check_rules(ScrubRules((*MANDATORY_RULES, _rule(must_not_match=("PLZ CH-3011",)))))
    assert [e.code for e in errors] == [ScrubImportErrorCode.MUST_NOT_MATCH_HIT]
    assert errors[0].detail == {"example": "PLZ CH-3011", "matched": "CH-3011"}


def test_must_not_match_is_local_to_its_rule() -> None:
    """The phone rule's counter-example `756.1234.5678.97` is what the AHV
    rule exists to replace; the set with both must be accepted."""
    assert check_rules(ScrubRules((*MANDATORY_RULES, *rule_file().rules))) == []


def test_a_rule_that_alters_a_protected_string_is_refused() -> None:
    eats_times = _rule(
        rule_id="time",
        tag="Time",
        pattern=r"\d{2}\.\d{2}",
        must_match=("14.30",),
        must_not_match=(),
    )
    errors = check_rules(ScrubRules((*MANDATORY_RULES, eats_times)))
    assert {e.code for e in errors} == {ScrubImportErrorCode.PROTECTED_ALTERED}
    assert {e.detail["protected"] for e in errors} >= {"um 14.30 Uhr", "um 07.45 Uhr"}
    assert all(e.rule_id == "time" for e in errors)


def test_a_name_list_that_alters_a_protected_string_is_refused() -> None:
    """`Rega` on a surname list would turn the air rescue's number into a
    person. The fix is the whitelist, and the refusal says which string."""
    errors = check_rules(ScrubRules(MANDATORY_RULES, lastnames=("Rega",)))
    assert [(e.code, e.detail["protected"]) for e in errors] == [
        (ScrubImportErrorCode.PROTECTED_ALTERED, "Rega 1414")
    ]


def test_the_whitelist_is_how_a_protected_collision_is_resolved() -> None:
    assert check_rules(ScrubRules(MANDATORY_RULES, lastnames=("Rega",), whitelist=("Rega",))) == []


def test_an_imported_protected_string_is_checked_too() -> None:
    errors = check_rules(
        ScrubRules(MANDATORY_RULES, lastnames=("Vortag",), protected=("am Vortag",))
    )
    assert [e.code for e in errors] == [ScrubImportErrorCode.PROTECTED_ALTERED]

"""Fixtures for the scrubber's unit tests (sw-design.md §19).

The rule sets are built from the committed fixtures in
`tests/fixtures/scrub/hazards/`, never from a real list.
"""

from pathlib import Path

import pytest

from ra2.domain.scrub import (
    ListKind,
    NameListFile,
    RegexRuleFile,
    Scrubber,
    ScrubRules,
    parse_name_list,
    parse_regex_rules,
)
from ra2.domain.scrub_mandatory import MANDATORY_RULES

HAZARDS = Path(__file__).resolve().parents[2] / "fixtures" / "scrub" / "hazards"


def fixture_bytes(name: str) -> bytes:
    return (HAZARDS / name).read_bytes()


def name_list(kind: ListKind, name: str) -> NameListFile:
    parsed = parse_name_list(kind, fixture_bytes(name))
    assert isinstance(parsed, NameListFile), parsed
    return parsed


def rule_file(name: str = "s04_rules.toml") -> RegexRuleFile:
    parsed = parse_regex_rules(fixture_bytes(name))
    assert isinstance(parsed, RegexRuleFile), parsed
    return parsed


@pytest.fixture
def full_rules() -> ScrubRules:
    """Mandatory + the fixture rules + all three fixture lists."""
    rules = rule_file()
    return ScrubRules(
        regex_rules=(*MANDATORY_RULES, *rules.rules),
        firstnames=name_list(ListKind.FIRSTNAME, "s01_firstnames.txt").entries,
        lastnames=name_list(ListKind.LASTNAME, "s02_lastnames.txt").entries,
        whitelist=name_list(ListKind.WHITELIST, "s03_whitelist.txt").entries,
        protected=rules.protected,
    )


@pytest.fixture
def scrubber(full_rules: ScrubRules) -> Scrubber:
    return Scrubber(full_rules)


@pytest.fixture
def mandatory_only() -> Scrubber:
    return Scrubber(ScrubRules(MANDATORY_RULES))

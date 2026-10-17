"""Counting a freeze's replacements (sw-design.md §19.7).

These counts are the import report's scrubbing table: one row per rule that
ran, zero-hit rules included, so the analyst always sees every rule.
"""

import pytest

from ra2.domain.scrub import (
    BOTH_LISTS_RULE_ID,
    FIRSTNAME_RULE_ID,
    LASTNAME_RULE_ID,
    MOST_HIT_FLOOR,
    RuleSource,
    Scrubber,
    ScrubCounter,
    ScrubRules,
)
from ra2.domain.scrub_mandatory import MANDATORY_RULES

pytestmark = pytest.mark.unit


def test_every_rule_has_a_row_even_with_no_hits(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber)
    counter.add("r1", scrubber.scrub("nichts zu ersetzen"))
    tally = counter.tally()
    assert [row.rule_id for row in tally.rules] == [
        "license-plate",
        "phone",
        "email",
        "iban-ch",
        "ahv",
        "date",
        FIRSTNAME_RULE_ID,
        LASTNAME_RULE_ID,
        BOTH_LISTS_RULE_ID,
    ]
    assert all(row.hits == 0 and row.records == 0 for row in tally.rules)
    assert (tally.records, tally.records_changed) == (1, 0)


def test_hits_add_up_and_records_count_once(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber)
    counter.add("r1", scrubber.scrub("079 123 45 67 und 044 123 45 67"))
    counter.add("r2", scrubber.scrub("079 123 45 67"))
    counter.add("r3", scrubber.scrub("keine Nummer"))
    phone = next(row for row in counter.tally().rules if row.rule_id == "phone")
    assert (phone.hits, phone.records, phone.source) == (3, 2, RuleSource.MANDATORY)


def test_two_texts_of_one_record_count_it_once(scrubber: Scrubber) -> None:
    """A record's narrative and its `UnfHergangTextAnonym` cell."""
    counter = ScrubCounter(scrubber)
    counter.add("r1", scrubber.scrub("079 123 45 67"))
    counter.add("r1", scrubber.scrub("Tel. 044 123 45 67"))
    tally = counter.tally()
    phone = next(row for row in tally.rules if row.rule_id == "phone")
    assert (phone.hits, phone.records) == (2, 1)
    assert (tally.records, tally.records_changed) == (1, 1)


def test_name_rows_exist_only_for_the_lists_that_were_imported() -> None:
    scrubber = Scrubber(ScrubRules(MANDATORY_RULES, lastnames=("Meier",)))
    rows = [row.rule_id for row in ScrubCounter(scrubber).tally().rules]
    assert rows == ["license-plate", "phone", "email", LASTNAME_RULE_ID]


def test_the_most_hit_table_names_only_entries_at_or_above_the_floor(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber)
    for i in range(MOST_HIT_FLOOR):
        counter.add(f"m{i}", scrubber.scrub("Herr Meier"))
    for i in range(MOST_HIT_FLOOR - 1):
        counter.add(f"b{i}", scrubber.scrub("Frau Brunner"))
    assert counter.tally().entry_hits == (("meier", MOST_HIT_FLOOR),)


def test_the_most_hit_table_is_ordered_by_hits_then_name(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber)
    for i in range(12):
        counter.add(f"a{i}", scrubber.scrub("Rossi und Dupont"))
    for i in range(15):
        counter.add(f"b{i}", scrubber.scrub("Meier"))
    assert counter.tally().entry_hits == (("meier", 15), ("dupont", 12), ("rossi", 12))

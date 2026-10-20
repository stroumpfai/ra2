"""What the dry run keeps to show what was replaced (sw-design.md §19.7, SD70)."""

import pytest

import ra2.domain.scrub as scrub_module
from ra2.domain.scrub import (
    EXAMPLE_CONTEXT_CHARS,
    EXAMPLES_PER_VALUE,
    Scrubber,
    ScrubCounter,
    ScrubRuleExamples,
)

pytestmark = pytest.mark.unit


def _add(counter: ScrubCounter, scrubber: Scrubber, key: str, text: str) -> None:
    counter.add(key, scrubber.scrub(text), text)


def _rule(counter: ScrubCounter, rule_id: str) -> ScrubRuleExamples:
    return next(r for r in counter.tally().examples if r.rule_id == rule_id)


def test_the_context_is_cut_from_the_scrubbed_text(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber, collect_examples=True)
    _add(counter, scrubber, "r1", "Herr Meier rief 079 123 45 67 an.")
    (value,) = _rule(counter, "phone").values
    (example,) = value.examples
    assert example.placeholder == "<Phone_1>"
    assert example.matched == "079 123 45 67"
    # The name beside the phone is its placeholder, never itself.
    assert example.before == "Herr <Lastname_1> rief"
    assert example.after == "an."


def test_the_span_is_the_original_not_the_transliterated_entry(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber, collect_examples=True)
    _add(counter, scrubber, "r1", "Herr MEIER war da")
    values = [v for rule in counter.tally().examples for v in rule.values]
    assert [v.value for v in values] == ["MEIER"]


def test_a_value_is_one_group_however_it_is_cased(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber, collect_examples=True)
    _add(counter, scrubber, "r1", "Herr Meier")
    _add(counter, scrubber, "r2", "Herr MEIER und Meier")
    values = [v for rule in counter.tally().examples for v in rule.values]
    assert [(v.value, v.hits, v.records) for v in values] == [("Meier", 3, 2)]


def test_spellings_sharing_a_placeholder_share_a_row(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber, collect_examples=True)
    _add(counter, scrubber, "r1", "079 123 45 67")
    _add(counter, scrubber, "r2", "079-123-45-67")
    (value,) = _rule(counter, "phone").values
    assert (value.value, value.hits, value.records) == ("079 123 45 67", 2, 2)


def test_a_counter_told_no_original_collects_nothing(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber, collect_examples=True)
    counter.add("r1", scrubber.scrub("079 123 45 67"))
    assert all(not r.values for r in counter.tally().examples)


def test_three_snippets_per_value_and_the_rest_are_counted(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber, collect_examples=True)
    for i in range(EXAMPLES_PER_VALUE + 1):
        _add(counter, scrubber, f"r{i}", "079 123 45 67")
    (value,) = _rule(counter, "phone").values
    assert value.hits == EXAMPLES_PER_VALUE + 1
    assert [e.record_key for e in value.examples] == ["r0", "r1", "r2"]


def test_values_past_the_cap_are_counted_not_listed(
    scrubber: Scrubber, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scrub_module, "MAX_VALUES_PER_RULE", 2)
    counter = ScrubCounter(scrubber, collect_examples=True)
    for i in range(4):
        _add(counter, scrubber, f"r{i}", f"079 123 45 6{i}")
    _add(counter, scrubber, "r9", "079 123 45 63")
    rule = _rule(counter, "phone")
    assert len(rule.values) == 2
    assert rule.other_hits == 3
    phone = next(r for r in counter.tally().rules if r.rule_id == "phone")
    assert sum(v.hits for v in rule.values) + rule.other_hits == phone.hits


def test_examples_add_up_to_the_counts_for_every_rule(scrubber: Scrubber) -> None:
    counter = ScrubCounter(scrubber, collect_examples=True)
    _add(counter, scrubber, "r1", "Herr Meier, 079 123 45 67, a@b.ch")
    _add(counter, scrubber, "r2", "Frau Brunner und Meier")
    tally = counter.tally()
    assert [r.rule_id for r in tally.examples] == [r.rule_id for r in tally.rules]
    for count, rule in zip(tally.rules, tally.examples, strict=True):
        assert sum(v.hits for v in rule.values) + rule.other_hits == count.hits


def test_collection_off_leaves_the_tally_as_it_was(scrubber: Scrubber) -> None:
    texts = ["Herr Meier 079 123 45 67", "Frau Brunner"]
    plain, collecting = ScrubCounter(scrubber), ScrubCounter(scrubber, collect_examples=True)
    for i, text in enumerate(texts):
        _add(plain, scrubber, f"r{i}", text)
        _add(collecting, scrubber, f"r{i}", text)
    assert plain.tally().examples == ()
    assert plain.tally().rules == collecting.tally().rules
    assert plain.tally().entry_hits == collecting.tally().entry_hits


@pytest.mark.parametrize("text", ["079 123 45 67", "079 123 45 67 ", " 079 123 45 67"])
def test_a_hit_at_either_end_has_a_short_empty_window(scrubber: Scrubber, text: str) -> None:
    counter = ScrubCounter(scrubber, collect_examples=True)
    _add(counter, scrubber, "r1", text)
    (example,) = _rule(counter, "phone").values[0].examples
    assert example.before == "" and example.after == ""


def test_the_window_is_bounded_and_one_line(scrubber: Scrubber) -> None:
    filler = "wort\n" * 40
    counter = ScrubCounter(scrubber, collect_examples=True)
    _add(counter, scrubber, "r1", f"{filler}079 123 45 67\n\n{filler}")
    (example,) = _rule(counter, "phone").values[0].examples
    assert len(example.before) <= EXAMPLE_CONTEXT_CHARS
    assert len(example.after) <= EXAMPLE_CONTEXT_CHARS
    assert "\n" not in example.before + example.after


def test_the_repr_does_not_carry_the_personal_data(scrubber: Scrubber) -> None:
    result = scrubber.scrub("079 123 45 67")
    assert "079" not in repr(result.hits)
    counter = ScrubCounter(scrubber, collect_examples=True)
    counter.add("r1", result, "079 123 45 67")
    assert "079" not in repr(counter.tally().examples)

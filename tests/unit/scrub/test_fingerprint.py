"""The rule-set fingerprint (sw-design.md §19.4): stable, and sensitive to
everything that changes what a corpus holds, and to nothing else."""

from dataclasses import replace

import pytest

from ra2.domain.scrub import ScrubRules, compute_rules_fingerprint

pytestmark = pytest.mark.unit


def test_the_same_rules_hash_the_same_way(full_rules: ScrubRules) -> None:
    assert compute_rules_fingerprint(full_rules) == compute_rules_fingerprint(full_rules)
    assert len(compute_rules_fingerprint(full_rules)) == 64


def test_a_list_hashes_as_a_set(full_rules: ScrubRules) -> None:
    """Reordering a list, or adding a spelling of an entry it already has,
    scrubs nothing differently."""
    reordered = replace(full_rules, lastnames=(*reversed(full_rules.lastnames), "MUELLER"))
    assert compute_rules_fingerprint(reordered) == compute_rules_fingerprint(full_rules)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: replace(r, lastnames=(*r.lastnames, "Zgraggen")),
        lambda r: replace(r, firstnames=r.firstnames[1:]),
        lambda r: replace(r, whitelist=(*r.whitelist, "Fink")),
        lambda r: replace(r, protected=(*r.protected, "Tempo 50")),
        lambda r: replace(r, regex_rules=r.regex_rules[:-1]),
        lambda r: replace(
            r,
            regex_rules=(
                *r.regex_rules[:-1],
                replace(r.regex_rules[-1], pattern=r.regex_rules[-1].pattern + "x"),
            ),
        ),
        lambda r: replace(
            r,
            regex_rules=(
                *r.regex_rules[:-1],
                replace(r.regex_rules[-1], tag="When"),
            ),
        ),
    ],
)
def test_anything_that_changes_an_outcome_changes_the_hash(full_rules: ScrubRules, change) -> None:  # type: ignore[no-untyped-def]
    assert compute_rules_fingerprint(change(full_rules)) != compute_rules_fingerprint(full_rules)


def test_a_description_is_not_part_of_the_hash(full_rules: ScrubRules) -> None:
    last = full_rules.regex_rules[-1]
    reworded = replace(
        full_rules,
        regex_rules=(*full_rules.regex_rules[:-1], replace(last, description="anders")),
    )
    assert compute_rules_fingerprint(reworded) == compute_rules_fingerprint(full_rules)

"""`domain.mismatch.tally` — the only arithmetic phase 5 contains
(sw-design.md §17.4, mvp-spec.md §12).

Small, pure, and carrying one rule that is easy to get wrong in a way nobody
notices: **a stored tag the enum does not name is counted, never dropped**
(`SD24`, §17.5). A tally that omitted those rows would report "of 40 reviewed"
over 38, and 38 looks exactly as plausible as 40.
"""

import pytest

from ra2.domain.mismatch import OTHER_TAG, MismatchTag, ReviewTally, tally

pytestmark = pytest.mark.unit


def test_the_spec_example_comes_out_of_the_spec_numbers():
    """mvp-spec.md §12, verbatim: "of 40 reviewed, 32 hallucination, 8 record
    error"."""
    result = tally({MismatchTag.HALLUCINATION: 32, MismatchTag.STRUCTURED_DATA_ERROR: 8})

    assert result.reviewed == 40
    assert result.counts[MismatchTag.HALLUCINATION] == 32
    assert result.counts[MismatchTag.STRUCTURED_DATA_ERROR] == 8
    #: The third tag is present at zero rather than absent — a renderer must
    #: not have to guess whether a missing key means "none" or "not counted".
    assert result.counts[MismatchTag.UNCLEAR] == 0


def test_every_tag_of_the_vocabulary_has_a_bucket_even_when_unused():
    """`ReviewTally.counts` always carries all three, so no renderer can
    `KeyError` on a tag nobody has used yet."""
    assert set(tally({}).counts) == set(MismatchTag)
    assert set(tally({MismatchTag.UNCLEAR: 1}).counts) == set(MismatchTag)


def test_an_unknown_tag_is_counted_under_other_and_the_total_still_adds_up():
    """**The headline test of this module** (`SD24`, §17.5, R7).

    Nothing in the MVP writes such a value — the wire is closed and answers
    422 — so this is exercised by writing the raw string, which is honest about
    being a synthetic guarantee. What it guards is real: the column is open by
    design, and the day a fourth tag exists this function must not quietly
    shrink the denominator.
    """
    result = tally(
        {
            MismatchTag.HALLUCINATION: 30,
            "fourth_thing": 2,
            None: 8,
        }
    )

    assert result.other == 2
    assert result.reviewed == 32, "the unknown tag is reviewed work, and is counted as such"
    assert result.untagged == 8
    assert result.total == 40
    #: And it does not land in any named bucket on the way.
    assert sum(result.counts.values()) == 30


def test_an_empty_input_is_a_zero_tally_rather_than_a_raise():
    """Unlike `domain/stats.py`'s `macro`, and for the opposite reason: there
    is nothing dishonest about "0 reviewed", and a run with no mismatches is a
    *good* result the screen has to be able to render."""
    result = tally({})

    assert result == ReviewTally(
        total=0,
        reviewed=0,
        untagged=0,
        counts=result.counts,
        other=0,
    )
    assert all(count == 0 for count in result.counts.values())


def test_none_and_the_empty_string_are_both_untagged():
    """Nothing writes `""` — `set_tag` clears to `None` — but the repository's
    filter treats it as untagged too, and the two have to agree or a row
    appears in the list that the strip did not count."""
    assert tally({None: 3, "": 2}).untagged == 5
    assert tally({None: 3, "": 2}).reviewed == 0
    assert tally({None: 3, "": 2}).other == 0


def test_the_two_identities_hold_over_a_mixed_input():
    """The pair §17.4 states, asserted rather than assumed:

    sum(counts.values()) + other == reviewed
    reviewed + untagged          == total
    """
    result = tally(
        {
            MismatchTag.HALLUCINATION: 11,
            MismatchTag.STRUCTURED_DATA_ERROR: 5,
            MismatchTag.UNCLEAR: 3,
            "fourth_thing": 1,
            "fifth_thing": 2,
            None: 7,
            "": 1,
        }
    )

    assert sum(result.counts.values()) + result.other == result.reviewed
    assert result.reviewed + result.untagged == result.total
    assert result.total == 30
    assert result.other == 3


def test_the_other_bucket_is_not_a_tag_anybody_can_write():
    """`OTHER_TAG` is a bucket, not a vocabulary word (§17.5).

    The asymmetry only holds if it is unwritable: were it a `MismatchTag`
    member, a control would eventually offer it, and "other" is not a
    judgement — it is the absence of one this codebase can name.
    """
    assert OTHER_TAG not in {tag.value for tag in MismatchTag}
    #: A row that somehow stored the literal string still lands in the bucket
    #: rather than in a named count.
    result = tally({OTHER_TAG: 4})
    assert result.other == 4
    assert sum(result.counts.values()) == 0


def test_the_counts_mapping_cannot_be_edited_by_a_renderer():
    """A strip is assembled by walking these buckets, which is exactly where
    somebody would be tempted to fold two together in place — and the identity
    above is what the strip is asserted on."""
    result = tally({MismatchTag.UNCLEAR: 2})
    with pytest.raises(TypeError):
        result.counts[MismatchTag.UNCLEAR] = 99  # type: ignore[index]

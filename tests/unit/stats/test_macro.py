"""`stats.macro` and `stats.macro_interval` — mvp-spec.md §11.5's **equal
weight**, and P4-D1's propagated interval."""

import pytest

from ra2.domain.stats import Interval, macro, macro_interval, wilson


def test_macro_is_the_unweighted_mean():
    assert macro([0.6, 0.8]) == pytest.approx(0.7)


def test_macro_does_not_weight_by_n():
    """§11.5: "a feature with 4 978 cases does not outvote one with 1 611".

    Weighting by `n` is the natural-looking mistake — it is what pooling the
    counts would do silently — and it would make a corpus-wide feature decide
    the ranking on its own.
    """
    # Same two values; the one with far more evidence is the low one.
    assert macro([0.5, 0.9]) == pytest.approx(0.7)


def test_macro_over_nothing_raises_rather_than_returning_zero():
    """§16.4. There is no mean of nothing, and a `0.0` here prints as a model
    that scored zero — which is a measurement, not an absence."""
    with pytest.raises(ValueError, match="no features"):
        macro([])


def test_macro_interval_brackets_the_macro():
    intervals = [wilson(1551, 1842), wilson(1826, 2004), wilson(1212, 1611)]
    combined = macro_interval(intervals)
    centre = macro([(i.low + i.high) / 2 for i in intervals])
    assert combined.low <= centre <= combined.high


def test_macro_interval_is_narrower_than_its_widest_input():
    """Averaging independent estimates buys evidence. An interval that grew
    would mean the combination lost information."""
    intervals = [wilson(1551, 1842), wilson(1826, 2004), wilson(1212, 1611)]
    combined = macro_interval(intervals)
    widest = max(i.high - i.low for i in intervals)
    assert (combined.high - combined.low) < widest


def test_macro_interval_sums_the_labelled_cases():
    """`n` on the macro answers "how much evidence is behind this", and is
    never used as a denominator (P4-D1)."""
    combined = macro_interval([wilson(1551, 1842), wilson(1826, 2004)])
    assert combined.n == 1842 + 2004


def test_macro_interval_stays_inside_zero_and_one():
    combined = macro_interval([wilson(5, 5), wilson(4, 5)])
    assert 0.0 <= combined.low <= combined.high <= 1.0


def test_macro_interval_over_nothing_raises():
    with pytest.raises(ValueError, match="no features"):
        macro_interval([])


def test_macro_interval_is_not_a_wilson_over_pooled_counts():
    """**P4-D1's whole point.** Pooling would weight by `n`, which is what
    equal weight refuses — and it would do it invisibly, producing a number
    that looks like every other Wilson bound on the page.

    Two features, wildly different `n`, same proportion in the small one and a
    different one in the large one: the pooled interval sits near the large
    feature's value, the propagated one near the unweighted mean.
    """
    small = wilson(90, 100)  # 0.90, little evidence
    large = wilson(5000, 10_000)  # 0.50, lots of evidence
    propagated = macro_interval([small, large])
    pooled = wilson(90 + 5000, 100 + 10_000)  # ~0.504

    unweighted_centre = 0.70
    propagated_centre = (propagated.low + propagated.high) / 2
    pooled_centre = (pooled.low + pooled.high) / 2
    assert abs(propagated_centre - unweighted_centre) < 0.02
    assert abs(pooled_centre - unweighted_centre) > 0.15


def test_a_single_feature_macro_interval_is_close_to_that_feature():
    """Degenerate but real: an evaluation with one labelled feature."""
    only = wilson(1551, 1842)
    combined = macro_interval([only])
    assert combined.low == pytest.approx(only.low, abs=1e-9)
    assert combined.high == pytest.approx(only.high, abs=1e-9)


def test_an_empty_interval_input_does_not_crash_the_macro():
    """A feature with `n = 0` should never reach here — it produces no `score`
    rows at all (§8.6) — but the arithmetic must not explode if one does."""
    combined = macro_interval([Interval(low=0.0, high=1.0, n=0), wilson(900, 1000)])
    assert 0.0 <= combined.low <= combined.high <= 1.0

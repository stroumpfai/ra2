"""`stats.wilson` — mvp-spec.md §11.4, `D4`.

Chosen over the normal approximation "for correct behaviour at small n and
near 0/1, where the normal approximation fails", so those are the cases with
tests rather than the comfortable middle.
"""

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ra2.domain.stats import EMPTY_INTERVAL, WILSON_Z_95, Interval, wilson


def test_zero_observations_is_the_empty_interval_not_a_measured_zero():
    """§16.4: `n = 0` is `[0, 1]` — everything is still possible.

    `Interval(0.0, 0.0, 0)` would read as *certainly zero*, which is how a
    feature nobody measured comes to look like a model that failed.
    """
    assert wilson(0, 0) == EMPTY_INTERVAL
    assert Interval(low=0.0, high=1.0, n=0) == EMPTY_INTERVAL


def test_zero_observations_does_not_divide_by_zero():
    """The obvious implementation raises here, and the caller is a scoring
    pass that must not die on a feature with no labelled cases."""
    assert wilson(0, 0).n == 0


def test_the_interval_carries_its_own_n():
    """§11.4: "every metric is rendered with its **n** and its interval".

    They travel together so a renderer cannot be handed one without the other.
    """
    assert wilson(1551, 1842).n == 1842


def test_all_successes_does_not_reach_one():
    """`p = 1` is where the normal approximation gives `[1, 1]` — a claim of
    certainty from 5 observations. Wilson's upper bound touches 1 but its
    lower bound stays honest, which is the whole reason `D4` chose it."""
    interval = wilson(5, 5)
    assert interval.high == pytest.approx(1.0, abs=1e-9)
    assert interval.low < 0.7, "5/5 is not strong evidence and must not look like it"


def test_no_successes_does_not_reach_zero():
    """The mirror case: `0/5` is not proof of impossibility."""
    interval = wilson(0, 5)
    assert interval.low == pytest.approx(0.0, abs=1e-9)
    assert interval.high > 0.3


def test_a_larger_sample_narrows_the_interval():
    """The same proportion, ten times the evidence, must say more."""
    small = wilson(42, 50)
    large = wilson(420, 500)
    assert (large.high - large.low) < (small.high - small.low)


@given(
    n=st.integers(min_value=1, max_value=100_000),
    fraction=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=400)
def test_bounds_stay_inside_zero_and_one(n: int, fraction: float) -> None:
    """A probability rendered as `1.0000000000000002` is a bug report.

    The closed form can stray a hair outside `[0, 1]` through floating point at
    extreme `p`, so the clamp is asserted rather than assumed.
    """
    successes = round(fraction * n)
    interval = wilson(successes, n)
    assert 0.0 <= interval.low <= 1.0
    assert 0.0 <= interval.high <= 1.0
    assert interval.low <= interval.high


@given(
    n=st.integers(min_value=1, max_value=100_000),
    fraction=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=400)
def test_the_interval_brackets_the_point_estimate(n: int, fraction: float) -> None:
    """An interval that does not contain its own point estimate is not an
    interval, and it would render as a number sitting outside its own range."""
    successes = round(fraction * n)
    interval = wilson(successes, n)
    point = successes / n
    assert interval.low <= point + 1e-12
    assert point <= interval.high + 1e-12


@given(n=st.integers(min_value=1, max_value=10_000))
@settings(max_examples=200)
def test_the_interval_is_asymmetric_near_the_edges(n: int) -> None:
    """Wilson's defining behaviour: near 0 the interval leans up, near 1 it
    leans down. A symmetric interval there is the normal approximation, i.e.
    the thing `D4` rejected."""
    near_zero = wilson(0, n)
    assert near_zero.low == pytest.approx(0.0, abs=1e-9)
    assert near_zero.high > 0.0


def test_the_z_constant_is_the_two_sided_95_percent_quantile():
    """The whole of what `scipy` would have been imported for (§16.4, F10).

    Checked against the standard normal CDF built from `math.erf`, so the
    constant is verified rather than trusted.
    """
    cdf = 0.5 * (1.0 + math.erf(WILSON_Z_95 / math.sqrt(2.0)))
    assert cdf == pytest.approx(0.975, abs=1e-9)

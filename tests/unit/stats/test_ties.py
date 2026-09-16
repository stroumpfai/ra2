"""`stats.mark_ties` — mvp-spec.md §11.5's "overlapping confidence intervals
are rendered as a tie, **not** as an order".

The rule has one plausible weaker reading — keep the highest point estimate as
`BEST` and mark the overlappers `TIED` — which is what `design/results/
README.md`'s *fixture counts* show and what its own *stated rule* contradicts
(P4-D2). These tests pin the spec-faithful reading.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from ra2.domain.stats import Interval, TiedCell, TieMark, mark_ties


def cell(point: float, low: float, high: float, n: int = 500) -> TiedCell:
    return TiedCell(point=point, interval=Interval(low=low, high=high, n=n))


def test_no_cells_is_no_marks():
    assert mark_ties([]) == ()


def test_one_cell_is_best():
    """Nothing overlaps it, so nothing stops it being best."""
    assert mark_ties([cell(0.8, 0.77, 0.83)]) == (TieMark.BEST,)


def test_a_clear_leader_is_best_and_the_rest_are_neither():
    assert mark_ties([cell(0.90, 0.88, 0.92), cell(0.60, 0.57, 0.63)]) == (
        TieMark.BEST,
        TieMark.NONE,
    )


def test_an_overlapped_leader_is_tied_not_best():
    """**The rule that distinguishes this product from a leaderboard.**

    §11.5: overlapping intervals are a tie, *not* an order. If the leader kept
    `BEST` while an overlapping rival got `TIED`, the render would assert
    exactly the ordering the spec refuses — and it would do it on evidence
    that does not support one.
    """
    marks = mark_ties([cell(0.842, 0.824, 0.858), cell(0.831, 0.813, 0.848)])
    assert marks == (TieMark.TIED, TieMark.TIED)
    assert TieMark.BEST not in marks


def test_only_cells_overlapping_the_leader_are_tied():
    """A cell that overlaps a *tied* cell but not the leader is not tied with
    best — "tied" means tied with the best, not tied with somebody."""
    marks = mark_ties(
        [
            cell(0.90, 0.88, 0.92),  # leader
            cell(0.89, 0.87, 0.91),  # overlaps the leader
            cell(0.86, 0.845, 0.875),  # overlaps #1 but not the leader
        ]
    )
    assert marks == (TieMark.TIED, TieMark.TIED, TieMark.NONE)


def test_touching_intervals_count_as_overlapping():
    """The bounds are estimates. Treating `.80-.85` and `.85-.90` as separated
    would claim a distinction the data does not support."""
    marks = mark_ties([cell(0.875, 0.85, 0.90), cell(0.825, 0.80, 0.85)])
    assert marks == (TieMark.TIED, TieMark.TIED)


def test_identical_cells_are_all_tied():
    """Three models that scored exactly the same rank `1, 1, 1` downstream."""
    same = cell(0.8, 0.77, 0.83)
    assert mark_ties([same, same, same]) == (TieMark.TIED,) * 3


def test_marks_are_returned_positionally():
    """`mark_ties` never reorders: the caller keeps the model correspondence
    it already had, which is why `TiedCell` carries no model identity."""
    marks = mark_ties([cell(0.10, 0.08, 0.12), cell(0.90, 0.88, 0.92)])
    assert marks == (TieMark.NONE, TieMark.BEST)


@given(
    points=st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            st.floats(min_value=0.0, max_value=0.2, allow_nan=False),
        ),
        min_size=1,
        max_size=6,
    )
)
@settings(max_examples=300)
def test_a_non_empty_input_never_marks_everything_none(
    points: list[tuple[float, float]],
) -> None:
    """Somebody is always either best or tied with best. All-`NONE` would
    render a table where no model leads anything, which is never true."""
    cells = [
        cell(point, max(0.0, point - width), min(1.0, point + width)) for point, width in points
    ]
    marks = mark_ties(cells)
    assert set(marks) != {TieMark.NONE}


@given(
    points=st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            st.floats(min_value=0.0, max_value=0.2, allow_nan=False),
        ),
        min_size=1,
        max_size=6,
    )
)
@settings(max_examples=300)
def test_best_and_tied_are_mutually_exclusive(
    points: list[tuple[float, float]],
) -> None:
    """Either exactly one `BEST` and no `TIED`, or at least two `TIED` and no
    `BEST`. A result with both would mean "nobody is separable, and also this
    one is"."""
    cells = [
        cell(point, max(0.0, point - width), min(1.0, point + width)) for point, width in points
    ]
    marks = mark_ties(cells)
    if TieMark.BEST in marks:
        assert marks.count(TieMark.BEST) == 1
        assert TieMark.TIED not in marks
    else:
        assert marks.count(TieMark.TIED) >= 2


@given(
    gap=st.floats(min_value=0.01, max_value=0.4, allow_nan=False),
    low=st.floats(min_value=0.0, max_value=0.4, allow_nan=False),
)
@settings(max_examples=200)
def test_disjoint_cells_are_never_both_tied(gap: float, low: float) -> None:
    """The inverse of the headline rule: separated evidence must separate."""
    first = cell(low + 0.05, low, low + 0.1)
    second = cell(low + 0.1 + gap + 0.05, low + 0.1 + gap, low + 0.2 + gap)
    marks = mark_ties([first, second])
    assert marks.count(TieMark.TIED) == 0

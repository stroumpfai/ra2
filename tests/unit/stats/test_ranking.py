"""`domain.ranking` — mvp-spec.md §11.5, sw-design.md §16.5.

The module exists to make one claim structurally true: every number on the
ranking tab is a function of tab 1's rows. These tests pin the two behaviours
that would break it quietly — a rank that enumerates through a tie, and a
suppressed feature leaking into a macro.
"""

import pytest

from ra2.domain.ids import FeatureId
from ra2.domain.ranking import FeatureCell, rank_models, separating_features
from ra2.domain.stats import Interval, TieMark, wilson


def cell(
    feature: str,
    f1: float,
    n: int = 1000,
    *,
    mark: TieMark = TieMark.NONE,
    suppressed: bool = False,
    width: float | None = None,
) -> FeatureCell:
    interval = (
        Interval(low=max(0.0, f1 - width), high=min(1.0, f1 + width), n=n)
        if width is not None
        else wilson(round(f1 * n), n)
    )
    return FeatureCell(
        feature_id=FeatureId(feature),
        f1=f1,
        interval=interval,
        suppressed=suppressed,
        mark=mark,
    )


def test_a_clear_order_ranks_one_two_three():
    ranked = rank_models(
        {
            "a": [cell("f1", 0.90, width=0.01), cell("f2", 0.90, width=0.01)],
            "b": [cell("f1", 0.70, width=0.01), cell("f2", 0.70, width=0.01)],
            "c": [cell("f1", 0.50, width=0.01), cell("f2", 0.50, width=0.01)],
        }
    )
    assert [(r.model_id, r.rank) for r in ranked] == [("a", 1), ("b", 2), ("c", 3)]


def test_two_tied_leaders_and_a_straggler_rank_one_one_three():
    """**Never `1, 2, 3`.** §11.5 renders overlapping intervals as a tie, not
    as an order; a dense rank would imply the order the spec refuses.

    The gap between rank 1 and rank 3 is the information: two models above,
    so the next distinct rank is 3.
    """
    ranked = rank_models(
        {
            "a": [cell("f1", 0.842, width=0.02)],
            "b": [cell("f1", 0.831, width=0.02)],
            "c": [cell("f1", 0.500, width=0.02)],
        }
    )
    assert [(r.model_id, r.rank) for r in ranked] == [("a", 1), ("b", 1), ("c", 3)]


def test_three_mutually_tied_models_all_rank_one():
    """ "This run does not separate them" is a result, and the ranks say so."""
    ranked = rank_models(
        {
            "a": [cell("f1", 0.80, width=0.05)],
            "b": [cell("f1", 0.81, width=0.05)],
            "c": [cell("f1", 0.79, width=0.05)],
        }
    )
    assert {r.rank for r in ranked} == {1}


def test_ranks_are_stable_when_macros_are_identical():
    """Two models with the same macro must not swap between page loads — the
    order is total, broken on model id."""
    inputs = {
        "zeta": [cell("f1", 0.80, width=0.001)],
        "alpha": [cell("f1", 0.80, width=0.001)],
    }
    first = [r.model_id for r in rank_models(inputs)]
    second = [r.model_id for r in rank_models(inputs)]
    assert first == second == ["alpha", "zeta"]


def test_a_suppressed_feature_is_excluded_from_the_macro():
    """Not averaged as zero, not averaged at its own value — excluded (§16.4).

    Including it as `0.0` is the failure mode: it would drag a model's macro
    down in proportion to how little evidence there was for the feature.
    """
    ranked = rank_models(
        {
            "a": [
                cell("scored", 0.90, width=0.01),
                cell("tiny", 0.10, n=17, suppressed=True, width=0.01),
            ]
        }
    )
    assert ranked[0].macro_f1 == pytest.approx(0.90)


def test_suppressed_features_do_not_count_toward_best_tied_or_worse():
    """`best + tied + worse` is the **scored**-feature count, which is what
    lets the ranking header render "across 7 scored features · 6 unscored"."""
    ranked = rank_models(
        {
            "a": [
                cell("one", 0.9, mark=TieMark.BEST, width=0.01),
                cell("two", 0.8, mark=TieMark.TIED, width=0.01),
                cell("three", 0.7, mark=TieMark.NONE, width=0.01),
                cell("tiny", 0.1, n=17, suppressed=True, mark=TieMark.NONE, width=0.01),
            ]
        }
    )
    row = ranked[0]
    assert (row.best, row.tied, row.worse) == (1, 1, 1)
    assert row.best + row.tied + row.worse == 3


def test_ranking_with_every_feature_suppressed_raises():
    """There is no macro of nothing, and a `0.0` prints as a model that scored
    zero. The caller renders the "nothing scoreable" state instead (§16.7)."""
    with pytest.raises(ValueError, match="nothing to rank"):
        rank_models({"a": [cell("tiny", 0.1, n=17, suppressed=True)]})


def test_separating_features_finds_only_non_overlapping_ones():
    cells = {
        "a": [cell("clear", 0.90, width=0.01), cell("murky", 0.80, width=0.10)],
        "b": [cell("clear", 0.60, width=0.01), cell("murky", 0.78, width=0.10)],
    }
    separating = separating_features(cells)
    assert [s.feature_id for s in separating] == ["clear"]
    assert separating[0].leader_model_id == "a"
    assert separating[0].delta == pytest.approx(0.30)


def test_separating_features_can_be_led_by_the_runner_up():
    """The design's own case: "the only feature where qwen3 clears mistral".

    The overall leader does not lead everywhere, and a `separating` list that
    assumed it would would silently report the wrong model.
    """
    cells = {
        # macro 0.825 — ahead overall, but beaten on `odd_one`.
        "leader": [
            cell("macro_driver", 0.95, width=0.01),
            cell("odd_one", 0.70, width=0.01),
        ],
        "rival": [cell("macro_driver", 0.70, width=0.01), cell("odd_one", 0.90, width=0.01)],
    }
    ranked = rank_models(cells)
    assert ranked[0].model_id == "leader"
    by_feature = {s.feature_id: s.leader_model_id for s in separating_features(cells)}
    assert by_feature == {"macro_driver": "leader", "odd_one": "rival"}


def test_separating_features_is_empty_when_the_leaders_overlap_everywhere():
    """A result, not a gap — the verdict banner is composed from exactly
    this."""
    cells = {
        "a": [cell("f1", 0.80, width=0.05), cell("f2", 0.70, width=0.05)],
        "b": [cell("f1", 0.79, width=0.05), cell("f2", 0.71, width=0.05)],
    }
    assert separating_features(cells) == ()


def test_a_suppressed_feature_separates_nothing():
    """A feature nobody could measure cannot distinguish two models, however
    far apart the point estimates happen to look."""
    cells = {
        "a": [
            cell("scored", 0.8, width=0.05),
            cell("tiny", 0.99, n=17, suppressed=True, width=0.001),
        ],
        "b": [
            cell("scored", 0.79, width=0.05),
            cell("tiny", 0.01, n=17, suppressed=True, width=0.001),
        ],
    }
    assert separating_features(cells) == ()


def test_one_model_separates_from_nobody():
    """A single-model evaluation is a legitimate run; it just answers no
    ranking question. Not an error."""
    assert separating_features({"only": [cell("f1", 0.8)]}) == ()


def test_separating_features_are_ordered_by_margin():
    cells = {
        "a": [cell("big", 0.90, width=0.01), cell("small", 0.80, width=0.01)],
        "b": [cell("big", 0.50, width=0.01), cell("small", 0.75, width=0.01)],
    }
    assert [s.feature_id for s in separating_features(cells)] == ["big", "small"]

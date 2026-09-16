# FROZEN (types and signatures) — see CONTRACTS.md
"""Goal 4 — which model to pick, and where the evidence does not separate them
(mvp-spec.md §11.5, sw-design.md §16.5).

`design/results/README.md` states the invariant this module exists to keep:

> Every number on this tab is derived from tab 1's scored rows — nothing here
> is independent... if the two disagree, Ranking is wrong by construction.

So ranking is **not a table, not a cache and not a materialised view**. It is
two pure functions over the same `score` rows the extraction tab reads, and a
function cannot disagree with its own input.

That is enforced structurally rather than by review: `domain/` may import
stdlib and `pydantic` and nothing else in `ra2/` (sw-design.md §1.1,
`import-linter`), so this module **cannot** reach a session, a repository or a
second source of numbers even if an agent wanted it to. `.importlinter` needs
no new contract for phase 4, which is the sign the layer rule was drawn in the
right place.

**Latency, VRAM and presence rate are reported, never scored.** The design's
own rule 4 — "the tie-breaker you apply, not one the tool applies" — covers the
first two. The presence figure joins them (`SD20`): mvp-spec.md §11.2 is
unambiguous that presence has no independent gold label, and §11.3's reasoning
applies to it directly, since a model that flags everything present maximises
presence rate. None of the three appears in this module's signatures at all,
which is the strongest available statement that none of them ranks anything.

Pure — no SQLAlchemy, no session (sw-design.md §16.8).

**M27 freezes the types and the signatures. S1 writes the bodies.**
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ra2.domain.ids import FeatureId
from ra2.domain.stats import Interval, TieMark, macro, macro_interval

__all__ = [
    "FeatureCell",
    "ModelRanking",
    "SeparatingFeature",
    "rank_models",
    "separating_features",
]


@dataclass(frozen=True, slots=True)
class FeatureCell:
    """One model's F1 on one feature — a cell of the extraction tab's table.

    This is the *only* input either function takes, which is how "nothing here
    is independent" is made true rather than promised.

    A cell whose feature is suppressed is passed in with `suppressed=True`
    rather than omitted, so that "how many features were there" and "how many
    could be scored" are both answerable — the ranking header renders both
    ("macro F1 across 7 scored features", "6 features unscored").
    """

    feature_id: FeatureId
    f1: float
    interval: Interval
    suppressed: bool
    mark: TieMark


@dataclass(frozen=True, slots=True)
class ModelRanking:
    """One row of the ranking table.

    `best` / `tied` / `worse` are counts of the `TieMark`s this model carries
    across the **scored** features, so they sum to the scored-feature count for
    every model — a property worth asserting, because a drift there means the
    marks and the macro were computed from different sets.
    """

    model_id: str
    #: **Shared on a tie.** Three models whose macro intervals all overlap rank
    #: `1, 1, 1`; two leaders and one straggler rank `1, 1, 3`. Never
    #: `1, 2, 3` — mvp-spec.md §11.5 renders overlapping intervals as a tie,
    #: not as an order, and a dense `1, 2, 3` would imply the order the spec
    #: refuses to claim.
    rank: int
    macro_f1: float
    interval: Interval
    best: int
    tied: int
    worse: int


@dataclass(frozen=True, slots=True)
class SeparatingFeature:
    """A feature where the two leaders' intervals do **not** overlap.

    The honest content of the ranking tab: usually a short list, sometimes
    empty, and an empty one is the finding — it means this run does not
    separate the models and the answer is "pick on cost".
    """

    feature_id: FeatureId
    leader_model_id: str
    #: Leader minus runner-up, on this feature. Always positive.
    delta: float
    f1_by_model: Mapping[str, float]


def rank_models(cells_by_model: Mapping[str, Sequence[FeatureCell]]) -> tuple[ModelRanking, ...]:
    """The ranking table, in rank order then model order.

    Macro F1 is `stats.macro` over each model's **non-suppressed** cells —
    equal weight, so a feature with 4 978 labelled cases does not outvote one
    with 1 611 (§11.5). A suppressed feature is excluded from the macro *and*
    from the best/tied/worse counts; it is never a zero in either.

    Ranks are assigned by `stats.mark_ties` over the models' macro intervals:
    every model whose interval overlaps the leader's shares rank 1, and the
    next distinct rank is the count of models above it plus one.

    Raises when every feature is suppressed for a model — there is no macro of
    nothing, and a `0.0` there prints as a model that scored zero (§16.4). The
    caller renders the "nothing scoreable" state instead (§16.7).
    """
    scored = {
        model_id: tuple(cell for cell in cells if not cell.suppressed)
        for model_id, cells in cells_by_model.items()
    }
    summaries = [_summarise(model_id, cells) for model_id, cells in sorted(scored.items()) if cells]
    if not summaries:
        raise ValueError("every feature is suppressed: there is nothing to rank")
    # Highest macro first, then model id, so the order is total and stable —
    # two models with identical macros must not swap between page loads.
    summaries.sort(key=lambda summary: (-summary.macro_f1, summary.model_id))

    ranked: dict[str, int] = {}
    remaining = list(summaries)
    while remaining:
        leader = remaining[0]
        # Every model whose macro interval overlaps the leader's SHARES its
        # rank (mvp-spec.md §11.5). The next distinct rank is then the count of
        # models above it plus one — so a tied pair is `1, 1, 3`, never
        # `1, 2, 3`, which would imply the order the spec refuses to claim.
        group = [s for s in remaining if _overlaps(s.interval, leader.interval)]
        rank = len(ranked) + 1
        for member in group:
            ranked[member.model_id] = rank
        remaining = [s for s in remaining if s.model_id not in ranked]

    return tuple(
        ModelRanking(
            model_id=summary.model_id,
            rank=ranked[summary.model_id],
            macro_f1=summary.macro_f1,
            interval=summary.interval,
            best=summary.best,
            tied=summary.tied,
            worse=summary.worse,
        )
        for summary in summaries
    )


def separating_features(
    cells_by_model: Mapping[str, Sequence[FeatureCell]],
) -> tuple[SeparatingFeature, ...]:
    """The features where the top two models are actually distinguishable.

    Ordered by `delta`, descending. Suppressed features never appear: a feature
    nobody could measure separates nothing.

    Returns empty when the leaders overlap everywhere, which is a result and
    not a gap — the verdict banner says "this run does not separate them" from
    exactly this.
    """
    rankings = rank_models(cells_by_model)
    if len(rankings) < 2:
        # One model separates from nobody. Not an error: a single-model
        # evaluation is a legitimate run, it just answers no ranking question.
        return ()
    first, second = rankings[0].model_id, rankings[1].model_id
    by_feature = {
        model_id: {cell.feature_id: cell for cell in cells}
        for model_id, cells in cells_by_model.items()
    }

    separating: list[SeparatingFeature] = []
    for feature_id, leader_cell in by_feature[first].items():
        rival_cell = by_feature[second].get(feature_id)
        if rival_cell is None:
            continue
        # A feature nobody could measure separates nothing.
        if leader_cell.suppressed or rival_cell.suppressed:
            continue
        if _overlaps(leader_cell.interval, rival_cell.interval):
            continue
        ahead = first if leader_cell.f1 >= rival_cell.f1 else second
        separating.append(
            SeparatingFeature(
                feature_id=feature_id,
                leader_model_id=ahead,
                delta=abs(leader_cell.f1 - rival_cell.f1),
                f1_by_model={
                    model_id: cells[feature_id].f1
                    for model_id, cells in by_feature.items()
                    if feature_id in cells and not cells[feature_id].suppressed
                },
            )
        )
    separating.sort(key=lambda row: (-row.delta, row.feature_id))
    return tuple(separating)


@dataclass(frozen=True, slots=True)
class _Summary:
    """One model's macro, computed once and reused by both public functions."""

    model_id: str
    macro_f1: float
    interval: Interval
    best: int
    tied: int
    worse: int


def _summarise(model_id: str, cells: Sequence[FeatureCell]) -> _Summary:
    """Macro and mark counts over one model's **non-suppressed** cells.

    `best + tied + worse` equals the scored-feature count for every model — a
    drift there means the marks and the macro were computed from different
    sets, which is why the ranking header can render both numbers.
    """
    marks = [cell.mark for cell in cells]
    return _Summary(
        model_id=model_id,
        macro_f1=macro([cell.f1 for cell in cells]),
        interval=macro_interval([cell.interval for cell in cells]),
        best=marks.count(TieMark.BEST),
        tied=marks.count(TieMark.TIED),
        worse=marks.count(TieMark.NONE),
    )


def _overlaps(left: Interval, right: Interval) -> bool:
    """Closed-interval overlap — the same rule `stats.mark_ties` applies to a
    feature's cells, applied here to the models' macros."""
    return left.low <= right.high and right.low <= left.high

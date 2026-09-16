# FROZEN (types and signatures) — see CONTRACTS.md
"""The statistics every rendered number carries (mvp-spec.md §11.4, §11.5).

Four functions, and they are the reason this phase has a golden-numbers
fixture. Nothing here raises on a wrong answer: a mis-computed interval or a
mis-marked tie produces no exception, no failing assertion anywhere else, and a
screen full of plausible numbers in the one view the project exists to produce
(sw-design.md §16.4).

- `wilson` — the 95 % score interval. Chosen over the normal approximation
  because it stays correct at small `n` and near 0 or 1, which is exactly where
  this corpus lives (`D4`).
- `suppressed` — `n < floor`, with the floor **passed in** from the evaluation
  (`evaluation.min_cell_count`, §11.4's "configurable per evaluation"). A pure
  function never reads config.
- `mark_ties` — a model is `BEST` only if **no** rival's interval overlaps it;
  the moment one does, every overlapper including the leader is `TIED`.
  "Overlapping confidence intervals are rendered as a tie, **not** as an
  order" (§11.5).
- `macro` — the unweighted mean over **non-suppressed** features. Equal weight,
  deliberately: a feature with 4 978 labelled cases does not outvote one with
  1 611.

**Wilson is written out rather than imported.** `scipy` would be the largest
dependency in the project, added for one closed form and one constant
(§16.4), and `pyproject.toml` gains nothing this phase.

Pure — no SQLAlchemy, no session, no config (sw-design.md §16.8).

**M27 freezes the types and the signatures. S1 writes the bodies.**
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "EMPTY_INTERVAL",
    "WILSON_Z_95",
    "Interval",
    "TieMark",
    "TiedCell",
    "macro",
    "macro_interval",
    "mark_ties",
    "suppressed",
    "wilson",
]

#: The two-sided 95 % normal quantile. The whole of what `scipy` would have
#: been imported for (§16.4).
WILSON_Z_95: Final = 1.959963985


@dataclass(frozen=True, slots=True)
class Interval:
    """A Wilson interval and the `n` it was computed from.

    `n` rides along because mvp-spec.md §11.4 requires every rendered metric to
    carry both — "every metric is rendered with its **n** and its interval" —
    so separating them would mean two values that can be passed to a renderer
    independently and therefore mismatched.

    It is also what makes the zero-observation case representable without a
    sentinel type: `n = 0` is `EMPTY_INTERVAL`, `[0.0, 1.0]`, meaning
    *everything is still possible*. That is a different statement from
    `Interval(0.0, 0.0, n=40)`, which is a real measurement meaning *certainly
    zero*, and conflating the two is how a feature nobody measured comes to
    look like a model that failed.
    """

    low: float
    high: float
    n: int


#: The interval for no observations at all (see `Interval`). Not `(0.0, 0.0)`.
EMPTY_INTERVAL: Final = Interval(low=0.0, high=1.0, n=0)


class TieMark(StrEnum):
    """The design's `.mk` vocabulary (`design/results/README.md`).

    Rendered as three **shapes** — filled, outlined, empty — not three colours:
    the distinction has to survive a greyscale print and a colour-blind reader,
    and `ui/theme.py`'s standing rule is that colour carries only state and
    severity, never a decorative hue (§16.4, plan-phase-4.md §15 F9).
    """

    #: Highest point estimate **and** no rival interval overlaps it.
    BEST = "best"
    #: Overlaps the leader. The leader itself is `TIED` when anything overlaps
    #: it — there is no "best among equals".
    TIED = "tied"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class TiedCell:
    """One model's cell in one feature's row — `mark_ties`'s input.

    Carries no model identity: `mark_ties` returns marks **positionally**, so
    the caller keeps the correspondence it already had and the function cannot
    reorder anything.
    """

    point: float
    interval: Interval


def wilson(successes: int, n: int, *, z: float = WILSON_Z_95) -> Interval:
    """The Wilson score interval for `successes` out of `n`.

    `n = 0` returns `EMPTY_INTERVAL` — never a `ZeroDivisionError`, and never
    `Interval(0.0, 0.0, 0)`, which would read as a measured zero.

    Bounds are clamped into `[0.0, 1.0]`: the closed form can stray a hair
    outside it through floating point at extreme `p`, and a probability
    rendered as `1.0000000000000002` is a bug report.
    """
    if n <= 0:
        return EMPTY_INTERVAL
    proportion = successes / n
    z_squared = z * z
    denominator = 1.0 + z_squared / n
    centre = (proportion + z_squared / (2 * n)) / denominator
    spread = math.sqrt(proportion * (1.0 - proportion) / n + z_squared / (4.0 * n * n))
    margin = (z / denominator) * spread
    return Interval(
        low=max(0.0, centre - margin),
        high=min(1.0, centre + margin),
        n=n,
    )


def suppressed(n: int, floor: int) -> bool:
    """`mvp-spec.md` §11.4's rule: a cell below the floor is not a number.

    The `floor` comes from `evaluation.min_cell_count` and is **passed in** —
    this module reads no config, so a suppression decision is reproducible from
    its two arguments alone, and changing the floor never requires a re-score
    (`SD19`).
    """
    return n < floor


def mark_ties(cells: Sequence[TiedCell]) -> tuple[TieMark, ...]:
    """One mark per cell, **positionally**, per `mvp-spec.md` §11.5.

    `BEST` goes to the highest point estimate **only if** no other cell's
    interval overlaps its own. If any does, that cell and every cell
    overlapping it — the leader included — are `TIED`. Everything else is
    `NONE`.

    Consequences worth stating, because each is a plausible wrong
    implementation that still returns marks:

    - A non-empty input always yields at least one `BEST` **or** at least two
      `TIED`. It never yields all `NONE`.
    - Two cells whose intervals are disjoint are never both `TIED`.
    - Suppressed cells are the caller's problem: they must not be passed in at
      all, because a suppressed cell has no point estimate to compare.
    """
    if not cells:
        return ()
    leader = max(range(len(cells)), key=lambda index: cells[index].point)
    overlapping = [
        index
        for index in range(len(cells))
        if index != leader and _overlaps(cells[index].interval, cells[leader].interval)
    ]
    if not overlapping:
        marks = [TieMark.NONE] * len(cells)
        marks[leader] = TieMark.BEST
        return tuple(marks)
    tied = {leader, *overlapping}
    return tuple(TieMark.TIED if index in tied else TieMark.NONE for index in range(len(cells)))


def _overlaps(left: Interval, right: Interval) -> bool:
    """Closed-interval overlap. Touching at a bound **is** an overlap: the
    bounds are estimates, and treating `.824-.859` and `.859-.871` as separated
    would claim a distinction the data does not support."""
    return left.low <= right.high and right.low <= left.high


def macro(values: Sequence[float]) -> float:
    """The unweighted mean — `mvp-spec.md` §11.5's macro average.

    **Equal weight, not weighted by `n`**, so a feature with 4 978 labelled
    cases does not outvote one with 1 611.

    The caller passes only **non-suppressed** features; a suppressed one is
    excluded from the macro entirely and is never a zero in it. An empty
    sequence **raises** rather than returning `0.0` — there is no mean of
    nothing, and a `0.0` here prints as a model that scored zero (§16.4).
    """
    if not values:
        raise ValueError("macro over no features: there is no mean of nothing")
    return sum(values) / len(values)


def macro_interval(intervals: Sequence[Interval]) -> Interval:
    """The macro average's own interval — **P4-D1**, a decision §16 leaves open.

    A macro F1 is *not* a proportion over a pooled denominator, so it has no
    Wilson interval of its own. Pooling the counts and running `wilson` over
    the totals would weight each feature by its `n` — which is exactly what
    mvp-spec.md §11.5's **equal weight** refuses, and it would do it
    invisibly: the number would look like every other Wilson bound on the page
    while answering a different question.

    So the per-feature uncertainties are **propagated** instead. Each Wilson
    half-width is read back as a standard error (`half / z`), combined as
    independent contributions to an unweighted mean
    (`se_macro = sqrt(sum(se^2)) / k`), and turned back into a 95 % interval.
    Equal weight in, equal weight out.

    Independence across features is an approximation — the same model scored
    two features on overlapping records — and it is the conservative direction
    to be wrong in only if the correlation is positive, which it usually is.
    The honest summary is that this interval says "these models are close", not
    "this model's true macro lies here with 95 % probability", and §11.5 only
    ever uses it for the first: **overlapping intervals render as a tie**.

    `n` on the result is the **summed** labelled-case count across the
    features, because that is what a reader asking "how much evidence is
    behind this" means; it is never used as a denominator.
    """
    if not intervals:
        raise ValueError("macro interval over no features")
    centres = [(interval.low + interval.high) / 2.0 for interval in intervals]
    standard_errors = [
        (interval.high - interval.low) / (2.0 * WILSON_Z_95) for interval in intervals
    ]
    count = len(intervals)
    centre = sum(centres) / count
    combined = math.sqrt(sum(error * error for error in standard_errors)) / count
    margin = WILSON_Z_95 * combined
    return Interval(
        low=max(0.0, centre - margin),
        high=min(1.0, centre + margin),
        n=sum(interval.n for interval in intervals),
    )

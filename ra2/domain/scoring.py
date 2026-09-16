# FROZEN (types and signatures) — see CONTRACTS.md
"""Classification and aggregation (mvp-spec.md §11.1-§11.3, sw-design.md §16).

One record at a time becomes an `Outcome`; a feature's worth of outcomes
becomes `ScoreRow`s. Everything here is pure: the session, the EAV read and the
commit belong to `services/scoring_service.py`.

**`classify` returns `Outcome | None`, and the `None` is the point.** It means
*not a labelled case* — mvp-spec.md §8.6, the sentence sw-design.md §16.2 gives
a table of its own because all three of its plausible wrong readings still
produce numbers. A caller cannot accidentally count a `None`, because there is
nothing there to count.

**Three numbers this module will not produce**, each computable and each a lie:

- a **hallucination rate** (`D1`) — distinguishing a hallucination from a
  misread means adjudicating whether an evidence span supports a value.
  `hallucinated` is a review tag on the mismatch list, reported as a tally.
- a **presence precision / recall / F1** (`D2`, §11.2) — there is no
  independent gold label for presence, and deriving one from Goal 1
  correctness would be circular. Hence `aggregate_goal2`'s rate, cross-tab and
  inconsistency count, and nothing more.
- a **cross-model comparison of discovery rate** (§11.3) — a freely
  hallucinating model wins it. `aggregate_goal3` therefore has no shape that
  admits a second model: the comparison is not merely undrawn, it is
  unrepresentable.

Pure — no SQLAlchemy, no session (sw-design.md §16.8).

**M27 freezes the types and the signatures. S2 writes the bodies.**
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ra2.domain.feature import MatchingRule, ValueType
from ra2.domain.ids import RecordId
from ra2.domain.matching import is_empty, matches
from ra2.domain.stats import wilson

__all__ = [
    "ALL_LANGUAGES",
    "COUNT_METRICS",
    "CrossTab",
    "ExploratoryCase",
    "LabelledCase",
    "Outcome",
    "ScoreMetric",
    "ScoreRow",
    "aggregate_goal1",
    "aggregate_goal2",
    "aggregate_goal3",
    "classify",
]

#: `score.language` for the all-languages row.
#:
#: mvp-spec.md §5 writes the column as `language|NULL`, which cannot carry a
#: composite primary key: SQL treats two NULLs as distinct in a unique
#: constraint, so the schema that looks like it prevents duplicate rows would
#: silently permit them — and "rewrite this feature's rows" would orphan the
#: old ones on every re-score. A sentinel makes the key real (`SD16`).
ALL_LANGUAGES: Final = "*"


class Outcome(StrEnum):
    """mvp-spec.md §11.1's three classes, for one labelled case.

    The vision names a fourth, `hallucinated`. **The MVP cannot compute it**
    and does not pretend to (`D1`): it is a review tag on the mismatch list,
    never a metric, and a report must not present a hallucination rate as if it
    were measured.
    """

    #: Model value non-null and matches the record under the matching rule.
    HIT = "hit"
    #: Model value non-null and does not match. **Produces a `mismatch` row.**
    WRONG = "wrong"
    #: Model value null.
    MISSING = "missing"


class ScoreMetric(StrEnum):
    """Every name a `score` row's `metric` column may hold — closed (`SD18`).

    Closed, because a metric this enum does not name cannot be written, and a
    tab asking for one that does not exist is a lint error in Wave 4 rather
    than a `KeyError` in front of an analyst.

    **Counts ride in the same row shape as rates.** They are recoverable from
    P, R and n in principle — and off by one in practice at small `n`, which is
    where the number matters most — so they are stored (§16.3). `value` holds a
    count as a float for the `COUNT_METRICS`; `ci_low` / `ci_high` are `None`
    there, because a count has no interval.
    """

    # --- Goal 1, rates (mvp-spec.md §11.1) ---
    PRECISION = "precision"
    RECALL = "recall"
    F1 = "f1"
    # --- Goal 1, raw counts: the design's breakdown row ---
    HIT = "hit"
    WRONG = "wrong"
    MISSING = "missing"
    # --- Goal 2 (mvp-spec.md §11.2) ---
    PRESENCE_RATE = "presence_rate"
    FLAG_INCONSISTENCY_RATE = "flag_inconsistency_rate"
    # --- Goal 2, the cross-tab's six cells ---
    HIT_PRESENT = "hit_present"
    HIT_ABSENT = "hit_absent"
    WRONG_PRESENT = "wrong_present"
    WRONG_ABSENT = "wrong_absent"
    MISSING_PRESENT = "missing_present"
    MISSING_ABSENT = "missing_absent"
    # --- Goal 3 (mvp-spec.md §11.3) ---
    DISCOVERY_RATE = "discovery_rate"
    EVIDENCE_SPAN_COUNT = "evidence_span_count"


#: The metrics whose `value` is a count, not a proportion — so `ci_low` and
#: `ci_high` are `None` and a renderer must not reach for an interval.
COUNT_METRICS: Final = frozenset(
    {
        ScoreMetric.HIT,
        ScoreMetric.WRONG,
        ScoreMetric.MISSING,
        ScoreMetric.HIT_PRESENT,
        ScoreMetric.HIT_ABSENT,
        ScoreMetric.WRONG_PRESENT,
        ScoreMetric.WRONG_ABSENT,
        ScoreMetric.MISSING_PRESENT,
        ScoreMetric.MISSING_ABSENT,
        ScoreMetric.EVIDENCE_SPAN_COUNT,
    }
)


@dataclass(frozen=True, slots=True)
class LabelledCase:
    """One record that counts, for one feature and one run.

    By construction this is **already** a labelled case: a record whose source
    column was empty never becomes one (§8.6). `record_value` is therefore
    never empty, and that invariant is what lets the aggregators use
    `len(cases)` as `n` without re-filtering.

    `present_flag` is the model's own claim that the narrative contains the
    feature — `None` when the model did not answer it. It is what Goal 2 reads
    and what Goal 1 ignores.
    """

    record_id: RecordId
    language: str
    outcome: Outcome
    record_value: str
    model_value: str | None
    present_flag: bool | None


@dataclass(frozen=True, slots=True)
class ExploratoryCase:
    """One record's Goal 3 result — no ground truth, so no `Outcome`.

    `evidence_span` is **mandatory whenever `reported` is true** (§11.3, "every
    finding carries its evidence span — mandatory, no exceptions"). A reported
    discovery with no span is a defect the parser records, not a finding this
    module averages.
    """

    record_id: RecordId
    language: str
    reported: bool
    evidence_span: str | None


@dataclass(frozen=True, slots=True)
class ScoreRow:
    """One `score` row, before it reaches a session.

    Mirrors the table exactly — `(language, metric, value, n, ci_low, ci_high)`
    against a `(run_id, feature_id)` the caller already holds — so the
    repository writes it without a translation step that could reorder or
    reinterpret anything.
    """

    language: str
    metric: ScoreMetric
    value: float
    n: int
    ci_low: float | None
    ci_high: float | None


@dataclass(frozen=True, slots=True)
class CrossTab:
    """Goal 1 outcome × the model's presence flag (mvp-spec.md §11.2).

    The cell the design calls "the whole point of the card" is
    `hit_absent`: the model said the text does **not** contain the feature and
    then extracted the record's exact value from it. That is
    self-contradiction, it is automatically countable, and it is a genuine
    quality signal on the flag itself.

    Cases whose `present_flag` is `None` appear in no cell. The totals are
    therefore `<=` the feature's `n`, and the read model says so rather than
    quietly making the rows add up.
    """

    hit_present: int
    hit_absent: int
    wrong_present: int
    wrong_absent: int
    missing_present: int
    missing_absent: int


def classify(
    record_value: str | None,
    model_value: str | None,
    *,
    value_type: ValueType,
    rule: MatchingRule,
) -> Outcome | None:
    """One record's outcome — or `None` for *not a labelled case*.

    `None` when `matching.is_empty(record_value)`. **Not** `MISSING`: the model
    was never asked a question that had an answer, the data has no label, and
    §8.6 excludes the record from the denominator entirely. `MISSING` means the
    record had a value and the model returned none.

    Otherwise `HIT` when `matching.matches`, `WRONG` when the model returned
    something that does not match, `MISSING` when it returned nothing.
    """
    if is_empty(record_value):
        # NOT a labelled case. §8.6: "a record whose column is empty is
        # excluded from that feature's denominator ENTIRELY". Returning
        # `MISSING` here is the wrong answer that still produces numbers — it
        # would inflate the denominator and depress recall for every feature
        # the delivery happens to populate sparsely.
        return None
    if is_empty(model_value):
        return Outcome.MISSING
    return (
        Outcome.HIT
        if matches(record_value, model_value, value_type=value_type, rule=rule)
        else Outcome.WRONG
    )


def aggregate_goal1(cases: Sequence[LabelledCase], *, language: str) -> tuple[ScoreRow, ...]:
    """§11.1's six rows for one `(feature, language)`.

    `precision = hit / (hit + wrong)` · `recall = hit / (hit + wrong + missing)`
    · `F1 = 2PR / (P + R)`, each with its Wilson interval, plus the three raw
    counts (`SD18`).

    `n` is `len(cases)` — the labelled-case count, **not** the corpus size
    (§8.6's consequence: "every reported metric carries its labelled-case
    count"). A zero denominator yields a rate of `0.0` with
    `EMPTY_INTERVAL`'s bounds rather than a `ZeroDivisionError`; whether such a
    cell is shown at all is `stats.suppressed`'s question, asked later and by
    someone else (`SD19`).
    """
    n = len(cases)
    hit = sum(1 for case in cases if case.outcome is Outcome.HIT)
    wrong = sum(1 for case in cases if case.outcome is Outcome.WRONG)
    missing = sum(1 for case in cases if case.outcome is Outcome.MISSING)

    claimed = hit + wrong
    precision = hit / claimed if claimed else 0.0
    recall = hit / n if n else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return (
        # Precision's denominator is what the model CLAIMED, not `n`: "of what
        # it claimed, how much was right" (§11.1). Its interval is over that
        # smaller base, which is why a model that answers rarely gets a wide
        # precision interval and a narrow recall one.
        _rate(language, ScoreMetric.PRECISION, hit, claimed),
        _rate(language, ScoreMetric.RECALL, hit, n),
        _derived_rate(language, ScoreMetric.F1, f1, n),
        _count(language, ScoreMetric.HIT, hit, n),
        _count(language, ScoreMetric.WRONG, wrong, n),
        _count(language, ScoreMetric.MISSING, missing, n),
    )


def aggregate_goal2(cases: Sequence[LabelledCase], *, language: str) -> tuple[ScoreRow, ...]:
    """§11.2's rows for one `(feature, language)`: rate, cross-tab, inconsistency.

    - **presence rate** — the share of labelled cases the model flagged as
      present, with its interval.
    - **the cross-tab's six cells** — as counts (`CrossTab`).
    - **flag inconsistency rate** — `present = false` **and** the extracted
      value matched. Self-contradiction, automatically countable, and the one
      Goal 2 number that is a quality signal rather than a description.

    There is deliberately **no presence precision, recall or F1** (`D2`). They
    need a human-labelled presence subset of ~50 records × features; deriving
    gold presence from Goal 1 correctness would be circular, and the circularity
    would not be visible in the output.
    """
    n = len(cases)
    flagged = [case for case in cases if case.present_flag is not None]
    present = sum(1 for case in flagged if case.present_flag)

    # Cases where the model gave no presence flag appear in NO cell, so the
    # cross-tab totals can be less than `n`. The read model says so rather
    # than quietly making the rows add up (§16.3).
    cross = CrossTab(
        hit_present=_tally(flagged, Outcome.HIT, present_flag=True),
        hit_absent=_tally(flagged, Outcome.HIT, present_flag=False),
        wrong_present=_tally(flagged, Outcome.WRONG, present_flag=True),
        wrong_absent=_tally(flagged, Outcome.WRONG, present_flag=False),
        missing_present=_tally(flagged, Outcome.MISSING, present_flag=True),
        missing_absent=_tally(flagged, Outcome.MISSING, present_flag=False),
    )

    # `present = false` AND the value matched: self-contradiction, and the one
    # Goal 2 number that is a quality signal rather than a description (§11.2).
    # The denominator is the flagged cases, not `n` — a case with no flag
    # cannot contradict itself.
    inconsistent = cross.hit_absent

    return (
        _rate(language, ScoreMetric.PRESENCE_RATE, present, n),
        _rate(
            language,
            ScoreMetric.FLAG_INCONSISTENCY_RATE,
            inconsistent,
            len(flagged),
        ),
        _count(language, ScoreMetric.HIT_PRESENT, cross.hit_present, len(flagged)),
        _count(language, ScoreMetric.HIT_ABSENT, cross.hit_absent, len(flagged)),
        _count(language, ScoreMetric.WRONG_PRESENT, cross.wrong_present, len(flagged)),
        _count(language, ScoreMetric.WRONG_ABSENT, cross.wrong_absent, len(flagged)),
        _count(language, ScoreMetric.MISSING_PRESENT, cross.missing_present, len(flagged)),
        _count(language, ScoreMetric.MISSING_ABSENT, cross.missing_absent, len(flagged)),
    )


def _tally(cases: Sequence[LabelledCase], outcome: Outcome, *, present_flag: bool) -> int:
    return sum(1 for case in cases if case.outcome is outcome and case.present_flag is present_flag)


def aggregate_goal3(cases: Sequence[ExploratoryCase], *, language: str) -> tuple[ScoreRow, ...]:
    """§11.3's two rows for one `(attribute, language)`.

    `discovery_rate` and `evidence_span_count`. There is **no model dimension**
    in this signature and that is the design: "discovery rates are never
    compared between models as a quality signal — a freely hallucinating model
    wins this metric". Exploratory attributes also take no part in the ranking
    and in no Goal 1/2 aggregate.
    """
    n = len(cases)
    reported = sum(1 for case in cases if case.reported)
    spans = sum(1 for case in cases if case.reported and case.evidence_span)
    return (
        _rate(language, ScoreMetric.DISCOVERY_RATE, reported, n),
        _count(language, ScoreMetric.EVIDENCE_SPAN_COUNT, spans, n),
    )


def _rate(language: str, metric: ScoreMetric, successes: int, n: int) -> ScoreRow:
    """A proportion with its Wilson interval — mvp-spec.md §11.4's "every
    metric is rendered with its n and its interval"."""
    interval = wilson(successes, n)
    return ScoreRow(
        language=language,
        metric=metric,
        value=(successes / n) if n else 0.0,
        n=n,
        ci_low=interval.low,
        ci_high=interval.high,
    )


def _derived_rate(language: str, metric: ScoreMetric, value: float, n: int) -> ScoreRow:
    """A rate that is not a raw `successes / n` — precision over its own
    denominator, and F1, which is a ratio of ratios.

    Its interval is Wilson over the value read back as a count. That is an
    approximation for F1 and is the standard one: `design/results/README.md`
    renders "F1 with a Wilson 95 % interval" and there is no closed form for
    the interval of a harmonic mean of two proportions.
    """
    interval = wilson(round(value * n), n)
    return ScoreRow(
        language=language,
        metric=metric,
        value=value,
        n=n,
        ci_low=interval.low,
        ci_high=interval.high,
    )


def _count(language: str, metric: ScoreMetric, value: int, n: int) -> ScoreRow:
    """A raw count. `ci_low`/`ci_high` stay `None` — a count has no interval,
    and a renderer must not reach for one (SD18)."""
    return ScoreRow(
        language=language,
        metric=metric,
        value=float(value),
        n=n,
        ci_low=None,
        ci_high=None,
    )

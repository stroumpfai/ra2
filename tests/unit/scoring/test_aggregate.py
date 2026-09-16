"""`domain.scoring.aggregate_goal1/2/3` — mvp-spec.md §11.1-§11.3.

The headline check is against `design/results/README.md`'s own published
breakdown row, which states every number this function must produce.
"""

from collections.abc import Sequence

import pytest

from ra2.domain.ids import RecordId
from ra2.domain.scoring import (
    ALL_LANGUAGES,
    COUNT_METRICS,
    ExploratoryCase,
    LabelledCase,
    Outcome,
    ScoreMetric,
    ScoreRow,
    aggregate_goal1,
    aggregate_goal2,
    aggregate_goal3,
)


def case(outcome: Outcome, *, present: bool | None = None, language: str = "de") -> LabelledCase:
    return LabelledCase(
        record_id=RecordId("rec"),
        language=language,
        outcome=outcome,
        record_value="3",
        model_value="3",
        present_flag=present,
    )


def by_metric(rows: Sequence[ScoreRow]) -> dict[ScoreMetric, ScoreRow]:
    return {row.metric: row for row in rows}


# --- Goal 1 ----------------------------------------------------------------


def test_goal1_reproduces_the_design_readmes_published_breakdown():
    """`design/results/README.md` §1a, Weather x qwen3:
    ".887/.802/**0.842**/1 477/188/177".

    Every number in that row, from 1 842 hand-built cases. If precision's
    denominator were `n` instead of what the model claimed, or F1 were
    computed from counts instead of from P and R, this is where it shows.
    """
    cases = [case(Outcome.HIT)] * 1477 + [case(Outcome.WRONG)] * 188 + [case(Outcome.MISSING)] * 177
    rows = by_metric(aggregate_goal1(cases, language=ALL_LANGUAGES))
    assert round(rows[ScoreMetric.PRECISION].value, 3) == 0.887
    assert round(rows[ScoreMetric.RECALL].value, 3) == 0.802
    assert round(rows[ScoreMetric.F1].value, 3) == 0.842
    assert rows[ScoreMetric.HIT].value == 1477
    assert rows[ScoreMetric.WRONG].value == 188
    assert rows[ScoreMetric.MISSING].value == 177


def test_precisions_denominator_is_what_the_model_claimed_not_n():
    """§11.1: "of what it claimed, how much was right".

    A model that answers rarely and accurately has high precision and low
    recall; using `n` for both would collapse the distinction the two metrics
    exist to draw.
    """
    cases = [case(Outcome.HIT)] * 10 + [case(Outcome.WRONG)] * 10 + [case(Outcome.MISSING)] * 80
    rows = by_metric(aggregate_goal1(cases, language=ALL_LANGUAGES))
    assert rows[ScoreMetric.PRECISION].value == pytest.approx(0.5)
    assert rows[ScoreMetric.PRECISION].n == 20
    assert rows[ScoreMetric.RECALL].value == pytest.approx(0.1)
    assert rows[ScoreMetric.RECALL].n == 100


def test_the_counts_are_stored_not_back_derived():
    """SD18. They are recoverable from P, R and n in principle — and off by
    one in practice at small `n`, which is where the number matters most."""
    cases = [case(Outcome.HIT)] * 2 + [case(Outcome.WRONG)] * 1
    rows = by_metric(aggregate_goal1(cases, language=ALL_LANGUAGES))
    assert rows[ScoreMetric.HIT].value == 2.0
    assert rows[ScoreMetric.WRONG].value == 1.0
    assert rows[ScoreMetric.MISSING].value == 0.0


def test_counts_carry_no_interval():
    """A count has no interval, and a renderer must not reach for one."""
    rows = aggregate_goal1([case(Outcome.HIT)], language=ALL_LANGUAGES)
    for row in rows:
        if row.metric in COUNT_METRICS:
            assert row.ci_low is None and row.ci_high is None
        else:
            assert row.ci_low is not None and row.ci_high is not None


def test_every_rate_carries_its_interval_and_its_n():
    """§11.4: "every metric is rendered with its **n** and its interval"."""
    rows = aggregate_goal1([case(Outcome.HIT)] * 40, language=ALL_LANGUAGES)
    rates = [row for row in rows if row.metric not in COUNT_METRICS]
    assert rates
    for row in rates:
        assert row.n > 0
        assert row.ci_low is not None and row.ci_high is not None
        assert row.ci_low <= row.value <= row.ci_high


def test_a_model_that_answered_nothing_does_not_divide_by_zero():
    """All `MISSING` means precision has a zero denominator. A scoring pass
    walks a whole corpus and must not die on a model that gave up."""
    rows = by_metric(aggregate_goal1([case(Outcome.MISSING)] * 40, language=ALL_LANGUAGES))
    assert rows[ScoreMetric.PRECISION].value == 0.0
    assert rows[ScoreMetric.F1].value == 0.0


def test_n_is_the_labelled_case_count():
    """§8.6's consequence: "every reported metric carries its **labelled-case
    count**, not just the corpus size"."""
    rows = aggregate_goal1([case(Outcome.HIT)] * 7, language=ALL_LANGUAGES)
    assert {row.n for row in rows if row.metric is not ScoreMetric.PRECISION} == {7}


# --- Goal 2 ----------------------------------------------------------------


def test_goal2_reports_rate_cross_tab_and_inconsistency_and_nothing_else():
    """§11.2 and `D2`. **No presence precision, recall or F1** — there is no
    independent gold label for presence, and deriving one from Goal 1
    correctness would be circular in a way the output would not show."""
    rows = aggregate_goal2([case(Outcome.HIT, present=True)] * 10, language=ALL_LANGUAGES)
    metrics = {row.metric for row in rows}
    assert ScoreMetric.PRESENCE_RATE in metrics
    assert ScoreMetric.FLAG_INCONSISTENCY_RATE in metrics
    assert metrics >= {
        ScoreMetric.HIT_PRESENT,
        ScoreMetric.HIT_ABSENT,
        ScoreMetric.WRONG_PRESENT,
        ScoreMetric.WRONG_ABSENT,
        ScoreMetric.MISSING_PRESENT,
        ScoreMetric.MISSING_ABSENT,
    }
    assert not any("f1" in m.value and m is not ScoreMetric.F1 for m in metrics)


def test_the_cross_tab_reproduces_the_designs_self_contradiction_cell():
    """`design/results/README.md` §2d: hit 2 190 / **114** / 2 304.

    The **114** in `hit x present = false` is the card's whole point: the model
    said the text does not contain the feature and then extracted the record's
    exact value from it.
    """
    cases = (
        [case(Outcome.HIT, present=True)] * 2190
        + [case(Outcome.HIT, present=False)] * 114
        + [case(Outcome.WRONG, present=True)] * 301
        + [case(Outcome.WRONG, present=False)] * 62
        + [case(Outcome.MISSING, present=True)] * 94
        + [case(Outcome.MISSING, present=False)] * 1286
    )
    rows = by_metric(aggregate_goal2(cases, language=ALL_LANGUAGES))
    assert rows[ScoreMetric.HIT_PRESENT].value == 2190
    assert rows[ScoreMetric.HIT_ABSENT].value == 114
    assert rows[ScoreMetric.WRONG_PRESENT].value == 301
    assert rows[ScoreMetric.WRONG_ABSENT].value == 62
    assert rows[ScoreMetric.MISSING_PRESENT].value == 94
    assert rows[ScoreMetric.MISSING_ABSENT].value == 1286


def test_flag_inconsistency_is_the_self_contradiction_cell():
    """§11.2: "cases where `present = false` but the model extracted a value
    that matched. This is self-contradiction and is automatically countable."
    """
    cases = [case(Outcome.HIT, present=False)] * 5 + [case(Outcome.HIT, present=True)] * 95
    rows = by_metric(aggregate_goal2(cases, language=ALL_LANGUAGES))
    assert rows[ScoreMetric.FLAG_INCONSISTENCY_RATE].value == pytest.approx(0.05)


def test_cases_with_no_presence_flag_appear_in_no_cross_tab_cell():
    """So the totals can be less than the feature's `n`, and the read model
    says so rather than quietly making the rows add up (§16.3)."""
    cases = [case(Outcome.HIT, present=True)] * 10 + [case(Outcome.HIT, present=None)] * 5
    rows = by_metric(aggregate_goal2(cases, language=ALL_LANGUAGES))
    cells = sum(
        rows[m].value
        for m in (
            ScoreMetric.HIT_PRESENT,
            ScoreMetric.HIT_ABSENT,
            ScoreMetric.WRONG_PRESENT,
            ScoreMetric.WRONG_ABSENT,
            ScoreMetric.MISSING_PRESENT,
            ScoreMetric.MISSING_ABSENT,
        )
    )
    assert cells == 10
    assert rows[ScoreMetric.PRESENCE_RATE].n == 15


# --- Goal 3 ----------------------------------------------------------------


def test_goal3_reports_a_discovery_rate_and_a_span_count():
    cases = [
        ExploratoryCase(record_id=RecordId("r"), language="de", reported=True, evidence_span="x")
    ] * 41 + [
        ExploratoryCase(record_id=RecordId("r"), language="de", reported=False, evidence_span=None)
    ] * 959
    rows = by_metric(aggregate_goal3(cases, language=ALL_LANGUAGES))
    assert rows[ScoreMetric.DISCOVERY_RATE].value == pytest.approx(0.041)
    assert rows[ScoreMetric.EVIDENCE_SPAN_COUNT].value == 41


def test_a_reported_discovery_without_a_span_is_not_counted_as_evidence():
    """§11.3: "every finding carries its **evidence span** — mandatory, no
    exceptions". A reported discovery with no span is a defect the parser
    records, not a finding to average."""
    cases = [
        ExploratoryCase(record_id=RecordId("r"), language="de", reported=True, evidence_span=None)
    ] * 10
    rows = by_metric(aggregate_goal3(cases, language=ALL_LANGUAGES))
    assert rows[ScoreMetric.DISCOVERY_RATE].value == pytest.approx(1.0)
    assert rows[ScoreMetric.EVIDENCE_SPAN_COUNT].value == 0


def test_goal3_has_no_model_dimension_at_all():
    """§11.3: "discovery rates are **never compared between models** as a
    quality signal — a freely hallucinating model wins this metric."

    The comparison is not merely undrawn: there is no argument, no field and no
    return shape that expresses it.
    """
    import inspect

    signature = inspect.signature(aggregate_goal3)
    assert "model" not in " ".join(signature.parameters)
    assert "model" not in " ".join(f.name for f in ExploratoryCase.__dataclass_fields__.values())

"""Whether the launch honours an `RA2_LLM_PARALLEL_CALLS` entry
(sw-design.md SD40, `plan-model-choice.md` D6).

One case per `ParallelReason`. Every refusal pins **1**: a map entry above
the gated N isn't lowered to the gated N, because that would run at a value
nobody configured (Q5).
"""

from datetime import UTC, datetime

import pytest

from ra2.domain.qualification import (
    GateResult,
    GateVerdict,
    ParallelDecision,
    ParallelReason,
    Qualification,
    QualitySummary,
    parallel_decision,
)

DIGEST = "500a1f067a9f"
OLLAMA = "0.34.0"

QUALITY = QualitySummary(
    records=200,
    reasoning_effort="none",
    macro_f1=0.895,
    macro_f1_low=0.870,
    macro_f1_high=0.905,
    f1_by_language={"de": 0.91, "fr": 0.88, "it": 0.93},
    median_latency_ms=1710,
    ms_per_record=1745.0,
    median_completion_tokens=121,
    entity_fill=0.0,
    parse_failures=0,
)


def _gate(n: int, verdict: GateVerdict) -> GateResult:
    return GateResult(
        n=n,
        records=48,
        noise_band=2,
        serial_on_n_slot_differ=0,
        parallel_differ=0,
        speedup=2.4,
        verdict=verdict,
    )


def _qualification(
    *gates: GateResult, digest: str = DIGEST, ollama_version: str | None = OLLAMA
) -> Qualification:
    return Qualification(
        model_tag="qwen3:8b",
        model_digest=digest,
        ollama_version=ollama_version,
        gpu_name=None,
        ra2_version=None,
        measured_at=datetime(2026, 9, 25, 10, 0, tzinfo=UTC),
        seed_records=200,
        quality=QUALITY,
        gates=gates,
    )


PASSED_AT_2_AND_4 = _qualification(_gate(2, GateVerdict.PASSES), _gate(4, GateVerdict.PASSES))


def _decide(
    mapped: int | None,
    qualification: Qualification | None = PASSED_AT_2_AND_4,
    *,
    digest: str = DIGEST,
    ollama_version: str | None = OLLAMA,
) -> ParallelDecision:
    return parallel_decision(
        mapped=mapped, qualification=qualification, digest=digest, ollama_version=ollama_version
    )


def test_a_gated_entry_applies() -> None:
    assert _decide(4) == ParallelDecision(4, ParallelReason.GATED)
    assert _decide(2) == ParallelDecision(2, ParallelReason.GATED)


@pytest.mark.parametrize("mapped", [None, 1])
def test_an_unmapped_model_runs_serially_whatever_it_passed(mapped: int | None) -> None:
    assert _decide(mapped) == ParallelDecision(1, ParallelReason.NOT_MAPPED)


def test_no_qualification_means_no_gate() -> None:
    assert _decide(4, None) == ParallelDecision(1, ParallelReason.NO_GATE)


def test_a_quality_only_qualification_is_no_gate() -> None:
    assert _decide(4, _qualification()) == ParallelDecision(1, ParallelReason.NO_GATE)


def test_a_re_pull_runs_serially() -> None:
    """Same tag, new weights: the gate described weights that are gone."""
    assert _decide(4, digest="ffffffffffff") == ParallelDecision(1, ParallelReason.DIGEST)


def test_a_different_ollama_version_runs_serially() -> None:
    assert _decide(4, ollama_version="0.35.0") == ParallelDecision(1, ParallelReason.OLLAMA_VERSION)


def test_an_unknown_ollama_version_matches_nothing() -> None:
    """Neither side's `None` is a match: an unknown can't be the same version."""
    assert _decide(4, ollama_version=None).reason is ParallelReason.OLLAMA_VERSION
    unknown = _qualification(_gate(4, GateVerdict.PASSES), ollama_version=None)
    assert _decide(4, unknown).reason is ParallelReason.OLLAMA_VERSION
    assert _decide(4, unknown, ollama_version=None).reason is ParallelReason.OLLAMA_VERSION


def test_parallel_decision_never_runs_above_the_gated_n() -> None:
    """Gated at 2 only, map says 4: pin 1, not 2 (plan-model-choice.md Q5)."""
    gated_at_2 = _qualification(_gate(2, GateVerdict.PASSES), _gate(4, GateVerdict.FAILS_PARALLEL))
    assert gated_at_2.passing_n == 2
    assert _decide(4, gated_at_2) == ParallelDecision(1, ParallelReason.FAILED)
    assert _decide(2, gated_at_2) == ParallelDecision(2, ParallelReason.GATED)


def test_a_model_that_failed_everywhere_runs_serially() -> None:
    failed = _qualification(_gate(4, GateVerdict.FAILS_PARALLEL))
    assert failed.passing_n == 1
    assert _decide(4, failed) == ParallelDecision(1, ParallelReason.FAILED)


def test_server_sensitivity_is_any_gate_where_serial_answers_moved() -> None:
    assert not PASSED_AT_2_AND_4.server_sensitive
    assert _qualification(_gate(4, GateVerdict.FAILS_SERVER)).server_sensitive
    assert _qualification(_gate(4, GateVerdict.FAILS_BOTH)).server_sensitive
    assert not _qualification(_gate(4, GateVerdict.FAILS_PARALLEL)).server_sensitive

"""The parallel-calls gate as one function (sw-design.md SD40,
`plan-parallel-calls.md` §4.1, `plan-model-choice.md` D5).

The gate used to be prose, applied by hand, with scripts that no longer
exist. These tests pin it to the counts those scripts produced
(`docs/choosing-models.md` §5), so the function and the measurements can't
drift apart without a test saying so.
"""

import pytest

from ra2.domain.ids import RecordId
from ra2.domain.qualification import (
    MIN_SPEEDUP,
    UNPARSED_PREFIX,
    GateVerdict,
    canonical_answer,
    differ_count,
    gate_result,
    gate_verdict,
    noise_band,
    noise_floor,
)


def test_canonical_answer_ignores_key_order_and_whitespace() -> None:
    first = '{"features": {"b": 2, "a": 1}, "entities": []}'
    second = '{ "entities" : [ ],\n  "features": {"a": 1, "b": 2} }'
    assert canonical_answer(first) == canonical_answer(second)


def test_canonical_answer_keeps_a_value_difference() -> None:
    assert canonical_answer('{"a": 1}') != canonical_answer('{"a": 2}')


def test_canonical_answer_keeps_non_ascii_as_written() -> None:
    """French arrives with `é` intact (docs/seed.md §3). Escaping it would
    still compare correctly, but a canonical form nobody can read is a
    debugging trap."""
    assert canonical_answer('{"lieu": "carrefour à Genève"}') == '{"lieu":"carrefour à Genève"}'


def test_an_unparseable_answer_is_its_own_answer() -> None:
    broken = '{"a": 1'
    assert canonical_answer(broken) == canonical_answer(broken)
    assert canonical_answer(broken) != canonical_answer('{"a": 2')
    assert canonical_answer(broken).startswith(UNPARSED_PREFIX)


def test_an_unparseable_answer_never_equals_a_parsed_one() -> None:
    """The literal JSON string `"!unparsed:x"` parses; the broken text `x`
    doesn't. They must not collide."""
    assert canonical_answer("x") != canonical_answer('"!unparsed:x"')


def _pass(**answers: str) -> dict[RecordId, str]:
    return {RecordId(record_id): canonical_answer(raw) for record_id, raw in answers.items()}


def test_differ_count_counts_records_answered_differently() -> None:
    first = _pass(r1='{"a": 1}', r2='{"a": 2}', r3='{"a": 3}')
    second = _pass(r1='{"a": 1}', r2='{"a": 9}', r3='{"a": 9}')
    assert differ_count(first, second) == 2
    assert differ_count(first, first) == 0


def test_differ_count_refuses_passes_over_different_records() -> None:
    """A pass with a hole is an interrupted pass. Counting the missing record
    as a difference would make an interrupted pass look like a noisy model."""
    first = _pass(r1='{"a": 1}', r2='{"a": 2}')
    second = _pass(r1='{"a": 1}')
    with pytest.raises(ValueError, match="different records"):
        differ_count(first, second)


@pytest.mark.parametrize(("records", "floor"), [(48, 2), (24, 1), (1, 1), (200, 9)])
def test_noise_band_is_floored_at_two_of_48_scaled_to_seed_size(records: int, floor: int) -> None:
    assert noise_floor(records) == floor
    assert noise_band([0, 0], records) == floor


def test_noise_band_takes_the_measured_noise_when_it_is_above_the_floor() -> None:
    """`gemma4:12b`'s own serial passes vary on up to 3 of 48."""
    assert noise_band([3, 1], 48) == 3


def test_noise_band_needs_a_baseline() -> None:
    with pytest.raises(ValueError, match="at least two serial passes"):
        noise_band([], 48)


def test_noise_floor_refuses_an_empty_seed() -> None:
    with pytest.raises(ValueError, match="at least one record"):
        noise_floor(0)


@pytest.mark.parametrize(
    ("model", "band", "serial_on_n_slot", "parallel", "speedup", "verdict"),
    [
        # plan-parallel-calls.md §1.2 and docs/choosing-models.md §5, at N=4.
        ("qwen3:8b", 2, 0, 1, 2.4, GateVerdict.PASSES),
        ("granite4.1:8b", 2, 2, 14, 2.7, GateVerdict.FAILS_PARALLEL),
        ("gemma3:4b", 2, 2, 29, 2.0, GateVerdict.FAILS_PARALLEL),
        ("gemma4:12b", 3, 3, 4, 2.3, GateVerdict.FAILS_PARALLEL),
        ("ministral-3:8b", 2, 6, 5, 2.6, GateVerdict.FAILS_BOTH),
        # Ollama 0.34 serves `qwen35` one call at a time: nothing moves, nothing gained.
        ("qwen3.5:2b", 2, 0, 0, 1.0, GateVerdict.FAILS_PARALLEL),
    ],
)
def test_gate_verdicts_reproduce_the_measured_history(
    model: str,
    band: int,
    serial_on_n_slot: int,
    parallel: int,
    speedup: float,
    verdict: GateVerdict,
) -> None:
    assert (
        gate_verdict(
            band=band,
            serial_on_n_slot_differ=serial_on_n_slot,
            parallel_differ=parallel,
            speedup=speedup,
        )
        is verdict
    ), model


def test_a_model_that_is_fine_in_parallel_but_moves_serially_fails_the_server() -> None:
    assert (
        gate_verdict(band=2, serial_on_n_slot_differ=6, parallel_differ=0, speedup=2.0)
        is GateVerdict.FAILS_SERVER
    )


def test_the_band_and_the_speedup_are_inclusive_bounds() -> None:
    assert (
        gate_verdict(band=2, serial_on_n_slot_differ=2, parallel_differ=2, speedup=MIN_SPEEDUP)
        is GateVerdict.PASSES
    )
    assert (
        gate_verdict(
            band=2, serial_on_n_slot_differ=0, parallel_differ=0, speedup=MIN_SPEEDUP - 0.01
        )
        is GateVerdict.FAILS_PARALLEL
    )


def _answers(flipped: int, records: int = 48) -> dict[RecordId, str]:
    """`records` answers, the first `flipped` of them different from the
    reference."""
    return {RecordId(f"r{i:02d}"): ("changed" if i < flipped else "same") for i in range(records)}


def test_gate_result_measures_every_pass_against_the_first_one_slot_pass() -> None:
    result = gate_result(
        n=4,
        baseline=[_answers(0), _answers(1), _answers(0)],
        serial_on_n_slot=_answers(0),
        parallel=_answers(1),
        serial_on_n_slot_ms=83_000,
        parallel_ms=34_000,
    )
    assert (result.n, result.records, result.noise_band) == (4, 48, 2)
    assert (result.serial_on_n_slot_differ, result.parallel_differ) == (0, 1)
    assert result.speedup == 2.44
    assert result.verdict is GateVerdict.PASSES


def test_gate_result_fails_a_model_whose_parallel_answers_move() -> None:
    result = gate_result(
        n=4,
        baseline=[_answers(0), _answers(0), _answers(0)],
        serial_on_n_slot=_answers(2),
        parallel=_answers(14),
        serial_on_n_slot_ms=147_000,
        parallel_ms=54_000,
    )
    assert result.verdict is GateVerdict.FAILS_PARALLEL


def test_gate_result_needs_a_baseline_to_measure_noise_against() -> None:
    with pytest.raises(ValueError, match="two one-slot serial passes"):
        gate_result(
            n=4,
            baseline=[_answers(0)],
            serial_on_n_slot=_answers(0),
            parallel=_answers(0),
            serial_on_n_slot_ms=1,
            parallel_ms=1,
        )


def test_gate_result_refuses_a_pass_that_took_no_time() -> None:
    with pytest.raises(ValueError, match="no time"):
        gate_result(
            n=4,
            baseline=[_answers(0), _answers(0)],
            serial_on_n_slot=_answers(0),
            parallel=_answers(0),
            serial_on_n_slot_ms=1000,
            parallel_ms=0,
        )

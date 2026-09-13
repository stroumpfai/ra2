"""A parse failure is a datum, not a stop (mvp-spec.md §10.4, §15.3).

`parse_ok = False`, `parse_error` set, `raw_output_text` stored **verbatim**,
and the run **continues**. Nothing here is retried: temperature and seed are
fixed, so a second call would return the same bytes.

The other half of the same rule is that nothing is repaired (Do-NOT #6): an
enum code outside the evaluation's snapshot is stored exactly as the model
wrote it, and a key no feature asked for produces no row rather than an
invented one.
"""

import json

import pytest
from tests.backend.services.run.conftest import NOTE, WEATHER, answer
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus

pytestmark = pytest.mark.backend

#: Prose where JSON was asked for — mvp-spec.md §10.4's own example.
PROSE = "Ich kann diese Frage leider nicht beantworten."


async def test_a_parse_failure_is_stored_verbatim_and_the_run_continues(
    seed, make_run_service, reporter, extractions_of
):
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(script=[answer(), PROSE, answer(note="danach")]))

    await service.execute_run(seeded.run_id, reporter)

    rows = await extractions_of(seeded.run_id)
    assert [row.parse_ok for row in rows] == [True, False, True]
    failed = rows[1]
    assert failed.raw_output_text == PROSE
    assert failed.parse_error == "invalid_json"
    assert failed.values == []
    assert failed.entities == []
    # The run continued past it and finished.
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE
    assert rows[2].values != []


async def test_the_adapters_own_parse_verdict_is_stored_not_second_guessed(
    seed, make_run_service, reporter, extractions_of
):
    """`Extraction.parse_ok is False` from the seam is already a judgement.

    The row records it, with the adapter's reason, rather than re-parsing the
    same bytes to a different answer.
    """
    seeded = await seed(records=1)
    service = make_run_service(
        FakeLLMClient(
            response=answer(),
            parse_ok=False,
            parse_error="truncated_response",
        )
    )

    await service.execute_run(seeded.run_id, reporter)

    row = (await extractions_of(seeded.run_id))[0]
    assert row.parse_ok is False
    assert row.parse_error == "truncated_response"
    assert row.raw_output_text == answer()
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE


async def test_an_enum_code_outside_the_snapshot_is_stored_never_repaired(
    seed, make_run_service, reporter, extractions_of
):
    """`03` is not in `{"01","02"}`. It is still what the model said."""
    seeded = await seed(records=1)
    service = make_run_service(FakeLLMClient(response=answer(weather="03")))

    await service.execute_run(seeded.run_id, reporter)

    row = (await extractions_of(seeded.run_id))[0]
    values = {value.feature_id: value for value in row.values}
    assert values[seeded.feature_ids[WEATHER]].value_raw == "03"
    # The envelope was readable, so the extraction itself is not a failure —
    # the issue lives on the evidence, not on a dropped row.
    assert row.parse_ok is True


async def test_a_key_no_feature_asked_for_produces_no_invented_row(
    seed, make_run_service, reporter, extractions_of
):
    seeded = await seed(records=1)
    body = json.dumps(
        {
            "features": {
                WEATHER: {"value": "01", "present": True, "evidence": "Regen"},
                NOTE: {"value": "x", "present": True, "evidence": "Regen"},
                "invented": {"value": "y", "present": True, "evidence": "Regen"},
            },
            "entities": [],
        }
    )
    service = make_run_service(FakeLLMClient(response=body))

    await service.execute_run(seeded.run_id, reporter)

    row = (await extractions_of(seeded.run_id))[0]
    assert {value.feature_id for value in row.values} == set(seeded.feature_ids.values())
    assert row.parse_ok is True


async def test_a_missing_feature_is_a_null_answer_not_a_missing_row(
    seed, make_run_service, reporter, extractions_of
):
    """Every configured feature gets a row, so "the model did not answer" is
    a value in the data rather than an absence to be inferred."""
    seeded = await seed(records=1)
    body = json.dumps(
        {
            "features": {WEATHER: {"value": "01", "present": True, "evidence": "Regen"}},
            "entities": [],
        }
    )
    service = make_run_service(FakeLLMClient(response=body))

    await service.execute_run(seeded.run_id, reporter)

    row = (await extractions_of(seeded.run_id))[0]
    values = {value.feature_id: value for value in row.values}
    assert set(values) == set(seeded.feature_ids.values())
    missing = values[seeded.feature_ids[NOTE]]
    assert (missing.value_raw, missing.present_flag, missing.evidence_span) == (
        None,
        False,
        None,
    )


async def test_the_endpoints_own_numbers_are_stored_on_the_row(
    seed, make_run_service, reporter, extractions_of
):
    """Latency, token counts and the **retry count** — bounded and counted
    (mvp-spec.md §10.4), carried back on `Extraction.retry_count` (H4)."""
    seeded = await seed(records=2)
    service = make_run_service(
        FakeLLMClient(response=answer(), latencies=[120, 340], retry_count=2)
    )

    await service.execute_run(seeded.run_id, reporter)

    rows = await extractions_of(seeded.run_id)
    assert [row.latency_ms for row in rows] == [120, 340]
    assert [row.retry_count for row in rows] == [2, 2]
    assert all(row.prompt_tokens and row.completion_tokens for row in rows)

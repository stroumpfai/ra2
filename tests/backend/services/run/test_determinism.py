"""A re-run is a check, not a new sample (design §2, §15 F9, mvp-spec.md N5).

Two runs of one evaluation ask the **same question** — same resolved prompt,
same model, same temperature, same seed — and, given a client that answers the
same way, store the **same values**. What differs is the `run_id`: a re-run
adds rows, it never touches the first run's (Do-NOT #2).
"""

from collections.abc import Sequence

import pytest
from tests.backend.services.run.conftest import DEFAULT_MODEL, answer
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import FeatureId, RecordId
from ra2.persistence.models import Extraction

pytestmark = pytest.mark.backend


def _stored(
    rows: Sequence[Extraction],
) -> dict[RecordId, dict[FeatureId, tuple[str | None, str | None, bool, str | None]]]:
    """`{record_id: {feature_id: (raw, normalised, present, evidence)}}` —
    everything about a run's answers except which run they belong to."""
    return {
        row.record_id: {
            value.feature_id: (
                value.value_raw,
                value.value_normalised,
                value.present_flag,
                value.evidence_span,
            )
            for value in row.values
        }
        for row in rows
    }


async def test_two_runs_of_one_evaluation_store_identical_values(
    seed, make_run_service, reporter, extractions_of
):
    seeded = await seed(records=4, models=(DEFAULT_MODEL, DEFAULT_MODEL), seed_value=1234)
    client = FakeLLMClient(responses={marker: answer(note=marker) for marker in seeded.markers})
    service = make_run_service(client)

    await service.execute_run(seeded.run_ids[0], reporter)
    await service.execute_run(seeded.run_ids[1], reporter)

    first = await extractions_of(seeded.run_ids[0])
    second = await extractions_of(seeded.run_ids[1])
    assert _stored(first) == _stored(second)
    assert len(first) == len(second) == 4

    # The same question, twice: prompt, model, temperature and seed.
    assert client.calls[:4] == client.calls[4:]
    assert {(call[2], call[3]) for call in client.calls} == {(0.0, 1234)}

    # Two rows per record, one per run — never one row mutated twice.
    assert {row.id for row in first}.isdisjoint({row.id for row in second})
    assert all(row.run_id == seeded.run_ids[0] for row in first)
    assert all(row.run_id == seeded.run_ids[1] for row in second)


async def test_a_resumed_run_asks_the_same_question_the_first_pass_did(
    seed, make_run_service, reporter
):
    """Resume is the same run continued, not a differently-configured one:
    the temperature and seed come from the `run` row's own provenance."""
    seeded = await seed(records=4, seed_value=7)
    first_client = FakeLLMClient(response=answer(), fail_from=2)
    await make_run_service(first_client).execute_run(seeded.run_id, reporter)

    second_client = FakeLLMClient(response=answer())
    service = make_run_service(second_client)
    await service.execute_run(seeded.run_id, reporter)

    assert {(call[1], call[2], call[3]) for call in second_client.calls} == {
        (DEFAULT_MODEL, 0.0, 7)
    }
    # The prompts of the resumed half are the ones the first pass never got an
    # answer to, byte for byte.
    assert second_client.prompts == first_client.prompts[2:]
    assert (await service.get(seeded.run_id)).status is RunStatus.DONE

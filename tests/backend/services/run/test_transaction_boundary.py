"""One record, one transaction (sw-design.md §15.3).

> One `extraction` row, its `extraction_value` children and its
> `extraction_entity` children are committed **together, per record**. Nothing
> batches across records, and nothing holds a transaction open across an LLM
> call.

This is the property `plan-phase-3.md` R3 calls non-negotiable, so it is
asserted from the outside: a **second connection** — one that took no part in
the worker's transaction — counts what is durable at the moment each model
call is made. If a transaction spanned the call, or anything batched, the
sequence it sees would not be 0, 1, 2, 3, ….
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.backend.services.run.conftest import NOTE, WEATHER, answer
from tests.fixtures.fake_llm import FakeLLMClient

from ra2.domain.extraction import RunStatus
from ra2.domain.ids import RunId
from ra2.domain.llm import Extraction as LlmOutput
from ra2.persistence.models import Extraction

pytestmark = pytest.mark.backend


class ObservingClient:
    """An `LLMClient` that counts **committed** rows on its way through.

    The count is taken over its own session factory — a different connection
    to the same file — so it measures durability, not the worker's own
    in-flight session.
    """

    def __init__(
        self,
        inner: FakeLLMClient,
        session_factory: async_sessionmaker[AsyncSession],
        run_id: RunId,
    ) -> None:
        self._inner = inner
        self._session_factory = session_factory
        self._run_id = run_id
        self.committed_at_call: list[int] = []

    async def extract[T](
        self,
        text: str,
        schema: type[T],
        model: str,
        *,
        temperature: float,
        seed: int,
        reasoning_effort: str | None = None,
    ) -> LlmOutput[T]:
        async with self._session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Extraction)
                .where(Extraction.run_id == self._run_id)
            )
        self.committed_at_call.append(int(count or 0))
        return await self._inner.extract(
            text,
            schema,
            model,
            temperature=temperature,
            seed=seed,
            reasoning_effort=reasoning_effort,
        )


async def test_each_record_is_committed_before_the_next_model_call(
    seed, make_run_service, reporter, other_engine
):
    """Nothing batches, and no transaction spans a call."""
    seeded = await seed(records=4)
    observer = ObservingClient(FakeLLMClient(response=answer()), other_engine(), seeded.run_id)
    service = make_run_service(observer)

    await service.execute_run(seeded.run_id, reporter)

    assert observer.committed_at_call == [0, 1, 2, 3]


async def test_a_row_and_its_children_are_committed_together(
    seed, make_run_service, reporter, extractions_of
):
    seeded = await seed(records=2)
    service = make_run_service(FakeLLMClient(response=answer(weather="02", note="Glatteis")))

    await service.execute_run(seeded.run_id, reporter)

    rows = await extractions_of(seeded.run_id)
    assert len(rows) == 2
    for row in rows:
        assert {value.feature_id for value in row.values} == set(seeded.feature_ids.values())
        assert [(e.entity_kind, e.entity_ref) for e in row.entities] == [("vehicle", "B1")]
        assert [e.attributes_json for e in row.entities] == ['{"type":"car"}']
    by_key = {value.feature_id: value for value in rows[0].values}
    assert by_key[seeded.feature_ids[WEATHER]].value_raw == "02"
    assert by_key[seeded.feature_ids[NOTE]].value_raw == "Glatteis"
    assert by_key[seeded.feature_ids[WEATHER]].present_flag is True
    assert by_key[seeded.feature_ids[WEATHER]].evidence_span == "es regnete"


async def test_an_unexpected_failure_fails_the_run_and_keeps_what_committed(
    seed, make_run_service, reporter, extractions_of, run_row
):
    """A bug is not an interruption.

    An endpoint that will not answer leaves the run `interrupted` and
    resumable; anything else is a failure, **recorded** on the row before it
    reaches the task runner (mvp-spec.md §10.4).
    """
    seeded = await seed(records=5)
    client = FakeLLMClient(response=answer(), failures={2: RuntimeError("boom")})
    service = make_run_service(client)

    with pytest.raises(RuntimeError):
        await service.execute_run(seeded.run_id, reporter)

    # The two records that committed before the failure are durable.
    assert len(await extractions_of(seeded.run_id)) == 2
    run = await run_row(seeded.run_id)
    assert RunStatus(run.status) is RunStatus.FAILED
    assert run.error is not None
    assert "boom" in run.error
    view = await service.get(seeded.run_id)
    assert view.status is RunStatus.FAILED
    assert view.error == run.error


async def test_the_prompt_is_resolved_once_per_record_in_scope_order(
    seed, make_run_service, reporter, resolver
):
    seeded = await seed(records=3)
    service = make_run_service(FakeLLMClient(response=answer()))

    await service.execute_run(seeded.run_id, reporter)

    assert [call[1] for call in resolver.calls] == list(seeded.record_ids)
    assert [call[0] for call in resolver.calls] == [seeded.evaluation_id] * 3

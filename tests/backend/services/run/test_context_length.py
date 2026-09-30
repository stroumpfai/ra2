"""The context a run's model was loaded with, pinned once (`SD48`, risk D1).

The adapter sends no context size, so the server applies its own: a Modelfile's
`num_ctx`, `OLLAMA_CONTEXT_LENGTH`, or its default. Nothing is loaded before the
first record, so the worker asks `/api/ps` right after the first commit and
writes the answer on the run. That number is what every extraction's
`prompt_tokens` is later compared with.
"""

import pytest
from sqlalchemy import update
from tests.backend.services.run.conftest import DEFAULT_MODEL
from tests.fixtures.fake_llm import FakeLLMClient, StaticModelCatalog

from ra2.domain.extraction import RunStatus
from ra2.persistence.models import Run

pytestmark = pytest.mark.backend


async def test_the_loaded_context_is_pinned_after_the_first_record(
    seed, make_run_service, reporter, run_row
):
    seeded = await seed(records=3)
    catalog = StaticModelCatalog(context_lengths={DEFAULT_MODEL: 4096})
    service = make_run_service(FakeLLMClient(), model_catalog=catalog)

    await service.execute_run(seeded.run_ids[0], reporter)

    run = await run_row(seeded.run_ids[0])
    assert run.status == RunStatus.DONE
    assert run.context_length == 4096
    # Once per run, not once per record: three records, one question.
    assert catalog.context_length_calls == 1


async def test_a_server_that_does_not_report_it_leaves_it_unrecorded(
    seed, make_run_service, reporter, run_row
):
    """`None`, not a default: nothing of this run can then be flagged as at
    the limit, and the screens say *not recorded*."""
    seeded = await seed(records=2)
    catalog = StaticModelCatalog()
    service = make_run_service(FakeLLMClient(), model_catalog=catalog)

    await service.execute_run(seeded.run_ids[0], reporter)

    assert (await run_row(seeded.run_ids[0])).context_length is None
    assert catalog.context_length_calls == 1


async def test_a_resumed_run_keeps_its_first_reading(
    seed, make_run_service, reporter, run_row, db_session_factory
):
    """The first reading describes the records read under it. A resume on a
    differently-loaded model neither asks again nor rewrites it."""
    seeded = await seed(records=2)
    async with db_session_factory() as session:
        await session.execute(
            update(Run).where(Run.id == seeded.run_ids[0]).values(context_length=8192)
        )
        await session.commit()
    catalog = StaticModelCatalog(context_lengths={DEFAULT_MODEL: 2048})
    service = make_run_service(FakeLLMClient(), model_catalog=catalog)

    await service.execute_run(seeded.run_ids[0], reporter)

    assert (await run_row(seeded.run_ids[0])).context_length == 8192
    assert catalog.context_length_calls == 0


async def test_without_a_catalogue_nothing_is_asked_or_written(
    seed, make_run_service, reporter, run_row
):
    seeded = await seed(records=2)
    service = make_run_service(FakeLLMClient())

    await service.execute_run(seeded.run_ids[0], reporter)

    assert (await run_row(seeded.run_ids[0])).context_length is None

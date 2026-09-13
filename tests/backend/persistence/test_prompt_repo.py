"""Round-trip tests for `PromptRepository` against a real temp-file SQLite
database (sw-design.md §15.1).

`prompt_template` is copy-on-write: a save is `INSERT` at `version + 1`,
never an `UPDATE` — there is no test here for "editing a version" because
there is no method that does it (the absence is the contract). What *is*
tested: the citation count that makes a version `locked` rather than merely
labelled so, and the active flag staying a singleton across activations.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import CorpusId, FeatureConfigId, PromptTemplateId, RunId
from ra2.persistence.models import Corpus, Evaluation, FeatureConfig, PromptTemplate, Run
from ra2.persistence.repositories.prompt_repo import PromptRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)


def _make_template(
    template_id: str, *, version: int, source: str = "hello {{narrative}}"
) -> PromptTemplate:
    return PromptTemplate(
        id=PromptTemplateId(template_id),
        version=version,
        source=source,
        created_at=NOW,
        fingerprint=f"fingerprint-v{version}",
    )


async def test_add_and_get_round_trips(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.add(_make_template("pt-1", version=1))
        await session.commit()

    async with db_session_factory() as session:
        repo = PromptRepository(session)
        fetched = await repo.get(PromptTemplateId("pt-1"))

    assert fetched is not None
    assert fetched.version == 1
    assert fetched.source == "hello {{narrative}}"
    assert fetched.activated_at is None


async def test_get_returns_none_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        assert await repo.get(PromptTemplateId("does-not-exist")) is None


async def test_get_by_version(db_session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.add(_make_template("pt-1", version=1))
        await session.commit()

    async with db_session_factory() as session:
        repo = PromptRepository(session)
        fetched = await repo.get_by_version(1)

    assert fetched is not None
    assert fetched.id == "pt-1"


async def test_list_all_orders_newest_version_first(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.add(_make_template("pt-1", version=1))
        await repo.add(_make_template("pt-2", version=2))
        await repo.add(_make_template("pt-3", version=3))
        await session.commit()

    async with db_session_factory() as session:
        repo = PromptRepository(session)
        versions = [t.version for t in await repo.list_all()]

    assert versions == [3, 2, 1]


async def test_next_version_is_one_for_an_empty_table(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        assert await repo.next_version() == 1


async def test_next_version_is_monotonic_across_the_whole_lineage(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One lineage, bare integers — not grouped by name the way
    `FeatureRepository.next_version` groups by feature-set name (sw-design.md
    §15.1: a template has no name)."""
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.add(_make_template("pt-1", version=1))
        await repo.add(_make_template("pt-2", version=2))
        await session.commit()

    async with db_session_factory() as session:
        repo = PromptRepository(session)
        assert await repo.next_version() == 3


async def test_citation_count_is_zero_for_an_uncited_version(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.add(_make_template("pt-1", version=1))
        await session.commit()

    async with db_session_factory() as session:
        repo = PromptRepository(session)
        assert await repo.citation_count(PromptTemplateId("pt-1")) == 0


async def test_citation_count_reflects_runs_citing_the_version(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.add(_make_template("pt-1", version=1))
        session.add(
            Corpus(
                id=CorpusId("corpus-1"),
                name="Test corpus",
                imported_at=NOW,
                source_file_manifest_json="[]",
                import_report_json="[]",
                record_count=10,
            )
        )
        session.add(
            FeatureConfig(id=FeatureConfigId("fc-1"), name="Weather & conditions", created_at=NOW)
        )
        await session.flush()
        session.add(
            Evaluation(
                id="eval-1",
                name="Weather eval",
                corpus_id="corpus-1",
                feature_config_id="fc-1",
                created_at=NOW,
            )
        )
        await session.flush()
        session.add(_make_run("run-1", "eval-1", "pt-1"))
        session.add(_make_run("run-2", "eval-1", "pt-1"))
        await session.commit()

    async with db_session_factory() as session:
        repo = PromptRepository(session)
        assert await repo.citation_count(PromptTemplateId("pt-1")) == 2


async def test_activate_sets_the_flag_and_clears_any_previous_active_version(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.add(_make_template("pt-1", version=1))
        await repo.add(_make_template("pt-2", version=2))
        await session.commit()

    activated_first = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.activate(PromptTemplateId("pt-1"), activated_at=activated_first)
        await session.commit()

    activated_second = datetime(2026, 9, 13, 11, 0, tzinfo=UTC)
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.activate(PromptTemplateId("pt-2"), activated_at=activated_second)
        await session.commit()

    async with db_session_factory() as session:
        repo = PromptRepository(session)
        assert (await repo.get(PromptTemplateId("pt-1"))).activated_at is None  # type: ignore[union-attr]
        second = await repo.get(PromptTemplateId("pt-2"))
        assert second is not None
        assert second.activated_at == activated_second.replace(tzinfo=None)
        assert await repo.get_active() == second


async def test_activate_is_a_noop_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.activate(PromptTemplateId("does-not-exist"), activated_at=NOW)
        await session.commit()


async def test_delete_removes_an_uncited_version(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.add(_make_template("pt-1", version=1))
        await session.commit()

    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.delete(PromptTemplateId("pt-1"))
        await session.commit()

    async with db_session_factory() as session:
        repo = PromptRepository(session)
        assert await repo.get(PromptTemplateId("pt-1")) is None


async def test_delete_is_a_noop_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = PromptRepository(session)
        await repo.delete(PromptTemplateId("does-not-exist"))
        await session.commit()


def _make_run(run_id: str, evaluation_id: str, prompt_template_id: str) -> Run:
    return Run(
        id=RunId(run_id),
        evaluation_id=evaluation_id,
        model_name="llama3.1:8b-instruct-q8_0",
        model_digest="sha256:abc",
        prompt_template_version=1,
        prompt_template_id=prompt_template_id,
        prompt_template_fingerprint="fingerprint-v1",
        temperature=0.0,
        seed=42,
        host_platform="linux-x64",
    )

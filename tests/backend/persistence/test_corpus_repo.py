"""Round-trip tests for `CorpusRepository` against a real temp-file SQLite
database. `corpus` is write-once: no update path exists (sw-design.md §4)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.persistence.models import Corpus, Evaluation
from ra2.persistence.repositories.corpus_repo import CorpusRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)


def _make_corpus(corpus_id: str, *, name: str, version: int = 1) -> Corpus:
    return Corpus(
        id=CorpusId(corpus_id),
        name=name,
        imported_at=NOW,
        version=version,
        source_file_manifest_json="[]",
        import_report_json="[]",
        record_count=42,
        is_dev_sized=False,
        cp1252_canary_count=0,
    )


async def test_add_and_get_round_trips_a_corpus(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus_id = CorpusId("corpus-1")
    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        await repo.add(_make_corpus("corpus-1", name="AG 2024"))
        await session.commit()

    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        fetched = await repo.get(corpus_id)

    assert fetched is not None
    assert fetched.id == corpus_id
    assert fetched.name == "AG 2024"
    assert fetched.version == 1
    assert fetched.record_count == 42
    assert fetched.is_dev_sized is False
    assert fetched.cp1252_canary_count == 0


async def test_get_returns_none_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        assert await repo.get(CorpusId("does-not-exist")) is None


async def test_list_all_returns_every_corpus(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        await repo.add(_make_corpus("corpus-1", name="AG 2024"))
        await repo.add(_make_corpus("corpus-2", name="BE 2024"))
        await session.commit()

    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        corpora = await repo.list_all()

    assert {c.id for c in corpora} == {CorpusId("corpus-1"), CorpusId("corpus-2")}


async def test_next_version_is_one_when_no_corpus_of_that_name_exists(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        assert await repo.next_version("AG 2024") == 1


async def test_next_version_is_monotonic_per_name(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        await repo.add(_make_corpus("corpus-1", name="AG 2024", version=1))
        await session.commit()

    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        assert await repo.next_version("AG 2024") == 2
        # A different name starts its own sequence.
        assert await repo.next_version("BE 2024") == 1


async def test_count_citing_evaluations_is_zero_with_no_evaluations(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        await repo.add(_make_corpus("corpus-1", name="AG 2024"))
        await session.commit()

    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        assert await repo.count_citing_evaluations(CorpusId("corpus-1")) == 0


async def test_count_citing_evaluations_counts_a_seeded_row(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """M0-D1: `evaluation` exists in phase 1 only so the corpus delete guard
    (sw-design.md §6.3) can be seeded and tested against a real row."""
    corpus_id = CorpusId("corpus-1")
    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        await repo.add(_make_corpus("corpus-1", name="AG 2024"))
        session.add(
            Evaluation(
                id=EvaluationId("eval-1"),
                name="baseline",
                corpus_id=corpus_id,
                is_dev=False,
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        assert await repo.count_citing_evaluations(corpus_id) == 1


async def test_delete_removes_a_corpus_with_no_citing_evaluations(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    corpus_id = CorpusId("corpus-1")
    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        await repo.add(_make_corpus("corpus-1", name="AG 2024"))
        await session.commit()

    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        await repo.delete(corpus_id)
        await session.commit()

    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        assert await repo.get(corpus_id) is None


async def test_delete_is_a_no_op_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = CorpusRepository(session)
        await repo.delete(CorpusId("does-not-exist"))
        await session.commit()

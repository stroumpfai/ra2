"""Round-trip tests for `ScrubRepository` against a real temp-file SQLite
database (sw-design.md §19.4).

Both tables are copy-on-write. There is no test here for editing a list or a
version because there is no method that does either: the absence is the
contract. What is tested: reuse by `(kind, sha256)` enforced by the schema,
the active version being the highest, and the citation count per version.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import CorpusId, ScrubListId, ScrubRulesetId
from ra2.domain.scrub import ListKind
from ra2.persistence.models import Corpus, ScrubList, ScrubRuleset
from ra2.persistence.repositories.scrub_repo import ScrubRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)


def _list(list_id: str, kind: ListKind = ListKind.LASTNAME, sha256: str = "a" * 64) -> ScrubList:
    return ScrubList(
        id=ScrubListId(list_id),
        kind=kind,
        filename=f"{list_id}.txt",
        sha256=sha256,
        imported_at=NOW,
        entry_count=2,
        content_text="Meier\nMüller\n",
        import_report_json="[]",
    )


def _ruleset(ruleset_id: str, version: int, **lists: str) -> ScrubRuleset:
    return ScrubRuleset(
        id=ScrubRulesetId(ruleset_id),
        version=version,
        created_at=NOW,
        fingerprint=f"fp-{version}",
        **{key: ScrubListId(value) for key, value in lists.items()},
    )


async def test_a_list_round_trips_with_its_text_intact(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        await ScrubRepository(session).add_list(_list("l1"))
        await session.commit()
    async with db_session_factory() as session:
        repo = ScrubRepository(session)
        fetched = await repo.get_list(ScrubListId("l1"))
        found = await repo.find_list(ListKind.LASTNAME, "a" * 64)
    assert fetched is not None and found is not None
    assert fetched.content_text == "Meier\nMüller\n"
    assert found.id == "l1"
    assert fetched.kind == ListKind.LASTNAME


async def test_the_same_file_of_the_same_kind_is_one_row(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = ScrubRepository(session)
        await repo.add_list(_list("l1"))
        with pytest.raises(IntegrityError):
            await repo.add_list(_list("l2"))


async def test_the_same_bytes_as_two_kinds_are_two_rows(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A file imported as last names and again as the whitelist is two
    different things to the scrubber."""
    async with db_session_factory() as session:
        repo = ScrubRepository(session)
        await repo.add_list(_list("l1", ListKind.LASTNAME))
        await repo.add_list(_list("l2", ListKind.WHITELIST))
        await session.commit()


async def test_an_unknown_kind_is_refused_by_the_schema(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = ScrubRepository(session)
        bad = _list("l1")
        bad.kind = "nickname"  # type: ignore[assignment]
        with pytest.raises(IntegrityError):
            await repo.add_list(bad)


async def test_the_active_version_is_the_highest(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = ScrubRepository(session)
        assert await repo.get_active() is None
        assert await repo.next_version() == 1
        await repo.add_list(_list("l1"))
        await repo.add_ruleset(_ruleset("r1", 1, lastname_list_id="l1"))
        await repo.add_ruleset(_ruleset("r2", 2, lastname_list_id="l1"))
        await session.commit()
    async with db_session_factory() as session:
        repo = ScrubRepository(session)
        active = await repo.get_active()
        versions = [r.version for r in await repo.list_rulesets()]
        assert await repo.next_version() == 3
    assert active is not None and active.id == "r2"
    assert versions == [2, 1]


async def test_two_rows_cannot_share_a_version(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = ScrubRepository(session)
        await repo.add_ruleset(_ruleset("r1", 1))
        with pytest.raises(IntegrityError):
            await repo.add_ruleset(_ruleset("r2", 1))


async def test_a_version_cannot_point_at_a_list_that_does_not_exist(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = ScrubRepository(session)
        with pytest.raises(IntegrityError):
            await repo.add_ruleset(_ruleset("r1", 1, whitelist_id="missing"))


async def test_corpora_are_counted_per_version(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = ScrubRepository(session)
        await repo.add_ruleset(_ruleset("r1", 1))
        await repo.add_ruleset(_ruleset("r2", 2))
        for index, ruleset_id in enumerate(("r1", "r1", None)):
            session.add(
                Corpus(
                    id=CorpusId(f"c{index}"),
                    name="Bern",
                    imported_at=NOW,
                    version=index + 1,
                    source_file_manifest_json="[]",
                    import_report_json="[]",
                    record_count=0,
                    scrub_ruleset_id=ruleset_id,
                    scrub_fingerprint="f" * 64,
                )
            )
        await session.commit()
    async with db_session_factory() as session:
        counts = await ScrubRepository(session).corpus_counts()
    assert counts == {ScrubRulesetId("r1"): 2}

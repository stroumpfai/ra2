"""`CodelistService.coverage` — the `EnumCodeTableProvider` implementation.

Called with a plain `AsyncSession` the test owns, exactly the way
`feature_service` (E2) will call it from Wave 3 on: this must prove the
method never opens a session or commits one of its own (sw-design.md §14.2,
mirrors `CensusMaterialiser`'s own rule).
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.codelist_coverage import CoverageStatus
from ra2.domain.ids import CorpusId
from ra2.services.codelist_service import CodelistService

pytestmark = pytest.mark.backend


async def test_coverage_is_none_for_an_unmapped_column(
    codelist_service: CodelistService,
    seed_enum_column: Callable[..., Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_enum_column("corpus-1", column_name="WetterAusw", values=["1", "2"])

    async with db_session_factory() as session:
        result = await codelist_service.coverage(session, CorpusId("corpus-1"), "WetterAusw")

    assert result is None


async def test_coverage_is_none_for_a_column_with_no_census_data_at_all(
    codelist_service: CodelistService,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No `CensusColumn` row at all for `(corpus_id, source_column)` — the
    resolved gap's "zero matches" branch, distinct from "mapped but the
    attribute carries no codes" (that is `MISSING`, not `None`)."""
    async with db_session_factory() as session:
        result = await codelist_service.coverage(session, CorpusId("no-such-corpus"), "WetterAusw")

    assert result is None


async def test_coverage_returns_a_real_columncoverage_for_a_mapped_column(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await codelist_service.import_file("codelist.json", codelist_bytes("c01_minimal_valid"))
    accident_type = next(
        a for a in await codelist_service.list_attributes() if a.key == "accident_type"
    )
    await seed_enum_column("corpus-1", column_name="UnfallartAusw", values=["01", "02"])
    await codelist_service.map_column(
        CorpusId("corpus-1"), "UnfallartAusw", accident_type.code_attribute_id
    )

    # A session this test owns and passes in directly — proving `coverage()`
    # runs on it rather than opening one of its own.
    async with db_session_factory() as session:
        result = await codelist_service.coverage(session, CorpusId("corpus-1"), "UnfallartAusw")
        # The session must still be usable afterwards: `coverage()` must not
        # have committed or closed it out from under the caller.
        assert session.is_active
        await session.rollback()

    assert result is not None
    assert result.status is CoverageStatus.OK
    assert result.total_count == 2
    assert result.language == "de"  # the protocol-shaped default (no language arg)


async def test_coverage_default_language_can_be_overridden(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`list_columns()` needs per-language coverage; `coverage()` accepts an
    explicit keyword beyond the frozen `EnumCodeTableProvider` shape so
    `list_columns()` can delegate to it without duplicating
    `compute_coverage`'s call (task note: "delegate to your own coverage()
    method to avoid duplicating logic")."""
    await codelist_service.import_file(
        "codelist.json", codelist_bytes("c02_missing_language_label")
    )
    main_cause = next(a for a in await codelist_service.list_attributes() if a.key == "main_cause")
    await seed_enum_column("corpus-1", column_name="HauptursacheAusw", values=["01", "02"])
    await codelist_service.map_column(
        CorpusId("corpus-1"), "HauptursacheAusw", main_cause.code_attribute_id
    )

    async with db_session_factory() as session:
        de_result = await codelist_service.coverage(
            session, CorpusId("corpus-1"), "HauptursacheAusw", language="de"
        )
        it_result = await codelist_service.coverage(
            session, CorpusId("corpus-1"), "HauptursacheAusw", language="it"
        )

    assert de_result is not None
    assert de_result.status is CoverageStatus.OK
    assert it_result is not None
    assert it_result.status is CoverageStatus.PARTIAL

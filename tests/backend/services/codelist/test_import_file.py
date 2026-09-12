"""`CodelistService.import_file` (sw-design.md §14.1).

Asserted against D1's committed hazard fixtures
(`tests/fixtures/codelists/hazards/c01..c05`), the same file c04 uses to
prove the whole-import-fails rule (Do-NOT list #6): one bad attribute fails
the lot, never a partial import.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import CorpusId
from ra2.infra.clock import FrozenClock
from ra2.persistence.models import CodeTableImport
from ra2.services.codelist_service import CodelistService
from ra2.services.errors import CodelistImportError

pytestmark = pytest.mark.backend


async def _count_imports(db_session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with db_session_factory() as session:
        return await session.scalar(select(func.count()).select_from(CodeTableImport)) or 0


async def test_first_import_writes_one_generation(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    content = codelist_bytes("c01_minimal_valid")

    result = await codelist_service.import_file("codelist.json", content)

    assert result.no_change is False
    assert result.attribute_count == 2  # accident_type, road_type
    assert await _count_imports(db_session_factory) == 1


async def test_reuploading_the_same_bytes_is_a_no_op(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    content = codelist_bytes("c01_minimal_valid")
    first = await codelist_service.import_file("codelist.json", content)

    second = await codelist_service.import_file("codelist.json", content)

    # Row count, not "no exception raised": Do-NOT list #2, a re-run adds
    # rows or it adds none — never mutates the one it already wrote.
    assert await _count_imports(db_session_factory) == 1
    assert second.no_change is True
    assert second.code_table_import_id == first.code_table_import_id
    assert second.attribute_count == first.attribute_count


async def test_a_corrected_reupload_creates_a_new_generation(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await codelist_service.import_file("codelist.json", codelist_bytes("c01_minimal_valid"))

    second = await codelist_service.import_file(
        "codelist.json", codelist_bytes("c05_orphan_corpus_value")
    )

    assert second.no_change is False
    assert second.code_table_import_id != first.code_table_import_id
    assert await _count_imports(db_session_factory) == 2


async def test_an_existing_mapping_still_points_at_the_old_generation_until_repointed(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
    clock: FrozenClock,
) -> None:
    first = await codelist_service.import_file("codelist.json", codelist_bytes("c01_minimal_valid"))
    attributes = await codelist_service.list_attributes()
    accident_type = next(a for a in attributes if a.key == "accident_type")

    await seed_enum_column("corpus-1", column_name="UnfallartAusw", values=["01", "02"])
    mapped = await codelist_service.map_column(
        CorpusId("corpus-1"), "UnfallartAusw", accident_type.code_attribute_id
    )
    assert mapped.mapped_attribute is not None
    assert mapped.mapped_attribute.code_attribute_id == accident_type.code_attribute_id

    # A corrected re-upload is additive (§14.1 step 3) — existing
    # `column_mapping` rows are left untouched, still pointing at `first`'s
    # generation, until an analyst explicitly re-points them. The clock is
    # advanced so the two imports have distinct `imported_at` values — with a
    # `FrozenClock` they would otherwise tie, and "most recent" needs the two
    # generations to be orderable in the first place.
    clock.advance(seconds=1)
    second = await codelist_service.import_file(
        "codelist.json", codelist_bytes("c05_orphan_corpus_value")
    )
    assert second.code_table_import_id != first.code_table_import_id

    columns = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")
    still_mapped = next(c for c in columns if c.column_name == "UnfallartAusw")
    assert still_mapped.mapped_attribute is not None
    assert still_mapped.mapped_attribute.code_attribute_id == accident_type.code_attribute_id

    # `list_attributes()` now offers only the newest generation's keys — the
    # still-mapped `accident_type` (first generation) is not among them.
    latest_keys = {a.key for a in await codelist_service.list_attributes()}
    assert latest_keys == {"weather"}


async def test_structural_error_raises_and_writes_nothing(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(CodelistImportError) as excinfo:
        await codelist_service.import_file("codelist.json", codelist_bytes("c04_missing_codes_key"))

    assert len(excinfo.value.import_errors) >= 1
    assert await _count_imports(db_session_factory) == 0


async def test_non_utf8_encoding_is_not_silently_replaced(
    codelist_service: CodelistService,
) -> None:
    """Do-NOT list #4: never `errors="replace"`. Invalid UTF-8 raises rather
    than being silently repaired into replacement characters."""
    with pytest.raises(UnicodeDecodeError):
        await codelist_service.import_file("codelist.json", b"\xff\xfe not utf-8 at all")

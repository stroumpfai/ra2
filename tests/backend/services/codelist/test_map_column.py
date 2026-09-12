"""`CodelistService.map_column` / `.unmap_column` (sw-design.md §14.2)."""

from collections.abc import Awaitable, Callable

import pytest

from ra2.domain.ids import CodeAttributeId, CorpusId
from ra2.services.codelist_service import CodelistService
from ra2.services.errors import NotFoundError

pytestmark = pytest.mark.backend


async def test_map_column_against_an_unknown_attribute_raises_not_found(
    codelist_service: CodelistService,
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    await seed_enum_column("corpus-1", column_name="WetterAusw", values=["1"])

    with pytest.raises(NotFoundError):
        await codelist_service.map_column(
            CorpusId("corpus-1"), "WetterAusw", CodeAttributeId("no-such-attribute")
        )


async def test_map_column_never_touches_code_value(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    """mvp-spec.md §7: mapping is per corpus, analyst-set — it never writes
    to `code_attribute`/`code_value`. Asserted by re-fetching the attribute
    through `list_attributes()` and checking its code count is unchanged."""
    await codelist_service.import_file("codelist.json", codelist_bytes("c01_minimal_valid"))
    before = next(a for a in await codelist_service.list_attributes() if a.key == "accident_type")

    await seed_enum_column("corpus-1", column_name="UnfallartAusw", values=["01"])
    await codelist_service.map_column(
        CorpusId("corpus-1"), "UnfallartAusw", before.code_attribute_id
    )

    after = next(a for a in await codelist_service.list_attributes() if a.key == "accident_type")
    assert after.code_count == before.code_count


async def test_repointing_a_mapping_replaces_it_in_place(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    await codelist_service.import_file("codelist.json", codelist_bytes("c01_minimal_valid"))
    attributes = await codelist_service.list_attributes()
    accident_type = next(a for a in attributes if a.key == "accident_type")
    road_type = next(a for a in attributes if a.key == "road_type")

    await seed_enum_column("corpus-1", column_name="UnfallartAusw", values=["01"])
    first = await codelist_service.map_column(
        CorpusId("corpus-1"), "UnfallartAusw", accident_type.code_attribute_id
    )
    second = await codelist_service.map_column(
        CorpusId("corpus-1"), "UnfallartAusw", road_type.code_attribute_id
    )

    # Re-editable at will, in place — not a second row for the same pair
    # (sw-design.md §14.2, the unique constraint on `column_mapping` would
    # refuse a second row anyway).
    assert second.mapping_id == first.mapping_id
    assert second.mapped_attribute is not None
    assert second.mapped_attribute.key == "road_type"

    columns = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")
    assert len(columns) == 1
    assert columns[0].mapped_attribute is not None
    assert columns[0].mapped_attribute.key == "road_type"


async def test_unmap_column_clears_the_mapping(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    await codelist_service.import_file("codelist.json", codelist_bytes("c01_minimal_valid"))
    accident_type = next(
        a for a in await codelist_service.list_attributes() if a.key == "accident_type"
    )
    await seed_enum_column("corpus-1", column_name="UnfallartAusw", values=["01"])
    await codelist_service.map_column(
        CorpusId("corpus-1"), "UnfallartAusw", accident_type.code_attribute_id
    )

    await codelist_service.unmap_column(CorpusId("corpus-1"), "UnfallartAusw")

    columns = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")
    assert columns[0].mapping_id is None
    assert columns[0].mapped_attribute is None
    assert columns[0].coverage is None


async def test_unmap_column_is_a_no_op_when_nothing_is_mapped(
    codelist_service: CodelistService,
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    await seed_enum_column("corpus-1", column_name="WetterAusw", values=["1"])

    # No mapping exists yet; this must not raise.
    await codelist_service.unmap_column(CorpusId("corpus-1"), "WetterAusw")

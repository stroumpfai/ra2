"""`CodelistService.list_columns` (sw-design.md §14.2), end to end against D1's
hazard fixtures — one real corpus, one real mapping, no mocked repository.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.codelist_coverage import CoverageStatus
from ra2.domain.feature import Grain, Kind, ValueType
from ra2.domain.ids import CorpusId, FeatureConfigId, FeatureId
from ra2.persistence.models import Feature, FeatureConfig
from ra2.services.codelist_service import CodelistService

pytestmark = pytest.mark.backend


async def test_unmapped_enum_column_has_no_coverage(
    codelist_service: CodelistService,
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    await seed_enum_column("corpus-1", column_name="WetterAusw", values=["1", "2"])

    columns = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")

    assert len(columns) == 1
    column = columns[0]
    assert column.table_name == "unfall"
    assert column.column_name == "WetterAusw"
    assert column.distinct_in_corpus == 2
    assert column.mapping_id is None
    assert column.mapped_attribute is None
    assert column.coverage is None
    assert column.used_by_features == ()


async def test_used_by_features_reflects_a_real_feature(
    codelist_service: CodelistService,
    seed_enum_column: Callable[..., Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """C5 / plan-phase-2.md §2: "computed from `feature.source_column`, not
    stored" — this phase turns the cross-link on. A *draft* feature counts
    too: it already depends on the column just as much as a frozen one, and
    a `feature_config` needs no corpus of its own to reference one."""
    await seed_enum_column("corpus-1", column_name="WetterAusw", values=["1", "2"])
    async with db_session_factory() as session:
        session.add(
            FeatureConfig(
                id=FeatureConfigId("fc-1"), name="draft set", created_at=datetime.now(UTC)
            )
        )
        await session.flush()
        session.add(
            Feature(
                id=FeatureId("feat-1"),
                feature_config_id=FeatureConfigId("fc-1"),
                ordinal=0,
                key="weather",
                kind=Kind.LABELLED,
                description="weather",
                grain=Grain.ACCIDENT,
                source_column="WetterAusw",
                value_type=ValueType.ENUM,
                matching_rule='{"kind":"exact","tolerance_minutes":null,"decimal_precision":null}',
            )
        )
        await session.commit()

    columns = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")

    assert columns[0].used_by_features == ("weather",)


async def test_mapping_to_c01_gives_ok_coverage(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    """c01: two well-formed attributes, every code labelled in every
    language — a column whose corpus values are a subset of `accident_type`'s
    codes must come back `OK` (sw-design.md §14.2)."""
    await codelist_service.import_file("codelist.json", codelist_bytes("c01_minimal_valid"))
    attributes = await codelist_service.list_attributes()
    accident_type = next(a for a in attributes if a.key == "accident_type")

    await seed_enum_column("corpus-1", column_name="UnfallartAusw", values=["01", "02", "01"])
    await codelist_service.map_column(
        CorpusId("corpus-1"), "UnfallartAusw", accident_type.code_attribute_id
    )

    columns = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")

    assert len(columns) == 1
    column = columns[0]
    assert column.mapping_id is not None
    assert column.mapped_attribute is not None
    assert column.mapped_attribute.key == "accident_type"
    assert column.coverage is not None
    assert column.coverage.status is CoverageStatus.OK
    assert column.coverage.total_count == 2  # distinct codes: "01", "02"


async def test_mapping_to_c02_is_partial_in_the_gapped_language(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    """c02 mirrors the real `main_cause` gap: code `02` has no `it` label."""
    await codelist_service.import_file(
        "codelist.json", codelist_bytes("c02_missing_language_label")
    )
    main_cause = next(a for a in await codelist_service.list_attributes() if a.key == "main_cause")

    await seed_enum_column("corpus-1", column_name="HauptursacheAusw", values=["01", "02"])
    await codelist_service.map_column(
        CorpusId("corpus-1"), "HauptursacheAusw", main_cause.code_attribute_id
    )

    columns_it = await codelist_service.list_columns(CorpusId("corpus-1"), language="it")
    columns_de = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")

    assert columns_it[0].coverage is not None
    assert columns_it[0].coverage.status is CoverageStatus.PARTIAL
    assert columns_de[0].coverage is not None
    assert columns_de[0].coverage.status is CoverageStatus.OK


async def test_mapping_to_c03_zero_codes_is_missing(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    """c03: an attribute with `codes: {}` — structurally valid, zero rows.
    A column mapped to it is `MISSING`, never `PARTIAL` (sw-design.md §14.2:
    "the mapped code_attribute has zero code_value rows")."""
    await codelist_service.import_file(
        "codelist.json", codelist_bytes("c03_attribute_with_zero_codes")
    )
    light_condition = next(
        a for a in await codelist_service.list_attributes() if a.key == "light_condition"
    )

    await seed_enum_column("corpus-1", column_name="LichtverhaeltnisAusw", values=["1"])
    await codelist_service.map_column(
        CorpusId("corpus-1"), "LichtverhaeltnisAusw", light_condition.code_attribute_id
    )

    columns = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")

    assert columns[0].coverage is not None
    assert columns[0].coverage.status is CoverageStatus.MISSING


async def test_mapping_to_c05_has_an_orphan_code(
    codelist_service: CodelistService,
    codelist_bytes: Callable[[str], bytes],
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    """c05's `ORPHAN_VALUE` ("97") has no counterpart in the mapped
    attribute's code table at all — the `Finding`-grade case mvp-spec.md §7
    names, surfaced as a danger row (`in_codelist=False`) rather than folded
    into `PARTIAL`."""
    await codelist_service.import_file("codelist.json", codelist_bytes("c05_orphan_corpus_value"))
    weather = next(a for a in await codelist_service.list_attributes() if a.key == "weather")

    await seed_enum_column("corpus-1", column_name="WetterAusw", values=["1", "97"])
    await codelist_service.map_column(CorpusId("corpus-1"), "WetterAusw", weather.code_attribute_id)

    columns = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")

    coverage = columns[0].coverage
    assert coverage is not None
    orphan = next(usage for usage in coverage.codes if usage.code == "97")
    assert orphan.in_codelist is False
    assert orphan.label is None
    known = next(usage for usage in coverage.codes if usage.code == "1")
    assert known.in_codelist is True


async def test_non_enum_column_is_never_listed(
    codelist_service: CodelistService,
    seed_enum_column: Callable[..., Awaitable[None]],
) -> None:
    """Only `type_hint == ENUM` columns appear — a `*Ausw` name is what
    `infer_type_hint` keys off, so a plain-named column never shows up here
    even though it is stored in the same `unfall` EAV table."""
    await seed_enum_column("corpus-1", column_name="StrasseName", values=["Bahnhofstrasse"])

    columns = await codelist_service.list_columns(CorpusId("corpus-1"), language="de")

    assert columns == []

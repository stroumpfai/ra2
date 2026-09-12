"""Round-trip tests for `FeatureRepository` against a real temp-file SQLite
database (mvp-spec.md §8).

Unlike `corpus`, `feature_config` / `feature` are mutable while a draft:
`freeze()` sets `frozen_at` on the existing row in place, it does not append
a new one (sw-design.md §14's sibling feature-config design, "draft states").
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.feature import Grain, Kind, MatchingRuleKind, ValueType
from ra2.domain.ids import FeatureConfigId, FeatureId
from ra2.persistence.models import Feature, FeatureConfig
from ra2.persistence.repositories.feature_repo import FeatureRepository

pytestmark = pytest.mark.backend

NOW = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)


def _make_feature(feature_id: str, feature_config_id: str, *, ordinal: int, key: str) -> Feature:
    return Feature(
        id=FeatureId(feature_id),
        feature_config_id=FeatureConfigId(feature_config_id),
        ordinal=ordinal,
        key=key,
        kind=Kind.LABELLED,
        description=f"description for {key}",
        grain=Grain.ACCIDENT,
        source_column="UnfTypAusw",
        value_type=ValueType.ENUM,
        matching_rule=f'{{"kind": "{MatchingRuleKind.EXACT.value}"}}',
    )


async def test_add_and_get_config_round_trips_its_features(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config_id = FeatureConfigId("fc-1")
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        config = FeatureConfig(
            id=config_id,
            name="Weather & conditions",
            description="Everything about the scene",
            created_at=NOW,
            features=[
                _make_feature("feat-2", "fc-1", ordinal=2, key="road_type"),
                _make_feature("feat-1", "fc-1", ordinal=1, key="accident_type"),
            ],
        )
        await repo.add_config(config)
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        fetched = await repo.get_config(config_id)

    assert fetched is not None
    assert fetched.name == "Weather & conditions"
    assert fetched.version == 1
    assert fetched.frozen_at is None
    # `Feature.ordinal` orders the relationship (models.py) — the design's
    # display/pagination order within the set.
    assert [f.key for f in fetched.features] == ["accident_type", "road_type"]


async def test_get_config_returns_none_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        assert await repo.get_config(FeatureConfigId("does-not-exist")) is None


async def test_list_configs_returns_every_config(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_config(FeatureConfig(id=FeatureConfigId("fc-1"), name="A", created_at=NOW))
        await repo.add_config(FeatureConfig(id=FeatureConfigId("fc-2"), name="B", created_at=NOW))
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        configs = await repo.list_configs()

    assert {c.id for c in configs} == {FeatureConfigId("fc-1"), FeatureConfigId("fc-2")}


async def test_next_version_is_one_when_no_config_of_that_name_exists(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        assert await repo.next_version("Weather & conditions") == 1


async def test_next_version_is_monotonic_per_name(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_config(
            FeatureConfig(
                id=FeatureConfigId("fc-1"), name="Weather & conditions", version=1, created_at=NOW
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        assert await repo.next_version("Weather & conditions") == 2
        assert await repo.next_version("Something else") == 1


async def test_freeze_sets_frozen_at_on_the_existing_row(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config_id = FeatureConfigId("fc-1")
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_config(
            FeatureConfig(id=config_id, name="Weather & conditions", created_at=NOW)
        )
        await session.commit()

    frozen_at = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.freeze(config_id, frozen_at=frozen_at)
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        fetched = await repo.get_config(config_id)

    assert fetched is not None
    assert fetched.frozen_at == frozen_at.replace(tzinfo=None)
    # Freezing is an update: still exactly one `feature_config` row.
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        assert len(await repo.list_configs()) == 1


async def test_freeze_is_a_noop_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.freeze(FeatureConfigId("does-not-exist"), frozen_at=NOW)
        await session.commit()


async def test_delete_config_removes_a_draft(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config_id = FeatureConfigId("fc-1")
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_config(FeatureConfig(id=config_id, name="Draft", created_at=NOW))
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.delete_config(config_id)
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        assert await repo.get_config(config_id) is None


async def test_delete_config_is_a_noop_for_an_unknown_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.delete_config(FeatureConfigId("does-not-exist"))
        await session.commit()


async def test_add_and_get_feature_round_trips(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config_id = FeatureConfigId("fc-1")
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_config(
            FeatureConfig(id=config_id, name="Weather & conditions", created_at=NOW)
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_feature(_make_feature("feat-1", "fc-1", ordinal=1, key="accident_type"))
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        fetched = await repo.get_feature(FeatureId("feat-1"))

    assert fetched is not None
    assert fetched.key == "accident_type"
    assert fetched.kind == Kind.LABELLED
    assert fetched.grain == Grain.ACCIDENT
    assert fetched.value_type == ValueType.ENUM


async def test_list_features_orders_by_ordinal(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config_id = FeatureConfigId("fc-1")
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_config(
            FeatureConfig(id=config_id, name="Weather & conditions", created_at=NOW)
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_feature(_make_feature("feat-b", "fc-1", ordinal=2, key="road_type"))
        await repo.add_feature(_make_feature("feat-a", "fc-1", ordinal=1, key="accident_type"))
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        features = await repo.list_features(config_id)

    assert [f.key for f in features] == ["accident_type", "road_type"]


async def test_delete_feature_removes_it(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    config_id = FeatureConfigId("fc-1")
    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_config(
            FeatureConfig(id=config_id, name="Weather & conditions", created_at=NOW)
        )
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.add_feature(_make_feature("feat-1", "fc-1", ordinal=1, key="accident_type"))
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        await repo.delete_feature(FeatureId("feat-1"))
        await session.commit()

    async with db_session_factory() as session:
        repo = FeatureRepository(session)
        assert await repo.get_feature(FeatureId("feat-1")) is None

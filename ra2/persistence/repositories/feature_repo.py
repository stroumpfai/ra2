# STUB — bodies owned by D3 (feat/p2-persistence). Not frozen.
"""Feature configuration persistence (mvp-spec.md §8).

Unlike `corpus` (write-once, a re-run adds rows), `feature_config` and
`feature` are **mutable while a draft**: the design's "drafts can be renamed
and deleted" and its live edit zones need an update path, not just an add
path. `freeze()` is the one state transition that matters here — it sets
`frozen_at` on the existing row in place, it does not create a new one.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ra2.domain.ids import FeatureConfigId, FeatureId
from ra2.persistence.models import Feature, FeatureConfig

__all__ = ["FeatureRepository"]


class FeatureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- feature_config -------------------------------------------------------

    async def add_config(self, config: FeatureConfig) -> None:
        """Writes one `feature_config`, plus any `feature` rows already
        attached through `FeatureConfig.features` (cascade), in one flush."""
        self._session.add(config)
        await self._session.flush()

    async def get_config(self, feature_config_id: FeatureConfigId) -> FeatureConfig | None:
        stmt = (
            select(FeatureConfig)
            .where(FeatureConfig.id == feature_config_id)
            .options(selectinload(FeatureConfig.features))
        )
        config: FeatureConfig | None = await self._session.scalar(stmt)
        return config

    async def list_configs(self) -> list[FeatureConfig]:
        stmt = select(FeatureConfig).order_by(FeatureConfig.created_at.desc())
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def next_version(self, name: str) -> int:
        """Monotonic per feature-set name — mirrors `CorpusRepository.next_version`,
        the design's "Weather & conditions v3" next to older v2/v1 sets."""
        stmt = select(func.max(FeatureConfig.version)).where(FeatureConfig.name == name)
        current_max = await self._session.scalar(stmt)
        return (current_max or 0) + 1

    async def freeze(self, feature_config_id: FeatureConfigId, *, frozen_at: datetime) -> None:
        """Sets `frozen_at` on the existing row — an update, not an append
        (mvp-spec.md §8, the design's draft/frozen states). No-op if the id
        is unknown; the caller is expected to have checked existence first
        when that distinction matters."""
        config = await self.get_config(feature_config_id)
        if config is None:
            return
        config.frozen_at = frozen_at
        await self._session.flush()

    async def delete_config(self, feature_config_id: FeatureConfigId) -> None:
        """Drafts can be deleted (the design's draft-state actions); a frozen
        config an evaluation cites is protected by the FK's `RESTRICT`, not
        by this method — it is a no-op only when the id is unknown."""
        config = await self.get_config(feature_config_id)
        if config is None:
            return
        await self._session.delete(config)
        await self._session.flush()

    # -- feature ----------------------------------------------------------------

    async def add_feature(self, feature: Feature) -> None:
        self._session.add(feature)
        await self._session.flush()

    async def get_feature(self, feature_id: FeatureId) -> Feature | None:
        stmt = select(Feature).where(Feature.id == feature_id)
        feature: Feature | None = await self._session.scalar(stmt)
        return feature

    async def list_features(self, feature_config_id: FeatureConfigId) -> list[Feature]:
        stmt = (
            select(Feature)
            .where(Feature.feature_config_id == feature_config_id)
            .order_by(Feature.ordinal)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def delete_feature(self, feature_id: FeatureId) -> None:
        feature = await self.get_feature(feature_id)
        if feature is None:
            return
        await self._session.delete(feature)
        await self._session.flush()

# STUB — bodies owned by E2 (feat/p2-feature-service). Not frozen.
"""Create, validate, freeze and clone feature configs (mvp-spec.md §8).

`EnumCodeTableProvider` is injected: this service never imports
`codelist_service` directly, only the protocol (`services/protocols.py`).
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.feature import DerivationSpec, Grain, Kind, MatchingRule, ValueType
from ra2.domain.ids import FeatureConfigId, FeatureId
from ra2.infra.clock import Clock
from ra2.infra.idgen import IdFactory
from ra2.services.protocols import EnumCodeTableProvider
from ra2.services.readmodels import FeatureConfigView, FeatureSetSummary

__all__ = ["FeatureService"]


class FeatureService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        codelist_provider: EnumCodeTableProvider,
        clock: Clock,
        ids: IdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._codelist_provider = codelist_provider
        self._clock = clock
        self._ids = ids

    async def list_configs(self) -> list[FeatureSetSummary]:
        """Every set, draft and frozen — the feature-sets strip."""
        raise NotImplementedError

    async def get(self, feature_config_id: FeatureConfigId) -> FeatureConfigView:
        """Raises `NotFoundError`."""
        raise NotImplementedError

    async def create_draft(self, *, name: str, description: str | None = None) -> FeatureConfigView:
        raise NotImplementedError

    async def rename(self, feature_config_id: FeatureConfigId, *, name: str) -> FeatureConfigView:
        """Draft only. Raises `FeatureConfigFrozenError`."""
        raise NotImplementedError

    async def delete(self, feature_config_id: FeatureConfigId) -> None:
        """Draft only. Raises `FeatureConfigFrozenError`."""
        raise NotImplementedError

    async def add_feature(
        self,
        feature_config_id: FeatureConfigId,
        *,
        key: str,
        kind: Kind,
        description: str,
        grain: Grain,
        source_column: str | None,
        derivation: DerivationSpec | None,
        value_type: ValueType,
        matching_rule: MatchingRule,
    ) -> FeatureConfigView:
        """Validates as it goes (mvp-spec.md §7/§8.2: unmapped/codeless enum,
        non-scalar grain, the 20-item exploratory cap) — problems surface as
        errors on the returned view, they do not raise. Only `freeze()`
        blocks on them.

        :raises FeatureConfigFrozenError: the set is already frozen.
        """
        raise NotImplementedError

    async def edit_feature(
        self,
        feature_config_id: FeatureConfigId,
        feature_id: FeatureId,
        *,
        key: str,
        kind: Kind,
        description: str,
        grain: Grain,
        source_column: str | None,
        derivation: DerivationSpec | None,
        value_type: ValueType,
        matching_rule: MatchingRule,
    ) -> FeatureConfigView:
        """Draft only. Raises `FeatureConfigFrozenError`."""
        raise NotImplementedError

    async def delete_feature(
        self, feature_config_id: FeatureConfigId, feature_id: FeatureId
    ) -> None:
        """Draft only. Raises `FeatureConfigFrozenError`."""
        raise NotImplementedError

    async def freeze(self, feature_config_id: FeatureConfigId) -> FeatureConfigView:
        """Computes and stores every feature's real fingerprint, one
        transaction (§8.5). Immutable from this point on (F2,
        plan-phase-2.md §15).

        :raises FeatureValidationError: a blocking error remains; nothing is
            frozen.
        """
        raise NotImplementedError

    async def clone(self, feature_config_id: FeatureConfigId, *, name: str) -> FeatureConfigView:
        """A frozen set only, into a fresh draft with its own feature rows —
        no shared mutable state with the frozen original (design's C4,
        "Clone to new evaluation").
        """
        raise NotImplementedError

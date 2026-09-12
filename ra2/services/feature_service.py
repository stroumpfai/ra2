# STUB — bodies owned by E2 (feat/p2-feature-service). Not frozen.
"""Create, validate, freeze and clone feature configs (mvp-spec.md §8).

`EnumCodeTableProvider` is injected: this service never imports
`codelist_service` directly, only the protocol (`services/protocols.py`).

**Validation has two tiers** (see `_validation_errors`). mvp-spec.md §7 puts
the "an `enum` feature with no codes cannot be run" gate at *evaluation setup*;
`design/code-feature/README.md` additionally draws it as a blocking row in the
Features list, long before an evaluation exists. Those are not in conflict —
the design adds an earlier authoring-time safety net — but the earlier check
needs a corpus to ask "does this column have codes *here*", and
`feature_config` deliberately carries no `corpus_id` (a feature set is
corpus-independent and reusable, plan-phase-2.md C3). Hence
`validate_against: CorpusId | None`: a **per-call validation context**, never
persisted, scoped to validation display exactly as C3 describes. With it the
codelist tier runs; without it that tier is simply *not run* — not passed, not
failed — so a set stays freezable without ever naming a corpus.
"""

import json
from collections.abc import Sequence
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute

from ra2.domain.codelist_coverage import CoverageStatus
from ra2.domain.feature import (
    EXPLORATORY_FEATURE_CAP,
    DerivationSpec,
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    ValueType,
    derivation_from_json,
    derivation_to_json,
    is_scalar_grain,
    requires_codelist,
)
from ra2.domain.fingerprint import FingerprintInput, compute_fingerprint
from ra2.domain.ids import CorpusId, FeatureConfigId, FeatureId
from ra2.infra.clock import Clock
from ra2.infra.idgen import IdFactory
from ra2.persistence.models import Evaluation, Feature, FeatureConfig
from ra2.persistence.repositories.feature_repo import FeatureRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import (
    FeatureConfigFrozenError,
    FeatureValidationError,
    NotFoundError,
)
from ra2.services.protocols import EnumCodeTableProvider
from ra2.services.readmodels import FeatureConfigView, FeatureSetSummary, FeatureView

__all__ = [
    "FEATURE_ERROR_CLONE_OF_DRAFT",
    "FEATURE_ERROR_EXPLORATORY_CAP",
    "FEATURE_ERROR_NON_SCALAR_GRAIN",
    "FEATURE_ERROR_NO_CODELIST",
    "FeatureService",
]

#: The `NotFoundError.kind` for a missing feature set — a stable identifier the
#: API and UI switch on, the way `FindingCode` values are (CLAUDE.md).
_CONFIG_KIND: Final = "feature config"
_FEATURE_KIND: Final = "feature"

# --- validation messages ---------------------------------------------------
#
# `FeatureValidationError` and `FeatureView.validation_errors` are frozen as plain
# strings, so unlike a `Finding` there is no code to assert on. These four
# templates are therefore the stable identifiers: tests and the UI format
# them rather than re-typing the wording.

#: mvp-spec.md §8.2 / the design's "Damage per vehicle · non-scalar ERROR".
FEATURE_ERROR_NON_SCALAR_GRAIN: Final = (
    "{key}: a labelled feature must be scalar — {grain} grain is captured, not scored."
)
#: mvp-spec.md §8.1 — exploratory features are capped at 20 per set.
FEATURE_ERROR_EXPLORATORY_CAP: Final = (
    "{key}: exploratory features are capped at {cap} per feature set."
)
#: mvp-spec.md §7 / the design's "Right of way `VortrittAusw · no codes`".
FEATURE_ERROR_NO_CODELIST: Final = (
    "{key}: enum column {column} has no code table in the validation corpus."
)
#: A draft is already editable; cloning one would only duplicate it.
FEATURE_ERROR_CLONE_OF_DRAFT: Final = (
    "{name}: only a frozen feature set can be cloned; this one is still a draft."
)


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
        async with self._session_factory() as session:
            repo = FeatureRepository(session)
            configs = await repo.list_configs()
            # Two grouped counts rather than a query per row: the strip shows
            # every set, and `FeatureConfig.features` is not eagerly loaded by
            # `list_configs()` (touching it lazily under asyncio raises).
            feature_counts = await _counts_by_config(session, Feature.feature_config_id)
            evaluation_counts = await _counts_by_config(session, Evaluation.feature_config_id)
            return [
                FeatureSetSummary(
                    feature_config_id=FeatureConfigId(config.id),
                    name=config.name,
                    version=config.version,
                    description=config.description,
                    created_at=config.created_at,
                    feature_count=feature_counts.get(config.id, 0),
                    frozen_at=config.frozen_at,
                    locked_by_evaluations=evaluation_counts.get(config.id, 0),
                )
                for config in configs
            ]

    async def get(self, feature_config_id: FeatureConfigId) -> FeatureConfigView:
        """Raises `NotFoundError`."""
        async with self._session_factory() as session:
            return await self._view(session, feature_config_id, validate_against=None)

    async def create_draft(self, *, name: str, description: str | None = None) -> FeatureConfigView:
        async with session_scope(self._session_factory) as session:
            repo = FeatureRepository(session)
            config_id = FeatureConfigId(self._ids.new_id())
            await repo.add_config(
                FeatureConfig(
                    id=config_id,
                    name=name,
                    description=description,
                    version=await repo.next_version(name),
                    created_at=self._clock.now(),
                )
            )
            return await self._view(session, config_id, validate_against=None)

    async def rename(self, feature_config_id: FeatureConfigId, *, name: str) -> FeatureConfigView:
        """Draft only. Raises `FeatureConfigFrozenError`."""
        async with session_scope(self._session_factory) as session:
            repo = FeatureRepository(session)
            config = await self._editable(repo, feature_config_id)
            if name != config.name:
                # `uq_feature_config_name_version` is on `(name, version)`, so
                # renaming into a name that already has a v1 would otherwise
                # surface as a raw `IntegrityError`. Re-deriving the version
                # for the new name is what `next_version` is for, and it keeps
                # the design's "Weather & conditions v3" numbering per name.
                config.version = await repo.next_version(name)
                config.name = name
            return await self._view(session, feature_config_id, validate_against=None)

    async def delete(self, feature_config_id: FeatureConfigId) -> None:
        """Draft only. Raises `FeatureConfigFrozenError`."""
        async with session_scope(self._session_factory) as session:
            repo = FeatureRepository(session)
            # The FK's RESTRICT protects a cited frozen config anyway; checking
            # `frozen_at` here is what turns that into a clean 409 instead of
            # an `IntegrityError` surfacing from the flush.
            await self._editable(repo, feature_config_id)
            await repo.delete_config(feature_config_id)

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
        validate_against: CorpusId | None = None,
    ) -> FeatureConfigView:
        """Validates as it goes (mvp-spec.md §7/§8.2: unmapped/codeless enum,
        non-scalar grain, the 20-item exploratory cap) — problems surface as
        errors on the returned view, they do not raise. Only `freeze()`
        blocks on them.

        :param validate_against: the corpus the codelist tier is checked
            against. `None` skips that tier entirely (module docstring).
        :raises FeatureConfigFrozenError: the set is already frozen.
        """
        async with session_scope(self._session_factory) as session:
            repo = FeatureRepository(session)
            await self._editable(repo, feature_config_id)
            existing = await repo.list_features(feature_config_id)
            await repo.add_feature(
                Feature(
                    id=FeatureId(self._ids.new_id()),
                    feature_config_id=feature_config_id,
                    # Ordinals stay dense: `delete_feature` compacts them, so
                    # the count is always the next free slot.
                    ordinal=len(existing),
                    key=key,
                    kind=kind,
                    description=description,
                    grain=grain,
                    source_column=source_column,
                    derivation_json=_derivation_json(derivation),
                    value_type=value_type,
                    matching_rule=matching_rule_json(matching_rule),
                    # §8.5's snapshot is taken when an evaluation is created;
                    # phase 2 has no evaluation to take one, so the real
                    # fingerprint hashes `null` here too.
                    enum_codelist_json=None,
                    fingerprint=None,
                )
            )
            return await self._view(session, feature_config_id, validate_against=validate_against)

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
        validate_against: CorpusId | None = None,
    ) -> FeatureConfigView:
        """Draft only. Raises `FeatureConfigFrozenError`.

        Like `add_feature`, validation problems come back on the view rather
        than raising — a draft is allowed to hold an error row.
        """
        async with session_scope(self._session_factory) as session:
            repo = FeatureRepository(session)
            await self._editable(repo, feature_config_id)
            feature = await self._feature_of(repo, feature_config_id, feature_id)
            feature.key = key
            feature.kind = kind
            feature.description = description
            feature.grain = grain
            feature.source_column = source_column
            feature.derivation_json = _derivation_json(derivation)
            feature.value_type = value_type
            feature.matching_rule = matching_rule_json(matching_rule)
            await session.flush()
            return await self._view(session, feature_config_id, validate_against=validate_against)

    async def delete_feature(
        self, feature_config_id: FeatureConfigId, feature_id: FeatureId
    ) -> None:
        """Draft only. Raises `FeatureConfigFrozenError`."""
        async with session_scope(self._session_factory) as session:
            repo = FeatureRepository(session)
            await self._editable(repo, feature_config_id)
            await self._feature_of(repo, feature_config_id, feature_id)
            await repo.delete_feature(feature_id)
            # Re-densify, so `ordinal` stays a gap-free display order and the
            # next `add_feature` cannot collide with a surviving row.
            for ordinal, feature in enumerate(await repo.list_features(feature_config_id)):
                feature.ordinal = ordinal
            await session.flush()

    async def freeze(
        self,
        feature_config_id: FeatureConfigId,
        *,
        validate_against: CorpusId | None = None,
    ) -> FeatureConfigView:
        """Computes and stores every feature's real fingerprint, one
        transaction (§8.5). Immutable from this point on (F2,
        plan-phase-2.md §15).

        :param validate_against: as `add_feature`. `None` leaves the codelist
            tier unrun — a feature set is corpus-independent by design and
            must stay freezable without naming one.
        :raises FeatureValidationError: a blocking error remains; nothing is
            frozen.
        :raises FeatureConfigFrozenError: it is frozen already.
        """
        async with session_scope(self._session_factory) as session:
            repo = FeatureRepository(session)
            await self._editable(repo, feature_config_id)
            features = await repo.list_features(feature_config_id)
            by_feature = await self._validation_errors(session, features, validate_against)
            blocking = [message for feature in features for message in by_feature[feature.id]]
            if blocking:
                # Raised inside `session_scope`, which rolls back: no
                # fingerprint and no `frozen_at` survives a blocked freeze.
                raise FeatureValidationError(blocking)
            for feature in features:
                feature.fingerprint = compute_fingerprint(_fingerprint_input(feature))
            await session.flush()
            await repo.freeze(feature_config_id, frozen_at=self._clock.now())
            return await self._view(session, feature_config_id, validate_against=validate_against)

    async def clone(self, feature_config_id: FeatureConfigId, *, name: str) -> FeatureConfigView:
        """A frozen set only, into a fresh draft with its own feature rows —
        no shared mutable state with the frozen original (design's C4,
        "Clone to new evaluation").

        :raises FeatureValidationError: the source is still a draft, which is
            editable already and so has nothing to clone into.
        """
        async with session_scope(self._session_factory) as session:
            repo = FeatureRepository(session)
            source = await repo.get_config(feature_config_id)
            if source is None:
                raise NotFoundError(_CONFIG_KIND, feature_config_id)
            if source.frozen_at is None:
                raise FeatureValidationError(
                    [FEATURE_ERROR_CLONE_OF_DRAFT.format(name=source.name)]
                )
            clone_id = FeatureConfigId(self._ids.new_id())
            clone = FeatureConfig(
                id=clone_id,
                name=name,
                description=source.description,
                version=await repo.next_version(name),
                created_at=self._clock.now(),
            )
            # Fresh `Feature` instances, never the source's: every copied
            # field is an immutable `str`/`int`/enum, so the two sets share
            # no object at all. A clone is a new draft, not a copy of
            # history, so the fingerprint and the §8.5 snapshot start empty.
            clone.features = [
                Feature(
                    id=FeatureId(self._ids.new_id()),
                    feature_config_id=clone_id,
                    ordinal=feature.ordinal,
                    key=feature.key,
                    kind=Kind(feature.kind),
                    description=feature.description,
                    grain=Grain(feature.grain),
                    source_column=feature.source_column,
                    derivation_json=feature.derivation_json,
                    value_type=ValueType(feature.value_type),
                    matching_rule=feature.matching_rule,
                    enum_codelist_json=None,
                    fingerprint=None,
                )
                for feature in await repo.list_features(feature_config_id)
            ]
            await repo.add_config(clone)
            return await self._view(session, clone_id, validate_against=None)

    # --- internals ---------------------------------------------------------

    async def _editable(
        self, repo: FeatureRepository, feature_config_id: FeatureConfigId
    ) -> FeatureConfig:
        """The config, or the two refusals every mutating path shares."""
        config = await repo.get_config(feature_config_id)
        if config is None:
            raise NotFoundError(_CONFIG_KIND, feature_config_id)
        if config.frozen_at is not None:
            raise FeatureConfigFrozenError(feature_config_id)
        return config

    async def _feature_of(
        self,
        repo: FeatureRepository,
        feature_config_id: FeatureConfigId,
        feature_id: FeatureId,
    ) -> Feature:
        """A feature *of this set* — a valid id belonging to another set is
        still a 404 here, not someone else's row edited by accident."""
        feature = await repo.get_feature(feature_id)
        if feature is None or feature.feature_config_id != feature_config_id:
            raise NotFoundError(_FEATURE_KIND, feature_id)
        return feature

    async def _view(
        self,
        session: AsyncSession,
        feature_config_id: FeatureConfigId,
        *,
        validate_against: CorpusId | None,
    ) -> FeatureConfigView:
        """The whole set, read back through the repository.

        Read back rather than assembled from what was just written: the
        features come from `list_features`, which is ordered by `ordinal` and
        sees the flush every mutating path above has already done.
        """
        repo = FeatureRepository(session)
        config = await repo.get_config(feature_config_id)
        if config is None:
            raise NotFoundError(_CONFIG_KIND, feature_config_id)
        features = await repo.list_features(feature_config_id)
        by_feature = await self._validation_errors(session, features, validate_against)
        return FeatureConfigView(
            feature_config_id=FeatureConfigId(config.id),
            name=config.name,
            version=config.version,
            description=config.description,
            created_at=config.created_at,
            frozen_at=config.frozen_at,
            locked_by_evaluations=await _count_citing_evaluations(session, feature_config_id),
            features=tuple(_feature_view(f, by_feature[f.id]) for f in features),
        )

    async def _validation_errors(
        self,
        session: AsyncSession,
        features: Sequence[Feature],
        validate_against: CorpusId | None,
    ) -> dict[str, tuple[str, ...]]:
        """Every blocking message, per feature id. Two tiers:

        **Corpus-independent**, always checked — a `LABELLED` feature at a
        non-scalar grain (mvp-spec.md §8.2), and every `EXPLORATORY` feature
        past `EXPLORATORY_FEATURE_CAP` (§8.1). The cap is a property of the
        draft, so it is reported on the offending rows — the ones past the
        cap in `ordinal` order — which is what the design's per-row error
        state renders.

        **Codelist**, checked only when `validate_against` names a corpus —
        an `enum` feature whose `source_column` has no mapping, or a mapping
        with no usable codes, in that corpus (mvp-spec.md §7).
        """
        errors: dict[str, list[str]] = {feature.id: [] for feature in features}
        exploratory_seen = 0
        for feature in features:
            kind = Kind(feature.kind)
            grain = Grain(feature.grain)
            if kind is Kind.LABELLED and not is_scalar_grain(grain):
                errors[feature.id].append(
                    FEATURE_ERROR_NON_SCALAR_GRAIN.format(key=feature.key, grain=grain.value)
                )
            if kind is Kind.EXPLORATORY:
                exploratory_seen += 1
                if exploratory_seen > EXPLORATORY_FEATURE_CAP:
                    errors[feature.id].append(
                        FEATURE_ERROR_EXPLORATORY_CAP.format(
                            key=feature.key, cap=EXPLORATORY_FEATURE_CAP
                        )
                    )
            if validate_against is None:
                continue
            # A feature with no `source_column` (a derived aggregate) has no
            # mapped column to ask about: its codes come from the derivation,
            # which nothing executes in phase 2 (plan-phase-2.md Q1). Not
            # checking is deliberate — inventing an error there would block a
            # legitimate `max_ordinal` feature.
            if not requires_codelist(ValueType(feature.value_type)) or not feature.source_column:
                continue
            # The provider is handed *this* session and this transaction, the
            # same contract `CensusMaterialiser` has: it must not open its own
            # and must not commit.
            coverage = await self._codelist_provider.coverage(
                session, validate_against, feature.source_column
            )
            if coverage is None or coverage.status is CoverageStatus.MISSING:
                errors[feature.id].append(
                    FEATURE_ERROR_NO_CODELIST.format(key=feature.key, column=feature.source_column)
                )
        return {feature_id: tuple(messages) for feature_id, messages in errors.items()}


# ---------------------------------------------------------------------------
# `MatchingRule` <-> JSON
#
# `domain.feature` ships a codec for `DerivationSpec` but not for
# `MatchingRule`, and `fingerprint.py`'s docstring puts "assembling the
# canonical form" on the caller. The M0-D8 convention `derivation_to_json`
# and `compute_fingerprint` both use is repeated here rather than borrowed
# from `dump_json`, which is compact but does **not** sort keys: everything
# that feeds the hash sorts, so that two writers of the same rule cannot
# produce two different fingerprints. Both the `feature.matching_rule` column
# and `FingerprintInput.matching_rule_json` read this one string, so a rule
# and its parameters travel together into the hash exactly as mvp-spec.md
# §8.5 requires.
# ---------------------------------------------------------------------------

_JSON_KWARGS: Final = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": False}


def matching_rule_json(rule: MatchingRule) -> str:
    """`{"decimal_precision":…,"kind":…,"tolerance_minutes":…}` (key-sorted).

    All three keys are always present, `null` included: a rule that drops its
    parameters when unset would hash differently from the same rule written
    out in full, and the fingerprint has to be stable across both.
    """
    payload = {
        "kind": rule.kind.value,
        "tolerance_minutes": rule.tolerance_minutes,
        "decimal_precision": rule.decimal_precision,
    }
    return json.dumps(payload, **_JSON_KWARGS)  # type: ignore[arg-type]


def matching_rule_from_json(payload: str) -> MatchingRule:
    """The exact inverse. Tolerant of a rule written before a parameter
    existed — a missing key reads as `None`, never as a crash."""
    data: dict[str, object] = json.loads(payload)
    return MatchingRule(
        kind=MatchingRuleKind(str(data["kind"])),
        tolerance_minutes=_optional_int(data.get("tolerance_minutes")),
        decimal_precision=_optional_int(data.get("decimal_precision")),
    )


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _derivation_json(derivation: DerivationSpec | None) -> str | None:
    return None if derivation is None else derivation_to_json(derivation)


def _fingerprint_input(feature: Feature) -> FingerprintInput:
    """mvp-spec.md §8.5's eight fields, from the row's current state.

    The same assembly serves the draft's preview and the real value stored at
    freeze — Q3's point being that the two differ only in the
    `enum_codelist_json` snapshot, which stays `None` until an evaluation
    exists to take one.
    """
    return FingerprintInput(
        kind=Kind(feature.kind),
        grain=Grain(feature.grain),
        source_column=feature.source_column,
        derivation_json=feature.derivation_json,
        value_type=ValueType(feature.value_type),
        matching_rule_json=feature.matching_rule,
        enum_codelist_json=feature.enum_codelist_json,
        description=feature.description,
    )


def _feature_view(feature: Feature, errors: tuple[str, ...]) -> FeatureView:
    """One row. The enums are coerced at this read boundary: they are mapped
    onto `String`, so SQLAlchemy hands back plain `str` after a round trip."""
    return FeatureView(
        feature_id=FeatureId(feature.id),
        feature_config_id=FeatureConfigId(feature.feature_config_id),
        ordinal=feature.ordinal,
        key=feature.key,
        kind=Kind(feature.kind),
        description=feature.description,
        grain=Grain(feature.grain),
        source_column=feature.source_column,
        derivation=(
            None
            if feature.derivation_json is None
            else derivation_from_json(feature.derivation_json)
        ),
        value_type=ValueType(feature.value_type),
        matching_rule=matching_rule_from_json(feature.matching_rule),
        # §8.5's snapshot is taken at evaluation creation; phase 2 never
        # writes one, so this is always `None` (readmodels.py).
        enum_codelist=None,
        fingerprint=feature.fingerprint,
        fingerprint_preview=compute_fingerprint(_fingerprint_input(feature)),
        validation_errors=errors,
    )


async def _counts_by_config(
    session: AsyncSession, column: InstrumentedAttribute[FeatureConfigId]
) -> dict[str, int]:
    """`feature_config_id` -> row count, for one table's FK column."""
    rows = await session.execute(select(column, func.count()).group_by(column))
    return dict(rows.all())  # type: ignore[arg-type]


async def _count_citing_evaluations(
    session: AsyncSession, feature_config_id: FeatureConfigId
) -> int:
    """How many evaluations cite this set — the `LOCKED · N eval` pill.

    `CorpusRepository` exposes the corpus equivalent as a repository method;
    `FeatureRepository` (D3's, frozen this wave) has no counterpart, so the
    same select lives here rather than in an amendment.
    """
    count = await session.scalar(
        select(func.count())
        .select_from(Evaluation)
        .where(Evaluation.feature_config_id == feature_config_id)
    )
    return count or 0

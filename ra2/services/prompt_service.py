# STUB — bodies owned by I1 (feat/p3-prompt-service). Not frozen.
"""Prompt template versions, copy-on-write (sw-design.md §15.1).

Implements `PromptResolver` (`services/protocols.py`) via `resolve()` — I3's
run worker is handed this class as that protocol and never imports it
directly, the same seam `EnumCodeTableProvider` gave phase 2.

**There is deliberately no `update_template`.** Saving is an `INSERT` at
`version + 1`; the previous row's `source` stays byte-identical, because the
runs citing it must keep resolving to the exact text they used. The absence of
the method is the contract — do not add one.

**The `evaluation_feature.enum_codelist_json` shape is this module's call.**
Nothing freezes it (CONTRACTS.md names the column, not its JSON schema), and
`EvaluationService.launch` (I2) is the writer while `resolve()` below is the
first reader — per plan-phase-3.md §12's Wave 2 dependency order (I1 merges
before I2), this module is where the shape gets decided rather than
discovered twice. It is a JSON array, in snapshot order, one object per code:
`[{"code": "01", "label": {"de": "...", "fr": "..."}}, ...]` — the same
`code`/`label` shape `codelist_service` already writes for a `CodeValue`
(`ra2.domain.codes.CodeValue`), just flattened into a list instead of one row
per attribute. I2 must write this shape (or this module's amendment/parser
updates in the same integration step).
"""

import json
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.codes import CodeValue as DomainCodeValue
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.ids import (
    CodeAttributeId,
    CorpusId,
    EvaluationId,
    FeatureConfigId,
    PromptTemplateId,
    RecordId,
)
from ra2.domain.prompt import (
    SLOTS,
    FeatureBlockEntry,
    ResolvedPrompt,
    SlotName,
    compute_template_fingerprint,
    render_feature_block,
    resolve_template,
    validate_template,
)
from ra2.infra.clock import Clock
from ra2.infra.idgen import IdFactory
from ra2.persistence.models import Feature, PromptTemplate, Record
from ra2.persistence.repositories.codelist_repo import CodelistRepository
from ra2.persistence.repositories.evaluation_repo import EvaluationRepository
from ra2.persistence.repositories.feature_repo import FeatureRepository
from ra2.persistence.repositories.prompt_repo import PromptRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import (
    NotFoundError,
    PromptTemplateCitedError,
    PromptTemplateInvalidError,
)
from ra2.services.readmodels import PromptTemplateView, ResolvedPromptView, SlotView

__all__ = ["PromptService"]

#: `NotFoundError.kind` values — stable, snake_case identifiers (the
#: `codelist_service` convention: "code_attribute", "census_column").
_KIND_TEMPLATE: Final = "prompt_template"
_KIND_FEATURE_CONFIG: Final = "feature_config"
_KIND_RECORD: Final = "record"
_KIND_EVALUATION: Final = "evaluation"


class PromptService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        ids: IdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._ids = ids

    async def list_versions(self) -> list[PromptTemplateView]:
        """Every version, newest first, each with its citation count.

        The count is `COUNT(run WHERE prompt_template_id = …)`, which is what
        makes `deletable` and the design's `locked` marker true rather than
        advisory.
        """
        async with self._session_factory() as session:
            repo = PromptRepository(session)
            templates = await repo.list_all()
            return [await _template_view(repo, template) for template in templates]

    async def get(self, prompt_template_id: PromptTemplateId) -> PromptTemplateView:
        """:raises NotFoundError: no such version."""
        async with self._session_factory() as session:
            repo = PromptRepository(session)
            template = await repo.get(prompt_template_id)
            if template is None:
                raise NotFoundError(_KIND_TEMPLATE, str(prompt_template_id))
            return await _template_view(repo, template)

    async def slots(self) -> list[SlotView]:
        """The closed catalogue as the reference strip renders it
        (`domain.prompt.SLOTS`). Never assembled in the view."""
        return [
            SlotView(
                name=slot.name,
                token=slot.token,
                required=slot.required,
                resolves_to=slot.description,
            )
            for slot in SLOTS
        ]

    async def save_as_next_version(self, source: str) -> PromptTemplateView:
        """**Copy-on-write.** Validate, then `INSERT` at `version + 1`.

        Never touches an existing row — not even an uncited one. The design's
        button says "Save as v5" for exactly this reason.

        :raises PromptTemplateInvalidError: `validate_template` refused it;
            nothing was written.
        """
        validation_errors = validate_template(source)
        if validation_errors:
            raise PromptTemplateInvalidError(validation_errors=validation_errors)

        async with session_scope(self._session_factory) as session:
            repo = PromptRepository(session)
            version = await repo.next_version()
            template = PromptTemplate(
                id=PromptTemplateId(self._ids.new_id()),
                version=version,
                source=source,
                created_at=self._clock.now(),
                fingerprint=compute_template_fingerprint(source),
            )
            await repo.add(template)
            # A brand-new id cannot yet be cited by any run.
            return PromptTemplateView(
                prompt_template_id=PromptTemplateId(template.id),
                version=template.version,
                source=template.source,
                created_at=template.created_at,
                is_active=template.activated_at is not None,
                cited_by_run_count=0,
                fingerprint=template.fingerprint,
            )

    async def activate(self, prompt_template_id: PromptTemplateId) -> PromptTemplateView:
        """Mark the version new evaluations default to. Activating one clears
        the other's `activated_at`, so exactly one row is active.

        :raises NotFoundError: no such version.
        """
        async with session_scope(self._session_factory) as session:
            repo = PromptRepository(session)
            existing = await repo.get(prompt_template_id)
            if existing is None:
                raise NotFoundError(_KIND_TEMPLATE, str(prompt_template_id))
            await repo.activate(prompt_template_id, activated_at=self._clock.now())
            updated = await repo.get(prompt_template_id)
            assert updated is not None  # just activated it, in this same session
            return await _template_view(repo, updated)

    async def delete(self, prompt_template_id: PromptTemplateId) -> None:
        """Delete a version **only when no run cites it**.

        :raises PromptTemplateCitedError: a run cites it; nothing deleted.
        :raises NotFoundError: no such version.
        """
        async with session_scope(self._session_factory) as session:
            repo = PromptRepository(session)
            existing = await repo.get(prompt_template_id)
            if existing is None:
                raise NotFoundError(_KIND_TEMPLATE, str(prompt_template_id))
            citation_count = await repo.citation_count(prompt_template_id)
            if citation_count > 0:
                raise PromptTemplateCitedError(str(prompt_template_id), citation_count)
            await repo.delete(prompt_template_id)

    async def preview(
        self,
        prompt_template_id: PromptTemplateId,
        feature_config_id: FeatureConfigId,
        record_id: RecordId,
        *,
        language: str,
    ) -> ResolvedPromptView:
        """Resolve a template against a feature set and one record.

        **Makes no model call** — both the Prompts toolbar's "Preview with
        record 1" and Evaluation's "Preview prompt" land here (C4). The token
        figure is `estimate_tokens`, rendered `≈ N`.

        Enum labels are resolved **live**, from the record's own corpus's
        current `column_mapping` — there is no evaluation yet to have
        snapshotted one. This is deliberately different from `resolve()`,
        which reads the evaluation's frozen snapshot instead; the two agree
        only when nothing has been re-mapped since the preview.

        :raises NotFoundError: no such template, feature set or record.
        """
        async with self._session_factory() as session:
            template = await PromptRepository(session).get(prompt_template_id)
            if template is None:
                raise NotFoundError(_KIND_TEMPLATE, str(prompt_template_id))

            config = await FeatureRepository(session).get_config(feature_config_id)
            if config is None:
                raise NotFoundError(_KIND_FEATURE_CONFIG, str(feature_config_id))

            record = await session.scalar(select(Record).where(Record.id == record_id))
            if record is None:
                raise NotFoundError(_KIND_RECORD, str(record_id))

            entries = [
                _feature_block_entry(
                    feature,
                    enum_codelist=await _live_enum_codelist(
                        session, CorpusId(record.corpus_id), feature.source_column
                    ),
                )
                for feature in config.features
            ]

            resolved = resolve_template(
                template.source,
                {
                    SlotName.FEATURE_BLOCK: render_feature_block(entries, language=language),
                    SlotName.NARRATIVE: record.text_raw or "",
                    SlotName.LANGUAGE: language,
                },
            )
            return ResolvedPromptView(
                text=resolved.text,
                token_estimate=resolved.token_estimate,
                record_key=record.unfall_uid,
                feature_count=len(config.features),
                slots_used=resolved.slots_used,
                validation_errors=validate_template(template.source),
            )

    async def resolve(
        self,
        session: AsyncSession,
        evaluation_id: EvaluationId,
        record_id: RecordId,
    ) -> ResolvedPrompt:
        """`PromptResolver` (`services/protocols.py`) — the worker's path.

        Resolves against the evaluation's *pinned* inputs: its template, its
        `evaluation_feature` snapshots and its `prompt_language`. Takes the
        caller's session and **never commits**: the worker owns the
        transaction boundary, one record at a time (sw-design.md §15.3).

        Feature order is the feature set's own `ordinal` order (via
        `FeatureConfig.features`), not `Evaluation.features`' insertion order
        (that relationship carries no `order_by`) — so two evaluations
        pinning the same feature set render the same feature block in the
        same order, which is exactly what "a dev run and a full run produce
        the same text for the same record" requires.

        :raises NotFoundError: no such evaluation, template, feature set or
            record.
        """
        evaluation = await EvaluationRepository(session).get(evaluation_id)
        if evaluation is None:
            raise NotFoundError(_KIND_EVALUATION, str(evaluation_id))
        if evaluation.prompt_template_id is None:
            raise NotFoundError(_KIND_TEMPLATE, str(evaluation_id))

        template = await PromptRepository(session).get(
            PromptTemplateId(evaluation.prompt_template_id)
        )
        if template is None:
            raise NotFoundError(_KIND_TEMPLATE, str(evaluation.prompt_template_id))

        record = await session.scalar(select(Record).where(Record.id == record_id))
        if record is None:
            raise NotFoundError(_KIND_RECORD, str(record_id))

        config = await FeatureRepository(session).get_config(
            FeatureConfigId(evaluation.feature_config_id)
        )
        if config is None:
            raise NotFoundError(_KIND_FEATURE_CONFIG, str(evaluation.feature_config_id))

        snapshot_by_feature_id = {ef.feature_id: ef for ef in evaluation.features}
        entries = [
            _feature_block_entry(
                feature,
                enum_codelist=_snapshot_enum_codelist(
                    snapshot_by_feature_id[feature.id].enum_codelist_json
                    if feature.id in snapshot_by_feature_id
                    else None
                ),
            )
            for feature in config.features
        ]

        return resolve_template(
            template.source,
            {
                SlotName.FEATURE_BLOCK: render_feature_block(
                    entries, language=evaluation.prompt_language
                ),
                SlotName.NARRATIVE: record.text_raw or "",
                SlotName.LANGUAGE: evaluation.prompt_language,
            },
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


async def _template_view(repo: PromptRepository, template: PromptTemplate) -> PromptTemplateView:
    citation_count = await repo.citation_count(PromptTemplateId(template.id))
    return PromptTemplateView(
        prompt_template_id=PromptTemplateId(template.id),
        version=template.version,
        source=template.source,
        created_at=template.created_at,
        is_active=template.activated_at is not None,
        cited_by_run_count=citation_count,
        fingerprint=template.fingerprint,
    )


def _feature_block_entry(
    feature: Feature, *, enum_codelist: tuple[DomainCodeValue, ...] | None
) -> FeatureBlockEntry:
    return FeatureBlockEntry(
        key=feature.key,
        kind=Kind(feature.kind),
        grain=Grain(feature.grain),
        value_type=ValueType(feature.value_type),
        description=feature.description,
        matching_rule=_matching_rule_from_json(feature.matching_rule),
        enum_codelist=enum_codelist,
    )


async def _live_enum_codelist(
    session: AsyncSession, corpus_id: CorpusId, source_column: str | None
) -> tuple[DomainCodeValue, ...] | None:
    """The mapped attribute's current full code table, or `None` if the
    feature is not an enum, is unmapped, or maps to nothing on record.

    Used only by `preview()` — `resolve()` reads the frozen snapshot instead
    (see the module docstring)."""
    if source_column is None:
        return None
    repo = CodelistRepository(session)
    mapping = await repo.get_mapping(corpus_id, source_column)
    if mapping is None:
        return None
    attribute = await repo.get_attribute(CodeAttributeId(mapping.code_attribute_id))
    if attribute is None:
        return None
    return tuple(
        DomainCodeValue(
            attribute_key=attribute.key,
            code=value.code,
            label=json.loads(value.label_json),
        )
        for value in attribute.values
    )


def _snapshot_enum_codelist(payload: str | None) -> tuple[DomainCodeValue, ...] | None:
    """The inverse of `EvaluationService.launch`'s `enum_codelist_json` write
    (see the module docstring for the agreed shape). `None`/empty payload
    means "not an enum feature" — `render_feature_block` renders the
    `key — type` line with no code list, exactly as it does when a live
    lookup in `preview()` finds nothing mapped."""
    if not payload:
        return None
    data = json.loads(payload)
    return tuple(
        DomainCodeValue(
            attribute_key=str(item.get("attribute_key", "")),
            code=str(item["code"]),
            label=dict(item.get("label", {})),
        )
        for item in data
    )


#: `domain.feature` ships a codec for `DerivationSpec` but not for
#: `MatchingRule` — `feature_service.py` wrote its own inverse
#: (`matching_rule_from_json`) rather than exporting one, so this is the
#: small, deliberate duplicate the M0-D8 convention already accepts (the same
#: reasoning `feature_service.py`'s own module docstring gives for not
#: reaching for `dump_json`). `FeatureBlockEntry.matching_rule` is otherwise
#: unused by `render_feature_block` today, but the field is not optional and
#: carrying the real rule (not a placeholder) keeps this module honest about
#: what a feature actually is.
def _matching_rule_from_json(payload: str) -> MatchingRule:
    data: dict[str, object] = json.loads(payload)
    return MatchingRule(
        kind=MatchingRuleKind(str(data["kind"])),
        tolerance_minutes=_optional_int(data.get("tolerance_minutes")),
        decimal_precision=_optional_int(data.get("decimal_precision")),
    )


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))

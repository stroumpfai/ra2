# STUB — bodies owned by I1 (feat/p3-prompt-service). Not frozen.
"""Prompt template versions, copy-on-write (sw-design.md §15.1).

Implements `PromptResolver` (`services/protocols.py`) via `resolve()` — I3's
run worker is handed this class as that protocol and never imports it
directly, the same seam `EnumCodeTableProvider` gave phase 2.

**There is deliberately no `update_template`.** Saving is an `INSERT` at
`version + 1`; the previous row's `source` stays byte-identical, because the
runs citing it must keep resolving to the exact text they used. The absence of
the method is the contract — do not add one.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import (
    EvaluationId,
    FeatureConfigId,
    PromptTemplateId,
    RecordId,
)
from ra2.domain.prompt import ResolvedPrompt
from ra2.infra.clock import Clock
from ra2.infra.idgen import IdFactory
from ra2.services.readmodels import PromptTemplateView, ResolvedPromptView, SlotView

__all__ = ["PromptService"]


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
        raise NotImplementedError

    async def get(self, prompt_template_id: PromptTemplateId) -> PromptTemplateView:
        """:raises NotFoundError: no such version."""
        raise NotImplementedError

    async def slots(self) -> list[SlotView]:
        """The closed catalogue as the reference strip renders it
        (`domain.prompt.SLOTS`). Never assembled in the view."""
        raise NotImplementedError

    async def save_as_next_version(self, source: str) -> PromptTemplateView:
        """**Copy-on-write.** Validate, then `INSERT` at `version + 1`.

        Never touches an existing row — not even an uncited one. The design's
        button says "Save as v5" for exactly this reason.

        :raises PromptTemplateInvalidError: `validate_template` refused it;
            nothing was written.
        """
        raise NotImplementedError

    async def activate(self, prompt_template_id: PromptTemplateId) -> PromptTemplateView:
        """Mark the version new evaluations default to. Activating one clears
        the other's `activated_at`, so exactly one row is active.

        :raises NotFoundError: no such version.
        """
        raise NotImplementedError

    async def delete(self, prompt_template_id: PromptTemplateId) -> None:
        """Delete a version **only when no run cites it**.

        :raises PromptTemplateCitedError: a run cites it; nothing deleted.
        :raises NotFoundError: no such version.
        """
        raise NotImplementedError

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

        :raises NotFoundError: no such template, feature set or record.
        """
        raise NotImplementedError

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
        """
        raise NotImplementedError

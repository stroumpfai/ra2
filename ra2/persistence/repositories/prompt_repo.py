# STUB — bodies owned by H3 (feat/p3-persistence). Not frozen.
"""Prompt template persistence — copy-on-write versions (sw-design.md §15.1).

`prompt_template` is **IMMUTABLE**: a save is `INSERT` at `version + 1`,
never an `UPDATE` (Do-NOT #2 by the same logic that protects `extraction`).
The one field this repository does mutate in place is `activated_at` —
activating a version clears every other row's flag first, so "exactly one row
non-null at a time" is an invariant this repository enforces, not a
convention callers must remember.

Deliberately **no `update_template`** method: the absence is the contract
(sw-design.md §15.1) — do not add one.

`citation_count()` is what makes `PromptTemplateView.deletable` and the
design's `locked` marker true rather than advisory (plan-phase-3.md §7's H3
section): it is a live `COUNT(run WHERE prompt_template_id = …)`, not a
cached flag that could go stale the moment a run is launched.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import PromptTemplateId
from ra2.persistence.models import PromptTemplate, Run

__all__ = ["PromptRepository"]


class PromptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, template: PromptTemplate) -> None:
        """Writes one new version. Copy-on-write means this is always an
        `INSERT` — never called against an id that already exists."""
        self._session.add(template)
        await self._session.flush()

    async def get(self, prompt_template_id: PromptTemplateId) -> PromptTemplate | None:
        stmt = select(PromptTemplate).where(PromptTemplate.id == prompt_template_id)
        result: PromptTemplate | None = await self._session.scalar(stmt)
        return result

    async def get_by_version(self, version: int) -> PromptTemplate | None:
        stmt = select(PromptTemplate).where(PromptTemplate.version == version)
        result: PromptTemplate | None = await self._session.scalar(stmt)
        return result

    async def list_all(self) -> list[PromptTemplate]:
        """Every version, newest first — the design's version list."""
        stmt = select(PromptTemplate).order_by(PromptTemplate.version.desc())
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_active(self) -> PromptTemplate | None:
        """The version new evaluations default to, or `None` before anything
        has ever been activated."""
        stmt = select(PromptTemplate).where(PromptTemplate.activated_at.is_not(None))
        result: PromptTemplate | None = await self._session.scalar(stmt)
        return result

    async def next_version(self) -> int:
        """`max(version) + 1` over the **whole** table.

        Unlike `FeatureRepository.next_version` (per feature-set *name*),
        this is one lineage with bare integers `v1…vN` and no grouping key
        (sw-design.md §15.1) — a template has no name to group by.
        """
        current_max = await self._session.scalar(select(func.max(PromptTemplate.version)))
        return (current_max or 0) + 1

    async def citation_count(self, prompt_template_id: PromptTemplateId) -> int:
        """`COUNT(run WHERE prompt_template_id = …)`.

        The live count, not a cache: it is what makes a version `locked`
        rather than merely presented as such.
        """
        count = await self._session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.prompt_template_id == prompt_template_id)
        )
        return int(count or 0)

    async def activate(
        self, prompt_template_id: PromptTemplateId, *, activated_at: datetime
    ) -> None:
        """Marks one version active, clearing every other row's flag first.

        "Exactly one row non-null at a time" (sw-design.md §15.1) — enforced
        here, in one flush, rather than left to callers to sequence
        correctly. No-op if the id is unknown (the `FeatureRepository`
        convention: the caller is expected to have checked existence first
        when that distinction matters).
        """
        target = await self.get(prompt_template_id)
        if target is None:
            return
        stmt = select(PromptTemplate).where(PromptTemplate.activated_at.is_not(None))
        for other in await self._session.scalars(stmt):
            other.activated_at = None
        target.activated_at = activated_at
        await self._session.flush()

    async def delete(self, prompt_template_id: PromptTemplateId) -> None:
        """Deletes a version. **Callers must check `citation_count()` first**
        and raise `PromptTemplateCitedError` themselves (sw-design.md §15.1);
        this method enforces nothing on its own — though the database's own
        `RESTRICT` on `run.prompt_template_id` is the second, unconditional
        guard if a caller ever skips the check. No-op if the id is unknown.
        """
        target = await self.get(prompt_template_id)
        if target is None:
            return
        await self._session.delete(target)
        await self._session.flush()

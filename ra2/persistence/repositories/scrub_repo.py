# NEW — feat/text-scrubbing. Not frozen.
"""Scrub lists and rule-set versions (sw-design.md §19.4, `SD63`).

Both tables are **IMMUTABLE**: an import is an `INSERT`, never an `UPDATE`.
`scrub_list` rows are reused by `(kind, sha256)`, so the same file imported
twice is one row; `scrub_ruleset` is copy-on-write at `version + 1`, and the
highest version is the active one.

Deliberately **no update and no delete** method on either: the absence is the
contract, as it is for `prompt_template` (§15.1). `corpus.scrub_ruleset_id`
is not a foreign key (revision `5b93f1f9617a`), and having no delete path is
what keeps that reference from dangling.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import ScrubListId, ScrubRulesetId
from ra2.domain.scrub import ListKind
from ra2.persistence.models import Corpus, ScrubList, ScrubRuleset

__all__ = ["ScrubRepository"]


class ScrubRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- lists ---------------------------------------------------------------

    async def add_list(self, scrub_list: ScrubList) -> None:
        self._session.add(scrub_list)
        await self._session.flush()

    async def get_list(self, scrub_list_id: ScrubListId) -> ScrubList | None:
        result: ScrubList | None = await self._session.get(ScrubList, scrub_list_id)
        return result

    async def find_list(self, kind: ListKind, sha256: str) -> ScrubList | None:
        """The row an identical upload already made, if any: the reuse key."""
        stmt = select(ScrubList).where(ScrubList.kind == kind, ScrubList.sha256 == sha256)
        result: ScrubList | None = await self._session.scalar(stmt)
        return result

    # --- rule sets -----------------------------------------------------------

    async def add_ruleset(self, ruleset: ScrubRuleset) -> None:
        """One new version. Always an `INSERT`, never against an existing id."""
        self._session.add(ruleset)
        await self._session.flush()

    async def get_ruleset(self, ruleset_id: ScrubRulesetId) -> ScrubRuleset | None:
        result: ScrubRuleset | None = await self._session.get(ScrubRuleset, ruleset_id)
        return result

    async def get_active(self) -> ScrubRuleset | None:
        """The highest version, or `None` before anything was imported."""
        stmt = select(ScrubRuleset).order_by(ScrubRuleset.version.desc()).limit(1)
        result: ScrubRuleset | None = await self._session.scalar(stmt)
        return result

    async def list_rulesets(self) -> list[ScrubRuleset]:
        """Every version, newest first: the Scrubbing screen's history."""
        stmt = select(ScrubRuleset).order_by(ScrubRuleset.version.desc())
        return list((await self._session.scalars(stmt)).all())

    async def next_version(self) -> int:
        current = await self._session.scalar(select(func.max(ScrubRuleset.version)))
        return (current or 0) + 1

    async def corpus_counts(self) -> dict[ScrubRulesetId, int]:
        """How many corpora each version scrubbed: the history's citation
        column. Versions no corpus cites are absent."""
        stmt = (
            select(Corpus.scrub_ruleset_id, func.count(Corpus.id))
            .where(Corpus.scrub_ruleset_id.is_not(None))
            .group_by(Corpus.scrub_ruleset_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {ScrubRulesetId(rid): count for rid, count in rows if rid is not None}

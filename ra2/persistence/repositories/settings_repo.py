"""`app_setting` persistence (sw-design.md SD43).

**Append-only, and it shows in the API.** There is `add` and there is
`latest`, and no update and no delete — `qualification_repo`'s shape. A save
adds a row and the newest per key wins; `just reset` is the one thing that
removes a row, and it removes the database with it.

Keys and values cross this boundary as plain strings: which keys exist, and
what a value must look like, is `domain.settings`' business and the service's,
not the database's.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.persistence.models import AppSetting

__all__ = ["SettingsRepository"]


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, setting_id: str, key: str, value_json: str, changed_at: datetime) -> None:
        self._session.add(
            AppSetting(id=setting_id, key=key, value_json=value_json, changed_at=changed_at)
        )
        await self._session.flush()

    async def latest(self) -> dict[str, str]:
        """The newest `value_json` per key, for every key ever stored.

        Newest by `changed_at`, then by id — a uuid7, so also in time order —
        for two rows stamped in the same instant. One query: a correlated
        "max per key" rather than a read per key, so an unknown key a newer
        build wrote costs nothing to skip.
        """
        newest = (
            select(AppSetting.key, func.max(AppSetting.changed_at).label("changed_at"))
            .group_by(AppSetting.key)
            .subquery()
        )
        stmt = (
            select(AppSetting)
            .join(
                newest,
                (AppSetting.key == newest.c.key) & (AppSetting.changed_at == newest.c.changed_at),
            )
            .order_by(AppSetting.key, AppSetting.id)
        )
        rows = (await self._session.scalars(stmt)).all()
        # Two rows for one key in the same instant: the later id wins, which the
        # ordering above puts last.
        return {row.key: row.value_json for row in rows}

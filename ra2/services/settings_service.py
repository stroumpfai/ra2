"""The settings an analyst changes from the product (sw-design.md SD43).

The LLM endpoint and its per-call timeout: the two the Models card's settings
dialog draws. `Settings` stays the bootstrap value it always was (§3) — built
once, injected, never mutated — and this service is what answers "what are
they **now**": the newest stored row when there is one, the environment's seed
when there is not.

**It satisfies `ConnectionSettings` structurally**, so `evaluation_service` and
`run_service` read it without importing it — `ScoreSubmitter`'s trick again.

**Held, not queried.** The values are resolved by `load()` and by each
accepted save, and held. Nothing on the record loop's path reads the database
for them (plan §4.2).

**Refusals, in order, and nothing is stored when one fires:**

1. a value `domain.settings` refuses — off loopback, malformed, a timeout
   below one second (`SettingRefusedError`, a code for `ui/` to word);
2. any run queued or running (`RunActiveError`): the live client is rebound on
   a save, and a rebind under a run would move its endpoint between two of its
   records while `run.llm_endpoint` pins one.

**A stored row that is refused on the way back in** — one written around this
service — is logged and **ignored**, and the seed stays in force. Not fatal:
an app that cannot start is one only a shell can fix, which is the cost this
whole slice exists to remove (`docs/risk-assesment.md` E3). N1 holds either
way, because the refused value never reaches a client. The log line carries
the code and never the value (`data-handling.md` §5.1).
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.extraction import RunStatus
from ra2.domain.settings import SettingKey, SettingRefusal, endpoint_refusal, timeout_refusal
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.infra.idgen import IdFactory
from ra2.persistence.repositories.run_repo import RunRepository
from ra2.persistence.repositories.settings_repo import SettingsRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import RunActiveError, SettingRefusedError
from ra2.services.lifecycle_service import ACTIVE_STATUSES

__all__ = ["SettingsService"]

_log = logging.getLogger(__name__)


class SettingsService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Clock,
        ids: IdFactory,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock
        self._ids = ids
        # The seed. What a host with no stored rows uses, and what a refused
        # stored row falls back to.
        self._endpoint = settings.llm_base_url
        self._timeout_s = settings.llm_timeout_s

    # --- ConnectionSettings --------------------------------------------------

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def timeout_s(self) -> int:
        return self._timeout_s

    # --- reads and writes ----------------------------------------------------

    async def load(self) -> None:
        """Resolve the stored values over the seed. Once at startup; a save
        keeps them current after that."""
        async with self._session_factory() as session:
            stored = await SettingsRepository(session).latest()
        for key, value_json in stored.items():
            if key not in SettingKey:
                # A newer build's key. Ignored, so its database still opens.
                _log.warning("app_setting: ignoring a key this build does not know")
                continue
            try:
                value = json.loads(value_json)
            except ValueError:
                _log.warning("app_setting: %s does not hold JSON; keeping the seed", key)
                continue
            self._apply_stored(SettingKey(key), value)

    async def save_connection(self, endpoint: str, timeout_s: int) -> None:
        """Store both values and make them current.

        :raises SettingRefusedError: a value `domain.settings` refuses.
        :raises RunActiveError: a run is queued or running.
        """
        for refusal in (endpoint_refusal(endpoint), timeout_refusal(timeout_s)):
            if refusal is not None:
                raise SettingRefusedError(refusal)
        async with session_scope(self._session_factory) as session:
            active = await RunRepository(session).first_with_status(ACTIVE_STATUSES)
            if active is not None:
                raise RunActiveError(str(active.id), RunStatus(active.status).value)
            repo = SettingsRepository(session)
            now = self._clock.now()
            await repo.add(self._ids.new_id(), SettingKey.LLM_BASE_URL, json.dumps(endpoint), now)
            await repo.add(self._ids.new_id(), SettingKey.LLM_TIMEOUT_S, json.dumps(timeout_s), now)
        # Only after the rows are committed: a failed save changes nothing.
        self._endpoint = endpoint
        self._timeout_s = timeout_s

    def _apply_stored(self, key: SettingKey, value: object) -> None:
        refusal: SettingRefusal | None
        if key is SettingKey.LLM_BASE_URL:
            refusal = (
                endpoint_refusal(value)
                if isinstance(value, str)
                else SettingRefusal.ENDPOINT_MALFORMED
            )
            if refusal is None:
                assert isinstance(value, str)
                self._endpoint = value
                return
        else:
            # `bool` is an `int`; a stored `true` is not a timeout.
            refusal = (
                timeout_refusal(value)
                if isinstance(value, int) and not isinstance(value, bool)
                else SettingRefusal.TIMEOUT_NOT_POSITIVE
            )
            if refusal is None:
                assert isinstance(value, int)
                self._timeout_s = value
                return
        _log.warning("app_setting: stored %s refused (%s); keeping the seed", key, refusal)

"""`SettingsService` — the endpoint and timeout an analyst saves (SD43).

Against a real migrated temp database, because the claims worth a test are
about rows: that a save **appends**, that the newest row beats the environment,
that a refused value leaves **no** row, and that a row written around the
service does not become policy.

The environment is always the `Settings` seed here, and every stored value is
chosen to differ from it — a test at the seed cannot tell "read the row" from
"fell back", which is how a setting goes unread unnoticed (SD42).
"""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import StaticEndpointProber, StaticModelCatalog
from tests.fixtures.scored_corpus import seed_scored_corpus

from ra2.domain.extraction import RunStatus
from ra2.domain.settings import SettingKey, SettingRefusal
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import StaticGpuProbe
from ra2.infra.idgen import Uuid7Factory
from ra2.persistence.models import AppSetting, Run
from ra2.persistence.repositories.settings_repo import SettingsRepository
from ra2.services.errors import RunActiveError, SettingRefusedError
from ra2.services.evaluation_service import EvaluationService
from ra2.services.protocols import ConnectionSettings
from ra2.services.settings_service import SettingsService

pytestmark = pytest.mark.backend

STORED_ENDPOINT = "http://127.0.0.1:11999/v1"
STORED_TIMEOUT = 45


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 9, 27, 12, 0, tzinfo=UTC))


@pytest.fixture
def make_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    backend_settings: Settings,
    clock: FrozenClock,
) -> Callable[[], SettingsService]:
    """A fresh service each call: a second one is what a restart looks like."""

    def _make() -> SettingsService:
        return SettingsService(
            session_factory=db_session_factory,
            clock=clock,
            ids=Uuid7Factory(),
            settings=backend_settings,
        )

    return _make


@pytest.fixture
def write_row(
    db_session_factory: async_sessionmaker[AsyncSession], clock: FrozenClock
) -> Callable[[str, object], Awaitable[None]]:
    """A row written **around** the service, the way only a hand-edited
    database or a newer build could — so the service's own refusals do not
    apply on the way in."""

    async def _write(key: str, value: object) -> None:
        async with db_session_factory() as session:
            await SettingsRepository(session).add(
                Uuid7Factory().new_id(), key, json.dumps(value), clock.now()
            )
            await session.commit()
        clock.advance(seconds=1)

    return _write


async def _row_count(db_session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with db_session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(AppSetting)) or 0)


def test_the_service_is_a_connection_settings_provider(
    make_service: Callable[[], SettingsService],
) -> None:
    """Structurally — `evaluation_service` and `run_service` never import it."""
    assert isinstance(make_service(), ConnectionSettings)


async def test_an_empty_store_reports_the_environment(
    make_service: Callable[[], SettingsService], backend_settings: Settings
) -> None:
    """D3's fallback: a host with no rows behaves exactly as before SD43."""
    service = make_service()
    await service.load()

    assert service.endpoint == backend_settings.llm_base_url
    assert service.timeout_s == backend_settings.llm_timeout_s


async def test_a_stored_endpoint_beats_the_environment(
    make_service: Callable[[], SettingsService],
    write_row: Callable[[str, object], Awaitable[None]],
    backend_settings: Settings,
) -> None:
    assert backend_settings.llm_base_url != STORED_ENDPOINT
    assert backend_settings.llm_timeout_s != STORED_TIMEOUT
    await write_row(SettingKey.LLM_BASE_URL, STORED_ENDPOINT)
    await write_row(SettingKey.LLM_TIMEOUT_S, STORED_TIMEOUT)

    service = make_service()
    await service.load()

    assert service.endpoint == STORED_ENDPOINT
    assert service.timeout_s == STORED_TIMEOUT


async def test_a_row_written_into_the_table_changes_what_connection_status_reports(
    make_service: Callable[[], SettingsService],
    write_row: Callable[[str, object], Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
    backend_settings: Settings,
    clock: FrozenClock,
) -> None:
    """Stage 2's exit, end to end through the service the Models card reads."""
    await write_row(SettingKey.LLM_BASE_URL, STORED_ENDPOINT)
    await write_row(SettingKey.LLM_TIMEOUT_S, STORED_TIMEOUT)
    connection = make_service()
    await connection.load()
    evaluation = EvaluationService(
        session_factory=db_session_factory,
        model_catalog=StaticModelCatalog(),
        endpoint_prober=StaticEndpointProber(),
        gpu_probe=StaticGpuProbe(),
        clock=clock,
        ids=Uuid7Factory(),
        settings=backend_settings,
        connection=connection,
    )

    view = await evaluation.connection_status()

    assert (view.endpoint, view.timeout_s) == (STORED_ENDPOINT, STORED_TIMEOUT)


async def test_a_save_is_current_at_once_and_survives_a_restart(
    make_service: Callable[[], SettingsService],
) -> None:
    service = make_service()
    await service.save_connection(STORED_ENDPOINT, STORED_TIMEOUT)

    assert (service.endpoint, service.timeout_s) == (STORED_ENDPOINT, STORED_TIMEOUT)
    restarted = make_service()
    await restarted.load()
    assert (restarted.endpoint, restarted.timeout_s) == (STORED_ENDPOINT, STORED_TIMEOUT)


async def test_a_save_appends_and_never_updates(
    make_service: Callable[[], SettingsService],
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> None:
    """D2: two saves leave four rows — two keys each — and the newest wins."""
    service = make_service()
    await service.save_connection("http://127.0.0.1:11111/v1", 30)
    clock.advance(seconds=1)
    await service.save_connection(STORED_ENDPOINT, STORED_TIMEOUT)

    assert await _row_count(db_session_factory) == 4
    restarted = make_service()
    await restarted.load()
    assert (restarted.endpoint, restarted.timeout_s) == (STORED_ENDPOINT, STORED_TIMEOUT)


@pytest.mark.parametrize(
    ("endpoint", "timeout_s", "refusal"),
    [
        ("http://0.0.0.0:11434/v1", 60, SettingRefusal.ENDPOINT_NOT_LOOPBACK),
        ("http://192.168.1.10:11434/v1", 60, SettingRefusal.ENDPOINT_NOT_LOOPBACK),
        ("not a url", 60, SettingRefusal.ENDPOINT_MALFORMED),
        (STORED_ENDPOINT, 0, SettingRefusal.TIMEOUT_NOT_POSITIVE),
    ],
)
async def test_a_refused_value_stores_nothing_and_changes_nothing(
    make_service: Callable[[], SettingsService],
    db_session_factory: async_sessionmaker[AsyncSession],
    backend_settings: Settings,
    endpoint: str,
    timeout_s: int,
    refusal: SettingRefusal,
) -> None:
    """D7: the third place the loopback rule is enforced, with no opt-out
    reachable. Asserted on the code, never the wording."""
    service = make_service()

    with pytest.raises(SettingRefusedError) as excinfo:
        await service.save_connection(endpoint, timeout_s)

    assert excinfo.value.refusal is refusal
    assert await _row_count(db_session_factory) == 0
    assert service.endpoint == backend_settings.llm_base_url
    assert service.timeout_s == backend_settings.llm_timeout_s


@pytest.mark.parametrize("status", [RunStatus.QUEUED, RunStatus.RUNNING])
async def test_a_save_is_refused_while_a_run_is_active(
    make_service: Callable[[], SettingsService],
    db_session_factory: async_sessionmaker[AsyncSession],
    backend_settings: Settings,
    status: RunStatus,
) -> None:
    """D6: a queued run counts too — it will execute against whichever client
    exists when it starts, and `run.llm_endpoint` pins one for all its
    records."""
    async with db_session_factory() as session:
        corpus = await seed_scored_corpus(session, records=4)
        run = await session.get(Run, corpus.run_ids[0])
        assert run is not None
        run.status = status
        await session.commit()
    service = make_service()

    with pytest.raises(RunActiveError) as excinfo:
        await service.save_connection(STORED_ENDPOINT, STORED_TIMEOUT)

    assert excinfo.value.status == status.value
    assert await _row_count(db_session_factory) == 0
    assert service.endpoint == backend_settings.llm_base_url


async def test_a_stored_non_loopback_row_is_refused_at_startup(
    make_service: Callable[[], SettingsService],
    write_row: Callable[[str, object], Awaitable[None]],
    backend_settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D7's other half. A row written around the service does not become
    policy: it is **ignored** and the seed stays — not fatal, because an app
    that cannot start is one only a shell can fix. The log names the code and
    never the value (`data-handling.md` §5.1)."""
    off_host = "http://10.0.0.5:11434/v1"
    await write_row(SettingKey.LLM_BASE_URL, off_host)
    await write_row(SettingKey.LLM_TIMEOUT_S, True)
    service = make_service()

    with caplog.at_level(logging.WARNING, logger="ra2.services.settings_service"):
        await service.load()

    assert service.endpoint == backend_settings.llm_base_url
    assert service.timeout_s == backend_settings.llm_timeout_s
    assert SettingRefusal.ENDPOINT_NOT_LOOPBACK.value in caplog.text
    assert SettingRefusal.TIMEOUT_NOT_POSITIVE.value in caplog.text
    assert off_host not in caplog.text


async def test_a_key_this_build_does_not_know_is_ignored(
    make_service: Callable[[], SettingsService],
    write_row: Callable[[str, object], Awaitable[None]],
    backend_settings: Settings,
) -> None:
    """A database written by a newer build still opens."""
    await write_row("a_future_setting", {"anything": 1})
    await write_row(SettingKey.LLM_TIMEOUT_S, STORED_TIMEOUT)
    service = make_service()

    await service.load()

    assert service.endpoint == backend_settings.llm_base_url
    assert service.timeout_s == STORED_TIMEOUT

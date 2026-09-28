"""The stored endpoint is the one the app **dials** after startup (SD43).

`test_settings_service.py` proves the service resolves and rebinds; this
proves `create_app()` wires it to the real client. A value the Models card
reports and a value the client uses are two claims, and only the second one
keeps a run off the wrong Ollama.

No Ollama and no private attribute: an asyncio listener on a free loopback
port **is** the stored endpoint, and the real `OllamaModelCatalog` inside the
real `OllamaConnection` either connects to it or does not. The listener hangs
up at once, so the catalogue reports the endpoint unreachable — which is
beside the point; that it knocked is the point.
"""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.settings import SettingKey
from ra2.infra.config import Settings
from ra2.infra.gpu import StaticGpuProbe
from ra2.infra.idgen import Uuid7Factory
from ra2.main import create_app
from ra2.persistence.repositories.settings_repo import SettingsRepository

pytestmark = pytest.mark.backend


async def test_after_startup_the_live_client_dials_the_stored_endpoint(
    run_upgrade_head: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    knocked = asyncio.Event()

    async def _hang_up(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        knocked.set()
        writer.close()
        await writer.wait_closed()

    listener = await asyncio.start_server(_hang_up, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    stored = f"http://127.0.0.1:{port}/v1"
    assert stored != run_upgrade_head.llm_base_url
    async with db_session_factory() as session:
        repo = SettingsRepository(session)
        now = datetime(2026, 9, 28, tzinfo=UTC)
        ids = Uuid7Factory()
        await repo.add(ids.new_id(), SettingKey.LLM_BASE_URL, json.dumps(stored), now)
        await repo.add(ids.new_id(), SettingKey.LLM_TIMEOUT_S, json.dumps(5), now)
        await session.commit()

    app = create_app(
        settings=run_upgrade_head,
        session_factory=db_session_factory,
        gpu_probe=StaticGpuProbe(),
        mount_ui=False,
    )
    async with listener, app.router.lifespan_context(app):
        services = app.state.services
        view = await services.evaluation.connection_status()
        await asyncio.wait_for(knocked.wait(), timeout=5)

    assert view.endpoint == stored
    assert view.timeout_s == 5

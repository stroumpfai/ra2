# FROZEN — see CONTRACTS.md
"""`create_app()` — the composition root. Wiring only, no logic.

Every implementation arrives as a **defaulted keyword argument**. Tests build
the app with substitutes (`FrozenClock`, `SeededFactory`, `InlineTaskRunner`,
`StubDetector`); production passes nothing and gets the real ones.

**There is no test-mode branch in production code** (sw-design.md §3, §12.12).
The E2E fixture starts a real server through this same function.

Order matters: the API routers are included **before** NiceGUI is mounted,
because `ui.run_with` mounts NiceGUI at `/` and a Mount at `/` matches every
path Starlette has not already matched.
"""

from fastapi import FastAPI
from nicegui import ui
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ra2.api.v1.router import api_router
from ra2.domain.language import LanguageDetector
from ra2.infra.clock import Clock, SystemClock
from ra2.infra.config import Settings
from ra2.infra.filestore import FileStore, HostPathFileStore, UploadedFileStore
from ra2.infra.idgen import IdFactory, Uuid7Factory
from ra2.infra.lingua_detector import LinguaDetector
from ra2.infra.tasks import AsyncioTaskRunner, TaskRunner
from ra2.persistence.session import create_engine, create_session_factory, ensure_database_dir
from ra2.services.census_materialiser import RelationalCensusMaterialiser
from ra2.services.census_service import CensusService
from ra2.services.container import Services
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.export_service import ExportService
from ra2.services.protocols import CensusMaterialiser
from ra2.ui import views
from ra2.ui.theme import FONTS_DIR, FONTS_URL_PATH

__all__ = ["create_app"]


def create_app(
    *,
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    clock: Clock | None = None,
    ids: IdFactory | None = None,
    task_runner: TaskRunner | None = None,
    upload_store: FileStore | None = None,
    host_path_store: FileStore | None = None,
    language_detector: LanguageDetector | None = None,
    census_materialiser: CensusMaterialiser | None = None,
    mount_ui: bool = True,
) -> FastAPI:
    """Build the application.

    :param mount_ui: mount NiceGUI. Defaults to on. Backend tests that drive
        only `/api/v1` through `httpx.ASGITransport` turn it off — NiceGUI's
        `core.app` is a process-wide singleton, so mounting it repeatedly in
        one test session accumulates middleware. This is a **composition-root
        parameter, not a branch inside production logic**: nothing downstream
        of here can tell which value was used.
    """
    settings = settings or Settings()
    clock = clock or SystemClock()
    ids = ids or Uuid7Factory()

    ensure_database_dir(settings.database_path)
    engine = engine or create_engine(settings.database_url)
    session_factory = session_factory or create_session_factory(engine)

    task_runner = task_runner or AsyncioTaskRunner(ids)
    upload_store = upload_store or UploadedFileStore(
        settings.deliveries_dir, max_bytes=settings.max_upload_bytes
    )
    host_path_store = host_path_store or HostPathFileStore()
    language_detector = language_detector or LinguaDetector()
    census_materialiser = census_materialiser or RelationalCensusMaterialiser(ids=ids)

    delivery_service = DeliveryService(
        session_factory=session_factory,
        upload_store=upload_store,
        host_path_store=host_path_store,
        task_runner=task_runner,
        clock=clock,
        ids=ids,
    )
    corpus_service = CorpusService(
        session_factory=session_factory,
        census_materialiser=census_materialiser,
        language_detector=language_detector,
        task_runner=task_runner,
        clock=clock,
        ids=ids,
        settings=settings,
    )
    census_service = CensusService(session_factory=session_factory)
    export_service = ExportService(
        census_service=census_service,
        delivery_service=delivery_service,
        corpus_service=corpus_service,
        clock=clock,
    )
    services = Services(
        delivery=delivery_service,
        corpus=corpus_service,
        census=census_service,
        export=export_service,
    )

    app = FastAPI(
        title="RA2",
        description="Road accident report analysis — import, census and evaluation.",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.services = services
    app.state.task_runner = task_runner
    app.state.engine = engine
    app.state.session_factory = session_factory

    # Routers first: NiceGUI mounts at "/" and would otherwise shadow them.
    app.include_router(api_router)

    if mount_ui:
        views.register_all(services)
        # Fonts are served by the app. No CDN, no Google Fonts (N1, SD3).
        from nicegui import app as nicegui_app  # noqa: PLC0415 - mount-time only

        nicegui_app.add_static_files(FONTS_URL_PATH, str(FONTS_DIR))
        ui.run_with(app, title="RA2", storage_secret=settings.storage_secret, dark=False)

    return app

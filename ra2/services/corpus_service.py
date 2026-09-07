# FROZEN (constructor + signatures) — bodies owned by B1 (feat/m3-delivery-corpus)
"""Freeze a selection into an immutable corpus; list; delete-guard (§6.3)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import CorpusId, DeliveryId
from ra2.domain.language import LanguageDetector
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import TaskRunner
from ra2.services.protocols import CensusMaterialiser
from ra2.services.readmodels import CorpusView, Page, SortDir

__all__ = ["CorpusService"]


class CorpusService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        census_materialiser: CensusMaterialiser,
        language_detector: LanguageDetector,
        task_runner: TaskRunner,
        clock: Clock,
        ids: IdFactory,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._census_materialiser = census_materialiser
        self._language_detector = language_detector
        self._task_runner = task_runner
        self._clock = clock
        self._ids = ids
        self._settings = settings

    async def freeze(
        self,
        delivery_id: DeliveryId,
        *,
        name: str,
        description: str | None = None,
    ) -> CorpusId:
        """One transaction, all-or-nothing (sw-design.md §6.3).

        1. Cross-file **blocking** validation over the *selected* files. Any
           failure -> `BlockingFindingsError`, **nothing written**.
        2. Write `corpus`, `record` and the EAV rows.
        3. Per-record language detection; low confidence stored as `mixed`.
        4. Corpus-level cp1252 canary count. One number, no per-record markers.
        5. Non-blocking findings into `import_report_json`.
        6. The census, via `CensusMaterialiser` on this same session.
        7. `is_dev_sized` from `RA2_DEV_RECORD_MAX` / `RA2_EVAL_RECORD_MIN`.

        :raises BlockingFindingsError: validation refused; zero corpus rows.
        :raises DeliveryNotAnalysedError: analysis has not finished.
        """
        raise NotImplementedError

    async def get(self, corpus_id: CorpusId) -> CorpusView:
        """Raises `NotFoundError`."""
        raise NotImplementedError

    async def list_corpora(
        self,
        *,
        sort_key: str = "imported_at",
        sort_dir: SortDir = SortDir.DESC,
        page: int = 1,
        page_size: int = 10,
    ) -> Page[CorpusView]:
        """Sort and page are service-call parameters, always (§8.4)."""
        raise NotImplementedError

    async def delete(self, corpus_id: CorpusId) -> None:
        """Refused when any evaluation cites the corpus.

        The runs that cite it would stop being reproducible.

        :raises CorpusLockedError: -> HTTP 409, UI "delete blocked" (J3).
        """
        raise NotImplementedError

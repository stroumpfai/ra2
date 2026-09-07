# FROZEN (constructor + signatures) — see CONTRACTS.md; bodies owned by B1
"""Register, analyse, re-parse, select (sw-design.md §6.1, §6.2).

Analyse writes only to `delivery_file`. **No corpus rows.**
"""

from pathlib import Path
from typing import BinaryIO

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.delivery import Encoding, SourceKind
from ra2.domain.ids import DeliveryId, FileId, TaskId
from ra2.infra.clock import Clock
from ra2.infra.filestore import FileStore
from ra2.infra.idgen import IdFactory
from ra2.infra.tasks import TaskRunner
from ra2.services.readmodels import DeliveryFileView, DeliveryView

__all__ = ["DeliveryService"]


class DeliveryService:
    """Every seam arrives through the constructor; nothing is a global (§3)."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        upload_store: FileStore,
        host_path_store: FileStore,
        task_runner: TaskRunner,
        clock: Clock,
        ids: IdFactory,
    ) -> None:
        self._session_factory = session_factory
        self._upload_store = upload_store
        self._host_path_store = host_path_store
        self._task_runner = task_runner
        self._clock = clock
        self._ids = ids

    # --- intake (sw-design.md §6.1) ----------------------------------------

    async def register(
        self,
        name: str,
        *,
        source_kind: SourceKind,
        root_path: Path | None = None,
    ) -> DeliveryId:
        """Create the staging area. `root_path` is required for `HOST_PATH`
        and must be absent for `UPLOAD`."""
        raise NotImplementedError

    async def add_file(self, delivery_id: DeliveryId, filename: str, content: BinaryIO) -> FileId:
        """Upload intake. Streamed, bounded by `RA2_MAX_UPLOAD_MB`.

        Raises `ReadOnlyFileStoreError` on a host-path delivery, whose files
        are registered in place rather than received.
        """
        raise NotImplementedError

    async def remove_file(self, delivery_id: DeliveryId, file_id: FileId) -> None:
        """The file report modal's "remove" (sw-design.md §8.3)."""
        raise NotImplementedError

    # --- analyse (sw-design.md §6.2) ---------------------------------------

    async def analyse(self, delivery_id: DeliveryId) -> TaskId:
        """Analyse every file, through `TaskRunner`, with progress.

        Idempotent and re-runnable. Returns immediately; the UI polls
        `GET /api/v1/tasks/{id}`.
        """
        raise NotImplementedError

    async def reparse_file(
        self,
        delivery_id: DeliveryId,
        file_id: FileId,
        *,
        encoding: Encoding | None = None,
        delimiter: str | None = None,
        quote_char: str | None = None,
    ) -> DeliveryFileView:
        """Re-run analysis for **one file alone** after an override.

        `None` means "keep what is effective now". Changes that file's row and
        no other — there is a test that asserts exactly that.
        """
        raise NotImplementedError

    # --- selection ---------------------------------------------------------

    async def set_selected(
        self, delivery_id: DeliveryId, file_id: FileId, *, selected: bool
    ) -> DeliveryView:
        """Deselected files stay in the list and are excluded from the corpus.

        Returns the whole delivery so the header count and the
        "Create corpus · N records" label both recompute from one call.
        """
        raise NotImplementedError

    # --- reads -------------------------------------------------------------

    async def get(self, delivery_id: DeliveryId) -> DeliveryView:
        """Raises `NotFoundError`."""
        raise NotImplementedError

    async def list_deliveries(self) -> tuple[DeliveryView, ...]:
        raise NotImplementedError

# FROZEN (protocol) — see CONTRACTS.md
"""The `FileStore` seam — both intake paths behind one interface (§6.1).

- **Upload**: NiceGUI `ui.upload`, streamed to
  `{data_dir}/deliveries/{delivery_id}/`, bounded by `RA2_MAX_UPLOAD_MB`.
- **Host path**: the analyst names a directory on this machine; files are
  registered **in place, not copied**.

Nothing downstream knows which was used — `delivery_file` rows come out
identical either way.

A host-path store is read-only: `accept()` raises `ReadOnlyFileStoreError`.
A4's parametrised contract test asserts exactly that, so both implementations
run the same test.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from ra2.domain.ids import DeliveryId, FileId

__all__ = [
    "FileStore",
    "FileStoreError",
    "HostPathFileStore",
    "ReadOnlyFileStoreError",
    "StoredFile",
    "UploadedFileStore",
]


class FileStoreError(Exception):
    """Anything the store cannot do."""


class ReadOnlyFileStoreError(FileStoreError):
    """Raised by `accept()` on a store that registers files in place."""


@dataclass(frozen=True, slots=True)
class StoredFile:
    """One file of one delivery, wherever it physically lives."""

    file_id: FileId
    filename: str
    #: Relative to the delivery's root. The key for `read_bytes`/`remove`, and
    #: what goes into `delivery_file.relative_path`.
    relative_path: str
    byte_size: int
    #: Hex sha256 of the bytes. Provenance, and the cheap re-parse guard.
    sha256: str


@runtime_checkable
class FileStore(Protocol):
    """Read access to a delivery's files, plus intake where supported."""

    async def accept(
        self, delivery_id: DeliveryId, filename: str, content: BinaryIO
    ) -> StoredFile:
        """Take a file into the store, streaming from `content`.

        Raises `ReadOnlyFileStoreError` on a host-path store, which registers
        files in place rather than receiving them.
        """
        ...

    async def list_files(self, delivery_id: DeliveryId) -> tuple[StoredFile, ...]:
        """Every file of this delivery, with sizes and digests computed."""
        ...

    async def read_bytes(self, delivery_id: DeliveryId, relative_path: str) -> bytes:
        """Raw bytes. Decoding is the parser's job — the store never guesses an
        encoding, and never opens anything in text mode (N4)."""
        ...

    async def remove(self, delivery_id: DeliveryId, relative_path: str) -> None:
        """Drop a file from the delivery. Raises `ReadOnlyFileStoreError` where
        the files are the analyst's own."""
        ...


# --- STUB implementations — bodies owned by A4 (feat/m2-infra). Not frozen. ---


class UploadedFileStore:
    """Streams uploads to `{data_dir}/deliveries/{delivery_id}/`."""

    def __init__(self, deliveries_dir: Path, *, max_bytes: int) -> None:
        self._root = deliveries_dir
        self._max_bytes = max_bytes

    async def accept(
        self, delivery_id: DeliveryId, filename: str, content: BinaryIO
    ) -> StoredFile:
        raise NotImplementedError

    async def list_files(self, delivery_id: DeliveryId) -> tuple[StoredFile, ...]:
        raise NotImplementedError

    async def read_bytes(self, delivery_id: DeliveryId, relative_path: str) -> bytes:
        raise NotImplementedError

    async def remove(self, delivery_id: DeliveryId, relative_path: str) -> None:
        raise NotImplementedError


class HostPathFileStore:
    """Registers the analyst's own files in place. Never copies, never writes."""

    def __init__(self, roots: Mapping[DeliveryId, Path] | None = None) -> None:
        self._roots: dict[DeliveryId, Path] = dict(roots or {})

    def bind(self, delivery_id: DeliveryId, root: Path) -> None:
        """Record which host directory a delivery was registered from."""
        self._roots[delivery_id] = root

    async def accept(
        self, delivery_id: DeliveryId, filename: str, content: BinaryIO
    ) -> StoredFile:
        raise ReadOnlyFileStoreError(
            "a host-path delivery registers files in place; it never receives them"
        )

    async def list_files(self, delivery_id: DeliveryId) -> tuple[StoredFile, ...]:
        raise NotImplementedError

    async def read_bytes(self, delivery_id: DeliveryId, relative_path: str) -> bytes:
        raise NotImplementedError

    async def remove(self, delivery_id: DeliveryId, relative_path: str) -> None:
        raise ReadOnlyFileStoreError("a host-path delivery never deletes the analyst's files")

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

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from ra2.domain.ids import DeliveryId, FileId
from ra2.infra.files import open_binary_reader, open_binary_writer
from ra2.infra.files import read_bytes as files_read_bytes

#: Streamed in bounded chunks so `accept()` never buffers a whole upload.
_CHUNK_BYTES = 1024 * 1024

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

    async def accept(self, delivery_id: DeliveryId, filename: str, content: BinaryIO) -> StoredFile:
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

    async def accept(self, delivery_id: DeliveryId, filename: str, content: BinaryIO) -> StoredFile:
        # Only the basename: an upload's filename is analyst-supplied and
        # must never be allowed to escape the delivery's own directory.
        safe_name = Path(filename).name
        if not safe_name:
            raise FileStoreError(f"empty filename for delivery {delivery_id!r}")

        dest = self._root / delivery_id / safe_name
        digest = hashlib.sha256()
        size = 0
        with open_binary_writer(dest) as out:
            while chunk := content.read(_CHUNK_BYTES):
                size += len(chunk)
                if size > self._max_bytes:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise FileStoreError(
                        f"{filename!r} exceeds the {self._max_bytes}-byte upload limit"
                    )
                digest.update(chunk)
                out.write(chunk)

        return StoredFile(
            file_id=FileId(safe_name),
            filename=filename,
            relative_path=safe_name,
            byte_size=size,
            sha256=digest.hexdigest(),
        )

    async def list_files(self, delivery_id: DeliveryId) -> tuple[StoredFile, ...]:
        root = self._root / delivery_id
        if not root.is_dir():
            return ()
        return tuple(_stat_file(path, root) for path in sorted(root.rglob("*")) if path.is_file())

    async def read_bytes(self, delivery_id: DeliveryId, relative_path: str) -> bytes:
        return files_read_bytes(_resolve(self._root / delivery_id, relative_path))

    async def remove(self, delivery_id: DeliveryId, relative_path: str) -> None:
        path = _resolve(self._root / delivery_id, relative_path)
        if not path.is_file():
            raise FileStoreError(f"{relative_path!r} is not in delivery {delivery_id!r}")
        path.unlink()


class HostPathRefusedError(FileStoreError):
    """A host-path registration this store will not walk (`SD49`, risk A4).

    `reason` is a stable code, like a `FindingCode`: the message is for a
    person and the code is for a test. Raised **before** anything is written,
    and a walk that meets a bound stops there rather than finishing the tree.
    """

    OUTSIDE_IMPORT_ROOT = "outside_import_root"
    TOO_MANY_FILES = "too_many_files"
    TOO_MANY_BYTES = "too_many_bytes"
    LINK_LEAVES_ROOT = "link_leaves_root"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class HostPathFileStore:
    """Registers the analyst's own files in place. Never copies, never writes.

    `SD49`, risk A4. Given an `allowed_root`, a delivery may be registered
    from that directory or beneath it and from nowhere else. Given
    `max_files` / `max_bytes`, the walk that hashes every file stops at the
    first file past either. Without them it behaves as it always did, which is
    what a test that builds its own store gets; `create_app()` always passes
    all three, from `Settings`.
    """

    def __init__(
        self,
        roots: Mapping[DeliveryId, Path] | None = None,
        *,
        allowed_root: Path | None = None,
        max_files: int | None = None,
        max_bytes: int | None = None,
    ) -> None:
        self._roots: dict[DeliveryId, Path] = dict(roots or {})
        self._allowed_root = allowed_root
        self._max_files = max_files
        self._max_bytes = max_bytes

    def bind(self, delivery_id: DeliveryId, root: Path) -> None:
        """Record which host directory a delivery was registered from.

        Refuses a root outside `allowed_root` before anything is read. The
        comparison is on resolved paths, so `import/../../home` and a link
        named inside the root that points out of it are both outside.
        """
        if self._allowed_root is not None and not _within(root, self._allowed_root):
            raise HostPathRefusedError(
                HostPathRefusedError.OUTSIDE_IMPORT_ROOT,
                f"{root} is outside the import directory {self._allowed_root}. "
                "Copy the delivery into it, or upload the files.",
            )
        self._roots[delivery_id] = root

    def restore(self, delivery_id: DeliveryId, root: Path) -> None:
        """Rebind a delivery registered **earlier**, from its stored root.

        The bindings live in memory, so a restarted process knew none of them
        and could not re-read an analysed delivery to freeze it. The services
        restore the binding from `delivery.root_path` before each use.
        **Not** re-checked against `allowed_root`: that rule applies at
        registration (`SD49`), and a delivery registered before it, or before
        the root moved, has to stay readable rather than become a dead row.
        """
        self._roots[delivery_id] = root

    async def accept(self, delivery_id: DeliveryId, filename: str, content: BinaryIO) -> StoredFile:
        raise ReadOnlyFileStoreError(
            "a host-path delivery registers files in place; it never receives them"
        )

    async def list_files(self, delivery_id: DeliveryId) -> tuple[StoredFile, ...]:
        """Every file under the root, hashed in chunks, within the bounds.

        The bounds are checked on sizes from `stat`, **before** any file is
        hashed, and the walk stops at the first file past either. A file whose
        real path leaves the root (a link out of it) is refused rather than
        skipped: a skipped file would be a silent drop (Do-NOT #6).
        """
        root = self._root_for(delivery_id)
        paths: list[Path] = []
        total = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if not _within(path, root):
                raise HostPathRefusedError(
                    HostPathRefusedError.LINK_LEAVES_ROOT,
                    f"{path.relative_to(root).as_posix()} links outside {root}.",
                )
            paths.append(path)
            total += path.stat().st_size
            if self._max_files is not None and len(paths) > self._max_files:
                raise HostPathRefusedError(
                    HostPathRefusedError.TOO_MANY_FILES,
                    f"{root} holds more than {self._max_files} files, the most one "
                    "delivery may register (RA2_IMPORT_MAX_FILES). Is it the delivery's "
                    "own directory?",
                )
            if self._max_bytes is not None and total > self._max_bytes:
                raise HostPathRefusedError(
                    HostPathRefusedError.TOO_MANY_BYTES,
                    f"{root} holds more than {self._max_bytes / 1e9:g} GB, the most one "
                    "delivery may register (RA2_IMPORT_MAX_GB). Is it the delivery's "
                    "own directory?",
                )
        return tuple(_stat_file(path, root) for path in sorted(paths))

    async def read_bytes(self, delivery_id: DeliveryId, relative_path: str) -> bytes:
        root = self._root_for(delivery_id)
        return files_read_bytes(_resolve(root, relative_path))

    async def remove(self, delivery_id: DeliveryId, relative_path: str) -> None:
        raise ReadOnlyFileStoreError("a host-path delivery never deletes the analyst's files")

    def _root_for(self, delivery_id: DeliveryId) -> Path:
        try:
            return self._roots[delivery_id]
        except KeyError:
            raise FileStoreError(f"no host path registered for delivery {delivery_id!r}") from None


def _stat_file(path: Path, root: Path) -> StoredFile:
    """One `StoredFile` for a file already sitting on disk.

    `file_id` is the relative path: neither store is handed an `IdFactory`
    (only `DeliveryService`, via B1, mints the `FileId` that becomes the
    `delivery_file` primary key), so this is a stable, store-local identity
    rather than that final id.
    """
    relative_path = path.relative_to(root).as_posix()
    # In chunks: a delivery file can be hundreds of MB, and the digest needs
    # none of it held at once (risk A4's "reads every file fully").
    digest = hashlib.sha256()
    size = 0
    with open_binary_reader(path) as source:
        while chunk := source.read(_CHUNK_BYTES):
            size += len(chunk)
            digest.update(chunk)
    return StoredFile(
        file_id=FileId(relative_path),
        filename=path.name,
        relative_path=relative_path,
        byte_size=size,
        sha256=digest.hexdigest(),
    )


def _within(path: Path, root: Path) -> bool:
    """`path` is `root` or beneath it, compared on **resolved** paths."""
    resolved, base = path.resolve(), root.resolve()
    return resolved == base or base in resolved.parents


def _resolve(root: Path, relative_path: str) -> Path:
    """`root / relative_path`, refusing to leave `root` (defence in depth)."""
    candidate = (root / relative_path).resolve()
    if candidate != root.resolve() and root.resolve() not in candidate.parents:
        raise FileStoreError(f"{relative_path!r} escapes its delivery root")
    return candidate

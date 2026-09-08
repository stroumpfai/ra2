# STUB — bodies owned by A4 (feat/m2-infra). Not frozen.
"""**All** file I/O in the app goes through here (sw-design.md §2, N4).

Every call specifies `encoding=` explicitly. `errors="replace"` is banned:
undecodable bytes fail the file, they are never turned into `U+FFFD`
(sw-design.md §12.4). `pathlib` only, no shell-outs (N3).

A4 adds a test asserting `open(` appears nowhere else in `ra2/`.

`open_binary_writer` exists alongside the four functions the stub declared so
`FileStore.accept()` (`ra2.infra.filestore`) can stream an upload straight to
disk, chunk by chunk, without buffering the whole payload in memory or
opening a file handle of its own — this module is the *only* place that
does that.
"""

from pathlib import Path
from typing import BinaryIO

__all__ = [
    "open_binary_writer",
    "read_bytes",
    "read_text",
    "write_bytes",
    "write_text",
]


def read_bytes(path: Path) -> bytes:
    """Raw bytes. The only way to get at a delivery file's content."""
    return path.read_bytes()


def write_bytes(path: Path, data: bytes) -> None:
    """Raw bytes, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read_text(path: Path, *, encoding: str) -> str:
    """Strict decoding. `encoding` is required and `errors` is never passed.

    `newline=""` so the raw line endings reach the caller untouched — the CSV
    dialect/encoding detection (A1) needs to see exactly what is on disk,
    including an embedded `\\r\\n` inside a quoted field, not a translation
    Python's universal-newlines mode would have already applied.
    """
    with path.open("r", encoding=encoding, newline="") as handle:
        return handle.read()


def write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Explicit encoding, always. Newlines are normalised to `\\n` so a Windows
    and a Linux run produce byte-identical exports."""
    path.parent.mkdir(parents=True, exist_ok=True)
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    with path.open("w", encoding=encoding, newline="\n") as handle:
        handle.write(normalised)


def open_binary_writer(path: Path) -> BinaryIO:
    """Open `path` for streaming binary writes, creating parent directories.

    Used only by `UploadedFileStore.accept()` to stream an upload to disk in
    bounded chunks while hashing it, rather than reading the whole body into
    memory first. Returns a context manager; the caller closes it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("wb")

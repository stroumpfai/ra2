# STUB — bodies owned by A4 (feat/m2-infra). Not frozen.
"""**All** file I/O in the app goes through here (sw-design.md §2, N4).

Every call specifies `encoding=` explicitly. `errors="replace"` is banned:
undecodable bytes fail the file, they are never turned into `U+FFFD`
(sw-design.md §12.4). `pathlib` only, no shell-outs (N3).

A4 adds a test asserting `open(` appears nowhere else in `ra2/`.
"""

from pathlib import Path

__all__ = ["read_bytes", "read_text", "write_bytes", "write_text"]


def read_bytes(path: Path) -> bytes:
    """Raw bytes. The only way to get at a delivery file's content."""
    raise NotImplementedError


def write_bytes(path: Path, data: bytes) -> None:
    """Raw bytes, creating parent directories."""
    raise NotImplementedError


def read_text(path: Path, *, encoding: str) -> str:
    """Strict decoding. `encoding` is required and `errors` is never passed."""
    raise NotImplementedError


def write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Explicit encoding, always. Newlines are normalised to `\\n` so a Windows
    and a Linux run produce byte-identical exports."""
    raise NotImplementedError

# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""Per-file encoding detection (mvp-spec.md §4.2.1).

UTF-8 first, then Windows-1252. Undecodable bytes **fail the file** — never
substitute `U+FFFD`, never pass `errors="replace"` (sw-design.md §12.4).
"""

from dataclasses import dataclass

from ra2.domain.delivery import Encoding

__all__ = ["EncodingResult", "Undecodable", "detect_encoding"]


@dataclass(frozen=True, slots=True)
class EncodingResult:
    """The bytes decoded cleanly under `encoding`."""

    encoding: Encoding
    text: str


@dataclass(frozen=True, slots=True)
class Undecodable:
    """The bytes decoded under neither encoding. The file fails."""

    byte_offset: int
    byte_value: int


def detect_encoding(data: bytes) -> EncodingResult | Undecodable:
    """Decode `data` strictly, UTF-8 then Windows-1252."""
    raise NotImplementedError

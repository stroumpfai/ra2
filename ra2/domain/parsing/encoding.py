# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""Per-file encoding detection (mvp-spec.md §4.2.1).

UTF-8 first, then Windows-1252. Undecodable bytes **fail the file** — never
substitute `U+FFFD`, never pass `errors="replace"` (sw-design.md §12.4).

The order matters and is not a heuristic. UTF-8 is checked first because it is
self-validating: a byte string that decodes cleanly as UTF-8 is almost never
accidentally UTF-8. Windows-1252 is the fallback because the delivery came
through a cp1252 pipeline (mvp-spec.md §4.4). There is deliberately **no third
fallback**: `latin-1` would decode every byte string ever written and turn a
detection failure into silent mojibake, which is exactly the failure mode
§4.2.1 exists to prevent.

`cp1252` leaves five byte values undefined — 0x81, 0x8D, 0x8F, 0x90, 0x9D — so
strict decoding really can fail, and `Undecodable` really is reachable (h02).
"""

from dataclasses import dataclass

from ra2.domain.delivery import Encoding

__all__ = ["ENCODING_ORDER", "EncodingResult", "Undecodable", "decode_strict", "detect_encoding"]

#: Tried in this order, strictly, and nothing else (mvp-spec.md §4.2.1).
ENCODING_ORDER: tuple[Encoding, ...] = (Encoding.UTF_8, Encoding.CP1252)

#: A UTF-8 byte-order mark. Excel writes one; it is a mark, not a character, so
#: it is dropped from the decoded text rather than becoming column zero's name.
_UTF8_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class EncodingResult:
    """The bytes decoded cleanly under `encoding`."""

    encoding: Encoding
    text: str
    #: True when a UTF-8 BOM was present and stripped.
    had_bom: bool = False


@dataclass(frozen=True, slots=True)
class Undecodable:
    """The bytes decoded under neither encoding. The file fails."""

    byte_offset: int
    byte_value: int

    @property
    def byte_hex(self) -> str:
        """`0x9d` — how the finding's detail names the offending byte."""
        return f"0x{self.byte_value:02x}"


def decode_strict(data: bytes, encoding: Encoding) -> str | None:
    """Decode under exactly `encoding`, strictly. `None` when it does not fit.

    The one place in the codebase that decodes delivery bytes. There is no
    `errors=` argument here and there must never be one: a replacement
    character written into a narrative is indistinguishable, downstream, from a
    character the analyst's source system lost (mvp-spec.md §4.4).
    """
    try:
        return data.decode(encoding.value)
    except UnicodeDecodeError:
        return None


def detect_encoding(data: bytes) -> EncodingResult | Undecodable:
    """Decode `data` strictly, UTF-8 then Windows-1252."""
    had_bom = data.startswith(_UTF8_BOM)
    payload = data[len(_UTF8_BOM) :] if had_bom else data

    for encoding in ENCODING_ORDER:
        text = decode_strict(payload, encoding)
        if text is not None:
            return EncodingResult(encoding=encoding, text=text, had_bom=had_bom)

    # Neither fitted. Report where cp1252 gave up: UTF-8 fails on any byte
    # sequence a legacy single-byte encoding would have accepted, so its offset
    # says little, whereas a cp1252 failure names a byte that is genuinely
    # undefined in both.
    try:
        payload.decode(Encoding.CP1252.value)
    except UnicodeDecodeError as exc:
        offset = exc.start + (len(_UTF8_BOM) if had_bom else 0)
        return Undecodable(byte_offset=offset, byte_value=data[offset])
    raise AssertionError("unreachable: cp1252 decoded on the second attempt")  # pragma: no cover

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

**What strictness does not catch, and what catches it instead** (risk G1, G2).
UTF-8 accepts `U+0000` and cp1252 decodes 251 of 256 byte values, so two kinds
of wrong input decode "successfully":

- A **UTF-16 or UTF-32** file (an Excel "Unicode Text" re-export) decodes into
  NUL-riddled text and then fails at the header, for the wrong reason.
  `refuse` names the real one before decoding is tried: a wide byte-order mark
  (h16), or a NUL byte anywhere (h17). No delivery format this app reads has a
  use for NUL, so neither is a guess, and an encoding override cannot get past
  either.
- A **mixed** file (UTF-8 rows plus one stray cp1252 byte) fails UTF-8 and
  falls back to cp1252 whole, so every correctly-encoded row becomes mojibake:
  `Grüezi` -> `GrÃ¼ezi`. That cannot be refused, because a genuine cp1252 file
  can contain the same bytes, rarely. `utf8_sequences` counts it instead, as
  the mirror image of the cp1252 canary (h15).
"""

import re
from dataclasses import dataclass
from typing import Final

from ra2.domain.delivery import Encoding

__all__ = [
    "ENCODING_ORDER",
    "EncodingResult",
    "NulByte",
    "Refused",
    "Undecodable",
    "UnsupportedBom",
    "Utf8Sequences",
    "decode_strict",
    "detect_encoding",
    "refuse",
    "utf8_sequences",
]

#: Tried in this order, strictly, and nothing else (mvp-spec.md §4.2.1).
ENCODING_ORDER: tuple[Encoding, ...] = (Encoding.UTF_8, Encoding.CP1252)

#: A UTF-8 byte-order mark. Excel writes one; it is a mark, not a character, so
#: it is dropped from the decoded text rather than becoming column zero's name.
_UTF8_BOM = b"\xef\xbb\xbf"

#: The byte-order marks of the encodings this app refuses, by name. UTF-32-LE's
#: mark begins with UTF-16-LE's, so it has to be tried first.
_WIDE_BOMS: Final = (
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)

#: One well-formed multi-byte UTF-8 sequence: no overlong form, no surrogate,
#: nothing past U+10FFFF (RFC 3629 §4). Read as cp1252, each one becomes two to
#: four characters of mojibake: `Ã¼` for `ü`, `â€™` for `’`.
_UTF8_MULTIBYTE: Final = re.compile(
    rb"[\xc2-\xdf][\x80-\xbf]"
    rb"|\xe0[\xa0-\xbf][\x80-\xbf]"
    rb"|[\xe1-\xec\xee\xef][\x80-\xbf]{2}"
    rb"|\xed[\x80-\x9f][\x80-\xbf]"
    rb"|\xf0[\x90-\xbf][\x80-\xbf]{2}"
    rb"|[\xf1-\xf3][\x80-\xbf]{3}"
    rb"|\xf4[\x80-\x8f][\x80-\xbf]{2}"
)


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


@dataclass(frozen=True, slots=True)
class UnsupportedBom:
    """The bytes open with a UTF-16 or UTF-32 byte-order mark. The file fails."""

    #: `utf-16-le`, `utf-16-be`, `utf-32-le` or `utf-32-be`.
    bom: str


@dataclass(frozen=True, slots=True)
class NulByte:
    """The bytes contain a NUL. The file fails.

    Checked on the bytes rather than on the decoded text. Under both encodings
    this app reads, `U+0000` comes from byte `0x00` and from nothing else, so
    the two checks agree and this one can say where the NUL is.
    """

    byte_offset: int


#: Every way `detect_encoding` fails a file. Each has its own `FindingCode`.
type Refused = Undecodable | UnsupportedBom | NulByte


@dataclass(frozen=True, slots=True)
class Utf8Sequences:
    """How much of a cp1252-decoded file was really UTF-8 (risk G1)."""

    count: int
    #: Into the original bytes, like `Undecodable.byte_offset`. `None` at zero.
    first_byte_offset: int | None
    #: The 1-based physical line holding the first one. `None` at zero.
    first_line_no: int | None


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


def refuse(data: bytes) -> UnsupportedBom | NulByte | None:
    """Why `data` must not be decoded at all, whichever encoding is asked for.

    This is separate from `detect_encoding` so an encoding override meets it
    too. Otherwise an analyst choosing cp1252 for a UTF-16 file would get
    exactly the NUL-riddled text this check exists to stop.
    """
    for mark, name in _WIDE_BOMS:
        if data.startswith(mark):
            return UnsupportedBom(bom=name)
    offset = data.find(b"\x00")
    if offset >= 0:
        return NulByte(byte_offset=offset)
    return None


def utf8_sequences(data: bytes) -> Utf8Sequences:
    """Count the well-formed multi-byte UTF-8 sequences in `data`.

    The count only means something for a file that was decoded as cp1252.
    There, every sequence is text that was written as UTF-8 and has become
    mojibake. A leading UTF-8 BOM is a mark, not a character, so it is not
    counted, by the same rule that strips it from the decoded text.
    """
    start = len(_UTF8_BOM) if data.startswith(_UTF8_BOM) else 0
    count = 0
    first: int | None = None
    for match in _UTF8_MULTIBYTE.finditer(data, start):
        if first is None:
            first = match.start()
        count += 1
    if first is None:
        return Utf8Sequences(count=0, first_byte_offset=None, first_line_no=None)
    return Utf8Sequences(
        count=count,
        first_byte_offset=first,
        first_line_no=data.count(b"\n", 0, first) + 1,
    )


def detect_encoding(data: bytes) -> EncodingResult | Refused:
    """Decode `data` strictly, UTF-8 then Windows-1252, unless `refuse` objects."""
    refused = refuse(data)
    if refused is not None:
        return refused

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

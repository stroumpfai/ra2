"""UTF-8, then Windows-1252, then failure (mvp-spec.md §4.2.1)."""

import pytest

from ra2.domain.delivery import Encoding
from ra2.domain.parsing.encoding import (
    ENCODING_ORDER,
    EncodingResult,
    Undecodable,
    decode_strict,
    detect_encoding,
)

#: Undefined in Windows-1252, and bare continuation bytes in UTF-8.
CP1252_UNDEFINED = (0x81, 0x8D, 0x8F, 0x90, 0x9D)


def test_order_is_utf8_then_cp1252_and_there_is_no_third():
    """A third fallback would end detection: `latin-1` decodes every byte
    string ever written, turning a failure into silent mojibake."""
    assert ENCODING_ORDER == (Encoding.UTF_8, Encoding.CP1252)


def test_utf8_wins_when_the_bytes_are_valid_utf8():
    result = detect_encoding("Nässe, Übergang, forêt".encode())
    assert isinstance(result, EncodingResult)
    assert result.encoding is Encoding.UTF_8
    assert result.text == "Nässe, Übergang, forêt"


def test_cp1252_is_the_fallback():
    result = detect_encoding("Nässe, Übergang, forêt".encode("cp1252"))
    assert isinstance(result, EncodingResult)
    assert result.encoding is Encoding.CP1252
    assert result.text == "Nässe, Übergang, forêt"


def test_ascii_is_reported_as_utf8_because_it_is():
    result = detect_encoding(b"plain ascii")
    assert isinstance(result, EncodingResult)
    assert result.encoding is Encoding.UTF_8


def test_empty_input_decodes_rather_than_failing():
    result = detect_encoding(b"")
    assert isinstance(result, EncodingResult)
    assert result.text == ""


@pytest.mark.parametrize("byte", CP1252_UNDEFINED)
def test_bytes_undefined_in_both_encodings_fail_the_file(byte):
    result = detect_encoding(b"abc" + bytes([byte]) + b"def")
    assert isinstance(result, Undecodable)
    assert result.byte_offset == 3
    assert result.byte_value == byte
    assert result.byte_hex == f"0x{byte:02x}"


def test_a_utf8_bom_is_stripped_not_turned_into_a_column_name():
    """Excel writes one. It is a mark, not a character, so it must not become
    part of the first header cell — where it would break every match."""
    result = detect_encoding(b"\xef\xbb\xbfUNFALLUID;HERGANG\r\n")
    assert isinstance(result, EncodingResult)
    assert result.had_bom is True
    assert result.text == "UNFALLUID;HERGANG\r\n"


def test_the_reported_offset_is_into_the_original_bytes_bom_included():
    """An analyst looking at the file with a hex editor counts from byte zero."""
    result = detect_encoding(b"\xef\xbb\xbfab\x9d")
    assert isinstance(result, Undecodable)
    assert result.byte_offset == 5
    assert result.byte_value == 0x9D


def test_decode_strict_returns_none_rather_than_substituting():
    """The one decoding call site in the codebase. It has no `errors=`
    parameter, and a caller cannot ask it for a lenient read."""
    assert decode_strict(b"\x9d", Encoding.CP1252) is None
    assert decode_strict(b"\xc3\xa9", Encoding.UTF_8) == "é"


def test_no_replacement_character_is_ever_produced():
    """`U+FFFD` in a narrative is indistinguishable, later, from a character
    the analyst's source system lost (mvp-spec.md §4.4)."""
    for payload in (b"\x9d", b"\xff\xfe", b"caf\xe9", "café".encode()):
        result = detect_encoding(payload)
        if isinstance(result, EncodingResult):
            assert "�" not in result.text

"""Delimiter and quote-character sniffing (mvp-spec.md §4.1)."""

import pytest

from ra2.domain.delivery import FileKind
from ra2.domain.parsing.dialect import DEFAULT_QUOTE_CHAR, detect_dialect

STRUCTURED = "UnfallUid|GeoRefUid|KantonAusw\r\naaa|bbb|AG\r\nccc|ddd|AG\r\n"
TEXT = 'UNFALLUID;HERGANG\r\naaa;"Er bremste, dann kam es zur Kollision."\r\n'


def test_structured_files_sniff_as_pipe():
    assert detect_dialect(STRUCTURED, FileKind.UNKNOWN).delimiter == "|"


def test_the_text_file_sniffs_as_semicolon():
    assert detect_dialect(TEXT, FileKind.UNKNOWN).delimiter == ";"


def test_the_quote_char_is_the_rfc4180_double_quote():
    assert detect_dialect(TEXT, FileKind.UNKNOWN).quote_char == DEFAULT_QUOTE_CHAR == '"'


def test_a_comma_inside_a_narrative_does_not_beat_the_real_delimiter():
    """Frequency alone would pick `,` here. Stability across rows must not."""
    text = (
        "UNFALLUID;HERGANG\r\n"
        "aaa;Er bremste, wich aus, verlor die Kontrolle, und hielt an\r\n"
        "bbb;Zweiter Fall, kurz, knapp\r\n"
    )
    assert detect_dialect(text, FileKind.UNKNOWN).delimiter == ";"


def test_kind_is_only_a_tie_breaker_never_a_substitute_for_looking():
    """Told it is a text file, but shown pipes, the sniff still says pipe.

    That is the point: the delimiter is per-file, defaulted by detection and
    overridable — never asserted from what the file is supposed to be.
    """
    assert detect_dialect(STRUCTURED, FileKind.TEXT).delimiter == "|"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (FileKind.UNFALL, "|"),
        (FileKind.OBJEKT, "|"),
        (FileKind.PERSON, "|"),
        (FileKind.TEXT, ";"),
    ],
)
def test_a_single_column_file_falls_back_on_what_the_kind_expects(kind, expected):
    """Nothing looked like a delimiter. The caller still needs a usable
    `Dialect` to report and to offer as an override."""
    assert detect_dialect("HEADER\r\nvalue\r\n", kind).delimiter == expected


def test_an_empty_file_still_yields_a_dialect():
    assert detect_dialect("", FileKind.UNKNOWN).delimiter == "|"


def test_a_tab_separated_file_is_sniffed_too():
    text = "A\tB\tC\r\n1\t2\t3\r\n4\t5\t6\r\n"
    assert detect_dialect(text, FileKind.UNKNOWN).delimiter == "\t"

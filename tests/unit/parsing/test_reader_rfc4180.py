"""The strict half of "strict first, recover second" (mvp-spec.md §4.2.2)."""

import pytest

from ra2.domain.delivery import Dialect
from ra2.domain.parsing.reader import RawRow, read_rows, split_physical_lines

SEMI = Dialect(delimiter=";")
PIPE = Dialect(delimiter="|")


def rows(text: str, dialect: Dialect = SEMI) -> list[RawRow]:
    return list(read_rows(text, dialect))


def test_a_plain_file_reads_one_row_per_line():
    result = rows("a;b\r\nc;d\r\n")
    assert [r.fields for r in result] == [("a", "b"), ("c", "d")]
    assert [r.line_no for r in result] == [1, 2]
    assert all(r.line_span == 1 for r in result)


def test_crlf_and_lf_both_read_the_same():
    assert [r.fields for r in rows("a;b\r\nc;d\r\n")] == [r.fields for r in rows("a;b\nc;d\n")]


def test_a_quoted_newline_is_one_record_spanning_two_lines():
    result = rows('a;"one\r\ntwo"\r\nb;c\r\n')
    assert result[0].fields == ("a", "one\r\ntwo")
    assert result[0].line_no == 1
    assert result[0].line_span == 2
    assert result[1].line_no == 3


def test_doubled_quotes_are_unescaped():
    assert rows('a;"he said ""hi"""\r\n')[0].fields == ("a", 'he said "hi"')


def test_a_bare_quote_in_an_unquoted_field_is_accepted():
    """The delivery's quoting is "selective, type-inconsistent" (§4.1) and
    narratives contain quotation marks. Rejecting those would reject the data."""
    assert rows('a;er sagte "nichts" dazu\r\n')[0].fields == ("a", 'er sagte "nichts" dazu')


def test_text_after_a_closing_quote_is_an_error_not_a_silent_deletion():
    """Non-strict `csv` drops the `junk` without a word. That is exactly the
    silent repair §12.6 forbids."""
    result = rows('a;"x"junk;z\r\nb;ok\r\n')
    assert result[0].error is not None
    assert result[0].fields == ()
    assert result[1].fields == ("b", "ok")


def test_an_unterminated_quote_is_an_error_not_a_swallowed_file():
    """Non-strict `csv` folds every remaining line into one field."""
    result = rows('a;"never closed\r\nb;ok\r\n')
    assert result[0].error is not None


def test_the_reader_keeps_reading_after_a_bad_row():
    result = rows('a;ok\r\nb;"x"junk;z\r\nc;ok\r\n')
    assert [r.error is None for r in result] == [True, False, True]
    assert result[2].fields == ("c", "ok")


def test_end_line_no_reports_where_a_multi_line_record_finished():
    result = rows('a;"one\r\ntwo\r\nthree"\r\n')
    assert result[0].line_no == 1
    assert result[0].end_line_no == 3


@pytest.mark.parametrize("separator", ["\v", "\f", "\x1c", "\x85", " "])
def test_only_cr_lf_and_crlf_separate_records(separator):
    """`str.splitlines()` breaks on all of these. A vertical tab inside a
    narrative would become a spurious extra row and then a spurious
    `ROW_RECOVERED` finding."""
    text = f"a;one{separator}two\r\nb;c\r\n"
    assert len(split_physical_lines(text)) == 2
    assert rows(text)[0].fields == ("a", f"one{separator}two")


def test_a_file_with_no_trailing_newline_still_yields_its_last_row():
    assert rows("a;b\r\nc;d")[-1].fields == ("c", "d")


def test_the_pipe_dialect_reads_the_wide_tables():
    assert rows("a|b|c\r\n", PIPE)[0].fields == ("a", "b", "c")


def test_an_empty_file_yields_nothing():
    assert rows("") == []

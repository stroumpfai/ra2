# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""RFC4180 reading with an explicit `Dialect` (mvp-spec.md §4.2.2).

"Strict first, recover second" (§4.2) is two modules: this one is the strict
half. It runs a real RFC4180 parser — `csv` with `strict=True` — and reports
what it could not parse instead of guessing. Guessing is
`ra2.domain.parsing.recovery`'s job, and only where the key anchor makes it
unambiguous.

`strict=True` is deliberate and its consequences are wanted:

- an unterminated quote raises rather than silently swallowing the rest of the
  file into one giant field;
- text after a closing quote (`"x"junk`) raises rather than being silently
  dropped — the row becomes `ROW_REJECTED_PARSE_ERROR`;
- a **bare** quote inside an unquoted field is still accepted, which matters,
  because the delivery's quoting is "selective, type-inconsistent" (§4.1) and
  narratives contain quotation marks.

Every `RawRow` carries the physical lines it came from, because a record that
spans more than one line is a reportable event (§4.2.4) whether the quoting or
the key anchor put it back together.
"""

import csv
from collections.abc import Iterator
from dataclasses import dataclass

from ra2.domain.delivery import Dialect

__all__ = ["RawRow", "read_rows", "split_physical_lines"]


@dataclass(frozen=True, slots=True)
class RawRow:
    """One physical row as read, before recovery or validation."""

    line_no: int
    fields: tuple[str, ...]
    #: Set when the reader itself could not parse the row.
    error: str | None = None
    #: Physical lines this record occupied. > 1 means the RFC4180 reader glued
    #: a quoted newline back together, which is still a reportable recovery.
    line_span: int = 1

    @property
    def end_line_no(self) -> int:
        return self.line_no + self.line_span - 1


def split_physical_lines(text: str) -> list[str]:
    """Split on `\\r\\n`, `\\r` and `\\n` only, keeping the terminator.

    `str.splitlines()` is wrong here: it also breaks on `\\v`, `\\f`, `\\x1c`,
    `\\x85` and `\\u2028`, none of which is a record separator in a delivered
    file. A vertical tab inside a narrative would silently become an extra row
    and then a spurious `ROW_RECOVERED` finding.
    """
    lines: list[str] = []
    start = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\r":
            end = index + 2 if text[index + 1 : index + 2] == "\n" else index + 1
            lines.append(text[start:end])
            start = index = end
        elif char == "\n":
            lines.append(text[start : index + 1])
            start = index = index + 1
        else:
            index += 1
    if start < length:
        lines.append(text[start:])
    return lines


def read_rows(text: str, dialect: Dialect) -> Iterator[RawRow]:
    """Read `text` with a real RFC4180 parser using `dialect`."""
    lines = split_physical_lines(text)
    consumed = [0]

    def feed() -> Iterator[str]:
        for line in lines:
            consumed[0] += 1
            yield line

    reader = csv.reader(
        feed(),
        delimiter=dialect.delimiter,
        quotechar=dialect.quote_char,
        doublequote=True,
        skipinitialspace=False,
        strict=True,
    )

    start = 1
    while True:
        try:
            fields = next(reader)
        except StopIteration:
            return
        except csv.Error as exc:
            end = max(consumed[0], start)
            yield RawRow(
                line_no=start,
                fields=(),
                error=str(exc),
                line_span=end - start + 1,
            )
            start = end + 1
            continue
        end = max(consumed[0], start)
        yield RawRow(line_no=start, fields=tuple(fields), line_span=end - start + 1)
        start = end + 1

"""Where a mismatch's evidence span occurs in its narrative (`SD70`).

The Mismatches detail row highlights the span inside the full text, so the
analyst sees what the model quoted *in context*. **It locates; it never
judges.** A span that is not found is not flagged: "the model quoted text
that isn't there" is the first step of automatic hallucination triage, which
mvp-spec.md §16 defers as `D1`. When nothing lights up, the analyst sees that
for themselves.

Two passes, and nothing looser:

1. **Exact**: every non-overlapping verbatim occurrence.
2. **Whitespace-tolerant**, only when exact found nothing: runs of whitespace
   on either side compare equal. This is the embedded-newline hazard, where
   the narrative breaks a line where the model's quote has a space. Offsets
   map back into the original text.

Case-sensitive, no Unicode normalisation, no edit distance. A lossy French
`chauss e` matches only a span carrying the same loss: anything looser is a
similarity threshold, and that is `D1` again.
"""

from typing import Final

__all__ = ["locate"]

#: What the tolerant pass treats as one run. `str.isspace` would also fold
#: the exotic separators, and the hazard is the ordinary three.
_WHITESPACE_CHARS: Final = " \t\r\n"
_WHITESPACE: Final = frozenset(_WHITESPACE_CHARS)


def locate(text: str | None, span: str | None) -> tuple[tuple[int, int], ...]:
    """Every occurrence of `span` in `text` as `(start, end)` offsets into
    `text`, left to right and non-overlapping. Empty when there is none."""
    if not text or not span or not span.strip():
        return ()
    exact = _occurrences(text, span)
    if exact:
        return tuple((start, start + len(span)) for start in exact)
    folded_text, origin = _fold(text)
    folded_span, _ = _fold(span.strip(_WHITESPACE_CHARS))
    return tuple(
        (origin[start], origin[start + len(folded_span) - 1] + 1)
        for start in _occurrences(folded_text, folded_span)
    )


def _occurrences(haystack: str, needle: str) -> list[int]:
    found: list[int] = []
    start = haystack.find(needle)
    while start != -1:
        found.append(start)
        start = haystack.find(needle, start + len(needle))
    return found


def _fold(text: str) -> tuple[str, list[int]]:
    """`text` with each whitespace run as one space, and for every character
    of the result, the offset in `text` it came from (a run maps to its first
    character)."""
    chars: list[str] = []
    origin: list[int] = []
    in_run = False
    for index, char in enumerate(text):
        if char in _WHITESPACE:
            if not in_run:
                chars.append(" ")
                origin.append(index)
            in_run = True
            continue
        chars.append(char)
        origin.append(index)
        in_run = False
    return "".join(chars), origin

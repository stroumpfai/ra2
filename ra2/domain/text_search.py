"""Search text matching for the Codelists screen (plan-codelists-usability.md §2–§3).

Pure, and here rather than in `ui/` because deciding what matches is a rule,
not a rendering (sw-design.md §8.1.1). Two callers: the column search, which
matches on the server, and the JSON-key search, which matches **in the
browser** against `fold`ed text the server wrote. The browser therefore folds
the typed text with the same three steps, written once more in JavaScript
(`codelists_view._KEY_FILTER_JS`). They are kept to steps both languages
spell identically — lower-case, `ß` → `ss`, NFKD with the combining marks
dropped — rather than Python's `casefold`, which has no JavaScript twin.
"""

import unicodedata

__all__ = ["fold", "matches"]


def fold(text: str) -> str:
    """The comparison form: lower-cased, `ß` spelt `ss`, accents dropped —
    `Straße` and `STRASSE` both become `strasse`, `Chaussée` `chaussee`."""
    decomposed = unicodedata.normalize("NFKD", text.lower().replace("ß", "ss"))
    # By general category, as JavaScript's `\p{M}` is — not by
    # `unicodedata.combining`, which leaves the spacing marks (`Mc`) in.
    return "".join(ch for ch in decomposed if not unicodedata.category(ch).startswith("M"))


def matches(query: str, *haystacks: str) -> bool:
    """Does the folded query occur in any folded haystack? Blank text matches."""
    needle = fold(query.strip())
    if not needle:
        return True
    return any(needle in fold(text) for text in haystacks)

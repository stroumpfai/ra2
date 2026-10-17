# NEW — feat/text-scrubbing. Types and signatures frozen in CONTRACTS.md.
"""Narrative scrubbing: numbered placeholders for personal data (sw-design.md §19).

A narrative goes in, the same narrative comes out with every span a rule
claims replaced by `<Tag_n>` — `<LicensePlate_1>`, `<Lastname_2>`. **No LLM,
no network, no filesystem**: regular expressions and name lists, nothing else
(`SD62`–`SD66`, `plan-text-scrubbing.md`).

Two kinds of rule:

- **Regex rules.** The mandatory ones are code (`scrub_mandatory.py`) and run
  on every freeze; the imported ones are data, parsed here from TOML.
- **Name lists.** First names, last names and a whitelist, one entry per line,
  matched on whole tokens without regard to case or accents (§19.3).

Four properties are what the rest of the codebase relies on, and each one is a
test in `tests/unit/scrub/`:

1. **One pass, deterministic.** Every candidate is collected against the
   *original* text, overlaps are resolved by a fixed order, and the
   replacements are made in one go. The same text and rules always give the
   same output, and a placeholder is never matched again by a later rule.
2. **Nothing else changes.** Text outside the replaced spans is
   byte-identical. Normalisation is for comparing only, never for storing.
3. **Numbered per record** (`SD64`). The same value gets the same number, so
   a narrative keeps its internal references the way `B1` / `G1` do.
4. **Fail closed** (`SD66`). A match that exceeds its time budget raises
   `ScrubTimeoutError`. No partial text and no unscrubbed original is ever
   returned, because a caller holding one would store it.

`regex` is imported here and nowhere else in `ra2/` (`.importlinter`,
`regex-only-in-the-scrubber`). It is here for its matching `timeout=` and its
Unicode property classes; its fuzzy matching and named lists are deliberately
unused (§19.6).
"""

import hashlib
import json
import tomllib
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

import regex

__all__ = [
    "ADVERSARIAL_LENGTH",
    "BOTH_LISTS_RULE_ID",
    "FIRSTNAME_RULE_ID",
    "HONORIFICS",
    "IMPORT_TIMEOUT_S",
    "LASTNAME_RULE_ID",
    "MATCH_TIMEOUT_S",
    "MIN_ENTRY_LETTERS",
    "MOST_HIT_FLOOR",
    "PROTECTED_STRINGS",
    "RESERVED_RULE_IDS",
    "RESERVED_TAGS",
    "SCRUB_ALGORITHM_VERSION",
    "ListKind",
    "ListNotice",
    "ListNoticeCode",
    "NameListFile",
    "NameTag",
    "RegexRule",
    "RegexRuleFile",
    "RuleSource",
    "RuleTally",
    "ScrubCounter",
    "ScrubHit",
    "ScrubImportError",
    "ScrubImportErrorCode",
    "ScrubResult",
    "ScrubRules",
    "ScrubTally",
    "ScrubTimeoutError",
    "Scrubber",
    "check_rules",
    "compute_rules_fingerprint",
    "entry_key",
    "parse_name_list",
    "parse_regex_rules",
    "placeholder",
]


# ===========================================================================
# Constants — every one is part of the fingerprint (§19.4)
# ===========================================================================

#: Bumped whenever a change here would scrub the same text differently with
#: the same rules: tokenising, normalising, overlap order, numbering. It is in
#: every corpus's `scrub_fingerprint`, so two corpora scrubbed by different
#: algorithms never claim the same rules.
SCRUB_ALGORITHM_VERSION: Final = 1

#: The budget of one regex rule over one text at freeze, in seconds. A
#: well-behaved pattern takes microseconds over a narrative; this exists for
#: the one that is not, and failing it fails the freeze (`SD66`).
MATCH_TIMEOUT_S: Final = 2.0

#: The tighter budget a pattern gets at import, over each adversarial string.
IMPORT_TIMEOUT_S: Final = 0.25

#: The length of the adversarial strings a pattern is timed against at import.
#: Narratives run to a few kilobytes; a pattern merely quadratic on a much
#: longer run of one character would be refused for a cost no narrative has.
ADVERSARIAL_LENGTH: Final = 4096

#: An entry whose letters, normalised, number fewer than this is skipped and
#: reported: `Le`, `Da` and `Li` are surnames and French articles (Q10).
MIN_ENTRY_LETTERS: Final = 3

#: A list entry is named in the most-hit table only from this many hits up.
#: The table shows list entries, which are public, but a low count could still
#: say that a rare name occurs in the corpus (Q6).
MOST_HIT_FLOOR: Final = 10

#: Words that, immediately before a whitelisted list entry, lift the whitelist
#: for it: `Herr Fuchs` loses his name while `ein Fuchs querte` keeps its fox
#: (Q2). They never make a word that is on no list into a name. Compared
#: casefolded, trailing dot included.
HONORIFICS: Final[tuple[str, ...]] = (
    "herr",
    "frau",
    "hr.",
    "fr.",
    "m.",
    "mme",
    "mme.",
    "mlle",
    "mlle.",
    "monsieur",
    "madame",
    "signor",
    "signora",
    "sig.",
    "sig.ra",
)

#: Strings the **whole** scrubber must leave untouched, checked whenever a
#: rule set is composed (§19.5). Features read every one of them: the role
#: codes are how the narrative refers to its parties, and the rest are the
#: speeds, times, roads and numbers extraction depends on. An imported rule
#: file can add to this list; it cannot take anything away.
PROTECTED_STRINGS: Final[tuple[str, ...]] = (
    "B1",
    "G1",
    "P",
    "B1 kollidierte mit G1",
    "80 km/h",
    "um 14.30 Uhr",
    "um 07.45 Uhr",
    "A1",
    "N1",
    "Hauptstrasse 12",
    "Km 12.5",
    "Rega 1414",
    "Notruf 117",
    "Notruf 144",
    "im Kanton ZH 2 Verletzte",
)

_TAG_SHAPE: Final = regex.compile(r"[A-Z][A-Za-z]{1,31}")
_RULE_ID_SHAPE: Final = regex.compile(r"[a-z0-9][a-z0-9-]{0,63}")

#: A token is a run of letters and the combining marks that belong to them, so
#: an NFD `Mu\u0308ller` is one token, as its NFC spelling is. Stdlib `\w`
#: would split it at the mark.
_TOKEN: Final = regex.compile(r"\p{L}[\p{L}\p{M}]*")
#: What may sit between the tokens of one multi-token entry: `von Allmen`,
#: `Müller-Lüdenscheidt`, `D'Alessandro`, and the same split by a line break.
_SEPARATOR: Final = regex.compile(r"[\s'’\-]{1,3}")
#: Removed from a regex match before it keys a number, so `079 123 45 67` and
#: `0791234567` are one `<Phone_1>`.
_VALUE_NOISE: Final = regex.compile(r"[\s\-./()]")
#: An honorific ending right where a name starts. Searched with `pos` and
#: `endpos` rather than over a slice, so the lookbehind still sees the real
#: character before the window: `Bauherr Fuchs` is not `Herr Fuchs`.
_HONORIFIC_BEFORE: Final = regex.compile(
    r"(?<![\p{L}\p{M}.])(?:"
    + "|".join(regex.escape(h) for h in sorted(HONORIFICS, key=len, reverse=True))
    + r")\s+$",
    regex.IGNORECASE,
)
#: How far back the honorific check looks: the longest honorific plus the
#: whitespace before the name.
_HONORIFIC_WINDOW: Final = 24

_TRANSLITERATION: Final = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})

_JSON_KWARGS: Final = {"sort_keys": False, "separators": (",", ":"), "ensure_ascii": False}


# ===========================================================================
# Vocabulary
# ===========================================================================


class RuleSource(StrEnum):
    """Where a rule came from. Stable identifiers; wording lives in `ui/`."""

    #: Compiled into the code; runs on every freeze; cannot be disabled.
    MANDATORY = "mandatory"
    #: From the analyst's imported TOML.
    IMPORTED = "imported"
    #: One of the name lists.
    LIST = "list"


class ListKind(StrEnum):
    """The four files an analyst can import into a rule set."""

    REGEX = "regex"
    FIRSTNAME = "firstname"
    LASTNAME = "lastname"
    WHITELIST = "whitelist"


class NameTag(StrEnum):
    """The tags only the name lists produce. Reserved: no regex rule may use
    one, so a `<Lastname_1>` always means a list matched."""

    FIRSTNAME = "Firstname"
    LASTNAME = "Lastname"
    #: A token on both lists whose neighbours do not settle which it is (Q1).
    NAME = "Name"


RESERVED_TAGS: Final = frozenset(NameTag)

#: The rule ids the name lists report under, so a tally row exists for them.
FIRSTNAME_RULE_ID: Final = "firstnames"
LASTNAME_RULE_ID: Final = "lastnames"
BOTH_LISTS_RULE_ID: Final = "both-lists"
RESERVED_RULE_IDS: Final = frozenset({FIRSTNAME_RULE_ID, LASTNAME_RULE_ID, BOTH_LISTS_RULE_ID})

_RULE_ID_FOR_TAG: Final[Mapping[NameTag, str]] = {
    NameTag.FIRSTNAME: FIRSTNAME_RULE_ID,
    NameTag.LASTNAME: LASTNAME_RULE_ID,
    NameTag.NAME: BOTH_LISTS_RULE_ID,
}


class ScrubImportErrorCode(StrEnum):
    """Why a rule file, a list or a composed rule set is refused. Stable
    identifiers: tests assert on them, `ui/` words them (§19.5)."""

    NOT_UTF8 = "not_utf8"
    TOML_INVALID = "toml_invalid"
    #: A top-level key other than `rule` and `protected`, or a rule key other
    #: than the six a rule has.
    UNKNOWN_FIELD = "unknown_field"
    FIELD_MISSING = "field_missing"
    #: Present, but the wrong type: a number where a string belongs, a string
    #: where a list does.
    FIELD_INVALID = "field_invalid"
    ID_MALFORMED = "id_malformed"
    DUPLICATE_ID = "duplicate_id"
    #: The id is a mandatory rule's or a name list's.
    ID_RESERVED = "id_reserved"
    TAG_MALFORMED = "tag_malformed"
    #: `Firstname`, `Lastname` or `Name`.
    TAG_RESERVED = "tag_reserved"
    PATTERN_INVALID = "pattern_invalid"
    PATTERN_EMPTY_MATCH = "pattern_empty_match"
    #: Timed out over an adversarial string at import (§19.6).
    PATTERN_TOO_SLOW = "pattern_too_slow"
    #: A rule with no `must_match` example: a rule nobody showed working.
    NO_MUST_MATCH = "no_must_match"
    MUST_MATCH_FAILED = "must_match_failed"
    MUST_NOT_MATCH_HIT = "must_not_match_hit"
    #: The whole scrubber altered a protected string.
    PROTECTED_ALTERED = "protected_altered"
    #: A name list with no usable entry left.
    LIST_EMPTY = "list_empty"


@dataclass(frozen=True, slots=True)
class ScrubImportError:
    """One reason an import is refused. `detail` is structured data, never a
    sentence: the UI renders it (sw-design.md §5's rule, applied here)."""

    code: ScrubImportErrorCode
    rule_id: str | None = None
    detail: Mapping[str, str] = field(default_factory=dict)


class ListNoticeCode(StrEnum):
    """What a name-list import reports without refusing it. Each one is a
    count, never a silent drop (Do-NOT #6)."""

    BOM = "bom"
    CRLF = "crlf"
    BLANK_LINES = "blank_lines"
    COMMENT_LINES = "comment_lines"
    DUPLICATES = "duplicates"
    TOO_SHORT = "too_short"
    NO_LETTERS = "no_letters"


@dataclass(frozen=True, slots=True)
class ListNotice:
    """One reported, non-refusing fact about an imported file.

    `examples` names up to five of the affected entries. They are entries of a
    public name list, never record text."""

    code: ListNoticeCode
    count: int
    examples: tuple[str, ...] = ()


# ===========================================================================
# Rules
# ===========================================================================


@dataclass(frozen=True, slots=True)
class RegexRule:
    """One regex rule, mandatory or imported (§19.1)."""

    rule_id: str
    tag: str
    pattern: str
    #: Each must be matched **in full** by this rule's pattern.
    must_match: tuple[str, ...]
    #: Each must not be matched anywhere by **this** rule. Local by design:
    #: another rule may legitimately claim it (§19.5).
    must_not_match: tuple[str, ...] = ()
    source: RuleSource = RuleSource.IMPORTED
    #: Free text for the Scrubbing screen. Not part of the fingerprint.
    description: str = ""


@dataclass(frozen=True, slots=True)
class RegexRuleFile:
    """A parsed rule TOML: structurally valid, not yet checked (§19.5)."""

    rules: tuple[RegexRule, ...]
    #: Strings the whole scrubber must leave alone, beyond `PROTECTED_STRINGS`.
    protected: tuple[str, ...] = ()
    notices: tuple[ListNotice, ...] = ()


@dataclass(frozen=True, slots=True)
class NameListFile:
    """A parsed name list: the accepted entries in file order, one per
    normalised key, and what was reported on the way."""

    kind: ListKind
    entries: tuple[str, ...]
    notices: tuple[ListNotice, ...] = ()


@dataclass(frozen=True, slots=True)
class ScrubRules:
    """Everything one scrub applies (§19.2).

    `regex_rules` carries the mandatory rules first, then the imported ones,
    each group in declared order. That order breaks overlap ties."""

    regex_rules: tuple[RegexRule, ...]
    firstnames: tuple[str, ...] = ()
    lastnames: tuple[str, ...] = ()
    whitelist: tuple[str, ...] = ()
    #: The imported file's additions to `PROTECTED_STRINGS`.
    protected: tuple[str, ...] = ()


def compute_rules_fingerprint(rules: ScrubRules) -> str:
    """`sha256` over everything that decides what the scrubber does (§19.4).

    The rules, the lists (as sets: their order decides nothing), the protected
    strings, and every constant of this module that changes an outcome. Not
    the rule descriptions, which change nothing a corpus holds.
    """
    payload = {
        "algorithm": SCRUB_ALGORITHM_VERSION,
        "min_entry_letters": MIN_ENTRY_LETTERS,
        "honorifics": list(HONORIFICS),
        "regex_rules": [
            {
                "id": r.rule_id,
                "tag": r.tag,
                "pattern": r.pattern,
                "source": r.source.value,
            }
            for r in rules.regex_rules
        ],
        "firstnames": sorted({entry_key(e) for e in rules.firstnames}),
        "lastnames": sorted({entry_key(e) for e in rules.lastnames}),
        "whitelist": sorted({entry_key(e) for e in rules.whitelist}),
        "protected": [*PROTECTED_STRINGS, *rules.protected],
    }
    canonical = json.dumps(payload, **_JSON_KWARGS)  # type: ignore[arg-type]
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ===========================================================================
# Normalisation (§19.3)
# ===========================================================================


def _stripped(token: str) -> str:
    """Casefolded, decomposed, combining marks dropped: `René` -> `rene`."""
    decomposed = unicodedata.normalize("NFKD", token.casefold())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _transliterated(token: str) -> str:
    """As `_stripped`, after `ä/ö/ü -> ae/oe/ue`: `Müller` -> `mueller`.

    Composed first, so an NFD `u` + U+0308 transliterates like `ü` does."""
    composed = unicodedata.normalize("NFC", token).casefold()
    return _stripped(composed.translate(_TRANSLITERATION))


def _tokens(text: str) -> list[str]:
    return [m.group() for m in _TOKEN.finditer(text)]


def entry_key(entry: str) -> str:
    """The key a list entry is known by: its transliterated tokens, joined by
    single spaces. `D'Alessandro` -> `d alessandro`, `Müller` -> `mueller`.

    It is what the most-hit table names, what the fingerprint hashes, and what
    numbering keys a name on, so one entry spelt three ways is one name."""
    return " ".join(_transliterated(t) for t in _tokens(entry))


def _entry_forms(entry: str) -> tuple[str, str]:
    tokens = _tokens(entry)
    return " ".join(_stripped(t) for t in tokens), " ".join(_transliterated(t) for t in tokens)


def _letter_count(entry: str) -> int:
    return sum(len(_stripped(t)) for t in _tokens(entry))


# ===========================================================================
# Results
# ===========================================================================


def placeholder(tag: str, number: int) -> str:
    """`<Lastname_1>`. One place, so the shape the prompt paragraph describes
    and the shape the scrubber writes cannot drift."""
    return f"<{tag}_{number}>"


@dataclass(frozen=True, slots=True)
class ScrubHit:
    """One replaced span, in the coordinates of the **original** text."""

    rule_id: str
    tag: str
    start: int
    end: int
    number: int
    #: The matched list entry's `entry_key` for a name; `None` for a regex.
    entry: str | None = None

    @property
    def placeholder(self) -> str:
        return placeholder(self.tag, self.number)


@dataclass(frozen=True, slots=True)
class ScrubResult:
    text: str
    hits: tuple[ScrubHit, ...]

    @property
    def changed(self) -> bool:
        return bool(self.hits)


class ScrubTimeoutError(Exception):
    """A rule exceeded its budget over one text (`SD66`). Carries the rule,
    never the text."""

    def __init__(self, rule_id: str) -> None:
        super().__init__(f"scrub rule {rule_id!r} timed out")
        self.rule_id = rule_id


# ===========================================================================
# The scrubber
# ===========================================================================


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    rule: RegexRule
    pattern: regex.Pattern[str]


@dataclass(slots=True)
class _Candidate:
    start: int
    end: int
    tag: str
    rule_id: str
    #: What numbering keys on: the cleaned match, or the entry key.
    value_key: str
    entry: str | None = None


@dataclass(frozen=True, slots=True)
class _Token:
    start: int
    end: int
    stripped: str
    transliterated: str


@dataclass(frozen=True, slots=True)
class _NameMatch:
    first: int
    count: int
    #: The entry key matched on each list, or `None`.
    firstname: str | None
    lastname: str | None


class _NameIndex:
    """One list, looked up by either normalised form of an n-gram."""

    def __init__(self, entries: Iterable[str]) -> None:
        self._keys: dict[str, str] = {}
        self.max_tokens = 0
        for entry in entries:
            stripped, transliterated = _entry_forms(entry)
            if not transliterated or _letter_count(entry) < MIN_ENTRY_LETTERS:
                continue
            key = transliterated
            self._keys.setdefault(stripped, key)
            self._keys.setdefault(transliterated, key)
            self.max_tokens = max(self.max_tokens, len(_tokens(entry)))

    def __len__(self) -> int:
        return len(set(self._keys.values()))

    def lookup(self, stripped: str, transliterated: str) -> str | None:
        return self._keys.get(transliterated) or self._keys.get(stripped)


class Scrubber:
    """A compiled rule set. Build once per freeze, call `scrub` per text.

    Compiling is the only expensive step, so a corpus of any size compiles its
    patterns and indexes its lists exactly once.

    :raises regex.error: a pattern does not compile. Imported rules were
        compiled at import (`check_rules`), so at freeze this means a
        mandatory rule is broken, which its unit tests exist to catch.
    """

    def __init__(self, rules: ScrubRules, *, timeout_s: float = MATCH_TIMEOUT_S) -> None:
        self.rules = rules
        self.fingerprint = compute_rules_fingerprint(rules)
        self._timeout_s = timeout_s
        self._compiled = tuple(
            _CompiledRule(rule, regex.compile(rule.pattern, regex.VERSION0))
            for rule in rules.regex_rules
        )
        self._firstnames = _NameIndex(rules.firstnames)
        self._lastnames = _NameIndex(rules.lastnames)
        self._whitelist = _NameIndex(rules.whitelist)
        self._max_tokens = max(self._firstnames.max_tokens, self._lastnames.max_tokens)

    @property
    def has_firstnames(self) -> bool:
        return len(self._firstnames) > 0

    @property
    def has_lastnames(self) -> bool:
        return len(self._lastnames) > 0

    def scrub(self, text: str) -> ScrubResult:
        """The scrubbed text and its hits (§19.2).

        :raises ScrubTimeoutError: a regex rule exceeded `timeout_s`.
        """
        if not text:
            return ScrubResult(text, ())
        claimed = self._resolve_regex(self._regex_candidates(text))
        names = [c for c in self._name_candidates(text) if not _overlaps(c, claimed)]
        chosen = sorted([*claimed, *names], key=lambda c: c.start)
        if not chosen:
            return ScrubResult(text, ())
        return _replace(text, chosen)

    # --- regex rules -------------------------------------------------------

    def _regex_candidates(self, text: str) -> list[tuple[int, _Candidate]]:
        found: list[tuple[int, _Candidate]] = []
        for order, compiled in enumerate(self._compiled):
            try:
                for match in compiled.pattern.finditer(text, timeout=self._timeout_s):
                    if match.end() <= match.start():
                        continue
                    value = _VALUE_NOISE.sub("", match.group()).casefold()
                    found.append(
                        (
                            order,
                            _Candidate(
                                match.start(),
                                match.end(),
                                compiled.rule.tag,
                                compiled.rule.rule_id,
                                value,
                            ),
                        )
                    )
            except TimeoutError as exc:
                raise ScrubTimeoutError(compiled.rule.rule_id) from exc
        return found

    @staticmethod
    def _resolve_regex(found: list[tuple[int, _Candidate]]) -> list[_Candidate]:
        """Earliest start wins, then the longest span, then the rule declared
        first. Greedy over that order, so no two claimed spans overlap."""
        ordered = sorted(found, key=lambda oc: (oc[1].start, -(oc[1].end - oc[1].start), oc[0]))
        claimed: list[_Candidate] = []
        reach = -1
        for _, candidate in ordered:
            if candidate.start >= reach:
                claimed.append(candidate)
                reach = candidate.end
        return claimed

    # --- name lists --------------------------------------------------------

    def _name_candidates(self, text: str) -> list[_Candidate]:
        if self._max_tokens == 0:
            return []
        tokens = [
            _Token(m.start(), m.end(), _stripped(m.group()), _transliterated(m.group()))
            for m in _TOKEN.finditer(text)
        ]
        joined = [
            _SEPARATOR.fullmatch(text, tokens[i].end, tokens[i + 1].start) is not None
            for i in range(len(tokens) - 1)
        ]
        matches = self._match_tokens(text, tokens, joined)
        return self._tag_names(tokens, joined, matches)

    def _match_tokens(
        self, text: str, tokens: Sequence[_Token], joined: Sequence[bool]
    ) -> list[_NameMatch]:
        """Longest n-gram first at each token, left to right, never
        overlapping. A whitelisted n-gram is skipped unless an honorific
        stands right before it."""
        matches: list[_NameMatch] = []
        i = 0
        while i < len(tokens):
            for n in range(min(self._max_tokens, len(tokens) - i), 0, -1):
                if not all(joined[i : i + n - 1]):
                    continue
                window = tokens[i : i + n]
                stripped = " ".join(t.stripped for t in window)
                transliterated = " ".join(t.transliterated for t in window)
                firstname = self._firstnames.lookup(stripped, transliterated)
                lastname = self._lastnames.lookup(stripped, transliterated)
                if firstname is None and lastname is None:
                    continue
                if self._whitelist.lookup(stripped, transliterated) is not None and not (
                    _honorific_before(text, tokens[i].start)
                ):
                    continue
                matches.append(_NameMatch(i, n, firstname, lastname))
                i += n
                break
            else:
                i += 1
        return matches

    @staticmethod
    def _tag_names(
        tokens: Sequence[_Token], joined: Sequence[bool], matches: Sequence[_NameMatch]
    ) -> list[_Candidate]:
        """Decide `Firstname`, `Lastname` or `Name` for each match (Q1).

        A match on one list takes that list's tag. A match on both is a
        first name when the next match, right after it, is on the last-name
        list; a last name when the match right before it was tagged a first
        name; otherwise whatever the same entry was tagged earlier in this
        text, so `Martin Simon … Martin kam` keeps one Martin; and only
        failing all three, `Name`."""
        tagged: list[_Candidate] = []
        previous_tag: NameTag | None = None
        decided: dict[str, tuple[NameTag, str]] = {}
        for index, match in enumerate(matches):
            following = matches[index + 1] if index + 1 < len(matches) else None
            adjacent_next = following is not None and _adjacent(match, following, joined)
            adjacent_prev = index > 0 and _adjacent(matches[index - 1], match, joined)
            if match.firstname is not None and match.lastname is not None:
                if adjacent_next and following is not None and following.lastname is not None:
                    tag, key = NameTag.FIRSTNAME, match.firstname
                elif adjacent_prev and previous_tag is NameTag.FIRSTNAME:
                    tag, key = NameTag.LASTNAME, match.lastname
                elif match.lastname in decided:
                    tag, key = decided[match.lastname]
                else:
                    tag, key = NameTag.NAME, match.lastname
                decided.setdefault(match.lastname, (tag, key))
            elif match.firstname is not None:
                tag, key = NameTag.FIRSTNAME, match.firstname
            else:
                assert match.lastname is not None
                tag, key = NameTag.LASTNAME, match.lastname
            first, last = tokens[match.first], tokens[match.first + match.count - 1]
            tagged.append(
                _Candidate(first.start, last.end, tag.value, _RULE_ID_FOR_TAG[tag], key, entry=key)
            )
            previous_tag = tag
        return tagged


def _adjacent(left: _NameMatch, right: _NameMatch, joined: Sequence[bool]) -> bool:
    boundary = left.first + left.count - 1
    return right.first == left.first + left.count and joined[boundary]


def _honorific_before(text: str, start: int) -> bool:
    return _HONORIFIC_BEFORE.search(text, max(0, start - _HONORIFIC_WINDOW), start) is not None


def _overlaps(candidate: _Candidate, claimed: Sequence[_Candidate]) -> bool:
    return any(candidate.start < c.end and c.start < candidate.end for c in claimed)


def _replace(text: str, chosen: Sequence[_Candidate]) -> ScrubResult:
    """Number by first occurrence per tag, then rebuild the text in one pass."""
    numbers: dict[tuple[str, str], int] = {}
    counters: dict[str, int] = {}
    hits: list[ScrubHit] = []
    pieces: list[str] = []
    cursor = 0
    for candidate in chosen:
        key = (candidate.tag, candidate.value_key)
        number = numbers.get(key)
        if number is None:
            number = counters.get(candidate.tag, 0) + 1
            counters[candidate.tag] = number
            numbers[key] = number
        hit = ScrubHit(
            candidate.rule_id,
            candidate.tag,
            candidate.start,
            candidate.end,
            number,
            candidate.entry,
        )
        pieces.append(text[cursor : candidate.start])
        pieces.append(hit.placeholder)
        cursor = candidate.end
        hits.append(hit)
    pieces.append(text[cursor:])
    return ScrubResult("".join(pieces), tuple(hits))


# ===========================================================================
# Counting (§19.7)
# ===========================================================================


@dataclass(frozen=True, slots=True)
class RuleTally:
    """One row of the import report's scrubbing table."""

    rule_id: str
    tag: str
    source: RuleSource
    hits: int
    #: Records with at least one hit from this rule.
    records: int


@dataclass(frozen=True, slots=True)
class ScrubTally:
    #: Every rule that ran, in rule-set order, zero-hit rules included.
    rules: tuple[RuleTally, ...]
    #: `(entry_key, hits)`, most hits first, only from `MOST_HIT_FLOOR` up.
    entry_hits: tuple[tuple[str, int], ...]
    #: Records seen, and records with at least one hit.
    records: int
    records_changed: int


class ScrubCounter:
    """Adds up the results of one freeze, or one dry run, per record.

    A record can contribute two texts (its narrative and its
    `UnfHergangTextAnonym` cell). `add` takes the record's key, so such a
    record counts once in `records` while its hits add up."""

    def __init__(self, scrubber: Scrubber) -> None:
        self._order: list[tuple[str, str, RuleSource]] = [
            (r.rule_id, r.tag, r.source) for r in scrubber.rules.regex_rules
        ]
        if scrubber.has_firstnames:
            self._order.append((FIRSTNAME_RULE_ID, NameTag.FIRSTNAME.value, RuleSource.LIST))
        if scrubber.has_lastnames:
            self._order.append((LASTNAME_RULE_ID, NameTag.LASTNAME.value, RuleSource.LIST))
        if scrubber.has_firstnames and scrubber.has_lastnames:
            self._order.append((BOTH_LISTS_RULE_ID, NameTag.NAME.value, RuleSource.LIST))
        self._hits: dict[str, int] = {}
        self._records_by_rule: dict[str, set[str]] = {}
        self._entries: dict[str, int] = {}
        self._seen: set[str] = set()
        self._changed: set[str] = set()

    def add(self, record_key: str, result: ScrubResult) -> None:
        self._seen.add(record_key)
        for hit in result.hits:
            self._hits[hit.rule_id] = self._hits.get(hit.rule_id, 0) + 1
            self._records_by_rule.setdefault(hit.rule_id, set()).add(record_key)
            if hit.entry is not None:
                self._entries[hit.entry] = self._entries.get(hit.entry, 0) + 1
            self._changed.add(record_key)

    def tally(self) -> ScrubTally:
        rows = tuple(
            RuleTally(
                rule_id,
                tag,
                source,
                self._hits.get(rule_id, 0),
                len(self._records_by_rule.get(rule_id, ())),
            )
            for rule_id, tag, source in self._order
        )
        most_hit = sorted(
            ((entry, hits) for entry, hits in self._entries.items() if hits >= MOST_HIT_FLOOR),
            key=lambda eh: (-eh[1], eh[0]),
        )
        return ScrubTally(rows, tuple(most_hit), len(self._seen), len(self._changed))


# ===========================================================================
# Checking a rule set (§19.5)
# ===========================================================================


def _adversarial_strings() -> tuple[str, ...]:
    """Digits, spaces, and a mix with separators: the three shapes a
    backtracking pattern written for numbers, words or plates blows up on."""
    n = ADVERSARIAL_LENGTH
    mixed = ("a1 -." * (n // 5 + 1))[:n]
    return ("1" * n + "!", " " * n + "!", "a" * n + "!", mixed)


def check_rules(rules: ScrubRules) -> list[ScrubImportError]:
    """Every refusal §19.5 lists, over a composed rule set. Empty means the
    set may be stored and used.

    The mandatory rules are checked like any others, which is how their own
    unit test proves they pass the contract the imported ones must meet.
    """
    errors: list[ScrubImportError] = []
    seen: set[str] = set()
    mandatory = {r.rule_id for r in rules.regex_rules if r.source is RuleSource.MANDATORY}

    for rule in rules.regex_rules:
        errors.extend(_check_identity(rule, seen, mandatory))
        seen.add(rule.rule_id)
        try:
            pattern = regex.compile(rule.pattern, regex.VERSION0)
        except regex.error as exc:
            errors.append(
                ScrubImportError(
                    ScrubImportErrorCode.PATTERN_INVALID, rule.rule_id, {"error": str(exc)}
                )
            )
            continue
        errors.extend(_check_pattern(rule, pattern))

    if errors:
        return errors
    return _check_protected(rules)


def _check_identity(rule: RegexRule, seen: set[str], mandatory: set[str]) -> list[ScrubImportError]:
    errors: list[ScrubImportError] = []
    rid = rule.rule_id
    if _RULE_ID_SHAPE.fullmatch(rid) is None:
        errors.append(ScrubImportError(ScrubImportErrorCode.ID_MALFORMED, rid))
    if rid in seen:
        code = (
            ScrubImportErrorCode.ID_RESERVED
            if rid in mandatory and rule.source is not RuleSource.MANDATORY
            else ScrubImportErrorCode.DUPLICATE_ID
        )
        errors.append(ScrubImportError(code, rid))
    if rid in RESERVED_RULE_IDS:
        errors.append(ScrubImportError(ScrubImportErrorCode.ID_RESERVED, rid))
    if rule.tag in RESERVED_TAGS:
        errors.append(ScrubImportError(ScrubImportErrorCode.TAG_RESERVED, rid, {"tag": rule.tag}))
    elif _TAG_SHAPE.fullmatch(rule.tag) is None:
        errors.append(ScrubImportError(ScrubImportErrorCode.TAG_MALFORMED, rid, {"tag": rule.tag}))
    return errors


def _check_pattern(rule: RegexRule, pattern: regex.Pattern[str]) -> list[ScrubImportError]:
    rid = rule.rule_id
    errors: list[ScrubImportError] = []
    try:
        for probe in _adversarial_strings():
            for _ in pattern.finditer(probe, timeout=IMPORT_TIMEOUT_S):
                pass
    except TimeoutError:
        return [ScrubImportError(ScrubImportErrorCode.PATTERN_TOO_SLOW, rid)]

    if pattern.search("") is not None or any(
        m.end() == m.start() for example in rule.must_match for m in pattern.finditer(example)
    ):
        errors.append(ScrubImportError(ScrubImportErrorCode.PATTERN_EMPTY_MATCH, rid))
    if not rule.must_match:
        errors.append(ScrubImportError(ScrubImportErrorCode.NO_MUST_MATCH, rid))
    for example in rule.must_match:
        if not any(m.start() == 0 and m.end() == len(example) for m in pattern.finditer(example)):
            errors.append(
                ScrubImportError(ScrubImportErrorCode.MUST_MATCH_FAILED, rid, {"example": example})
            )
    for example in rule.must_not_match:
        match = pattern.search(example)
        if match is not None:
            errors.append(
                ScrubImportError(
                    ScrubImportErrorCode.MUST_NOT_MATCH_HIT,
                    rid,
                    {"example": example, "matched": match.group()},
                )
            )
    return errors


def _check_protected(rules: ScrubRules) -> list[ScrubImportError]:
    scrubber = Scrubber(rules, timeout_s=IMPORT_TIMEOUT_S)
    errors: list[ScrubImportError] = []
    for protected in (*PROTECTED_STRINGS, *rules.protected):
        try:
            result = scrubber.scrub(protected)
        except ScrubTimeoutError as exc:
            errors.append(ScrubImportError(ScrubImportErrorCode.PATTERN_TOO_SLOW, exc.rule_id))
            continue
        if result.changed:
            errors.append(
                ScrubImportError(
                    ScrubImportErrorCode.PROTECTED_ALTERED,
                    result.hits[0].rule_id,
                    {"protected": protected, "scrubbed": result.text},
                )
            )
    return errors


# ===========================================================================
# Parsing imported files (§19.5)
# ===========================================================================

_RULE_FIELDS: Final = frozenset(
    {"id", "tag", "pattern", "must_match", "must_not_match", "description"}
)
_REQUIRED_RULE_FIELDS: Final = ("id", "tag", "pattern", "must_match")
_TOP_FIELDS: Final = frozenset({"rule", "protected"})


def _decode(content: bytes) -> tuple[str, list[ListNotice]] | ScrubImportError:
    """UTF-8, nothing else (Do-NOT #4). A BOM is reported, then dropped."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return ScrubImportError(
            ScrubImportErrorCode.NOT_UTF8, None, {"byte_offset": str(exc.start)}
        )
    notices: list[ListNotice] = []
    if text.startswith("\ufeff"):
        text = text[1:]
        notices.append(ListNotice(ListNoticeCode.BOM, 1))
    crlf = text.count("\r\n")
    if crlf:
        notices.append(ListNotice(ListNoticeCode.CRLF, crlf))
    return text, notices


def _string_list(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return tuple(str(v) for v in value)


def parse_regex_rules(content: bytes) -> RegexRuleFile | list[ScrubImportError]:
    """The rule TOML, structurally (§19.1). `check_rules` does the rest once
    the file is composed with the mandatory rules and the lists.

    Every rule needs `id`, `tag`, `pattern` and `must_match`; `must_not_match`
    and `description` are optional; nothing else is allowed. Unknown keys are
    refused rather than ignored, so a typo in `must_not_macth` cannot quietly
    drop the examples it was meant to carry.
    """
    decoded = _decode(content)
    if isinstance(decoded, ScrubImportError):
        return [decoded]
    text, notices = decoded
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return [ScrubImportError(ScrubImportErrorCode.TOML_INVALID, None, {"error": str(exc)})]

    errors: list[ScrubImportError] = [
        ScrubImportError(ScrubImportErrorCode.UNKNOWN_FIELD, None, {"field": key})
        for key in sorted(set(data) - _TOP_FIELDS)
    ]
    protected = _string_list(data.get("protected", []))
    if protected is None:
        errors.append(
            ScrubImportError(ScrubImportErrorCode.FIELD_INVALID, None, {"field": "protected"})
        )
    raw_rules = data.get("rule", [])
    if not isinstance(raw_rules, list) or not all(isinstance(r, dict) for r in raw_rules):
        errors.append(ScrubImportError(ScrubImportErrorCode.FIELD_INVALID, None, {"field": "rule"}))
        return errors

    rules: list[RegexRule] = []
    for index, raw in enumerate(raw_rules):
        parsed = _parse_rule(index, raw)
        if isinstance(parsed, RegexRule):
            rules.append(parsed)
        else:
            errors.extend(parsed)
    if errors:
        return errors
    return RegexRuleFile(tuple(rules), protected or (), tuple(notices))


def _parse_rule(index: int, raw: Mapping[str, object]) -> RegexRule | list[ScrubImportError]:
    rid_value = raw.get("id")
    rid = rid_value if isinstance(rid_value, str) else f"#{index + 1}"
    problems = [
        ScrubImportError(ScrubImportErrorCode.UNKNOWN_FIELD, rid, {"field": key})
        for key in sorted(set(raw) - _RULE_FIELDS)
    ]
    problems.extend(
        ScrubImportError(ScrubImportErrorCode.FIELD_MISSING, rid, {"field": key})
        for key in _REQUIRED_RULE_FIELDS
        if key not in raw
    )
    strings: dict[str, str] = {}
    for key in ("id", "tag", "pattern", "description"):
        if key in raw:
            value = raw[key]
            if isinstance(value, str):
                strings[key] = value
            else:
                problems.append(
                    ScrubImportError(ScrubImportErrorCode.FIELD_INVALID, rid, {"field": key})
                )
    examples: dict[str, tuple[str, ...]] = {}
    for key in ("must_match", "must_not_match"):
        if key in raw:
            parsed = _string_list(raw[key])
            if parsed is None:
                problems.append(
                    ScrubImportError(ScrubImportErrorCode.FIELD_INVALID, rid, {"field": key})
                )
            else:
                examples[key] = parsed
    if problems:
        return problems
    return RegexRule(
        rule_id=strings["id"],
        tag=strings["tag"],
        pattern=strings["pattern"],
        must_match=examples["must_match"],
        must_not_match=examples.get("must_not_match", ()),
        source=RuleSource.IMPORTED,
        description=strings.get("description", ""),
    )


def parse_name_list(kind: ListKind, content: bytes) -> NameListFile | list[ScrubImportError]:
    """One name per line, UTF-8 (§19.5).

    Blank lines and `#` comments are skipped; an entry whose key another
    entry already has is a duplicate; an entry with fewer than
    `MIN_ENTRY_LETTERS` letters, or none, is not usable. Every one of those is
    a `ListNotice` count. A list left with no usable entry is refused.
    """
    if kind is ListKind.REGEX:
        raise ValueError("a rule file is parsed by parse_regex_rules")
    decoded = _decode(content)
    if isinstance(decoded, ScrubImportError):
        return [decoded]
    text, notices = decoded

    entries: list[str] = []
    seen: set[str] = set()
    blank = comments = 0
    duplicates: list[str] = []
    too_short: list[str] = []
    no_letters: list[str] = []
    for line in text.splitlines():
        entry = line.strip()
        if not entry:
            blank += 1
            continue
        if entry.startswith("#"):
            comments += 1
            continue
        key = entry_key(entry)
        if not key:
            no_letters.append(entry)
        elif _letter_count(entry) < MIN_ENTRY_LETTERS:
            too_short.append(entry)
        elif key in seen:
            duplicates.append(entry)
        else:
            seen.add(key)
            entries.append(entry)

    for code, count in (
        (ListNoticeCode.BLANK_LINES, blank),
        (ListNoticeCode.COMMENT_LINES, comments),
    ):
        if count:
            notices.append(ListNotice(code, count))
    for code, items in (
        (ListNoticeCode.DUPLICATES, duplicates),
        (ListNoticeCode.TOO_SHORT, too_short),
        (ListNoticeCode.NO_LETTERS, no_letters),
    ):
        if items:
            notices.append(ListNotice(code, len(items), tuple(items[:5])))
    if not entries:
        return [ScrubImportError(ScrubImportErrorCode.LIST_EMPTY, None, {"kind": kind.value})]
    return NameListFile(kind, tuple(entries), tuple(notices))

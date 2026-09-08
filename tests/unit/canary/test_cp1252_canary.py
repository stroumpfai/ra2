"""The cp1252 canary: one corpus-level number, and what it is allowed to mean.

mvp-spec.md §4.4 is unusually emphatic about what this check is *not*. It is not
a damage score, not per record, not per language, and not a correction. The
source system runs no spell check, so a deleted character and a typo are
indistinguishable; any per-record measure would be counting typos with extra
steps. The one thing kept is decisive rather than suggestive:

    zero cp1252-only characters, in a corpus containing French,
    proves the lossy conversion happened.

Its only purpose is to justify asking for a UTF-8 re-export. The tests below
pin the number, and pin the condition that turns the number into evidence.
"""

import pytest

from ra2.domain.canary import (
    CP1252_ONLY_CHARS,
    canary_finding,
    count_canary_chars,
    count_canary_chars_by_char,
)
from ra2.domain.findings import FindingCode, Severity

#: The set mvp-spec.md §4.4 lists, restated so a change to either is noticed.
SPEC_CHARS = "œŒ‘’“”–—…€™šžŠŽŸ‚„†‡‰‹›ˆ˜•"


def test_the_character_set_is_the_one_the_spec_lists():
    assert frozenset(SPEC_CHARS) == CP1252_ONLY_CHARS
    assert len(CP1252_ONLY_CHARS) == len(set(SPEC_CHARS))


def test_every_canary_character_really_is_cp1252_only():
    """Each must encode in Windows-1252 and *not* in Latin-1 — that is what
    makes its absence evidence rather than a coincidence."""
    for char in CP1252_ONLY_CHARS:
        char.encode("cp1252")
        with pytest.raises(UnicodeEncodeError):
            char.encode("latin-1")


def test_ordinary_accented_letters_are_not_canary_characters():
    """They survive the conversion, which is why French still reads afterwards
    and why decoding cannot detect the loss."""
    for char in "éàèùçäöüâêîôûñ":
        assert char not in CP1252_ONLY_CHARS


def test_counting_is_occurrences_not_distinct_characters():
    assert count_canary_chars(["œœœ"]) == 3
    assert count_canary_chars(["œ", "Œ", "…"]) == 3


def test_counting_spans_the_whole_corpus():
    assert count_canary_chars(["a—b", "c", "d…e…f"]) == 3


def test_text_with_none_of_them_counts_zero():
    assert count_canary_chars(["Le conducteur a perdu le controle."]) == 0
    assert count_canary_chars([]) == 0
    assert count_canary_chars([""]) == 0


def test_the_breakdown_agrees_with_the_total():
    texts = ["œuvre — un test…", "cœur", "rien"]
    breakdown = count_canary_chars_by_char(texts)
    assert sum(breakdown.values()) == count_canary_chars(texts)
    assert breakdown == {"œ": 2, "—": 1, "…": 1}


# --- the condition that makes zero mean something --------------------------


def test_zero_in_a_corpus_containing_french_is_reported():
    finding = canary_finding(0, ["de", "fr", "it"])
    assert finding is not None
    assert finding.code is FindingCode.CP1252_CANARY_ZERO
    assert finding.severity is Severity.REPORTED
    assert finding.detail["canary_count"] == "0"
    assert finding.detail["languages"] == "de,fr,it"


def test_zero_without_french_proves_nothing_and_is_not_reported():
    """German and Italian use almost none of these characters, so zero there is
    the expected result, not a discovery. Leaving the condition to the caller
    is how "0 - conversion proven" ends up on a German-only corpus."""
    assert canary_finding(0, ["de"]) is None
    assert canary_finding(0, ["de", "it"]) is None
    assert canary_finding(0, []) is None


def test_a_non_zero_count_is_not_a_finding():
    """There is nothing to report: the characters survived, so the conversion
    did not happen. The count is still stored on the corpus."""
    assert canary_finding(1, ["de", "fr", "it"]) is None
    assert canary_finding(4211, ["fr"]) is None


def test_the_finding_is_corpus_level_with_no_row_key():
    """ "No per-record markers, no per-language damage rate" (§4.4), as an
    assertion: there is no key and no file to hang one on."""
    finding = canary_finding(0, ["fr"])
    assert finding is not None
    assert finding.key is None
    assert finding.file_id is None
    assert finding.line_no is None


def test_languages_are_deduplicated_and_ordered_so_the_report_is_stable():
    """The import report is diffed byte-for-byte against a golden file (M0-D8),
    so anything that reaches it has to be ordered."""
    finding = canary_finding(0, ["it", "fr", "de", "fr"])
    assert finding is not None
    assert finding.detail["languages"] == "de,fr,it"

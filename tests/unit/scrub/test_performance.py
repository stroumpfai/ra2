"""The scrubber stays fast with a large list (sw-design.md §19.3, `docs/performance.md` §8).

Name matching is a set lookup per n-gram, never one alternation over the
list, so its cost follows the text and not the list. This holds that to a
number: a 50 000-entry surname list and 20 000 first names, over 5 000
narratives of 600 characters.

**The budgets are generous on purpose**, about ten times what was measured on
the development machine (0.5 s to compile, 1.5 s for 5 000 narratives;
`docs/performance.md` §8), so a slow CI runner does not fail the gate. What
they catch is a change of *shape*: a scan of the list per token, or a cache
that stopped working, costs orders of magnitude, not a factor of two.
"""

import itertools
import time

import pytest

from ra2.domain.scrub import Scrubber, ScrubRules
from ra2.domain.scrub_mandatory import MANDATORY_RULES

pytestmark = pytest.mark.unit

COMPILE_BUDGET_S = 10.0
SCRUB_BUDGET_S = 15.0
NARRATIVES = 5_000

_SYLLABLES = (
    *("ba", "ce", "di", "fo", "gu", "ha", "ke", "li", "mo", "nu"),
    *("pa", "re", "si", "to", "vu", "wa", "xe", "zo", "bri", "sta"),
)
#: 160 000 invented four-syllable names, deterministically: `Bacedifo`, ...
_NAMES = tuple("".join(parts).capitalize() for parts in itertools.product(_SYLLABLES, repeat=4))
_NARRATIVE = (
    "Der Lenker B1 fuhr auf der Hauptstrasse mit 80 km/h und bremste um 14.30 Uhr, "
    "als G1 abbog. Zeuge Bacedifo Hakelimo rief 079 123 45 67 an; Fahrzeug BE 123456. " * 4
)[:600]


def test_a_large_list_compiles_and_scrubs_within_budget() -> None:
    started = time.perf_counter()
    scrubber = Scrubber(
        ScrubRules(MANDATORY_RULES, firstnames=_NAMES[:20_000], lastnames=_NAMES[:50_000])
    )
    compiled = time.perf_counter() - started

    started = time.perf_counter()
    for _ in range(NARRATIVES):
        result = scrubber.scrub(_NARRATIVE)
    scrubbed = time.perf_counter() - started

    assert "<Phone_1>" in result.text and "<Firstname_1>" in result.text
    assert compiled < COMPILE_BUDGET_S, f"compile took {compiled:.2f} s"
    assert scrubbed < SCRUB_BUDGET_S, f"{NARRATIVES} narratives took {scrubbed:.2f} s"

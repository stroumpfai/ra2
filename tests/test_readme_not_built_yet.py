"""The README's *Not built yet* names nothing that ships (risk F6, `SD47`).

The README is the handover document, and it was the one document here with
nothing behind it. Its *Not built yet* said Scoring, Results and Mismatches
"route to a placeholder" long after all three shipped, and an incoming operator
reading it would be told the deliverable does not exist. `FindingCode` values,
load-bearing UI copy, line endings, import layers and frozen contracts all have
a gate; this gives the README one, in the same idiom.

The test reads each bullet's **bold lead** — the thing the bullet says is not
built — and refuses any nav label whose item is `built=True`. Only the lead, on
purpose: *"Cross-evaluation views. Results and Mismatches read one evaluation at
a time"* is a true bullet that mentions two shipped screens in its body.
"""

import re
from pathlib import Path

from ra2.ui.shell import NAV_ITEMS

README = Path(__file__).resolve().parents[1] / "README.md"
HEADING = "## Not built yet"

#: `- **Docker packaging and an installer.** Planned; …` -> the bold part.
_LEAD = re.compile(r"^- \*\*(?P<lead>.+?)\*\*", re.MULTILINE)


def _names(label: str, lead: str) -> bool:
    """`label` as a word of its own. A hyphenated compound is a different word:
    "Cross-evaluation views" is not the Evaluation screen."""
    return re.search(rf"(?<![\w-]){re.escape(label)}(?![\w-])", lead, re.IGNORECASE) is not None


def _section() -> str:
    text = README.read_text(encoding="utf-8")
    assert HEADING in text, f"README has no '{HEADING}' section; this gate would pass vacuously"
    body = text.split(HEADING, 1)[1]
    return body.split("\n## ", 1)[0]


def _leads() -> list[str]:
    return [match["lead"] for match in _LEAD.finditer(_section())]


def test_the_section_still_has_bullets_to_check() -> None:
    """A rewrite into prose would leave the gate below checking nothing."""
    assert _leads()


def test_no_shipped_screen_is_listed_as_not_built() -> None:
    shipped = [item.label for item in NAV_ITEMS if item.built]
    assert shipped, "NAV_ITEMS lists nothing built; the gate would pass vacuously"
    offending = [(label, lead) for lead in _leads() for label in shipped if _names(label, lead)]
    assert offending == [], "README 'Not built yet' names a screen that ships: " + repr(offending)


def test_the_gate_catches_the_bullet_that_was_there() -> None:
    """The positive control: the exact claim F6 found would fail the gate."""
    lead = "Scoring, Results and Mismatches."
    shipped = [item.label for item in NAV_ITEMS if item.built]
    assert any(_names(label, lead) for label in shipped)
    assert not _names("Evaluation", "Cross-evaluation views.")

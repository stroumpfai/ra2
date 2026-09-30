"""The report template states the app's determinism caveat verbatim (`SD48`).

Risk D3 asks for the caveat "once, plainly, in the evaluation report
template". The app shows the same sentence on the reproducibility card and
under the ranking. Two copies drift unless something compares them.
"""

from pathlib import Path

from ra2.ui.views.results.chrome import DETERMINISM_CAVEAT

TEMPLATE = Path(__file__).resolve().parents[1] / "docs" / "evaluation-report-template.md"


def _prose(text: str) -> str:
    """The template's text with Markdown quote markers and line breaks folded
    away, so a re-wrapped paragraph still compares equal."""
    lines = (line.removeprefix(">").strip() for line in text.splitlines())
    return " ".join(line for line in lines if line)


def test_the_template_quotes_the_caveat_the_app_shows() -> None:
    assert DETERMINISM_CAVEAT in _prose(TEMPLATE.read_text(encoding="utf-8"))

# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
"""The route for a view that is not built yet (sw-design.md §8.1.6).

Codelists, Features, Evaluation, Results and Mismatches have real nav entries
and real routes from phase 1, so the shell is built once and never revisited.
The page renders the *real* shell — the same header, the same nav, the same
active-item derivation — with one card saying what is missing. Nothing about
the shell is special-cased for these five.
"""

from nicegui import ui

from ra2.ui.components import card
from ra2.ui.shell import NavItem, shell

__all__ = ["PLACEHOLDER_NOTE", "register"]

PLACEHOLDER_NOTE = "Not built in phase 1."


def register(item: NavItem) -> None:
    @ui.page(item.path)
    def _page() -> None:
        with (
            shell(title=item.title, description=item.description, active=item.key),
            card(),
            ui.element("div").style("padding:12px 14px;"),
        ):
            ui.label(item.label).classes("lbl")
            ui.label(item.description).style("font-size:12.5px;color:var(--ink2);margin-top:6px;")
            ui.label(PLACEHOLDER_NOTE).props('data-testid="placeholder-note"').style(
                "font-size:12.5px;color:var(--ink3);margin-top:6px;"
            )

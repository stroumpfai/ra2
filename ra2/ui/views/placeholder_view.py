# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
"""The route for a view that is not built yet (sw-design.md §8.1.6).

Codelists, Features, Evaluation, Results and Mismatches have real nav entries
and real routes from phase 1, so the shell is built once and never revisited.
"""

from nicegui import ui

from ra2.ui.shell import NavItem

__all__ = ["register"]


def register(item: NavItem) -> None:
    @ui.page(item.path)
    def _page() -> None:
        # A5 renders this inside `shell(...)`. Until then it is a real route
        # with the right title, which is what the nav test asserts.
        ui.label(item.title)
        ui.label(item.description)
        ui.label("Not built in phase 1.")

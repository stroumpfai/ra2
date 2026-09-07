# STUB — bodies owned by A5 (M5 shell) then M6 (the view itself). Not frozen.
"""Import view — "One delivery becomes one immutable corpus."

Two side-by-side file cards that **never wrap or stack at any width**, the
corpora table, and the create-corpus button with a live record count
(design/nav-import-census/README.md §1).
"""

from nicegui import ui

from ra2.services.container import Services
from ra2.ui.shell import NAV_ITEMS

__all__ = ["register"]

_ITEM = next(i for i in NAV_ITEMS if i.key == "import")


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    def _page() -> None:
        ui.label(_ITEM.title)
        ui.label(_ITEM.description)

    @ui.page("/")
    def _root() -> None:
        """Import is the landing view."""
        ui.navigate.to(_ITEM.path)

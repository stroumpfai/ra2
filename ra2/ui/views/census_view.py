# STUB — bodies owned by A5 (M5 shell) then M7 (the view itself). Not frozen.
"""Census view — "How populated each source column is."

Filter toolbar (three chips + caption + Export CSV), the census table with the
populated bar and the distribution bar, and the two summary cards. Default
sort is Populated descending; changing a chip refilters and resets to page 1.
"""

from nicegui import ui

from ra2.services.container import Services
from ra2.ui.shell import NAV_ITEMS

__all__ = ["register"]

_ITEM = next(i for i in NAV_ITEMS if i.key == "census")


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    def _page() -> None:
        ui.label(_ITEM.title)
        ui.label(_ITEM.description)

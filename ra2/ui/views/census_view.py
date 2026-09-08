# STUB — bodies owned by A5 (M5 shell) then M7 (the view itself). Not frozen.
"""Census view — "How populated each source column is."

Filter toolbar (three chips + caption + Export CSV), the census table with the
populated bar and the distribution bar, and the two summary cards. Default
sort is Populated descending; changing a chip refilters and resets to page 1.

**What M5 delivers here is the shell and the toolbar shape, not the view.**
The census table is a `DataTable` over `CensusService`, whose body is Wave
2's; feeding it invented rows would be a demo branch in production code
(§12.12). M7 fills the card.
"""

from nicegui import ui

from ra2.services.container import Services
from ra2.ui.components import card
from ra2.ui.shell import NAV_ITEMS, shell

__all__ = ["CONTENT_GAP", "CONTENT_PADDING", "register"]

_ITEM = next(i for i in NAV_ITEMS if i.key == "census")

#: README §2: `main > div` is `padding:16px 28px 24px` with a 14px gap.
CONTENT_PADDING = "16px 28px 24px"
CONTENT_GAP = "14px"


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    def _page() -> None:
        with (
            shell(
                title=_ITEM.title,
                description=_ITEM.description,
                active=_ITEM.key,
                content_padding=CONTENT_PADDING,
                content_gap=CONTENT_GAP,
            ),
            card(flex="1", extra="overflow:hidden;"),
            ui.element("div").style("padding:12px 14px;"),
        ):
            ui.label("Census").classes("lbl")
            ui.label("Arrives with the census service (M7).").style(
                "font-size:12.5px;color:var(--ink3);margin-top:6px;"
            )

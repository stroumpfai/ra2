# STUB — bodies owned by A5 (M5 shell) then M6 (the view itself). Not frozen.
"""Import view — "One delivery becomes one immutable corpus."

Two side-by-side file cards that **never wrap or stack at any width**, the
corpora table, and the create-corpus button with a live record count
(design/nav-import-census/README.md §1).

**What M5 delivers here is the shell and the grid, not the view.** The two
file cards and the corpora table are `DataTable` instances driven by
`DeliveryService` / `CorpusService`, whose bodies are Wave 2's; wiring them to
invented fixture data would be a branch in production code that exists only
for a demo (§12.12). So the route renders the real header, the real nav and
the real `minmax(0,1fr) minmax(0,1fr)` grid, and M6 fills the cards.

The grid is the part that had to be settled now: `minmax(0,1fr)` is what lets
the columns shrink below their content width instead of wrapping, and J4
asserts it at 1024 / 1440 / 1920 px.
"""

from nicegui import ui

from ra2.services.container import Services
from ra2.ui.components import card
from ra2.ui.shell import NAV_ITEMS, shell

__all__ = ["CONTENT_GAP", "CONTENT_PADDING", "GRID_STYLE", "register"]

_ITEM = next(i for i in NAV_ITEMS if i.key == "import")

#: README §1: `main > div` is `padding:20px 28px` with a 16px gap.
CONTENT_PADDING = "20px 28px"
CONTENT_GAP = "16px"

#: A CSS grid, **not** flex wrapping. `minmax(0,1fr)` is required so the two
#: columns can shrink below their content width — they must never stack.
GRID_STYLE = (
    "display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start;"
)


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
            ui.element("div").props('data-testid="file-grid"').style(GRID_STYLE),
        ):
            _pending(title="Structured sets")
            _pending(title="Text file")

    @ui.page("/")
    def _root() -> None:
        """Import is the landing view."""
        ui.navigate.to(_ITEM.path)


def _pending(*, title: str) -> None:
    with card(), ui.element("div").style("padding:12px 14px;"):
        ui.label(title).classes("lbl")
        ui.label("Arrives with the delivery services (M6).").style(
            "font-size:12.5px;color:var(--ink3);margin-top:6px;"
        )

"""Views. Each exposes `register(services)`; `create_app()` calls them all.

**Deviation from sw-design.md §8.1.5, which writes `register(app)`.** NiceGUI's
`ui.page` registers on `nicegui.core.app` — the sub-application `create_app()`
mounts — so handing a view our own `FastAPI` instance would be decorative.
What a view actually needs is the services, and it gets them explicitly rather
than reaching into `app.state` (sw-design.md §3: no service reaches for a
global). See CONTRACTS.md.
"""

from ra2.services.container import Services
from ra2.ui.shell import NAV_ITEMS
from ra2.ui.views import census_view, import_view, placeholder_view

__all__ = ["register_all"]


def register_all(services: Services) -> None:
    """Register every nav route: the built views, then the placeholders.

    Unbuilt views still have real nav entries and real routes — the shell is
    built once (sw-design.md §8.1.6).
    """
    import_view.register(services)
    census_view.register(services)
    for item in NAV_ITEMS:
        if not item.built:
            placeholder_view.register(item)

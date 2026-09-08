# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
#
# NAV_ITEMS is seeded here because `create_app()` registers exactly these seven
# routes and the M0 exit criterion checks for them. A5 owns the rendering; the
# routes and the Import/Census copy are from design/nav-import-census/README.md
# and should not drift.
"""Header, 4 nav groups, 7 items, active state derived from the route."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final

from nicegui import ui

from ra2.ui import theme
from ra2.ui.components.icons import NAV_ICONS, svg

__all__ = [
    "BRAND_SUBTITLE",
    "BRAND_TITLE",
    "NAV_GROUPS",
    "NAV_ITEMS",
    "NAV_WIDTH_PX",
    "NavItem",
    "item_for_key",
    "item_for_path",
    "shell",
]

#: sw-design.md §8.2 — load-bearing and asserted in E2E (J4).
NAV_WIDTH_PX: Final = 196

BRAND_TITLE: Final = "RA2"
BRAND_SUBTITLE: Final = "Accident report analysis"


@dataclass(frozen=True, slots=True)
class NavItem:
    key: str
    group: str
    label: str
    path: str
    #: The header `h1`.
    title: str
    #: The one-line description under it. Exactly one line, no controls.
    description: str
    #: False -> routes to `placeholder_view` (sw-design.md §8.1.6).
    built: bool


#: The 4 groups x 7 items. Order is the nav's order.
#:
#: Import and Census copy is **verbatim** from the design README. The other five
#: views are not designed yet, so their copy is provisional and lands with the
#: view (phase 2); the route and the label are not.
NAV_ITEMS: Final[tuple[NavItem, ...]] = (
    NavItem(
        key="import",
        group="Data",
        label="Import",
        path="/import",
        title="Import",
        description="One delivery becomes one immutable corpus.",
        built=True,
    ),
    NavItem(
        key="census",
        group="Data",
        label="Census",
        path="/census",
        title="Census",
        description=("How populated each source column is — the basis for choosing features."),
        built=True,
    ),
    NavItem(
        key="codelists",
        group="Data",
        label="Codelists",
        path="/codelists",
        title="Codelists",
        description="Code and label per source column; labels are editable.",
        built=False,
    ),
    NavItem(
        key="features",
        group="Configure",
        label="Features",
        path="/features",
        title="Features",
        description="What to extract: labelled features and exploratory attributes.",
        built=False,
    ),
    NavItem(
        key="evaluation",
        group="Run",
        label="Evaluation",
        path="/evaluation",
        title="Evaluation",
        description="One corpus, one frozen feature config, N models.",
        built=False,
    ),
    NavItem(
        key="results",
        group="Review",
        label="Results",
        path="/results",
        title="Results",
        description="Per-feature, per-model precision, recall and F1, with intervals.",
        built=False,
    ),
    NavItem(
        key="mismatches",
        group="Review",
        label="Mismatches",
        path="/mismatches",
        title="Mismatches",
        description="Every wrong outcome, with its evidence span, for tagging.",
        built=False,
    ),
)

#: Group label -> its items, in nav order. Four groups — Data, Configure, Run,
#: Review — because permanent orientation in the pipeline is the nav's whole
#: job (README §0, "Purpose").
NAV_GROUPS: Final[tuple[tuple[str, tuple[NavItem, ...]], ...]] = tuple(
    (group, tuple(i for i in NAV_ITEMS if i.group == group))
    for group in dict.fromkeys(i.group for i in NAV_ITEMS)
)

_BY_PATH: Final[dict[str, NavItem]] = {i.path: i for i in NAV_ITEMS}
_BY_KEY: Final[dict[str, NavItem]] = {i.key: i for i in NAV_ITEMS}


def item_for_path(path: str) -> NavItem | None:
    """The nav item a route belongs to, or `None` for an unknown path.

    A pure lookup, so the active-state rule can be asserted without rendering.
    """
    return _BY_PATH.get("/" + path.strip("/"))


def item_for_key(key: str) -> NavItem:
    """The nav item with this key. Raises on an unknown key rather than
    rendering a nav with nothing lit."""
    return _BY_KEY[key]


def _active_key(fallback: str) -> str:
    """The active nav key, **derived from the request path**.

    Nothing stores "which view am I on" — the route already knows, and a second
    copy of that fact is a second thing to keep in sync (README, Interactions:
    "the active item is derived from the current route"). `fallback` is the key
    the view passed; it is used only when there is no request context.
    """
    try:
        path = ui.context.client.request.url.path
    except RuntimeError, AttributeError:  # pragma: no cover - no client context
        return fallback
    item = item_for_path(path)
    return item.key if item is not None else fallback


@contextmanager
def shell(
    *,
    title: str,
    description: str,
    active: str,
    content_padding: str = "20px 28px",
    content_gap: str = "16px",
) -> Iterator[None]:
    """Render header + nav and yield inside the content column.

    `design/nav-import-census/README.md` §0, transcribed:

    - the header spans the **full window width**, and its first cell is exactly
      the nav width, so the vertical rule runs unbroken from header to sidebar;
    - below it, `nav` (fixed 196px) beside `main` (`flex:1; min-width:0`);
    - the content column scrolls. The artboard's fixed board height is *not*
      ported (README, "About the Design Files").

    Built from `ui.element`, never `ui.card` — Quasar's card carries elevation
    and padding this design does not have (R2, §8.2).

    :param content_padding: the content column's padding. Import is
        `20px 28px`; Census is `16px 28px 24px`.
    :param content_gap: the gap between the content column's children.
    :param active: the calling view's nav key, used only when the request path
        is not a nav route.
    """
    theme.inject()
    active_key = _active_key(active)

    with ui.element("div").classes("ra2-root").props('data-testid="shell"'):
        _header(title=title, description=description)
        with ui.element("div").style("display:flex;flex:1;min-height:0;"):
            _nav(active_key)
            with (
                ui.element("main").style("flex:1;min-width:0;display:flex;flex-direction:column;"),
                ui.element("div")
                .props('data-testid="content"')
                .style(
                    f"flex:1;min-height:0;overflow:auto;padding:{content_padding};"
                    f"display:flex;flex-direction:column;gap:{content_gap};"
                ),
            ):
                yield


def _header(*, title: str, description: str) -> None:
    with (
        ui.element("header")
        .props('data-testid="header"')
        .style(
            "flex:none;display:flex;align-items:stretch;background:var(--surface);"
            "border-bottom:1px solid var(--rule);"
        )
    ):
        with (
            ui.element("div")
            .props('data-testid="brand"')
            .style(
                f"width:{NAV_WIDTH_PX}px;flex:none;padding:14px;"
                "border-right:1px solid var(--rule);"
                "display:flex;flex-direction:column;justify-content:center;"
            )
        ):
            ui.label(BRAND_TITLE).classes("mono").style(
                "font-size:15px;font-weight:600;letter-spacing:-.01em;color:var(--ink);"
            )
            ui.label(BRAND_SUBTITLE).classes("lbl").style("margin-top:3px;")
        with ui.element("div").style(
            "flex:1;min-width:0;padding:14px 28px;display:flex;"
            "flex-direction:column;justify-content:center;"
        ):
            with (
                ui.element("h1")
                .props('data-testid="view-title"')
                .style(
                    "margin:0;font-size:19px;font-weight:600;letter-spacing:-.012em;color:var(--ink);"
                )
            ):
                ui.label(title).mark("view-title")
            ui.label(description).mark("view-description").props(
                'data-testid="view-description"'
            ).style("color:var(--ink2);font-size:12.5px;margin-top:2px;")


def _nav(active_key: str) -> None:
    """The 4 groups x 7 items.

    Every item is a real `<a href>`: reachable with Tab alone, focus-ringed by
    the one `--focus` token in `theme.py`, and openable in a new tab. The mock
    leaves focus undesigned (README, "`.navitem` states") and sw-design.md §8.2
    says to add a visible one from a single token, so that is what `--focus`
    is. J5 asserts it.
    """
    with (
        ui.element("nav")
        .props('aria-label="Main" data-testid="nav"')
        .style(
            f"width:{NAV_WIDTH_PX}px;flex:none;background:var(--surface);"
            "border-right:1px solid var(--rule);display:flex;flex-direction:column;"
            "padding-bottom:14px;overflow-y:auto;"
        ),
        ui.element("div").style("display:flex;flex-direction:column;gap:2px;padding-top:14px;"),
    ):
        for index, (group, items) in enumerate(NAV_GROUPS):
            padding = "0 14px 6px" if index == 0 else "16px 14px 6px"
            ui.label(group).classes("lbl").mark(f"nav-group-{group.lower()}").style(
                f"padding:{padding};"
            )
            for item in items:
                _nav_link(item, active=item.key == active_key)


def _nav_link(item: NavItem, *, active: bool) -> None:
    link = ui.link(target=item.path)
    link.classes(remove="nicegui-link", add="navitem")
    link.mark(f"nav-{item.key}")
    props = f'data-testid="nav-{item.key}"'
    if active:
        link.classes(add="on")
        props += ' aria-current="page"'
    link.props(props)
    with link:
        # `sanitize=False`: the content is a module-level constant in
        # `components/icons.py`, never user input.
        ui.html(svg(NAV_ICONS[item.key], size=15), tag="span", sanitize=False).style(
            "display:inline-flex;flex:none;"
        )
        ui.label(item.label)

"""J5 — navigation (sw-design.md §11.5).

> Every nav item routes; header title and description match the specified
> copy; the active item is derived from the route; unbuilt views render the
> placeholder; the nav is keyboard-reachable with a visible focus ring.

The copy assertions duplicate `tests/ui/test_shell_nav.py` on purpose: the UI
layer proves the *element tree* carries it, this one proves the *browser*
renders it after a real navigation.
"""

import pytest

from ra2.ui.shell import NAV_ITEMS
from ra2.ui.views.placeholder_view import PLACEHOLDER_NOTE

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda i: i.key)
def test_every_nav_item_routes_when_clicked(page, server_url, item):
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="nav"]')

    page.click(f'[data-testid="nav-{item.key}"]')
    page.wait_for_url(f"**{item.path}")

    assert page.inner_text('[data-testid="view-title"]').strip() == item.title
    assert page.inner_text('[data-testid="view-description"]').strip() == item.description


@pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda i: i.key)
def test_the_active_item_is_derived_from_the_route(page, server_url, item):
    page.goto(f"{server_url}{item.path}")
    page.wait_for_selector('[data-testid="nav"]')

    lit = page.eval_on_selector_all(
        '[data-testid="nav"] a',
        "els => els.filter(e => e.classList.contains('on'))"
        ".map(e => e.getAttribute('data-testid'))",
    )
    assert lit == [f"nav-{item.key}"]

    current = page.eval_on_selector_all(
        '[data-testid="nav"] a[aria-current="page"]',
        "els => els.map(e => e.getAttribute('data-testid'))",
    )
    assert current == [f"nav-{item.key}"]


@pytest.mark.parametrize("item", [i for i in NAV_ITEMS if not i.built], ids=lambda i: i.key)
def test_unbuilt_views_render_the_placeholder_in_the_real_shell(page, server_url, item):
    page.goto(f"{server_url}{item.path}")
    page.wait_for_selector('[data-testid="placeholder-note"]')
    assert page.inner_text('[data-testid="placeholder-note"]').strip() == PLACEHOLDER_NOTE
    assert page.locator('[data-testid="nav"] a').count() == len(NAV_ITEMS)


def test_the_nav_is_reachable_with_tab_alone(page, server_url):
    """No mouse, no shortcuts: Tab from the top of the document has to arrive
    at the first nav link."""
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="nav"]')
    page.evaluate("() => document.body.focus()")

    reached = None
    for _ in range(20):
        page.keyboard.press("Tab")
        reached = page.evaluate(
            "() => document.activeElement && document.activeElement.getAttribute('data-testid')"
        )
        if reached == "nav-import":
            break
    assert reached == "nav-import", f"Tab never reached the nav (stopped at {reached!r})"


def test_a_focused_nav_item_has_a_visible_focus_ring(page, server_url):
    """The mock leaves focus undesigned; sw-design.md §8.2 requires a visible
    ring from a single token, so `--focus` has to actually paint."""
    page.goto(f"{server_url}/census")
    page.wait_for_selector('[data-testid="nav"]')

    ring = page.evaluate(
        """() => {
            const el = document.querySelector('[data-testid="nav-import"]');
            el.focus();
            const s = getComputedStyle(el);
            return {style: s.outlineStyle, width: s.outlineWidth, color: s.outlineColor};
        }"""
    )
    assert ring["style"] not in ("none", ""), "no focus ring on the focused nav item"
    assert float(ring["width"].removesuffix("px")) >= 2
    assert ring["color"] not in ("", "transparent", "rgba(0, 0, 0, 0)")


def test_every_nav_item_is_a_real_link_with_an_href(page, server_url):
    """Links, not click handlers: openable in a new tab, and the route stays
    the single source of truth for the active item."""
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="nav"]')
    hrefs = page.eval_on_selector_all(
        '[data-testid="nav"] a', "els => els.map(e => new URL(e.href).pathname)"
    )
    assert hrefs == [item.path for item in NAV_ITEMS]


def test_the_root_route_lands_on_import(page, server_url):
    page.goto(f"{server_url}/")
    page.wait_for_url("**/import")
    assert page.inner_text('[data-testid="view-title"]').strip() == "Import"

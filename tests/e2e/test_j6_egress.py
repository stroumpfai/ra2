"""J6 — no egress (sw-design.md §11.5, N1).

> Fail the test on any request to a host other than the server under test —
> this is N1 as a gate, not a policy.

The design README says the fonts come from Google Fonts. N1 forbids any CDN
fetch and N1 wins (SD3), so the fonts are vendored in `ra2/ui/static/fonts/`
and served by the app. This file is what makes that difference enforceable
rather than aspirational: the browser is watched for **every** request it
makes across a full page load, and the served CSS is read for any absolute
URL at all.
"""

import re

import pytest

from ra2.ui import theme
from ra2.ui.shell import NAV_ITEMS

pytestmark = pytest.mark.e2e

#: Schemes a page may use without touching the network.
LOCAL_SCHEMES = ("data:", "blob:", "about:", "javascript:")

#: Any absolute URL. `//host/path` is protocol-relative and just as external.
ABSOLUTE_URL = re.compile(r"""(?:https?:)?//[^\s'")]+""")


def _record(page) -> list[str]:
    seen: list[str] = []
    page.on("request", lambda request: seen.append(request.url))
    return seen


def _external(urls: list[str], server_url: str) -> list[str]:
    return [
        url for url in urls if not url.startswith(server_url) and not url.startswith(LOCAL_SCHEMES)
    ]


@pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda i: i.key)
def test_no_page_load_reaches_any_other_host(page, server_url, item):
    seen = _record(page)
    page.goto(f"{server_url}{item.path}")
    page.wait_for_selector('[data-testid="nav"]')
    page.wait_for_load_state("networkidle")

    assert _external(seen, server_url) == [], "the UI fetched something off-host (N1)"
    assert seen, "no requests were recorded at all — the page did not load"


def test_navigating_the_whole_nav_reaches_no_other_host(page, server_url):
    """A full walk, because a lazily loaded font or icon set would only show
    up on the view that uses it."""
    seen = _record(page)
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="nav"]')
    for item in NAV_ITEMS:
        page.click(f'[data-testid="nav-{item.key}"]')
        page.wait_for_url(f"**{item.path}")
    page.wait_for_load_state("networkidle")

    assert _external(seen, server_url) == []


def test_the_fonts_are_served_by_the_app_itself(page, server_url):
    """The positive half of N1: not merely "nothing external" but "the vendored
    files are the ones actually used"."""
    seen = _record(page)
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="nav"]')
    page.wait_for_load_state("networkidle")

    fonts = [url for url in seen if theme.FONTS_URL_PATH in url]
    assert fonts, "no vendored font was requested — is the @font-face still local?"
    assert all(url.startswith(server_url) for url in fonts)


def test_the_stylesheet_contains_no_absolute_url():
    """A static gate that needs no browser: the one injected stylesheet must
    not name a host. It is the file the CDN would sneak back into."""
    assert ABSOLUTE_URL.search(theme.STYLESHEET) is None
    assert "fonts.googleapis.com" not in theme.STYLESHEET
    assert "fonts.gstatic.com" not in theme.STYLESHEET


@pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda i: i.key)
def test_the_served_html_names_no_other_host(page, server_url, item):
    """`ui.add_css`, `ui.add_head_html` and a stray `<img src>` all end up
    here, so this catches an external URL that never got fetched because the
    element was hidden."""
    response = page.request.get(f"{server_url}{item.path}")
    assert response.ok
    offenders = [
        url
        for url in ABSOLUTE_URL.findall(response.text())
        if not url.lstrip("htps:").startswith(("//127.0.0.1", "//localhost"))
        and not url.startswith(("http://www.w3.org", "https://www.w3.org"))
    ]
    assert offenders == [], f"{item.path} names external URLs: {offenders}"

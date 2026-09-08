"""J4 — layout invariants (sw-design.md §11.5).

The design calls these requirements, not preferences, so they are assertions:

> The two Import file tables **stay side by side at every width** and never
> wrap. […] The zones are height-matched between the two cards so the header
> rules and the pagination rows line up horizontally — this alignment is a
> requirement, not a nicety.

Everything is measured in a real Chromium at the three widths the plan names.
`design/nav-import-census/README.md`, "Responsive behaviour" and §1a.
"""

import pytest
from playwright.sync_api import FloatRect, Page

pytestmark = pytest.mark.e2e

#: The plan's three widths. 1024 is below the ~1030px point where the File
#: column starts to ellipsize, so it exercises the shrink path too.
WIDTHS = (1024, 1440, 1920)
HEIGHT = 900


def _box(page: Page, selector: str) -> FloatRect:
    box = page.locator(selector).first.bounding_box()
    assert box is not None, f"{selector} has no box — it is not rendered"
    return box


@pytest.mark.parametrize("width", WIDTHS)
def test_the_two_file_cards_are_side_by_side_and_never_wrap(page, demo_tables_url, width):
    page.set_viewport_size({"width": width, "height": HEIGHT})
    page.goto(demo_tables_url)
    page.wait_for_selector('[data-card="text"]')

    left = _box(page, '[data-card="structured"]')
    right = _box(page, '[data-card="text"]')

    assert left["y"] == right["y"], f"the cards stacked at {width}px"
    assert right["x"] > left["x"], f"the cards are not side by side at {width}px"


@pytest.mark.parametrize("width", WIDTHS)
def test_the_document_never_scrolls_horizontally(page, demo_tables_url, width):
    page.set_viewport_size({"width": width, "height": HEIGHT})
    page.goto(demo_tables_url)
    page.wait_for_selector('[data-card="text"]')

    scroll_width, client_width = page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
    )
    assert scroll_width <= client_width, (
        f"{width}px: scrollWidth {scroll_width} > clientWidth {client_width}"
    )


@pytest.mark.parametrize("width", WIDTHS)
def test_the_two_card_headers_are_the_same_height(page, demo_tables_url, width):
    page.set_viewport_size({"width": width, "height": HEIGHT})
    page.goto(demo_tables_url)
    page.wait_for_selector('[data-card="text"]')

    left = _box(page, '[data-card="structured"] [data-testid="card-header"]')
    right = _box(page, '[data-card="text"] [data-testid="card-header"]')
    assert left["height"] == right["height"]


@pytest.mark.parametrize("width", WIDTHS)
def test_the_two_pagination_rows_share_a_y(page, demo_tables_url, width):
    page.set_viewport_size({"width": width, "height": HEIGHT})
    page.goto(demo_tables_url)
    page.wait_for_selector('[data-card="text"]')

    left = _box(page, '[data-card="structured"] [data-testid="pagination"]')
    right = _box(page, '[data-card="text"] [data-testid="pagination"]')
    assert left["y"] == right["y"], (
        f"{width}px: the pagination rows are at {left['y']} and {right['y']}"
    )


def test_the_fixed_sizes_the_design_calls_load_bearing(page, demo_tables_url):
    """nav 196, card header 46, Import well 404, `.bar` 78x6, distribution bar
    8px tall with a 230px max width (README, "Fixed sizes worth keeping")."""
    page.set_viewport_size({"width": 1440, "height": HEIGHT})
    page.goto(demo_tables_url)
    page.wait_for_selector('[data-card="text"]')

    assert _box(page, "nav")["width"] == 196
    assert _box(page, '[data-testid="brand"]')["width"] == 196
    assert _box(page, '[data-testid="card-header"]')["height"] == 46
    assert _box(page, '[data-testid="well-structured"]')["height"] == 404
    assert _box(page, '[data-testid="well-text"]')["height"] == 404

    bar = _box(page, '[data-testid="bar"]')
    assert (bar["width"], bar["height"]) == (78, 6)

    track = _box(page, '[data-testid="distbar"] .track')
    assert track["height"] == 8
    assert track["width"] <= 230

    max_width = page.evaluate(
        "() => getComputedStyle(document.querySelector('[data-testid=\"distbar\"]')).maxWidth"
    )
    assert max_width == "230px"


def test_the_file_column_is_the_only_one_that_truncates(page, demo_tables_url):
    """`table-layout: fixed` plus one flexible column: the table can never
    exceed its card, and no column becomes unreachable (README §1a)."""
    page.set_viewport_size({"width": 1024, "height": HEIGHT})
    page.goto(demo_tables_url)
    page.wait_for_selector('[data-card="text"]')

    widths = page.evaluate(
        """() => Object.fromEntries(
            [...document.querySelectorAll('[data-testid="table-structured"] th')]
                .map(th => [th.dataset.column, th.getBoundingClientRect().width])
        )"""
    )
    assert widths["selection"] == 30
    assert widths["rows"] == 52
    assert widths["state"] == 86
    assert widths["action"] == 46

    layout = page.evaluate(
        "() => getComputedStyle(document.querySelector('[data-testid=\"table-structured\"]'))"
        ".tableLayout"
    )
    assert layout == "fixed"


def test_no_component_in_the_kit_is_swallowed_by_quasar(page: Page, demo_tables_url: str) -> None:
    """Quasar ships `.sm` / `.md` / `.lg` breakpoint helpers carrying
    `display:none !important`, so a utility class named after a size silently
    deletes the element it was meant to size. That is how the add button and
    every row action once vanished; this is the tripwire.
    """
    page.set_viewport_size({"width": 1440, "height": HEIGHT})
    page.goto(demo_tables_url)
    page.wait_for_selector('[data-card="text"]')

    invisible = page.evaluate(
        """() => [...document.querySelectorAll(
            '.iconbtn, .tick, .bar, .distbar, .chip, .card, .navitem, .lbl, .sorth'
        )]
            .filter(e => e.getBoundingClientRect().width === 0)
            .map(e => e.className)"""
    )
    assert invisible == [], f"components rendered with a zero box: {invisible}"


def test_the_header_block_is_the_designs_two_tight_lines(page: Page, demo_tables_url: str) -> None:
    """Quasar sets `h1` to 6rem/6rem weight 300. Unreset, the header block is
    145px tall and the description floats 40px below the title instead of the
    design's `margin-top:2px` (README §0, "View title block")."""
    page.set_viewport_size({"width": 1440, "height": HEIGHT})
    page.goto(demo_tables_url)
    page.wait_for_selector('[data-card="text"]')

    title = _box(page, '[data-testid="view-title"]')
    description = _box(page, '[data-testid="view-description"]')

    assert title["height"] < 30, "the h1 kept Quasar's 6rem line box"
    assert description["y"] - (title["y"] + title["height"]) == pytest.approx(2, abs=1)
    assert _box(page, '[data-testid="header"]')["height"] < 90

    styles = page.evaluate(
        """() => {
            const s = getComputedStyle(document.querySelector('[data-testid="view-title"]'));
            return {size: s.fontSize, weight: s.fontWeight};
        }"""
    )
    assert styles["size"] == "19px"
    assert styles["weight"] == "600"

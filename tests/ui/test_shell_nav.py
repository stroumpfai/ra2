"""Layer 3 — the shell (sw-design.md §11.3, first bullet).

Three claims, one per test group:

1. every route renders all **7 nav items in 4 groups**;
2. the active item is **derived from the route**, never stored;
3. the header title and description are the design's copy, **verbatim**.

Claim 3 is asserted against `design/nav-import-census/README.md` for the two
views the README actually specifies, so a paraphrase in `shell.NAV_ITEMS`
fails here rather than at handover.
"""

import re
from pathlib import Path

import pytest

from ra2.ui.shell import (
    BRAND_SUBTITLE,
    BRAND_TITLE,
    NAV_GROUPS,
    NAV_ITEMS,
    item_for_path,
)
from ra2.ui.views.placeholder_view import PLACEHOLDER_NOTE

pytestmark = pytest.mark.ui

DESIGN_README = Path(__file__).resolve().parents[2] / "design" / "nav-import-census" / "README.md"

#: The README states each built view's title and description in its own
#: section heading line: `### 1. Import view` / `Title "Import" / "…"`.
DESIGNED_COPY = {
    "import": ("Import", "One delivery becomes one immutable corpus."),
    "census": (
        "Census",
        "How populated each source column is — the basis for choosing features.",
    ),
}


def test_the_nav_is_four_groups_of_seven_items():
    assert [group for group, _ in NAV_GROUPS] == ["Data", "Configure", "Run", "Review"]
    assert len(NAV_ITEMS) == 7
    assert sum(len(items) for _, items in NAV_GROUPS) == 7


def test_the_design_readme_still_says_what_nav_items_says():
    """The copy in `NAV_ITEMS` is the README's, not a paraphrase of it.

    The README is the handoff; if someone reworded a title here, this is where
    it is caught (§8.1.5: "the header copy is the design's, verbatim").
    """
    readme = DESIGN_README.read_text(encoding="utf-8")
    # The README writes the description with a hard line break in the prose,
    # so compare on collapsed whitespace.
    collapsed = re.sub(r"\s+", " ", readme)
    for key, (title, description) in DESIGNED_COPY.items():
        item = next(i for i in NAV_ITEMS if i.key == key)
        assert item.title == title
        assert item.description == description
        assert description in collapsed, f"{key}: description is not the README's"


@pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda i: i.key)
def test_item_for_path_maps_every_route(item):
    assert item_for_path(item.path) is item
    assert item_for_path(item.path + "/") is item


def test_item_for_path_returns_none_for_an_unknown_route():
    assert item_for_path("/nope") is None


@pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda i: i.key)
async def test_every_route_renders_the_whole_nav(user, item):
    await user.open(item.path)
    for other in NAV_ITEMS:
        assert user.find(marker=f"nav-{other.key}").elements, f"{other.key} is missing"
    for group, _ in NAV_GROUPS:
        assert user.find(marker=f"nav-group-{group.lower()}").elements


@pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda i: i.key)
async def test_the_active_item_is_derived_from_the_route(user, item):
    await user.open(item.path)
    for other in NAV_ITEMS:
        (link,) = user.find(marker=f"nav-{other.key}").elements
        lit = "on" in link.classes
        assert lit is (other.key == item.key), (
            f"on {item.path} the {other.key} item should {'' if other is item else 'not '}be lit"
        )


@pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda i: i.key)
async def test_the_header_carries_this_view_s_copy(user, item):
    await user.open(item.path)
    (title,) = user.find(marker="view-title").elements
    (description,) = user.find(marker="view-description").elements
    assert title.text == item.title
    assert description.text == item.description


async def test_the_brand_block_is_the_designs(user):
    await user.open("/import")
    await user.should_see(BRAND_TITLE)
    await user.should_see(BRAND_SUBTITLE)


@pytest.mark.parametrize("item", [i for i in NAV_ITEMS if not i.built], ids=lambda i: i.key)
async def test_unbuilt_views_render_the_placeholder_inside_the_real_shell(user, item):
    await user.open(item.path)
    await user.should_see(PLACEHOLDER_NOTE)
    # The shell is built once: the placeholder is not a different chrome.
    assert user.find(marker="nav-import").elements


@pytest.mark.parametrize("item", [i for i in NAV_ITEMS if i.built], ids=lambda i: i.key)
async def test_built_views_do_not_render_the_placeholder(user, item):
    await user.open(item.path)
    await user.should_not_see(PLACEHOLDER_NOTE)


async def test_the_root_route_lands_on_import(user):
    await user.open("/")
    await user.should_see("One delivery becomes one immutable corpus.")

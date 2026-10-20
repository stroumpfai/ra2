"""Layer 3 — what the scrubbing dry run replaced (sw-design.md SD70).

The component is driven directly with synthetic examples, so the shapes the
real delivery rarely makes (60 values, a capped list, markup in a sentence)
are exact. One test goes through the real dialog.
"""

import pytest
from nicegui import ui
from nicegui.testing.user import User

from ra2.domain.scrub import ScrubExample, ScrubRuleExamples, ScrubValueExamples
from ra2.ui.components.scrub_examples import (
    INLINE_VALUES,
    VALUES_FIRST_PAGE,
    VALUES_NEXT_PAGE,
    expanded_at_first,
    render_rule_examples,
)

pytestmark = pytest.mark.ui


def _value(name: str, hits: int = 1, *, before: str = "", after: str = "") -> ScrubValueExamples:
    example = ScrubExample("r1", "<Lastname_1>", before, name, after)
    return ScrubValueExamples(name, hits, 1, (example,))


def _rule(count: int, *, other_hits: int = 0) -> ScrubRuleExamples:
    values = tuple(_value(f"Name{i:03d}", count - i) for i in range(count))
    return ScrubRuleExamples("lastnames", values, other_hits)


def _rows(user: User) -> list[object]:
    return [
        e
        for e in user.find(kind=ui.element).elements
        if e._props.get("data-testid") == "scrub-value-row"
    ]


def _by_testid(user: User, testid: str) -> list[object]:
    return [e for e in user.find(kind=ui.element).elements if e._props.get("data-testid") == testid]


def _mount(rule: ScrubRuleExamples):  # type: ignore[no-untyped-def]
    @ui.page("/examples")
    def page() -> None:
        render_rule_examples(ui.element("div"), rule, "<Lastname_n>")


async def test_a_short_list_opens_expanded_and_shows_every_value(user: User) -> None:
    rule = _rule(3)
    assert expanded_at_first(rule)
    _mount(rule)
    await user.open("/examples")
    assert len(_rows(user)) == 3
    assert not _by_testid(user, "scrub-filter")
    assert not _by_testid(user, "scrub-more")


async def test_no_values_is_not_expandable() -> None:
    assert not expanded_at_first(ScrubRuleExamples("phone", ()))


async def test_a_long_list_opens_collapsed_and_pages(user: User) -> None:
    rule = _rule(60)
    assert not expanded_at_first(rule)
    assert INLINE_VALUES < 60
    _mount(rule)
    await user.open("/examples")
    assert len(_rows(user)) == VALUES_FIRST_PAGE
    assert len(_by_testid(user, "scrub-more")) == 1
    user.find(marker="scrub-more").click()
    assert len(_rows(user)) == min(60, VALUES_FIRST_PAGE + VALUES_NEXT_PAGE)
    assert not _by_testid(user, "scrub-more")


async def test_the_filter_narrows_to_the_matching_value(user: User) -> None:
    _mount(_rule(60))
    await user.open("/examples")
    user.find(kind=ui.input).type("name042")
    await user.should_see("Name042")
    assert len(_rows(user)) == 1
    user.find(kind=ui.input).clear().type("zzz")
    await user.should_see("No value matches.")


async def test_a_capped_list_says_so(user: User) -> None:
    _mount(_rule(30, other_hits=1700))
    await user.open("/examples")
    await user.should_see("Showing the first 30 values met")
    await user.should_see("1 700 further replacements")
    user.find(kind=ui.input).type("zzz")
    await user.should_see("may be among the replacements not listed")


async def test_markup_and_newlines_in_a_sentence_render_as_text(user: User) -> None:
    value = _value("<b>&amp;", before="a <i>", after="x & y")
    _mount(ScrubRuleExamples("lastnames", (value,)))
    await user.open("/examples")
    await user.should_see("<b>&amp;")
    await user.should_see("…a <i>")
    await user.should_see("x & y…")

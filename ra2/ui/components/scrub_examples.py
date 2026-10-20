# NEW — plan-scrub-diff.md. Not frozen.
"""What a scrubbing rule replaced, for the dry-run dialog (sw-design.md SD70).

One rule's values, most-hit first, each with the sentences it was found in. The
matched span is the original; the words around it are already scrubbed. **The
span is personal data**, so it goes into element *text* only, never into a prop
or an attribute, and nothing here logs.

State (how many values are shown, the filter) lives in closures of one dialog,
never in a module global (Do-NOT #8); the examples themselves come from the
service. **No business logic** (Do-NOT #7): this words and pages what the
service already collected.
"""

from dataclasses import dataclass

from nicegui import ui
from nicegui.element import Element
from nicegui.events import ValueChangeEventArguments

from ra2.domain.scrub import ScrubRuleExamples, ScrubValueExamples
from ra2.ui.components.primitives import data_props, format_count

__all__ = [
    "FILTER_LABEL",
    "INLINE_VALUES",
    "NO_MATCH_CAPPED_TEXT",
    "NO_MATCH_TEXT",
    "SHOW_MORE_LABEL",
    "VALUES_FIRST_PAGE",
    "VALUES_NEXT_PAGE",
    "expanded_at_first",
    "render_rule_examples",
]

#: A rule with this many values or fewer opens expanded and lists them all.
INLINE_VALUES = 20
#: Values listed when a longer list is opened, and added by each *Show more*.
VALUES_FIRST_PAGE = 25
VALUES_NEXT_PAGE = 100

SHOW_MORE_LABEL = "Show more"
FILTER_LABEL = "Filter values"
NO_MATCH_TEXT = "No value matches."
NO_MATCH_CAPPED_TEXT = "No listed value matches; it may be among the replacements not listed."


@dataclass
class _Paging:
    limit: int = VALUES_FIRST_PAGE
    text: str = ""


def expanded_at_first(rule: ScrubRuleExamples) -> bool:
    return 0 < len(rule.values) <= INLINE_VALUES


def _capped_note(rule: ScrubRuleExamples) -> str:
    return (
        f"Showing the first {format_count(len(rule.values))} values met; "
        f"{format_count(rule.other_hits)} further replacements of other values are "
        "counted but not listed."
    )


def _example_line(value: ScrubValueExamples, placeholder: str) -> None:
    for example in value.examples:
        with (
            ui.element("div")
            .props('data-testid="scrub-example"')
            .style("display:flex;flex-wrap:wrap;gap:0 4px;font-size:11.5px;padding-left:12px;")
        ):
            if example.before:
                ui.label(f"…{example.before}").classes("ink3")
            ui.label(example.matched).classes("mono").props(
                'data-testid="scrub-example-span"'
            ).style("text-decoration:line-through;color:var(--ink2);white-space:pre-wrap;")
            ui.label("→").classes("ink3")
            ui.label(example.placeholder or placeholder).classes("mono")
            if example.after:
                ui.label(f"{example.after}…").classes("ink3")


def _value_block(value: ScrubValueExamples, placeholder: str) -> None:
    with (
        ui.element("div")
        .props('data-testid="scrub-value-row"')
        .style("padding:4px 0;border-top:1px solid var(--rule2);")
    ):
        with ui.element("div").style("display:flex;gap:8px;align-items:baseline;"):
            ui.label(value.value).classes("mono").style("font-size:12px;")
            ui.label(f"→ {placeholder} · {format_count(value.hits)}×").classes("ink3").style(
                "font-size:11.5px;"
            )
            ui.label(f"{format_count(value.records)} records").classes("ink3").style(
                "font-size:11.5px;"
            )
        _example_line(value, placeholder)


def render_rule_examples(host: Element, rule: ScrubRuleExamples, placeholder: str) -> None:
    """Fill `host` with `rule`'s values, a filter when the list is long, and
    *Show more*. `placeholder` is the rule's generic form, `<Phone_n>`."""
    state = _Paging()
    long_list = len(rule.values) > INLINE_VALUES
    data_props(host, {"data-rule-id": rule.rule_id})

    def redraw() -> None:
        body.clear()
        needle = state.text.strip().casefold()
        matching = [v for v in rule.values if needle in v.value.casefold()]
        shown = matching[: state.limit] if long_list else matching
        with body:
            if rule.other_hits:
                ui.label(_capped_note(rule)).classes("ink3").props(
                    'data-testid="scrub-cap-note"'
                ).style("font-size:11.5px;")
            if not matching:
                ui.label(NO_MATCH_CAPPED_TEXT if rule.other_hits else NO_MATCH_TEXT).classes(
                    "ink3"
                ).style("font-size:11.5px;")
            for value in shown:
                _value_block(value, placeholder)
            if len(shown) < len(matching):
                ui.button(SHOW_MORE_LABEL, on_click=show_more).props(
                    'flat dense no-caps data-testid="scrub-more"'
                ).mark("scrub-more")

    def show_more() -> None:
        state.limit += VALUES_NEXT_PAGE
        redraw()

    def on_filter(event: ValueChangeEventArguments[str | None]) -> None:
        state.text = str(event.value or "")
        state.limit = VALUES_FIRST_PAGE
        redraw()

    with host:
        if long_list:
            # Outside `body`, so a keystroke's redraw does not replace the
            # field the person is typing in.
            ui.input(FILTER_LABEL, on_change=on_filter).props(
                'dense outlined debounce=300 data-testid="scrub-filter"'
            )
        body = ui.element("div")
    redraw()

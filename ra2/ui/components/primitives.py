# STUB — bodies owned by A5 (feat/m5-shell). Not frozen.
"""The component kit: card, card header, chip, tick, icon button, `.bar`,
distribution bar, pagination row, footnote.

Everything here is built from `ui.element`, not from `ui.card` / `ui.table` /
`ui.checkbox`. Quasar's defaults carry elevation, ripple, 40px hit targets and
a type scale this design does not have, and overriding them costs more than
rendering the six elements the design actually specifies (R2, sw-design.md
§8.2).

**None of these components computes anything.** They take numbers and strings
and turn them into DOM. Rates, totals, selections and sort decisions arrive
from a service (§8.1.1).
"""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Final

from nicegui import ui
from nicegui.element import Element

from ra2.ui.components.icons import CHECK, INFO, PLUS, svg
from ra2.ui.state import TableState

__all__ = [
    "PAGE_SIZES",
    "add_button",
    "bar",
    "card",
    "card_header",
    "chip",
    "distribution_bar",
    "footnote",
    "format_count",
    "icon_button",
    "long_tail_bar",
    "pagination_row",
    "tick",
]

#: Rank-order shades for the stacked distribution bar (README, Design Tokens).
DIST_SHADES: Final[tuple[str, ...]] = (
    "var(--dist-1)",
    "var(--dist-2)",
    "var(--dist-3)",
    "var(--dist-4)",
)
#: The alternating pair a long-tail column renders instead of real segments.
LONG_TAIL_SHADES: Final[tuple[str, str]] = ("oklch(0.80 0.006 260)", "oklch(0.86 0.005 260)")
LONG_TAIL_SEGMENTS: Final = 24

#: The page sizes the "Rows per page" selector offers. 10 on Import, 25 on
#: Census (README §1a, §2b).
PAGE_SIZES: Final[tuple[int, ...]] = (10, 25, 50, 100)


def format_count(value: int) -> str:
    """`4978` -> `"4 978"`. A space, exactly as the design files render it.

    Presentation only — the number itself is always a service's.
    """
    return f"{value:,}".replace(",", " ")


def card(*, flex: str = "none", extra: str = "") -> Element:
    """A `.card`: `--surface`, 1px `--rule`, radius 3px, no shadow.

    Elevation in this design is expressed with borders only (README, Shadows).
    """
    return (
        ui.element("section")
        .classes("card")
        .props('data-testid="card"')
        .style(f"display:flex;flex-direction:column;min-width:0;flex:{flex};{extra}")
    )


@contextmanager
def card_header(
    *,
    title: str,
    count: str | None = None,
    count_class: str = "",
) -> Iterator[None]:
    """The fixed 46px header strip. Yields the right-hand control slot.

    `overflow:hidden` is load-bearing: without it the header content bleeds
    over the neighbouring card (README §1a.1).
    """
    with ui.element("div").classes("card-header").props('data-testid="card-header"'):
        with ui.element("div").style("display:flex;align-items:baseline;gap:10px;min-width:0;"):
            ui.label(title).classes("lbl")
            if count is not None:
                ui.label(count).classes(f"mono nowrap {count_class}".strip()).style(
                    "font-size:11px;"
                )
        with ui.element("div").style("display:flex;gap:6px;align-items:center;flex:none;"):
            yield


def icon_button(
    icon: str,
    *,
    label: str,
    size: int = 24,
    glyph: int = 12,
    stroke: float = 2.2,
    on_click: Callable[[], None] | None = None,
    disabled: bool = False,
    extra_class: str = "",
) -> Element:
    """A bordered icon-only button. A real `<button>`, so Tab reaches it and
    the `--focus` ring shows (README: focus is undesigned; add one)."""
    css_size = "iconbtn-md" if size == 24 else "iconbtn-sm"
    button = (
        ui.element("button")
        .classes(f"iconbtn {css_size} {extra_class}".strip())
        .props(f'type="button" aria-label="{label}" title="{label}"')
        .mark(label.lower().replace(" ", "-"))
        .style(f"width:{size}px;height:{size}px;")
    )
    if disabled:
        button.props("disabled")
    elif on_click is not None:
        button.on("click", lambda _: on_click())
    with button:
        ui.html(svg(icon, size=glyph, stroke=stroke), tag="span", sanitize=False).style(
            "display:inline-flex;"
        )
    return button


def add_button(*, label: str, on_click: Callable[[], None] | None = None) -> Element:
    """The card header's single icon-only add button (README §1a.1)."""
    return icon_button(PLUS, label=label, size=24, glyph=12, stroke=2.2, on_click=on_click)


def tick(
    *,
    checked: bool,
    indeterminate: bool = False,
    label: str,
    on_change: Callable[[], None] | None = None,
) -> Element:
    """A 14x14 checkbox with a real **indeterminate** state.

    The header-row tick is indeterminate when a table is partially selected
    (README, Interactions). Whether it is partial is the caller's fact, never
    this component's: it renders `aria-checked="mixed"` when told to.
    """
    state = "mixed" if indeterminate else ("true" if checked else "false")
    classes = "tick"
    if indeterminate:
        classes += " mixed"
    elif checked:
        classes += " on"
    box = (
        ui.element("button")
        .classes(classes)
        .props(
            f'type="button" role="checkbox" aria-checked="{state}" '
            f'aria-label="{label}" title="{label}" data-testid="tick"'
        )
        .mark("tick")
    )
    if on_change is not None:
        box.on("click", lambda _: on_change())
    with box:
        if indeterminate:
            ui.html(
                '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" '
                'stroke="currentColor" stroke-width="3.2" stroke-linecap="round" '
                'aria-hidden="true"><path d="M6 12h12"></path></svg>',
                tag="span",
                sanitize=False,
            ).style("display:inline-flex;")
        elif checked:
            ui.html(svg(CHECK, size=10, stroke=3.2), tag="span", sanitize=False).style(
                "display:inline-flex;"
            )
    return box


def chip(
    text: str,
    *,
    caret: bool = True,
    label: str | None = None,
    on_click: Callable[[], None] | None = None,
) -> Element:
    """A dropdown chip from the Census filter toolbar (README §2a).

    A `<button>` when it is interactive, so the toolbar is keyboard-reachable.
    """
    tag = "button" if on_click is not None else "span"
    element = ui.element(tag).classes("chip").props('data-testid="chip"').mark("chip")
    if on_click is not None:
        element.props(f'type="button" aria-label="{label or text}"')
        element.on("click", lambda _: on_click())
    with element:
        ui.label(text)
        if caret:
            ui.label("▼").classes("caret")
    return element


def bar(*, fill_pct: float) -> Element:
    """The 78x6 `.bar` with an `--ink3` fill at `fill_pct` percent.

    `fill_pct` is a **service's** number. This clamps it to the drawable range
    and draws it; it never derives a rate from counts (§8.1.1).
    """
    drawn = min(100.0, max(0.0, fill_pct))
    element = ui.element("div").classes("bar").props('data-testid="bar"').mark("bar")
    with element:
        ui.element("i").style(f"width:{drawn:g}%;")
    return element


def distribution_bar(*, segments: Sequence[float], legend: str) -> Element:
    """The 8px stacked bar (max-width 230px) plus its mono legend.

    `segments` are percentages in rank order, already computed. Shades come
    from the four-step ramp in the design tokens.
    """
    element = ui.element("div").classes("distbar").props('data-testid="distbar"').mark("distbar")
    with element:
        with ui.element("div").classes("track"):
            for index, pct in enumerate(segments):
                shade = DIST_SHADES[min(index, len(DIST_SHADES) - 1)]
                ui.element("i").style(f"width:{pct:g}%;background:{shade};")
        ui.label(legend).classes("legend")
    return element


def long_tail_bar(*, legend: str) -> Element:
    """A long-tail column: 24 equal alternating segments, no value over 1 %
    (README §2b)."""
    element = ui.element("div").classes("distbar").props('data-testid="distbar"').mark("distbar")
    width = 100 / LONG_TAIL_SEGMENTS
    with element:
        with ui.element("div").classes("track"):
            for index in range(LONG_TAIL_SEGMENTS):
                shade = LONG_TAIL_SHADES[index % 2]
                ui.element("i").style(f"width:{width:.2f}%;background:{shade};")
        ui.label(legend).classes("legend")
    return element


def pagination_row(
    *,
    state: TableState,
    total: int,
    shown: int,
    on_page: Callable[[int], None] | None = None,
    on_page_size: Callable[[int], None] | None = None,
    page_sizes: Sequence[int] = PAGE_SIZES,
) -> Element:
    """ "Rows per page" on the left, the range and prev/next on the right.

    Disabled arrows are **greyed, not hidden** (README, Interactions). The
    range label is formatted from the page metadata a service returned; no
    filtering or slicing happens here.
    """
    first = (state.page - 1) * state.page_size + 1 if shown else 0
    last = first + shown - 1 if shown else 0
    row = ui.element("div").classes("pagerow").props('data-testid="pagination"').mark("pagination")
    with row:
        with ui.element("div").style("display:flex;align-items:center;gap:9px;"):
            ui.label("Rows per page").classes("lbl")
            _page_size_select(state=state, page_sizes=page_sizes, on_page_size=on_page_size)
        with ui.element("div").style("display:flex;align-items:center;gap:9px;"):
            ui.label(f"{first}–{last} of {format_count(total)}").classes("mono nowrap").props(
                'data-testid="pagination-range"'
            ).mark("pagination-range").style("font-size:11px;color:var(--ink2);")
            _arrow(
                "‹",
                label="Previous page",
                disabled=state.page <= 1,
                target=state.page - 1,
                on_page=on_page,
                testid="page-prev",
            )
            _arrow(
                "›",
                label="Next page",
                disabled=last >= total,
                target=state.page + 1,
                on_page=on_page,
                testid="page-next",
            )
    return row


def _page_size_select(
    *,
    state: TableState,
    page_sizes: Sequence[int],
    on_page_size: Callable[[int], None] | None,
) -> None:
    select = (
        ui.element("select")
        .classes("chip")
        .props('aria-label="Rows per page" data-testid="page-size"')
        .style("padding:3px 8px;font-size:11px;")
    )
    if on_page_size is not None:
        select.on(
            "change",
            lambda event: on_page_size(int(event.args["target"]["value"])),
            args=[["target", "value"]],
        )
    with select:
        for size in page_sizes:
            option = ui.element("option").props(f'value="{size}"')
            if size == state.page_size:
                option.props("selected")
            with option:
                ui.label(str(size))


def _arrow(
    glyph: str,
    *,
    label: str,
    disabled: bool,
    target: int,
    on_page: Callable[[int], None] | None,
    testid: str,
) -> None:
    button = (
        ui.element("button")
        .classes("iconbtn iconbtn-md")
        .props(f'type="button" aria-label="{label}" title="{label}" data-testid="{testid}"')
        .mark(testid)
    )
    if disabled or on_page is None:
        button.props("disabled")
    else:
        button.on("click", lambda _: on_page(target))
    with button:
        ui.label(glyph)


def footnote(text: str, *, tone: str = "muted") -> Element:
    """The note below a card's pagination row.

    `tone="muted"` is `--ink3` on no background; `tone="info"` is the
    `--accent-soft` note in `--note-ink` (README §1a.4). Footnote heights may
    differ between two cards — it sits *below* the pagination row, which is
    what has to align.
    """
    skin = (
        "background:var(--accent-soft);color:var(--note-ink);"
        if tone == "info"
        else "color:var(--ink3);"
    )
    element = (
        ui.element("div")
        .props('data-testid="footnote"')
        .style(
            "padding:10px 14px;border-top:1px solid var(--rule2);font-size:11.5px;"
            f"display:flex;gap:7px;align-items:flex-start;{skin}"
        )
    )
    with element:
        ui.html(svg(INFO, size=14, stroke=1.8), tag="span", sanitize=False).style(
            "flex:none;margin-top:1px;display:inline-flex;"
        )
        ui.label(text)
    return element

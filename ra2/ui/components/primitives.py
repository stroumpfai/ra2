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

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
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
    "data_props",
    "dialog_card",
    "distribution_bar",
    "field_select",
    "fingerprint_badge",
    "footnote",
    "format_count",
    "format_gigabytes",
    "format_latency_ms",
    "format_local",
    "format_tokens",
    "frozen_readout",
    "icon_button",
    "labeled_field",
    "long_tail_bar",
    "master_detail_split",
    "pagination_row",
    "pill",
    "radio_option",
    "scroll_well",
    "segmented_control",
    "slot_highlighted_block",
    "step_label",
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

#: Where `format_tokens` switches from a thousands space to `M`.
_TOKENS_PER_MILLION: Final = 1_000_000
#: Decimal GB, matching `GpuInfo.total_vram_gb` and how Ollama reports sizes.
_BYTES_PER_GB: Final = 1_000_000_000


def format_count(value: int) -> str:
    """`4978` -> `"4 978"`. A space, exactly as the design files render it.

    Presentation only — the number itself is always a service's.
    """
    return f"{value:,}".replace(",", " ")


def format_gigabytes(value: int) -> str:
    """`8_500_000_000` -> `"8.5 GB"`. Decimal GB, one decimal, everywhere a
    model's size is rendered.

    **Decimal, not binary**, matching `GpuInfo.total_vram_gb` and how Ollama
    itself reports sizes: the Models card's `· 8.5 GB`, the VRAM-limit refusal
    it can turn into, and Ranking's VRAM column (`SD41`) are three renderings
    of one datum, and a 7 % unit disagreement between them would read as a
    disagreement about the model.

    Presentation only — the byte count is always a service's.
    """
    return f"{value / _BYTES_PER_GB:.1f} GB"


def format_tokens(count: int) -> str:
    """`2_100_000` -> `"2.1 M"`; `69_000` -> `"69 000"`. One rule for a token
    count, wherever one is rendered.

    A token count is a *magnitude*, not a measurement being compared: the
    progress card's metrics line and Ranking's Prompt tokens column both
    answer "how much did this cost", and a millions figure spelled out to the
    digit ("2 100 000") is read digit by digit before it is understood. Above
    a million it renders `M` to one decimal, and below it falls through to
    `format_count`'s thousands space — the design's own two renderings
    ("2.1 M prompt tok", "2.4 M tok") plus the small case a 200-record run
    actually produces.

    **Not `format_latency_ms`'s rule.** That one holds a single unit down a
    column *because* the numbers there are compared against each other; these
    are not, and the unit switch costs nothing a reader has to unpick.
    """
    if count >= _TOKENS_PER_MILLION:
        return f"{count / _TOKENS_PER_MILLION:.1f} M"
    return format_count(count)


def format_latency_ms(ms: int) -> str:
    """`812` -> `"0.81 s"`. Seconds, two decimals, one rule everywhere.

    **Not `progress_card.format_duration_ms`**, which renders `1 min 40 s`.
    That one is for a span a person waits out — elapsed, ETA — where minutes
    are the unit and a sub-second value honestly reads `0 s`. A latency is a
    *measurement being compared between models*, which is what the Ranking
    column exists for, and a comparison needs one unit and one precision:
    two decimals span the 0.4 s of a GPU host and the 190 s of a thinking
    model on CPU without a unit switch that would make a column of numbers
    incommensurable.

    A value that is greater than zero but rounds to `0.00` renders
    `< 0.01 s`. A connection probe answers in single-digit milliseconds, and
    `0.00 s` there reads as *zero* rather than as *instant* — the same rule
    `SuppressedCell` follows one layer up: never print a number that says
    something the datum does not.
    """
    if 0 < ms < 5:
        return "< 0.01 s"
    return f"{ms / 1000:.2f} s"


def format_local(value: datetime, fmt: str) -> str:
    """A stored instant as the **host's own** wall clock, then `strftime`.

    RA2 is a loopback-only desktop application (N1): the browser and the
    server are the same machine, so `astimezone()` with no argument is the
    analyst's zone, and no timezone setting, browser round trip or `Settings`
    field is needed to reach it.

    A naive value is read as UTC, which is what `persistence.models.
    UtcDateTime` guarantees for everything that came through the ORM and what
    `Clock.now()` guarantees for everything that did not. Reading it as
    *local* instead would shift it silently by the host's offset.

    Stored, exported and API values are unaffected: local time is a property
    of reading a screen, and it stops at the screen.
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone().strftime(fmt)


def data_props[E: Element](element: E, values: Mapping[str, object]) -> E:
    """Assign props whose values did **not** come from this source file (SD31).

    `element.props("k=v")` is a *parser*, not a formatter: `Props.parse` hands
    every quoted value to `ast.literal_eval`, so an interpolated value is read
    as **Python source**. A filename `Unfall\\next.csv` arrives with a literal
    newline in it; a feature set named `draft\\` ends the quoted run early and
    the prop **disappears entirely**, silently. `html.escape` is no defence —
    it handles `&`, `<`, `>` and quotes, and the parser it feeds cares about
    backslashes.

    Writing into `element.props` — an `ObservableDict`, so the write still
    fires `element.update()` — bypasses that parser. It is also the *last*
    escaping hop: the mapping is serialised as JSON and handed to `Vue.h` as
    the props of a native tag, which sets attributes through the DOM API. No
    HTML parsing happens anywhere on that path, so **do not** `html.escape` a
    value on its way in here; that would put a literal `&amp;` on screen.

    Returns the element, so it composes with the chained builders around it.

    Only values that are literals in the calling source file — a `data-testid`,
    a `type="button"`, an `int`, an enum member's `.value`, a `"true"`/`"false"`
    chosen from a `bool` — may stay in a props *string*. Everything a person
    typed, a delivery supplied or the environment set comes through here.
    `tests/ui/test_props_provenance.py` holds the floor of that rule.
    """
    for key, value in values.items():
        element.props[key] = value
    return element


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
def dialog_card(*, extra: str = "") -> Iterator[Element]:
    """The div-then-card wrapper every `ui.dialog()` body needs, yielding the
    card to build the dialog's content in.

    Two Quasar defaults are being defeated here, both scoped to `.q-dialog__
    inner > div` — the literal element this function creates:

    - Quasar re-enables pointer events by *tag*, on that selector; a
      `<section class="card">` as the dialog's direct child renders but is
      completely unclickable, so the card has to go one level in.
    - `.q-dialog__inner--minimized > div` — the same element — also carries a
      hardcoded `max-width:560px` (plus `overflow:auto`), a Quasar default
      that wins over any width the *card* declares, because the cap sits one
      level higher, on this wrapper, not on the card. A card wider than
      560px (everything but the narrowest dialog) rendered correctly-sized
      but clipped, with a horizontal scrollbar standing in for the missing
      ~200px — a manual-testing report on the file report modal (its 760px
      card, the widest of the five) is where this was actually visible, but
      every dialog with a card wider than 560px carries the same defect. The
      wrapper's own inline `max-width:96vw` — which wins over Quasar's
      class-based rule with no `!important` behind it — removes the cap
      without reintroducing page-level scroll on a narrow window.

    The card's own cap is `max-width:100%` **of the wrapper**, not a second,
    independent `96vw`: `.q-dialog__inner` adds 24px of padding on each side,
    so a card computing `96vw` straight off the viewport ignores that padding
    and can still overflow the wrapper by ~48px at viewport widths where the
    padding, not the `96vw` cap, is what makes the wrapper the narrower of
    the two. Deriving the card's cap from the wrapper's own resolved box —
    whatever produced it — keeps the two in agreement instead of each
    independently guessing the same number.
    """
    with (
        ui.element("div").style("border-radius:3px;max-width:96vw;"),
        card(extra=f"max-width:100%;{extra}") as c,
    ):
        yield c


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
    button = data_props(
        ui.element("button")
        .classes(f"iconbtn {css_size} {extra_class}".strip())
        .props('type="button"')
        .mark(label.lower().replace(" ", "-"))
        .style(f"width:{size}px;height:{size}px;"),
        {"aria-label": label, "title": label},
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
    disabled: bool = False,
    on_change: Callable[[], None] | None = None,
) -> Element:
    """A 14x14 checkbox with a real **indeterminate** state.

    The header-row tick is indeterminate when a table is partially selected
    (README, Interactions). Whether it is partial is the caller's fact, never
    this component's: it renders `aria-checked="mixed"` when told to.

    `disabled` renders a tick that is **visibly** not interactive — the
    `disabled` attribute, so the browser and a screen reader both know, and
    `aria-disabled` for assistive tech that reads the role rather than the
    tag. Omitting `on_change` alone only makes a tick *inert*: it still looks
    live and silently swallows the click, which is how the Evaluation view's
    model rows behaved before an evaluation existed to record a selection
    into.
    """
    state = "mixed" if indeterminate else ("true" if checked else "false")
    classes = "tick"
    if indeterminate:
        classes += " mixed"
    elif checked:
        classes += " on"
    if disabled:
        classes += " disabled"
    box = data_props(
        ui.element("button")
        .classes(classes)
        .props(
            f'type="button" role="checkbox" aria-checked="{state}" data-testid="tick"'
            + (' disabled aria-disabled="true"' if disabled else "")
        )
        .mark("tick"),
        {"aria-label": label, "title": label},
    )
    if on_change is not None and not disabled:
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
        element.props('type="button"')
        data_props(element, {"aria-label": label or text})
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
        # `args=[["target", "value"]]` looks like a nested-path extraction but
        # is not one: it does not serialise, so `event.args` always comes
        # back `{}` and every page-size change was silently inert. The client
        # must emit the value itself.
        select.on(
            "change",
            lambda event: on_page_size(int(event.args)),
            js_handler="(e) => emit(e.target.value)",
        )
    with select:
        for size in page_sizes:
            option = data_props(ui.element("option"), {"value": str(size)})
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
    button = data_props(
        ui.element("button")
        .classes("iconbtn iconbtn-md")
        .props(f'type="button" data-testid="{testid}"')
        .mark(testid),
        {"aria-label": label, "title": label},
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


# --- Phase 2 (Codelists, Features) additions --------------------------------
#
# design/code-feature/README.md, "New utility classes worth naming in the
# implementation": `.seg`, `.rof`/`.ro`, `.fp`, `.pill`, and the master/detail
# split both screens share. Same rules as everything above this line: plain
# `ui.element`, a `data-testid` and a `.mark()` on every node, nothing here
# computes a value it wasn't handed.

_PILL_TONES: Final[frozenset[str]] = frozenset({"ok", "danger", "accent"})


def segmented_control(
    *,
    options: Sequence[str],
    value: str | None,
    label: str,
    on_change: Callable[[str], None] | None = None,
    on_clear: Callable[[], None] | None = None,
    clear_label: str = "Clear",
) -> Element:
    """A `.seg` toggle — the Features edit zone's Kind field,
    `Labelled | Exploratory` (README, "Kind / Grain / Value type"), and the
    Mismatches row's three-way tag control (sw-design.md §17, W2).

    Real `<button>`s in a `role="group"`, not a styled `<div>`: Tab reaches
    every segment and the active one carries `aria-pressed="true"`. Which
    option is active is the caller's fact; this only reports a click.

    **Any number of options, and `value=None` is a real state.** Phase 5 needs
    three segments where phase 2 needed two, and it needs "nothing chosen yet"
    to be renderable — an untagged mismatch is the *normal* state of a row
    nobody has reviewed, not a missing value. With `value=None` every segment
    carries `aria-pressed="false"`, which is exactly what a screen reader
    should hear.

    `on_clear` adds a trailing **action**, not a fourth value. It carries no
    `aria-pressed` and is not in `options`, so "how many values does this
    control have" has the same answer in the DOM, in the accessibility tree
    and in `MismatchTag`. It is **disabled when there is nothing to clear**
    rather than hidden — the same rule `pagination_row` follows, so the
    control does not change width as an analyst tags rows (`Q4`).
    """
    group = data_props(
        ui.element("div").classes("seg").props('role="group" data-testid="seg"').mark("seg"),
        {"aria-label": label},
    )
    with group:
        for option in options:
            active = option == value
            button = (
                ui.element("button")
                .classes(f"seg-btn{' on' if active else ''}")
                .props(
                    'type="button" '
                    f'aria-pressed="{"true" if active else "false"}" '
                    'data-testid="seg-option"'
                )
                .mark("seg-option", f"seg-{option.lower().replace(' ', '-')}")
            )
            if on_change is not None:
                button.on("click", lambda _, o=option: on_change(o))
            with button:
                ui.label(option)
        if on_clear is not None:
            _clear_segment(label=clear_label, enabled=value is not None, on_clear=on_clear)
    return group


def _clear_segment(*, label: str, enabled: bool, on_clear: Callable[[], None]) -> None:
    """The trailing clear action of a `segmented_control`.

    Deliberately **not** a `seg-option`: no `aria-pressed`, its own marker and
    its own `data-testid`, so a test counting the control's values counts
    three and not four.
    """
    button = data_props(
        ui.element("button")
        .classes("seg-btn seg-clear" if enabled else "seg-btn seg-clear disabled")
        .props('type="button" data-testid="seg-clear"' + ("" if enabled else " disabled"))
        .mark("seg-clear"),
        {"aria-label": label},
    )
    if enabled:
        button.on("click", lambda _: on_clear())
    with button:
        #: A multiplication sign, not an "x": it is the glyph the rest of this
        #: design family uses for a dismiss and it is not a letter a screen
        #: reader will try to pronounce. The `aria-label` is what is announced.
        ui.label("×").props('aria-hidden="true"')


def field_select(
    text: str,
    *,
    label: str | None = None,
    disabled: bool = False,
    on_click: Callable[[], None] | None = None,
) -> Element:
    """A `.rof` full-width field readout — the editable half of the
    Codelists/Features select pair (`display:flex; width:100%;
    justify-content:space-between`). **Not** `.sl`/`chip`, which must stay
    `nowrap` for toolbars (README, Design Tokens).

    A real `<button>` when interactive, so Tab reaches it; opening an actual
    option list is a later wave's job — this renders the closed, current
    value. `disabled=True` is the exploratory board's dashed, inert state
    (README, Case D).
    """
    interactive = on_click is not None and not disabled
    classes = "rof disabled" if disabled else "rof"
    tag = "button" if interactive else "span"
    element = ui.element(tag).classes(classes).props('data-testid="rof"').mark("rof")
    if interactive:
        assert on_click is not None
        element.props('type="button"')
        data_props(element, {"aria-label": label or text})
        element.on("click", lambda _: on_click())
    with element:
        ui.label(text)
        if not disabled:
            ui.label("▾").classes("caret")
    return element


def frozen_readout(text: str) -> Element:
    """A `.ro` frozen static readout — same visual family as `field_select`,
    no caret, not interactive. Used throughout the design's "frozen state"
    board, where every control becomes read-only (README, "Frozen state")."""
    element = ui.element("span").classes("ro").props('data-testid="ro"').mark("ro")
    with element:
        ui.label(text)
    return element


def fingerprint_badge(fingerprint: str, *, preview: bool = False) -> Element:
    """A `.fp` 6-character truncated hash in mono type (Features toolbar and
    edit-zone header), with an optional "· preview" qualifier in `--warn` for
    a fingerprint that is not final yet (README, "Definition fingerprint").

    The truncation is a display clamp, exactly like `bar()`'s percentage
    clamp — the full fingerprint is a service's value.
    """
    element = ui.element("span").classes("fp mono").props('data-testid="fp"').mark("fp")
    with element:
        ui.label(fingerprint[:6])
        if preview:
            ui.label("· preview").classes("fp-preview").props('data-testid="fp-preview"').mark(
                "fp-preview"
            )
    return element


def pill(text: str, *, tone: str) -> Element:
    """A small bordered/filled `.pill` status label, reused across three
    states: `tone="ok"` ("100%"), `tone="danger"` ("no codes", outline),
    `tone="accent"` ("LOCKED · 2 evals") (README, Design Tokens).

    One component parameterised by tone rather than three near-duplicates —
    the tone is the caller's classification, never computed here.
    """
    if tone not in _PILL_TONES:
        raise ValueError(f"unknown pill tone: {tone!r} (expected one of {sorted(_PILL_TONES)})")
    element = (
        ui.element("span")
        .classes(f"pill pill-{tone}")
        .props(f'data-testid="pill" data-tone="{tone}"')
        .mark("pill")
    )
    with element:
        ui.label(text)
    return element


def master_detail_split(*, list_extra: str = "", detail_extra: str = "") -> tuple[Element, Element]:
    """The master/detail shell Codelists, Features and Prompts all use:
    `flex:1; min-height:0; display:flex; flex-wrap:nowrap` — a list pane
    floored at 300px, an edit/detail pane floored at 360px. Must never wrap,
    down to 1024px (README, "Layout" and "Responsive behaviour").

    `list_extra` / `detail_extra` are optional inline-style overrides, added
    on top of the two panes' base classes, for a caller whose split needs a
    different geometry than that 452px/300px + 520px/360px default — the
    Evaluation view's setup/progress split floors its left pane 10px
    narrower (`design/prompt-evaluation/README.md` §2, "Layout": setup
    basis 430px, min 320px; progress basis 520px, min 360px) and sizes the
    setup pane to its own content (`align-self:flex-start`). Inline style
    wins over the class, so passing e.g.
    `list_extra="flex:0 1 430px;min-width:320px;align-self:flex-start;"`
    repoints just the numbers that differ. Passing nothing reproduces
    today's geometry exactly — a parameter added to an existing primitive,
    not a new sibling split (CLAUDE.md, "extend, don't replace").

    Returns `(list_pane, detail_pane)`, both already mounted in the split;
    the caller fills each with `with list_pane: ...` / `with detail_pane:`.
    """
    split = ui.element("div").classes("split").props('data-testid="split"').mark("split")
    with split:
        list_pane = (
            ui.element("div")
            .classes("split-list")
            .props('data-testid="split-list"')
            .mark("split-list")
        )
        if list_extra:
            list_pane.style(list_extra)
        detail_pane = (
            ui.element("div")
            .classes("split-detail")
            .props('data-testid="split-detail"')
            .mark("split-detail")
        )
        if detail_extra:
            detail_pane.style(detail_extra)
    return list_pane, detail_pane


# --- Phase 3 (Prompts, Evaluation) additions --------------------------------
#
# design/prompt-evaluation/README.md, §1 (Prompts) and §2 (Evaluation): the
# primitives those two views need that the kit above lacks. Every one of
# these bakes its CSS inline rather than naming a new class in `theme.py` —
# H5 owns `primitives.py` and this test file only (CLAUDE.md, the ownership
# rule); `theme.py` is untouched this wave, so nothing here can add to the
# shared stylesheet. The numbers themselves (196px, 530px, 320px/360px, the
# `{{slot}}` highlight colour) are transcribed from the README, not invented.

#: A `{{name}}`-shaped run. Whether a given name is one of the prompt's
#: **closed** slots is `domain/prompt.py`'s validation concern (sw-design.md
#: §15.1) — this only recognises the shape the design's mock highlights.
_SLOT_PATTERN: Final = re.compile(r"\{\{\w+\}\}")

#: The design's `.sel` base look (`PromptTemplate - A source.dc.html` /
#: `Evaluation.dc.html`, `<style>` block), transcribed verbatim since there is
#: no shared `.sel` class to hang it on yet.
_SEL_BASE: Final = (
    "display:flex;align-items:center;justify-content:space-between;"
    "border:1px solid var(--rule);border-radius:3px;padding:7px 10px;"
    "background:var(--surface);font-family:var(--mono);font-size:11.5px;"
)


@contextmanager
def labeled_field(label: str, *, extra: str = "") -> Iterator[None]:
    """A field with its label drawn **above** the control, not beside it —
    the Determinism step's Temperature/Seed pair, drawn that way explicitly
    "so input and label can't be confused" (Evaluation README §2, step 5).

    Yields nothing; build the field control itself as the `with` block's
    body. The label is the same `.lbl` strip every other label in the kit
    uses, at the 4px gap the design specifies (`margin-bottom:6px` is a
    *step* label's gap, `step_label` below — this is the field's own,
    smaller one, and the two must not be confused with each other either).
    """
    with (
        ui.element("div")
        .props('data-testid="labeled-field"')
        .mark("labeled-field")
        .style(f"display:flex;flex-direction:column;min-width:0;{extra}")
    ):
        ui.label(label).classes("lbl").style("margin-bottom:4px;")
        yield


def radio_option(
    text: str, *, selected: bool, on_click: Callable[[], None] | None = None
) -> Element:
    """A `.sel` radio-style option — the Size step's full/dev choice
    (Evaluation README §2, step 6): a filled `●` and `border-color:--ink`
    when selected, an outline `○` in `--ink3` otherwise. A real `<button>`
    role="radio", so Tab and Enter both reach it; which option is selected
    is the caller's fact, never decided here.
    """
    skin = "flex:1;border-color:var(--ink);" if selected else "flex:1;color:var(--ink3);"
    element = data_props(
        ui.element("button")
        .props(
            'type="button" role="radio" '
            f'aria-checked="{"true" if selected else "false"}" '
            'data-testid="sel-radio"'
        )
        .mark("sel-radio")
        .style(f"{_SEL_BASE}{skin}width:100%;cursor:pointer;"),
        {"aria-label": text},
    )
    if on_click is not None:
        element.on("click", lambda _: on_click())
    with element:
        ui.label(text)
        ui.label("●" if selected else "○")
    return element


def scroll_well(*, max_height_px: int, extra: str = "") -> Element:
    """A scrolling well capped at a fixed row count, expressed as the
    resulting pixel height the design already computed — the models card's 4
    visible rows (196px, Evaluation README §2 step 4) and the Prompts
    version list's 10 × 53px rows (530px, README §1). This only draws the
    box at whatever height the caller hands it; how many rows fit is the
    design's arithmetic, never this component's.
    """
    return (
        ui.element("div")
        .props(f'data-testid="scroll-well" data-max-height-px="{max_height_px}"')
        .mark("scroll-well")
        .style(f"max-height:{max_height_px}px;overflow-y:auto;min-height:0;{extra}")
    )


def slot_highlighted_block(text: str, *, extra: str = "") -> Element:
    """The Prompts editor's Source/Resolved card body (README §1, "Source
    card"): mono, `white-space:pre-wrap` text with every `{{slot}}`-shaped
    token picked out on `--accent-soft`. Matching is purely the literal
    `{{...}}` shape the design's own mock highlights — which names are
    *valid* slots is `domain/prompt.py`'s closed catalogue (sw-design.md
    §15.1), a validation question this rendering-only component has no part
    in answering.
    """
    element = (
        ui.element("div")
        .classes("mono")
        .props('data-testid="slot-block"')
        .mark("slot-block")
        .style(f"white-space:pre-wrap;line-height:1.75;font-size:12px;color:var(--ink);{extra}")
    )
    with element:
        pos = 0
        for match in _SLOT_PATTERN.finditer(text):
            if match.start() > pos:
                _slot_text(text[pos : match.start()])
            _slot_token(match.group())
            pos = match.end()
        if pos < len(text):
            _slot_text(text[pos:])
    return element


def _slot_text(segment: str) -> None:
    ui.label(segment).style("display:inline;white-space:pre-wrap;")


def _slot_token(token: str) -> None:
    ui.label(token).props('data-testid="slot-token"').mark("slot-token").style(
        "display:inline;background:var(--accent-soft);padding:1px 4px;border-radius:2px;"
    )


def step_label(number: int, title: str) -> Element:
    """The setup column's "N · Title" header (Evaluation README §2, the six
    numbered steps) — the same `.lbl` mono/uppercase treatment as every other
    label in the kit, with the ordinal folded into the one string the design
    always renders as a single strip, not a number plus a separate title.
    """
    return (
        ui.label(f"{number} · {title}")
        .classes("lbl")
        .props('data-testid="step-label"')
        .mark("step-label")
        .style("margin-bottom:6px;")
    )

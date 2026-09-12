# STUB — signature only at M9, body owned by G3 (feat/p2-feature-components).
"""Case C's closed-catalogue derivation builder
(design/code-feature/README.md, Screen 2 · Case C).

Declared at M9 (plan-phase-2.md §3) so G2 (the Features view) and G3 (this
component) can build in Wave 4 in parallel: G2 places this component and
wires `on_change` into the feature draft; G2 never reaches inside it.

**No `.tok` utility class exists in `ra2/ui/theme.py` yet** — only the design
mock's own `<style>` block defines one (`design/code-feature/FeatureConfig
.dc.html`). Adding it there is outside this file's ownership for Wave 4
(`theme.py` has no Wave 4 owner), so every chip below carries the design's
`.tok` look — mono type, `--surface` fill, `--rule` border, 5px/9px padding —
as an inline style built from tokens that already exist (`--surface`,
`--rule`, `--ink3`, `--field-tint`), rather than a new shared class. See the
final report for the amendment note this implies for G2's Case A/B chips.

Every control here is a plain `ui.element`, exactly like the phase-1 kit in
`primitives.py` (R2): no `ui.input`, no `ui.select`. An editable value (a
column name, a code) is a bare `<input>` whose `change` event is read via the
same `js_handler="(e) => emit(e.target.value)"` trick `primitives.py`'s
page-size selector already uses, because NiceGUI's automatic argument
extraction does not serialise `event.target.value` on its own.
"""

import html
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Final

from nicegui import ui
from nicegui.element import Element

from ra2.domain.feature import (
    AnyObjectMatches,
    AnyPersonMatches,
    CountObjects,
    CountPersons,
    DerivationSpec,
    DerivationType,
    DistinctCount,
    Filter,
    MaxOrdinal,
    MinOrdinal,
    Operator,
)

__all__ = ["derivation_builder"]

#: The closed catalogue, in the order the type chip cycles through it
#: (mvp-spec.md §8.3, `DerivationType`'s own declaration order).
_DERIVATION_TYPES: Final[tuple[DerivationType, ...]] = tuple(DerivationType)
#: The six operators shared by every filterable derivation, same rule.
_OPERATORS: Final[tuple[Operator, ...]] = tuple(Operator)
#: `MaxOrdinal` / `MinOrdinal` / `DistinctCount`'s closed table choice.
_TABLES: Final[tuple[str, ...]] = ("objekt", "person")

_FILTER_TYPES: Final[frozenset[DerivationType]] = frozenset(
    {
        DerivationType.COUNT_OBJECTS,
        DerivationType.COUNT_PERSONS,
        DerivationType.ANY_OBJECT_MATCHES,
        DerivationType.ANY_PERSON_MATCHES,
    }
)
_TABLE_TYPES: Final[frozenset[DerivationType]] = frozenset(
    {DerivationType.MAX_ORDINAL, DerivationType.MIN_ORDINAL, DerivationType.DISTINCT_COUNT}
)

#: The mock's `.tok` rule (`design/code-feature/FeatureConfig.dc.html`),
#: reproduced inline — see the module docstring for why it is not a class.
_TOK_STYLE: Final = (
    "font-family:var(--mono);font-size:12px;background:var(--surface);"
    "border:1px solid var(--rule);padding:5px 9px;border-radius:3px;"
    "display:inline-flex;align-items:center;gap:7px;"
)
_TOK_DASHED_STYLE: Final = "border-style:dashed;color:var(--ink3);cursor:pointer;"


def _derivation_type_of(spec: DerivationSpec) -> DerivationType:
    if isinstance(spec, CountObjects):
        return DerivationType.COUNT_OBJECTS
    if isinstance(spec, CountPersons):
        return DerivationType.COUNT_PERSONS
    if isinstance(spec, AnyObjectMatches):
        return DerivationType.ANY_OBJECT_MATCHES
    if isinstance(spec, AnyPersonMatches):
        return DerivationType.ANY_PERSON_MATCHES
    if isinstance(spec, MaxOrdinal):
        return DerivationType.MAX_ORDINAL
    if isinstance(spec, MinOrdinal):
        return DerivationType.MIN_ORDINAL
    assert isinstance(spec, DistinctCount)
    return DerivationType.DISTINCT_COUNT


def _default_for(dtype: DerivationType) -> DerivationSpec:
    """A blank-but-valid spec of `dtype` — what the type chip switches to
    when the previous spec's shape shares nothing with the new one."""
    if dtype is DerivationType.COUNT_OBJECTS:
        return CountObjects(filter=None)
    if dtype is DerivationType.COUNT_PERSONS:
        return CountPersons(filter=None)
    if dtype is DerivationType.ANY_OBJECT_MATCHES:
        return AnyObjectMatches(filter=Filter(column="", operator=Operator.EQ, value=""))
    if dtype is DerivationType.ANY_PERSON_MATCHES:
        return AnyPersonMatches(filter=Filter(column="", operator=Operator.EQ, value=""))
    if dtype is DerivationType.MAX_ORDINAL:
        return MaxOrdinal(table="objekt", column="", ordered_codes=())
    if dtype is DerivationType.MIN_ORDINAL:
        return MinOrdinal(table="objekt", column="", ordered_codes=())
    return DistinctCount(table="objekt", column="")


def _change_type(old: DerivationSpec, new_type: DerivationType) -> DerivationSpec:
    """The type chip's edit: keep whatever of the old spec still makes sense
    (the filter, or the table/column pair) and fill in the rest blank."""
    old_type = _derivation_type_of(old)
    if new_type is old_type:
        return old
    if old_type in _FILTER_TYPES and new_type in _FILTER_TYPES:
        old_filter = getattr(old, "filter", None)
        filter_ = (
            old_filter
            if old_filter is not None
            else Filter(column="", operator=Operator.EQ, value="")
        )
        if new_type is DerivationType.COUNT_OBJECTS:
            return CountObjects(filter=filter_)
        if new_type is DerivationType.COUNT_PERSONS:
            return CountPersons(filter=filter_)
        if new_type is DerivationType.ANY_OBJECT_MATCHES:
            return AnyObjectMatches(filter=filter_)
        return AnyPersonMatches(filter=filter_)
    if old_type in _TABLE_TYPES and new_type in _TABLE_TYPES:
        table = getattr(old, "table", "objekt")
        column = getattr(old, "column", "")
        ordered_codes = getattr(old, "ordered_codes", ())
        if new_type is DerivationType.MAX_ORDINAL:
            return MaxOrdinal(table=table, column=column, ordered_codes=ordered_codes)
        if new_type is DerivationType.MIN_ORDINAL:
            return MinOrdinal(table=table, column=column, ordered_codes=ordered_codes)
        return DistinctCount(table=table, column=column)
    return _default_for(new_type)


def _cycle[T](current: T, options: Sequence[T]) -> T:
    """The next value in a closed, ordered catalogue — wraps at the end."""
    values = list(options)
    if current not in values:
        return values[0]
    return values[(values.index(current) + 1) % len(values)]


def _coerce_value(
    value: str | tuple[str, ...] | None, operator: Operator
) -> str | tuple[str, ...] | None:
    """`Filter.value`'s shape is dictated by its operator (domain/feature.py).
    Cycling the operator chip across a shape boundary (e.g. `eq` -> `in`)
    still has to leave a **valid** `Filter` behind, so this reshapes the old
    value rather than dropping it — a presentation-only concern (which Python
    type this field is), not a matching/scoring rule."""
    if operator in (Operator.IS_EMPTY, Operator.IS_NOT_EMPTY):
        return None
    if operator in (Operator.IN, Operator.NOT_IN):
        if isinstance(value, tuple):
            return value
        if isinstance(value, str) and value:
            return (value,)
        return ()
    # EQ / NE
    if isinstance(value, tuple):
        return value[0] if value else ""
    return value if isinstance(value, str) else ""


def _with_replaced(values: tuple[str, ...], index: int, new_value: str) -> tuple[str, ...]:
    return tuple(new_value if i == index else v for i, v in enumerate(values))


def _without(values: tuple[str, ...], index: int) -> tuple[str, ...]:
    return tuple(v for i, v in enumerate(values) if i != index)


def _operator_symbol(operator: Operator) -> str:
    return {
        Operator.EQ: "=",
        Operator.NE: "!=",
        Operator.IN: "in",
        Operator.NOT_IN: "not in",
        Operator.IS_EMPTY: "is empty",
        Operator.IS_NOT_EMPTY: "is not empty",
    }[operator]


def _filter_expression(filter_: Filter) -> str:
    symbol = _operator_symbol(filter_.operator)
    if filter_.operator in (Operator.IS_EMPTY, Operator.IS_NOT_EMPTY):
        return f"{filter_.column} {symbol}"
    if isinstance(filter_.value, tuple):
        values = ", ".join(filter_.value) if filter_.value else "…"
        return f"{filter_.column} {symbol} {values}"
    return f"{filter_.column} {symbol} {filter_.value or '…'}"


def _expression(spec: DerivationSpec) -> str:
    """The "Saved as" mono line — assembled from `spec` alone, never fetched
    (design, Case C)."""
    dtype = _derivation_type_of(spec)
    if isinstance(spec, (CountObjects, CountPersons)):
        if spec.filter is None:
            return dtype.value
        return f"{dtype.value} · {_filter_expression(spec.filter)}"
    if isinstance(spec, (AnyObjectMatches, AnyPersonMatches)):
        return f"{dtype.value} · {_filter_expression(spec.filter)}"
    if isinstance(spec, (MaxOrdinal, MinOrdinal)):
        codes = ", ".join(spec.ordered_codes) if spec.ordered_codes else "…"
        return f"{dtype.value} · {spec.table}.{spec.column} ({codes})"
    assert isinstance(spec, DistinctCount)
    return f"{dtype.value} · {spec.table}.{spec.column}"


# --- chip primitives (local — see module docstring for why `.tok` is inline) -


def _tok_chip(
    text: str, *, on_click: Callable[[], None] | None, testid: str, caret: bool = True
) -> Element:
    tag = "button" if on_click is not None else "span"
    element = (
        ui.element(tag)
        .classes("tok")
        .props(f'data-testid="{testid}"')
        .mark(testid)
        .style(_TOK_STYLE)
    )
    if on_click is not None:
        element.props('type="button"')
        element.on("click", lambda _: on_click())
    with element:
        ui.label(text)
        if caret:
            ui.label("▾").style("color:var(--ink3);font-size:9px;")
    return element


def _add_chip(*, label: str, on_click: Callable[[], None], testid: str) -> Element:
    element = (
        ui.element("button")
        .classes("tok tok-add")
        .props(f'type="button" aria-label="{label}" data-testid="{testid}"')
        .mark(testid)
        .style(_TOK_STYLE + _TOK_DASHED_STYLE)
    )
    element.on("click", lambda _: on_click())
    with element:
        ui.label(label)
    return element


def _text_chip(value: str, *, label: str, on_change: Callable[[str], None], testid: str) -> Element:
    """An editable `.tok`-styled `<input>` — column names and codes are open
    strings, not part of the closed catalogue (design, "Derivation — closed
    catalogue": the *types* and *operators* are closed, values are not)."""
    element = (
        ui.element("input")
        .classes("tok tok-input")
        .props(
            f'type="text" value="{html.escape(value)}" aria-label="{html.escape(label)}" '
            f'data-testid="{testid}"'
        )
        .mark(testid)
        .style(_TOK_STYLE + "min-width:64px;")
    )
    element.on(
        "change",
        lambda event: on_change(str(event.args)),
        js_handler="(e) => emit(e.target.value)",
    )
    return element


def _removable_value_chip(
    value: str, *, on_change: Callable[[str], None], on_remove: Callable[[], None], testid: str
) -> Element:
    """One `M12 ×`-style chip (design, Case C): editable text plus a remove
    button, used by `in`/`not_in` value lists and by ordered-code lists."""
    element = (
        ui.element("span")
        .classes("tok tok-value")
        .props(f'data-testid="{testid}"')
        .mark(testid)
        .style(_TOK_STYLE)
    )
    with element:
        input_element = (
            ui.element("input")
            .props(
                f'type="text" value="{html.escape(value)}" aria-label="Code value" '
                f'data-testid="{testid}-input"'
            )
            .mark(f"{testid}-input")
            .style(
                "border:none;background:transparent;font-family:var(--mono);"
                "font-size:12px;width:44px;padding:0;color:var(--ink);"
            )
        )
        input_element.on(
            "change",
            lambda event: on_change(str(event.args)),
            js_handler="(e) => emit(e.target.value)",
        )
        remove_button = (
            ui.element("button")
            .props(f'type="button" aria-label="Remove {html.escape(value)}"')
            .mark(f"{testid}-remove")
            .style(
                "border:none;background:transparent;color:var(--ink3);cursor:pointer;"
                "font-size:12px;line-height:1;padding:0;"
            )
        )
        remove_button.on("click", lambda _: on_remove())
        with remove_button:
            ui.label("×")
    return element


# --- filter chips (CountObjects/CountPersons/AnyObjectMatches/AnyPersonMatches) -


def _value_chips(
    filter_: Filter, *, on_filter_change: Callable[[Filter], None], prefix: str
) -> None:
    operator = filter_.operator
    if operator in (Operator.IS_EMPTY, Operator.IS_NOT_EMPTY):
        return
    if operator in (Operator.EQ, Operator.NE):
        current = filter_.value if isinstance(filter_.value, str) else ""
        _text_chip(
            current,
            label="Filter value",
            on_change=lambda v: on_filter_change(replace(filter_, value=v)),
            testid=f"{prefix}-value",
        )
        return
    values = filter_.value if isinstance(filter_.value, tuple) else ()
    for index, item in enumerate(values):

        def _on_change(new_value: str, i: int = index) -> None:
            on_filter_change(replace(filter_, value=_with_replaced(values, i, new_value)))

        def _on_remove(i: int = index) -> None:
            on_filter_change(replace(filter_, value=_without(values, i)))

        _removable_value_chip(
            item,
            on_change=_on_change,
            on_remove=_on_remove,
            testid=f"{prefix}-value-{index}",
        )
    _add_chip(
        label="+ code",
        on_click=lambda: on_filter_change(replace(filter_, value=(*values, ""))),
        testid=f"{prefix}-value-add",
    )


def _filter_chips(
    *, filter_: Filter, on_filter_change: Callable[[Filter], None], prefix: str
) -> None:
    _text_chip(
        filter_.column,
        label="Filter column",
        on_change=lambda c: on_filter_change(replace(filter_, column=c)),
        testid=f"{prefix}-column",
    )
    next_operator = _cycle(filter_.operator, _OPERATORS)
    _tok_chip(
        filter_.operator.value,
        on_click=lambda: on_filter_change(
            replace(
                filter_, operator=next_operator, value=_coerce_value(filter_.value, next_operator)
            )
        ),
        testid=f"{prefix}-operator",
    )
    _value_chips(filter_, on_filter_change=on_filter_change, prefix=prefix)


def _optional_filter(
    spec: CountObjects | CountPersons, *, on_change: Callable[[DerivationSpec], None]
) -> None:
    if spec.filter is None:
        _add_chip(
            label="+ filter",
            on_click=lambda: on_change(
                replace(spec, filter=Filter(column="", operator=Operator.EQ, value=""))
            ),
            testid="filter-add",
        )
        return
    filter_ = spec.filter
    _filter_chips(
        filter_=filter_,
        on_filter_change=lambda f: on_change(replace(spec, filter=f)),
        prefix="filter",
    )
    _add_chip(
        label="remove filter ×",
        on_click=lambda: on_change(replace(spec, filter=None)),
        testid="filter-remove",
    )


def _ordinal_chips(
    spec: MaxOrdinal | MinOrdinal, *, on_change: Callable[[DerivationSpec], None]
) -> None:
    next_table = _cycle(spec.table, _TABLES)
    _tok_chip(
        spec.table,
        on_click=lambda: on_change(replace(spec, table=next_table)),
        testid="ordinal-table-chip",
    )
    _text_chip(
        spec.column,
        label="Column",
        on_change=lambda c: on_change(replace(spec, column=c)),
        testid="ordinal-column",
    )
    codes = spec.ordered_codes
    for index, code in enumerate(codes):

        def _on_change(new_value: str, i: int = index) -> None:
            on_change(replace(spec, ordered_codes=_with_replaced(codes, i, new_value)))

        def _on_remove(i: int = index) -> None:
            on_change(replace(spec, ordered_codes=_without(codes, i)))

        _removable_value_chip(
            code,
            on_change=_on_change,
            on_remove=_on_remove,
            testid=f"ordinal-code-{index}",
        )
    _add_chip(
        label="+ code",
        on_click=lambda: on_change(replace(spec, ordered_codes=(*codes, ""))),
        testid="ordinal-code-add",
    )


def _table_column_chips(
    spec: DistinctCount, *, on_change: Callable[[DerivationSpec], None]
) -> None:
    next_table = _cycle(spec.table, _TABLES)
    _tok_chip(
        spec.table,
        on_click=lambda: on_change(replace(spec, table=next_table)),
        testid="distinct-table-chip",
    )
    _text_chip(
        spec.column,
        label="Column",
        on_change=lambda c: on_change(replace(spec, column=c)),
        testid="distinct-column",
    )


def _render_type_specific(
    spec: DerivationSpec, *, on_change: Callable[[DerivationSpec], None]
) -> None:
    if isinstance(spec, (CountObjects, CountPersons)):
        _optional_filter(spec, on_change=on_change)
    elif isinstance(spec, (AnyObjectMatches, AnyPersonMatches)):
        _filter_chips(
            filter_=spec.filter,
            on_filter_change=lambda f: on_change(replace(spec, filter=f)),
            prefix="filter",
        )
    elif isinstance(spec, (MaxOrdinal, MinOrdinal)):
        _ordinal_chips(spec, on_change=on_change)
    else:
        assert isinstance(spec, DistinctCount)
        _table_column_chips(spec, on_change=on_change)


def derivation_builder(
    *, value: DerivationSpec | None, on_change: Callable[[DerivationSpec], None]
) -> Element:
    """A tinted box of `.tok` chips: derivation type, its column/operator/
    value chips, and a "+ code" control — never free text (the catalogue is
    closed, mvp-spec.md §8.3).

    Round-trips a `DerivationSpec` through the chip UI without loss.
    """
    spec = value if value is not None else _default_for(DerivationType.COUNT_OBJECTS)
    dtype = _derivation_type_of(spec)
    next_type = _cycle(dtype, _DERIVATION_TYPES)

    container = (
        ui.element("div")
        .classes("derivation-builder")
        .props('data-testid="derivation-builder"')
        .mark("derivation-builder")
        .style(
            "display:flex;flex-direction:column;gap:10px;padding:12px;"
            "border:1px solid var(--rule);border-radius:3px;background:var(--field-tint);"
        )
    )
    with container:
        with ui.element("div").style("display:flex;flex-wrap:wrap;gap:8px;align-items:center;"):
            _tok_chip(
                dtype.value,
                on_click=lambda: on_change(_change_type(spec, next_type)),
                testid="derivation-type-chip",
            )
            _render_type_specific(spec, on_change=on_change)
        with ui.element("div").style("display:flex;flex-direction:column;gap:2px;"):
            ui.label("Saved as").classes("lbl")
            ui.label(_expression(spec)).classes("mono").props(
                'data-testid="derivation-expression"'
            ).mark("derivation-expression").style("font-size:11.5px;color:var(--ink2);")
    return container

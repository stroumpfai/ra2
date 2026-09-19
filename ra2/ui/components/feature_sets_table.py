# STUB — signature only at M9, body owned by G3 (feat/p2-feature-components).
"""The feature-sets strip below the Features split
(design/code-feature/README.md, Screen 2 · "Feature sets table").

Declared at M9 (plan-phase-2.md §3), same reasoning as `derivation_builder.py`
— G2 places this component; G3 owns its body in Wave 4.

`sets` is typed `FeatureSetSummary` (`services/readmodels.py`), not the
`FeatureSetView` name plan-phase-2.md §3's snippet used loosely — the actual
read model this wave defines is `FeatureSetSummary`; there is no second type
to reconcile.

Built on `data_table` / `ColumnSpec` (`ra2/ui/components/data_table.py`)
exactly the way the Import view's two file tables are — a fixed-width column
per `ColumnSpec`, and one trailing `ColumnSpec(width=None)` for the filler
that absorbs the rest (the same `table-layout:fixed` trick `tests/e2e/
test_j4_layout.py` asserts for the Import cards' own flexible column).
"""

from collections.abc import Callable, Sequence
from typing import Final

from nicegui import ui
from nicegui.element import Element

from ra2.services.readmodels import FeatureSetSummary
from ra2.ui.components.data_table import ColumnSpec, data_table
from ra2.ui.components.primitives import (
    data_props,
    footnote,
    format_count,
    icon_button,
    pill,
)
from ra2.ui.state import TableState

__all__ = ["feature_sets_table"]

#: Lucide-equivalent inline paths (README, Assets), local to this file — the
#: shared `ra2/ui/components/icons.py` catalogue has no pencil/trash yet and
#: is outside this file's Wave 4 ownership (see the final report's note).
_PENCIL: Final = (
    '<path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"></path>'
)
_TRASH: Final = (
    '<path d="M3 6h18"></path>'
    '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>'
    '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>'
)


def _new_set_button(on_new_set: Callable[[], None]) -> Element:
    button = (
        ui.element("button")
        .classes("btn secondary")
        .props('type="button" data-testid="new-set-button"')
        .mark("new-set-button")
    )
    button.on("click", lambda _: on_new_set())
    with button:
        ui.label("New set")
    return button


def _set_cell(
    row: FeatureSetSummary, *, selected_id: str | None, on_select: Callable[[str], None]
) -> Element:
    is_selected = row.feature_config_id == selected_id
    button = (
        ui.element("button")
        .props(
            f'type="button" aria-pressed="{"true" if is_selected else "false"}" '
            f'data-testid="feature-set-row"'
        )
        .mark("feature-set-row")
        .style(
            "display:flex;flex-direction:column;gap:2px;text-align:left;"
            "background:none;border:none;padding:0;cursor:pointer;width:100%;color:var(--ink);"
        )
    )
    button.on("click", lambda _: on_select(row.feature_config_id))
    with button:
        weight = "600" if is_selected else "500"
        ui.label(row.name).style(f"font-size:12.5px;font-weight:{weight};")
        ui.label(f"v{row.version}").classes("mono").style("font-size:10.5px;color:var(--ink3);")
    return button


def _created_cell(row: FeatureSetSummary) -> Element:
    element = ui.element("div").style("display:flex;gap:5px;align-items:baseline;")
    with element:
        ui.label(row.created_at.strftime("%Y-%m-%d")).classes("mono").style("font-size:11.5px;")
        ui.label(row.created_at.strftime("%H:%M")).classes("mono").style(
            "font-size:11.5px;color:var(--ink3);"
        )
    return element


def _state_cell(row: FeatureSetSummary) -> Element:
    if row.is_frozen:
        count = row.locked_by_evaluations
        noun = "eval" if count == 1 else "evals"
        return pill(f"LOCKED · {count} {noun}", tone="accent")
    return ui.label("draft · never run").classes("mono").style("font-size:11px;color:var(--ink2);")


def _actions_cell(
    row: FeatureSetSummary,
    *,
    on_rename: Callable[[str, str], None],
    on_delete: Callable[[str], None],
) -> None:
    if row.is_frozen:
        # Exit criterion: a locked row's rename/delete controls are
        # **absent**, not merely disabled (README, "Feature sets table").
        return
    with ui.element("div").style("display:flex;justify-content:flex-end;gap:4px;"):
        # The set's name is analyst-typed, so it goes through the props
        # *mapping* (SD31, `data_props`). It used to be `html.escape`d into the
        # props string, which was wrong twice over: the string is parsed with
        # `ast.literal_eval`, so a set named `draft\\` closed the quoted run
        # early and the `value` prop **vanished** — the rename box pre-filled
        # empty, over a name the analyst could not see. And `html.escape` was
        # never the tool: the mapping is bound by Vue, so escaping here would
        # have rendered `A &amp; B` in the input.
        rename_input = data_props(
            ui.element("input")
            .props('type="text" data-testid="rename-input"')
            .mark("rename-input")
            .style("display:none;width:1px;height:1px;"),
            {"value": row.name, "aria-label": f"Rename {row.name}"},
        )
        rename_input.on(
            "change",
            lambda event: on_rename(row.feature_config_id, str(event.args)),
            js_handler="(e) => emit(e.target.value)",
        )

        def _reveal_rename() -> None:
            rename_input.style("display:inline-block;width:92px;height:auto;")

        icon_button(
            _PENCIL, label=f"Rename {row.name}", size=22, glyph=12, on_click=_reveal_rename
        ).mark("rename-button")
        icon_button(
            _TRASH,
            label=f"Delete {row.name}",
            size=22,
            glyph=12,
            on_click=lambda: on_delete(row.feature_config_id),
        ).mark("delete-button").style("color:var(--danger);")


def _columns(
    *,
    selected_id: str | None,
    on_select: Callable[[str], None],
    on_rename: Callable[[str, str], None],
    on_delete: Callable[[str], None],
) -> tuple[ColumnSpec[FeatureSetSummary], ...]:
    return (
        ColumnSpec(
            key="set",
            label="Set",
            width="164px",
            cell_style="padding-left:28px;",
            header_style="padding-left:28px;",
            render=lambda row: _set_cell(row, selected_id=selected_id, on_select=on_select),
        ),
        ColumnSpec(
            key="description",
            label="Description",
            width="132px",
            render=lambda row: ui.label(row.description or "").style(
                "font-size:12px;color:var(--ink2);"
            ),
        ),
        ColumnSpec(key="created", label="Created", width="126px", render=_created_cell),
        ColumnSpec(
            key="features",
            label="Features",
            width="66px",
            align="right",
            render=lambda row: ui.label(format_count(row.feature_count)).classes("mono"),
        ),
        ColumnSpec(key="state", label="State", width="138px", render=_state_cell),
        ColumnSpec(
            key="action",
            width="72px",
            align="right",
            render=lambda row: _actions_cell(row, on_rename=on_rename, on_delete=on_delete),
        ),
        # The trailing filler: no width, so `table-layout:fixed` gives it all
        # remaining space instead of opening a gap (README, "Feature sets
        # table"; the same pattern as the Import view's flexible column).
        ColumnSpec(key="filler", width=None, cell_style="padding:0;"),
    )


def feature_sets_table(
    *,
    sets: Sequence[FeatureSetSummary],
    selected_id: str | None,
    on_select: Callable[[str], None],
    on_rename: Callable[[str, str], None],
    on_delete: Callable[[str], None],
    on_new_set: Callable[[], None],
) -> Element:
    """`table-layout:fixed`, fixed-width content columns plus a trailing
    filler column that absorbs all remaining width (README, Screen 2).

    A locked row's rename/delete controls are **absent**, not merely
    disabled.
    """
    container = (
        ui.element("div")
        .classes("feature-sets-strip")
        .props('data-testid="feature-sets-strip"')
        .mark("feature-sets-strip")
        .style(
            "flex:none;margin-top:16px;border-top:1px solid var(--rule);"
            "background:var(--surface);display:flex;flex-direction:column;"
            "max-height:302px;min-height:0;"
        )
    )
    with container:
        with ui.element("div").style(
            "display:flex;align-items:center;justify-content:space-between;flex:none;"
            "height:42px;padding:0 28px;background:var(--strip-tint);"
            "border-bottom:1px solid var(--rule2);"
        ):
            ui.label("Feature sets").classes("lbl")
            _new_set_button(on_new_set)
        with ui.element("div").style("flex:1;min-height:0;overflow:auto;"):
            data_table(
                columns=_columns(
                    selected_id=selected_id,
                    on_select=on_select,
                    on_rename=on_rename,
                    on_delete=on_delete,
                ),
                rows=sets,
                state=TableState("set"),
                empty_message="No feature sets yet.",
                wide=True,
                testid="feature-sets-table",
                row_style=lambda row: (
                    "background:var(--accent-soft);" if row.feature_config_id == selected_id else ""
                ),
            )
        footnote(
            "A set locked by an evaluation cannot be renamed or deleted — its runs cite it by name."
        )
    return container

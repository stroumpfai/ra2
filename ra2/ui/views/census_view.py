"""Census view — "How populated each source column is."

`design/nav-import-census/README.md` §2, implemented: the filter toolbar
(three dropdown chips + caption + Export CSV), the census table with the
populated bar and the distribution bar, and the two summary cards.

The same three rules that shape `import_view.py` shape every line here:

1. **The UI holds no business logic** (§8.1.1). Filtering, sorting, paging,
   the bucket counts, the per-table column counts and every rate arrive from
   `CensusService`; `CensusColumnView` and `CensusSummary` are rendered, never
   recomputed. The only arithmetic below is `rate * 100`, because the design's
   readout and `bar(fill_pct=…)` are in percent while the stored number is in
   `[0, 1]` — a unit conversion of a service's number, not a derived one.
2. **No module-level mutable state** (§12.8). Sort and page live in
   `app.storage.client` through `ui/state.py`; the selected corpus and the two
   filter chips live there too, under this module's own keys; the open
   dropdown is per-render local state on a `_CensusPage` instance built inside
   the page function, one per client.
3. **The UI calls services in-process as Python** (§1). No HTTP call to this
   app's own API anywhere in this file.

Two things the design leaves open, decided here and marked at the point of
decision: the populated-rate chip's threshold list (README shows only the
"all" state), and what the view does with **no corpus at all** (README's
"Loading / empty / error" section is explicitly undesigned).
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, cast
from urllib.parse import urlencode

from nicegui import app, ui
from nicegui.element import Element

from ra2.domain.census import BUCKET_ORDER, CensusBucketLabel, ValueCount
from ra2.domain.ids import CorpusId
from ra2.services.container import Services
from ra2.services.readmodels import CensusColumnView, CensusSummary, CorpusView, Page, SortDir
from ra2.ui.components import (
    ColumnSpec,
    bar,
    card,
    chip,
    data_table,
    distribution_bar,
    format_count,
    long_tail_bar,
    pagination_row,
)
from ra2.ui.shell import NAV_ITEMS, shell
from ra2.ui.state import TableState, set_table_state, table_state

__all__ = [
    "BUCKET_LABELS",
    "CENSUS_TABLE",
    "COLUMN_PARAM",
    "CONTENT_GAP",
    "CONTENT_PADDING",
    "CORPUS_KEY",
    "CORPUS_PARAM",
    "FEATURES_PATH",
    "FILTERS_KEY",
    "NO_COLUMNS_MESSAGE",
    "NO_CORPUS_MESSAGE",
    "PAGE_SIZE",
    "POPULATED_THRESHOLDS",
    "PROFILE_TITLE",
    "REMINDER_BODY",
    "REMINDER_TITLE",
    "TOOLBAR_CAPTION",
    "CensusFilters",
    "census_filters",
    "register",
]

_ITEM = next(i for i in NAV_ITEMS if i.key == "census")

#: README §2: `main > div` is `padding:16px 28px 24px` with a 14px gap.
CONTENT_PADDING = "16px 28px 24px"
CONTENT_GAP = "14px"

#: One `TableState`, so the census table's sort and page are its own and
#: survive a filter change the same way Import's do.
CENSUS_TABLE: Final = "census.columns"

#: Which corpus this browser tab is profiling, and what the two filter chips
#: are set to. Per client, never a module global (§12.8) — the same shape as
#: `import_view.DELIVERY_KEY`.
CORPUS_KEY: Final = "ra2.census.corpus"
FILTERS_KEY: Final = "ra2.census.filters"

#: README §2b: "page size **25**, label "1–25 of 162"".
PAGE_SIZE: Final = 25
#: Sorted **descending by default** (README §2b, sw-design.md §11.3).
DEFAULT_SORT_KEY: Final = "populated_rate"
DEFAULT_SORT_DIR: Final = SortDir.DESC

#: How many corpora the picker offers. The design's chip is a single-corpus
#: selector with no paging of its own, so this bounds the one service call
#: rather than being a page the analyst can turn.
CORPUS_CHOICES: Final = 100

#: The populated-rate chip's options. **The design does not spell these out**
#: — its mock shows only the "all" state — so this is the smallest ladder that
#: answers the question the chip exists for ("which columns are viable
#: features?") without turning into a numeric entry field. `None` is "all".
POPULATED_THRESHOLDS: Final[tuple[tuple[float | None, str], ...]] = (
    (None, "all"),
    (0.25, "25 %"),
    (0.50, "50 %"),
    (0.75, "75 %"),
    (1.00, "100 %"),
)

#: The three source tables, in the design's own order. The **counts** beside
#: them are always `CensusSummary`'s, never counted here (§8.1.1).
TABLE_NAMES: Final[tuple[str, ...]] = ("unfall", "objekt", "person")

#: `FindingCode`-style stable identifiers render through one table in `ui/`;
#: so do the bucket labels. `CensusBucketLabel.P100_80` is `"100-80"` on the
#: wire and "100–80 %" (en dash) on screen.
BUCKET_LABELS: Final[dict[CensusBucketLabel, str]] = {
    CensusBucketLabel.P100_80: "100–80 %",
    CensusBucketLabel.P80_60: "80–60 %",
    CensusBucketLabel.P60_40: "60–40 %",
    CensusBucketLabel.P40_20: "40–20 %",
    CensusBucketLabel.P20_0: "20–0 %",
    CensusBucketLabel.EMPTY: "empty",
}

# --- copy, verbatim from design/nav-import-census/README.md ------------------

TOOLBAR_CAPTION: Final = "Feature selection reads this table."
EXPORT_LABEL: Final = "Export CSV"
PROFILE_TITLE: Final = "Population profile · all tables"
REMINDER_TITLE: Final = "Reminder"
#: README §2c, with the mock's own curly quotes and apostrophe. "no value
#: provided" is emphasised in the design; `ui.label` takes plain text, so the
#: emphasis is the one thing not reproduced.
REMINDER_BODY: Final = (
    "Empty means no value provided — not “not applicable”. Records with an "
    "empty cell leave that feature’s denominator entirely (§8.6)."
)
#: The action column. README §2b: a mono 11px link "use as feature" →
#: Features/FeatureConfig, or the static "in config" once some feature's
#: `source_column` names this column. Phase 1 had no Features route and
#: rendered the affordance disabled; phase 2 has one, so it is a real link.
USE_AS_FEATURE: Final = "use as feature"
IN_CONFIG: Final = "in config"

#: Where "use as feature" goes, and the two query parameters it carries.
#: `features_view` validates both against its own services before using them
#: and reads the column's table and type hint from the census itself — the URL
#: names the column, it does not describe it.
FEATURES_PATH: Final = next(i for i in NAV_ITEMS if i.key == "features").path
CORPUS_PARAM: Final = "corpus"
COLUMN_PARAM: Final = "column"

#: Undesigned states, in the tone README's "Loading / empty / error" section
#: suggests: one centred line inside the well.
NO_CORPUS_MESSAGE: Final = "No corpus yet — create one on Import."
NO_COLUMNS_MESSAGE: Final = "No columns match this filter."
NO_VALUES_LEGEND: Final = "no values"

#: The distribution bar's width, from `theme.py`'s token — the legend under it
#: is clipped to the same box (README §2b: "max-width:230px").
DIST_BAR_MAX_W: Final = "var(--dist-bar-max-w)"
#: How much of a raw value the legend shows. The mock's legend values are
#: one-character codes; a real `UnfallUid` is 32 characters of unbreakable
#: hex, which no 230px box can hold beside two more of them. The full values
#: are in the CSV export, which is what the export is for.
LEGEND_VALUE_CHARS: Final = 10

#: Two non-breaking spaces between the legend's entries, exactly as the mock
#: renders them (`2 · 62 %&nbsp;&nbsp;1 · 26 %`), so a pair never wraps.
_LEGEND_GAP: Final = "  "

# --- layout, verbatim from the design's inline styles ------------------------

TOOLBAR_STYLE: Final = "display:flex;align-items:center;gap:10px;flex-wrap:wrap;"
LEFT_GROUP_STYLE: Final = (
    "display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0;position:relative;"
)
#: `margin-left:auto` on the **group**, not a `flex:1` spacer — the spacer
#: breaks right alignment as soon as the row wraps (README §2a).
RIGHT_GROUP_STYLE: Final = "display:flex;align-items:center;gap:10px;margin-left:auto;flex:none;"
SUMMARY_ROW_STYLE: Final = "display:flex;gap:14px;"
SUMMARY_CARD_PADDING: Final = "padding:12px 14px;"

_MENU_STYLE: Final = (
    "position:absolute;top:100%;left:0;margin-top:4px;z-index:20;min-width:100%;"
    "display:flex;flex-direction:column;padding:4px 0;background:var(--surface);"
    "border:1px solid var(--rule);border-radius:3px;"
)
_MENU_ITEM_STYLE: Final = (
    "display:block;width:100%;text-align:left;background:none;border:none;"
    "padding:5px 10px;font-family:var(--mono);font-size:11px;color:var(--ink);"
    "cursor:pointer;white-space:nowrap;"
)
_MENU_ITEM_ON_STYLE: Final = "background:var(--accent-soft);font-weight:500;"


@dataclass(frozen=True, slots=True)
class CensusFilters:
    """The two filter chips, per client.

    A typed dataclass in `app.storage.client` (§8.1.2). It lives here rather
    than in `ui/state.py` because `ui/state.py` is frozen for this milestone
    and nothing outside the Census view has a census filter.
    """

    table_name: str | None = None
    min_populated_rate: float | None = None


def census_filters() -> CensusFilters:
    """This client's filter chips, created on first use."""
    filters: CensusFilters = app.storage.client.setdefault(FILTERS_KEY, CensusFilters())
    return filters


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page() -> None:
        page = _CensusPage(services)
        await page.build()


class _CensusPage:
    """One client's Census view.

    Built inside the page function, so every browser tab gets its own instance
    and nothing is shared between them (§12.8). It holds only what it last
    read from a service, plus which dropdown is open.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._corpora: tuple[CorpusView, ...] = ()
        self._corpus: CorpusView | None = None
        self._summary: CensusSummary | None = None
        self._columns: Page[CensusColumnView] | None = None
        self._open_menu: str | None = None
        self._toolbar: Element | None = None
        self._table_slot: Element | None = None
        self._cards_slot: Element | None = None

    # --- lifecycle ---------------------------------------------------------

    async def build(self) -> None:
        with shell(
            title=_ITEM.title,
            description=_ITEM.description,
            active=_ITEM.key,
            content_padding=CONTENT_PADDING,
            content_gap=CONTENT_GAP,
        ):
            root = ui.element("div").style(
                f"display:flex;flex-direction:column;gap:{CONTENT_GAP};"
                "flex:1;min-height:0;min-width:0;"
            )
            with root:
                self._toolbar = (
                    ui.element("div").props('data-testid="census-toolbar"').style(TOOLBAR_STYLE)
                )
                self._table_slot = ui.element("div").style(
                    "flex:1;min-height:0;min-width:0;display:flex;flex-direction:column;"
                )
                self._cards_slot = ui.element("div").style(SUMMARY_ROW_STYLE)
        await self.reload()

    async def reload(self) -> None:
        """Re-read everything this view shows, then redraw.

        One place reads, so no handler has to work out which half of the page
        its action invalidated — the same shape as `_ImportPage.reload`.
        """
        corpora = await self._services.corpus.list_corpora(
            sort_key="imported_at", sort_dir=SortDir.DESC, page=1, page_size=CORPUS_CHOICES
        )
        self._corpora = corpora.items
        self._corpus = self._current_corpus()
        if self._corpus is None:
            # No corpus id to ask about, so no census call is made at all.
            self._summary = None
            self._columns = None
        else:
            filters = census_filters()
            state = _state()
            self._summary = await self._services.census.summary(self._corpus.corpus_id)
            self._columns = await self._services.census.columns(
                self._corpus.corpus_id,
                table_name=filters.table_name,
                min_populated_rate=filters.min_populated_rate,
                sort_key=state.sort_key,
                sort_dir=state.sort_dir,
                page=state.page,
                page_size=state.page_size,
            )
        self._render()

    def _current_corpus(self) -> CorpusView | None:
        """The corpus the first chip names.

        Unlike Import's delivery this **is** a designed selector, so the chip
        decides it; this only supplies the default. It is the **most recently
        imported** corpus, remembered per client so a re-render cannot move
        the analyst to a different one, falling back to the newest that exists
        when the remembered one is gone (a corpus can be deleted from Import).
        """
        if not self._corpora:
            app.storage.client.pop(CORPUS_KEY, None)
            return None
        remembered = app.storage.client.get(CORPUS_KEY)
        current = next((c for c in self._corpora if c.corpus_id == remembered), None)
        if current is None:
            current = max(self._corpora, key=lambda c: (c.imported_at, c.corpus_id))
        app.storage.client[CORPUS_KEY] = current.corpus_id
        return current

    # --- rendering ---------------------------------------------------------

    def _render(self) -> None:
        # All three are built in `build()`, before anything can render.
        assert self._toolbar is not None
        assert self._table_slot is not None
        assert self._cards_slot is not None
        self._toolbar.clear()
        with self._toolbar:
            self._filter_toolbar()
        self._table_slot.clear()
        with self._table_slot:
            self._table_card()
        self._cards_slot.clear()
        with self._cards_slot:
            if self._summary is not None:
                self._profile_card(self._summary)
                self._reminder_card()

    # --- 2a. the filter toolbar --------------------------------------------

    def _filter_toolbar(self) -> None:
        with ui.element("div").style(LEFT_GROUP_STYLE):
            if self._corpus is not None:
                self._corpus_chip(self._corpus)
                self._populated_chip()
                self._table_chip()
            ui.label(TOOLBAR_CAPTION).props('data-testid="toolbar-caption"').style(
                "font-size:12px;color:var(--ink2);"
            )
        with ui.element("div").style(RIGHT_GROUP_STYLE):
            self._export_button()

    def _corpus_chip(self, current: CorpusView) -> None:
        """ "corpus 2026‑09‑02 · v1 ▼" — which corpus is being profiled."""
        self._dropdown(
            name="corpus",
            text=_corpus_chip_text(current),
            aria_label="Corpus",
            options=[
                (
                    corpus.corpus_id,
                    _corpus_chip_text(corpus),
                    corpus.corpus_id == current.corpus_id,
                )
                for corpus in self._corpora
            ],
            on_pick=self._pick_corpus,
        )

    def _populated_chip(self) -> None:
        """ "populated ≥ all ▼" — the minimum fill-rate filter."""
        chosen = census_filters().min_populated_rate
        label = next(
            (text for value, text in POPULATED_THRESHOLDS if value == chosen),
            POPULATED_THRESHOLDS[0][1],
        )
        self._dropdown(
            name="populated",
            text=f"populated ≥ {label}",
            aria_label="Minimum populated rate",
            options=[
                (_threshold_key(value), f"populated ≥ {text}", value == chosen)
                for value, text in POPULATED_THRESHOLDS
            ],
            on_pick=self._pick_threshold,
        )

    def _table_chip(self) -> None:
        """ "table · all 162 ▼" — the source-table filter.

        Every count is `CensusSummary`'s. A view that counted the rows it was
        holding would be counting one *page* (§8.1.1, §8.1.4).
        """
        summary = self._summary
        assert summary is not None  # a corpus is selected, so a summary was read
        chosen = census_filters().table_name
        counts = summary.column_counts_by_table
        options = [
            (
                "",
                f"table · all {summary.total_column_count}",
                chosen is None,
            ),
            *(
                (name, f"table · {name} {counts.get(name, 0)}", name == chosen)
                for name in TABLE_NAMES
            ),
        ]
        text = next(option_text for _, option_text, on in options if on)
        self._dropdown(
            name="table",
            text=text,
            aria_label="Source table",
            options=options,
            on_pick=self._pick_table,
        )

    def _dropdown(
        self,
        *,
        name: str,
        text: str,
        aria_label: str,
        options: Sequence[tuple[str, str, bool]],
        on_pick: Callable[[str], Awaitable[None]],
    ) -> None:
        """One dropdown chip: the `.chip` button plus, when open, its panel.

        Built from `ui.element`, not from `ui.select` / `ui.menu`: Quasar's
        carry a 40px hit target, a ripple and a type scale this design does
        not have (R2, §8.2), and the design's chip is a 4×9px `.chip` with a
        9px caret. Both the chip and every option are real `<button>`s, so the
        toolbar is keyboard-reachable and the focus ring shows.
        """
        expanded = self._open_menu == name
        with ui.element("div").style("position:relative;display:inline-flex;"):
            chip(
                text,
                label=aria_label,
                on_click=lambda: self._toggle_menu(name),
            ).props(
                f'data-chip="{name}" aria-haspopup="listbox" '
                f'aria-expanded="{"true" if expanded else "false"}"'
            ).mark("chip", f"chip-{name}")
            if not expanded:
                return
            with (
                ui.element("div")
                .props(f'role="listbox" aria-label="{aria_label}" data-testid="menu-{name}"')
                .style(_MENU_STYLE)
            ):
                for value, option_text, selected in options:
                    self._menu_item(
                        name=name,
                        value=value,
                        text=option_text,
                        selected=selected,
                        on_pick=on_pick,
                    )

    def _menu_item(
        self,
        *,
        name: str,
        value: str,
        text: str,
        selected: bool,
        on_pick: Callable[[str], Awaitable[None]],
    ) -> None:
        button = (
            ui.element("button")
            .classes("mono")
            .props(
                f'type="button" role="option" aria-selected="{"true" if selected else "false"}" '
                f'aria-label="{text}" data-testid="option-{name}"'
            )
            .mark(f"option-{name}")
            .style(_MENU_ITEM_STYLE + (_MENU_ITEM_ON_STYLE if selected else ""))
        )
        button.on("click", cast("Callable[[], None]", lambda: on_pick(value)))
        with button:
            ui.label(text)

    def _export_button(self) -> None:
        """ ".btn" secondary, README §2a. Disabled when there is no corpus to
        export — the affordance stays visible rather than disappearing, the
        same rule the pagination arrows follow."""
        button = (
            ui.element("button")
            .classes("btn secondary")
            .props('type="button" data-testid="export-csv"')
            .mark("export-csv")
        )
        if self._corpus is None:
            button.props("disabled").style("opacity:.5;cursor:default;")
        else:
            button.on("click", cast("Callable[[], None]", self._export))
        with button:
            ui.label(EXPORT_LABEL)

    # --- 2b. the census table ----------------------------------------------

    def _table_card(self) -> None:
        page = self._columns
        rows = page.items if page is not None else ()
        total = page.total if page is not None else 0
        state = _state()
        with card(flex="1", extra="min-height:0;overflow:hidden;"):
            with ui.element("div").style("flex:1;min-height:0;overflow:auto;"):
                data_table(
                    columns=_census_columns(
                        self._corpus.corpus_id if self._corpus is not None else None
                    ),
                    rows=rows,
                    state=state,
                    on_sort=_sync(self._sort),
                    row_class=_row_class,
                    row_style=_row_style,
                    empty_message=(
                        NO_COLUMNS_MESSAGE if self._corpus is not None else NO_CORPUS_MESSAGE
                    ),
                    wide=True,
                    testid="table-census",
                )
            pagination_row(
                state=state,
                total=total,
                shown=len(rows),
                on_page=_sync(self._page),
                on_page_size=_sync(self._page_size),
            )

    # --- 2c. the two summary cards ------------------------------------------

    def _profile_card(self, summary: CensusSummary) -> None:
        """The six buckets, in `BUCKET_ORDER` — the domain's display order, so
        a bucket the service happened not to return still holds its place."""
        counts = {bucket.label: bucket.column_count for bucket in summary.buckets}
        with card(flex="1", extra=SUMMARY_CARD_PADDING).props('data-card="profile"'):
            ui.label(PROFILE_TITLE).classes("lbl")
            with ui.element("div").style(
                "display:flex;gap:18px;margin-top:8px;font-size:12.5px;flex-wrap:wrap;"
            ):
                for label in BUCKET_ORDER:
                    with ui.element("div").props('data-testid="bucket"'):
                        ui.label(str(counts.get(label, 0))).classes("mono").props(
                            f'data-bucket="{label.value}"'
                        ).style("font-size:15px;font-weight:500;")
                        ui.label(BUCKET_LABELS[label]).style("color:var(--ink2);")

    def _reminder_card(self) -> None:
        with card(flex="1", extra=SUMMARY_CARD_PADDING).props('data-card="reminder"'):
            ui.label(REMINDER_TITLE).classes("lbl")
            ui.label(REMINDER_BODY).props('data-testid="reminder-body"').style(
                "color:var(--ink2);font-size:12.5px;margin-top:6px;"
            )

    # --- table state --------------------------------------------------------

    async def _sort(self, key: str) -> None:
        """`TableState.toggled` decides the next direction; this stores it and
        re-reads the page from the service — sort is a **service call**
        parameter, not something applied to rows already held (§8.1.4)."""
        set_table_state(CENSUS_TABLE, _state().toggled(key))
        self._open_menu = None
        await self.reload()

    async def _page(self, page: int) -> None:
        current = _state()
        set_table_state(
            CENSUS_TABLE, TableState(current.sort_key, current.sort_dir, page, current.page_size)
        )
        await self.reload()

    async def _page_size(self, size: int) -> None:
        current = _state()
        set_table_state(CENSUS_TABLE, TableState(current.sort_key, current.sort_dir, 1, size))
        await self.reload()

    # --- filter actions -----------------------------------------------------

    async def _pick_corpus(self, corpus_id: str) -> None:
        app.storage.client[CORPUS_KEY] = corpus_id
        await self._refilter()

    async def _pick_threshold(self, key: str) -> None:
        app.storage.client[FILTERS_KEY] = CensusFilters(
            table_name=census_filters().table_name,
            min_populated_rate=None if key == "" else float(key),
        )
        await self._refilter()

    async def _pick_table(self, table_name: str) -> None:
        app.storage.client[FILTERS_KEY] = CensusFilters(
            table_name=table_name or None,
            min_populated_rate=census_filters().min_populated_rate,
        )
        await self._refilter()

    async def _refilter(self) -> None:
        """ "Changing any of them refilters and **resets to page 1**" (README,
        Interactions; sw-design.md §11.3). The reset is a new `TableState`,
        which is what the next service call carries — the service is told the
        page, it never remembers one."""
        current = _state()
        set_table_state(
            CENSUS_TABLE, TableState(current.sort_key, current.sort_dir, 1, current.page_size)
        )
        self._open_menu = None
        await self.reload()

    def _toggle_menu(self, name: str) -> None:
        self._open_menu = None if self._open_menu == name else name
        self._render()

    # --- export -------------------------------------------------------------

    async def _export(self) -> None:
        """ "Export CSV exports the currently filtered, currently sorted
        table" (README, Interactions). Both come out of the same state the
        table itself was drawn from, so the file can never disagree with the
        screen; the bytes — BOM, delimiter, comment line — are the service's
        (sw-design.md §7)."""
        if self._corpus is None:
            return
        filters = census_filters()
        state = _state()
        data = await self._services.export.census_csv(
            self._corpus.corpus_id,
            table_name=filters.table_name,
            min_populated_rate=filters.min_populated_rate,
            sort_key=state.sort_key,
            sort_dir=state.sort_dir,
        )
        ui.download.content(data, _export_filename(self._corpus), media_type="text/csv")


# --- columns ------------------------------------------------------------------


def _census_columns(corpus_id: CorpusId | None) -> tuple[ColumnSpec[CensusColumnView], ...]:
    """The seven columns of README §2b, widths verbatim.

    `corpus_id` reaches the action column only: "use as feature" links to
    Features **for this corpus**, and a cell renderer is handed one row, never
    the page it came from.
    """
    return (
        ColumnSpec(
            key="column_name",
            label="Column",
            width="230px",
            sortable=True,
            cell_class="mono",
            render=_render_column_name,
        ),
        ColumnSpec(
            key="table_name",
            label="Table",
            width="78px",
            sortable=True,
            cell_class="mono",
            render=lambda row: (
                ui.label(row.table_name)
                .props('data-testid="census-table-name"')
                .mark("census-table-name")
                .style("font-size:11.5px;color:var(--ink2);")
            ),
        ),
        ColumnSpec(
            key="type_hint",
            label="Type hint",
            width="96px",
            sortable=True,
            cell_class="mono",
            # `str(...)`, not `.value`: `TypeHint` maps to `String(16)`
            # (`models.type_annotation_map`), so a `CensusColumnView` loaded
            # back out of SQLite carries the plain string even though the read
            # model annotates it as the enum. `export_service` writes it the
            # same way. A `StrEnum` and its value stringify identically, so
            # this renders "enum" either way.
            render=lambda row: ui.label(str(row.type_hint)).style("color:var(--ink2);"),
        ),
        ColumnSpec(
            key="populated_rate",
            label="Populated",
            width="180px",
            sortable=True,
            render=_render_populated,
        ),
        ColumnSpec(
            key="distinct_count",
            label="Distinct",
            width="78px",
            sortable=True,
            cell_class="mono",
            render=lambda row: ui.label(format_count(row.distinct_count)),
        ),
        ColumnSpec(
            key="distribution",
            label="Value distribution",
            width="286px",
            render=_render_distribution,
        ),
        ColumnSpec(
            key="action",
            width="135px",
            render=lambda row: _render_action(row, corpus_id),
        ),
    )


# --- cell renderers -----------------------------------------------------------


def _render_column_name(column: CensusColumnView) -> None:
    """The column name, at weight 500 when the column is already configured
    (README §2b). `in_config` is real from phase 2 on: it is `True` once some
    feature's `source_column` names this column (`census_service`), which is
    what the "use as feature" link creates."""
    ui.label(column.column_name).props('data-testid="census-column-name"').mark(
        "census-column-name"
    ).style("font-weight:500;" if column.in_config else "")


def _render_populated(column: CensusColumnView) -> None:
    """The `.bar` plus the two-line readout: percentage over the absolute
    populated count (README §2b — the mock's "99.4 % / 4 948" is 4 948 of
    4 978 records).

    `populated_rate` is stored in `[0, 1]` and both the bar and the readout
    are in percent, so the `* 100` here is a unit conversion of the service's
    number. Nothing divides.
    """
    with ui.element("div").style("display:flex;align-items:center;gap:9px;"):
        bar(fill_pct=column.populated_rate * 100)
        with ui.element("div"):
            ui.label(_percent(column.populated_rate)).classes("mono").props(
                'data-testid="populated-pct"'
            ).mark("populated-pct").style("font-size:11.5px;")
            ui.label(format_count(column.populated_count)).classes("mono").style(
                "font-size:10.5px;color:var(--ink3);margin-top:1px;"
            )


def _render_distribution(column: CensusColumnView) -> None:
    """The stacked bar and its legend, or the long-tail rendering.

    `long_tail` is a **stored** boolean (SD8, sw-design.md §7) — the view
    renders the rule's answer, it does not re-evaluate the rule.

    The wrapper clips at the design's 230px bar width. The mock's legend
    values are one-character codes; a real one can be a 32-character UID, and
    an unbreakable token that long escapes `.distbar`'s `max-width` and runs
    across the action column. `_legend` shortens it and this stops whatever it
    could not.
    """
    with ui.element("div").style(f"max-width:{DIST_BAR_MAX_W};overflow:hidden;"):
        if column.long_tail:
            long_tail_bar(
                legend=f"long tail · {format_count(column.distinct_count)} distinct, "
                "no value over 1 %"
            )
            return
        top = column.top_values
        distribution_bar(
            # Top 4 as segments; the remainder is the `--rule2` track showing
            # through, which is what the design's stacked bar does (sw-design.md
            # §7: "top 4 shown as stacked-bar segments plus a remainder").
            segments=tuple(value.share * 100 for value in top[:4]),
            legend=_legend(top[:3]),
        )


def _render_action(column: CensusColumnView, corpus_id: CorpusId | None) -> None:
    """ "use as feature" as a real link, or the static "in config".

    A plain `<a href>` — the design's own element (README §2b: "mono 11px link
    ... → Features/FeatureConfig") and the whole hand-off: no click handler, no
    shared cross-view state, and the URL is something the analyst can keep.
    `features_view` validates the two parameters against its own services
    before prefilling anything.

    An already-configured column renders the static text instead, as drawn —
    the reverse cross-link ("which feature reads this column?") is a separate
    question the design does not answer.

    `corpus_id` is `None` only when no corpus is selected, and then the table
    holds no rows for this renderer to be called on.
    """
    if column.in_config:
        ui.label(IN_CONFIG).classes("mono ink3").props('data-testid="in-config"').mark(
            "in-config"
        ).style("font-size:11px;")
        return
    assert corpus_id is not None
    query = urlencode({CORPUS_PARAM: corpus_id, COLUMN_PARAM: column.column_name})
    link = ui.link(target=f"{FEATURES_PATH}?{query}")
    link.classes(remove="nicegui-link", add="mono")
    link.props('data-testid="use-as-feature"').mark("use-as-feature")
    # Inline rather than a global `a` rule, because `theme.py` is frozen for
    # this milestone; the colour and the 11px are the design's either way.
    link.style("font-size:11px;color:var(--accent);text-decoration:none;")
    with link:
        ui.label(USE_AS_FEATURE)


def _row_class(column: CensusColumnView) -> str:
    """A stable hook on the tinted row, so "already-in-config rows are
    highlighted" is selectable rather than only visible."""
    return "in-config" if column.in_config else ""


def _row_style(column: CensusColumnView) -> str:
    """README §2b: already-in-config rows are `background:--accent-soft`.

    Inline rather than a `.in-config` rule because `theme.py` is frozen for
    this milestone; the token is the design's either way.
    """
    return "background:var(--accent-soft);" if column.in_config else ""


# --- plumbing -----------------------------------------------------------------


def _state() -> TableState:
    """This client's census `TableState`, Populated ▼ on first use."""
    return table_state(
        CENSUS_TABLE,
        sort_key=DEFAULT_SORT_KEY,
        sort_dir=DEFAULT_SORT_DIR,
        page_size=PAGE_SIZE,
    )


def _percent(rate: float) -> str:
    """The design's "100 %", "99.4 %", "81.3 %", "79.0 %".

    One decimal everywhere except a full 100 %, which the mock writes without
    one. Presentation only — the rate itself is the service's.
    """
    pct = rate * 100
    if pct >= 100:
        return "100 %"
    return f"{pct:.1f} %"


def _legend(top: Sequence[ValueCount]) -> str:
    """The legend under the stacked bar: the top three values, as the
    design renders them (README §2b).

    A column with nothing in it has no top values at all, which the mock
    never shows — it says so rather than drawing an empty legend.
    """
    entries = [f"{_short(value.value_raw)} · {value.share * 100:.0f} %" for value in top]
    return _LEGEND_GAP.join(entries) if entries else NO_VALUES_LEGEND


def _short(value: str) -> str:
    """A raw value, cut to what the 230px legend can hold (see
    `LEGEND_VALUE_CHARS`). Presentation only: the value itself is the
    census's, and the export writes it whole."""
    if len(value) <= LEGEND_VALUE_CHARS:
        return value
    return value[:LEGEND_VALUE_CHARS] + "…"


def _corpus_chip_text(corpus: CorpusView) -> str:
    """The design's "corpus 2026‑09‑02 · v1"."""
    return f"corpus {corpus.name} · v{corpus.version}"


def _threshold_key(value: float | None) -> str:
    """The dropdown carries its value as text, so "all" is the empty string
    and every threshold round-trips through `float()`."""
    return "" if value is None else str(value)


def _export_filename(corpus: CorpusView) -> str:
    """`<corpus name>-census.csv`, with anything that is not a plain filename
    character replaced — a corpus is named from the delivery, and a delivery
    is named from a directory on someone's machine."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in corpus.name)
    return f"{safe or 'corpus'}-census.csv"


def _sync[**P](action: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    """Adapt an async handler to the component kit's synchronous callback type.

    NiceGUI's `handle_event` awaits an awaitable result inside the sender's
    slot context, so this is a typing formality and not a change of behaviour.
    """
    return cast("Callable[P, None]", action)

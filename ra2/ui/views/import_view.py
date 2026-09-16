"""Import view — "One delivery becomes one immutable corpus."

`design/nav-import-census/README.md` §1, implemented: two side-by-side file
cards that **never wrap or stack at any width**, the corpora table below them,
and a create-corpus button whose record count comes from the service.

Three rules shape every line of this module:

1. **The UI holds no business logic** (§8.1.1). Selection, freeze, delete,
   re-parse, sort, page and every count are service calls; `DeliveryView`,
   `DeliveryFileView`, `CorpusView` and `CorpusSummary` arrive as detached read
   models and are rendered, never recomputed.
2. **No module-level mutable state** (§12.8). Sort and page live in
   `app.storage.client` through `ui/state.py`; the current delivery id lives
   there too; everything else is per-render local state on a `_ImportPage`
   instance built inside the page function, one per client.
3. **The UI calls services in-process as Python** (§1). There is no HTTP call
   to this app's own API anywhere in this file.

The two-column grid is `minmax(0,1fr) minmax(0,1fr)`, which is what lets the
columns shrink below their content width instead of wrapping. J4 asserts it at
1024 / 1440 / 1920 px.
"""

from collections.abc import Awaitable, Callable, Sequence
from io import BytesIO
from pathlib import Path
from typing import Final, cast

from nicegui import app, ui
from nicegui.element import Element
from nicegui.events import MultiUploadEventArguments

from ra2.domain.delivery import DeliveryStatus, FileKind, SourceKind
from ra2.domain.findings import Finding
from ra2.domain.ids import CorpusId, DeliveryId, FileId
from ra2.services.container import Services
from ra2.services.errors import BlockingFindingsError, ServiceError
from ra2.services.readmodels import CorpusView, DeliveryFileView, DeliveryView, Page, SortDir
from ra2.ui.components import (
    ColumnSpec,
    add_button,
    card,
    card_header,
    data_table,
    dialog_card,
    footnote,
    format_count,
    icon_button,
    pagination_row,
    tick,
)
from ra2.ui.components.icons import CLIPBOARD, REFRESH, TRASH
from ra2.ui.shell import NAV_ITEMS, shell
from ra2.ui.state import TableState, set_table_state, table_state
from ra2.ui.views.file_report_modal import open_file_report

__all__ = [
    "ACTION_WIDTH",
    "CONTENT_GAP",
    "CONTENT_PADDING",
    "CORPORA_CAPTION",
    "CORPORA_TABLE",
    "GRID_STYLE",
    "STRUCTURED_NOTE",
    "STRUCTURED_TABLE",
    "TEXT_NOTE",
    "TEXT_TABLE",
    "register",
]

_ITEM = next(i for i in NAV_ITEMS if i.key == "import")

#: README §1: `main > div` is `padding:20px 28px` with a 16px gap.
CONTENT_PADDING = "20px 28px"
CONTENT_GAP = "16px"

#: A CSS grid, **not** flex wrapping. `minmax(0,1fr)` is required so the two
#: columns can shrink below their content width — they must never stack.
GRID_STYLE = (
    "display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start;"
)

#: One `TableState` per table, so the two file tables' sort state is
#: independent (README, Interactions) and the corpora table has its own page.
STRUCTURED_TABLE: Final = "import.structured"
TEXT_TABLE: Final = "import.text"
CORPORA_TABLE: Final = "import.corpora"

#: Which delivery this browser tab is looking at. Per client, never a module
#: global (§12.8).
DELIVERY_KEY: Final = "ra2.import.delivery"

#: README §1a.2 — 10 rows plus the header row, so both cards are the same
#: height regardless of how many rows they hold.
WELL_HEIGHT_PX: Final = 404

#: The action column, widened from the design's 46px by P3-D22: three 22px
#: buttons, two 4px gaps and the design's own 14px right padding. The File
#: column absorbs it, which is what it is the flexible one for (README §1a).
ACTION_WIDTH: Final = "92px"
PAGE_SIZE: Final = 10

# --- copy, verbatim from design/nav-import-census/README.md ------------------

STRUCTURED_TITLE: Final = "Structured sets"
TEXT_TITLE: Final = "Text file"
CORPORA_TITLE: Final = "Corpora"

STRUCTURED_NOTE: Final = (
    "Deselected files stay in the list and are excluded from the corpus. "
    "The report icon opens that file's parse findings; re-parse after changing "
    "its encoding or delimiter."
)
#: README §1a.4 renders `UnfallUid` in mono inside this sentence. `footnote()`
#: takes plain text, so the mono span is the one thing not reproduced here.
TEXT_NOTE: Final = (
    "A UnfallUid collision attaches the wrong narrative — uniqueness is checked "
    "across the whole delivery."
)
CORPORA_CAPTION: Final = (
    "A corpus is immutable. Once a run has touched it, it cannot be deleted — "
    "the runs that cite it would stop being reproducible."
)

#: Undesigned states, in the tone README's "Loading / empty / error" section
#: suggests: one centred line inside the fixed-height well.
NO_DELIVERY_MESSAGE: Final = "No delivery yet — use + to register one."
NO_FILES_MESSAGE: Final = "No files."
NO_CORPORA_MESSAGE: Final = "No corpora yet."


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page() -> None:
        page = _ImportPage(services)
        await page.build()

    @ui.page("/")
    def _root() -> None:
        """Import is the landing view."""
        ui.navigate.to(_ITEM.path)


class _ImportPage:
    """One client's Import view.

    Built inside the page function, so every browser tab gets its own instance
    and nothing is shared between them (§12.8). It holds only what it last
    read from a service; it is never the source of truth for any of it.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._delivery: DeliveryView | None = None
        self._structured: Page[DeliveryFileView] | None = None
        self._text: Page[DeliveryFileView] | None = None
        self._corpora: Page[CorpusView] | None = None
        self._corpus_total = 0
        self._corpus_locked = 0
        self._corpus_busy = False
        self._deleting_corpus_id: CorpusId | None = None
        #: The file whose delete is one click from happening (P3-D22's inline
        #: two-step) and the file a row action is currently running for. Both
        #: are per-instance, so one row going busy leaves every other row
        #: interactive — the same shape `_deleting_corpus_id` has.
        self._confirming_file_id: FileId | None = None
        self._busy_file_id: FileId | None = None
        self._root: Element | None = None
        self._grid: Element | None = None
        self._corpora_slot: Element | None = None
        self._poll: ui.timer | None = None

    # --- lifecycle ---------------------------------------------------------

    async def build(self) -> None:
        with shell(
            title=_ITEM.title,
            description=_ITEM.description,
            active=_ITEM.key,
            data_dir=self._services.lifecycle.data_dir().data_dir,
            content_padding=CONTENT_PADDING,
            content_gap=CONTENT_GAP,
        ):
            self._root = ui.element("div").style(
                f"display:flex;flex-direction:column;gap:{CONTENT_GAP};min-width:0;"
            )
            with self._root:
                self._grid = ui.element("div").props('data-testid="file-grid"').style(GRID_STYLE)
                self._corpora_slot = ui.element("div").style("min-width:0;")
        await self.reload()

    async def reload(self) -> None:
        """Re-read everything this view shows, then redraw.

        One place reads, so no handler has to work out which half of the page
        its action invalidated.

        The body runs in **`_root`'s** context, not in the context of whatever
        fired it. `table_state` and `_current_delivery` both read
        `app.storage.client`, which NiceGUI resolves through the slot stack —
        and an event handler's slot belongs to the element that fired it, an
        element this method's own `_render()` is entitled to destroy. Two
        events in flight at once is all it takes: the first one's redraw
        deletes the second one's button, and the second one then raises "The
        parent element this slot belongs to has been deleted" from whichever
        storage read it happened to reach first. A manual-testing report
        caught it on a double-clicked "Delete" — the corpus was deleted
        correctly both times, and the crash came afterwards, out of the
        orphaned handler. `_root` is built once in `build()` and never
        cleared (only `_grid` and `_corpora_slot` are), so it outlives every
        redraw and every button in it.
        """
        assert self._root is not None  # built in `build()`, before any reload
        # Any action at all disarms a pending delete: sorting, paging, a
        # selection toggle or a corpus action all land here, and a "Sure?"
        # left armed behind an unrelated click is a trap (P3-D22).
        self._confirming_file_id = None
        with self._root:
            self._delivery = await self._current_delivery()
            if self._delivery is not None:
                delivery_id = self._delivery.delivery_id
                structured_state = table_state(
                    STRUCTURED_TABLE, sort_key="filename", page_size=PAGE_SIZE
                )
                text_state = table_state(TEXT_TABLE, sort_key="filename", page_size=PAGE_SIZE)
                self._structured = await self._services.delivery.files(
                    delivery_id,
                    exclude_kinds={FileKind.TEXT},
                    sort_key=structured_state.sort_key,
                    sort_dir=structured_state.sort_dir,
                    page=structured_state.page,
                    page_size=structured_state.page_size,
                )
                self._text = await self._services.delivery.files(
                    delivery_id,
                    kinds={FileKind.TEXT},
                    sort_key=text_state.sort_key,
                    sort_dir=text_state.sort_dir,
                    page=text_state.page,
                    page_size=text_state.page_size,
                )
            else:
                self._structured = None
                self._text = None
            state = table_state(CORPORA_TABLE, sort_key="imported_at", page_size=PAGE_SIZE)
            self._corpora = await self._services.corpus.list_corpora(
                sort_key="imported_at",
                sort_dir=SortDir.DESC,
                page=state.page,
                page_size=state.page_size,
            )
            summary = await self._services.corpus.summary()
            self._corpus_total, self._corpus_locked = summary.total, summary.locked
            self._render()

    async def _current_delivery(self) -> DeliveryView | None:
        """The delivery the two file cards show.

        The design shows exactly one delivery and has no switcher, and nothing
        upstream defines "the current" one. This picks the **most recently
        registered** delivery, remembering it per client so a re-render cannot
        silently move the analyst to a different one; if that delivery is gone,
        it falls back to the newest that exists.
        """
        deliveries = await self._services.delivery.list_deliveries()
        if not deliveries:
            app.storage.client.pop(DELIVERY_KEY, None)
            return None
        remembered = app.storage.client.get(DELIVERY_KEY)
        current = next((d for d in deliveries if d.delivery_id == remembered), None)
        if current is None:
            current = max(deliveries, key=lambda d: (d.created_at, d.delivery_id))
        app.storage.client[DELIVERY_KEY] = current.delivery_id
        return current

    # --- rendering ---------------------------------------------------------

    def _render(self) -> None:
        # Both are built in `build()`, before anything can render.
        assert self._grid is not None
        assert self._corpora_slot is not None
        self._grid.clear()
        with self._grid:
            self._file_card(
                title=STRUCTURED_TITLE,
                name=STRUCTURED_TABLE,
                page=self._structured,
                all_files=self._files(text=False),
                note=STRUCTURED_NOTE,
                note_tone="muted",
                count_class="ink2",
                add_label="Add set",
                testid="structured",
            )
            self._file_card(
                title=TEXT_TITLE,
                name=TEXT_TABLE,
                page=self._text,
                all_files=self._files(text=True),
                note=TEXT_NOTE,
                note_tone="info",
                count_class="accent",
                add_label="Add file",
                testid="text",
            )
        self._corpora_slot.clear()
        with self._corpora_slot:
            self._corpora_card()

    def _files(self, *, text: bool) -> tuple[DeliveryFileView, ...]:
        """Every file of the relevant kind, unpaged — used only for the
        selection count and the select-all/indeterminate state, which are
        properties of the **whole table**, not of the page on screen. The
        rows actually rendered come from `self._structured` / `self._text`,
        fetched sorted and paged by `DeliveryService.files` (§8.1/§8.4)."""
        if self._delivery is None:
            return ()
        return tuple(f for f in self._delivery.files if (f.file_kind is FileKind.TEXT) == text)

    def _file_card(
        self,
        *,
        title: str,
        name: str,
        page: Page[DeliveryFileView] | None,
        all_files: Sequence[DeliveryFileView],
        note: str,
        note_tone: str,
        count_class: str,
        add_label: str,
        testid: str,
    ) -> None:
        state = table_state(name, sort_key="filename", page_size=PAGE_SIZE)
        rows = page.items if page is not None else ()
        total = page.total if page is not None else 0
        selected = sum(1 for f in all_files if f.selected)

        with card().props(f'data-card="{testid}"'):
            with card_header(
                title=title, count=_files_count(total, selected), count_class=count_class
            ):
                add_button(label=add_label, on_click=_sync(self._open_intake))
            with (
                ui.element("div")
                .props(f'data-testid="well-{testid}"')
                .style(f"height:{WELL_HEIGHT_PX}px;overflow:auto;flex:none;")
            ):
                data_table(
                    columns=self._file_columns(files=all_files, selected=selected),
                    rows=rows,
                    state=state,
                    on_sort=_sync(lambda key: self._sort(name, key)),
                    empty_message=NO_FILES_MESSAGE if self._delivery else NO_DELIVERY_MESSAGE,
                    testid=f"table-{testid}",
                )
            pagination_row(
                state=state,
                total=total,
                shown=len(rows),
                on_page=_sync(lambda page_num: self._file_page(name, page_num)),
                on_page_size=_sync(lambda size: self._file_page_size(name, size)),
            )
            footnote(note, tone=note_tone)

    def _file_columns(
        self, *, files: Sequence[DeliveryFileView], selected: int
    ) -> tuple[ColumnSpec[DeliveryFileView], ...]:
        """The five columns of README §1a, widths verbatim."""
        all_selected = bool(files) and selected == len(files)
        return (
            ColumnSpec(
                key="selection",
                width="30px",
                header_style="padding-right:0;",
                cell_style="padding-right:0;",
                header_render=lambda: tick(
                    checked=all_selected,
                    indeterminate=0 < selected < len(files),
                    label="Select all",
                    on_change=_sync(lambda: self._select_all(files, selected=not all_selected)),
                ),
                render=lambda row: tick(
                    checked=row.selected,
                    label=f"Select {row.filename}",
                    on_change=_sync(lambda: self._toggle(row)),
                ),
            ),
            ColumnSpec(key="filename", label="File", sortable=True, render=_render_filename),
            ColumnSpec(
                key="row_count",
                label="Rows",
                width="52px",
                align="right",
                sortable=True,
                cell_class="mono",
                render=lambda row: ui.label(format_count(row.row_count or 0)),
            ),
            ColumnSpec(
                key="state",
                label="State",
                width="86px",
                sortable=True,
                render=_render_state,
            ),
            ColumnSpec(
                key="action",
                width=ACTION_WIDTH,
                align="right",
                cell_style="padding-right:14px;",
                render=self._render_row_actions,
            ),
        )

    def _render_row_actions(self, row: DeliveryFileView) -> None:
        """Report, re-parse and delete, in the row itself (P3-D22).

        Three 22x22 buttons at README §1a's own row-icon metrics. The cell has
        exactly three states and renders one of them:

        *busy* — a spinner while `reparse_file` or `remove_file` is in flight,
        keyed by file id so only this row loses its controls;
        *confirming* — "Sure?" and a cancel, **instead of** the three buttons.
        A delete is unrecoverable for an upload delivery, where `remove_file`
        deletes the stored bytes, and a 22px glyph is a small target to hang
        that on. It takes the whole cell rather than only the trash's place
        because three buttons plus "Sure?" do not fit 92px, and because a row
        that is one click from losing a file should not also be offering to
        re-parse it;
        *idle* — the three buttons.
        """
        with ui.element("div").style(
            "display:inline-flex;align-items:center;justify-content:flex-end;gap:4px;"
        ):
            if self._busy_file_id == row.file_id:
                ui.spinner(size="13px", color="var(--ink3)").props(
                    'data-testid="row-action-busy"'
                ).mark("row-action-busy")
                return
            if self._confirming_file_id == row.file_id:
                self._confirm_delete_cell(row)
                return
            icon_button(
                CLIPBOARD,
                label=f"Report for {row.filename}",
                size=22,
                glyph=13,
                stroke=1.9,
                on_click=_sync(lambda: self._open_report(row)),
            )
            icon_button(
                REFRESH,
                label=f"Re-parse {row.filename}",
                size=22,
                glyph=13,
                stroke=1.9,
                on_click=_sync(lambda: self._reparse_file(row)),
            )
            icon_button(
                TRASH,
                label=f"Delete {row.filename}",
                size=22,
                glyph=13,
                stroke=1.9,
                extra_class="danger-hover",
                on_click=lambda: self._confirm_delete(row),
            )

    def _confirm_delete_cell(self, row: DeliveryFileView) -> None:
        """The armed row: "Sure?" and a cancel.

        Both are mono text rather than icons — the corpora table's own delete
        idiom, and the design's vocabulary already carries text glyphs for
        sort arrows and pagination chevrons. The cancel is what keeps the
        two-step escapable without clicking something unrelated.
        """
        confirm = (
            ui.element("button")
            .classes("mono danger")
            .props(
                f'type="button" aria-label="Confirm delete {row.filename}" '
                f'data-testid="confirm-delete-file"'
            )
            .mark("confirm-delete-file")
            .style(
                "font-size:11px;background:none;border:none;padding:0;"
                "cursor:pointer;color:var(--danger);"
            )
        )
        confirm.on("click", lambda _: self._delete_file(row))
        with confirm:
            ui.label("Sure?")

        cancel = (
            ui.element("button")
            .classes("mono ink3")
            .props(
                f'type="button" aria-label="Cancel delete {row.filename}" '
                f'data-testid="cancel-delete-file"'
            )
            .mark("cancel-delete-file")
            .style(
                "font-size:12px;background:none;border:none;padding:0 2px;"
                "cursor:pointer;color:var(--ink3);line-height:1;"
            )
        )
        cancel.on("click", lambda _: self._cancel_delete())
        with cancel:
            ui.label("✕")

    def _corpora_card(self) -> None:
        page = self._corpora
        items = page.items if page is not None else ()
        total = page.total if page is not None else 0
        state = table_state(CORPORA_TABLE, sort_key="imported_at", page_size=PAGE_SIZE)

        with card():
            with card_header(
                title=CORPORA_TITLE,
                count=f"{self._corpus_total} imported · {self._corpus_locked} "
                f"locked by an evaluation",
                count_class="ink2",
            ):
                self._create_corpus_button()
            ui.label(CORPORA_CAPTION).props('data-testid="corpora-caption"').style(
                "padding:9px 14px;border-bottom:1px solid var(--rule2);"
                "font-size:11.5px;color:var(--ink2);"
            )
            with ui.element("div").style("overflow-x:auto;"):
                data_table(
                    columns=self._corpus_columns(),
                    rows=items,
                    state=state,
                    empty_message=NO_CORPORA_MESSAGE,
                    wide=True,
                    testid="table-corpora",
                )
            pagination_row(
                state=state,
                total=total,
                shown=len(items),
                on_page=_sync(self._corpora_page),
                on_page_size=_sync(self._corpora_page_size),
            )

    def _create_corpus_button(self) -> None:
        """ "Create corpus · N records" — the record count is the service's.

        `DeliveryView.selected_record_count` sums the `unfall` rows of the
        selected files; a view function that summed them itself would be the
        derived count §8.1.1 bans.
        """
        records = self._delivery.selected_record_count if self._delivery else 0
        button = (
            ui.element("button")
            .classes("btn primary")
            .props('type="button" data-testid="create-corpus"')
            .mark("create-corpus")
        )
        if self._corpus_busy:
            button.props("disabled").style("opacity:.5;cursor:default;")
            with button:
                ui.spinner(size="14px", color="white")
                ui.label("Creating…").mark("create-corpus-label")
            return
        if self._delivery is None or self._delivery.status is not DeliveryStatus.ANALYSED:
            button.props("disabled").style("opacity:.5;cursor:default;")
        else:
            button.on("click", cast("Callable[[], None]", self._create_corpus))
        with button:
            ui.label(f"Create corpus · {format_count(records)} records").mark("create-corpus-label")

    def _corpus_columns(self) -> tuple[ColumnSpec[CorpusView], ...]:
        """README §1b's eight columns, widths verbatim.

        Not sortable: the design shows no sort affordance on this table, and
        the service's default — newest first — is the order it renders.
        """
        return (
            ColumnSpec(key="corpus", label="Corpus", width="150px", render=_render_corpus_name),
            ColumnSpec(
                key="description",
                label="Description",
                render=lambda row: ui.label(row.description or "").style(
                    "font-size:12px;color:var(--ink2);"
                ),
            ),
            ColumnSpec(
                key="created",
                label="Created",
                width="118px",
                cell_class="mono",
                render=lambda row: ui.label(row.imported_at.strftime("%Y-%m-%d %H:%M")).style(
                    "font-size:11.5px;"
                ),
            ),
            ColumnSpec(
                key="records",
                label="Records",
                width="84px",
                align="right",
                cell_class="mono",
                render=lambda row: (
                    ui.label(format_count(row.record_count))
                    .props('data-testid="corpus-records"')
                    .mark("corpus-records")
                ),
            ),
            ColumnSpec(
                key="languages",
                label="Language composition",
                render=_render_languages,
            ),
            ColumnSpec(
                key="canary",
                label="Canary",
                width="78px",
                align="right",
                cell_class="mono",
                render=_render_canary,
            ),
            ColumnSpec(key="status", label="Status", width="184px", render=_render_status),
            ColumnSpec(
                key="action",
                width="104px",
                align="right",
                render=lambda row: self._render_delete(row),
            ),
        )

    def _render_delete(self, row: CorpusView) -> None:
        """ "Delete" only when no evaluation cites the corpus; otherwise a
        non-interactive "delete blocked" (README §1b, J3)."""
        if row.is_locked:
            ui.label("delete blocked").classes("mono ink3").props(
                'data-testid="delete-blocked"'
            ).mark("delete-blocked").style("font-size:11px;")
            return
        if self._deleting_corpus_id == row.corpus_id:
            with (
                ui.element("div")
                .style("display:inline-flex;align-items:center;gap:5px;")
                .props('data-testid="delete-corpus-busy"')
            ):
                ui.spinner(size="12px", color="var(--danger)")
                ui.label("Deleting…").classes("mono danger").style("font-size:11px;")
            return
        button = (
            ui.element("button")
            .classes("mono danger")
            .props(f'type="button" aria-label="Delete {row.name}" data-testid="delete-corpus"')
            .mark("delete-corpus")
            .style(
                "font-size:11px;background:none;border:none;padding:0;cursor:pointer;"
                "color:var(--danger);"
            )
        )
        button.on("click", cast("Callable[[], None]", lambda: self._delete_corpus(row.corpus_id)))
        with button:
            ui.label("Delete")

    # --- table state -------------------------------------------------------

    async def _sort(self, name: str, key: str) -> None:
        """`TableState.toggled` decides the next direction; this stores it and
        re-reads the table's page from the service — sort is a **service
        call** parameter, not something this view applies to rows it already
        holds (§8.1.4). Independent per table, because each table has its own
        named state (README, Interactions)."""
        set_table_state(name, table_state(name, sort_key="filename").toggled(key))
        await self.reload()

    @staticmethod
    def _turn(name: str, *, page: int | None = None, page_size: int | None = None) -> None:
        """Store this table's new page or page size. The page resets to 1 when
        the page size changes, because "1–10 of 25" on page 3 of a 10-row page
        size is a different row range at 25."""
        current = table_state(name, sort_key="filename", page_size=PAGE_SIZE)
        if page_size is not None:
            set_table_state(name, TableState(current.sort_key, current.sort_dir, 1, page_size))
            return
        set_table_state(
            name,
            TableState(current.sort_key, current.sort_dir, page or current.page, current.page_size),
        )

    async def _file_page(self, name: str, page: int) -> None:
        """The file table's page is a **service call** with the new page
        number, not a slice of a list this view is holding (§8.1.4)."""
        self._turn(name, page=page)
        await self.reload()

    async def _file_page_size(self, name: str, size: int) -> None:
        self._turn(name, page_size=size)
        await self.reload()

    async def _corpora_page(self, page: int) -> None:
        """The corpora page is a **service call** with the new page number, not
        a slice of a list this view is holding (§8.1.4)."""
        self._turn(CORPORA_TABLE, page=page)
        await self.reload()

    async def _corpora_page_size(self, size: int) -> None:
        self._turn(CORPORA_TABLE, page_size=size)
        await self.reload()

    # --- actions -----------------------------------------------------------

    async def _toggle(self, file: DeliveryFileView) -> None:
        """Per-file selection. The service returns the whole delivery so the
        header count and the "Create corpus · N records" label both recompute
        from one call (README, Interactions).

        Reloads rather than just re-rendering: the table's own rows come from
        `self._structured` / `self._text`, fetched separately by
        `DeliveryService.files` (§8.1.4), and would otherwise still show this
        file's pre-toggle `selected` value.
        """
        if self._delivery is None:
            return
        self._delivery = await self._services.delivery.set_selected(
            self._delivery.delivery_id, file.file_id, selected=not file.selected
        )
        await self.reload()

    async def _select_all(self, files: Sequence[DeliveryFileView], *, selected: bool) -> None:
        """The header tick: select all / none for **that table only**."""
        if self._delivery is None:
            return
        for file in files:
            if file.selected != selected:
                self._delivery = await self._services.delivery.set_selected(
                    self._delivery.delivery_id, file.file_id, selected=selected
                )
        await self.reload()

    async def _reparse_file(self, file: DeliveryFileView) -> None:
        """The row's re-parse: re-run analysis for this file with the settings
        that are effective now.

        Every override argument is left `None`, which `reparse_file` documents
        as "keep what is effective now" — so this is a re-run, never a change.
        Changing an encoding or a delimiter is still the report modal's job,
        because that is where the selectors are.

        `_render()` rather than `reload()` flips the row busy before the slow
        `await`: `_render()` touches no service and no `app.storage.client`, so
        it carries none of the slot-lifetime hazard `reload()`'s own docstring
        describes. The row's new counts and state are the feedback; nothing
        follows the final `reload()`, which has already deleted this handler's
        button.
        """
        if self._delivery is None:
            return
        self._confirming_file_id = None
        self._busy_file_id = file.file_id
        self._render()
        try:
            await self._services.delivery.reparse_file(self._delivery.delivery_id, file.file_id)
        except ServiceError as exc:
            self._busy_file_id = None
            self._render()
            ui.notify(str(exc), type="negative")
            return
        self._busy_file_id = None
        await self.reload()

    def _confirm_delete(self, file: DeliveryFileView) -> None:
        """First click of the two-step: arm this row and disarm any other.

        Synchronous and `_render()`-only — nothing has happened yet, so there
        is nothing to re-read.
        """
        self._confirming_file_id = file.file_id
        self._render()

    def _cancel_delete(self) -> None:
        """Back out of the two-step without touching anything."""
        self._confirming_file_id = None
        self._render()

    async def _delete_file(self, file: DeliveryFileView) -> None:
        """Second click: drop the file from the delivery.

        For an upload delivery this deletes the stored bytes; for a host-path
        delivery `remove_file` leaves the analyst's own file where it is and
        only drops the row. Either way the delivery's selection, its header
        count and "Create corpus · N records" all change, so this ends in a
        full `reload()` rather than a `_render()`.
        """
        if self._delivery is None:
            return
        self._confirming_file_id = None
        self._busy_file_id = file.file_id
        self._render()
        try:
            await self._services.delivery.remove_file(self._delivery.delivery_id, file.file_id)
        except ServiceError as exc:
            self._busy_file_id = None
            self._render()
            ui.notify(str(exc), type="negative")
            return
        self._busy_file_id = None
        await self.reload()

    async def _open_report(self, file: DeliveryFileView) -> None:
        if self._delivery is None:
            return
        self._confirming_file_id = None
        assert self._root is not None
        await open_file_report(
            services=self._services,
            delivery=self._delivery,
            file_id=file.file_id,
            host=self._root,
            on_changed=self.reload,
        )

    async def _create_corpus(self) -> None:
        """Freeze the selection. On a blocking failure **nothing was written**
        and the findings go back to the analyst naming the offending key.

        The button gives no feedback of its own between click and redraw —
        `freeze()` can take a moment, and with nothing to show for it an
        analyst could reasonably click again. `_corpus_busy` flips the button
        to disabled + a spinner *before* the slow `await`, via a plain
        `_render()` (not `reload()`): `_render()` touches no service or
        `app.storage.client`, so it carries none of the slot-lifetime hazard
        `reload()`'s own docstring describes for a redraw mid-handler.
        """
        if self._delivery is None:
            return
        self._corpus_busy = True
        self._render()
        try:
            await self._services.corpus.freeze(self._delivery.delivery_id, name=self._delivery.name)
        except BlockingFindingsError as exc:
            self._corpus_busy = False
            self._render()
            assert self._root is not None
            _show_blocking(exc.findings, host=self._root)
            return
        except ServiceError as exc:
            self._corpus_busy = False
            self._render()
            ui.notify(str(exc), type="negative")
            return
        # `reload()` redraws the corpora card, which deletes the button that
        # fired this handler — so nothing follows it, and in particular no
        # toast, which would have no slot left to resolve. The new row in the
        # table is the feedback.
        self._corpus_busy = False
        await self.reload()

    async def _delete_corpus(self, corpus_id: CorpusId) -> None:
        """Mirrors `_create_corpus`'s busy handling, keyed by corpus id so
        only the clicked row goes busy — other rows stay interactive."""
        self._deleting_corpus_id = corpus_id
        self._render()
        try:
            await self._services.corpus.delete(corpus_id)
        except ServiceError as exc:
            self._deleting_corpus_id = None
            self._render()
            ui.notify(str(exc), type="negative")
            return
        self._deleting_corpus_id = None
        await self.reload()

    # --- intake (sw-design.md §6.1) ----------------------------------------

    async def _open_intake(self) -> None:
        """Both intake paths behind the design's one `+` button.

        The design has no registration control at all — it starts from a
        delivery that already exists — so this is the smallest surface that
        makes §6.1's two paths reachable: name a directory on this machine, or
        upload files. Nothing downstream knows which was used.

        The dialog is shown by setting `dialog.value = True` after it is
        built — see `file_report_modal._FileReport.show` for why this file
        never writes NiceGUI's equivalent one-liner.
        """
        assert self._root is not None
        with (
            # Built inside `_root`, which the view never clears: this dialog's
            # own button redraws the card its `+` lives in, and a dialog
            # parented there would be destroyed mid-handler.
            self._root,
            ui.dialog().props('data-testid="intake"') as dialog,
            dialog_card(extra="width:560px;max-height:88vh;overflow:auto;"),
        ):
            with ui.element("div").style("padding:14px;"):
                ui.label("Add files").classes("lbl")
                ui.label(
                    "Register a directory on this machine, or upload files. A host "
                    "directory is registered in place and never copied."
                ).style("font-size:12.5px;color:var(--ink2);margin-top:6px;")
            with ui.element("div").style("padding:0 14px 14px;"):
                ui.label("Host directory").classes("lbl")
                # A native `<input>`, like the component kit's page-size
                # selector: Quasar's own carries a 40px hit target and a type
                # scale this design does not have (R2, §8.2).
                typed = {"path": ""}
                entry = (
                    ui.element("input")
                    .classes("chip")
                    .props(
                        'type="text" placeholder="/path/to/delivery" '
                        'aria-label="Host directory" data-testid="host-path"'
                    )
                    .mark("host-path")
                    .style("width:100%;")
                )
                # `js_handler` emits the value itself. `args=[["target",
                # "value"]]` looks equivalent and is not: it asks the client
                # for the *event's* `target`, a DOM node that never survives
                # serialisation, and the handler then raises `KeyError`.
                entry.on(
                    "input",
                    lambda event: typed.update(path=str(event.args)),
                    js_handler="(e) => emit(e.target.value)",
                )
                register = (
                    ui.element("button")
                    .classes("btn primary")
                    .props('type="button" data-testid="register-delivery"')
                    .mark("register-delivery")
                    .style("margin-top:8px;")
                )
                register.on(
                    "click",
                    cast(
                        "Callable[[], None]",
                        lambda: self._register_host_path(typed["path"], dialog),
                    ),
                )
                with register:
                    ui.label("Register delivery")
            with ui.element("div").style("padding:0 14px 14px;"):
                ui.label("Upload").classes("lbl")
                ui.upload(
                    multiple=True,
                    on_multi_upload=cast(
                        "Callable[[MultiUploadEventArguments], None]",
                        lambda event: self._upload(event, dialog),
                    ),
                ).props('data-testid="upload"').style("width:100%;")
        dialog.value = True

    async def _register_host_path(self, path: str, dialog: ui.dialog) -> None:
        if not path.strip():
            ui.notify("Name a directory to register.", type="warning")
            return
        root = Path(path.strip())
        try:
            delivery_id = await self._services.delivery.register(
                root.name or path.strip(),
                source_kind=SourceKind.HOST_PATH,
                root_path=root,
            )
        except (ServiceError, OSError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        dialog.close()
        app.storage.client[DELIVERY_KEY] = delivery_id
        await self._analyse(delivery_id)

    async def _upload(self, event: MultiUploadEventArguments, dialog: ui.dialog) -> None:
        """Upload intake (§6.1). Files land on the same `FileStore` seam as a
        host directory, and nothing downstream knows which was used.

        NiceGUI hands the upload over as a `FileUpload`, so the bytes are read
        here and handed to the service as a binary stream; the store is what
        bounds them by `RA2_MAX_UPLOAD_MB`.
        """
        delivery = self._delivery
        delivery_id = (
            delivery.delivery_id
            if delivery is not None and delivery.source_kind is SourceKind.UPLOAD
            else await self._services.delivery.register("upload", source_kind=SourceKind.UPLOAD)
        )
        try:
            for upload in event.files:
                await self._services.delivery.add_file(
                    delivery_id, upload.name, BytesIO(await upload.read())
                )
        except (ServiceError, OSError) as exc:
            ui.notify(str(exc), type="negative")
            return
        dialog.close()
        app.storage.client[DELIVERY_KEY] = delivery_id
        await self._analyse(delivery_id)

    async def _analyse(self, delivery_id: DeliveryId) -> None:
        """Analyse the delivery, then keep redrawing until it settles.

        `TaskRunner` returns immediately — and returns *before* the work it
        scheduled has even started, so "still `registered`" and "`analysing`"
        are the same thing to a caller. The view therefore polls until the
        delivery's own status is **terminal**, and polls the status rather than
        the task table because the status is a service read model and
        `TaskProgress` is an `infra` type the layer rule keeps out of `ui/`.

        Polling always starts here, unconditionally — a manual-testing report
        found that adding a file to an **already-analysed** delivery could
        leave a freshly-uploaded file stuck showing its pre-analysis category
        (a text file rendered as structured) until a manual page reload. The
        cause: this method's own `reload()` races the background task this
        same call just scheduled — for a *fresh* delivery `status` starts at
        `REGISTERED`, so `_settled` is safely `False` regardless of who wins
        that race, but for a delivery analysed once already, `status` can
        still read its **old** terminal value (`ANALYSED`) if `reload()` beats
        `work()`'s first line (which sets `ANALYSING`) to the database —
        making `_settled` true by mistake and skipping `_start_polling()`
        right when a second round of analysis is what is actually running.
        `_start_polling()`'s own timer already checks `_settled` on every
        tick and stops itself the moment it is genuinely true, so starting it
        unconditionally costs at most one harmless extra poll when nothing
        was racing in the first place.
        """
        await self._services.delivery.analyse(delivery_id)
        await self.reload()
        self._start_polling()

    @property
    def _settled(self) -> bool:
        return self._delivery is None or self._delivery.status in (
            DeliveryStatus.ANALYSED,
            DeliveryStatus.FAILED,
        )

    def _start_polling(self) -> None:
        if self._poll is not None or self._root is None:
            return

        async def poll() -> None:
            await self.reload()
            if self._settled and self._poll is not None:
                self._poll.deactivate()
                self._poll = None

        with self._root:
            self._poll = ui.timer(0.2, poll)


# --- cell renderers ----------------------------------------------------------


def _state(file: DeliveryFileView) -> tuple[str, str]:
    """The State column's text and its colour class (README §1a).

    "ok" in `--ok`, "N rejected" in `--danger`, "N recovered" in `--warn`. Two
    states the design's fixtures never showed but the pipeline produces: a file
    that has not been analysed yet, and one that failed outright — undecodable
    bytes or a header matching no table. Rejected outranks recovered: a
    rejected row is data that did not make it in.
    """
    if file.analysed_at is None:
        return "not analysed", "ink3"
    if file.header_ok is False or file.file_kind is FileKind.UNKNOWN:
        return "failed", "danger"
    if file.rejected_count:
        return f"{format_count(file.rejected_count)} rejected", "danger"
    if file.recovered_count:
        return f"{format_count(file.recovered_count)} recovered", "warn"
    return "ok", "ok"


def _render_state(file: DeliveryFileView) -> None:
    text, tone = _state(file)
    ui.label(text).classes(tone).props('data-testid="file-state"').mark("file-state").style(
        "font-size:12.5px;"
    )


def _render_filename(file: DeliveryFileView) -> None:
    """The only column allowed to truncate (README §1a)."""
    with ui.element("div").style("display:flex;align-items:center;overflow:hidden;"):
        ui.label(file.filename).classes("mono").props('data-testid="filename"').mark(
            "filename"
        ).style("font-size:11.5px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;")


def _render_corpus_name(corpus: CorpusView) -> None:
    with ui.element("div").style("display:flex;align-items:baseline;gap:6px;min-width:0;"):
        ui.label(corpus.name).classes("mono").props('data-testid="corpus-name"').mark(
            "corpus-name"
        ).style("font-weight:500;overflow:hidden;text-overflow:ellipsis;")
        ui.label(f"v{corpus.version}").classes("mono ink3").style("font-size:11px;")


def _render_languages(corpus: CorpusView) -> None:
    """The design's "de 2 812 · fr 1 402 · it 396"; a dev-sized corpus gets the
    `--warn` "· dev-sized" suffix (README §1b, mvp-spec.md §9)."""
    composition = " · ".join(
        f"{language} {format_count(count)}" for language, count in corpus.language_counts.items()
    )
    with ui.element("div").style("display:flex;align-items:baseline;gap:6px;min-width:0;"):
        ui.label(composition or "—").classes("mono").props('data-testid="corpus-languages"').mark(
            "corpus-languages"
        ).style("font-size:11.5px;")
        if corpus.is_dev_sized:
            ui.label("· dev-sized").classes("mono warn").props('data-testid="dev-sized"').style(
                "font-size:11.5px;"
            )


def _render_canary(corpus: CorpusView) -> None:
    """0 in `--danger`, non-zero in `--warn` (README §1b, mvp-spec.md §4.4)."""
    tone = "danger" if corpus.cp1252_canary_count == 0 else "warn"
    ui.label(format_count(corpus.cp1252_canary_count)).classes(f"mono {tone}").props(
        'data-testid="corpus-canary"'
    ).mark("corpus-canary")


def _render_status(corpus: CorpusView) -> None:
    if corpus.is_locked:
        plural = "" if corpus.locked_by_evaluations == 1 else "s"
        ui.label(f"LOCKED · {corpus.locked_by_evaluations} eval{plural}").classes("pill").props(
            'data-testid="locked-pill"'
        ).mark("locked-pill")
        return
    ui.label("Not used by any evaluation").classes("ink2").style("font-size:12px;")


# --- error surfaces ----------------------------------------------------------


def _show_blocking(findings: Sequence[Finding], *, host: Element) -> None:
    """The blocking-freeze surface (J2).

    Undesigned — README's "Loading / empty / error" section covers parse
    errors only, and a refused freeze is neither a row state nor a toast: it
    is a list the analyst has to read and act on. So it is a dialog, showing
    each finding's **code** and its **key**, because "the error names the key"
    is the assertion J2 makes.
    """
    with (
        # See `_open_intake` for why the dialog is parented to `host`.
        host,
        ui.dialog().props('data-testid="blocking"') as dialog,
        dialog_card(extra="width:640px;max-height:88vh;overflow:auto;"),
    ):
        with ui.element("div").style("padding:14px;"):
            ui.label("Corpus not created").props('data-testid="blocking-title"').mark(
                "blocking-title"
            ).style("font-size:13px;font-weight:600;")
            ui.label(
                "Nothing was written. Resolve these, or deselect the files they "
                "come from, and create the corpus again."
            ).style("font-size:12.5px;color:var(--ink2);margin-top:4px;")
        with ui.element("div").style("padding:0 14px 14px;"):
            for finding in findings:
                with (
                    ui.element("div")
                    .props('data-testid="blocking-finding"')
                    .style("padding:8px 0;border-top:1px solid var(--rule2);")
                ):
                    with ui.element("div").style("display:flex;gap:8px;align-items:baseline;"):
                        ui.label(finding.code.value).classes("mono").style(
                            "font-size:11px;color:var(--ink2);"
                        )
                        if finding.key:
                            ui.label(finding.key).classes("mono").props(
                                'data-testid="blocking-key"'
                            ).mark("blocking-key").style(
                                "font-size:11px;word-break:break-all;white-space:normal;"
                            )
                    detail = " · ".join(
                        f"{key}={finding.detail[key]}" for key in sorted(finding.detail)
                    )
                    if detail:
                        ui.label(detail).classes("mono").style(
                            "font-size:10.5px;color:var(--ink3);white-space:normal;"
                        )
        with ui.element("div").style("padding:0 14px 14px;"):
            close = (
                ui.element("button")
                .classes("btn secondary")
                .props('type="button" data-testid="blocking-close"')
                .mark("blocking-close")
            )
            close.on("click", lambda _: dialog.close())
            with close:
                ui.label("Close")
    dialog.value = True


# --- plumbing ----------------------------------------------------------------


def _files_count(total: int, selected: int) -> str:
    """The design's "9 files · 9 selected" (README §1a.1)."""
    noun = "file" if total == 1 else "files"
    return f"{total} {noun} · {selected} selected"


def _sync[**P](action: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    """Adapt an async handler to the component kit's synchronous callback type.

    NiceGUI's `handle_event` awaits an awaitable result inside the sender's
    slot context, so this is a typing formality and not a change of behaviour —
    which is why it casts rather than spawning its own task.
    """
    return cast("Callable[P, None]", action)

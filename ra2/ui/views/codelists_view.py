"""Codelists view — "Code → label tables the prompt reads."

`design/code-feature/README.md` Screen 1, implemented: the toolbar (corpus,
prompt language and status chips plus the danger chip), the grouped master
list (missing / partial / ok), and the edit zone's read-only codes table with
its two footers, the prompt-preview and the reminder card.

The same three rules that shape `census_view.py` shape every line here:

1. **The UI holds no business logic** (§8.1.1). Every status, every label,
   every count and every percentage on this page is a `ColumnMappingView` /
   `ColumnCoverage` / `CodeUsage` field. `compute_coverage` decides missing
   vs. partial vs. ok; this file only decides which heading to draw it under.
   The only arithmetic below is `pct * 100`, because `bar(fill_pct=…)` and the
   design's readouts are in percent while `coverage_pct`/`share` are stored in
   `[0, 1]` — a unit conversion of a service's number, not a derived one.
2. **No module-level mutable state** (§12.8). The three filter chips and the
   selected column live in `app.storage.client` under this module's own key;
   what the view last read from a service lives on a `_CodelistsPage` built
   inside the page function, one per client.
3. **The UI calls services in-process as Python** (§1). No HTTP call to this
   app's own API anywhere in this file, and nothing imported from `ra2.api`.

Five of `CodelistService`'s six methods are called from here. The sixth,
`coverage()`, takes an `AsyncSession` — a `ui/` module that called it would be
holding a session, which §12.7 forbids outright — so coverage reaches this
view the way it is meant to, inside `ColumnMappingView.coverage`.

**Where the design is not the whole answer**, decided here and marked at the
point of decision:

- the master list is **not paged** in the design, so the group counts, the
  status chip's counts and the "N of M shown" footer are `len()` over the
  *complete* list `list_columns()` returned — never over a page (the mistake
  §8.1.1 actually names). The status chip likewise filters that complete
  list by the status the service already assigned each row; `CodelistService`
  has no status parameter to push it into.
- **"used by"** reads `used_by_features` verbatim — nothing here computes it
  (that would be exactly the business logic §12.7 forbids). It started out
  permanently empty (C5, plan-phase-2.md §2); `CodelistService.list_columns`
  now populates it for real (a code review found the stub had never been
  turned on), so a row reads "unused" only when no feature actually names
  this column, and the copy naming a feature reflects that live state.
- **"Add label"** is drawn disabled. mvp-spec.md §7 is explicit that no UI
  path writes `code_value`; the design draws the affordance, so it renders
  inert with a title saying what to do instead, exactly as Census draws
  "use as feature".
- **Loading / empty / error** are undesigned (README, "Interactions &
  Behavior"). Empty states are one centred line, in the tone that section
  suggests; a refused import is a **dialog** listing every structural error,
  the same surface `import_view._show_blocking` gives a refused freeze —
  a list the analyst has to read and act on is not a toast.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final, cast

from nicegui import app, ui
from nicegui.element import Element
from nicegui.events import MultiUploadEventArguments

from ra2.domain.codelist_coverage import CodeUsage, ColumnCoverage, CoverageStatus
from ra2.domain.codes import CodeImportError
from ra2.domain.ids import CodeAttributeId, CorpusId
from ra2.domain.language import Language
from ra2.services.container import Services
from ra2.services.errors import CodelistImportError, ServiceError
from ra2.services.readmodels import CodeAttributeView, ColumnMappingView, CorpusView, SortDir
from ra2.ui.components import bar, card, format_count
from ra2.ui.components.icons import ALERT_TRIANGLE, DOWNLOAD, INFO, svg
from ra2.ui.components.primitives import field_select, master_detail_split, pill
from ra2.ui.shell import item_for_key, shell

__all__ = [
    "ADD_LABEL",
    "CONTENT_GAP",
    "CONTENT_PADDING",
    "CORPUS_KEY",
    "EDIT_ZONE_LABEL",
    "FULLY_LABELLED_PILL",
    "GROUP_ORDER",
    "IMPORT_FAILED_TITLE",
    "IMPORT_LABEL",
    "NEUTRAL_FOOTER",
    "NOT_MAPPED_OPTION",
    "NO_CODELIST_MESSAGE",
    "NO_CODES_PILL",
    "NO_COLUMNS_MESSAGE",
    "NO_CORPUS_MESSAGE",
    "NO_SELECTION_MESSAGE",
    "PROMPT_LANGUAGES",
    "PROMPT_PREVIEW_TITLE",
    "REMINDER_BODY",
    "REMINDER_TITLE",
    "SORTED_BY_STATUS",
    "STATE_KEY",
    "STATUS_LABELS",
    "UNUSED",
    "CodelistsState",
    "codelists_state",
    "danger_footer_text",
    "group_label",
    "percent",
    "prompt_preview",
    "register",
]

_ITEM = item_for_key("codelists")

#: The split fills the content column, so the shell's own padding would be a
#: second frame around it: README's toolbar is `11px 28px` and the panes carry
#: their own padding.
CONTENT_PADDING = "0"
CONTENT_GAP = "0"

#: Per client, never a module global (§12.8) — the same shape as
#: `census_view.CORPUS_KEY` / `FILTERS_KEY`.
CORPUS_KEY: Final = "ra2.codelists.corpus"
STATE_KEY: Final = "ra2.codelists.state"

#: How many corpora the picker offers, bounding the one service call. The
#: design's chip is a single-corpus selector with no paging of its own.
CORPUS_CHOICES: Final = 100

#: mvp-spec.md §7: labels exist per `de`/`fr`/`it`, and the prompt uses the
#: configured one. `Language` carries four more values, none of which a code
#: table is ever authored in.
PROMPT_LANGUAGES: Final[tuple[str, ...]] = (Language.DE.value, Language.FR.value, Language.IT.value)

#: The design's group order, top to bottom — this *is* "Sorted by status".
GROUP_ORDER: Final[tuple[CoverageStatus, ...]] = (
    CoverageStatus.MISSING,
    CoverageStatus.PARTIAL,
    CoverageStatus.OK,
)

#: `CoverageStatus` values are stable identifiers; the words are a rendering
#: table in `ui/`, exactly like `census_view.BUCKET_LABELS`.
STATUS_LABELS: Final[dict[CoverageStatus, str]] = {
    CoverageStatus.MISSING: "missing — blocks any feature using it",
    CoverageStatus.PARTIAL: "partial — codes with no label",
    CoverageStatus.OK: "ok — fully labelled",
}

#: How many `code = label` lines the prompt preview shows before the ellipsis
#: (README: "the first three code = label lines").
PREVIEW_LINES: Final = 3

#: README: "`9` and `0` (unknown / not collected) rendered in `--ink3`".
_UNKNOWN_CODES: Final[frozenset[str]] = frozenset({"9", "0"})
_UNKNOWN_CODE_STYLE: Final = "color:var(--ink3);"

# --- copy, verbatim from design/code-feature/README.md ------------------------

IMPORT_LABEL: Final = "Import Codes as JSON"
EDIT_ZONE_LABEL: Final = "Codelist"
SORTED_BY_STATUS: Final = "Sorted by status"
NO_CODES_PILL: Final = "no codes"
FULLY_LABELLED_PILL: Final = "100 %"
LABELS_LABEL: Final = "Labels"
JSON_KEY_LABEL: Final = "JSON key"
UNUSED: Final = "unused"
USED_BY: Final = "used by"
ADD_LABEL: Final = "Add label"
#: The design names the one feature reading the column; kept generic here
#: since a column can legitimately be `used_by_features` of more than one.
NEUTRAL_FOOTER: Final = (
    "Read-only. Labels come from the imported JSON — to change one, import a "
    "corrected file. Any change gives every feature using it a new "
    "fingerprint, so runs before and after it are not comparable."
)
PROMPT_PREVIEW_TITLE: Final = "Prompt preview · what the model is shown"
REMINDER_TITLE: Final = "Reminder"
REMINDER_BODY: Final = (
    "A label is prompt text, not a display string. All stored languages travel "
    "with the codelist; only the configured prompt language is sent (§7)."
)

CODE_HEADER: Final = "Code"
USAGE_HEADER: Final = "Usage"

#: The dropdown's own first entry. The design lists only attribute keys; a
#: mis-mapped column has to be correctable, and this is the one place the
#: correction belongs (it is `CodelistService.unmap_column`, not a delete).
NOT_MAPPED_OPTION: Final = "— not mapped —"

#: Undesigned states (README, "Loading / empty / error"): one centred line.
NO_CORPUS_MESSAGE: Final = "No corpus yet — create one on Import."
NO_COLUMNS_MESSAGE: Final = "No enum columns match this filter."
NO_SELECTION_MESSAGE: Final = "Select a column to see its codes."
NO_CODELIST_MESSAGE: Final = (
    "No codes yet. Import a codelist JSON, then map this column to one of its keys."
)
IMPORT_FAILED_TITLE: Final = "Codelist not imported"
IMPORT_FAILED_BODY: Final = (
    "Nothing was written. Fix the file and import it again — an import "
    "succeeds whole or not at all."
)

# --- layout, verbatim from the design's inline styles -------------------------

TOOLBAR_STYLE: Final = (
    "flex:none;display:flex;align-items:center;gap:10px;flex-wrap:wrap;"
    "padding:11px 28px;background:var(--surface);border-bottom:1px solid var(--rule);"
)
LEFT_GROUP_STYLE: Final = (
    "display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0;position:relative;"
)
LIST_HEADER_STYLE: Final = (
    "flex:none;height:var(--card-header-h);padding:0 16px;overflow:hidden;"
    "display:flex;align-items:center;justify-content:space-between;gap:10px;"
    "border-bottom:1px solid var(--rule);"
)
LIST_BODY_STYLE: Final = "flex:1;min-height:0;overflow:auto;"
LIST_FOOTER_STYLE: Final = (
    "flex:none;padding:9px 16px;border-top:1px solid var(--rule);"
    "display:flex;align-items:center;justify-content:space-between;gap:10px;"
)
ROW_STYLE: Final = (
    "padding:9px 16px;border-bottom:1px solid var(--rule2);display:flex;"
    "justify-content:space-between;align-items:center;gap:10px;width:100%;"
    "background:none;border-left:0;border-right:0;border-top:0;text-align:left;cursor:pointer;"
)
ROW_SELECTED_STYLE: Final = (
    "background:var(--accent-soft);border-left:2px solid var(--accent);padding-left:14px;"
)
ROW_DANGER_STYLE: Final = "background:var(--danger-soft);"
EDIT_HEADER_STYLE: Final = "display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;"
#: README: "**must be** `flex:1 1 auto; min-width:0; flex-wrap:wrap;
#: justify-content:flex-end`, or it pushes past the pane's right gutter".
EDIT_HEADER_RIGHT_STYLE: Final = (
    "flex:1 1 auto;min-width:0;display:flex;flex-wrap:wrap;align-items:center;gap:8px;"
    "justify-content:flex-end;"
)
#: README: the JSON-key dropdown is `max-width:210px`. `field_select` is a
#: `.rof`, which is `width:100%` by contract, so the clamp is on its box.
JSON_KEY_BOX_STYLE: Final = "max-width:210px;min-width:0;position:relative;flex:none;"
CARDS_ROW_STYLE: Final = "display:flex;gap:14px;flex-wrap:wrap;margin-top:14px;"
#: `.fld`: plain text that **wraps** rather than truncating (README's codes
#: table) — the label column is the one cell allowed to be two lines tall.
FLD_STYLE: Final = "font-size:12.5px;line-height:1.4;text-wrap:pretty;white-space:normal;"
EMPTY_STYLE: Final = "padding:24px 16px;text-align:center;font-size:12.5px;color:var(--ink2);"

_MENU_STYLE: Final = (
    "position:absolute;top:100%;left:0;margin-top:4px;z-index:20;min-width:100%;"
    "display:flex;flex-direction:column;padding:4px 0;background:var(--surface);"
    "border:1px solid var(--rule);border-radius:3px;max-height:280px;overflow:auto;"
)
_MENU_ITEM_STYLE: Final = (
    "display:block;width:100%;text-align:left;background:none;border:none;"
    "padding:5px 10px;font-family:var(--mono);font-size:11px;color:var(--ink);"
    "cursor:pointer;white-space:nowrap;"
)
_MENU_ITEM_ON_STYLE: Final = "background:var(--accent-soft);font-weight:500;"
_FOOTER_BASE_STYLE: Final = (
    "flex:none;padding:10px 14px;font-size:11.5px;display:flex;gap:7px;align-items:flex-start;"
)


@dataclass(frozen=True, slots=True)
class CodelistsState:
    """The three filter chips and the selected row, per client.

    A typed dataclass in `app.storage.client` (§8.1.2). It lives here rather
    than in `ui/state.py` because `ui/state.py` is frozen for this milestone
    and nothing outside the Codelists view has a codelist filter — the same
    reasoning `census_view.CensusFilters` is written under.

    The corpus is *not* here: it is the one piece of state Census keeps under
    its own key too, so both views' pickers behave identically.
    """

    language: str = Language.DE.value
    #: `None` is the design's "status · all".
    status: CoverageStatus | None = None
    #: The column name loaded in the edit zone, or `None` for "first shown".
    selected: str | None = None


def codelists_state() -> CodelistsState:
    """This client's chips and selection, created on first use."""
    state: CodelistsState = app.storage.client.setdefault(STATE_KEY, CodelistsState())
    return state


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page() -> None:
        page = _CodelistsPage(services)
        await page.build()


class _CodelistsPage:
    """One client's Codelists view.

    Built inside the page function, so every browser tab gets its own instance
    and nothing is shared between them (§12.8). It holds only what it last
    read from a service, plus which dropdown is open.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._corpora: tuple[CorpusView, ...] = ()
        self._corpus: CorpusView | None = None
        self._columns: tuple[ColumnMappingView, ...] = ()
        self._attributes: tuple[CodeAttributeView, ...] = ()
        #: The name of the file this client last imported, if it did. No read
        #: model carries `code_table_import.source_file`, so the design's
        #: "in codes-vum-2026-09.json" is shown when it is *known* and the
        #: line reads without it otherwise. Never guessed.
        self._import_file: str | None = None
        self._open_menu: str | None = None
        #: The file picker, kept so re-opening replaces it rather than
        #: stacking a second one inside `_root` (see `_open_import`).
        self._import_dialog: ui.dialog | None = None
        self._root: Element | None = None
        self._toolbar: Element | None = None
        self._list_slot: Element | None = None
        self._detail_slot: Element | None = None

    # --- lifecycle ---------------------------------------------------------

    async def build(self) -> None:
        with shell(
            title=_ITEM.title,
            description=_ITEM.description,
            active=_ITEM.key,
            content_padding=CONTENT_PADDING,
            content_gap=CONTENT_GAP,
        ):
            self._root = ui.element("div").style(
                "display:flex;flex-direction:column;flex:1;min-height:0;min-width:0;"
            )
            with self._root:
                self._toolbar = (
                    ui.element("div").props('data-testid="codelists-toolbar"').style(TOOLBAR_STYLE)
                )
                list_pane, detail_pane = master_detail_split()
                self._list_slot = list_pane
                self._detail_slot = detail_pane
        await self.reload()

    async def reload(self) -> None:
        """Re-read everything this view shows, then redraw.

        One place reads, so no handler has to work out which half of the page
        its action invalidated — the same shape as `_CensusPage.reload`.
        """
        corpora = await self._services.corpus.list_corpora(
            sort_key="imported_at", sort_dir=SortDir.DESC, page=1, page_size=CORPUS_CHOICES
        )
        self._corpora = corpora.items
        self._corpus = self._current_corpus()
        self._attributes = tuple(await self._services.codelist.list_attributes())
        if self._corpus is None:
            # No corpus id to ask about, so no codelist call is made at all.
            self._columns = ()
        else:
            self._columns = tuple(
                await self._services.codelist.list_columns(
                    self._corpus.corpus_id, language=codelists_state().language
                )
            )
        self._render()

    def _current_corpus(self) -> CorpusView | None:
        """The corpus the first chip names — the most recently imported one,
        remembered per client, falling back to the newest that still exists
        (a corpus can be deleted from Import). Identical to Census's rule, so
        the two views never disagree about "the" corpus."""
        if not self._corpora:
            app.storage.client.pop(CORPUS_KEY, None)
            return None
        remembered = app.storage.client.get(CORPUS_KEY)
        current = next((c for c in self._corpora if c.corpus_id == remembered), None)
        if current is None:
            current = max(self._corpora, key=lambda c: (c.imported_at, c.corpus_id))
        app.storage.client[CORPUS_KEY] = current.corpus_id
        return current

    # --- the rows this render is working from ------------------------------

    def _shown(self) -> tuple[ColumnMappingView, ...]:
        """The rows the status chip leaves visible.

        A display filter over rows the service already classified — the status
        on each row is `compute_coverage`'s, never re-derived here, and this is
        the complete list rather than a page (see the module docstring).
        """
        chosen = codelists_state().status
        if chosen is None:
            return self._columns
        return tuple(c for c in self._columns if _status_of(c) is chosen)

    def _of_status(self, status: CoverageStatus) -> tuple[ColumnMappingView, ...]:
        """Every column the service classified `status`, over the complete
        list — the number the chip and the group heading both show."""
        return tuple(c for c in self._columns if _status_of(c) is status)

    def _selected(self) -> ColumnMappingView | None:
        """The row loaded in the edit zone: the remembered one while it is
        still visible, otherwise the first row shown (the design's board opens
        with a row selected, never with an empty edit zone)."""
        shown = self._shown()
        if not shown:
            return None
        remembered = codelists_state().selected
        return next((c for c in shown if c.column_name == remembered), shown[0])

    # --- rendering ---------------------------------------------------------

    def _render(self) -> None:
        # All three are built in `build()`, before anything can render.
        assert self._toolbar is not None
        assert self._list_slot is not None
        assert self._detail_slot is not None
        self._toolbar.clear()
        with self._toolbar:
            self._filter_toolbar()
        self._list_slot.clear()
        with self._list_slot:
            self._master_list()
        self._detail_slot.clear()
        with self._detail_slot:
            self._edit_zone()

    # --- the toolbar -------------------------------------------------------

    def _filter_toolbar(self) -> None:
        with ui.element("div").style(LEFT_GROUP_STYLE):
            if self._corpus is not None:
                self._corpus_chip(self._corpus)
                self._language_chip()
                self._status_chip()
                self._blocking_chip()
            else:
                ui.label(NO_CORPUS_MESSAGE).props('data-testid="no-corpus"').mark(
                    "no-corpus"
                ).style("font-size:12px;color:var(--ink2);")

    def _corpus_chip(self, current: CorpusView) -> None:
        """ "corpus 2026‑09‑02 · v1 ▼" — which corpus's columns are listed."""
        self._dropdown(
            name="corpus",
            text=_corpus_chip_text(current),
            aria_label="Corpus",
            options=[
                (c.corpus_id, _corpus_chip_text(c), c.corpus_id == current.corpus_id)
                for c in self._corpora
            ],
            on_pick=self._pick_corpus,
        )

    def _language_chip(self) -> None:
        """ "prompt language · de ▼".

        One language for the whole view: the edit zone's `Labels de | fr | it`
        chips set the same fact. Two independent selectors would let the list's
        statuses and the codes table's labels disagree about which language was
        being judged, and the status *is* per language (§14.2).
        """
        chosen = codelists_state().language
        self._dropdown(
            name="language",
            text=f"prompt language · {chosen}",
            aria_label="Prompt language",
            options=[
                (code, f"prompt language · {code}", code == chosen) for code in PROMPT_LANGUAGES
            ],
            on_pick=self._pick_language,
        )

    def _status_chip(self) -> None:
        """ "status · all 18 ▼", each option carrying its live count.

        `len()` over the complete list the service returned — not over a page,
        and not a recomputed status (module docstring).
        """
        chosen = codelists_state().status
        options = [
            ("", f"status · all {len(self._columns)}", chosen is None),
            *(
                (
                    status.value,
                    f"status · {status.value} {len(self._of_status(status))}",
                    status is chosen,
                )
                for status in GROUP_ORDER
            ),
        ]
        text = next(option_text for _, option_text, on in options if on)
        self._dropdown(
            name="status",
            text=text,
            aria_label="Coverage status",
            options=options,
            on_pick=self._pick_status,
        )

    def _blocking_chip(self) -> None:
        """ "2 columns have no codes · blocks 1 feature" — the danger chip.

        The feature half is **always zero** in phase 2: nothing links a feature
        to a column yet (C5), and inventing a number here would be the exact
        business logic §12.7 forbids. The column half is real.
        """
        missing = len(self._of_status(CoverageStatus.MISSING))
        if not missing:
            return
        with (
            ui.element("div")
            .props('data-testid="blocking-chip"')
            .mark("blocking-chip")
            .style(
                "display:inline-flex;align-items:center;gap:7px;padding:4px 9px;border-radius:3px;"
                "background:var(--danger-soft);color:var(--danger);font-size:11.5px;"
                "font-weight:500;white-space:nowrap;"
            )
        ):
            ui.html(svg(ALERT_TRIANGLE, size=13, stroke=1.9), tag="span", sanitize=False).style(
                "display:inline-flex;flex:none;"
            )
            ui.label(_blocking_text(missing))

    # --- the master list ---------------------------------------------------

    def _master_list(self) -> None:
        shown = self._shown()
        with ui.element("div").style(LIST_HEADER_STYLE):
            ui.label(_columns_count(len(self._columns))).classes("lbl").props(
                'data-testid="columns-count"'
            ).mark("columns-count").style("min-width:0;overflow:hidden;text-overflow:ellipsis;")
            self._import_button()
        with ui.element("div").props('data-testid="codelist-list"').style(LIST_BODY_STYLE):
            if not shown:
                ui.label(
                    NO_COLUMNS_MESSAGE if self._corpus is not None else NO_CORPUS_MESSAGE
                ).props('data-testid="list-empty"').mark("list-empty").style(EMPTY_STYLE)
            else:
                self._groups(shown)
        with ui.element("div").style(LIST_FOOTER_STYLE):
            ui.label(SORTED_BY_STATUS).classes("lbl")
            ui.label(f"{len(shown)} of {len(self._columns)} shown").classes("mono nowrap").props(
                'data-testid="shown-count"'
            ).mark("shown-count").style("font-size:11px;color:var(--ink2);")

    def _groups(self, shown: Sequence[ColumnMappingView]) -> None:
        selected = self._selected()
        first = True
        for status in GROUP_ORDER:
            rows = [c for c in shown if _status_of(c) is status]
            if not rows:
                continue
            padding = "12px 16px 6px" if first else "16px 16px 6px"
            first = False
            ui.label(group_label(status, len(rows))).classes("lbl").props(
                f'data-testid="group-label" data-status="{status.value}"'
            ).mark("group-label").style(f"padding:{padding};")
            for row in rows:
                self._row(row, status=status, selected=row is selected)

    def _row(self, column: ColumnMappingView, *, status: CoverageStatus, selected: bool) -> None:
        """One `.row`: name over subtitle on the left, status marker right.

        A real `<button>`, so the list is reachable with Tab alone and the
        `--focus` ring shows — the design leaves focus undesigned and
        sw-design.md §8.2 says to add one from the single token.
        """
        style = ROW_STYLE
        if status is CoverageStatus.MISSING:
            style += ROW_DANGER_STYLE
        if selected:
            style += ROW_SELECTED_STYLE
        button = (
            ui.element("button")
            .props(
                'type="button" data-testid="codelist-row" '
                f'data-status="{status.value}" data-column="{column.column_name}" '
                f'aria-pressed="{"true" if selected else "false"}" '
                f'aria-label="{_row_name(column)}"'
            )
            .mark("codelist-row", f"row-{column.column_name}")
            .style(style)
        )
        button.on("click", lambda _: self._select(column.column_name))
        with button:
            with ui.element("div").style("min-width:0;overflow:hidden;"):
                ui.label(_row_name(column)).props('data-testid="row-name"').mark("row-name").style(
                    "font-size:12.5px;font-weight:"
                    + ("600;" if selected else "500;")
                    + ("color:var(--danger);" if status is CoverageStatus.MISSING else "")
                )
                ui.label(_row_subtitle(column, status)).classes("mono").props(
                    'data-testid="row-sub"'
                ).mark("row-sub").style(
                    "font-size:10.5px;margin-top:2px;color:"
                    + (
                        "var(--danger);"
                        if status is CoverageStatus.MISSING
                        else ("var(--ink2);" if selected else "var(--ink3);")
                    )
                )
            with ui.element("div").style("flex:none;display:flex;align-items:center;gap:8px;"):
                _status_marker(column, status)

    def _import_button(self) -> None:
        """The design's secondary "Import Codes as JSON" — **the only** import
        action, one file for every attribute (sw-design.md §14.1)."""
        button = (
            ui.element("button")
            .classes("btn secondary")
            .props('type="button" data-testid="import-codes"')
            .mark("import-codes")
            .style("flex:none;")
        )
        button.on("click", cast("Callable[[], None]", self._open_import))
        with button:
            ui.html(svg(DOWNLOAD, size=12, stroke=2.0), tag="span", sanitize=False).style(
                "display:inline-flex;"
            )
            ui.label(IMPORT_LABEL)

    # --- the edit zone -----------------------------------------------------

    def _edit_zone(self) -> None:
        column = self._selected()
        if column is None:
            ui.label(NO_SELECTION_MESSAGE if self._corpus is not None else NO_CORPUS_MESSAGE).props(
                'data-testid="detail-empty"'
            ).mark("detail-empty").style(EMPTY_STYLE)
            return
        self._edit_header(column)
        self._codes_card(column)
        self._below_cards(column)

    def _edit_header(self, column: ColumnMappingView) -> None:
        with ui.element("div").style(EDIT_HEADER_STYLE):
            with ui.element("div").style("min-width:0;"):
                ui.label(EDIT_ZONE_LABEL).classes("lbl")
                with ui.element("h2").style(
                    "margin:4px 0 0;font-family:var(--mono);font-size:16px;font-weight:600;"
                    "color:var(--ink);word-break:break-all;"
                ):
                    ui.label(_row_name(column)).props('data-testid="detail-name"').mark(
                        "detail-name"
                    )
                ui.label(_detail_subtitle(column)).props('data-testid="detail-sub"').mark(
                    "detail-sub"
                ).style("font-size:12px;color:var(--ink2);margin-top:3px;")
                ui.label(self._mapping_line(column)).classes("mono").props(
                    'data-testid="detail-mapping"'
                ).mark("detail-mapping").style(
                    "font-size:11px;color:var(--ink3);margin-top:3px;white-space:normal;"
                )
            with ui.element("div").style(EDIT_HEADER_RIGHT_STYLE):
                ui.label(LABELS_LABEL).classes("lbl")
                self._language_chips()
                ui.label(JSON_KEY_LABEL).classes("lbl").style("margin-left:6px;")
                self._json_key_select(column)

    def _language_chips(self) -> None:
        """`.chip`s `de` / `fr` / `it`, the active one border `--accent`.

        The same fact the toolbar's language chip carries (see
        `_language_chip`), offered where the design offers it.
        """
        chosen = codelists_state().language
        for code in PROMPT_LANGUAGES:
            active = code == chosen
            element = (
                ui.element("button")
                .classes("chip")
                .props(
                    f'type="button" aria-label="Labels in {code}" '
                    f'aria-pressed="{"true" if active else "false"}" '
                    f'data-testid="language-chip" data-language="{code}"'
                )
                .mark("language-chip", f"language-{code}")
                .style(
                    "padding:3px 8px;"
                    + (
                        "border-color:var(--accent);color:var(--ink);font-weight:500;"
                        if active
                        else "color:var(--ink2);"
                    )
                )
            )
            element.on("click", cast("Callable[[], None]", lambda c=code: self._pick_language(c)))
            with element:
                ui.label(code)

    def _json_key_select(self, column: ColumnMappingView) -> None:
        """The mapping control (README): the attribute keys of the imported
        file, so a census column can be pointed at the right one.

        `field_select` is the kit's `.rof`; README clamps this particular one
        to 210px, which is what the wrapper does. Picking calls
        `CodelistService.map_column`; the first entry calls `unmap_column`.
        """
        attribute = column.mapped_attribute
        text = (
            f"{attribute.key} {attribute.code_count}"
            if attribute is not None
            else NOT_MAPPED_OPTION
        )
        expanded = self._open_menu == "json-key"
        with ui.element("div").style(JSON_KEY_BOX_STYLE):
            field_select(
                text,
                label=JSON_KEY_LABEL,
                disabled=not self._attributes,
                on_click=lambda: self._toggle_menu("json-key"),
            ).props(
                'data-testid="json-key" aria-haspopup="listbox" '
                f'aria-expanded="{"true" if expanded else "false"}"'
            ).mark("json-key")
            if not expanded:
                return
            with (
                ui.element("div")
                .props('role="listbox" aria-label="JSON key" data-testid="menu-json-key"')
                .style(_MENU_STYLE)
            ):
                self._menu_item(
                    name="json-key",
                    value="",
                    text=NOT_MAPPED_OPTION,
                    selected=attribute is None,
                    on_pick=self._pick_attribute,
                )
                for candidate in self._attributes:
                    self._menu_item(
                        name="json-key",
                        value=str(candidate.code_attribute_id),
                        text=f"{candidate.key} {candidate.code_count}",
                        selected=(
                            attribute is not None
                            and candidate.code_attribute_id == attribute.code_attribute_id
                        ),
                        on_pick=self._pick_attribute,
                    )

    def _codes_card(self, column: ColumnMappingView) -> None:
        """The read-only codes table plus its two footers, in one `.card`."""
        coverage = column.coverage
        with card(extra="margin-top:14px;overflow:hidden;"):
            if coverage is None or not coverage.codes:
                ui.label(NO_CODELIST_MESSAGE).props('data-testid="codes-empty"').mark(
                    "codes-empty"
                ).style(EMPTY_STYLE)
            else:
                self._codes_table(coverage)
                orphans = tuple(u for u in coverage.codes if not u.in_codelist)
                if orphans:
                    self._danger_footer(orphans)
            self._neutral_footer()

    def _codes_table(self, coverage: ColumnCoverage) -> None:
        """Code 44px · Label (flexible, wrapping) · Usage 96px right.

        Not `data_table`: this table does not sort, does not page and has no
        `TableState` behind it — the row order is `ColumnCoverage.codes`, which
        the domain already ordered by usage (§14.2). Forcing it through the
        sortable component would mean inventing a sort the design does not
        draw, which is exactly what §8.1.4 warns against.
        """
        with (
            ui.element("div").style("overflow:auto;"),
            ui.element("table")
            .classes("wide")
            .props('data-testid="table-codes"')
            .mark("table-codes")
            .style("table-layout:fixed;width:100%;border-collapse:collapse;"),
        ):
            with ui.element("thead"), ui.element("tr"):
                _header_cell(CODE_HEADER, width="44px")
                _header_cell(_label_header(coverage.language), width=None)
                _header_cell(USAGE_HEADER, width="96px", align="right")
            with ui.element("tbody"):
                for usage in coverage.codes:
                    _code_row(usage)

    def _danger_footer(self, orphans: Sequence[CodeUsage]) -> None:
        """README footer 1: the codes the corpus uses that the codelist has no
        row for at all — mvp-spec.md §7's `Finding`-grade case."""
        with (
            ui.element("div")
            .props('data-testid="danger-footer"')
            .mark("danger-footer")
            .style(
                _FOOTER_BASE_STYLE + "background:var(--danger-soft);color:var(--danger);"
                "border-top:1px solid var(--rule);"
            )
        ):
            ui.html(svg(ALERT_TRIANGLE, size=14, stroke=1.8), tag="span", sanitize=False).style(
                "flex:none;margin-top:1px;display:inline-flex;"
            )
            ui.label(danger_footer_text(orphans)).props('data-testid="danger-text"').mark(
                "danger-text"
            ).style("white-space:normal;")
            _add_label_button()

    def _neutral_footer(self) -> None:
        """README footer 2 — always present, because "read-only" is a property
        of every codelist, not of the ones with a problem."""
        with (
            ui.element("div")
            .props('data-testid="neutral-footer"')
            .mark("neutral-footer")
            .style(
                _FOOTER_BASE_STYLE + "background:var(--field-tint);color:var(--ink2);"
                "border-top:1px solid var(--rule2);"
            )
        ):
            ui.html(svg(INFO, size=14, stroke=1.8), tag="span", sanitize=False).style(
                "flex:none;margin-top:1px;display:inline-flex;"
            )
            ui.label(NEUTRAL_FOOTER).props('data-testid="neutral-text"').mark("neutral-text").style(
                "white-space:normal;"
            )

    def _below_cards(self, column: ColumnMappingView) -> None:
        with ui.element("div").style(CARDS_ROW_STYLE):
            with card(flex="1.4 1 300px", extra="padding:12px 14px;").props(
                'data-card="prompt-preview"'
            ):
                ui.label(PROMPT_PREVIEW_TITLE).classes("lbl")
                ui.label(prompt_preview(column)).classes("mono").props(
                    'data-testid="prompt-preview"'
                ).mark("prompt-preview").style(
                    "font-size:11.5px;white-space:pre-wrap;margin-top:8px;color:var(--ink);"
                )
            with card(flex="1 1 240px", extra="padding:12px 14px;").props('data-card="reminder"'):
                ui.label(REMINDER_TITLE).classes("lbl")
                ui.label(REMINDER_BODY).props('data-testid="reminder-body"').mark(
                    "reminder-body"
                ).style("color:var(--ink2);font-size:12.5px;margin-top:6px;white-space:normal;")

    def _mapping_line(self, column: ColumnMappingView) -> str:
        """README: "mapped to witterung_codes in codes-vum-2026-09.json · 24
        keys, 18 mapped".

        The filename is only shown when this client imported the file itself:
        no read model carries `code_table_import.source_file`, and a filename
        this view invented would be a lie about provenance. Both counts are
        `len()` over complete service results (module docstring).
        """
        attribute = column.mapped_attribute
        keys = len(self._attributes)
        mapped = sum(1 for c in self._columns if c.mapping_id is not None)
        tail = f"{keys} keys, {mapped} mapped"
        if attribute is None:
            return f"not mapped · {tail}"
        where = f" in {self._import_file}" if self._import_file else ""
        return f"mapped to {attribute.key}{where} · {tail}"

    # --- dropdown plumbing --------------------------------------------------

    def _dropdown(
        self,
        *,
        name: str,
        text: str,
        aria_label: str,
        options: Sequence[tuple[str, str, bool]],
        on_pick: Callable[[str], Awaitable[None]],
    ) -> None:
        """One `.sl` toolbar chip plus, when open, its option panel.

        Built from `ui.element` rather than `ui.select`/`ui.menu` for the same
        reason `census_view` builds its own: Quasar's carry a 40px hit target,
        a ripple and a type scale this design does not have (R2, §8.2).
        """
        expanded = self._open_menu == name
        with ui.element("div").style("position:relative;display:inline-flex;"):
            chip = (
                ui.element("button")
                .classes("chip")
                .props(
                    f'type="button" aria-label="{aria_label}" data-chip="{name}" '
                    'aria-haspopup="listbox" '
                    f'aria-expanded="{"true" if expanded else "false"}" '
                    'data-testid="chip"'
                )
                .mark("chip", f"chip-{name}")
            )
            chip.on("click", lambda _: self._toggle_menu(name))
            with chip:
                ui.label(text)
                ui.label("▼").classes("caret")
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

    def _toggle_menu(self, name: str) -> None:
        self._open_menu = None if self._open_menu == name else name
        self._render()

    # --- actions ------------------------------------------------------------

    async def _pick_corpus(self, corpus_id: str) -> None:
        app.storage.client[CORPUS_KEY] = corpus_id
        # A column name is only meaningful inside one corpus.
        current = codelists_state()
        self._store(CodelistsState(language=current.language, status=current.status, selected=None))
        self._open_menu = None
        await self.reload()

    async def _pick_language(self, language: str) -> None:
        """The status is **per language** (§14.2), so this is a re-read, not a
        redraw: every row's status can change."""
        current = codelists_state()
        self._store(
            CodelistsState(language=language, status=current.status, selected=current.selected)
        )
        self._open_menu = None
        await self.reload()

    async def _pick_status(self, status: str) -> None:
        current = codelists_state()
        self._store(
            CodelistsState(
                language=current.language,
                status=CoverageStatus(status) if status else None,
                selected=current.selected,
            )
        )
        self._open_menu = None
        await self.reload()

    async def _pick_attribute(self, code_attribute_id: str) -> None:
        """Map or unmap the selected column. Both write `column_mapping` only
        — mvp-spec.md §7: no UI path ever writes `code_value`."""
        column = self._selected()
        self._open_menu = None
        if column is None or self._corpus is None:
            self._render()
            return
        try:
            if code_attribute_id:
                await self._services.codelist.map_column(
                    CorpusId(self._corpus.corpus_id),
                    column.column_name,
                    CodeAttributeId(code_attribute_id),
                )
            else:
                await self._services.codelist.unmap_column(
                    CorpusId(self._corpus.corpus_id), column.column_name
                )
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            self._render()
            return
        # The row can move between groups, so keep it selected by name.
        self._select_only(column.column_name)
        await self.reload()

    def _select(self, column_name: str) -> None:
        self._select_only(column_name)
        self._open_menu = None
        self._render()

    def _select_only(self, column_name: str) -> None:
        current = codelists_state()
        self._store(
            CodelistsState(language=current.language, status=current.status, selected=column_name)
        )

    def _store(self, changed: CodelistsState) -> None:
        """Replace this client's `CodelistsState`.

        The dataclass is frozen, so "changing a filter" is storing a new value
        under the same key — never a mutation of something another render is
        holding.
        """
        app.storage.client[STATE_KEY] = changed

    # --- import (sw-design.md §14.1) ----------------------------------------

    async def _open_import(self) -> None:
        """One file, every attribute. The design draws a button and no dialog;
        a file picker needs somewhere to live, so this is the smallest surface
        that makes §14.1's single upload reachable — the same shape as
        `import_view._open_intake`.

        The previous dialog is deleted first: it is parented to `_root`, which
        nothing clears, so re-opening would otherwise leave a second file
        picker behind on every press.
        """
        assert self._root is not None
        if self._import_dialog is not None:
            self._import_dialog.delete()
            self._import_dialog = None
        with (
            # Parented to `_root`, which the view never clears: the button that
            # opened this dialog is redrawn by `reload()` mid-handler.
            self._root,
            ui.dialog().props('data-testid="import-dialog"') as dialog,
            # Quasar re-enables pointer events by tag on `.q-dialog__inner >
            # div`; a `<section class="card">` as the direct child is inert.
            ui.element("div").style("border-radius:3px;"),
            card(extra="width:520px;"),
        ):
            self._import_dialog = dialog
            with ui.element("div").style("padding:14px;"):
                ui.label(IMPORT_LABEL).classes("lbl")
                ui.label(
                    "One JSON file holding every attribute. An import succeeds "
                    "whole or not at all, and never edits an existing code table."
                ).style("font-size:12.5px;color:var(--ink2);margin-top:6px;white-space:normal;")
            with ui.element("div").style("padding:0 14px 14px;"):
                # `auto_upload=True`: the design draws **one** action ("Import
                # Codes as JSON"), and Quasar's uploader otherwise needs a
                # second press on its own ▶ button before anything is sent.
                # One file, one gesture — picking the file *is* the import.
                ui.upload(
                    multiple=False,
                    auto_upload=True,
                    on_multi_upload=cast(
                        "Callable[[MultiUploadEventArguments], None]",
                        lambda event: self._import(event, dialog),
                    ),
                ).props('accept=".json,application/json" data-testid="codelist-upload"').style(
                    "width:100%;"
                )
        dialog.value = True

    async def _import(self, event: MultiUploadEventArguments, dialog: ui.dialog) -> None:
        """Hand the bytes to `CodelistService.import_file` and redraw.

        A structural failure is a **dialog**, not a toast: it is a list of
        errors the analyst has to read (see the module docstring). A re-upload
        of the current file is `no_change=True` — reported, not an error.
        """
        upload = next(iter(event.files), None)
        if upload is None:
            return
        try:
            result = await self._services.codelist.import_file(upload.name, await upload.read())
        except CodelistImportError as exc:
            dialog.close()
            assert self._root is not None
            _show_import_errors(exc.import_errors, host=self._root)
            return
        except (ServiceError, OSError, UnicodeDecodeError, ValueError) as exc:
            dialog.close()
            ui.notify(str(exc), type="negative")
            return
        dialog.close()
        self._import_file = upload.name
        ui.notify(_import_message(result.attribute_count, no_change=result.no_change))
        await self.reload()


# --- row rendering ------------------------------------------------------------


def _status_of(column: ColumnMappingView) -> CoverageStatus:
    """The row's group. `coverage is None` is "no `column_mapping` row", which
    §14.2 defines as `MISSING` — the same answer `compute_coverage` gives for
    a mapping with no codes, and the reason `ColumnMappingView.coverage` is
    documented as `None` exactly when `mapped_attribute` is."""
    return column.coverage.status if column.coverage is not None else CoverageStatus.MISSING


def _status_marker(column: ColumnMappingView, status: CoverageStatus) -> None:
    """README: an outline `.pill` "no codes", a 44×6 `.bar` + percentage, or
    an `--ok-soft` `.pill` "100 %"."""
    if status is CoverageStatus.MISSING:
        pill(NO_CODES_PILL, tone="danger").props('data-testid="marker-missing"').mark(
            "marker-missing"
        )
        return
    coverage = column.coverage
    assert coverage is not None  # only a MISSING row can be unmapped (§14.2)
    if status is CoverageStatus.OK:
        pill(FULLY_LABELLED_PILL, tone="ok").props('data-testid="marker-ok"').mark("marker-ok")
        return
    # README: the partial bar is 44px wide with a `--warn` fill, where the
    # kit's `.bar` is 78px with an `--ink3` one. The width is the element's own
    # style; the fill colour belongs to the `<i>` the component made, so it is
    # set on that child rather than by a new CSS rule (`theme.py` is not this
    # branch's to edit). Nothing about the *value* changes — `coverage_pct` is
    # the service's, in `[0, 1]`, and `* 100` is the unit the bar draws in.
    track = bar(fill_pct=coverage.coverage_pct * 100)
    track.style("width:44px;").props('data-testid="marker-partial"').mark("marker-partial")
    for fill in track.default_slot.children:
        fill.style("background:var(--warn);")
    ui.label(percent(coverage.coverage_pct)).classes("mono").props(
        'data-testid="coverage-pct"'
    ).mark("coverage-pct").style("font-size:11px;color:var(--warn);")


def _header_cell(label: str, *, width: str | None, align: str = "left") -> None:
    style = f"text-align:{align};"
    if width is not None:
        style += f"width:{width};"
    with ui.element("th").classes("th").props('scope="col" data-testid="codes-th"').style(style):
        ui.label(label)


def _code_row(usage: CodeUsage) -> None:
    """One `CodeUsage`. The orphan row is the design's danger row: the code has
    **no row at all** in the mapped attribute, in any language (§14.2)."""
    orphan = not usage.in_codelist
    row = (
        ui.element("tr")
        .props(
            f'data-testid="code-row" data-code="{usage.code}" '
            f'data-orphan="{"true" if orphan else "false"}"'
        )
        .mark("code-row", f"code-{usage.code}")
    )
    if orphan:
        row.style(ROW_DANGER_STYLE)
    with row:
        with (
            ui.element("td")
            .classes("td mono")
            .style(
                "color:var(--danger);"
                if orphan
                else (_UNKNOWN_CODE_STYLE if _is_unknown(usage) else "")
            )
        ):
            ui.label(usage.code)
        with (
            ui.element("td")
            .classes("td")
            .style("white-space:normal;" + ("color:var(--danger);" if orphan else ""))
        ):
            # `.fld`: plain text, no border, no hover, **never** an input —
            # mvp-spec.md §7 has no inline label editing at all.
            ui.label(_label_text(usage)).props('data-testid="code-label"').mark("code-label").style(
                FLD_STYLE
            )
        with ui.element("td").classes("td").style("text-align:right;"):
            ui.label(format_count(usage.count)).classes("mono").props(
                'data-testid="code-count"'
            ).mark("code-count").style("font-size:12px;")
            ui.label(percent(usage.share)).classes("mono").props('data-testid="code-share"').mark(
                "code-share"
            ).style("font-size:10.5px;color:var(--ink3);margin-top:1px;")


def _add_label_button() -> None:
    """README draws a secondary "Add label" in the danger footer.

    It is drawn **disabled**: mvp-spec.md §7 says there is no UI path that
    writes `code_value` — "a correction means importing a fixed file". The
    same rule Census's "use as feature" follows: the affordance stays visible
    and is inert, rather than vanishing or lying.
    """
    button = (
        ui.element("button")
        .classes("btn secondary")
        .props(
            'type="button" disabled aria-disabled="true" data-testid="add-label" '
            'title="Labels are read-only — import a corrected JSON file instead"'
        )
        .mark("add-label")
        .style("flex:none;margin-left:auto;color:var(--danger);opacity:.6;cursor:default;")
    )
    with button:
        ui.label(ADD_LABEL)


# --- copy builders ------------------------------------------------------------


def group_label(status: CoverageStatus, count: int) -> str:
    """README's group headings: "2 missing — blocks any feature using it"."""
    return f"{count} {STATUS_LABELS[status]}"


def danger_footer_text(orphans: Sequence[CodeUsage]) -> str:
    """README footer 1, verbatim for the design's one-code case.

    "Code 7 appears in 31 records but has no label. The prompt cannot name it,
    and those records score against an unnamed code."

    More than one orphan is undrawn; the sentence pluralises rather than
    repeating itself per code, and the record count is the sum of the counts
    the service reported — no other number is available or invented.
    """
    codes = ", ".join(usage.code for usage in orphans)
    records = sum(usage.count for usage in orphans)
    if len(orphans) == 1:
        return (
            f"Code {codes} appears in {format_count(records)} records but has no "
            "label. The prompt cannot name it, and those records score against "
            "an unnamed code."
        )
    return (
        f"Codes {codes} appear in {format_count(records)} records but have no "
        "labels. The prompt cannot name them, and those records score against "
        "unnamed codes."
    )


def prompt_preview(column: ColumnMappingView) -> str:
    """README's "Prompt preview · what the model is shown".

    Assembled from what is already on screen — the attribute key and the first
    few `code = label` pairs — not fetched. It is a **display** of the codelist,
    and deliberately not the prompt builder: the real prompt is phase 3's
    (mvp-spec.md §10.2), and a second implementation of it here would be two
    truths about what the model is asked.
    """
    attribute = column.mapped_attribute
    coverage = column.coverage
    if attribute is None or coverage is None:
        return f"{column.column_name} — enum. No codelist mapped yet."
    lines = [f"{attribute.key} — enum. Emit the code."]
    labelled = [u for u in coverage.codes if u.label is not None]
    lines.extend(f"{u.code} = {u.label}" for u in labelled[:PREVIEW_LINES])
    if len(labelled) > PREVIEW_LINES:
        lines.append("…")
    return "\n".join(lines)


def _row_name(column: ColumnMappingView) -> str:
    """README's row names: `VortrittAusw`, but `objekt.SchadenAusw` and
    `person.VerletzungsgradAusw`.

    The design qualifies a column with its table everywhere except `unfall`,
    the one-row-per-accident table — a pure presentation rule over two
    service fields, and the reason a column name alone is never ambiguous on
    screen.
    """
    if column.table_name == "unfall":
        return column.column_name
    return f"{column.table_name}.{column.column_name}"


def _row_subtitle(column: ColumnMappingView, status: CoverageStatus) -> str:
    """README's `.rsub`, which says a different thing per group:

    - missing: "unfall · 4 distinct in corpus · unused"
    - partial: "unfall · 8 of 9 labelled · used by Weather"
    - ok:      "unfall · 5 codes · unused"
    """
    coverage = column.coverage
    if status is CoverageStatus.MISSING or coverage is None:
        middle = f"{column.distinct_in_corpus} distinct in corpus"
    elif status is CoverageStatus.PARTIAL:
        middle = f"{coverage.labelled_count} of {coverage.total_count} labelled"
    else:
        middle = f"{coverage.total_count} codes"
    return f"{column.table_name} · {middle} · {_used_by(column)}"


def _detail_subtitle(column: ColumnMappingView) -> str:
    """README's edit-zone line: "unfall · 8 codes · used by Weather"."""
    coverage = column.coverage
    if coverage is None:
        middle = f"{column.distinct_in_corpus} distinct in corpus"
    else:
        middle = f"{coverage.total_count} codes"
    return f"{column.table_name} · {middle} · {_used_by(column)}"


def _used_by(column: ColumnMappingView) -> str:
    """ "used by Weather", or the design's own "unused" — rendered, never
    computed here; `CodelistService.list_columns` is what decides it (C5)."""
    if not column.used_by_features:
        return UNUSED
    return f"{USED_BY} {', '.join(column.used_by_features)}"


def _blocking_text(missing: int) -> str:
    """The danger chip: "2 columns have no codes · blocks 1 feature".

    The feature count is `0` until a feature can cite a column (C5).
    """
    subject = "1 column has" if missing == 1 else f"{missing} columns have"
    return f"{subject} no codes · blocks 0 features"


def _columns_count(total: int) -> str:
    noun = "column" if total == 1 else "columns"
    return f"{total} {noun}"


def _label_header(language: str) -> str:
    """README: "Label · de (prompt)"."""
    return f"Label · {language} (prompt)"


def _label_text(usage: CodeUsage) -> str:
    """The label, or the design's danger-row copy for a code the codelist has
    no row for, or the same for one merely missing this language's label."""
    if usage.label is not None:
        return usage.label
    if not usage.in_codelist:
        return "no label — not in the codelist"
    return "no label in this language"


def _is_unknown(usage: CodeUsage) -> bool:
    return usage.code in _UNKNOWN_CODES


def percent(rate: float) -> str:
    """The design's "100 %", "88.9 %", "0.4 %", "0 %".

    One decimal, except a full 100 % and a flat 0 %, which the mock writes
    without one. Presentation only — the rate itself is the service's.
    """
    pct = rate * 100
    if pct >= 100:
        return "100 %"
    if pct == 0:
        return "0 %"
    return f"{pct:.1f} %"


def _corpus_chip_text(corpus: CorpusView) -> str:
    """The design's "corpus 2026‑09‑02 · v1", identical to Census's chip."""
    return f"corpus {corpus.name} · v{corpus.version}"


def _import_message(attribute_count: int, *, no_change: bool) -> str:
    """Undesigned. `no_change=True` is **not** an error (§14.1 step 2)."""
    if no_change:
        return "Already current — nothing imported."
    noun = "attribute" if attribute_count == 1 else "attributes"
    return f"Imported {attribute_count} {noun}."


# --- error surfaces -----------------------------------------------------------


def _show_import_errors(errors: Sequence[CodeImportError], *, host: Element) -> None:
    """The refused-import surface.

    Undesigned (README, "Loading / empty / error"), and the same judgment
    `import_view._show_blocking` makes for a refused freeze: a list the
    analyst has to read and act on is a dialog, not a toast. Each error names
    its attribute key and its JSON path, because those are what locate the
    problem in the file.
    """
    with (
        # See `_open_import` for why the dialog is parented to `host`.
        host,
        ui.dialog().props('data-testid="import-failed"') as dialog,
        ui.element("div").style("border-radius:3px;"),
        card(extra="width:640px;"),
    ):
        with ui.element("div").style("padding:14px;"):
            ui.label(IMPORT_FAILED_TITLE).props('data-testid="import-failed-title"').mark(
                "import-failed-title"
            ).style("font-size:13px;font-weight:600;")
            ui.label(IMPORT_FAILED_BODY).style(
                "font-size:12.5px;color:var(--ink2);margin-top:4px;white-space:normal;"
            )
        with ui.element("div").style("padding:0 14px 14px;"):
            for error in errors:
                with (
                    ui.element("div")
                    .props('data-testid="import-error"')
                    .mark("import-error")
                    .style("padding:8px 0;border-top:1px solid var(--rule2);")
                ):
                    with ui.element("div").style("display:flex;gap:8px;align-items:baseline;"):
                        if error.attribute_key:
                            ui.label(error.attribute_key).classes("mono").props(
                                'data-testid="import-error-key"'
                            ).mark("import-error-key").style(
                                "font-size:11px;word-break:break-all;white-space:normal;"
                            )
                        ui.label(error.path).classes("mono").props(
                            'data-testid="import-error-path"'
                        ).mark("import-error-path").style(
                            "font-size:11px;color:var(--ink3);word-break:break-all;"
                            "white-space:normal;"
                        )
                    ui.label(error.message).props('data-testid="import-error-message"').mark(
                        "import-error-message"
                    ).style("font-size:12px;white-space:normal;")
        with ui.element("div").style("padding:0 14px 14px;"):
            close = (
                ui.element("button")
                .classes("btn secondary")
                .props('type="button" data-testid="import-failed-close"')
                .mark("import-failed-close")
            )
            close.on("click", lambda _: dialog.close())
            with close:
                ui.label("Close")
    dialog.value = True

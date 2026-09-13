# STUB — bodies owned by L1 (feat/p3-prompts-view, phase 3 Wave 4).
"""Prompts view — the wording around the feature descriptions, versioned.

`design/prompt-evaluation/README.md` §1 (`PromptTemplate - A source.dc.html`):
master/detail, identical in structure to Codelists and Features. The version
list is capped at **10 rows / 530px** with the standard pagination row, then
two reference strips ("Slots available" and the slot table); the editor
carries the fingerprint block, the Source card with inline slot highlighting
and its `--warn-soft` copy-on-write footer, and the Resolved card capped at
**210px**.

The three rules that shape every view here are unchanged:

1. **No business logic** (CLAUDE.md #7) — every version, count, fingerprint
   and validation message arrives from `PromptService`. This file decides only
   *how much of what it was handed fits on screen*: which page of the version
   list is drawn, which row is selected, and which of the design's four row
   markers a row's own `is_active` / `cited_by_run_count` / `deletable` fields
   put on it. Nothing below re-derives one of those facts.
2. **No module-level mutable state** (#8) — the selected version and the page
   live in `app.storage.client` (the page through `ui/state.py`'s
   `TableState`, the same way every other paged list in this app keeps it).
   The one thing that does *not* go there is the in-progress edit buffer, for
   the reason `features_view.py`'s docstring gives: `app.storage.client` is
   for navigational state a service could always reconstruct, not a scratchpad
   for an edit nobody asked to persist yet.
3. **Services in-process as Python** — no HTTP call to this app's own API, and
   no session or ORM object crosses into this file.

`prompt_preview_panel` (`ui/components/prompt_preview.py`) is **placed here,
not implemented here**: it is L3's, built in parallel this same wave against a
signature frozen at M17 (plan-phase-3.md §3.1, C4 — one component, two entry
points). Wiring against the frozen signature is correct regardless of when the
body lands — exactly as `features_view.py` places `derivation_builder` — and
it has since landed.

L1 also flips this view's own `built` flag in `ui/shell.py` and adds its own
line to `views/register_all` — **those two lines and nothing else** in either
file (plan-phase-3.md §6.1).

**Judgment calls made in this file, documented at the point of decision and
repeated in the branch's final report:**

- *Saving activates the new version* (`_save_as_next_version`). The design
  draws no activate affordance anywhere — the toolbar has exactly two buttons
  and the rows carry markers, not actions — yet the ACTIVE pill marks "the one
  new evaluations default to" and copy-on-write means the new wording arrives
  as a *new row*. A version nobody can activate is a version nobody can use,
  so the save that creates vN+1 also makes it the one new evaluations get.
  Both halves are `PromptService` calls; nothing is decided here beyond the
  order they happen in.
- *Editing is entered explicitly, and saving is explicit.* The design's Source
  card is a static mock with no edit affordance at all. Clicking the rendered
  source opens the editor on it, and so does "New version" in the list header
  (which seeds the editor from the selected version rather than writing
  anything — under copy-on-write, "new version" *is* "save as vN"). No
  autosave-on-keystroke, matching `features_view`'s own decision for the same
  undesigned corner.
- *"Preview with record 1" resolves against the most recent evaluation.* C4
  says Prompts previews against "the active feature set and record 1", but no
  service surface hands a `ui/` module a record id: `PromptService.preview` —
  whose signature is frozen — requires one, and neither `PromptTemplateView`
  nor `CorpusView` nor `FeatureSetSummary` carries one. The most recent
  evaluation is the one place this app can point at a record *and* the feature
  set and prompt language that belong with it, so that is what the preview
  resolves against; with no evaluation yet, the Resolved card renders its
  (undesigned) empty state rather than guessing. `contracts/amendments/
  feat-p3-prompts-view.md` proposes the small read that would let the preview
  stand on its own.
- *The version list is paged in the view.* `PromptService.list_versions()`
  takes no page parameter (its signature is frozen, CONTRACTS.md), and the
  design pages this list at 10 rows. Slicing the complete list the service
  returned is presentation over data already handed over — the same class of
  operation as `bar()`'s percentage clamp — and the "1–N of M" range is
  computed by `pagination_row` from the totals, not from what is on screen.
- *Loading / empty / error* are undesigned (README, "Loading / empty /
  error"): empty states are one centred line, a refused delete and a failed
  save are a `ui.notify` and, for a validation refusal, the typed error list
  rendered in the Source card where the text that caused it is.
"""

from collections.abc import Awaitable, Callable
from typing import Final, cast

from nicegui import app, ui
from nicegui.element import Element

from ra2.domain.ids import FeatureConfigId, PromptTemplateId, RecordId
from ra2.domain.prompt import PromptValidationCode, PromptValidationError
from ra2.services.container import Services
from ra2.services.errors import PromptTemplateInvalidError, ServiceError
from ra2.services.readmodels import (
    PromptTemplateView,
    ResolvedPromptView,
    SlotView,
    SortDir,
)
from ra2.ui.components import card, format_count, icon_button, pagination_row
from ra2.ui.components.icons import INFO, PLUS, svg
from ra2.ui.components.primitives import (
    fingerprint_badge,
    master_detail_split,
    pill,
    scroll_well,
    slot_highlighted_block,
)
from ra2.ui.components.prompt_preview import prompt_preview_panel
from ra2.ui.shell import item_for_key, shell
from ra2.ui.state import TableState, set_table_state, table_state

__all__ = [
    "ACTIVE_PILL",
    "ACTIVE_WORD",
    "CONTENT_GAP",
    "CONTENT_PADDING",
    "EDITING_LABEL",
    "FINGERPRINT_LABEL",
    "FINGERPRINT_NOTE",
    "LOCKED",
    "NEVER_RUN",
    "NEW_VERSION_LABEL",
    "NO_PREVIEW_MESSAGE",
    "NO_VERSIONS_MESSAGE",
    "PAGE_SIZE",
    "PREVIEW_LABEL",
    "RESOLVED_EMPTY_TITLE",
    "SELECTED_KEY",
    "SLOTS_AVAILABLE",
    "SOURCE_HINT",
    "SOURCE_TITLE",
    "VALIDATION_MESSAGES",
    "VERSIONS_TABLE",
    "WELL_HEIGHT_PX",
    "citation_text",
    "copy_on_write_text",
    "register",
    "save_label",
    "selected_version_id",
    "validation_message",
    "versions_label",
]

_ITEM = item_for_key("prompts")

#: The split fills the content column, so the shell's own padding would be a
#: second frame around it — the toolbar is `11px 28px` and the panes carry
#: their own padding (identical to Codelists and Features).
CONTENT_PADDING = "0"
CONTENT_GAP = "0"

#: Per client, never a module global (CLAUDE.md #8).
SELECTED_KEY: Final = "ra2.prompts.selected"
#: This view's entry in `ui/state.py`'s per-client table registry.
VERSIONS_TABLE: Final = "prompts.versions"

#: README §1: "The well is capped at **10 rows (530px)**" — 10 x 53px rows.
PAGE_SIZE: Final = 10
WELL_HEIGHT_PX: Final = 530
#: README §1, Resolved card: "a resolved prompt is long, and that cap is
#: deliberate". The cap itself lives inside `prompt_preview_panel`; this
#: constant is what the empty state matches so the card does not jump height.
RESOLVED_MAX_HEIGHT_PX: Final = 210

# --- copy, verbatim from design/prompt-evaluation/README.md §1 ---------------

PREVIEW_LABEL: Final = "Preview with record 1"
NEW_VERSION_LABEL: Final = "New version"
SLOTS_AVAILABLE: Final = "Slots available"
EDITING_LABEL: Final = "Editing"
FINGERPRINT_LABEL: Final = "Template fingerprint"
FINGERPRINT_NOTE: Final = "Every run stores this alongside the model digest."
SOURCE_TITLE: Final = "Source"
SOURCE_HINT: Final = "plain text · slots in {{ }}"
ACTIVE_PILL: Final = "ACTIVE"
#: The mono qualifier the design sets beside the active version's name.
ACTIVE_WORD: Final = "active"
LOCKED: Final = "locked"
NEVER_RUN: Final = "never run"

#: Undesigned states (README, "Loading / empty / error"): one centred line.
NO_VERSIONS_MESSAGE: Final = "No template yet — create the first version."
NO_SELECTION_MESSAGE: Final = "Select a version to see its source."
RESOLVED_EMPTY_TITLE: Final = "Resolved"
NO_PREVIEW_MESSAGE: Final = (
    "Not previewed yet. “Preview with record 1” expands this template against an "
    "evaluation's feature set, its prompt language and the first record in its scope."
)
NO_PREVIEW_INPUTS_MESSAGE: Final = (
    "Nothing to preview against yet: an evaluation pins the feature set, the prompt "
    "language and the records this template would be resolved against."
)
EDIT_HINT: Final = "Click the source to edit it."
NEW_TEMPLATE_SOURCE: Final = ""

#: `PromptValidationCode` values are stable identifiers; the wording is a
#: rendering table in `ui/` and is asserted on by **code**, never by text
#: (CLAUDE.md, "Findings, not prose").
VALIDATION_MESSAGES: Final[dict[PromptValidationCode, str]] = {
    PromptValidationCode.UNKNOWN_SLOT: "Unknown slot — not one of the three the prompt offers.",
    PromptValidationCode.MISSING_REQUIRED_SLOT: "Required slot missing — add it to the template.",
    PromptValidationCode.MALFORMED_SLOT: "Malformed slot — a slot is written {{ name }} .",
    PromptValidationCode.EMPTY_SOURCE: "A template cannot be empty.",
}

# --- layout, verbatim from the design's inline styles ------------------------

TOOLBAR_STYLE: Final = (
    "flex:none;display:flex;align-items:center;gap:10px;flex-wrap:wrap;"
    "padding:11px 28px;background:var(--surface);border-bottom:1px solid var(--rule);"
)
#: README §1, Toolbar: "**Right group only** — `display:flex; gap:10px;
#: margin-left:auto; flex:none`. There is deliberately **no left chip group**."
RIGHT_GROUP_STYLE: Final = "display:flex;gap:10px;margin-left:auto;flex:none;"
LIST_HEADER_STYLE: Final = (
    "flex:none;height:var(--card-header-h);padding:0 16px;overflow:hidden;"
    "display:flex;align-items:center;justify-content:space-between;gap:10px;"
    "border-bottom:1px solid var(--rule);"
)
ROW_STYLE: Final = (
    "padding:9px 16px;border-bottom:1px solid var(--rule2);display:flex;"
    "justify-content:space-between;align-items:center;gap:10px;width:100%;height:53px;flex-wrap:nowrap;"
    "background:none;border-left:0;border-right:0;border-top:0;text-align:left;cursor:pointer;"
)
ROW_SELECTED_STYLE: Final = (
    "background:var(--accent-soft);border-left:2px solid var(--accent);padding-left:14px;"
)
RNAME_STYLE: Final = "font-size:12.5px;color:var(--ink);"
RSUB_STYLE: Final = "font-family:var(--mono);font-size:10.5px;color:var(--ink3);margin-top:2px;"
STRIP_STYLE: Final = (
    "flex:none;padding:9px 16px;border-top:1px solid var(--rule2);"
    "display:flex;justify-content:space-between;gap:10px;"
)
SLOT_TABLE_STYLE: Final = (
    "flex:none;padding:10px 16px;border-top:1px solid var(--rule2);"
    "display:flex;flex-direction:column;gap:7px;"
)
SLOT_ROW_STYLE: Final = "display:flex;justify-content:space-between;gap:10px;"
DETAIL_STYLE: Final = "display:flex;flex-direction:column;gap:14px;"
EDIT_HEADER_STYLE: Final = (
    "display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;"
)
EDIT_HEADER_RIGHT_STYLE: Final = "text-align:right;flex:1 1 240px;min-width:0;"
#: README, Design Tokens: "two literals already in use" — this is the
#: card-header tint. The header itself is 42px here, not the shared 46px
#: `.card-header`; both sizes are the design's ("42-46px card headers").
CARD_HEADER_42_STYLE: Final = (
    "flex:none;height:42px;padding:0 14px;display:flex;align-items:center;"
    "justify-content:space-between;gap:10px;border-bottom:1px solid var(--rule2);"
    "background:oklch(0.988 0.003 260);"
)
SOURCE_BODY_STYLE: Final = "padding:14px;"
#: README §1, Source card footer: `--warn-soft` behind `oklch(0.40 0.10 72)`.
WARN_FOOTER_STYLE: Final = (
    "flex:none;display:flex;gap:10px;align-items:flex-start;padding:10px 14px;"
    "border-top:1px solid var(--rule);background:var(--warn-soft);"
    "color:oklch(0.40 0.10 72);font-size:11.5px;"
)
VALIDATION_STYLE: Final = (
    "flex:none;display:flex;flex-direction:column;gap:5px;padding:10px 14px;"
    "border-top:1px solid var(--rule);background:var(--danger-soft);"
    "color:var(--danger);font-size:11.5px;"
)
EMPTY_STYLE: Final = "padding:24px 16px;text-align:center;font-size:12.5px;color:var(--ink2);"
TEXTAREA_STYLE: Final = (
    "width:100%;border:none;border-radius:0;padding:14px;font-family:var(--mono);"
    "font-size:12px;line-height:1.75;color:var(--ink);background:var(--surface);"
    "resize:vertical;min-height:240px;outline:none;"
)

#: Lucide `trash`, transcribed from the design file's own inline SVG (the
#: uncited version's 22x22 `--danger` delete button). It lives here rather
#: than in `ui/components/icons.py` because that module is not this branch's
#: to write (CLAUDE.md, the ownership rule); the eight path commands are the
#: design's, not invented.
TRASH: Final = (
    '<path d="M5 7h14"></path><path d="M9 7V5h6v2"></path><path d="M7 7l1 13h8l1-13"></path>'
)


# --- copy builders (presentation only — every number is a service's) ---------


def versions_label(total: int) -> str:
    """The list header's "4 versions"."""
    return f"{total} version" if total == 1 else f"{total} versions"


def citation_text(view: PromptTemplateView) -> str:
    """The design's `.rsub`: "2026-09-04 14:22 · cited by 3 runs"."""
    created = view.created_at.strftime("%Y-%m-%d %H:%M")
    if view.cited_by_run_count == 0:
        return f"{created} · {NEVER_RUN}"
    runs = "run" if view.cited_by_run_count == 1 else "runs"
    return f"{created} · cited by {view.cited_by_run_count} {runs}"


def save_label(next_version: int) -> str:
    """The primary button's "Save as v5" — the version the *store* will
    assign, handed to this view by the service, never counted here."""
    return f"Save as v{next_version}"


def copy_on_write_text(*, current_version: int, next_version: int, cited_by: int) -> str:
    """The `--warn-soft` footer, verbatim for the design's own fixture.

    The zero-citation case is not drawn (every version in the mock is cited or
    never run); it says the same thing without naming runs that do not exist.
    """
    head = f"Saving creates v{next_version}. v{current_version} stays as it is"
    if cited_by == 0:
        return f"{head} — every version is kept byte-identical, so a run can always resolve it."
    runs = "run" if cited_by == 1 else "runs"
    return (
        f"{head} — the {cited_by} {runs} citing it must keep resolving to the exact text they used."
    )


def validation_message(error: PromptValidationError) -> str:
    """One refused-save line. The **code** carries the meaning; this is the
    one place its wording lives."""
    text = VALIDATION_MESSAGES[error.code]
    return f"{text} ({error.slot})" if error.slot else text


def selected_version_id() -> str | None:
    """This client's selected version, or `None` for "the active one"."""
    value = app.storage.client.get(SELECTED_KEY)
    return value if isinstance(value, str) else None


def register(services: Services) -> None:
    """Register `/prompts`."""

    @ui.page(_ITEM.path)
    async def _page() -> None:
        page = _PromptsPage(services)
        await page.build()


#: The language a preview resolves in when no evaluation has chosen one
#: yet. `evaluation.prompt_language` is the real home for this (§15 F10);
#: this is only the fallback for the no-evaluation-yet preview path, and it
#: matches `evaluation_service`'s own default so the two never disagree.
_PREVIEW_FALLBACK_LANGUAGE: Final = "de"

class _PromptsPage:
    """One client's Prompts view.

    Built inside the page function, so every browser tab gets its own instance
    and nothing is shared between them (CLAUDE.md #8). It holds only what it
    last read from a service, plus the unsaved edit buffer.
    """

    def __init__(self, services: Services) -> None:
        self._services = services
        self._versions: tuple[PromptTemplateView, ...] = ()
        self._slots: tuple[SlotView, ...] = ()
        #: The unsaved source. `None` means "not editing" — the Source card
        #: renders the selected version's own text instead.
        self._draft: str | None = None
        #: The last refused save's typed errors, cleared on every edit.
        self._errors: tuple[PromptValidationError, ...] = ()
        self._preview: ResolvedPromptView | None = None
        self._preview_note: str = NO_PREVIEW_MESSAGE
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
                    ui.element("div").props('data-testid="prompts-toolbar"').style(TOOLBAR_STYLE)
                )
                list_pane, detail_pane = master_detail_split(detail_extra=DETAIL_STYLE)
                self._list_slot = list_pane
                self._detail_slot = detail_pane
        await self.reload()

    async def reload(self) -> None:
        """Re-read everything this view shows, then redraw.

        One place reads, so no handler has to work out which half of the page
        its action invalidated — `_CodelistsPage.reload`'s shape.
        """
        self._versions = tuple(await self._services.prompt.list_versions())
        self._slots = tuple(await self._services.prompt.slots())
        self._sync_selection()
        self._sync_page()
        self._render()

    def _sync_page(self) -> None:
        """Step back off a page the list no longer reaches.

        Deleting the last row of page 2 otherwise leaves the well empty with
        the pagination row still reading "0–0 of N" — the same thing a paged
        table does everywhere else when its data shrinks under it.
        """
        state = self._table_state()
        last_page = max(1, -(-len(self._versions) // state.page_size))
        if state.page > last_page:
            set_table_state(
                VERSIONS_TABLE,
                TableState(state.sort_key, state.sort_dir, last_page, state.page_size),
            )

    def _sync_selection(self) -> None:
        """Drop a selection that no longer exists (deleted, or never set).

        Never rebuilds `self._draft` for a survivor: an unsaved edit outlives
        a reload of the list around it.
        """
        if not self._versions:
            app.storage.client[SELECTED_KEY] = None
            return
        selected = selected_version_id()
        if selected is not None and any(
            str(v.prompt_template_id) == selected for v in self._versions
        ):
            return
        app.storage.client[SELECTED_KEY] = str(self._default_version().prompt_template_id)

    def _default_version(self) -> PromptTemplateView:
        """The board opens on the **active** version — "the one new
        evaluations default to" — falling back to the newest row the service
        returned when nothing has ever been activated."""
        return next((v for v in self._versions if v.is_active), self._versions[0])

    # --- the rows this render is working from ------------------------------

    def _table_state(self) -> TableState:
        return table_state(
            VERSIONS_TABLE, sort_key="version", sort_dir=SortDir.DESC, page_size=PAGE_SIZE
        )

    def _page_rows(self) -> tuple[PromptTemplateView, ...]:
        """The slice of the (already newest-first) list this page draws. See
        the module docstring for why the slicing happens here."""
        state = self._table_state()
        start = (state.page - 1) * state.page_size
        return self._versions[start : start + state.page_size]

    def _selected(self) -> PromptTemplateView | None:
        selected = selected_version_id()
        return next((v for v in self._versions if str(v.prompt_template_id) == selected), None)

    def _next_version(self) -> int:
        """The integer the store will assign the next save.

        `PromptRepository.next_version()` is `max(version) + 1` over the whole
        table and the service is what calls it; this reads the same maximum
        off the rows the service just handed over so the button can be
        *labelled* before the save happens — the label is a prediction, the
        version is not this view's to choose.
        """
        return max((v.version for v in self._versions), default=0) + 1

    # --- rendering ---------------------------------------------------------

    def _render(self) -> None:
        # All three are built in `build()`, before anything can render.
        assert self._toolbar is not None
        assert self._list_slot is not None
        assert self._detail_slot is not None
        self._toolbar.clear()
        with self._toolbar:
            self._render_toolbar()
        self._list_slot.clear()
        with self._list_slot:
            self._render_version_list()
        self._detail_slot.clear()
        with self._detail_slot:
            self._render_editor()

    # --- toolbar -----------------------------------------------------------

    def _render_toolbar(self) -> None:
        """Right group only (README §1, Toolbar)."""
        with ui.element("div").style(RIGHT_GROUP_STYLE):
            self._button(
                PREVIEW_LABEL,
                primary=False,
                testid="preview-template",
                on_click=self._preview_with_record_1,
                disabled=self._selected() is None,
            )
            self._button(
                save_label(self._next_version()),
                primary=True,
                testid="save-template",
                on_click=self._save_as_next_version,
                disabled=self._selected() is None and self._draft is None,
            )

    def _button(
        self,
        text: str,
        *,
        primary: bool,
        testid: str,
        on_click: Callable[[], Awaitable[None]],
        disabled: bool = False,
        icon: str | None = None,
    ) -> Element:
        button = (
            ui.element("button")
            .classes(f"btn {'primary' if primary else 'secondary'}")
            .props(f'type="button" data-testid="{testid}"')
            .mark(testid)
        )
        if disabled:
            button.props("disabled").style("opacity:.45;cursor:default;")
        else:
            button.on("click", cast("Callable[[], None]", on_click))
        with button:
            if icon is not None:
                ui.html(svg(icon, size=12, stroke=2.2), tag="span", sanitize=False).style(
                    "display:inline-flex;"
                )
            ui.label(text)
        return button

    # --- the version list (master) -----------------------------------------

    def _render_version_list(self) -> None:
        with ui.element("div").style(LIST_HEADER_STYLE):
            ui.label(versions_label(len(self._versions))).classes("lbl").props(
                'data-testid="versions-count"'
            ).mark("versions-count").style("min-width:0;overflow:hidden;text-overflow:ellipsis;")
            self._button(
                NEW_VERSION_LABEL,
                primary=False,
                testid="new-version",
                on_click=self._start_new_version,
                icon=PLUS,
            ).style("gap:5px;flex:none;padding:6px 13px;")
        rows = self._page_rows()
        with scroll_well(max_height_px=WELL_HEIGHT_PX, extra="flex:1;"):
            if not rows:
                ui.label(NO_VERSIONS_MESSAGE).props('data-testid="list-empty"').mark(
                    "list-empty"
                ).style(EMPTY_STYLE)
            for view in rows:
                self._version_row(view)
        pagination_row(
            state=self._table_state(),
            total=len(self._versions),
            shown=len(rows),
            on_page=_sync(self._page),
            on_page_size=_sync(self._page_size),
        )
        self._slots_strip()
        self._slot_table()

    def _version_row(self, view: PromptTemplateView) -> None:
        """One `.row`, with exactly one of the design's three right-hand
        markers plus the selected-row treatment.

        The precedence is the design's own reading: the **active** version
        wears the ACTIVE pill; any other version a run cites is `locked`
        (`deletable` is false, so there is no action to offer); a version no
        run cites offers the delete button. All three facts are
        `PromptTemplateView` fields — none is derived here.
        """
        selected = str(view.prompt_template_id) == selected_version_id()
        marker = "active" if view.is_active else ("deletable" if view.deletable else "locked")
        row = (
            ui.element("button")
            .props(
                f'type="button" data-testid="version-row" data-version="{view.version}" '
                f'data-marker="{marker}" aria-current="{"true" if selected else "false"}"'
            )
            .mark("version-row", f"version-v{view.version}")
            .style(ROW_STYLE + (ROW_SELECTED_STYLE if selected else ""))
        )
        row.on("click", _sync(lambda v=view: self._select(v)))
        with row:
            with ui.element("div").style("min-width:0;"):
                with ui.element("div").style(
                    RNAME_STYLE + ("font-weight:600;" if selected else "")
                ):
                    ui.label(f"v{view.version}").props('data-testid="version-name"').mark(
                        "version-name"
                    ).style("display:inline;")
                    if view.is_active:
                        ui.label(ACTIVE_WORD).classes("mono").props(
                            'data-testid="active-word"'
                        ).style("display:inline;font-weight:500;color:var(--ink3);margin-left:5px;")
                ui.label(citation_text(view)).props('data-testid="version-sub"').mark(
                    "version-sub"
                ).style(RSUB_STYLE)
            with ui.element("div").style("display:flex;gap:6px;flex:none;align-items:center;"):
                self._row_marker(view, marker)

    def _row_marker(self, view: PromptTemplateView, marker: str) -> None:
        if marker == "active":
            pill(ACTIVE_PILL, tone="ok").props('data-testid="active-pill"').mark(
                "active-pill"
            ).style("flex:none;")
            return
        if marker == "locked":
            ui.label(LOCKED).classes("mono").props('data-testid="locked"').mark("locked").style(
                "font-size:11px;color:var(--ink3);flex:none;"
            )
            return
        icon_button(
            TRASH,
            label=f"Delete v{view.version}",
            size=22,
            glyph=12,
            stroke=1.9,
            on_click=_sync(lambda: self._delete(view.prompt_template_id)),
        ).props('data-testid="delete-version"').style("color:var(--danger);")

    def _slots_strip(self) -> None:
        """ "Slots available" + a mono count — the closed catalogue's size, as
        `PromptService.slots()` returned it."""
        with ui.element("div").style(STRIP_STYLE):
            ui.label(SLOTS_AVAILABLE).classes("lbl")
            ui.label(format_count(len(self._slots))).classes("mono").props(
                'data-testid="slot-count"'
            ).mark("slot-count").style("font-size:11px;color:var(--ink2);")

    def _slot_table(self) -> None:
        """One row per slot: the literal token, and what it resolves to."""
        with ui.element("div").props('data-testid="slot-table"').style(SLOT_TABLE_STYLE):
            for slot in self._slots:
                with (
                    ui.element("div")
                    .props(f'data-testid="slot-row" data-slot="{slot.name.value}"')
                    .mark("slot-row")
                    .style(SLOT_ROW_STYLE)
                ):
                    ui.label(slot.token).classes("mono").style("font-size:11.5px;")
                    ui.label(slot.resolves_to).style("font-size:11px;color:var(--ink3);")

    # --- the editor (detail) -----------------------------------------------

    def _render_editor(self) -> None:
        selected = self._selected()
        if selected is None and self._draft is None:
            ui.label(NO_SELECTION_MESSAGE).props('data-testid="detail-empty"').mark(
                "detail-empty"
            ).style(EMPTY_STYLE)
            return
        self._editor_header(selected)
        self._source_card(selected)
        self._resolved_card()

    def _editor_header(self, selected: PromptTemplateView | None) -> None:
        with ui.element("div").style(EDIT_HEADER_STYLE):
            with ui.element("div").style("min-width:0;"):
                ui.label(EDITING_LABEL).classes("lbl")
                title = (
                    f"Template v{selected.version}"
                    if selected is not None
                    else f"Template v{self._next_version()}"
                )
                with (
                    ui.element("h2")
                    .props('data-testid="editing-title"')
                    .mark("editing-title")
                    .style("margin:3px 0 0;font-size:16px;font-weight:600;")
                ):
                    ui.label(title)
            with ui.element("div").style(EDIT_HEADER_RIGHT_STYLE):
                ui.label(FINGERPRINT_LABEL).classes("lbl")
                # `fingerprint_badge` is the kit's one fingerprint renderer
                # (H5 / phase 2). It clamps to 6 characters where the design
                # draws 10 — a display clamp either way, and one truncation
                # rule across the app beats two.
                fingerprint_badge(selected.fingerprint if selected is not None else "").style(
                    "font-size:12px;color:var(--ink2);margin-top:3px;display:block;"
                )
                ui.label(FINGERPRINT_NOTE).style("font-size:11px;color:var(--ink3);margin-top:2px;")

    def _source_card(self, selected: PromptTemplateView | None) -> None:
        source = self._draft if self._draft is not None else (selected.source if selected else "")
        with card(extra="overflow:hidden;"):
            with ui.element("div").props('data-testid="source-header"').style(CARD_HEADER_42_STYLE):
                ui.label(SOURCE_TITLE).classes("lbl")
                ui.label(SOURCE_HINT).classes("mono").style("font-size:10.5px;color:var(--ink3);")
            if self._draft is None:
                self._source_readout(source)
            else:
                self._source_editor(source)
            if self._errors:
                self._validation_errors()
            if selected is not None:
                self._copy_on_write_footer(selected)

    def _source_readout(self, source: str) -> None:
        """The design's Source body: mono, `pre-wrap`, every `{{slot}}` picked
        out inline. Clicking it opens the editor (see the module docstring)."""
        body = (
            ui.element("div")
            .props(f'data-testid="source-body" role="button" tabindex="0" title="{EDIT_HINT}"')
            .mark("source-body")
            .style(SOURCE_BODY_STYLE + "cursor:text;")
        )
        body.on("click", lambda _: self._start_editing(source))
        with body:
            slot_highlighted_block(source)

    def _source_editor(self, source: str) -> None:
        element = (
            ui.element("textarea")
            .props('data-testid="source-editor" rows="16" aria-label="Template source"')
            .mark("source-editor")
            .style(TEXTAREA_STYLE)
        )
        # Through the props **dict**, never the props string: the string is
        # parsed, so a template carrying a newline (every template does)
        # breaks the parse and the page silently never renders. The dict is
        # serialised as JSON and round-trips any text byte-for-byte — the same
        # reasoning `features_view._textarea` documents.
        element.props["value"] = source
        element.on(
            "input",
            lambda event: self._on_source_input(str(event.args)),
            js_handler="(e) => emit(e.target.value)",
        )

    def _validation_errors(self) -> None:
        """The refused save, rendered where the text that caused it is.

        Each line carries its `PromptValidationCode` in the DOM: the code is
        the stable identifier, the words are this file's rendering table.
        """
        with ui.element("div").props('data-testid="validation-errors"').style(VALIDATION_STYLE):
            for error in self._errors:
                ui.label(validation_message(error)).props(
                    f'data-testid="validation-error" data-code="{error.code.value}"'
                ).mark("validation-error")

    def _copy_on_write_footer(self, selected: PromptTemplateView) -> None:
        with (
            ui.element("div")
            .props('data-testid="cow-footer"')
            .mark("cow-footer")
            .style(WARN_FOOTER_STYLE)
        ):
            ui.html(svg(INFO, size=14, stroke=1.8), tag="span", sanitize=False).style(
                "flex:none;margin-top:1px;display:inline-flex;"
            )
            ui.label(
                copy_on_write_text(
                    current_version=selected.version,
                    next_version=self._next_version(),
                    cited_by=selected.cited_by_run_count,
                )
            ).style("flex:1;min-width:0;")

    def _resolved_card(self) -> None:
        """L3's shared panel, **placed** here (C4). With nothing resolved yet,
        the card renders its own undesigned empty state at the same height so
        the column does not jump when a preview arrives."""
        if self._preview is not None:
            prompt_preview_panel(resolved=self._preview)
            return
        with card(extra="overflow:hidden;"):
            with (
                ui.element("div").props('data-testid="resolved-header"').style(CARD_HEADER_42_STYLE)
            ):
                ui.label(RESOLVED_EMPTY_TITLE).classes("lbl")
            ui.label(self._preview_note).props('data-testid="resolved-empty"').mark(
                "resolved-empty"
            ).style(
                f"padding:14px;font-size:11.5px;color:var(--ink3);"
                f"max-height:{RESOLVED_MAX_HEIGHT_PX}px;overflow:auto;"
            )

    # --- selection and paging ----------------------------------------------

    async def _select(self, view: PromptTemplateView) -> None:
        """Selecting a version loads it into the editor (README,
        Interactions), discarding an unsaved draft — an explicit click on
        another version is an explicit abandonment of the edit."""
        app.storage.client[SELECTED_KEY] = str(view.prompt_template_id)
        self._draft = None
        self._errors = ()
        self._preview = None
        self._preview_note = NO_PREVIEW_MESSAGE
        self._render()

    async def _page(self, page: int) -> None:
        current = self._table_state()
        set_table_state(
            VERSIONS_TABLE, TableState(current.sort_key, current.sort_dir, page, current.page_size)
        )
        self._render()

    async def _page_size(self, size: int) -> None:
        current = self._table_state()
        set_table_state(VERSIONS_TABLE, TableState(current.sort_key, current.sort_dir, 1, size))
        self._render()

    # --- editing -----------------------------------------------------------

    def _start_editing(self, source: str) -> None:
        self._draft = source
        self._errors = ()
        self._render()

    def _on_source_input(self, value: str) -> None:
        """Keystrokes update the buffer only. Nothing re-renders: re-rendering
        a `<textarea>` under the caret is how a cursor ends up at position 0
        on every keypress."""
        self._draft = value

    async def _start_new_version(self) -> None:
        """ "New version" seeds the editor from the selected version and
        writes nothing — under copy-on-write, the write *is* "Save as vN"."""
        selected = self._selected()
        self._start_editing(selected.source if selected is not None else NEW_TEMPLATE_SOURCE)

    # --- mutating actions --------------------------------------------------

    async def _save_as_next_version(self) -> None:
        """Copy-on-write, then activate (see the module docstring).

        A refused save renders the service's typed errors and **writes
        nothing** — the draft stays in the editor, where it can be fixed.
        """
        selected = self._selected()
        source = self._draft if self._draft is not None else (selected.source if selected else "")
        try:
            saved = await self._services.prompt.save_as_next_version(source)
        except PromptTemplateInvalidError as exc:
            self._errors = exc.validation_errors
            self._render()
            return
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        try:
            await self._services.prompt.activate(saved.prompt_template_id)
        except ServiceError as exc:  # pragma: no cover - just-created id exists
            ui.notify(str(exc), type="negative")
        # Written before `reload()` clears the slot this handler's own button
        # lives in: any `app.storage.client` write resolves the ambient
        # client through that slot, and once it is gone NiceGUI has nothing
        # left to resolve it through (the trap `features_view._save_draft`
        # documents at length).
        app.storage.client[SELECTED_KEY] = str(saved.prompt_template_id)
        self._draft = None
        self._errors = ()
        self._preview = None
        self._preview_note = NO_PREVIEW_MESSAGE
        await self.reload()

    async def _delete(self, prompt_template_id: PromptTemplateId) -> None:
        """Only a version no run cites can be deleted; the service is what
        refuses the others, and its refusal is what reaches the analyst."""
        try:
            await self._services.prompt.delete(prompt_template_id)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        if selected_version_id() == str(prompt_template_id):
            app.storage.client[SELECTED_KEY] = None
            self._draft = None
        await self.reload()

    async def _preview_with_record_1(self) -> None:
        """Resolve the selected version against a real feature set and a real
        record — **no model call** (C4). See the module docstring for why the
        inputs come from the most recent evaluation."""
        selected = self._selected()
        if selected is None:
            return
        inputs = await self._preview_inputs()
        if inputs is None:
            self._preview = None
            self._preview_note = NO_PREVIEW_INPUTS_MESSAGE
            self._render()
            return
        feature_config_id, record_id, language = inputs
        try:
            self._preview = await self._services.prompt.preview(
                selected.prompt_template_id, feature_config_id, record_id, language=language
            )
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        self._render()

    async def _preview_inputs(self) -> tuple[FeatureConfigId, RecordId, str] | None:
        """The feature set, the record and the prompt language to resolve
        against — the design's "Preview with record 1".

        **An evaluation first, the newest corpus second.** When one exists,
        all three come from a single evaluation, which is what keeps them
        consistent: `PromptService.preview` resolves enum labels from *the
        record's own corpus*, so a feature set chosen independently of the
        record could be previewed against labels from a different corpus
        entirely. That is the more faithful preview, so it wins where it is
        available.

        With no evaluation yet, "record 1" is the newest corpus's first
        record by id (`CorpusService.first_record`, added by L1's accepted
        amendment) and the newest feature set — which is what the design
        actually describes, and what makes Preview work on a fresh install
        instead of showing an empty state for a reason the analyst cannot
        see.
        """
        for draft in await self._services.evaluation.list_evaluations():
            scope = await self._services.evaluation.record_scope(draft.evaluation_id)
            if scope:
                return draft.feature_config_id, scope[0], draft.prompt_language

        configs = await self._services.feature.list_configs()
        if not configs:
            return None
        corpora = await self._services.corpus.list_corpora()
        for corpus in corpora.items:
            record_id = await self._services.corpus.first_record(corpus.corpus_id)
            if record_id is not None:
                return configs[0].feature_config_id, record_id, _PREVIEW_FALLBACK_LANGUAGE
        return None


def _sync[**P](action: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    """Adapt an async handler to a sync callback type — the identical typing
    formality `census_view._sync` documents."""
    return cast("Callable[P, None]", action)

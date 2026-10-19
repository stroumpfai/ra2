"""Scrubbing view — "Rules and name lists that replace personal data in the
narratives when a corpus is frozen" (sw-design.md §19, `SD62`–`SD66`).

**There is no design for this screen yet** (`plan-text-scrubbing.md` §7.1).
It is built from the existing tokens and primitives only, as six stacked
cards in the order an analyst works through them:

1. **Files**: the four kinds of file a rule set can hold, each with its file,
   its counts and an import / remove action.
2. **Regex rules**: every rule the next freeze runs, mandatory first, with
   its pattern and its examples verbatim.
3. **Name lists**: the active lists, searched the way the scrubber compares.
4. **Protected strings**: what the whole scrubber must leave alone.
5. **Try a sentence**: the active rules over one sentence, stored nowhere.
6. **Versions**: every rule-set version and the corpora frozen under it.

The three rules every view keeps hold here too:

1. **No business logic** (§8.1.1). What is active, what a rule matched, why
   an import was refused: every fact is a `ScrubService` read model. The
   only decisions here are which words to say (`ERROR_LABELS`,
   `NOTICE_LABELS`, `KIND_LABELS`, the one wording table each).
2. **No module-level mutable state** (§12.8). The list being searched, the
   query, its page and the sentence being tried live in `app.storage.client`
   under `STATE_KEY`.
3. **In-process services** (§1): no call to this app's own API.

**What the screen never shows: record text.** A list entry is public data,
and the sentence tester shows back only what the analyst typed. The screen
reads no narrative, so it cannot display one.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Final, cast

from nicegui import app, ui
from nicegui.element import Element
from nicegui.events import MultiUploadEventArguments

from ra2.domain.scrub import ListKind, ListNoticeCode, ScrubImportError, ScrubImportErrorCode
from ra2.services.container import Services
from ra2.services.errors import ScrubImportRefusedError, ServiceError
from ra2.services.readmodels import (
    Page,
    ScrubEntryView,
    ScrubListView,
    ScrubRulesetView,
    ScrubRuleView,
    ScrubTryView,
    ScrubVersionView,
)
from ra2.ui.components import ColumnSpec, card, data_table, dialog_card, format_count
from ra2.ui.components.primitives import (
    card_header,
    data_props,
    fingerprint_badge,
    footnote,
    format_local,
    pagination_row,
    segmented_control,
)
from ra2.ui.components.refusal import refusal_text
from ra2.ui.shell import item_for_key, shell
from ra2.ui.state import TableState

__all__ = [
    "ENTRY_KINDS",
    "ERROR_LABELS",
    "KIND_HINTS",
    "KIND_LABELS",
    "MANDATORY_ONLY",
    "NOTHING_STORED",
    "NOTICE_LABELS",
    "NO_FILE",
    "NO_VERSIONS_MESSAGE",
    "REFUSED_TITLE",
    "SCRUBBED_NOT_ANONYMISED",
    "SOURCE_LABELS",
    "STATE_KEY",
    "TRY_BUTTON",
    "ScrubbingState",
    "error_text",
    "register",
    "scrubbing_state",
]

_ITEM = item_for_key("scrubbing")

#: Per client, never a module global (§12.8).
STATE_KEY: Final = "ra2.scrubbing.state"

#: How many entries a page of the list search shows.
ENTRY_PAGE_SIZE: Final = 25

# --- the wording tables: stable codes in, words out --------------------------

KIND_LABELS: Final[dict[ListKind, str]] = {
    ListKind.REGEX: "Rule file",
    ListKind.FIRSTNAME: "First names",
    ListKind.LASTNAME: "Last names",
    ListKind.WHITELIST: "Whitelist",
}

#: What each kind of file is, said once beside its import action.
KIND_HINTS: Final[dict[ListKind, str]] = {
    ListKind.REGEX: "TOML: id, tag, pattern, must_match, optional must_not_match",
    ListKind.FIRSTNAME: "UTF-8, one name per line, tagged <Firstname_n>",
    ListKind.LASTNAME: "UTF-8, one name per line, tagged <Lastname_n>",
    ListKind.WHITELIST: "UTF-8, one word per line, never replaced as a name",
}

#: The lists the entry search can page through, in screen order.
ENTRY_KINDS: Final[tuple[ListKind, ...]] = (
    ListKind.FIRSTNAME,
    ListKind.LASTNAME,
    ListKind.WHITELIST,
)

SOURCE_LABELS: Final[dict[str, str]] = {
    "mandatory": "mandatory",
    "imported": "imported",
    "list": "name list",
}

ERROR_LABELS: Final[dict[ScrubImportErrorCode, str]] = {
    ScrubImportErrorCode.NOT_UTF8: "The file is not UTF-8",
    ScrubImportErrorCode.TOML_INVALID: "The rule file is not valid TOML",
    ScrubImportErrorCode.UNKNOWN_FIELD: "A field the rule file may not have",
    ScrubImportErrorCode.FIELD_MISSING: "A required field is missing",
    ScrubImportErrorCode.FIELD_INVALID: "A field has the wrong type",
    ScrubImportErrorCode.ID_MALFORMED: "A rule id is not lower-case letters, digits and hyphens",
    ScrubImportErrorCode.DUPLICATE_ID: "Two rules share an id",
    ScrubImportErrorCode.ID_RESERVED: "The id belongs to a mandatory rule or a name list",
    ScrubImportErrorCode.TAG_MALFORMED: "A tag is not one capitalised word of letters",
    ScrubImportErrorCode.TAG_RESERVED: "Firstname, Lastname and Name are the name lists' tags",
    ScrubImportErrorCode.PATTERN_INVALID: "A pattern does not compile",
    ScrubImportErrorCode.PATTERN_EMPTY_MATCH: "A pattern can match nothing at all",
    ScrubImportErrorCode.PATTERN_TOO_SLOW: "A pattern backtracks too long on hard input",
    ScrubImportErrorCode.NO_MUST_MATCH: "A rule has no must_match example",
    ScrubImportErrorCode.MUST_MATCH_FAILED: "A must_match example is not matched in full",
    ScrubImportErrorCode.MUST_NOT_MATCH_HIT: "A must_not_match example is matched",
    ScrubImportErrorCode.PROTECTED_ALTERED: "A protected string would be changed",
    ScrubImportErrorCode.LIST_EMPTY: "The list has no usable entry",
}

NOTICE_LABELS: Final[dict[ListNoticeCode, str]] = {
    ListNoticeCode.BOM: "byte-order mark removed",
    ListNoticeCode.CRLF: "CRLF line endings",
    ListNoticeCode.BLANK_LINES: "blank lines skipped",
    ListNoticeCode.COMMENT_LINES: "comment lines skipped",
    ListNoticeCode.DUPLICATES: "duplicates skipped",
    ListNoticeCode.TOO_SHORT: "shorter than 3 letters, skipped",
    ListNoticeCode.NO_LETTERS: "no letters, skipped",
}

NO_FILE: Final = "none imported"
MANDATORY_ONLY: Final = "Nothing imported: only the mandatory rules run"
NO_VERSIONS_MESSAGE: Final = "No rule set has been imported yet."
REFUSED_TITLE: Final = "Import refused — nothing was changed"
TRY_BUTTON: Final = "Scrub"
NOTHING_STORED: Final = "Uses the active rules. Nothing typed here is stored or logged."
#: `SD65`: the one sentence that must not be lost from this screen.
SCRUBBED_NOT_ANONYMISED: Final = (
    "Scrubbed is not anonymised. A name list misses names that are not on it, inflected "
    "forms and nicknames, and addresses are not attempted: read every narrative as sensitive."
)
PROTECTED_NOTE: Final = (
    "The whole rule set must leave these exactly as they are. An import that would change "
    "one is refused; the whitelist is how a name-list collision is resolved."
)

_CODE_BLOCK_STYLE: Final = (
    "font-family:var(--mono);font-size:12px;white-space:pre-wrap;word-break:break-word;"
    "background:var(--bg);border:1px solid var(--rule);border-radius:3px;padding:10px 12px;"
)
_TEXTAREA_STYLE: Final = (
    "width:100%;min-height:72px;resize:vertical;box-sizing:border-box;"
    "font-family:var(--mono);font-size:12px;color:var(--ink);background:var(--surface);"
    "border:1px solid var(--rule);border-radius:3px;padding:8px 10px;"
)
_INPUT_STYLE: Final = (
    "width:220px;box-sizing:border-box;font-size:12.5px;color:var(--ink);"
    "background:var(--surface);border:1px solid var(--rule);border-radius:3px;padding:5px 8px;"
)
_NOTE_STYLE: Final = "padding:10px 14px;font-size:12px;color:var(--ink2);white-space:normal;"


@dataclass(slots=True)
class ScrubbingState:
    """This client's search and sentence. Never a module global (§12.8)."""

    entry_kind: str = ListKind.LASTNAME.value
    query: str = ""
    page: int = 1
    sentence: str = ""


def scrubbing_state() -> ScrubbingState:
    state: ScrubbingState = app.storage.client.setdefault(STATE_KEY, ScrubbingState())
    return state


def _store(changed: ScrubbingState) -> None:
    app.storage.client[STATE_KEY] = changed


def error_text(error: ScrubImportError) -> str:
    """One refusal, worded: the label, then which rule and what, from
    `detail`. The code itself rides on the element (`data-code`)."""
    parts = [ERROR_LABELS[error.code]]
    if error.rule_id:
        parts.append(f"rule {error.rule_id}")
    parts.extend(f"{key}: {value}" for key, value in sorted(error.detail.items()))
    return " · ".join(parts)


def register(services: Services) -> None:
    @ui.page(_ITEM.path)
    async def _page() -> None:
        page = _ScrubbingPage(services)
        page.frame()
        # SD55: the frame goes to the browser now and the reads fill it over
        # the websocket, so the nav answers at once whatever the lists cost.
        await ui.context.client.connected()
        await page.reload()


class _ScrubbingPage:
    """One client's Scrubbing view, built inside the page function so no two
    tabs share an instance (§12.8). Holds only what it last read."""

    def __init__(self, services: Services) -> None:
        self._services = services
        self._active: ScrubRulesetView | None = None
        self._versions: tuple[ScrubVersionView, ...] = ()
        self._entries: Page[ScrubEntryView] | None = None
        self._tried: ScrubTryView | None = None
        self._dialog: ui.dialog | None = None
        self._root: Element | None = None
        self._upper: Element | None = None
        self._protected_slot: Element | None = None
        self._kind_slot: Element | None = None
        self._entries_slot: Element | None = None
        self._try_slot: Element | None = None
        self._editor: Element | None = None
        self._versions_slot: Element | None = None

    def frame(self) -> None:
        """Every card, empty: nothing here waits on a read. `data-loading`
        stays `true` until the first `reload` has drawn what it read."""
        data_dir_view = self._services.lifecycle.data_dir()
        with shell(
            title=_ITEM.title,
            description=_ITEM.description,
            active=_ITEM.key,
            data_dir=data_dir_view.data_dir,
            database_replaced=data_dir_view.database_replaced,
        ):
            self._root = (
                ui.element("div")
                .props('data-testid="scrubbing-page" data-loading="true"')
                .style("display:flex;flex-direction:column;gap:16px;min-width:0;")
            )
            with self._root:
                self._upper = ui.element("div").style(
                    "display:flex;flex-direction:column;gap:16px;min-width:0;"
                )
                self._entries_card()
                self._protected_slot = ui.element("div")
                self._try_card()
                self._versions_slot = ui.element("div")

    async def reload(self) -> None:
        """Re-read everything, then redraw what it changes. The search box and
        the sentence box are drawn once, so typing never loses focus."""
        self._active = await self._services.scrub.active()
        self._versions = tuple(await self._services.scrub.versions())
        await self._reload_entries()
        self._render_upper()
        self._render_protected()
        self._render_versions()
        if self._root is not None:
            self._root.props('data-loading="false"')

    async def _reload_entries(self) -> None:
        state = scrubbing_state()
        self._entries = await self._services.scrub.entries(
            ListKind(state.entry_kind),
            query=state.query,
            page=state.page,
            page_size=ENTRY_PAGE_SIZE,
        )
        self._render_entries()

    # --- 1-2. files and rules -------------------------------------------------

    def _render_upper(self) -> None:
        assert self._upper is not None and self._active is not None
        self._upper.clear()
        with self._upper:
            self._files_card(self._active)
            self._rules_card(self._active)

    def _files_card(self, active: ScrubRulesetView) -> None:
        by_kind = {lst.kind: lst for lst in active.lists}
        with card().props('data-testid="scrub-files"'):
            with card_header(
                title="Rule set", count=self._version_line(active), count_class="ink2"
            ):
                fingerprint_badge(active.fingerprint)
            with ui.element("div").style("display:flex;flex-direction:column;"):
                for kind in ListKind:
                    self._file_row(kind, by_kind.get(kind.value))
            footnote(SCRUBBED_NOT_ANONYMISED, tone="info")

    @staticmethod
    def _version_line(active: ScrubRulesetView) -> str:
        if active.version is None or active.created_at is None:
            return MANDATORY_ONLY
        return (
            f"v{active.version} · active since "
            f"{format_local(active.created_at, '%Y-%m-%d %H:%M')} · "
            f"mandatory rules v{active.mandatory_version}"
        )

    def _file_row(self, kind: ListKind, current: ScrubListView | None) -> None:
        row = (
            ui.element("div")
            .props(f'data-testid="scrub-file-row" data-kind="{kind.value}"')
            .mark("scrub-file-row")
            .style(
                "display:flex;align-items:center;gap:14px;padding:10px 14px;"
                "border-top:1px solid var(--rule2);min-width:0;"
            )
        )
        with row:
            with ui.element("div").style("width:120px;flex:none;"):
                ui.label(KIND_LABELS[kind]).style("font-weight:500;font-size:12.5px;")
            with ui.element("div").style("flex:1;min-width:0;"):
                if current is None:
                    ui.label(NO_FILE).classes("ink3").props('data-testid="scrub-file-none"').style(
                        "font-size:12px;"
                    )
                else:
                    with ui.element("div").style("display:flex;gap:10px;align-items:baseline;"):
                        ui.label(current.filename).classes("mono").props(
                            'data-testid="scrub-file-name"'
                        ).style("font-size:12px;overflow:hidden;text-overflow:ellipsis;")
                        ui.label(_entries_label(kind, current.entry_count)).classes(
                            "mono ink2"
                        ).props('data-testid="scrub-file-count"').style("font-size:11.5px;")
                        ui.label(current.sha256[:8]).classes("mono ink3").style("font-size:11px;")
                    if current.notices:
                        ui.label(_notices_line(current)).classes("ink3").props(
                            'data-testid="scrub-file-notices"'
                        ).style("font-size:11.5px;margin-top:2px;white-space:normal;")
                ui.label(KIND_HINTS[kind]).classes("ink3").style("font-size:11px;margin-top:2px;")
            with ui.element("div").style("display:flex;gap:6px;flex:none;"):
                self._action_button(
                    "Import",
                    testid=f"scrub-import-{kind.value}",
                    primary=False,
                    on_click=lambda: self._open_import(kind),
                )
                if current is not None:
                    self._action_button(
                        "Remove",
                        testid=f"scrub-remove-{kind.value}",
                        primary=False,
                        on_click=lambda: self._remove(kind),
                    )

    @staticmethod
    def _action_button(
        label: str, *, testid: str, primary: bool, on_click: Callable[[], object]
    ) -> Element:
        button = (
            ui.element("button")
            .classes("btn primary" if primary else "btn secondary")
            .props(f'type="button" data-testid="{testid}"')
            .mark(testid)
        )
        button.on("click", cast("Callable[[], None]", on_click))
        with button:
            ui.label(label)
        return button

    def _rules_card(self, active: ScrubRulesetView) -> None:
        with card():
            with card_header(title="Regex rules", count=f"{len(active.rules)} run at every freeze"):
                pass
            data_table(
                columns=_rule_columns(),
                rows=active.rules,
                state=TableState(sort_key="order"),
                empty_message="No rule.",
                wide=True,
                testid="table-scrub-rules",
            )

    # --- 3. the name lists ----------------------------------------------------

    def _entries_card(self) -> None:
        state = scrubbing_state()
        with card().props('data-testid="scrub-entries"'):
            with card_header(title="Name lists"):
                pass
            with ui.element("div").style(
                "display:flex;align-items:center;gap:12px;padding:10px 14px;"
                "border-bottom:1px solid var(--rule2);flex-wrap:wrap;"
            ):
                self._kind_slot = ui.element("div")
                self._render_kind()
                search = data_props(
                    ui.element("input")
                    .props('type="search" data-testid="scrub-entry-search"')
                    .mark("scrub-entry-search")
                    .style(_INPUT_STYLE),
                    {"aria-label": "Search the list", "placeholder": "Search, e.g. müll"},
                )
                search.props["value"] = state.query
                search.on(
                    "input",
                    lambda event: self._search(str(event.args)),
                    js_handler="(e) => emit(e.target.value)",
                )
            self._entries_slot = ui.element("div")

    def _render_kind(self) -> None:
        """The list switch, in a slot of its own. `segmented_control` draws
        the value it is handed and only reports a click, so a pick must redraw
        it; the rest of the card is drawn once, so the search box keeps focus."""
        if self._kind_slot is None:
            return
        self._kind_slot.clear()
        with self._kind_slot:
            segmented_control(
                options=[KIND_LABELS[k] for k in ENTRY_KINDS],
                value=KIND_LABELS[ListKind(scrubbing_state().entry_kind)],
                label="Which list",
                on_change=_sync(self._pick_kind),
            )

    def _render_entries(self) -> None:
        if self._entries_slot is None or self._entries is None:
            return
        page = self._entries
        state = scrubbing_state()
        table = TableState(sort_key="file_order", page=page.page, page_size=page.page_size)
        self._entries_slot.clear()
        with self._entries_slot:
            data_table(
                columns=(
                    ColumnSpec[ScrubEntryView](
                        key="entry",
                        label="Entry",
                        render=lambda e: ui.label(e.entry).props('data-testid="scrub-entry"'),
                    ),
                    ColumnSpec[ScrubEntryView](
                        key="key",
                        label="Compared as",
                        width="40%",
                        render=lambda e: (
                            ui.label(e.key).classes("mono ink3").style("font-size:11.5px;")
                        ),
                    ),
                ),
                rows=page.items,
                state=table,
                empty_message=(
                    f"No {KIND_LABELS[ListKind(state.entry_kind)].lower()} imported."
                    if not state.query
                    else "No entry matches."
                ),
                testid="table-scrub-entries",
            )
            pagination_row(
                state=table,
                total=page.total,
                shown=len(page.items),
                on_page=_sync(self._turn),
                page_sizes=(ENTRY_PAGE_SIZE,),
            )

    # --- 4. protected strings ---------------------------------------------------

    def _render_protected(self) -> None:
        assert self._active is not None and self._protected_slot is not None
        self._protected_slot.clear()
        with self._protected_slot, card().props('data-testid="scrub-protected"'):
            with card_header(title="Protected strings", count=str(len(self._active.protected))):
                pass
            with ui.element("div").style("display:flex;flex-wrap:wrap;gap:6px;padding:10px 14px;"):
                for text in self._active.protected:
                    ui.label(text).classes("mono chip").props(
                        'data-testid="scrub-protected-string"'
                    ).style("font-size:11.5px;")
            ui.label(PROTECTED_NOTE).style(_NOTE_STYLE + "border-top:1px solid var(--rule2);")

    # --- 5. try a sentence ------------------------------------------------------

    def _try_card(self) -> None:
        state = scrubbing_state()
        with card().props('data-testid="scrub-try"'):
            with card_header(title="Try a sentence"):
                self._action_button(
                    TRY_BUTTON, testid="scrub-try-run", primary=True, on_click=self._try
                )
            with ui.element("div").style(
                "padding:10px 14px;display:flex;flex-direction:column;gap:8px;"
            ):
                editor = (
                    ui.element("textarea")
                    .props('data-testid="scrub-try-input" rows="3" aria-label="Sentence to scrub"')
                    .mark("scrub-try-input")
                    .style(_TEXTAREA_STYLE)
                )
                # Through the props mapping: the text is the analyst's (SD31).
                editor.props["value"] = state.sentence
                self._editor = editor
                # `change`, not `input`: it fires on blur, so pressing Scrub
                # sends the text first, and echoing it back cannot race typing.
                editor.on(
                    "change",
                    lambda event: self._type(str(event.args)),
                    js_handler="(e) => emit(e.target.value)",
                )
                self._try_slot = ui.element("div")
                ui.label(NOTHING_STORED).classes("ink3").style("font-size:11px;")

    def _render_try(self) -> None:
        if self._try_slot is None:
            return
        self._try_slot.clear()
        if self._tried is None:
            return
        with self._try_slot:
            if self._tried.timed_out_rule is not None:
                ui.label(
                    f"Rule {self._tried.timed_out_rule} took too long on this sentence; "
                    "a freeze over it would be refused."
                ).classes("danger").props('data-testid="scrub-try-timeout"').style(
                    "font-size:12px;"
                )
                return
            ui.label(self._tried.text).props('data-testid="scrub-try-output"').style(
                _CODE_BLOCK_STYLE
            )
            ui.label(_hits_line(self._tried)).classes("ink2").props(
                'data-testid="scrub-try-hits"'
            ).style("font-size:11.5px;")

    # --- 6. versions ------------------------------------------------------------

    def _render_versions(self) -> None:
        assert self._versions_slot is not None
        self._versions_slot.clear()
        with self._versions_slot, card():
            with card_header(title="Versions", count=str(len(self._versions))):
                pass
            data_table(
                columns=_version_columns(),
                rows=self._versions,
                state=TableState(sort_key="version"),
                empty_message=NO_VERSIONS_MESSAGE,
                wide=True,
                testid="table-scrub-versions",
            )

    # --- handlers ---------------------------------------------------------------

    async def _pick_kind(self, label: str) -> None:
        kind = next(k for k in ENTRY_KINDS if KIND_LABELS[k] == label)
        _store(replace(scrubbing_state(), entry_kind=kind.value, page=1))
        await self._reload_entries()
        # Last: NiceGUI runs this handler inside the clicked button's slot,
        # and redrawing deletes that button, so any element created after it
        # raises "the parent element this slot belongs to has been deleted".
        self._render_kind()

    async def _search(self, query: str) -> None:
        _store(replace(scrubbing_state(), query=query, page=1))
        await self._reload_entries()

    async def _turn(self, page: int) -> None:
        _store(replace(scrubbing_state(), page=max(page, 1)))
        await self._reload_entries()

    def _type(self, text: str) -> None:
        """Keep the text, and give the box its own `value` back.

        Drawing the result redraws the box from the `value` the client last
        received, which emptied it (seen in a browser). Sent on `change`,
        after the analyst has left the box, so the echo cannot overwrite a
        keystroke still in flight."""
        _store(replace(scrubbing_state(), sentence=text))
        if self._editor is not None:
            self._editor.props["value"] = text

    async def _try(self) -> None:
        self._tried = await self._services.scrub.try_text(scrubbing_state().sentence)
        self._render_try()

    async def _open_import(self, kind: ListKind) -> None:
        """One file of one kind. Picking the file is the import, as on the
        Codelists screen (`auto_upload`)."""
        assert self._root is not None
        if self._dialog is not None:
            self._dialog.delete()
            self._dialog = None
        with (
            self._root,
            ui.dialog().props('data-testid="scrub-import-dialog"') as dialog,
            dialog_card(extra="width:520px;max-height:88vh;overflow:auto;"),
        ):
            self._dialog = dialog
            with ui.element("div").style("padding:14px;"):
                ui.label(f"Import {KIND_LABELS[kind].lower()}").classes("lbl")
                ui.label(
                    f"{KIND_HINTS[kind]}. The file is checked together with the mandatory "
                    "rules and the other files; it becomes a new version or nothing changes."
                ).style("font-size:12.5px;color:var(--ink2);margin-top:6px;white-space:normal;")
            with ui.element("div").style("padding:0 14px 14px;"):
                ui.upload(
                    multiple=False,
                    auto_upload=True,
                    on_multi_upload=cast(
                        "Callable[[MultiUploadEventArguments], None]",
                        lambda event: self._import(event, kind, dialog),
                    ),
                ).props('data-testid="scrub-upload"').style("width:100%;")
        dialog.value = True

    async def _import(
        self, event: MultiUploadEventArguments, kind: ListKind, dialog: ui.dialog
    ) -> None:
        upload = next(iter(event.files), None)
        if upload is None:
            return
        try:
            result = await self._services.scrub.import_list(kind, upload.name, await upload.read())
        except ScrubImportRefusedError as exc:
            dialog.close()
            self._show_refusal(exc.import_errors)
            return
        except (ServiceError, OSError) as exc:
            dialog.close()
            ui.notify(refusal_text(exc), type="negative")
            return
        dialog.close()
        ui.notify(
            "Already the active file — nothing changed."
            if result.no_change
            else f"Rule set v{result.ruleset.version} is active."
        )
        await self.reload()

    async def _remove(self, kind: ListKind) -> None:
        """Reversible (re-import the file), so no confirmation: the `SD61`
        rule for reversible acts."""
        try:
            result = await self._services.scrub.remove_list(kind)
        except ScrubImportRefusedError as exc:
            self._show_refusal(exc.import_errors)
            return
        ui.notify(f"Rule set v{result.ruleset.version} is active.")
        await self.reload()

    def _show_refusal(self, errors: Sequence[ScrubImportError]) -> None:
        """A list to read and act on is a dialog, not a toast, as for a
        refused freeze (`import_view._show_blocking`)."""
        assert self._root is not None
        with (
            self._root,
            ui.dialog().props('data-testid="scrub-refusal"') as dialog,
            dialog_card(extra="width:620px;max-height:88vh;overflow:auto;"),
            ui.element("div").style("padding:14px;"),
        ):
            ui.label(REFUSED_TITLE).classes("lbl danger")
            for error in errors:
                ui.label(error_text(error)).props(
                    f'data-testid="scrub-refusal-error" data-code="{error.code.value}"'
                ).mark("scrub-refusal-error").style(
                    "font-size:12.5px;margin-top:8px;white-space:normal;"
                )
        dialog.value = True


# --- columns and lines ------------------------------------------------------------


def _rule_columns() -> tuple[ColumnSpec[ScrubRuleView], ...]:
    return (
        ColumnSpec[ScrubRuleView](
            key="source", label="Source", width="104px", render=_render_source
        ),
        ColumnSpec[ScrubRuleView](
            key="rule",
            label="Rule",
            width="140px",
            render=lambda r: (
                ui.label(r.rule_id)
                .classes("mono")
                .props('data-testid="scrub-rule-id"')
                .style("font-size:12px;")
            ),
        ),
        ColumnSpec[ScrubRuleView](
            key="tag",
            label="Placeholder",
            width="150px",
            render=lambda r: ui.label(f"<{r.tag}_n>").classes("mono").style("font-size:12px;"),
        ),
        ColumnSpec[ScrubRuleView](
            key="pattern", label="Pattern and examples", render=_render_pattern
        ),
    )


def _render_source(rule: ScrubRuleView) -> None:
    """A mandatory rule in the `LOCKED` pill's shape (the class on the label
    itself, as the Corpora table draws it); an imported one in plain mono."""
    label = ui.label(SOURCE_LABELS.get(rule.source, rule.source)).props(
        f'data-testid="scrub-rule-source" data-source="{rule.source}"'
    )
    if rule.source == "mandatory":
        label.classes("pill")
    else:
        label.classes("mono ink2").style("font-size:11.5px;")


def _render_pattern(rule: ScrubRuleView) -> None:
    with ui.element("div").style("display:flex;flex-direction:column;gap:4px;min-width:0;"):
        ui.label(rule.pattern).classes("mono").props('data-testid="scrub-rule-pattern"').style(
            "font-size:11.5px;white-space:pre-wrap;word-break:break-all;"
        )
        if rule.description:
            ui.label(rule.description).classes("ink2").style("font-size:11.5px;white-space:normal;")
        ui.label("matches: " + " · ".join(rule.must_match)).classes("mono ok").style(
            "font-size:11px;white-space:normal;"
        )
        if rule.must_not_match:
            ui.label("never: " + " · ".join(rule.must_not_match)).classes("mono ink3").style(
                "font-size:11px;white-space:normal;"
            )


def _version_columns() -> tuple[ColumnSpec[ScrubVersionView], ...]:
    return (
        ColumnSpec[ScrubVersionView](
            key="version",
            label="Version",
            width="80px",
            render=lambda v: (
                ui.label(f"v{v.version}").classes("mono").props('data-testid="scrub-version"')
            ),
        ),
        ColumnSpec[ScrubVersionView](
            key="created",
            label="Created",
            width="130px",
            render=lambda v: (
                ui.label(format_local(v.created_at, "%Y-%m-%d %H:%M"))
                .classes("mono")
                .style("font-size:11.5px;")
            ),
        ),
        ColumnSpec[ScrubVersionView](
            key="files",
            label="Files",
            render=lambda v: ui.label(_components_line(v)).style(
                "font-size:12px;white-space:normal;"
            ),
        ),
        ColumnSpec[ScrubVersionView](
            key="corpora",
            label="Corpora",
            width="90px",
            align="right",
            render=lambda v: ui.label(format_count(v.corpus_count)).classes("mono"),
        ),
    )


def _entries_label(kind: ListKind, count: int) -> str:
    if kind is ListKind.REGEX:
        return f"{format_count(count)} rule{'' if count == 1 else 's'}"
    return f"{format_count(count)} {'entry' if count == 1 else 'entries'}"


def _notices_line(current: ScrubListView) -> str:
    return " · ".join(
        f"{NOTICE_LABELS.get(ListNoticeCode(n.code), n.code)}: {format_count(n.count)}"
        for n in current.notices
    )


def _components_line(version: ScrubVersionView) -> str:
    parts = [f"{KIND_LABELS[ListKind(kind)]}: {name}" for kind, name in version.components.items()]
    return " · ".join(parts) or "no files"


def _hits_line(tried: ScrubTryView) -> str:
    """Each replaced span, as the service reported it: rule and placeholder.
    Listed, never counted here (§8.1.1)."""
    if not tried.hits:
        return "Nothing replaced."
    return "Replaced: " + " · ".join(f"{h.placeholder} ({h.rule_id})" for h in tried.hits)


def _sync[**P](action: Callable[P, Awaitable[None]]) -> Callable[P, None]:
    """An async handler, typed as the component kit's synchronous callback.
    NiceGUI awaits an awaitable result, so this is a typing formality; the
    same helper `import_view` uses."""
    return cast("Callable[P, None]", action)

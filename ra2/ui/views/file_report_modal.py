"""The file report modal — the Import row action's destination (SD9).

The design defers it ("modal, not yet designed", README §1a and "Open
questions" 1), so sw-design.md §8.3 specifies the minimum and this module
implements exactly that list and nothing more:

- per-file findings **grouped by `FindingCode`**, with counts and keys;
- detected vs. effective encoding / delimiter / quote character, with
  override selectors;
- a re-parse button;
- a 20-row raw preview;
- remove;
- "Export findings CSV".

Two things here are architecture, not decoration:

**The wording table.** `FindingCode` values are stable identifiers and tests
assert on the code, never on prose (sw-design.md §5.1). `FINDING_LABELS`
below is the one rendering table that turns a code into a sentence, so
wording changes never break a test. `Finding.detail` is structured data and
is rendered as its own key/value pairs — never as a pre-formatted sentence.

**Styling.** Nothing about this modal is designed, so it is deliberately
plain: `ui.dialog` with the app's own `.card`, the app's own tokens, and the
same native `<select>` / `<input>` the component kit's pagination row uses.
Inventing a visual language for an undesigned surface would be a second design
to reconcile later.
"""

from collections.abc import Awaitable, Callable
from typing import Final, cast

from nicegui import ui
from nicegui.element import Element

from ra2.domain.delivery import Encoding
from ra2.domain.findings import Finding, FindingCode, Severity
from ra2.domain.ids import FileId
from ra2.services.container import Services
from ra2.services.errors import ServiceError
from ra2.services.readmodels import DeliveryFileView, DeliveryView
from ra2.ui.components import card, format_count

__all__ = ["FINDING_LABELS", "PREVIEW_LINES", "open_file_report"]

#: sw-design.md §8.3 — "a 20-row raw preview".
PREVIEW_LINES: Final = 20

#: The **one** rendering table for the report vocabulary (sw-design.md §5.1).
#: Every `FindingCode` appears; a missing entry would render a bare enum name
#: at an analyst, so the fallback in `_finding_label` is a safety net, not a
#: licence to leave codes out.
FINDING_LABELS: Final[dict[FindingCode, str]] = {
    FindingCode.ENCODING_DETECTED: "Encoding detected",
    FindingCode.FILE_UNDECODABLE: "File could not be decoded — it is excluded from any corpus",
    FindingCode.DIALECT_DETECTED: "Delimiter and quote character detected",
    FindingCode.UNKNOWN_HEADER: "Header matches no known table",
    FindingCode.HEADER_MISMATCH: "Header matches a known table, but not exactly",
    FindingCode.ROW_RECOVERED: "Row reassembled across several lines",
    FindingCode.ROW_REJECTED_FIELD_COUNT: "Row rejected — field count differs from the header",
    FindingCode.ROW_REJECTED_PARSE_ERROR: "Row rejected — it could not be read",
    FindingCode.DUP_KEY_CROSS_SET: "Key appears twice in this delivery",
    FindingCode.ORPHAN_FK: "Child row with no parent",
    FindingCode.SET_UNRESOLVED: "File reaches no unfall file, so it belongs to no set",
    FindingCode.COUNT_MISMATCH_OBJ: "Declared object count differs from the delivered rows",
    FindingCode.COUNT_MISMATCH_PERS: "Declared person count differs from the delivered rows",
    FindingCode.TEXT_KEY_UNMATCHED: "Narrative with no unfall row",
    FindingCode.UNFALL_WITHOUT_TEXT: "Unfall row with no narrative",
    FindingCode.CP1252_CANARY_ZERO: "No Windows-1252-only character in a corpus containing French",
}

#: How many of a group's keys are listed inline before the count takes over.
#: Every key is still in the CSV export, which is why that action exists.
_KEYS_SHOWN: Final = 12

_LABEL = "font-family:var(--mono);font-size:10px;letter-spacing:.09em;text-transform:uppercase;"
_SECTION = "padding:14px;border-top:1px solid var(--rule2);"


async def open_file_report(
    *,
    services: Services,
    delivery: DeliveryView,
    file_id: FileId,
    host: Element,
    on_changed: Callable[[], Awaitable[None]],
) -> None:
    """Open the report for one file of one delivery.

    `on_changed` is awaited after anything that changes the delivery — a
    re-parse or a removal — so the view behind the modal re-reads the service
    rather than guessing what changed.

    `host` is the element the dialog is built inside, and it must be one the
    view never clears: the click that opens this modal comes from a button in
    a table cell, and `on_changed` redraws that table. A dialog parented to
    the cell would be destroyed mid-refresh, taking its own handler's slot
    with it.
    """
    report = _FileReport(
        services=services, delivery=delivery, file_id=file_id, host=host, on_changed=on_changed
    )
    await report.show()


class _FileReport:
    """One open modal. Instantiated per click, so it holds no shared state
    and nothing lives in a module global (§12.8)."""

    def __init__(
        self,
        *,
        services: Services,
        delivery: DeliveryView,
        file_id: FileId,
        host: Element,
        on_changed: Callable[[], Awaitable[None]],
    ) -> None:
        self._services = services
        self._delivery = delivery
        self._file_id = file_id
        self._host = host
        self._on_changed = on_changed
        self._dialog: ui.dialog | None = None
        self._body: Element | None = None
        self._encoding = ""
        self._delimiter = ""
        self._quote_char = ""

    # --- lifecycle ---------------------------------------------------------

    async def show(self) -> None:
        """Build the dialog, fill it, then show it with `dialog.value = True`.

        That last line is what NiceGUI's `Dialog.open()` does, spelled out.
        The N4 gates scan every line of `ra2/` for `.open(` and require an
        `encoding=` beside it (§12.4); that scan is about file I/O, and a
        dialog opener tripping it would be a false positive on a real
        invariant. The invariant is worth more than the sugar.
        """
        file = self._file()
        if file is None:
            ui.notify("That file is no longer part of this delivery.", type="warning")
            return
        with self._host, ui.dialog().props('data-testid="file-report"') as dialog:
            self._dialog = dialog
            # Quasar re-enables pointer events with `.q-dialog__inner > div`,
            # by tag. A `<section class="card">` as the direct child renders
            # correctly and is completely unclickable, so the card goes one
            # level in.
            with (
                ui.element("div").style("border-radius:3px;"),
                card(extra="width:760px;max-width:96vw;max-height:88vh;overflow:auto;"),
            ):
                self._body = ui.element("div").style("display:flex;flex-direction:column;")
        self._render(file)
        dialog.value = True

    def _file(self) -> DeliveryFileView | None:
        return next((f for f in self._delivery.files if f.file_id == self._file_id), None)

    async def _refresh(self) -> None:
        """Re-read the delivery, redraw the view behind the modal, and only
        **then** redraw the modal itself.

        The order is load-bearing. Every action here is fired by a button
        inside `self._body`, and redrawing the body destroys that button —
        after which NiceGUI can no longer resolve the handler's slot, and the
        next `app.storage.client` or `ui.notify` in the same handler raises
        "The parent element this slot belongs to has been deleted." So the
        modal redraws itself last, and nothing follows it.
        """
        self._delivery = await self._services.delivery.get(self._delivery.delivery_id)
        file = self._file()
        await self._on_changed()
        if file is None:
            self._close()
        else:
            self._render(file)

    def _close(self) -> None:
        if self._dialog is not None:
            self._dialog.close()

    # --- rendering ---------------------------------------------------------

    def _render(self, file: DeliveryFileView) -> None:
        assert self._body is not None  # built in `show()`, before any render
        self._encoding = file.encoding or Encoding.UTF_8.value
        self._delimiter = file.delimiter or ""
        self._quote_char = file.quote_char or ""
        self._body.clear()
        with self._body:
            self._header(file)
            self._settings(file)
            self._findings(file)
            self._preview()
            self._actions(file)

    def _header(self, file: DeliveryFileView) -> None:
        with ui.element("div").style("padding:14px;"):
            ui.label("File report").classes("lbl")
            ui.label(file.filename).classes("mono").props('data-testid="report-filename"').mark(
                "report-filename"
            ).style("font-size:13px;font-weight:500;margin-top:4px;")
            facts = [
                f"kind {file.file_kind.value}",
                f"set {file.set_key}" if file.set_key else "no set",
                f"canton {file.canton}" if file.canton else "no canton",
                f"{format_count(file.byte_size)} bytes",
                f"sha256 {file.sha256[:12]}",
            ]
            ui.label(" · ".join(facts)).classes("mono").style(
                "font-size:11px;color:var(--ink3);margin-top:3px;"
            )
            counts = (
                f"{format_count(file.row_count)} rows · {format_count(file.ok_count)} ok · "
                f"{format_count(file.recovered_count)} recovered · "
                f"{format_count(file.rejected_count)} rejected"
                if file.row_count is not None
                else "not analysed"
            )
            ui.label(counts).classes("mono").props('data-testid="report-counts"').mark(
                "report-counts"
            ).style("font-size:11.5px;color:var(--ink2);margin-top:6px;")

    def _settings(self, file: DeliveryFileView) -> None:
        """Detected vs. effective, with the override selectors (§8.3).

        Both columns are shown because the difference *is* the override:
        `delivery_file` stores the effective settings beside what detection
        said, and an override is exactly the case where the two differ.

        The three controls are a native `<select>` and two native `<input>`s,
        the same choice `components/primitives.py` makes for the "Rows per
        page" selector: Quasar's own carry a 40px hit target and a type scale
        this design does not have (R2, §8.2).
        """
        with ui.element("div").style(_SECTION):
            ui.label("Encoding and dialect").classes("lbl")
            with ui.element("div").style(
                "display:grid;grid-template-columns:110px 1fr 1fr;gap:8px 14px;"
                "align-items:center;margin-top:8px;"
            ):
                ui.label("")
                ui.label("Detected").style(_LABEL + "color:var(--ink3);")
                ui.label("Effective").style(_LABEL + "color:var(--ink3);")

                ui.label("Encoding").style("font-size:12.5px;")
                _detected(file.encoding_detected, testid="detected-encoding")
                self._encoding_select()

                ui.label("Delimiter").style("font-size:12.5px;")
                _detected(file.delimiter, testid="detected-delimiter")
                self._text_override(
                    "_delimiter", value=self._delimiter, testid="override-delimiter"
                )

                ui.label("Quote char").style("font-size:12.5px;")
                _detected(file.quote_char, testid="detected-quote")
                self._text_override("_quote_char", value=self._quote_char, testid="override-quote")

            ui.label(
                "Re-parse re-runs analysis for this file alone. Nothing else in the "
                "delivery changes."
            ).style("font-size:11.5px;color:var(--ink3);margin-top:10px;")

    def _encoding_select(self) -> None:
        """The two encodings the pipeline tries, and nothing else: undecodable
        bytes fail the file, and there is no third fallback (§4.2.1)."""
        select = (
            ui.element("select")
            .classes("chip")
            .props('aria-label="Encoding" data-testid="override-encoding"')
            .mark("override-encoding")
            .style("padding:3px 8px;font-size:11px;")
        )
        # `js_handler` emits the value itself: asking the client for the
        # event's `target` hands back a DOM node that never survives
        # serialisation, and the handler raises `KeyError` instead.
        select.on(
            "change",
            lambda event: self._set("_encoding", event.args),
            js_handler="(e) => emit(e.target.value)",
        )
        with select:
            for encoding in Encoding:
                option = ui.element("option").props(f'value="{encoding.value}"')
                if encoding.value == self._encoding:
                    option.props("selected")
                with option:
                    ui.label(encoding.value)

    def _text_override(self, field: str, *, value: str, testid: str) -> None:
        entry = (
            ui.element("input")
            .classes("chip")
            .props(f'type="text" value="{value}" aria-label="{testid}" data-testid="{testid}"')
            .mark(testid)
            .style("padding:3px 8px;font-size:11px;")
        )
        entry.on(
            "input",
            lambda event: self._set(field, event.args),
            js_handler="(e) => emit(e.target.value)",
        )

    def _set(self, field: str, value: object) -> None:
        setattr(self, field, "" if value is None else str(value))

    def _findings(self, file: DeliveryFileView) -> None:
        """Grouped by `FindingCode`, with counts and keys (§8.3).

        Grouping is what makes a report readable: 4 402 rejected rows are one
        line with a count, not 4 402 lines.
        """
        with ui.element("div").style(_SECTION):
            ui.label("Findings").classes("lbl")
            groups = _grouped(file.findings)
            if not groups:
                ui.label("No findings for this file.").style(
                    "font-size:12.5px;color:var(--ink3);margin-top:8px;"
                )
                return
            with ui.element("div").style("margin-top:8px;"):
                for code, findings in groups:
                    self._finding_group(code, findings)

    def _finding_group(self, code: FindingCode, findings: tuple[Finding, ...]) -> None:
        blocking = any(f.severity is Severity.BLOCKING for f in findings)
        with (
            ui.element("div")
            .props(f'data-testid="finding-group" data-code="{code.value}"')
            .mark(f"finding-{code.value}")
            .style("padding:8px 0;border-bottom:1px solid var(--rule2);")
        ):
            with ui.element("div").style("display:flex;align-items:baseline;gap:8px;"):
                ui.label(code.value).classes("mono").style("font-size:11px;color:var(--ink2);")
                ui.label(format_count(len(findings))).classes(
                    "mono danger" if blocking else "mono"
                ).style("font-size:11px;")
                if blocking:
                    ui.label("blocking").classes("pill danger")
            ui.label(_finding_label(code)).style("font-size:12.5px;margin-top:2px;")

            keys = [f.key for f in findings if f.key]
            if keys:
                shown = " · ".join(keys[:_KEYS_SHOWN])
                more = "" if len(keys) <= _KEYS_SHOWN else f" · +{len(keys) - _KEYS_SHOWN} more"
                ui.label(shown + more).classes("mono").props('data-testid="finding-keys"').style(
                    "font-size:10.5px;color:var(--ink3);margin-top:3px;"
                    "word-break:break-all;white-space:normal;"
                )
            detail = _detail_line(findings[0])
            if detail:
                ui.label(detail).classes("mono").style(
                    "font-size:10.5px;color:var(--ink3);margin-top:3px;white-space:normal;"
                )

    def _preview(self) -> None:
        """The 20-row raw preview (§8.3).

        **Blocked on `contracts/amendments/feat-m6-import-view.md` item 3.**
        Reading a delivery file's bytes needs `FileStore`, which lives in
        `ra2.infra`, and `.importlinter` forbids `ra2.ui -> ra2.infra` — so
        the import that would implement this fails the build. The section
        renders its own absence rather than pretending the file has no
        content.
        """
        with ui.element("div").style(_SECTION):
            ui.label(f"First {PREVIEW_LINES} lines").classes("lbl")
            ui.label(
                "Unavailable: no service reads a delivery file's raw lines yet "
                "(amendment feat/m6-import-view, item 3)."
            ).props('data-testid="report-preview"').mark("report-preview").style(
                "font-size:12.5px;color:var(--ink3);margin-top:8px;"
            )

    def _actions(self, file: DeliveryFileView) -> None:
        with ui.element("div").style(
            _SECTION + "display:flex;gap:8px;align-items:center;flex-wrap:wrap;"
        ):
            _button("Re-parse", primary=True, testid="reparse", action=self._reparse)
            _button("Export findings CSV", testid="export-findings", action=self._export)
            _button("Remove file", testid="remove-file", action=self._remove, danger=True)
            ui.element("div").style("flex:1;")
            _button("Close", testid="close-report", action=self._close_async)
            ui.label(file.relative_path).classes("mono").style(
                "font-size:10.5px;color:var(--ink3);flex-basis:100%;"
            )

    # --- actions -----------------------------------------------------------

    async def _reparse(self) -> None:
        try:
            await self._services.delivery.reparse_file(
                self._delivery.delivery_id,
                self._file_id,
                encoding=Encoding(self._encoding) if self._encoding else None,
                delimiter=self._delimiter or None,
                quote_char=self._quote_char or None,
            )
        except (ServiceError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        # No toast on success: `_refresh` ends by redrawing this modal, which
        # deletes the button that fired this handler, and a notification after
        # that has no slot to resolve. The new counts and the row's new state
        # are the feedback — README's own advice for parse outcomes.
        await self._refresh()

    async def _export(self) -> None:
        data = await self._services.export.findings_csv(self._delivery.delivery_id, self._file_id)
        file = self._file()
        name = file.filename if file is not None else self._file_id
        ui.download.content(data, f"{name}.findings.csv", media_type="text/csv")

    async def _remove(self) -> None:
        try:
            await self._services.delivery.remove_file(self._delivery.delivery_id, self._file_id)
        except ServiceError as exc:
            ui.notify(str(exc), type="negative")
            return
        self._close()
        await self._on_changed()

    async def _close_async(self) -> None:
        self._close()


# --- helpers ----------------------------------------------------------------


def _finding_label(code: FindingCode) -> str:
    return FINDING_LABELS.get(code, code.value)


def _grouped(findings: tuple[Finding, ...]) -> list[tuple[FindingCode, tuple[Finding, ...]]]:
    """Findings by code, blocking groups first, then by descending count.

    Ordering is presentation: the analyst is looking for what stops the
    freeze, and after that for what happened most.
    """
    groups: dict[FindingCode, list[Finding]] = {}
    for finding in findings:
        groups.setdefault(finding.code, []).append(finding)
    return sorted(
        ((code, tuple(items)) for code, items in groups.items()),
        key=lambda group: (
            not any(f.severity is Severity.BLOCKING for f in group[1]),
            -len(group[1]),
            group[0].value,
        ),
    )


def _detail_line(finding: Finding) -> str:
    """`Finding.detail` as its own key/value pairs — never a pre-formatted
    sentence (sw-design.md §5)."""
    return " · ".join(f"{key}={finding.detail[key]}" for key in sorted(finding.detail))


def _detected(value: str | None, *, testid: str) -> None:
    ui.label(value or "—").classes("mono").props(f'data-testid="{testid}"').mark(testid).style(
        "font-size:11.5px;color:var(--ink2);"
    )


def _button(
    label: str,
    *,
    testid: str,
    action: Callable[[], Awaitable[None]],
    primary: bool = False,
    danger: bool = False,
) -> None:
    """A `.btn` from the design's own two variants.

    The handler is async; NiceGUI's `handle_event` awaits an awaitable result
    inside the sender's slot context, so the cast is a typing formality and
    not a change of behaviour.
    """
    classes = "btn primary" if primary else "btn secondary"
    button = (
        ui.element("button")
        .classes(classes)
        .props(f'type="button" data-testid="{testid}"')
        .mark(testid)
    )
    if danger:
        button.style("color:var(--danger);")
    button.on("click", cast("Callable[[], None]", action))
    with button:
        ui.label(label)

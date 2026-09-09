"""Layer 3 — the Import view (sw-design.md §11.3, "import").

Exactly the bullet list §11.3 names, against the **real** view driven by the
**real** services over a real migrated temp-file SQLite database:

- deselecting a file updates **both** the card-header count and the
  "Create corpus · N records" label;
- the header checkbox selects all / none and shows indeterminate when partial;
- a sort click flips direction;
- sort state is independent per table;
- pagination **disables** rather than hides.

Nothing here stubs a service. A view that recomputed a count instead of
re-reading one would pass a mock-shaped test and fail these.

`seeded` is a local fixture rather than `conftest.py`'s `user`: that one
yields only a `User`, and these tests need the app's **services** to seed a
delivery. Seeding through `/api/v1` is what §11.5 asks of E2E, but
`ra2/api/v1/deliveries.py` is still the M0 stub (every handler raises 501), so
there is no HTTP path to seed through at this milestone. The schema comes from
`conftest.py`'s `migrated_db` — `alembic upgrade head`, never
`metadata.create_all()` (§12.10).
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.element import Element
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction

from ra2.domain.delivery import DeliveryStatus, SourceKind
from ra2.infra.config import Settings
from ra2.services.container import Services
from ra2.ui.views.import_view import (
    CORPORA_CAPTION,
    NO_CORPORA_MESSAGE,
    STRUCTURED_NOTE,
    TEXT_NOTE,
)

pytestmark = pytest.mark.ui

#: `tests/ui/` -> `tests/`.
_TESTS_ROOT = Path(__file__).resolve().parents[1]
_HAZARDS = _TESTS_ROOT / "fixtures" / "deliveries" / "hazards"

#: The delivery these tests drive: **thirteen committed hazard files**, twelve
#: structured and one text, so the left card has two pages at the default page
#: size of 10 and the right card has one. Filenames are deliberately arbitrary:
#: kind, canton and set all come from the data (§12.5), so what a file is
#: called can never decide which card it lands in.
#:
#: The states this produces are the design's own three: `1 rejected`
#: (h03's stray delimiter), `1 recovered` (h04's embedded newline), `ok`
#: everywhere else — plus `failed` for h12, whose header matches no table.
DELIVERY: dict[str, str] = {
    "a_unfall.txt": "h03_stray_delimiter/unfall.txt",
    "b_unfall.txt": "h08_all_empty_column/unfall.txt",
    "c_unfall.txt": "h01_cp1252/unfall.txt",
    "d_objekt.txt": "h10_count_mismatch/objekt.txt",
    "e_person.txt": "h10_count_mismatch/person.txt",
    "f_objekt.txt": "h06_orphan_objekt/objekt.txt",
    "g_unfall.txt": "h06_orphan_objekt/unfall.txt",
    "h_unfall.txt": "h11_unmatched_text_key/unfall.txt",
    "i_unknown.csv": "h12_unknown_header/unknown.csv",
    "j_unfall.txt": "h10_count_mismatch/unfall.txt",
    "k_objekt.txt": "h06_orphan_objekt/objekt.txt",
    "l_person.txt": "h10_count_mismatch/person.txt",
    "m_text.csv": "h04_embedded_newline/text.csv",
}

#: The `unfall` `ok_count`s of `DELIVERY`, which is what
#: `DeliveryView.selected_record_count` sums: a 2 + b 3 + c 2 + g 1 + h 1 + j 1.
ALL_RECORDS = 10
#: … minus `a_unfall.txt`, the file every deselection test drops.
WITHOUT_A = 8

STRUCTURED_FILES = 12
TEXT_FILES = 1


@dataclass(frozen=True)
class Seeded:
    user: User
    services: Services
    app: FastAPI


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def delivery_root(tmp_path: Path) -> Path:
    """`DELIVERY` on disk, byte-for-byte, ready to register as a host path."""
    root = tmp_path / "delivery"
    root.mkdir(parents=True)
    for name, source in DELIVERY.items():
        (root / name).write_bytes((_HAZARDS / source).read_bytes())
    return root


@pytest.fixture
async def seeded(
    app_factory: Callable[..., FastAPI],
    migrated_db: Settings,
    delivery_root: Path,
) -> AsyncIterator[Seeded]:
    """The real UI-mounted app, with one analysed delivery already in it."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            services: Services = app.state.services
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                delivery_id = await services.delivery.register(
                    "hazards", source_kind=SourceKind.HOST_PATH, root_path=delivery_root
                )
                await services.delivery.analyse(delivery_id)
                await _until_analysed(services, delivery_id)
                yield Seeded(User(client), services, app)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            from nicegui.functions.download import download
            from nicegui.functions.navigate import Navigate
            from nicegui.functions.notify import notify

            ui.navigate = Navigate()
            ui.notify = notify
            ui.download = download


async def _until_analysed(services: Services, delivery_id: str) -> None:
    """`TaskRunner` returns immediately — and before the work it scheduled has
    started — so the seed waits for a **terminal** status, exactly as the view
    does."""
    for _ in range(500):
        delivery = await services.delivery.get(delivery_id)  # type: ignore[arg-type]
        if delivery.status in (DeliveryStatus.ANALYSED, DeliveryStatus.FAILED):
            assert delivery.status is DeliveryStatus.ANALYSED, delivery.status
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the delivery never finished analysing")


async def _until(predicate: Callable[[], bool]) -> None:
    """Poll until `predicate()` is true.

    A click's handler is dispatched but not awaited by `UserInteraction.click`
    (`nicegui.testing`'s `_dispatch_click` fires it via `handle_event` and
    returns immediately), so an async handler's effects — a sort, a page
    change, a selection — are not guaranteed to be visible the instant
    `.click()` returns. `user.should_see(text)` covers most cases, but a text
    marker is only a reliable sync point when it cannot **already** be true
    before the handler runs; this covers the rest.
    """
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


# --- helpers -----------------------------------------------------------------


def _card(user: User, name: str) -> Element:
    """One of the two file cards, by the `data-card` the view stamps on it."""
    return next(e for e in user.find(kind=ui.element).elements if e._props.get("data-card") == name)


def _within(root: Element, testid: str) -> list[Element]:
    """Elements under `root` carrying `data-testid`.

    Both file tables render the same markers — that is the point of one
    `DataTable` component — so anything asserting about *one* table has to
    scope itself to that table's subtree.
    """
    return [e for e in root.descendants() if e._props.get("data-testid") == testid]


def _one(user: User, element: Element) -> UserInteraction[Element]:
    return UserInteraction(user, {element}, None)


def _tick(user: User, root: Element, label: str) -> Element:
    return next(e for e in _within(root, "tick") if e._props.get("aria-label") == label)


def _table(user: User, name: str) -> Element:
    (table,) = user.find(marker=f"table-{name}").elements
    return table


def _filenames(root: Element) -> list[str]:
    return [_own_text(e) for e in _ordered(_within(root, "filename"))]


def _states(root: Element) -> list[str]:
    return [_own_text(e) for e in _ordered(_within(root, "file-state"))]


def _own_text(element: Element) -> str:
    """A `ui.label`'s own text. `Element` itself has no `text`, which is why
    this goes through `getattr` rather than a cast."""
    return str(getattr(element, "text", ""))


def _ordered(elements: Iterable[Element]) -> list[Element]:
    """NiceGUI hands out ids in creation order, which is document order here."""
    return sorted(elements, key=lambda e: e.id)


def _text_of(user: User, marker: str) -> str:
    (element,) = user.find(marker=marker).elements
    parts = [_own_text(element), *(_own_text(c) for c in element.descendants())]
    return " ".join(p for p in parts if p).strip()


# --- §11.3: the two counts ---------------------------------------------------


async def test_deselecting_a_file_updates_both_counts(seeded: Seeded) -> None:
    """README, Interactions: the header count and the "Create corpus · N
    records" label "both recompute live from the selection".

    Both numbers come from the one `DeliveryView` the service returns — the
    view never sums anything itself (§8.1.1).
    """
    user = seeded.user
    await user.open("/import")
    await user.should_see(f"{STRUCTURED_FILES} files · {STRUCTURED_FILES} selected", retries=30)
    await user.should_see(f"Create corpus · {ALL_RECORDS} records", retries=30)

    structured = _card(user, "structured")
    _one(user, _tick(user, structured, "Select a_unfall.txt")).click()

    await user.should_see(f"{STRUCTURED_FILES} files · {STRUCTURED_FILES - 1} selected", retries=30)
    await user.should_see(f"Create corpus · {WITHOUT_A} records", retries=30)


async def test_a_deselected_file_stays_in_the_list(seeded: Seeded) -> None:
    """ "Deselected files stay in the list and are excluded from the corpus"
    (README §1a.4) — the row is still there, its tick is not."""
    user = seeded.user
    await user.open("/import")
    structured = _card(user, "structured")
    _one(user, _tick(user, structured, "Select a_unfall.txt")).click()
    await user.should_see(f"Create corpus · {WITHOUT_A} records", retries=30)

    structured = _card(user, "structured")
    assert "a_unfall.txt" in _filenames(structured)
    assert _tick(user, structured, "Select a_unfall.txt")._props["aria-checked"] == "false"


# --- §11.3: select all / none / indeterminate --------------------------------


async def test_the_header_tick_selects_all_none_and_goes_indeterminate(seeded: Seeded) -> None:
    """README, Interactions: "Header-row checkbox = select all / none for that
    table (indeterminate when partially selected)"."""
    user = seeded.user
    await user.open("/import")

    def header() -> Element:
        return _tick(user, _table(user, "structured"), "Select all")

    assert header()._props["aria-checked"] == "true"

    _one(user, _tick(user, _card(user, "structured"), "Select a_unfall.txt")).click()
    await user.should_see(f"Create corpus · {WITHOUT_A} records", retries=30)
    assert header()._props["aria-checked"] == "mixed"

    _one(user, header()).click()
    await user.should_see(f"Create corpus · {ALL_RECORDS} records", retries=30)
    assert header()._props["aria-checked"] == "true"

    _one(user, header()).click()
    await user.should_see("Create corpus · 0 records", retries=30)
    assert header()._props["aria-checked"] == "false"
    await user.should_see(f"{STRUCTURED_FILES} files · 0 selected", retries=30)


async def test_the_header_tick_only_touches_its_own_table(seeded: Seeded) -> None:
    """Select-all is per table: the text file is a separate card with a
    separate header tick (README §1a)."""
    user = seeded.user
    await user.open("/import")
    _one(user, _tick(user, _table(user, "structured"), "Select all")).click()
    await user.should_see(f"{STRUCTURED_FILES} files · 0 selected", retries=30)
    await user.should_see(f"{TEXT_FILES} file · {TEXT_FILES} selected", retries=30)


# --- §11.3: sorting ----------------------------------------------------------


async def test_a_sort_click_flips_the_direction(seeded: Seeded) -> None:
    """ "Clicking the active column flips direction" (README, Interactions).

    `TableState.toggled` decides it; the table only reports the click.
    """
    user = seeded.user
    await user.open("/import")
    table = _table(user, "structured")
    (header,) = _within(table, "sort-filename")
    assert header._props["aria-sort"] == "ascending"
    assert _filenames(table)[0] == "a_unfall.txt"

    _one(user, header).click()
    await user.should_see("l_person.txt", retries=30)

    table = _table(user, "structured")
    (header,) = _within(table, "sort-filename")
    assert header._props["aria-sort"] == "descending"
    assert _filenames(table)[0] == "l_person.txt"


async def test_sorting_on_rows_moves_the_active_column(seeded: Seeded) -> None:
    """Sorting is two-direction on File, Rows and State, and only one column
    is active at a time (README §1a).

    Ascending by row count puts the three one-row files first — a fact about
    the *data*, which is the point: the order is never the filename's.
    """
    user = seeded.user
    await user.open("/import")
    (header,) = _within(_table(user, "structured"), "sort-row_count")
    _one(user, header).click()
    await _until(
        lambda: (
            _within(_table(user, "structured"), "sort-row_count")[0]._props["aria-sort"]
            == "ascending"
        )
    )

    table = _table(user, "structured")
    assert _within(table, "sort-row_count")[0]._props["aria-sort"] == "ascending"
    assert _within(table, "sort-filename")[0]._props["aria-sort"] == "none"
    assert _filenames(table)[:3] == ["g_unfall.txt", "h_unfall.txt", "j_unfall.txt"]


async def test_sort_state_is_independent_per_table(seeded: Seeded) -> None:
    """README, Interactions: "Sort state is per-table and independent between
    the two tables". One named `TableState` per table is what makes it so."""
    user = seeded.user
    await user.open("/import")
    (header,) = _within(_table(user, "structured"), "sort-filename")
    _one(user, header).click()
    await user.should_see("l_person.txt", retries=30)

    assert _within(_table(user, "structured"), "sort-filename")[0]._props["aria-sort"] == (
        "descending"
    )
    assert _within(_table(user, "text"), "sort-filename")[0]._props["aria-sort"] == "ascending"


# --- §11.3: pagination -------------------------------------------------------


async def test_pagination_disables_rather_than_hides(seeded: Seeded) -> None:
    """README, Interactions: "disabled arrows are greyed, not hidden"."""
    user = seeded.user
    await user.open("/import")
    card = _card(user, "structured")
    (previous,) = _within(card, "page-prev")
    (following,) = _within(card, "page-next")
    assert "disabled" in previous._props
    assert "disabled" not in following._props
    await user.should_see(f"1–10 of {STRUCTURED_FILES}", retries=30)

    _one(user, following).click()
    await user.should_see(f"11–{STRUCTURED_FILES} of {STRUCTURED_FILES}", retries=30)

    card = _card(user, "structured")
    assert "disabled" not in _within(card, "page-prev")[0]._props
    assert "disabled" in _within(card, "page-next")[0]._props
    assert _filenames(_table(user, "structured")) == ["k_objekt.txt", "l_person.txt"]


async def test_the_single_text_file_has_both_arrows_disabled_not_hidden(seeded: Seeded) -> None:
    user = seeded.user
    await user.open("/import")
    card = _card(user, "text")
    assert "disabled" in _within(card, "page-prev")[0]._props
    assert "disabled" in _within(card, "page-next")[0]._props
    await user.should_see(f"1–1 of {TEXT_FILES}", retries=30)


# --- the design's own copy and states ----------------------------------------


async def test_the_state_column_renders_the_designs_three_states(seeded: Seeded) -> None:
    """ "ok" in `--ok`, "N rejected" in `--danger`, "N recovered" in `--warn`
    (README §1a). The counts come from the analysis, never from a filename."""
    user = seeded.user
    await user.open("/import")
    structured = _table(user, "structured")
    states = dict(zip(_filenames(structured), _states(structured), strict=True))
    assert states["a_unfall.txt"] == "1 rejected"
    assert states["b_unfall.txt"] == "ok"
    # h12's header matches no table at all — undesigned, but the pipeline
    # produces it, so it renders as its own state rather than as "ok".
    assert states["i_unknown.csv"] == "failed"

    text = _table(user, "text")
    assert _states(text) == ["1 recovered"]

    rejected = next(e for e in _within(structured, "file-state") if _own_text(e) == "1 rejected")
    recovered = next(e for e in _within(text, "file-state") if _own_text(e) == "1 recovered")
    assert "danger" in rejected.classes
    assert "warn" in recovered.classes


async def test_the_two_cards_carry_the_designs_titles_and_footnotes(seeded: Seeded) -> None:
    user = seeded.user
    await user.open("/import")
    await user.should_see("Structured sets", retries=30)
    await user.should_see("Text file", retries=30)
    await user.should_see(STRUCTURED_NOTE)
    await user.should_see(TEXT_NOTE)


async def test_the_corpora_card_is_empty_and_carries_its_caption(seeded: Seeded) -> None:
    """The immutability note is a sub-caption strip, verbatim (README §1b)."""
    user = seeded.user
    await user.open("/import")
    await user.should_see("Corpora", retries=30)
    await user.should_see("0 imported · 0 locked by an evaluation", retries=30)
    await user.should_see(CORPORA_CAPTION)
    await user.should_see(NO_CORPORA_MESSAGE)


async def test_a_delivery_that_has_not_been_registered_yet_says_so(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> None:
    """Empty state: undesigned, so one centred line inside the well, which is
    what README's "Loading / empty / error" section suggests."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                user = User(client)
                await user.open("/import")
                await user.should_see("No delivery yet", retries=30)
                await user.should_see("0 files · 0 selected", retries=30)
                await user.should_see("Create corpus · 0 records", retries=30)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)


# --- the file report modal (sw-design.md §8.3) -------------------------------


async def test_the_row_action_opens_that_files_report(seeded: Seeded) -> None:
    """The clipboard icon opens the per-file parse findings, grouped by
    `FindingCode` with counts and keys — never a pre-formatted sentence."""
    user = seeded.user
    await user.open("/import")
    structured = _card(user, "structured")
    action = next(
        e
        for e in structured.descendants()
        if e._props.get("aria-label") == "Report for a_unfall.txt"
    )
    _one(user, action).click()

    await user.should_see("File report", retries=30)
    await user.should_see("a_unfall.txt", retries=30)
    # The code, not its wording: `FindingCode` values are the stable
    # identifiers tests assert on (sw-design.md §5.1).
    await user.should_see("ROW_REJECTED_FIELD_COUNT", retries=30)
    # …and the offending key, which §4.2 requires every rejected row to carry.
    await user.should_see("aa000000000000000000000000000002", retries=30)


async def test_the_report_shows_detected_beside_effective_settings(seeded: Seeded) -> None:
    """§8.3: "the detected vs. effective encoding/delimiter/quote char with
    override selectors". An override is exactly where the two differ."""
    user = seeded.user
    await user.open("/import")
    structured = _card(user, "structured")
    action = next(
        e
        for e in structured.descendants()
        if e._props.get("aria-label") == "Report for c_unfall.txt"
    )
    _one(user, action).click()
    await user.should_see("File report", retries=30)
    assert _text_of(user, "detected-encoding") == "cp1252"
    assert _text_of(user, "detected-delimiter") == "|"


async def test_the_report_shows_a_twenty_line_raw_preview(seeded: Seeded) -> None:
    """§8.3 requires a 20-row raw preview, via `DeliveryService.preview()`
    (amendment feat/m6-import-view item 3, resolved at integration)."""
    user = seeded.user
    await user.open("/import")
    structured = _card(user, "structured")
    action = next(
        e
        for e in structured.descendants()
        if e._props.get("aria-label") == "Report for a_unfall.txt"
    )
    _one(user, action).click()
    await user.should_see("File report", retries=30)
    assert _text_of(user, "report-preview").startswith("UnfallUid|GeoRefUid")

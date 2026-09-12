"""Layer 3 — the Codelists view (sw-design.md §11.3, `design/code-feature`).

Everything below drives the **real** view through the **real** `CodelistService`
over a real migrated temp-file SQLite database. Nothing is mocked: the codelists
are D1's committed hazard fixtures (`tests/fixtures/codelists/hazards/c01..c05`)
imported through `CodelistService.import_file`, and every status, percentage and
count asserted on is `compute_coverage`'s, reached through `list_columns`.

**Two pieces of test-only plumbing, and why each is here.**

1. *The route.* `views/__init__.py` and `shell.py` belong to the integration
   step that merges this branch with G2's, so `/codelists` is still
   `placeholder_view`'s when `create_app()` returns. `codelists_view.register`
   is therefore called *after* the app is built; NiceGUI's `@ui.page` starts
   with `core.app.remove_route(path)`, so the real view replaces the
   placeholder on the same path exactly as `register_all` will once the nav
   item flips to `built=True`.

2. *The seed.* Coverage is computed from the **live EAV cells**, not from
   `census_value` (§14.2), so a fixture needs the `record`/`unfall_row` rows
   *and* the materialised `census_column` row, built from one list of values so
   the two can never drift. That is exactly what
   `tests/backend/services/codelist/conftest.py`'s `seed_enum_column` does; it
   is restated here rather than imported, because a sibling layer's conftest is
   not a module to reach into (X8 — duplication inside an owned path beats a
   shared utility four agents write to).

The seeded corpus is shaped to put one column in each of the design's three
groups, with the partial one carrying an orphan code:

| column             | values in the corpus | mapped to       | status  |
|--------------------|----------------------|-----------------|---------|
| `UnfallartAusw`    | 01, 01, 02           | `accident_type` | ok      |
| `StrassenartAusw`  | 01, 03, 03           | `road_type`     | partial |
| `WetterAusw`       | 1, 2, 1              | —               | missing |

`03` is in no attribute of c01, in any language: it is mvp-spec.md §7's
`Finding`-grade orphan, so `StrassenartAusw` is 1 of 2 labelled — 50 % — and
carries the design's danger footer.
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
from nicegui.elements.upload import Upload
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction
from tests.conftest import FrozenClock
from tests.fixtures.factories import make_census_input, make_census_table_input, seed_corpus

from ra2.domain.codelist_coverage import ColumnCoverage, CoverageStatus
from ra2.domain.ids import CorpusId, RecordId
from ra2.infra.config import Settings
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import Record, UnfallRow
from ra2.persistence.session import create_engine, create_session_factory
from ra2.services.census_materialiser import RelationalCensusMaterialiser
from ra2.services.container import Services
from ra2.ui.views import codelists_view
from ra2.ui.views.codelists_view import (
    ADD_LABEL,
    FULLY_LABELLED_PILL,
    IMPORT_FAILED_TITLE,
    IMPORT_LABEL,
    NEUTRAL_FOOTER,
    NO_CODES_PILL,
    NO_CORPUS_MESSAGE,
    NOT_MAPPED_OPTION,
    PROMPT_PREVIEW_TITLE,
    REMINDER_BODY,
    SORTED_BY_STATUS,
    group_label,
)

pytestmark = pytest.mark.ui

#: `tests/ui/` -> `tests/`.
_TESTS_ROOT = Path(__file__).resolve().parents[1]
_CODELISTS = _TESTS_ROOT / "fixtures" / "codelists" / "hazards"

CORPUS_ID = "corpus-codelists"
CORPUS_NAME = "codelists"

OK_COLUMN = "UnfallartAusw"
PARTIAL_COLUMN = "StrassenartAusw"
MISSING_COLUMN = "WetterAusw"

#: The value no attribute of c01 carries, in any language.
ORPHAN_CODE = "03"
#: How many records carry it — the number the danger footer has to name.
ORPHAN_RECORDS = 2

#: `{column: values}`, one entry per record, in record order.
SEED: dict[str, tuple[str, ...]] = {
    OK_COLUMN: ("01", "01", "02"),
    PARTIAL_COLUMN: ("01", ORPHAN_CODE, ORPHAN_CODE),
    MISSING_COLUMN: ("1", "2", "1"),
}


@dataclass(frozen=True)
class Seeded:
    user: User
    services: Services
    corpus_id: CorpusId


# --- fixtures ----------------------------------------------------------------


def codelist_bytes(hazard: str) -> bytes:
    """One committed hazard fixture, verbatim. Never `data/Codes/*.json`,
    which is gitignored and must never reach a test (§12.11)."""
    return (_CODELISTS / hazard / "codelist.json").read_bytes()


async def _seed_enum_columns(settings: Settings) -> None:
    """One corpus, three enum columns, and the EAV cells behind them.

    See the module docstring for why this exists rather than being imported.
    Both the `unfall_row` cells and the materialised `census_column` rows come
    from the same `SEED` mapping, so `coverage_counts()`'s live `GROUP BY` and
    the census's `distinct_count` can never disagree.
    """
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    record_count = len(next(iter(SEED.values())))
    try:
        async with factory() as session:
            await seed_corpus(session, CORPUS_ID, name=CORPUS_NAME, record_count=record_count)
            for index in range(record_count):
                record_id = RecordId(f"{CORPUS_ID}-r{index}")
                session.add(
                    Record(
                        id=record_id,
                        corpus_id=CorpusId(CORPUS_ID),
                        unfall_uid=f"{CORPUS_ID}-u{index}",
                        language="de",
                        language_confidence=1.0,
                    )
                )
                await session.flush()
                for column_name, values in SEED.items():
                    session.add(
                        UnfallRow(
                            record_id=record_id, column_name=column_name, value_raw=values[index]
                        )
                    )
            await session.flush()

            cells = [
                (column_name, value) for column_name, values in SEED.items() for value in values
            ]
            census = make_census_input(
                record_count=record_count,
                tables=[make_census_table_input("unfall", tuple(SEED), cells)],
            )
            materialiser = RelationalCensusMaterialiser(ids=SeededFactory(seed=7))
            await materialiser.materialise(session, CorpusId(CORPUS_ID), census)
            await session.commit()
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[Seeded]:
    """The real UI-mounted app with the corpus above, c01 imported, and two of
    its three enum columns mapped through the **real** service."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            services: Services = app.state.services
            # See the module docstring: the nav item is still `built=False`,
            # so the real view replaces the placeholder on the same path.
            codelists_view.register(services)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                await _seed_enum_columns(migrated_db)
                await services.codelist.import_file(
                    "codelist.json", codelist_bytes("c01_minimal_valid")
                )
                attributes = {a.key: a for a in await services.codelist.list_attributes()}
                await services.codelist.map_column(
                    CorpusId(CORPUS_ID), OK_COLUMN, attributes["accident_type"].code_attribute_id
                )
                await services.codelist.map_column(
                    CorpusId(CORPUS_ID), PARTIAL_COLUMN, attributes["road_type"].code_attribute_id
                )
                yield Seeded(User(client), services, CorpusId(CORPUS_ID))
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


@pytest.fixture
async def unmapped(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[Seeded]:
    """The same corpus and the same import, with **nothing mapped** — the state
    J7 starts from and the one the JSON-key dropdown acts on."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            services: Services = app.state.services
            codelists_view.register(services)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                await _seed_enum_columns(migrated_db)
                await services.codelist.import_file(
                    "codelist.json", codelist_bytes("c01_minimal_valid")
                )
                yield Seeded(User(client), services, CorpusId(CORPUS_ID))
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


@pytest.fixture
async def empty(app_factory: Callable[..., FastAPI], migrated_db: Settings) -> AsyncIterator[User]:
    """The same app with **no corpus at all** — the undesigned empty state."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            codelists_view.register(app.state.services)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                yield User(client)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


def _restore_nicegui_functions() -> None:
    from nicegui.functions.download import download
    from nicegui.functions.navigate import Navigate
    from nicegui.functions.notify import notify

    ui.navigate = Navigate()
    ui.notify = notify
    ui.download = download


# --- helpers -----------------------------------------------------------------


def _own_text(element: Element) -> str:
    """A `ui.label`'s own text. `Element` itself has no `text`, which is why
    this goes through `getattr` rather than a cast."""
    return str(getattr(element, "text", ""))


def _kids(element: Element) -> list[Element]:
    """An element's descendants in document order. `Element.descendants()` is
    an iterator, and every assertion below wants a position in it."""
    return _ordered(element.descendants())


def _ordered(elements: Iterable[Element]) -> list[Element]:
    """NiceGUI hands out ids in creation order, which is document order here."""
    return sorted(elements, key=lambda e: e.id)


def _one(user: User, element: Element) -> UserInteraction[Element]:
    return UserInteraction(user, {element}, None)


def _find(user: User, testid: str) -> list[Element]:
    return _ordered(
        e for e in user.find(kind=ui.element).elements if e._props.get("data-testid") == testid
    )


def _within(root: Element, testid: str) -> list[Element]:
    return _ordered(e for e in root.descendants() if e._props.get("data-testid") == testid)


def _rows(user: User) -> list[Element]:
    return _find(user, "codelist-row")


def _row(user: User, column_name: str) -> Element:
    (element,) = [e for e in _rows(user) if e._props.get("data-column") == column_name]
    return element


def _row_status(user: User, column_name: str) -> str:
    return str(_row(user, column_name)._props["data-status"])


def _group_labels(user: User) -> list[str]:
    return [_own_text(e) for e in _find(user, "group-label")]


def _texts(user: User, testid: str) -> list[str]:
    return [_own_text(e) for e in _find(user, testid)]


def _header_texts(user: User) -> list[str]:
    """The codes table's three column headings. A `<th>` holds its label as a
    child element, so the text is one level down."""
    return [_own_text(_kids(e)[0]) for e in _find(user, "codes-th")]


def _chip_text(user: User, name: str) -> str:
    (element,) = user.find(marker=f"chip-{name}").elements
    return " ".join(_own_text(c) for c in element.descendants()).strip()


async def _until(predicate: Callable[[], bool]) -> None:
    """Poll until `predicate()` is true.

    A click's handler is dispatched but not awaited by `UserInteraction.click`,
    so an async handler's effects are not guaranteed to be visible the instant
    `.click()` returns.
    """
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


async def _pick(user: User, chip: str, option: str) -> None:
    """Open a dropdown and choose one of its options."""
    (element,) = user.find(marker=f"chip-{chip}").elements
    _one(user, element).click()
    await _until(lambda: bool(_find(user, f"menu-{chip}")))
    button = next(e for e in _find(user, f"option-{chip}") if e._props.get("aria-label") == option)
    _one(user, button).click()
    await _until(lambda: not _find(user, f"menu-{chip}"))


async def _pick_json_key(user: User, option: str) -> None:
    """Open the edit zone's JSON-key control and choose one of its options.

    It is a `.rof` `field_select`, not a toolbar `.sl` chip, so it carries its
    own marker — the option list below it is the same panel the chips use.
    """
    (element,) = user.find(marker="json-key").elements
    _one(user, element).click()
    await _until(lambda: bool(_find(user, "menu-json-key")))
    button = next(e for e in _find(user, "option-json-key") if e._props.get("aria-label") == option)
    _one(user, button).click()


async def _upload(user: User, payload: bytes, *, filename: str) -> None:
    """Drive the real `ui.upload` the way NiceGUI's own test seam does.

    `Upload.handle_uploads` is documented as the hook "for simulating file
    uploads in tests"; the `User` fixture has no browser to pick a file with,
    so the E2E journey (J7) is what exercises the real `<input type=file>`.
    """
    _one(user, _find(user, "import-codes")[0]).click()
    await _until(lambda: bool(_find(user, "codelist-upload")))
    (element,) = [e for e in _find(user, "codelist-upload") if isinstance(e, Upload)]
    await element.handle_uploads([SmallFileUpload(filename, "application/json", payload)])


# --- the three status groups (the exit criterion) -----------------------------


async def test_the_three_status_groups_render_with_their_counts(seeded: Seeded) -> None:
    """README, Master list: rows grouped by status, "the counts live in the
    group labels", missing then partial then ok.

    Each row's group is `CoverageStatus` as the **service** classified it; this
    view only decides the heading it goes under (§8.1.1).
    """
    user = seeded.user
    await user.open("/codelists")
    await user.should_see(SORTED_BY_STATUS)

    assert _group_labels(user) == [
        group_label(CoverageStatus.MISSING, 1),
        group_label(CoverageStatus.PARTIAL, 1),
        group_label(CoverageStatus.OK, 1),
    ]
    assert _group_labels(user) == [
        "1 missing — blocks any feature using it",
        "1 partial — codes with no label",
        "1 ok — fully labelled",
    ]
    # …and the rows sit under them in that order, each carrying its status.
    assert [str(e._props["data-column"]) for e in _rows(user)] == [
        MISSING_COLUMN,
        PARTIAL_COLUMN,
        OK_COLUMN,
    ]
    assert _row_status(user, MISSING_COLUMN) == CoverageStatus.MISSING.value
    assert _row_status(user, PARTIAL_COLUMN) == CoverageStatus.PARTIAL.value
    assert _row_status(user, OK_COLUMN) == CoverageStatus.OK.value


async def test_each_group_carries_the_designs_status_marker(seeded: Seeded) -> None:
    """README: an outline `.pill` "no codes" on a missing row, a `.bar` plus a
    percentage on a partial one, an `--ok-soft` `.pill` "100 %" on an ok one."""
    user = seeded.user
    await user.open("/codelists")

    (missing,) = _find(user, "marker-missing")
    assert _own_text(_kids(missing)[0]) == NO_CODES_PILL
    assert missing._props["data-tone"] == "danger"
    assert missing in _row(user, MISSING_COLUMN).descendants()

    (ok,) = _find(user, "marker-ok")
    assert _own_text(_kids(ok)[0]) == FULLY_LABELLED_PILL
    assert ok._props["data-tone"] == "ok"
    assert ok in _row(user, OK_COLUMN).descendants()

    assert len(_find(user, "marker-partial")) == 1


async def test_the_row_subtitles_say_a_different_thing_per_group(seeded: Seeded) -> None:
    """README's `.rsub`: distinct-in-corpus while missing, "N of M labelled"
    while partial, "N codes" once ok — and "unused" throughout, since this
    fixture set seeds no `Feature` row naming any of these columns (C5:
    `used_by_features` is computed live from `feature.source_column`)."""
    user = seeded.user
    await user.open("/codelists")
    subtitles = {
        str(row._props["data-column"]): _own_text(_within(row, "row-sub")[0]) for row in _rows(user)
    }
    assert subtitles[MISSING_COLUMN] == "unfall · 2 distinct in corpus · unused"
    assert subtitles[PARTIAL_COLUMN] == "unfall · 1 of 2 labelled · unused"
    assert subtitles[OK_COLUMN] == "unfall · 2 codes · unused"


# --- the danger footer's exact copy (the exit criterion) ----------------------


async def test_the_danger_footer_names_the_unlabelled_code_and_its_records(
    seeded: Seeded,
) -> None:
    """README footer 1, verbatim for one orphan code:

    > "Code 7 appears in 31 records but has no label. The prompt cannot name
    > it, and those records score against an unnamed code."

    Both numbers are the service's: `03` and its count come straight out of
    `ColumnCoverage.codes`, where `in_codelist=False` is mvp-spec.md §7's
    `Finding`-grade case.
    """
    user = seeded.user
    await user.open("/codelists")
    _one(user, _row(user, PARTIAL_COLUMN)).click()
    await _until(lambda: bool(_find(user, "danger-footer")))

    (text,) = _texts(user, "danger-text")
    assert text == (
        f"Code {ORPHAN_CODE} appears in {ORPHAN_RECORDS} records but has no label. "
        "The prompt cannot name it, and those records score against an unnamed code."
    )

    # The orphan's own row is the design's danger row, and its label is the
    # design's copy — never an empty cell, never a repaired value (§12.6).
    (orphan,) = [e for e in _find(user, "code-row") if e._props.get("data-code") == ORPHAN_CODE]
    assert orphan._props["data-orphan"] == "true"
    assert _own_text(_within(orphan, "code-label")[0]) == "no label — not in the codelist"


async def test_the_danger_footer_is_absent_when_every_code_has_a_label(seeded: Seeded) -> None:
    """The other half: an ok column has no orphan, so footer 1 is not drawn —
    while footer 2, "read-only", is a property of *every* codelist and is."""
    user = seeded.user
    await user.open("/codelists")
    _one(user, _row(user, OK_COLUMN)).click()
    await _until(lambda: _texts(user, "detail-name") == [OK_COLUMN])

    assert _find(user, "danger-footer") == []
    assert _texts(user, "neutral-text") == [NEUTRAL_FOOTER]


async def test_add_label_is_drawn_and_inert(seeded: Seeded) -> None:
    """mvp-spec.md §7: "There is no inline label editing, and no UI path that
    writes to `code_attribute` or `code_value`". The design draws the button,
    so it is drawn — and disabled, like Census's "use as feature"."""
    user = seeded.user
    await user.open("/codelists")
    _one(user, _row(user, PARTIAL_COLUMN)).click()
    await _until(lambda: bool(_find(user, "add-label")))

    (button,) = _find(user, "add-label")
    assert button.tag == "button"
    assert "disabled" in button._props
    assert button._props["aria-disabled"] == "true"
    assert _own_text(_kids(button)[0]) == ADD_LABEL


# --- the coverage percentage (the exit criterion) -----------------------------


async def test_the_coverage_bar_reflects_the_services_percentage(seeded: Seeded) -> None:
    """README: the partial marker is a 44px `.bar` with a `--warn` fill plus a
    mono percentage.

    `StrassenartAusw` has two distinct codes in the corpus and a label for one
    of them, so `compute_coverage` reports `0.5`. The bar's fill width and the
    readout are that one number, drawn in percent — nothing here divides.
    """
    user = seeded.user
    await user.open("/codelists")

    coverage = await _coverage(seeded, PARTIAL_COLUMN)
    assert coverage.labelled_count == 1
    assert coverage.total_count == 2
    assert coverage.coverage_pct == pytest.approx(0.5)

    (readout,) = _texts(user, "coverage-pct")
    assert readout == "50.0 %"

    (track,) = _find(user, "marker-partial")
    assert track._style.get("width") == "44px"
    (fill,) = track.default_slot.children
    assert fill._style.get("width") == "50%"
    assert fill._style.get("background") == "var(--warn)"


async def test_the_codes_table_renders_one_row_per_used_code_with_its_usage(
    seeded: Seeded,
) -> None:
    """README's codes table: Code · Label (read-only) · Usage (count over
    percentage), one row per `CodeUsage`, usage-ordered by the domain."""
    user = seeded.user
    await user.open("/codelists")
    _one(user, _row(user, PARTIAL_COLUMN)).click()
    await _until(lambda: len(_find(user, "code-row")) == 2)

    coverage = await _coverage(seeded, PARTIAL_COLUMN)
    assert [str(e._props["data-code"]) for e in _find(user, "code-row")] == [
        usage.code for usage in coverage.codes
    ]
    assert _texts(user, "code-count") == [str(usage.count) for usage in coverage.codes]
    assert _texts(user, "code-share") == ["66.7 %", "33.3 %"]

    # Read-only: the label cell is text, never an input (mvp-spec.md §7).
    for label in _find(user, "code-label"):
        assert label.tag != "input"


async def test_the_labels_are_never_editable_controls(seeded: Seeded) -> None:
    """The whole edit zone holds exactly one writable control — the JSON-key
    mapping dropdown. `column_mapping` is the only editable state this feature
    introduces (sw-design.md §14.2)."""
    user = seeded.user
    await user.open("/codelists")
    _one(user, _row(user, PARTIAL_COLUMN)).click()
    await _until(lambda: bool(_find(user, "table-codes")))

    (table,) = _find(user, "table-codes")
    assert [e.tag for e in table.descendants() if e.tag in {"input", "textarea", "select"}] == []


# --- the toolbar --------------------------------------------------------------


async def test_the_toolbar_carries_three_chips_and_the_danger_chip(seeded: Seeded) -> None:
    """README, Toolbar: corpus / prompt language / status, then the danger chip.

    Its feature half is `0` and stays `0` until a feature can cite a column
    (C5, plan-phase-2.md §2) — the column half is real.
    """
    user = seeded.user
    await user.open("/codelists")

    assert _chip_text(user, "corpus") == f"corpus {CORPUS_NAME} · v1 ▼"
    assert _chip_text(user, "language") == "prompt language · de ▼"
    assert _chip_text(user, "status") == "status · all 3 ▼"

    (chip,) = _find(user, "blocking-chip")
    assert _own_text(_kids(chip)[-1]) == "1 column has no codes · blocks 0 features"


async def test_the_status_chip_filters_the_list_and_the_footer_counts_both(
    seeded: Seeded,
) -> None:
    """README: the chips filter the master list, and the footer reads
    "10 of 18 shown" — both numbers over the complete list, never a page."""
    user = seeded.user
    await user.open("/codelists")
    assert _texts(user, "shown-count") == ["3 of 3 shown"]

    await _pick(user, "status", "status · missing 1")
    await _until(lambda: len(_rows(user)) == 1)

    assert [str(e._props["data-column"]) for e in _rows(user)] == [MISSING_COLUMN]
    assert _texts(user, "shown-count") == ["1 of 3 shown"]
    assert _group_labels(user) == [group_label(CoverageStatus.MISSING, 1)]
    # The header still names every column in the corpus, not the filtered set.
    assert _texts(user, "columns-count") == ["3 columns"]


async def test_the_prompt_language_chip_re_reads_the_coverage(seeded: Seeded) -> None:
    """The status is **per language** (§14.2), so changing the chip is a
    re-read of `list_columns(language=…)`, not a redraw of what is held.

    c01 labels every code in every language, so `it` leaves the statuses where
    `de` had them — what this pins is that the view asked the service again
    with the new language, which the edit zone's column header shows.
    """
    user = seeded.user
    await user.open("/codelists")
    _one(user, _row(user, PARTIAL_COLUMN)).click()
    await _until(lambda: bool(_find(user, "table-codes")))
    assert _header_texts(user)[1] == "Label · de (prompt)"

    await _pick(user, "language", "prompt language · it")
    await _until(lambda: _header_texts(user)[1] == "Label · it (prompt)")

    assert _chip_text(user, "language") == "prompt language · it ▼"
    assert _row_status(user, PARTIAL_COLUMN) == CoverageStatus.PARTIAL.value


async def test_the_language_chips_in_the_edit_zone_set_the_same_language(
    seeded: Seeded,
) -> None:
    """README draws `Labels de | fr | it` beside the toolbar's prompt-language
    chip. One fact, two controls — two independent ones would let the list's
    statuses and the codes table's labels disagree about the language."""
    user = seeded.user
    await user.open("/codelists")
    (french,) = user.find(marker="language-fr").elements
    _one(user, french).click()
    await _until(lambda: _chip_text(user, "language") == "prompt language · fr ▼")

    (active,) = [e for e in _find(user, "language-chip") if e._props["aria-pressed"] == "true"]
    assert active._props["data-language"] == "fr"


# --- the edit zone ------------------------------------------------------------


async def test_selecting_a_row_loads_it_into_the_edit_zone(seeded: Seeded) -> None:
    """README, Interactions: "selecting a row loads it into the edit zone",
    and the selected row is the tinted one."""
    user = seeded.user
    await user.open("/codelists")
    _one(user, _row(user, OK_COLUMN)).click()
    await _until(lambda: _texts(user, "detail-name") == [OK_COLUMN])

    row = _row(user, OK_COLUMN)
    assert row._props["aria-pressed"] == "true"
    assert row._style.get("background") == "var(--accent-soft)"
    assert row._style.get("border-left") == "2px solid var(--accent)"
    assert _texts(user, "detail-sub") == ["unfall · 2 codes · unused"]
    assert _texts(user, "detail-mapping") == ["mapped to accident_type · 2 keys, 2 mapped"]


async def test_the_prompt_preview_and_reminder_cards_render(seeded: Seeded) -> None:
    """README's two cards below the codes table. The preview is assembled from
    what is already on screen — it is a display of the codelist, deliberately
    not a second implementation of the phase-3 prompt builder."""
    user = seeded.user
    await user.open("/codelists")
    _one(user, _row(user, OK_COLUMN)).click()
    await _until(lambda: _texts(user, "detail-name") == [OK_COLUMN])

    await user.should_see(PROMPT_PREVIEW_TITLE)
    await user.should_see(REMINDER_BODY)
    (preview,) = _texts(user, "prompt-preview")
    assert preview.splitlines() == [
        "accident_type — enum. Emit the code.",
        "01 = Auffahren",
        "02 = Frontalkollision",
    ]


async def test_an_unmapped_column_offers_the_mapping_dropdown_and_no_codes(
    unmapped: Seeded,
) -> None:
    """A column with no `column_mapping` row has no codes to show, so the edit
    zone says so rather than drawing an empty table — and still offers the one
    control that fixes it."""
    user = unmapped.user
    await user.open("/codelists")
    await _until(lambda: bool(_find(user, "codes-empty")))

    assert _find(user, "table-codes") == []
    assert _texts(user, "detail-mapping") == ["not mapped · 2 keys, 0 mapped"]
    (select,) = _find(user, "json-key")
    assert _own_text(_kids(select)[0]) == NOT_MAPPED_OPTION


async def test_mapping_a_column_through_the_dropdown_moves_it_out_of_missing(
    unmapped: Seeded,
) -> None:
    """The JSON-key dropdown **is** the mapping control (README).

    Picking a key calls `CodelistService.map_column` and nothing else — the
    code table is never touched (mvp-spec.md §7) — and the row then carries
    the status the service computes for the new mapping.
    """
    user = unmapped.user
    await user.open("/codelists")
    await _until(lambda: len(_rows(user)) == 3)
    assert _row_status(user, OK_COLUMN) == CoverageStatus.MISSING.value

    _one(user, _row(user, OK_COLUMN)).click()
    await _until(lambda: _texts(user, "detail-name") == [OK_COLUMN])
    await _pick_json_key(user, "accident_type 2")
    await _until(lambda: _row_status(user, OK_COLUMN) == CoverageStatus.OK.value)

    assert _group_labels(user) == [
        group_label(CoverageStatus.MISSING, 2),
        group_label(CoverageStatus.OK, 1),
    ]
    # The service agrees — the mapping is a row, not a rendering.
    coverage = await _coverage(unmapped, OK_COLUMN)
    assert coverage.status is CoverageStatus.OK


async def test_unmapping_a_column_puts_it_back_into_missing(seeded: Seeded) -> None:
    """The dropdown's first entry is `CodelistService.unmap_column` — a
    mis-mapped column has to be correctable, and `column_mapping` is the only
    editable state this feature introduces (§14.2)."""
    user = seeded.user
    await user.open("/codelists")
    _one(user, _row(user, OK_COLUMN)).click()
    await _until(lambda: _texts(user, "detail-name") == [OK_COLUMN])

    await _pick_json_key(user, NOT_MAPPED_OPTION)
    await _until(lambda: _row_status(user, OK_COLUMN) == CoverageStatus.MISSING.value)

    columns = {
        c.column_name: c
        for c in await seeded.services.codelist.list_columns(seeded.corpus_id, language="de")
    }
    assert columns[OK_COLUMN].mapping_id is None


# --- import (sw-design.md §14.1) ----------------------------------------------


async def test_importing_a_codelist_offers_its_attributes_as_json_keys(
    unmapped: Seeded, frozen_clock: FrozenClock
) -> None:
    """ "Import Codes as JSON" takes **one file for all columns** (§14.1), and
    the keys it carries are what the mapping dropdown then offers.

    The clock is advanced first because `get_latest_import()` orders on
    `imported_at` alone: under the test `FrozenClock` a second import lands on
    the same instant as the first and the tie is resolved arbitrarily. That is
    a property of the repository's ordering, not of this view — noted here so
    the second import in this test is unambiguously the later one.
    """
    user = unmapped.user
    await user.open("/codelists")
    await _until(lambda: bool(_find(user, "import-codes")))
    (button,) = _find(user, "import-codes")
    assert _own_text(_kids(button)[-1]) == IMPORT_LABEL
    frozen_clock.advance(seconds=60)

    await _upload(user, codelist_bytes("c05_orphan_corpus_value"), filename="c05.json")
    # c05 holds one attribute where c01 held two, so the header line counting
    # the file's keys is what settles when the import has landed and redrawn.
    await _until(lambda: _texts(user, "detail-mapping") == ["not mapped · 1 keys, 0 mapped"])

    attributes = {a.key for a in await unmapped.services.codelist.list_attributes()}
    assert attributes == {"weather"}

    # …and the column whose corpus values c05 actually covers can now be mapped
    # to it, straight out of the file just uploaded.
    _one(user, _row(user, MISSING_COLUMN)).click()
    await _until(lambda: _texts(user, "detail-name") == [MISSING_COLUMN])
    await _pick_json_key(user, "weather 3")
    await _until(lambda: _row_status(user, MISSING_COLUMN) == CoverageStatus.OK.value)


async def test_a_structurally_invalid_import_is_refused_and_writes_nothing(
    unmapped: Seeded,
) -> None:
    """c04: one attribute has no `codes` key, so the **whole** import fails
    (§14.1 step 1, Do-NOT #6 — no partial import, no best-effort skipping).

    The surface is undesigned (README, "Loading / empty / error"), and this is
    the same judgment `import_view` makes for a refused freeze: a list the
    analyst has to read is a dialog, not a toast.
    """
    user = unmapped.user
    await user.open("/codelists")
    before = await unmapped.services.codelist.list_attributes()

    await _upload(user, codelist_bytes("c04_missing_codes_key"), filename="c04.json")
    await _until(lambda: bool(_find(user, "import-failed")))

    assert _texts(user, "import-failed-title") == [IMPORT_FAILED_TITLE]
    assert _texts(user, "import-error-key") == ["weather"]
    assert _texts(user, "import-error")  # at least one error is listed

    # Nothing was written: the previous generation is still the current one.
    after = await unmapped.services.codelist.list_attributes()
    assert [a.key for a in after] == [a.key for a in before]


# --- the undesigned empty state ----------------------------------------------


async def test_a_view_with_no_corpus_says_so(empty: User) -> None:
    """Undesigned (README, "Loading / empty / error"): one centred line, and
    **no codelist column call at all** — there is no corpus id to make one
    with, so no chip has anything to name."""
    await empty.open("/codelists")
    await empty.should_see(NO_CORPUS_MESSAGE)
    assert _find(empty, "chip") == []
    assert _rows(empty) == []


# --- reading the service back -------------------------------------------------


async def _coverage(seeded: Seeded, column_name: str) -> ColumnCoverage:
    """The service's own answer for one column, so an assertion about a number
    on screen can be checked against the number that produced it."""
    columns = await seeded.services.codelist.list_columns(seeded.corpus_id, language="de")
    column = next(c for c in columns if c.column_name == column_name)
    assert column.coverage is not None
    return column.coverage

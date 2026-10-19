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
from datetime import datetime, timedelta
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
from tests.fixtures.factories import NOW, make_census_input, make_census_table_input, seed_corpus

from ra2.domain.codelist_coverage import ColumnCoverage, CoverageStatus
from ra2.domain.codelist_suggest import SuggestionSource
from ra2.domain.ids import CodeAttributeId, CorpusId, RecordId
from ra2.infra.config import Settings
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import Record, UnfallRow
from ra2.persistence.session import create_engine, create_session_factory
from ra2.services.census_materialiser import RelationalCensusMaterialiser
from ra2.services.container import Services
from ra2.services.readmodels import CodeAttributeView, ColumnMappingView
from ra2.ui.views import codelists_view
from ra2.ui.views.codelists_view import (
    ADD_LABEL,
    AUTOMAP_APPLY,
    AUTOMAP_NOTHING,
    FULLY_LABELLED_PILL,
    IMPORT_FAILED_TITLE,
    IMPORT_LABEL,
    KEY_SEARCH_PLACEHOLDER,
    NEUTRAL_FOOTER,
    NO_CODES_PILL,
    NO_COLUMNS_MESSAGE,
    NO_CORPUS_MESSAGE,
    NOT_MAPPED_OPTION,
    PROMPT_PREVIEW_TITLE,
    REMINDER_BODY,
    SORTED_BY_STATUS,
    automap_applied_message,
    group_label,
    key_search_text,
    matches_query,
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


#: The `two_tables` fixture's one `person` column — unmapped, so `missing`.
PERSON_COLUMN = "VerletzungAusw"
PERSON_SEED: dict[str, tuple[str, ...]] = {PERSON_COLUMN: ("1", "2", "1")}


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


async def _seed_enum_columns(
    settings: Settings,
    *,
    with_person: bool = False,
    corpus_id: str = CORPUS_ID,
    version: int = 1,
    imported_at: datetime = NOW,
) -> None:
    """One corpus, three enum columns, and the EAV cells behind them.

    See the module docstring for why this exists rather than being imported.
    Both the `unfall_row` cells and the materialised `census_column` rows come
    from the same `SEED` mapping, so `coverage_counts()`'s live `GROUP BY` and
    the census's `distinct_count` can never disagree.

    `corpus_id` / `version` / `imported_at` let a test freeze a second
    version of the same corpus (Automap's copy source) beside the first.

    `with_person=True` adds `PERSON_SEED`'s column to the census as a `person`
    table column — census only, no EAV cells: it stays unmapped, so nothing
    ever runs its `GROUP BY`, and the table filter needs a second table name,
    not a second table's coverage.
    """
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    record_count = len(next(iter(SEED.values())))
    try:
        async with factory() as session:
            await seed_corpus(
                session,
                corpus_id,
                name=CORPUS_NAME,
                version=version,
                imported_at=imported_at,
                record_count=record_count,
            )
            for index in range(record_count):
                record_id = RecordId(f"{corpus_id}-r{index}")
                session.add(
                    Record(
                        id=record_id,
                        corpus_id=CorpusId(corpus_id),
                        unfall_uid=f"{corpus_id}-u{index}",
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
            tables = [make_census_table_input("unfall", tuple(SEED), cells)]
            if with_person:
                person_cells = [
                    (column_name, value)
                    for column_name, values in PERSON_SEED.items()
                    for value in values
                ]
                tables.append(make_census_table_input("person", tuple(PERSON_SEED), person_cells))
            census = make_census_input(record_count=record_count, tables=tables)
            # One seed per version, so two corpora's census rows never share an id.
            materialiser = RelationalCensusMaterialiser(ids=SeededFactory(seed=7 + version))
            await materialiser.materialise(session, CorpusId(corpus_id), census)
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
async def two_tables(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[Seeded]:
    """`seeded`, plus one unmapped enum column in `person` — the table chip
    needs a second table name to have anything to choose between."""
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
                await _seed_enum_columns(migrated_db, with_person=True)
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


#: Automap's copy source: version 1 of `CORPUS_NAME`, frozen a day before
#: `CORPUS_ID` — which, as version 2 and the newest, is the one the view opens.
PREVIOUS_ID = "corpus-codelists-v1"


@pytest.fixture
async def two_versions(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[Seeded]:
    """`unmapped`'s corpus as version 2, beside a version 1 whose ok and
    partial columns are mapped — the state "Automap…" copies from."""
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
                await _seed_enum_columns(
                    migrated_db,
                    corpus_id=PREVIOUS_ID,
                    version=1,
                    imported_at=NOW - timedelta(days=1),
                )
                await _seed_enum_columns(migrated_db, version=2)
                await services.codelist.import_file(
                    "codelist.json", codelist_bytes("c01_minimal_valid")
                )
                attributes = {a.key: a for a in await services.codelist.list_attributes()}
                await services.codelist.map_column(
                    CorpusId(PREVIOUS_ID), OK_COLUMN, attributes["accident_type"].code_attribute_id
                )
                await services.codelist.map_column(
                    CorpusId(PREVIOUS_ID), PARTIAL_COLUMN, attributes["road_type"].code_attribute_id
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


# --- the JSON-key popover (plan-codelists-usability.md §2) ---------------------


async def _open_json_key(user: User, column_name: str) -> Element:
    _one(user, _row(user, column_name)).click()
    await _until(lambda: _texts(user, "detail-name") == [column_name])
    (field,) = user.find(marker="json-key").elements
    _one(user, field).click()
    await _until(lambda: bool(_find(user, "json-key-popover")))
    (popover,) = _find(user, "json-key-popover")
    return popover


async def test_the_json_key_popover_opens_with_a_search_field(unmapped: Seeded) -> None:
    """Amended README: a search field over the options, "— not mapped —"
    pinned first, and the popover anchored to the field's right edge so it
    opens leftwards, inside the pane."""
    user = unmapped.user
    await user.open("/codelists")
    popover = await _open_json_key(user, OK_COLUMN)

    assert popover._style.get("right") == "0"
    assert popover._style.get("width") == "440px"
    (search,) = _within(popover, "json-key-search")
    assert search._props["placeholder"] == KEY_SEARCH_PLACEHOLDER
    options = _within(popover, "option-json-key")
    assert [str(o._props["aria-label"]) for o in options] == [
        NOT_MAPPED_OPTION,
        "accident_type 2",
        "road_type 2",
    ]


def _details(popover: Element) -> list[list[tuple[str, str]]]:
    """Each option's second line as `(text, colour)` pieces — the README
    draws the name in `--ink2` and the chapter in `--ink3`."""
    return [
        [(_own_text(piece), str(piece._style.get("color"))) for piece in _kids(line)]
        for line in _within(popover, "json-key-details")
    ]


async def test_each_key_option_names_its_attribute_and_chapter(unmapped: Seeded) -> None:
    """The second line is the attribute's name **in the prompt language**,
    then its chapter — the words an analyst recognises when the key is an
    English identifier and the column is German."""
    user = unmapped.user
    await user.open("/codelists")
    popover = await _open_json_key(user, OK_COLUMN)
    assert _details(popover) == [
        [("Unfallart", "var(--ink2)"), (" · 4.1.1", "var(--ink3)")],
        [("Strassenart", "var(--ink2)"), (" · 4.1.2", "var(--ink3)")],
    ]

    await _pick(user, "language", "prompt language · fr")
    popover = await _open_json_key(user, OK_COLUMN)
    assert [[text for text, _ in line] for line in _details(popover)] == [
        ["Type d'accident", " · 4.1.1"],
        ["Type de route", " · 4.1.2"],
    ]


async def test_every_key_option_carries_its_search_text_but_not_mapped_does_not(
    unmapped: Seeded,
) -> None:
    """The browser filters on `data-search`; an option without one is never
    hidden, which is how "— not mapped —" stays pinned."""
    user = unmapped.user
    await user.open("/codelists")
    popover = await _open_json_key(user, OK_COLUMN)
    by_label = {str(o._props["aria-label"]): o for o in _within(popover, "option-json-key")}

    assert "data-search" not in by_label[NOT_MAPPED_OPTION]._props
    assert by_label["road_type 2"]._props["data-search"] == (
        "road_type strassenart type de route tipo di strada 4.1.2"
    )


async def test_escape_in_the_key_search_closes_the_popover(unmapped: Seeded) -> None:
    """Escape is the one key the browser sends back: the popover closes and
    nothing is mapped."""
    user = unmapped.user
    await user.open("/codelists")
    popover = await _open_json_key(user, OK_COLUMN)
    (search,) = _within(popover, "json-key-search")

    _one(user, search).trigger("keydown")
    await _until(lambda: not _find(user, "json-key-popover"))
    assert _row_status(user, OK_COLUMN) == CoverageStatus.MISSING.value


# --- automap (plan-codelists-usability.md §4.3) --------------------------------


def _automap_rows(user: User) -> dict[str, Element]:
    return {str(e._props["data-column"]): e for e in _find(user, "automap-row")}


async def _open_automap(user: User) -> None:
    _one(user, _find(user, "automap")[0]).click()
    await _until(lambda: bool(_find(user, "table-automap")) or bool(_find(user, "automap-empty")))


async def test_automap_pre_ticks_the_copied_mappings_of_unmapped_columns(
    two_versions: Seeded,
) -> None:
    """Version 1 mapped the ok and partial columns; version 2 maps nothing.
    Both copies are offered and ticked; `WetterAusw` (`1`, `2`) sits in no
    attribute of c01 (whose codes are `01`, `02`), so nothing is proposed for
    it — and the dialog names the corpus it copied from."""
    user = two_versions.user
    await user.open("/codelists")
    await _open_automap(user)

    rows = _automap_rows(user)
    assert set(rows) == {OK_COLUMN, PARTIAL_COLUMN}
    assert {c: r._props["data-source"] for c, r in rows.items()} == {
        OK_COLUMN: SuggestionSource.COPIED.value,
        PARTIAL_COLUMN: SuggestionSource.COPIED.value,
    }
    assert {c: r._props["data-checked"] for c, r in rows.items()} == {
        OK_COLUMN: "true",
        PARTIAL_COLUMN: "true",
    }
    assert _chip_text(user, "automap-source") == f"from corpus {CORPUS_NAME} · v1 ▼"
    # The key alone is an English identifier; its name is what the analyst checks.
    assert [_own_text(e) for e in _within(rows[OK_COLUMN], "automap-name")] == ["Unfallart"]
    (apply,) = _find(user, "automap-apply")
    assert _own_text(_kids(apply)[0]) == f"{AUTOMAP_APPLY} (2)"


async def test_applying_maps_only_the_ticked_rows(two_versions: Seeded) -> None:
    user = two_versions.user
    await user.open("/codelists")
    await _open_automap(user)

    (box,) = _within(_automap_rows(user)[PARTIAL_COLUMN], "automap-check")
    _one(user, box).trigger("change")
    await _until(lambda: _automap_rows(user)[PARTIAL_COLUMN]._props["data-checked"] == "false")
    _one(user, _find(user, "automap-apply")[0]).click()
    await user.should_see(automap_applied_message(1))

    await _until(lambda: _row_status(user, OK_COLUMN) == CoverageStatus.OK.value)
    assert _row_status(user, PARTIAL_COLUMN) == CoverageStatus.MISSING.value
    mapped = {
        c.column_name: c.mapped_attribute.key if c.mapped_attribute else None
        for c in await two_versions.services.codelist.list_columns(
            two_versions.corpus_id, language="de"
        )
    }
    assert mapped == {OK_COLUMN: "accident_type", PARTIAL_COLUMN: None, MISSING_COLUMN: None}


async def test_cancelling_automap_maps_nothing(two_versions: Seeded) -> None:
    user = two_versions.user
    await user.open("/codelists")
    await _open_automap(user)
    _one(user, _find(user, "automap-cancel")[0]).click()

    columns = await two_versions.services.codelist.list_columns(
        two_versions.corpus_id, language="de"
    )
    assert all(c.mapping_id is None for c in columns)


async def test_automap_with_nothing_to_propose_says_so(seeded: Seeded) -> None:
    """One corpus, so nothing to copy; c01's two attributes share their
    codes, so overlap ties everywhere and proposes nothing either."""
    user = seeded.user
    await user.open("/codelists")
    await _open_automap(user)
    assert _texts(user, "automap-empty") == [AUTOMAP_NOTHING]
    (apply,) = _find(user, "automap-apply")
    assert "disabled" in apply._props


def test_key_search_text_is_folded_over_every_language() -> None:
    attribute = CodeAttributeView(
        code_attribute_id=CodeAttributeId("a1"),
        key="Road_Type",
        chapter="4.1.2",
        name={"de": "Straße", "fr": "Chaussée"},
        code_count=2,
    )
    assert key_search_text(attribute) == "road_type strasse chaussee 4.1.2"


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


# --- filtering the list (plan-codelists-usability.md §3) ----------------------


def _shown_columns(user: User) -> list[str]:
    return [str(e._props["data-column"]) for e in _rows(user)]


async def _search(user: User, text: str) -> None:
    """Type into the search field the way the browser's `input` event does."""
    (field,) = _find(user, "column-search")
    _one(user, field).trigger("input", args=text)


async def test_the_table_chip_offers_the_tables_the_rows_name(two_tables: Seeded) -> None:
    """Amended README, Toolbar: the options are the tables the service
    returned rows for, each with its live count — never a fixed list, so
    `objekt`, which this corpus has no enum column in, is not offered."""
    user = two_tables.user
    await user.open("/codelists")
    assert _chip_text(user, "table") == "table · all 4 ▼"

    (chip,) = user.find(marker="chip-table").elements
    _one(user, chip).click()
    await _until(lambda: bool(_find(user, "menu-table")))
    assert [str(e._props["aria-label"]) for e in _find(user, "option-table")] == [
        "table · all 4",
        "table · person 1",
        "table · unfall 3",
    ]


async def test_picking_a_table_narrows_the_list_and_the_status_counts(
    two_tables: Seeded,
) -> None:
    """A chip's count is the number of rows it would leave on screen, so the
    status chip counts over the table already picked — while the header and
    the danger chip still describe the whole corpus."""
    user = two_tables.user
    await user.open("/codelists")

    await _pick(user, "table", "table · person 1")
    await _until(lambda: _shown_columns(user) == [PERSON_COLUMN])

    assert _chip_text(user, "table") == "table · person 1 ▼"
    assert _chip_text(user, "status") == "status · all 1 ▼"
    assert _texts(user, "shown-count") == ["1 of 4 shown"]
    assert _texts(user, "columns-count") == ["4 columns"]
    (blocking,) = _find(user, "blocking-chip")
    assert _own_text(_kids(blocking)[-1]) == "2 columns have no codes · blocks 0 features"
    # The edit zone follows: the first row shown is loaded, never a hidden one.
    assert _texts(user, "detail-name") == [f"person.{PERSON_COLUMN}"]


async def test_the_table_and_status_chips_combine(two_tables: Seeded) -> None:
    """Both filters apply at once, and each one's counts honour the other."""
    user = two_tables.user
    await user.open("/codelists")
    await _pick(user, "status", "status · missing 2")
    await _until(lambda: len(_rows(user)) == 2)
    assert _chip_text(user, "table") == "table · all 2 ▼"

    await _pick(user, "table", "table · unfall 1")
    await _until(lambda: _shown_columns(user) == [MISSING_COLUMN])


async def test_the_search_field_filters_by_column_name(seeded: Seeded) -> None:
    """Case-insensitive, on the name as the census stored it."""
    user = seeded.user
    await user.open("/codelists")
    await _search(user, "strassen")
    await _until(lambda: _shown_columns(user) == [PARTIAL_COLUMN])

    assert _texts(user, "shown-count") == ["1 of 3 shown"]
    assert _chip_text(user, "status") == "status · all 1 ▼"


async def test_the_search_field_also_matches_the_mapped_key(seeded: Seeded) -> None:
    """`accident_type` is nowhere in `UnfallartAusw`'s name; it is the key
    the column is mapped to, which is what an analyst who knows the codelist
    types."""
    user = seeded.user
    await user.open("/codelists")
    await _search(user, "ACCIDENT")
    await _until(lambda: _shown_columns(user) == [OK_COLUMN])


async def test_a_search_matching_nothing_says_so(seeded: Seeded) -> None:
    user = seeded.user
    await user.open("/codelists")
    await _search(user, "no-such-column")
    await _until(lambda: _rows(user) == [])

    assert _texts(user, "list-empty") == [NO_COLUMNS_MESSAGE]
    assert _texts(user, "shown-count") == ["0 of 3 shown"]


async def test_the_search_field_survives_the_redraw_it_causes(seeded: Seeded) -> None:
    """The list re-filters on every (throttled) keystroke. Were the field
    rebuilt with it, the browser would drop its focus and caret mid-word, so
    it must be the *same* element afterwards — and clearing it shows every
    row again."""
    user = seeded.user
    await user.open("/codelists")
    (before,) = _find(user, "column-search")

    await _search(user, "wetter")
    await _until(lambda: _shown_columns(user) == [MISSING_COLUMN])
    (after,) = _find(user, "column-search")
    assert after is before

    await _search(user, "")
    await _until(lambda: len(_rows(user)) == 3)


def _view(column_name: str, *, table: str = "unfall", key: str | None = None) -> ColumnMappingView:
    attribute = (
        CodeAttributeView(
            code_attribute_id=CodeAttributeId("a1"), key=key, chapter=None, name={}, code_count=0
        )
        if key is not None
        else None
    )
    return ColumnMappingView(
        corpus_id=CorpusId(CORPUS_ID),
        table_name=table,
        column_name=column_name,
        distinct_in_corpus=0,
        mapping_id=None,
        mapped_attribute=attribute,
        coverage=None,
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", True),
        ("   ", True),
        ("strasse", True),
        ("STRASSENART", True),
        ("person.", False),
        ("chaussee", True),  # the mapped key is spelt `chaussée`
        ("CHAUSSÉE", True),
        ("weather", False),
    ],
)
def test_matches_query_folds_case_and_accents(query: str, expected: bool) -> None:
    column = _view("StrassenartAusw", key="type_de_chaussée")
    assert matches_query(column, query) is expected


def test_matches_query_reads_the_table_qualified_name() -> None:
    """`person.` narrows to one table the way the screen writes the name."""
    assert matches_query(_view(PERSON_COLUMN, table="person"), "person.verl")
    assert not matches_query(_view(OK_COLUMN), "person.")


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

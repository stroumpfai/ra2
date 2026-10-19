"""J7 — codelists: import, map, cover (sw-design.md §11.5, §14).

> A corpus with an unmapped `enum` column shows it under "missing — blocks any
> feature using it". Upload one codelist JSON through the UI, point the
> column's JSON key at an attribute in it, and the row leaves "missing" for the
> status its real coverage earns.

The first journey that touches Codelists at all, and the first that exercises
`CodelistService.import_file` / `map_column` through a real browser against a
real server.

**How the corpus is seeded.** Through the Import view, exactly as J1 and J2 do
— register the committed hazard delivery, then "Create corpus". plan-phase-2.md
§2's Q2 note says J7/J8 "seed state through the API"; driving the *delivery*
through the API is not actually available (`POST /api/v1/deliveries` intake is
not a seeding shortcut a browser session can drive without leaving the page),
and J1/J2 already establish the UI as this layer's seeding path. What J7 adds
over them is everything after the corpus exists, which is the part of the
sentence that is new.

**One piece of test-only plumbing.** `shell.NAV_ITEMS`'s `codelists` entry is
still `built=False` and `views/register_all` still routes `/codelists` to
`placeholder_view`: flipping that flag and adding the wiring line is the
integration step that merges this branch with the Features view's, deliberately
made once and centrally rather than twice. So this module registers the real
view on the running server's own `Services` before the journey starts.
NiceGUI's `@ui.page` begins with `core.app.remove_route(path)`, so the real
view replaces the placeholder on the same path — which is precisely what
`register_all` will do once the flag flips, and the journey below is unchanged
by that.

**The fixtures.** `h08_all_empty_column/unfall.txt` is three accident records
whose `*Ausw` columns the census types as `enum` (`infer_type_hint`: the suffix
decides). `Witter0Ausw` holds `6` in all three. `c05_orphan_corpus_value`'s
`weather` attribute carries codes `1`, `2` and `6` — so mapping that column to
that attribute makes every code appearing in the corpus labelled, and the row
earns **ok**, not merely "no longer missing".
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

from ra2.infra.config import Settings

pytestmark = pytest.mark.e2e

#: `tests/e2e/` -> `tests/`.
_TESTS = Path(__file__).resolve().parents[1]
_HAZARDS = _TESTS / "fixtures" / "deliveries" / "hazards"
_CODELISTS = _TESTS / "fixtures" / "codelists" / "hazards"

#: The codelist uploaded through the UI, and the attribute it carries.
CODELIST = _CODELISTS / "c05_orphan_corpus_value" / "codelist.json"
ATTRIBUTE_KEY = "weather"
#: `weather` has three codes, which is what the dropdown option reads.
ATTRIBUTE_OPTION = f"{ATTRIBUTE_KEY} 3"

#: The column this journey maps. Its only value in the corpus is `6`, which
#: `weather` labels — so the mapping takes it all the way to `ok`.
COLUMN = "Witter0Ausw"
#: A second enum column, whose value (`8`) `weather` does **not** carry. It is
#: left unmapped, so "the row moved" is a statement about one row and not about
#: the whole list being redrawn.
UNTOUCHED_COLUMN = "VortrittAusw"

CORPUS_NAME = "j7-delivery"

ROW = '[data-testid="codelist-row"]'


@pytest.fixture
def delivery_root(tmp_path: Path, e2e_settings: Settings) -> Path:
    """One `unfall` file, registered in place. Filenames are arbitrary on
    purpose: kind and canton come from the data (§12.5)."""
    # Under the server's import root, one directory per test: a host path
    # anywhere else is refused (SD49), and the root is shared by the session.
    root = e2e_settings.import_root_path / tmp_path.name / CORPUS_NAME
    root.mkdir(parents=True)
    (root / "one.txt").write_bytes((_HAZARDS / "h08_all_empty_column" / "unfall.txt").read_bytes())
    return root


@pytest.fixture(scope="session")
def codelists_route(server_url: str) -> str:
    """Register the real Codelists view on the running server's `Services`.

    See the module docstring for why this is here rather than in
    `views/register_all`. The app object is reached through the uvicorn server
    NiceGUI itself keeps a handle on (`ui.run_with` sets `Server.instance` from
    the loaded app), walking out of the proxy-headers wrapper to the `FastAPI`
    that `create_app()` put `state.services` on.
    """
    from nicegui.server import Server

    from ra2.ui.views import codelists_view

    candidate = Server.instance.config.loaded_app
    while candidate is not None:
        state = getattr(candidate, "state", None)
        services = getattr(state, "services", None)
        if services is not None:
            codelists_view.register(services)
            return f"{server_url}/codelists"
        candidate = getattr(candidate, "app", None)
    raise AssertionError("the running E2E server exposes no Services to register against")


def _seed_corpus(page: Page, server_url: str, root: Path, *, name: str = CORPUS_NAME) -> None:
    """Register the delivery and freeze it, through the Import UI (J1's path).

    `name` is the delivery folder's name, which the corpus is frozen under.
    """
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="file-grid"]')
    page.click('[aria-label="Add set"]')
    page.fill('[data-testid="host-path"]', str(root))
    page.click('[data-testid="register-delivery"]')
    expect(page.locator('[data-testid="filename"]')).to_have_count(1, timeout=15_000)
    page.click('[data-testid="create-corpus"]')
    expect(page.locator('[data-testid="table-corpora"] tbody tr', has_text=name)).to_have_count(
        1, timeout=15_000
    )


def _select_corpus(page: Page, *, name: str = CORPUS_NAME) -> None:
    """Name the corpus explicitly rather than trusting the default.

    The E2E server is session-scoped and J1 legitimately leaves corpora behind,
    so the chip's "most recently imported" default is not this journey's to
    assume.
    """
    page.click('[data-chip="corpus"]')
    page.click(f'[data-testid="option-corpus"][aria-label^="corpus {name} "]')
    # Wait for the **menu** to go, not for the chip's text: the chip may
    # already read the right corpus (it defaults to the newest), so its text
    # settles before the re-render the pick triggers has reached the browser —
    # and a click that lands on the pre-render DOM is lost.
    expect(page.locator('[data-testid="menu-corpus"]')).to_have_count(0)
    expect(page.locator('[data-chip="corpus"]')).to_contain_text(f"corpus {name} · v1")


def _open_import(page: Page) -> None:
    """Open the "Import Codes as JSON" dialog, with the same guard: the button
    lives in a pane the view re-renders, so the dialog is what settles it."""
    page.click('[data-testid="import-codes"]')
    expect(page.locator('[data-testid="codelist-upload"]')).to_be_visible(timeout=15_000)


def test_an_unmapped_enum_column_gains_its_codes(
    page: Page, server_url: str, codelists_route: str, delivery_root: Path
) -> None:
    _seed_corpus(page, server_url, delivery_root)

    # --- the column starts under "missing" ----------------------------------
    # Through the nav, not a `goto`: the analyst walks there from the corpus
    # they just created, in the same session.
    page.click('[data-testid="nav-codelists"]')
    page.wait_for_selector(ROW)
    _select_corpus(page)

    row = page.locator(f'{ROW}[data-column="{COLUMN}"]')
    expect(row).to_have_attribute("data-status", "missing")
    expect(row.locator('[data-testid="marker-missing"]')).to_contain_text("no codes")
    # …and the toolbar's danger chip counts it, with the feature half at zero
    # until a feature can cite a column (C5, plan-phase-2.md §2).
    expect(page.locator('[data-testid="blocking-chip"]')).to_contain_text("blocks 0 features")

    # --- upload one codelist JSON, for every column -------------------------
    _open_import(page)
    page.set_input_files('[data-testid="codelist-upload"] input[type="file"]', str(CODELIST))
    # The import is a single transaction (§14.1): the dialog closes only once
    # the whole file has been validated and written.
    expect(page.locator('[data-testid="import-dialog"]')).not_to_be_visible(timeout=15_000)
    expect(page.locator('[data-testid="import-failed"]')).to_have_count(0)

    # An import maps nothing on its own — "unmapped columns show as no codes"
    # (README, Interactions).
    expect(row).to_have_attribute("data-status", "missing")

    # --- map the column to a key in the file --------------------------------
    row.click()
    expect(page.locator('[data-testid="detail-name"]')).to_have_text(COLUMN)
    page.click('[data-testid="json-key"]')
    page.click(f'[data-testid="option-json-key"][aria-label="{ATTRIBUTE_OPTION}"]')

    # --- the row leaves "missing" for the status its coverage earns ---------
    moved = page.locator(f'{ROW}[data-column="{COLUMN}"]')
    expect(moved).to_have_attribute("data-status", "ok", timeout=15_000)
    expect(moved.locator('[data-testid="marker-ok"]')).to_contain_text("100 %")
    expect(page.locator('[data-testid="group-label"][data-status="ok"]')).to_contain_text(
        "1 ok — fully labelled"
    )

    # The edit zone now shows the codes themselves, read-only, and says where
    # they came from.
    expect(page.locator('[data-testid="detail-mapping"]')).to_contain_text(
        f"mapped to {ATTRIBUTE_KEY} in codelist.json"
    )
    expect(page.locator('[data-testid="table-codes"] [data-testid="code-row"]')).to_have_count(1)
    expect(page.locator('[data-testid="code-label"]')).to_have_text("Starker Wind")
    expect(page.locator('[data-testid="neutral-footer"]')).to_contain_text("Read-only.")
    # Nothing is editable: `column_mapping` is the only writable state this
    # feature introduces (§14.2), and it is the dropdown above.
    expect(page.locator('[data-testid="table-codes"] input')).to_have_count(0)

    # …and only that row moved.
    untouched = page.locator(f'{ROW}[data-column="{UNTOUCHED_COLUMN}"]')
    expect(untouched).to_have_attribute("data-status", "missing")


def test_an_unlabelled_code_surfaces_the_danger_footer(
    page: Page, server_url: str, codelists_route: str, delivery_root: Path
) -> None:
    """The other half of the journey: a mapping that does **not** cover every
    code in the corpus.

    `VortrittAusw` holds `8`, which `weather` has no row for in any language —
    mvp-spec.md §7's `Finding`-grade orphan. The column becomes `partial`, the
    code's own row is the design's danger row, and the footer names the code
    and how many records carry it.
    """
    _seed_corpus(page, server_url, delivery_root)
    page.click('[data-testid="nav-codelists"]')
    page.wait_for_selector(ROW)
    _select_corpus(page)

    _open_import(page)
    page.set_input_files('[data-testid="codelist-upload"] input[type="file"]', str(CODELIST))
    expect(page.locator('[data-testid="import-dialog"]')).not_to_be_visible(timeout=15_000)

    # The import's re-render can land after the first click and swallow it, so
    # click until the detail pane names the row.
    for attempt in range(5):
        page.locator(f'{ROW}[data-column="{UNTOUCHED_COLUMN}"]').click()
        try:
            expect(page.locator('[data-testid="detail-name"]')).to_have_text(
                UNTOUCHED_COLUMN, timeout=2_000
            )
            break
        except AssertionError:
            if attempt == 4:
                raise
    page.click('[data-testid="json-key"]')
    page.click(f'[data-testid="option-json-key"][aria-label="{ATTRIBUTE_OPTION}"]')

    moved = page.locator(f'{ROW}[data-column="{UNTOUCHED_COLUMN}"]')
    expect(moved).to_have_attribute("data-status", "partial", timeout=15_000)
    # 0 of 1 code labelled, so the bar reads 0 %.
    expect(moved.locator('[data-testid="coverage-pct"]')).to_have_text("0 %")

    orphan = page.locator('[data-testid="code-row"][data-code="8"]')
    expect(orphan).to_have_attribute("data-orphan", "true")
    expect(orphan.locator('[data-testid="code-label"]')).to_have_text(
        "no label — not in the codelist"
    )
    expect(page.locator('[data-testid="danger-text"]')).to_have_text(
        "Code 8 appears in 3 records but has no label. The prompt cannot name it, "
        "and those records score against an unnamed code."
    )
    # The design draws "Add label"; mvp-spec.md §7 has no UI path that writes a
    # label, so it is drawn and inert.
    expect(page.locator('[data-testid="add-label"]')).to_be_disabled()


# --- plan-codelists-usability.md §2–§3: finding a key, finding a column -------

#: Two attributes, so a search has something to tell apart. `road_type`'s
#: German name is `Strassenart` — the word an analyst looking at a German
#: column name actually types.
PICKER_CODELIST = _CODELISTS / "c01_minimal_valid" / "codelist.json"
POPOVER = '[data-testid="json-key-popover"]'
KEY_SEARCH = '[data-testid="json-key-search"]'


def _key_option(page: Page, label: str) -> Locator:
    return page.locator(f'[data-testid="option-json-key"][aria-label="{label}"]')


#: The one corpus every journey below works on, frozen by whichever of them
#: runs first. One, not one each: the E2E server lives for the session, and
#: J8/J9 count rows of a corpora table that shows ten — every corpus frozen
#: here spends their margin.
PICKER_CORPUS = "j7-picker"


@pytest.fixture(scope="session")
def picker_corpus() -> dict[str, bool]:
    """Whether `PICKER_CORPUS` has been frozen yet in this E2E session."""
    return {}


@pytest.fixture
def picker_root(e2e_settings: Settings, picker_corpus: dict[str, bool]) -> Path:
    """`delivery_root`'s file, under a folder named for `PICKER_CORPUS`."""
    root = e2e_settings.import_root_path / "j7-picker" / PICKER_CORPUS
    if not picker_corpus:
        root.mkdir(parents=True, exist_ok=True)
        (root / "one.txt").write_bytes(
            (_HAZARDS / "h08_all_empty_column" / "unfall.txt").read_bytes()
        )
    return root


def _ready_for_picker(
    page: Page, server_url: str, root: Path, picker_corpus: dict[str, bool]
) -> None:
    """`PICKER_CORPUS`, c01 imported, `UNTOUCHED_COLUMN` in the edit zone.

    What an earlier journey mapped on the shared corpus does not matter: each
    journey below asserts on the mapping it makes, never on the one it found.
    """
    if not picker_corpus:
        _seed_corpus(page, server_url, root, name=PICKER_CORPUS)
        picker_corpus["frozen"] = True
        page.click('[data-testid="nav-codelists"]')
    else:
        page.goto(f"{server_url}/codelists")
    page.wait_for_selector(ROW)
    _select_corpus(page, name=PICKER_CORPUS)
    _open_import(page)
    page.set_input_files('[data-testid="codelist-upload"] input[type="file"]', str(PICKER_CODELIST))
    expect(page.locator('[data-testid="import-dialog"]')).not_to_be_visible(timeout=15_000)
    # See `test_an_unlabelled_code_surfaces_the_danger_footer`: the import's
    # re-render can swallow the first click.
    for attempt in range(5):
        page.locator(f'{ROW}[data-column="{UNTOUCHED_COLUMN}"]').click()
        try:
            expect(page.locator('[data-testid="detail-name"]')).to_have_text(
                UNTOUCHED_COLUMN, timeout=2_000
            )
            break
        except AssertionError:
            if attempt == 4:
                raise


def _open_picker(page: Page) -> None:
    page.click('[data-testid="json-key"]')
    expect(page.locator(POPOVER)).to_be_visible()


def test_the_key_picker_opens_focused_and_inside_the_pane(
    page: Page,
    server_url: str,
    codelists_route: str,
    picker_root: Path,
    picker_corpus: dict[str, bool],
) -> None:
    """The search field has focus the moment the popover opens, and the
    popover — 440px, wider than the 320px field — opens leftwards, never past
    the edit pane's right edge or off the window."""
    _ready_for_picker(page, server_url, picker_root, picker_corpus)
    _open_picker(page)
    expect(page.locator(KEY_SEARCH)).to_be_focused()

    popover = page.locator(POPOVER).bounding_box()
    pane = page.locator('[data-testid="split-detail"]').bounding_box()
    assert popover is not None and pane is not None
    assert popover["width"] == 440
    assert popover["x"] >= 0
    assert popover["x"] + popover["width"] <= pane["x"] + pane["width"]


def test_the_key_search_filters_in_the_browser(
    page: Page,
    server_url: str,
    codelists_route: str,
    picker_root: Path,
    picker_corpus: dict[str, bool],
) -> None:
    """Typing hides the options that do not match — by key, by name in any
    language — and keeps "— not mapped —". The typed text surviving is the
    proof nothing redrew the popover: a server render would rebuild the field
    empty."""
    _ready_for_picker(page, server_url, picker_root, picker_corpus)
    _open_picker(page)
    search = page.locator(KEY_SEARCH)

    search.press_sequentially("strasse")
    expect(_key_option(page, "accident_type 2")).to_be_hidden()
    expect(_key_option(page, "road_type 2")).to_be_visible()
    expect(_key_option(page, "— not mapped —")).to_be_visible()
    expect(search).to_have_value("strasse")

    # Folded the way the server folded `data-search`: case, and ß as ss.
    search.fill("STRAßE")
    expect(_key_option(page, "road_type 2")).to_be_visible()
    search.fill("tipo di incidente")
    expect(_key_option(page, "accident_type 2")).to_be_visible()
    expect(_key_option(page, "road_type 2")).to_be_hidden()

    search.fill("zzz")
    expect(page.locator('[data-testid="json-key-no-match"]')).to_be_visible()

    # Enter with nothing highlighted takes the first search result.
    search.fill("road")
    search.press("Enter")
    expect(page.locator('[data-testid="detail-mapping"]')).to_contain_text(
        "mapped to road_type", timeout=15_000
    )


def test_the_key_picker_is_driven_by_the_keyboard(
    page: Page,
    server_url: str,
    codelists_route: str,
    picker_root: Path,
    picker_corpus: dict[str, bool],
) -> None:
    """↓ walks the options from "— not mapped —", Enter picks the highlighted
    one; Escape closes and hands the focus back to the field."""
    _ready_for_picker(page, server_url, picker_root, picker_corpus)
    _open_picker(page)
    search = page.locator(KEY_SEARCH)
    search.press("Escape")
    expect(page.locator(POPOVER)).to_have_count(0)
    expect(page.locator('[data-testid="json-key"]')).to_be_focused()

    _open_picker(page)
    search.press("ArrowDown")
    expect(_key_option(page, "— not mapped —")).to_have_attribute("data-active", "true")
    search.press("ArrowDown")
    expect(_key_option(page, "accident_type 2")).to_have_attribute("data-active", "true")
    expect(search).to_have_attribute("aria-activedescendant", re.compile(r"^c\d+$"))
    search.press("Enter")
    expect(page.locator('[data-testid="detail-mapping"]')).to_contain_text(
        "mapped to accident_type", timeout=15_000
    )


def test_the_column_search_keeps_its_focus_while_the_list_refilters(
    page: Page,
    server_url: str,
    codelists_route: str,
    picker_root: Path,
    picker_corpus: dict[str, bool],
) -> None:
    """The list redraws on the server as the analyst types; the field must
    not be part of that redraw, or the caret is lost mid-word."""
    _ready_for_picker(page, server_url, picker_root, picker_corpus)
    search = page.locator('[data-testid="column-search"]')
    search.click()
    search.press_sequentially("vortritt", delay=40)

    expect(page.locator(ROW)).to_have_count(1, timeout=15_000)
    expect(page.locator(f'{ROW}[data-column="{UNTOUCHED_COLUMN}"]')).to_be_visible()
    expect(search).to_be_focused()
    expect(search).to_have_value("vortritt")
    expect(page.locator('[data-testid="shown-count"]')).to_contain_text("1 of ")

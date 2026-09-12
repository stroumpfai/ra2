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

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

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
def delivery_root(tmp_path: Path) -> Path:
    """One `unfall` file, registered in place. Filenames are arbitrary on
    purpose: kind and canton come from the data (§12.5)."""
    root = tmp_path / CORPUS_NAME
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


def _seed_corpus(page: Page, server_url: str, root: Path) -> None:
    """Register the delivery and freeze it, through the Import UI (J1's path)."""
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="file-grid"]')
    page.click('[aria-label="Add set"]')
    page.fill('[data-testid="host-path"]', str(root))
    page.click('[data-testid="register-delivery"]')
    expect(page.locator('[data-testid="filename"]')).to_have_count(1, timeout=15_000)
    page.click('[data-testid="create-corpus"]')
    expect(
        page.locator('[data-testid="table-corpora"] tbody tr', has_text=CORPUS_NAME)
    ).to_have_count(1, timeout=15_000)


def _select_corpus(page: Page) -> None:
    """Name the corpus explicitly rather than trusting the default.

    The E2E server is session-scoped and J1 legitimately leaves corpora behind,
    so the chip's "most recently imported" default is not this journey's to
    assume.
    """
    page.click('[data-chip="corpus"]')
    page.click(f'[data-testid="option-corpus"][aria-label^="corpus {CORPUS_NAME} "]')
    # Wait for the **menu** to go, not for the chip's text: the chip may
    # already read the right corpus (it defaults to the newest), so its text
    # settles before the re-render the pick triggers has reached the browser —
    # and a click that lands on the pre-render DOM is lost.
    expect(page.locator('[data-testid="menu-corpus"]')).to_have_count(0)
    expect(page.locator('[data-chip="corpus"]')).to_contain_text(f"corpus {CORPUS_NAME} · v1")


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

    page.locator(f'{ROW}[data-column="{UNTOUCHED_COLUMN}"]').click()
    expect(page.locator('[data-testid="detail-name"]')).to_have_text(UNTOUCHED_COLUMN)
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

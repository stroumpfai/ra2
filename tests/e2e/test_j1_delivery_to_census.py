"""J1 — delivery to census (sw-design.md §11.5).

> Register the hazard delivery → analyse → per-file states show `ok` /
> `2 rejected` / `3 recovered` → open a file report → change its encoding →
> re-parse → state clears → deselect one file and watch both counts drop →
> Create corpus → the corpus row shows records, language composition and
> canary → Census loads, sorted Populated ▼ → filter to `unfall` → Export CSV
> and assert the downloaded file's header and row count.

**The whole journey, in one browser session.** The Import half landed with M6
and the Census tail with M7; they are one test function because J1 is one
sentence — the corpus the Census half profiles is the corpus the Import half
just created, and asserting that is the point of the journey.

Two deliberate departures from the sentence above, both because the journey is
driven against the **committed** hazard fixtures rather than the design mock's
illustrative ones (§11.4 — real data never reaches a test, so the hazards are
the synthetic ones on disk):

- the counts are `1 rejected` and `1 recovered`, not `2` and `3`. Those two
  numbers came from the design's fixture table; the states themselves — one
  rejected row reported with its key, one recovered row, `ok` for the rest —
  are exactly what h03 and h04 produce.
- "change its encoding → re-parse → state clears" is a round trip. Detection
  already gets h01 right (cp1252, `ok`), so the journey overrides it to
  **utf-8** — the file fails, which is the honest outcome for bytes that do
  not decode — and then back to cp1252, where the state clears. That exercises
  the same mechanism the sentence is about: an override re-runs step 1 onward
  for that file alone, and the row's state follows.

There is no `/api/v1` seeding here: registering and analysing the delivery
**is** the journey's first step, and it is driven through the real UI. (The
API could not seed it in any case — `ra2/api/v1/deliveries.py` is still the M0
stub and every handler raises 501.)
"""

import csv
import io
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from ra2.services.export_service import CLASSIFICATION_COMMENT, CSV_BOM, CSV_DELIMITER

pytestmark = pytest.mark.e2e

#: `tests/e2e/` -> `tests/`.
_HAZARDS = Path(__file__).resolve().parents[1] / "fixtures" / "deliveries" / "hazards"

#: One AG set, one shared text file, and a second AG `unfall` file that is a
#: **re-delivery of the same accidents** — same `UnfallUid`s. Selecting both
#: would be h07's collision all over again, so the journey deselects it, which
#: is the same step J1 asks for and the reason the design's own footnote says
#: deselected files stay in the list.
DELIVERY: dict[str, str] = {
    "ag_unfall.txt": "h03_stray_delimiter/unfall.txt",
    "ag_objekt.txt": "h10_count_mismatch/objekt.txt",
    "ag_person.txt": "h10_count_mismatch/person.txt",
    "ag_unfall_cp1252.txt": "h01_cp1252/unfall.txt",
    "unfallhergang.csv": "h04_embedded_newline/text.csv",
}

STRUCTURED = '[data-card="structured"]'
TEXT = '[data-card="text"]'
STATE = '[data-testid="file-state"]'

#: `DeliveryView.selected_record_count`: `ag_unfall` 2 ok + `ag_unfall_cp1252`
#: 2 ok, and 2 alone once the re-delivery is deselected.
ALL_RECORDS = 4
AFTER_DESELECT = 2

CENSUS_TABLE = '[data-testid="table-census"]'
#: `ExportService._CENSUS_CSV_HEADER`, spelled out here rather than imported:
#: the header row is the export's **contract with Excel**, and a test that
#: imported it would agree with any change to it (§11.5).
CENSUS_CSV_HEADER = [
    "table_name",
    "column_name",
    "type_hint",
    "record_count",
    "populated_count",
    "populated_rate",
    "distinct_count",
    "top_value_share",
    "long_tail",
    "top_values",
    #: Risk B1. Empty `top_values` means "empty in every row" for a column with
    #: no values and "you may not have these" for one whose sample was withheld
    #: — opposite conclusions, so the file says which it is.
    "top_values_withheld",
]


@pytest.fixture
def delivery_root(tmp_path: Path) -> Path:
    root = tmp_path / "j1-delivery"
    root.mkdir(parents=True)
    for name, source in DELIVERY.items():
        (root / name).write_bytes((_HAZARDS / source).read_bytes())
    return root


def _register(page: Page, server_url: str, root: Path) -> None:
    """Register a host directory through the design's one `+` button.

    Registered **in place, not copied** (§6.1); the delivery is analysed as
    soon as it is registered, and the view polls its status until it settles.
    """
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="file-grid"]')
    page.click('[aria-label="Add set"]')
    page.fill('[data-testid="host-path"]', str(root))
    page.click('[data-testid="register-delivery"]')


def _census_total(page: Page) -> int:
    """The unpaged total behind "1–25 of 67" — the number the export must
    contain, read off the screen rather than recomputed."""
    label = page.locator('[data-testid="pagination-range"]').inner_text()
    # `format_count` groups thousands with a space, so the digits are pulled
    # out rather than the separator guessed at.
    return int("".join(c for c in label.rsplit(" of ", 1)[1] if c.isdigit()))


def test_a_delivery_becomes_a_corpus(
    page: Page, server_url: str, delivery_root: Path, tmp_path: Path
) -> None:
    _register(page, server_url, delivery_root)

    # --- analyse: the per-file states are the analysis's, not a filename's ---
    expect(page.locator(f'{STRUCTURED} [data-testid="filename"]')).to_have_count(4, timeout=15_000)
    expect(page.locator(STRUCTURED).locator(STATE, has_text="1 rejected")).to_have_count(1)
    expect(page.locator(STRUCTURED).locator(STATE, has_text="ok")).to_have_count(3)
    expect(page.locator(TEXT).locator(STATE, has_text="1 recovered")).to_have_count(1)
    expect(page.locator(f"{STRUCTURED} " + '[data-testid="card-header"]')).to_contain_text(
        "4 files · 4 selected"
    )
    expect(page.locator('[data-testid="create-corpus"]')).to_contain_text(
        f"Create corpus · {ALL_RECORDS} records"
    )

    # --- the file report: detected vs. effective, override, re-parse --------
    page.click('[aria-label="Report for ag_unfall_cp1252.txt"]')
    expect(page.locator('[data-testid="file-report"]')).to_be_visible()
    expect(page.locator('[data-testid="detected-encoding"]')).to_have_text("cp1252")

    page.select_option('[data-testid="override-encoding"]', "utf-8")
    page.click('[data-testid="reparse"]')
    # Bytes that decode under neither encoding fail the file. No `U+FFFD`,
    # no silent repair — the row says so (§4.2.1, §12.4).
    expect(page.locator(STRUCTURED).locator(STATE, has_text="failed")).to_have_count(1)
    expect(page.locator('[data-testid="file-report"]')).to_contain_text("FILE_UNDECODABLE")

    page.select_option('[data-testid="override-encoding"]', "cp1252")
    page.click('[data-testid="reparse"]')
    expect(page.locator(STRUCTURED).locator(STATE, has_text="failed")).to_have_count(0)
    expect(page.locator(STRUCTURED).locator(STATE, has_text="ok")).to_have_count(3)
    page.click('[data-testid="close-report"]')
    expect(page.locator('[data-testid="file-report"]')).not_to_be_visible()

    # --- deselect one file: both counts drop --------------------------------
    page.click('[aria-label="Select ag_unfall_cp1252.txt"]')
    expect(page.locator(f"{STRUCTURED} " + '[data-testid="card-header"]')).to_contain_text(
        "4 files · 3 selected"
    )
    expect(page.locator('[data-testid="create-corpus"]')).to_contain_text(
        f"Create corpus · {AFTER_DESELECT} records"
    )
    # "Deselected files stay in the list" (README §1a.4).
    expect(page.locator(STRUCTURED).locator('[data-testid="filename"]')).to_have_count(4)

    # --- create the corpus ---------------------------------------------------
    page.click('[data-testid="create-corpus"]')
    row = page.locator('[data-testid="table-corpora"] tbody tr', has_text="j1-delivery")
    expect(row).to_have_count(1, timeout=15_000)

    # Records, language composition and canary — the three numbers J1 names.
    expect(row.locator('[data-testid="corpus-records"]')).to_have_text(str(AFTER_DESELECT))
    # The design's "de 2 812 · fr 1 402 · it 396", at this delivery's scale.
    expect(row.locator('[data-testid="corpus-languages"]')).not_to_have_text("—")
    expect(row.locator('[data-testid="corpus-canary"]')).to_have_count(1)
    # Nothing cites it yet, so delete is offered rather than blocked (J3).
    expect(row.locator('[data-testid="delete-corpus"]')).to_have_count(1)
    expect(row).to_contain_text("Not used by any evaluation")

    # --- Census loads, sorted Populated ▼ -----------------------------------
    # Through the nav, not a `goto`: "Census loads" is the analyst walking
    # there from the corpus they just made, in the same session.
    page.click('[data-testid="nav-census"]')
    page.wait_for_selector(f"{CENSUS_TABLE} tbody tr")
    # The corpus this journey created is the one being profiled — newest
    # first, which is what the corpus chip defaults to.
    expect(page.locator('[data-chip="corpus"]')).to_contain_text("corpus j1-delivery · v1")
    expect(page.locator('[data-testid="sort-populated_rate"]')).to_have_attribute(
        "aria-sort", "descending"
    )
    # …and no other column is the active sort.
    for other in ("column_name", "table_name", "type_hint", "distinct_count"):
        expect(page.locator(f'[data-testid="sort-{other}"]')).to_have_attribute("aria-sort", "none")
    all_columns = _census_total(page)

    # --- filter to `unfall` --------------------------------------------------
    page.click('[data-chip="table"]')
    page.click('[data-testid="option-table"][aria-label^="table · unfall"]')
    expect(page.locator('[data-chip="table"]')).to_contain_text("table · unfall")
    expect(page.locator(f'{CENSUS_TABLE} [data-testid="census-table-name"]')).not_to_have_count(0)
    # Every rendered row is `unfall`, and the total dropped.
    for cell in page.locator(f'{CENSUS_TABLE} [data-testid="census-table-name"]').all():
        assert cell.inner_text() == "unfall"
    unfall_columns = _census_total(page)
    assert 0 < unfall_columns < all_columns

    # --- Export CSV: the header and the row count ----------------------------
    with page.expect_download() as downloading:
        page.click('[data-testid="export-csv"]')
    saved = tmp_path / "census.csv"
    downloading.value.save_as(saved)
    raw = saved.read_bytes()

    # UTF-8 **with BOM** — Excel on Windows reads UTF-8 no other way (N3).
    assert raw.startswith(CSV_BOM)
    text = raw.decode("utf-8-sig")
    # Line 1 says what the file is, before anything says what is in it (B1).
    # Imported rather than spelled out, unlike the header below: the header is
    # the contract with Excel and a test that agreed with any change to it
    # would assert nothing, whereas the marking's wording is explicitly one
    # string "and nowhere else" — a formal marking replaces it when the
    # governance page exists (F1), and that must not be a two-file edit.
    classification, _, rest = text.partition("\r\n")
    assert classification == CLASSIFICATION_COMMENT
    comment, _, body = rest.partition("\r\n")
    # The header comment line names the corpus and its version (sw-design.md §7).
    assert comment.startswith("# corpus ")
    assert comment.endswith(" v1")

    reader = csv.reader(io.StringIO(body), delimiter=CSV_DELIMITER)
    assert next(reader) == CENSUS_CSV_HEADER
    rows = [row for row in reader if row]
    # The export is the **currently filtered** table, whole — no paging, so
    # the file holds every `unfall` column, not the 25 on screen.
    assert len(rows) == unfall_columns
    assert {row[0] for row in rows} == {"unfall"}


def test_the_corpora_card_states_the_immutability_rule(page: Page, server_url: str) -> None:
    """The Corpora card's sub-caption is the reason `corpus` is never mutated
    (§12.2), and it is verbatim design copy (README §1b)."""
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="corpora-caption"]')
    caption = page.locator('[data-testid="corpora-caption"]')
    expect(caption).to_contain_text("A corpus is immutable.")
    expect(caption).to_contain_text("the runs that cite it would stop being reproducible.")

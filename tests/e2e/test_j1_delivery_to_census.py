"""J1 — delivery to census (sw-design.md §11.5).

> Register the hazard delivery → analyse → per-file states show `ok` /
> `2 rejected` / `3 recovered` → open a file report → change its encoding →
> re-parse → state clears → deselect one file and watch both counts drop →
> Create corpus → the corpus row shows records, language composition and
> canary → Census loads, sorted Populated ▼ → filter to `unfall` → Export CSV
> and assert the downloaded file's header and row count.

**This is the Import half.** Census is M7's; the journey stops at "the corpus
row shows records, language composition and canary" and the Census tail lands
with that view.

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

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

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


def test_a_delivery_becomes_a_corpus(page: Page, server_url: str, delivery_root: Path) -> None:
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


def test_the_corpora_card_states_the_immutability_rule(page: Page, server_url: str) -> None:
    """The Corpora card's sub-caption is the reason `corpus` is never mutated
    (§12.2), and it is verbatim design copy (README §1b)."""
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="corpora-caption"]')
    caption = page.locator('[data-testid="corpora-caption"]')
    expect(caption).to_contain_text("A corpus is immutable.")
    expect(caption).to_contain_text("the runs that cite it would stop being reproducible.")

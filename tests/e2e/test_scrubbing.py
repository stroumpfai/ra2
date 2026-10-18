"""Scrubbing, end to end in a real browser (sw-design.md §19, `plan-text-scrubbing.md` §9).

> Import the name lists on the Scrubbing screen → try a sentence and see its
> placeholders → register h18 → preview the scrubbing on Import → create the
> corpus with those rules → the corpus row says `scrubbed · rules v3` → the
> version history counts the corpus → remove the lists again.

**Name lists only, no rule file.** The server and its database live for the
whole E2E session, so whatever this journey imports, every later journey
freezes with. A rule file would bring a date rule, and other journeys'
narratives state dates. The lists replace names, which no other journey's
fixtures contain, and the journey removes them again at the end, leaving the
active set equivalent to "mandatory rules only".

J6 already proves the Scrubbing screen makes no outbound request: it is
parametrised over `NAV_ITEMS`, and Scrubbing is one.
"""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from ra2.infra.config import Settings

pytestmark = pytest.mark.e2e

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
H18 = _FIXTURES / "deliveries" / "hazards" / "h18_names_in_narrative"
SCRUB = _FIXTURES / "scrub" / "hazards"

LISTS = (
    ("lastname", "s02_lastnames.txt"),
    ("firstname", "s01_firstnames.txt"),
    ("whitelist", "s03_whitelist.txt"),
)


@pytest.fixture
def delivery_root(tmp_path: Path, e2e_settings: Settings) -> Path:
    root = e2e_settings.import_root_path / tmp_path.name / "scrub-delivery"
    root.mkdir(parents=True)
    for name in ("unfall.txt", "text.csv"):
        (root / name).write_bytes((H18 / name).read_bytes())
    return root


def _import(page: Page, kind: str, name: str) -> None:
    page.click(f'[data-testid="scrub-import-{kind}"]')
    page.set_input_files('[data-testid="scrub-upload"] input[type="file"]', str(SCRUB / name))
    expect(page.locator('[data-testid="scrub-import-dialog"]')).not_to_be_visible(timeout=15_000)
    row = page.locator(f'[data-testid="scrub-file-row"][data-kind="{kind}"]')
    expect(row.locator('[data-testid="scrub-file-name"]')).to_have_text(name, timeout=15_000)


def test_names_are_scrubbed_before_a_corpus_stores_them(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    # --- the rules ---------------------------------------------------------
    page.goto(f"{server_url}/scrubbing")
    expect(page.locator('[data-testid="table-scrub-rules"]')).to_contain_text("license-plate")
    for kind, name in LISTS:
        _import(page, kind, name)

    # --- one sentence, scrubbed, shown as text ------------------------------
    page.fill('[data-testid="scrub-try-input"]', "Herr Meier rief 079 123 45 67 an.")
    page.click('[data-testid="scrub-try-run"]')
    expect(page.locator('[data-testid="scrub-try-output"]')).to_have_text(
        "Herr <Lastname_1> rief <Phone_1> an."
    )

    # --- the delivery, previewed, then frozen with what the preview showed ---
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="file-grid"]')
    page.click('[aria-label="Add set"]')
    page.fill('[data-testid="host-path"]', str(delivery_root))
    page.click('[data-testid="register-delivery"]')
    expect(page.locator('[data-testid="create-corpus"]')).to_contain_text(
        "Create corpus · 3 records", timeout=15_000
    )

    page.click('[data-testid="scrub-preview"]')
    dialog = page.locator('[data-testid="scrub-preview-dialog"]')
    expect(dialog).to_be_visible()
    expect(dialog.locator('[data-testid="scrub-preview-records"]')).to_contain_text("3 of 3")
    expect(
        dialog.locator('[data-testid="scrub-preview-row"][data-rule-id="lastnames"]')
    ).to_contain_text("5")
    dialog.locator('[data-testid="scrub-preview-create"]').click()

    row = page.locator('[data-testid="table-corpora"] tbody tr', has_text="scrub-delivery")
    expect(row).to_have_count(1, timeout=15_000)
    expect(row.locator('[data-testid="scrub-status"]')).to_have_text("scrubbed · rules v3")

    # --- the history counts it; then the lists come out again ---------------
    page.goto(f"{server_url}/scrubbing")
    versions = page.locator('[data-testid="table-scrub-versions"] tbody tr')
    expect(versions.first).to_contain_text("v3")
    expect(versions.first).to_contain_text("1")
    for kind, _ in LISTS:
        page.click(f'[data-testid="scrub-remove-{kind}"]')
        expect(
            page.locator(f'[data-testid="scrub-file-row"][data-kind="{kind}"]').locator(
                '[data-testid="scrub-file-none"]'
            )
        ).to_have_count(1, timeout=15_000)

"""A corpus is named when it is created (`SD68`, plan-corpus-naming.md).

Reuses J1's delivery: registering it through the UI is the first step, and its
hazards (a rejected row, a recovered one) do not block a freeze.
"""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from tests.e2e.test_j1_delivery_to_census import _register, delivery_root  # noqa: F401

pytestmark = pytest.mark.e2e


def test_a_corpus_is_created_under_the_name_and_description_the_analyst_typed(
    page: Page,
    server_url: str,
    delivery_root: Path,  # noqa: F811
) -> None:
    _register(page, server_url, delivery_root)
    create = page.locator('[data-testid="create-corpus"]')
    # J1's step: the second AG `unfall` file re-delivers the same accidents, and
    # selecting both would block the freeze.
    page.wait_for_selector('[aria-label="Select ag_unfall_cp1252.txt"]', timeout=30_000)
    page.click('[aria-label="Select ag_unfall_cp1252.txt"]')
    # The deselect redraws the page, and NiceGUI drops an event aimed at an
    # element the redraw replaced: type only once it has settled.
    expect(page.locator('[data-card="structured"] [data-testid="card-header"]')).to_contain_text(
        "3 selected"
    )
    expect(create).to_contain_text("Create corpus · ", timeout=30_000)
    expect(create).to_be_enabled(timeout=30_000)

    # The box starts on the delivery's own name.
    name = page.locator('[data-testid="corpus-name-input"]')
    expect(name).to_have_value("j1-delivery")
    name.fill("only-canton-ag")
    page.locator('[data-testid="corpus-description-input"]').fill("AG only, delivery of 2023")
    create.click()

    row = page.locator('[data-testid="table-corpora"] tbody tr', has_text="only-canton-ag")
    expect(row).to_have_count(1, timeout=15_000)
    expect(row.locator('[data-testid="corpus-name"]')).to_have_text("only-canton-ag")
    expect(row.locator('[data-testid="corpus-description"]')).to_have_text(
        "AG only, delivery of 2023"
    )
    # The form goes back to the delivery's name for the next one.
    expect(name).to_have_value("j1-delivery")
    expect(page.locator('[data-testid="corpus-description-input"]')).to_have_value("")

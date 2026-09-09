"""J2 — blocking validation (sw-design.md §11.5).

> A delivery with a `UnfallUid` duplicated across two cantonal sets: Create
> corpus is refused, the error names the key, and **no corpus row exists**
> afterwards.

The delivery is `h07_dup_uid_cross_canton` — the committed fixture built for
exactly this: an AG `unfall` file and a BE `unfall` file that share
`aa000000000000000000000000000001`. That is the collision mvp-spec.md §4.3
calls blocking, and the one the design's own text-card footnote warns about:
"A `UnfallUid` collision attaches the wrong narrative".

"No corpus row exists afterwards" is asserted as **no new row**, not as an
empty table: the E2E server is session-scoped and J1 legitimately leaves a
corpus behind. A freeze that wrote a row and then rolled back half of it would
still fail this.
"""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

#: `tests/e2e/` -> `tests/`.
_HAZARDS = Path(__file__).resolve().parents[1] / "fixtures" / "deliveries" / "hazards"

#: The key h07 duplicates across the AG and the BE set.
DUPLICATE_KEY = "aa000000000000000000000000000001"

STRUCTURED = '[data-card="structured"]'


@pytest.fixture
def delivery_root(tmp_path: Path) -> Path:
    """h07, verbatim: `ag_unfall.txt` and `be_unfall.txt`."""
    source = _HAZARDS / "h07_dup_uid_cross_canton"
    root = tmp_path / "j2-delivery"
    root.mkdir(parents=True)
    for path in sorted(source.iterdir()):
        (root / path.name).write_bytes(path.read_bytes())
    return root


def _corpus_rows(page: Page) -> int:
    return page.locator('[data-testid="table-corpora"] [data-testid="corpus-name"]').count()


def test_a_duplicate_key_across_two_sets_refuses_the_freeze(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="file-grid"]')

    page.click('[aria-label="Add set"]')
    page.fill('[data-testid="host-path"]', str(delivery_root))
    page.click('[data-testid="register-delivery"]')

    # Both files analyse cleanly on their own: the collision is **cross-file**,
    # which is why it is caught at freeze and not at parse (§6.3.1).
    expect(page.locator(f'{STRUCTURED} [data-testid="filename"]')).to_have_count(2, timeout=15_000)
    expect(
        page.locator(STRUCTURED).locator('[data-testid="file-state"]', has_text="ok")
    ).to_have_count(2)
    expect(page.locator('[data-testid="create-corpus"]')).to_contain_text(
        "Create corpus · 4 records"
    )

    before = _corpus_rows(page)

    page.click('[data-testid="create-corpus"]')

    # The freeze is refused, and the error names the key.
    blocking = page.locator('[data-testid="blocking"]')
    expect(blocking).to_be_visible(timeout=15_000)
    expect(blocking.locator('[data-testid="blocking-title"]')).to_have_text("Corpus not created")
    expect(blocking).to_contain_text("DUP_KEY_CROSS_SET")
    expect(blocking.locator('[data-testid="blocking-key"]', has_text=DUPLICATE_KEY)).to_have_count(
        1
    )

    page.click('[data-testid="blocking-close"]')
    expect(blocking).not_to_be_visible()

    # …and nothing was written. One transaction, all-or-nothing (§6.3).
    assert _corpus_rows(page) == before
    page.reload()
    page.wait_for_selector('[data-testid="table-corpora"]')
    assert _corpus_rows(page) == before


def test_the_text_cards_footnote_warns_about_exactly_this(page: Page, server_url: str) -> None:
    """README §1a.4, verbatim: the footnote is the design's own explanation of
    why the check J2 exercises exists at all."""
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="file-grid"]')
    expect(page.locator('[data-card="text"] [data-testid="footnote"]')).to_contain_text(
        "uniqueness is checked across the whole delivery."
    )

"""J8 — build and freeze a feature set through the Features UI (sw-design.md §11.5).

> Seed a corpus and its census (through the Import UI, the way J1 does),
> then, through the Features UI: build a labelled enum feature and an
> exploratory feature, freeze the set, and assert it now appears LOCKED and
> un-editable.

**One step goes through the already-live `/api/v1/feature-configs` API
instead of clicking a button**: creating a brand-new draft set is
`feature_sets_table`'s "New set" action, and that component
(`ra2/ui/components/feature_sets_table.py`) is G3's, built in parallel this
same wave — its body is still a `raise NotImplementedError` stub as this file
is written, so this journey has no button to click yet and no known markup to
target. `POST /api/v1/feature-configs` is Wave 3's own router (F2), already
real and already live, and it is exactly what "New set" calls on the service
side — using it here seeds the one precondition this view cannot yet create
for itself, the same way `test_j1_delivery_to_census.py` seeds nothing
because Import already can. Every other step — selecting the set, adding both
features, freezing, and reading the frozen state back — goes through this
view's own controls, which this branch does own.

**This branch cannot make `/features` itself live.** `features_view.register()`
is not wired into `ra2/ui/views/register_all()` — the lead does that
centrally after merging this branch alongside G1's Codelists view (see
`ra2/ui/views/features_view.py`'s module docstring and CLAUDE.md's ownership
rule on `ra2/ui/shell.py` / `ra2/ui/views/__init__.py`). Until then, `/features`
on the shared E2E server resolves to the `built=False` placeholder, not this
view — this test is written to pass once that wiring lands, and the branch's
final report says plainly that it could not be run to a genuine green inside
this worktree for that reason.
"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

#: `tests/e2e/` -> `tests/`.
_HAZARDS = Path(__file__).resolve().parents[1] / "fixtures" / "deliveries" / "hazards"

#: One complete cantonal set — the same combination `test_census_view.py` and
#: `test_features_view.py` both use — so the corpus this journey freezes has
#: a real enum column (`Witter0Ausw`) to name on the labelled feature.
DELIVERY: dict[str, str] = {
    "one.txt": "h08_all_empty_column/unfall.txt",
    "two.txt": "h10_count_mismatch/objekt.txt",
    "three.txt": "h10_count_mismatch/person.txt",
}

WEATHER_COLUMN = "Witter0Ausw"


@pytest.fixture
def delivery_root(tmp_path: Path) -> Path:
    root = tmp_path / "j8-delivery"
    root.mkdir(parents=True)
    for name, source in DELIVERY.items():
        (root / name).write_bytes((_HAZARDS / source).read_bytes())
    return root


def _register_and_freeze_corpus(page: Page, server_url: str, root: Path) -> None:
    """Register + analyse + freeze one corpus through the Import UI —
    `test_j1_delivery_to_census.py`'s own first act, repeated rather than
    imported (tests/ has no shared per-journey helper module by design).

    Asserted as **one more row than before**, not as an absolute count: the
    E2E server is session-scoped, and J1/J2/J7 legitimately leave corpora
    behind by the time this journey runs (the same reasoning
    `test_j2_blocking_validation.py`'s own `_corpus_rows` helper documents —
    counting `[data-testid="corpus-name"]`, not `tbody tr`: an empty table
    still renders one placeholder `<tr>`, so a plain row count cannot tell
    "no corpora" and "one corpus" apart).
    """
    page.goto(f"{server_url}/import")
    page.wait_for_selector('[data-testid="file-grid"]')
    names = page.locator('[data-testid="table-corpora"] [data-testid="corpus-name"]')
    before = names.count()
    page.click('[aria-label="Add set"]')
    page.fill('[data-testid="host-path"]', str(root))
    page.click('[data-testid="register-delivery"]')

    expect(page.locator('[data-card="structured"] [data-testid="filename"]')).to_have_count(
        3, timeout=15_000
    )
    expect(page.locator('[data-testid="create-corpus"]')).to_be_enabled(timeout=15_000)
    page.click('[data-testid="create-corpus"]')
    expect(names).to_have_count(before + 1, timeout=15_000)


def _create_draft_feature_config(page: Page, server_url: str, name: str) -> str:
    """`POST /api/v1/feature-configs` — see the module docstring for why this
    one precondition is seeded through the API rather than the UI."""
    response = page.request.post(
        f"{server_url}/api/v1/feature-configs",
        data=json.dumps({"name": name}),
        headers={"Content-Type": "application/json"},
    )
    assert response.ok, response.text()
    body = response.json()
    feature_config_id: str = body["feature_config_id"]
    return feature_config_id


def _add_feature_through_the_ui(
    page: Page, *, key: str, exploratory: bool, source_column: str | None
) -> None:
    page.click('[aria-label="Add feature"]')
    page.wait_for_selector('[data-testid="feature-key"]')
    page.fill('[data-testid="feature-key"]', key)
    if exploratory:
        page.locator('[data-testid="seg-option"]', has_text="Exploratory").click()
    if source_column is not None:
        # No corpus was picked in `validate-corpus-select`, so the codelist
        # tier never runs (feature_service's own docstring) and the source
        # column renders as the plain text fallback, not the corpus-driven
        # `<select>` (`features_view._column_picker`).
        page.fill('[data-testid="source-column-input"]', source_column)
    page.click('[data-testid="save-feature"]')


def test_build_two_features_and_freeze_the_set(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    _register_and_freeze_corpus(page, server_url, delivery_root)
    feature_config_id = _create_draft_feature_config(page, server_url, "J8 weather set")

    page.goto(f"{server_url}/features")
    page.wait_for_selector('[data-testid="set-select"]')
    page.select_option('[data-testid="set-select"]', value=feature_config_id)
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("0 + 0 features")

    # --- a labelled enum feature ---------------------------------------------
    _add_feature_through_the_ui(
        page, key="weather", exploratory=False, source_column=WEATHER_COLUMN
    )
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("1 + 0 features")

    # --- an exploratory feature -----------------------------------------------
    _add_feature_through_the_ui(
        page, key="phone_use_mentioned", exploratory=True, source_column=None
    )
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("1 + 1 features")

    # Both features saved clean — no blocking row, no danger chip.
    expect(page.locator('[data-testid="danger-chip"]')).to_have_count(0)

    # --- freeze ---------------------------------------------------------------
    page.click('[data-testid="create-feature-set"]')

    # The frozen board: LOCKED, read-only, "Clone to new evaluation" instead
    # of "Create a feature set", and "Add feature" is gone entirely.
    expect(page.locator('[data-testid="frozen-banner"]')).to_be_visible(timeout=15_000)
    expect(page.locator('[data-testid="frozen-banner"]')).to_contain_text("Frozen")
    expect(page.locator('[data-testid="clone-feature-set"]')).to_be_visible()
    expect(page.locator('[data-testid="create-feature-set"]')).to_have_count(0)
    expect(page.locator('[aria-label="Add feature"]')).to_have_count(0)

    # A reload proves it, not just the in-memory render after the click.
    page.reload()
    page.wait_for_selector('[data-testid="frozen-banner"]')
    expect(page.locator('[data-testid="clone-feature-set"]')).to_be_visible()
    expect(page.locator('[aria-label="Add feature"]')).to_have_count(0)

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

`/features` is live: `features_view.register()` is wired into
`ra2/ui/views/register_all()` (it was not when this file was first written,
which is why the journey below was authored against a placeholder route).

The second journey walks the Census → Features hand-off, which is the only
way `CensusColumnView.in_config` — and therefore the Census action column's
other state — can be reached at all.
"""

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Locator, Page, expect

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

#: `test_j1_delivery_to_census.py`'s own selector, repeated rather than
#: imported (tests/e2e has no shared helper module by design).
CENSUS_TABLE = '[data-testid="table-census"]'


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
    page: Page,
    *,
    key: str,
    exploratory: bool,
    source_column: str | None,
    description: str | None = None,
) -> None:
    page.click('[aria-label="Add feature"]')
    page.wait_for_selector('[data-testid="feature-key"]')
    page.fill('[data-testid="feature-key"]', key)
    if description is not None:
        page.fill('[data-testid="feature-description"]', description)
    if exploratory:
        page.locator('[data-testid="seg-option"]', has_text="Exploratory").click()
    if source_column is not None:
        # No corpus was picked in `validate-corpus-select`, so the codelist
        # tier never runs (feature_service's own docstring) and the source
        # column renders as the plain text fallback, not the corpus-driven
        # `<select>` (`features_view._column_picker`).
        page.fill('[data-testid="source-column-input"]', source_column)
    page.click('[data-testid="save-feature"]')


def _expect_open_on_the_newest_set(page: Page, feature_config_id: str) -> None:
    """Wait until the view is showing the set the caller just created, without
    touching the picker.

    `features_view._load_selected_config` opens on the newest draft whenever
    this client has no remembered set — which is the case on a fresh page and
    again after a reload, since `app.storage.client` survives neither. Picking
    that same set from the dropdown would therefore be a no-op that still costs
    a full asynchronous `reload()`, and a click issued into that window lands
    on a toolbar NiceGUI is midway through replacing, where it is silently
    dropped. Asserting the default is both race-free and a real assertion: if a
    later test ever leaves a newer set behind, this fails loudly instead of
    turning the journey flaky.
    """
    page.wait_for_selector('[data-testid="set-select"]')
    expect(page.locator('[data-testid="set-select"]')).to_have_value(feature_config_id)


def test_build_two_features_and_freeze_the_set(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    _register_and_freeze_corpus(page, server_url, delivery_root)
    feature_config_id = _create_draft_feature_config(page, server_url, "J8 weather set")

    page.goto(f"{server_url}/features")
    _expect_open_on_the_newest_set(page, feature_config_id)
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


def test_use_as_feature_carries_a_census_column_into_a_new_feature(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    """The Census → Features hand-off, end to end, as a browser sees it.

    `design/nav-import-census/README.md`, Interactions: ""use as feature"
    navigates to Features with that column preselected; already-configured
    columns show "in config" instead and their row is tinted." Both halves
    are one loop — the second is only reachable by walking the first, because
    `CensusColumnView.in_config` is computed from `feature.source_column`
    (`census_service`), which is exactly what saving here writes.

    The action is asserted to be a **real** `<a href>` the browser follows,
    the J5 way (`test_j5_nav.py`'s own nav-link assertion): the UI-layer
    suites can see a `ui.link`'s props, only a browser can see that clicking
    it navigates.
    """
    _register_and_freeze_corpus(page, server_url, delivery_root)
    # Created last, so it is the newest draft and the set the hand-off lands
    # in (`features_view._load_selected_config`); the set J8's other journey
    # freezes must not be the one this column arrives at.
    _create_draft_feature_config(page, server_url, "J8 hand-off set")

    page.goto(f"{server_url}/census")
    page.wait_for_selector(f"{CENSUS_TABLE} tbody tr")
    action = page.locator('[data-testid="use-as-feature"]').first
    href = action.get_attribute("href")
    assert href is not None, "the action must be a link, not a scripted button"
    column = parse_qs(urlparse(href).query)["column"][0]

    action.click()

    page.wait_for_selector('[data-testid="source-column-select"]')
    expect(page.locator('[data-testid="source-column-select"]')).to_have_value(column)
    expect(page.locator('[data-testid="editing-feature-name"]')).to_have_text("(new feature)")
    page.fill('[data-testid="feature-key"]', "from_census")
    page.click('[data-testid="save-feature"]')
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("1 + 0 features")

    # Back on Census the loop is closed: that column is in config, its row is
    # tinted, and the action it was clicked through is gone.
    page.goto(f"{server_url}/census")
    page.wait_for_selector(f"{CENSUS_TABLE} tbody tr")
    row = page.locator(f"{CENSUS_TABLE} tbody tr").filter(
        has=page.locator(f'[data-testid="census-column-name"]:text-is("{column}")')
    )
    expect(row).to_have_count(1)
    expect(row).to_have_class(re.compile(r"\bin-config\b"))
    expect(row.locator('[data-testid="in-config"]')).to_have_text("in config")
    expect(row.locator('[data-testid="use-as-feature"]')).to_have_count(0)


#: The description this journey saves. It carries the hazards the round trip
#: has to survive — an angle bracket, an ampersand, a double quote and an
#: embedded newline (CLAUDE.md: fixtures hold the real hazards, and a clean
#: string would pass against a half-fixed implementation). A `<textarea>`
#: whose value is a parsed HTML attribute or a child text node mangles at
#: least one of these; the DOM property `features_view._textarea` sets
#: carries all four.
HAZARDOUS_DESCRIPTION = 'Weather at the time — "wet" & <slippery>?\nSecond line.'


def test_a_description_survives_a_save_and_a_reload(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    """mvp-spec.md's description is prompt text: what the analyst typed is
    what the model is later given, so the box must read back exactly what was
    stored — and a browser is the only place that can be checked.

    The regression this pins: the description persisted correctly all along,
    but the edit zone rendered it as a child node of the `<textarea>`, which a
    Vue-built element never reads as its value. The field came up blank on
    every reload and looked unsaved — and an analyst typing into the
    apparently empty box would silently replace prose they could not see. The
    UI-layer suites cannot see this at all: the NiceGUI `User` fixture
    inspects the server-side element tree, where that child node is present
    and looks right.

    Asserted after `page.reload()`, not on the in-memory re-render that
    follows the click, because the reload is where it failed.
    """
    _register_and_freeze_corpus(page, server_url, delivery_root)
    feature_config_id = _create_draft_feature_config(page, server_url, "J8 description set")

    page.goto(f"{server_url}/features")
    _expect_open_on_the_newest_set(page, feature_config_id)
    _add_feature_through_the_ui(
        page,
        key="weather_described",
        exploratory=False,
        source_column=WEATHER_COLUMN,
        description=HAZARDOUS_DESCRIPTION,
    )
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("1 + 0 features")

    page.reload()
    _expect_open_on_the_newest_set(page, feature_config_id)
    page.click('[aria-label="Edit weather_described"]')
    expect(page.locator('[data-testid="feature-description"]')).to_have_value(HAZARDOUS_DESCRIPTION)


def test_the_validate_against_corpus_survives_a_save_and_a_reload(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    """The picked validation corpus is what scopes the codelist tier of
    `add_feature` / `edit_feature` (`features_view._validate_against`), so an
    analyst who reloads and does not notice it has reset to "none" goes on
    saving features whose enum codelists are never checked.

    It rides in the query string rather than in `app.storage.client`, which
    NiceGUI discards as soon as the socket closes — so the assertion that
    matters is made after a real `page.reload()`, and the URL the view wrote
    is asserted too, since that is the whole mechanism.
    """
    _register_and_freeze_corpus(page, server_url, delivery_root)
    feature_config_id = _create_draft_feature_config(page, server_url, "J8 validation set")

    page.goto(f"{server_url}/features")
    _expect_open_on_the_newest_set(page, feature_config_id)
    page.click('[aria-label="Add feature"]')
    page.wait_for_selector('[data-testid="validate-corpus-select"]')

    picker = page.locator('[data-testid="validate-corpus-select"]')
    options = picker.locator("option")
    corpus_id = next(
        value
        for value in (options.nth(i).get_attribute("value") for i in range(options.count()))
        if value
    )
    page.select_option('[data-testid="validate-corpus-select"]', value=corpus_id)
    expect(picker).to_have_value(corpus_id)
    # The pick is in the URL, and `column` is not: a consumed Census hand-off
    # must not be re-applied by the reload below.
    expect(page).to_have_url(re.compile(rf"/features\?corpus={re.escape(corpus_id)}$"))
    # Picking a corpus re-renders the edit zone asynchronously (the codelist
    # tier is fetched first) and swaps the source-column control from the
    # no-corpus text fallback to the corpus-driven `<select>`. Waiting for that
    # swap is what makes the key typed below land in the surviving element
    # rather than in one about to be replaced.
    page.wait_for_selector('[data-testid="source-column-select"]')

    page.fill('[data-testid="feature-key"]', "validated_feature")
    page.click('[data-testid="save-feature"]')
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("1 + 0 features")

    page.reload()
    _expect_open_on_the_newest_set(page, feature_config_id)
    page.click('[aria-label="Edit validated_feature"]')
    expect(page.locator('[data-testid="validate-corpus-select"]')).to_have_value(corpus_id)
    # The hand-off was consumed before the reload, so nothing re-opened a
    # new-feature draft over the feature just clicked.
    expect(page.locator('[data-testid="editing-feature-name"]')).not_to_have_text("(new feature)")


#: What the edit journeys below type into the description box. Short — the
#: byte-exactness of that field is `HAZARDOUS_DESCRIPTION`'s job, not theirs.
EDITED_DESCRIPTION = "Reworded after review."


def _open_feature_for_editing(page: Page, key: str) -> None:
    """Click a saved feature's row and wait until its edit zone is up.

    Every journey below edits a feature that is already saved, so each one
    starts here: the *edit* path is where a dropped field costs an analyst work
    they had already done, and it is the path `edit_feature` takes.
    """
    page.click(f'[aria-label="Edit {key}"]')
    expect(page.locator('[data-testid="editing-feature-name"]')).to_have_text(key)


def _save_and_wait_for_the_rename(page: Page, key: str) -> None:
    """Save the open draft and wait until the saved row carries `key`.

    Every edit journey renames its feature, because the key is both a field
    under test and the only edit whose result is visible in the feature list —
    which makes the renamed row the one unambiguous signal that the save has
    actually landed. Asserting the feature *count* instead would be a no-op
    here: editing a feature never changes it, so the assertion passes on the
    pre-save render and lets the reload that follows race the save.
    """
    page.click('[data-testid="save-feature"]')
    expect(page.locator(f'[aria-label="Edit {key}"]')).to_have_count(1)


def _readout(page: Page, text: str) -> Locator:
    """One `.ro` frozen readout by its text. `frozen_readout` gives every
    readout the same `data-testid`, so the text is the only selector there is
    (`ra2/ui/components/primitives.py`)."""
    return page.locator('[data-testid="ro"]').filter(has_text=text)


def test_editing_every_field_of_a_labelled_enum_feature_round_trips(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    """Case A, the whole edit zone: key, description, validation corpus,
    source column and grain all changed on a saved feature, then read back
    after a reload.

    The conditional rendering that belongs to this case is asserted in the
    same pass, because it is what tells the analyst which fields are even
    live: picking a corpus swaps the source column from a free-text fallback
    to the corpus-driven `<select>` (`features_view._column_picker`), an enum
    takes no matching parameter, and an object-grain feature is captured but
    never scored (mvp-spec.md §8.2).
    """
    _register_and_freeze_corpus(page, server_url, delivery_root)
    feature_config_id = _create_draft_feature_config(page, server_url, "J8 enum edit set")

    page.goto(f"{server_url}/features")
    _expect_open_on_the_newest_set(page, feature_config_id)
    _add_feature_through_the_ui(
        page, key="weather_raw", exploratory=False, source_column=WEATHER_COLUMN
    )
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("1 + 0 features")

    _open_feature_for_editing(page, "weather_raw")
    # No corpus is picked yet, so the column list holds nothing but the column
    # this feature already names (`features_view._column_picker` keeps a
    # foreign column visible rather than dropping it).
    expect(page.locator('[data-testid="source-column-select"] option')).to_have_count(1)

    picker = page.locator('[data-testid="validate-corpus-select"]')
    options = picker.locator("option")
    corpus_id = next(
        value
        for value in (options.nth(i).get_attribute("value") for i in range(options.count()))
        if value
    )
    page.select_option('[data-testid="validate-corpus-select"]', value=corpus_id)
    # Conditional rendering: the corpus is what opens the column list up to the
    # whole census, so waiting for it to grow past that single remembered entry
    # is both an assertion and the signal that the re-render has landed.
    page.wait_for_selector('[data-testid="source-column-select"]')
    expect(page.locator('[data-testid="source-column-select"] option')).not_to_have_count(1)

    page.fill('[data-testid="feature-key"]', "weather_edited")
    page.fill('[data-testid="feature-description"]', EDITED_DESCRIPTION)
    page.select_option('[data-testid="source-column-select"]', value=WEATHER_COLUMN)
    page.select_option('[data-testid="grain-select"]', value="object")

    # Case A's own readouts: an enum matches exactly and takes no parameter,
    # and object grain is captured, not scored.
    expect(_readout(page, "exact")).to_have_count(1)
    expect(_readout(page, "none for enum")).to_have_count(1)
    expect(page.locator('[data-testid="tolerance-value"]')).to_have_count(0)
    expect(page.get_by_text("No — captured, not scored")).to_have_count(1)

    _save_and_wait_for_the_rename(page, "weather_edited")

    page.reload()
    _expect_open_on_the_newest_set(page, feature_config_id)
    _open_feature_for_editing(page, "weather_edited")
    expect(page.locator('[data-testid="feature-key"]')).to_have_value("weather_edited")
    expect(page.locator('[data-testid="feature-description"]')).to_have_value(EDITED_DESCRIPTION)
    expect(page.locator('[data-testid="grain-select"]')).to_have_value("object")
    expect(page.locator('[data-testid="value-type-select"]')).to_have_value("enum")
    expect(page.locator('[data-testid="validate-corpus-select"]')).to_have_value(corpus_id)
    expect(page.locator('[data-testid="source-column-select"]')).to_have_value(WEATHER_COLUMN)


def test_switching_a_feature_to_time_round_trips_its_tolerance(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    """Case B: the ± tolerance is part of the feature's definition — it feeds
    the fingerprint (mvp-spec.md §8.4), so losing it silently changes what
    "correct" means.

    The stepper exists only for `time`, which is the conditional rendering
    asserted here: every other value type shows a static parameter readout.
    """
    feature_config_id = _create_draft_feature_config(page, server_url, "J8 time edit set")

    page.goto(f"{server_url}/features")
    _expect_open_on_the_newest_set(page, feature_config_id)
    _add_feature_through_the_ui(
        page, key="accident_time", exploratory=False, source_column="UnfallZeitFeld"
    )
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("1 + 0 features")

    _open_feature_for_editing(page, "accident_time")
    expect(page.locator('[data-testid="tolerance-value"]')).to_have_count(0)

    page.select_option('[data-testid="value-type-select"]', value="time")
    # Conditional rendering: `time` is the one type with an editable parameter.
    page.wait_for_selector('[data-testid="tolerance-value"]')
    expect(page.locator('[data-testid="tolerance-value"]')).to_have_text("± 15 min")
    expect(_readout(page, "within tolerance")).to_have_count(1)

    # One step at a time, each waited for: every click re-renders the zone, and
    # a second click issued into that window would land on a replaced button.
    page.click('[aria-label="Increase tolerance"]')
    expect(page.locator('[data-testid="tolerance-value"]')).to_have_text("± 20 min")
    page.click('[aria-label="Increase tolerance"]')
    expect(page.locator('[data-testid="tolerance-value"]')).to_have_text("± 25 min")

    page.fill('[data-testid="feature-key"]', "accident_time_edited")
    _save_and_wait_for_the_rename(page, "accident_time_edited")

    page.reload()
    _expect_open_on_the_newest_set(page, feature_config_id)
    _open_feature_for_editing(page, "accident_time_edited")
    expect(page.locator('[data-testid="value-type-select"]')).to_have_value("time")
    expect(page.locator('[data-testid="tolerance-value"]')).to_have_text("± 25 min")
    expect(_readout(page, "within tolerance")).to_have_count(1)


def test_switching_a_feature_to_derived_round_trips_its_derivation(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    """Case C: a derived feature has no native column — it has a derivation
    from mvp-spec.md §8.3's closed catalogue, built by G3's
    `derivation_builder` and stored as `derivation_json`.

    Choosing `derived` is what replaces the source column with the builder and
    withdraws the validation corpus (a derivation has no column to validate),
    and the derivation in turn decides the value type — all three asserted
    here, then read back after the reload.
    """
    feature_config_id = _create_draft_feature_config(page, server_url, "J8 derived edit set")

    page.goto(f"{server_url}/features")
    _expect_open_on_the_newest_set(page, feature_config_id)
    _add_feature_through_the_ui(
        page, key="vehicles_involved", exploratory=False, source_column="AnzObjFeld"
    )
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("1 + 0 features")

    _open_feature_for_editing(page, "vehicles_involved")
    page.select_option('[data-testid="grain-select"]', value="derived")
    page.wait_for_selector('[data-testid="derivation-builder"]')

    # Conditional rendering: no native column, and nothing to validate against.
    expect(page.locator('[data-testid="source-column-input"]')).to_have_count(0)
    expect(page.locator('[data-testid="source-column-select"]')).to_have_count(0)
    expect(page.locator('[data-testid="validate-corpus-select"]')).to_have_count(0)
    expect(page.locator('[data-testid="derivation-expression"]')).to_have_text("count_objects")

    # The type chip cycles the catalogue; the value type follows the choice
    # (`features_view._set_derivation`) rather than being picked by hand.
    page.click('[data-testid="derivation-type-chip"]')
    expression = page.locator('[data-testid="derivation-expression"]')
    expect(expression).to_contain_text("count_persons")
    expect(page.locator('[data-testid="value-type-select"]')).to_have_value("integer")
    # Compared verbatim after the reload rather than spelled out here: how an
    # empty filter renders is `derivation_builder`'s business, and what this
    # journey pins is that the same spec comes back.
    saved_expression = expression.inner_text()

    page.fill('[data-testid="feature-key"]', "vehicles_derived")
    _save_and_wait_for_the_rename(page, "vehicles_derived")

    page.reload()
    _expect_open_on_the_newest_set(page, feature_config_id)
    _open_feature_for_editing(page, "vehicles_derived")
    expect(page.locator('[data-testid="grain-select"]')).to_have_value("derived")
    expect(page.locator('[data-testid="value-type-select"]')).to_have_value("integer")
    expect(page.locator('[data-testid="derivation-expression"]')).to_have_text(saved_expression)


def test_switching_a_feature_to_exploratory_round_trips_its_kind(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    """Case D: promoting a feature to exploratory withdraws almost the whole
    edit zone — grain, value type, source column and matching rule all stop
    being the analyst's to set (mvp-spec.md §8.1: an exploratory feature is
    reported, never scored).

    That is the widest conditional rendering on this screen, and the kind is
    what the feature count splits on, so both are asserted before and after
    the reload.
    """
    feature_config_id = _create_draft_feature_config(page, server_url, "J8 exploratory edit set")

    page.goto(f"{server_url}/features")
    _expect_open_on_the_newest_set(page, feature_config_id)
    _add_feature_through_the_ui(page, key="phone_use", exploratory=False, source_column="HandyFeld")
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("1 + 0 features")

    _open_feature_for_editing(page, "phone_use")
    expect(page.locator('[data-testid="grain-select"]')).to_have_count(1)

    page.locator('[data-testid="seg-option"]', has_text="Exploratory").click()
    expect(_readout(page, "n/a — narrative only")).to_have_count(1)

    # Conditional rendering: nothing left to choose but the key and the prose.
    expect(page.locator('[data-testid="grain-select"]')).to_have_count(0)
    expect(page.locator('[data-testid="value-type-select"]')).to_have_count(0)
    expect(page.locator('[data-testid="source-column-input"]')).to_have_count(0)
    expect(page.locator('[data-testid="validate-corpus-select"]')).to_have_count(0)
    expect(_readout(page, "n/a — reported, not typed")).to_have_count(1)
    expect(_readout(page, "n/a — no ground truth")).to_have_count(1)
    expect(_readout(page, "discovery rate")).to_have_count(1)
    expect(page.get_by_text("narrative only — no source column exists for this")).to_have_count(1)
    expect(page.locator('[data-testid="exploratory-budget"]')).to_have_count(1)

    page.click('[data-testid="save-feature"]')
    # The count splits on kind: the labelled feature became the exploratory one.
    expect(page.locator('[data-testid="feature-count"]')).to_have_text("0 + 1 features")

    page.reload()
    _expect_open_on_the_newest_set(page, feature_config_id)
    _open_feature_for_editing(page, "phone_use")
    expect(page.locator('[data-testid="grain-select"]')).to_have_count(0)
    expect(page.locator('[data-testid="value-type-select"]')).to_have_count(0)
    expect(_readout(page, "n/a — narrative only")).to_have_count(1)
    expect(_readout(page, "discovery rate")).to_have_count(1)
    expect(page.locator('[data-testid="exploratory-budget"]')).to_have_count(1)

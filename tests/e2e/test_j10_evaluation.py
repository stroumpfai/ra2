"""J10 — launch an evaluation and watch it finish (sw-design.md §11.5).

> Seed a corpus, a frozen feature set and a prompt template through the API;
> then, through the Evaluation UI: select two models, launch, poll to
> completion, and assert two runs `done`, the runs-table rows, the dev marker
> on a dev-sized run, and that the reproducibility card names every field
> `mvp-spec.md` §19.8 requires.

**What is seeded through `/api/v1`, and why.** The corpus, the frozen feature
set, the prompt template and the evaluation *draft row* are preconditions this
view cannot create for itself — Import freezes corpora, Features freezes sets,
Prompts saves templates, and none of those is the journey under test. J8 set
the precedent and the reasoning is the same: seed the precondition through the
router that already exists, drive the thing under test through its own UI.

The draft row is included deliberately. The E2E server is **session-scoped**
and shared with J1/J2/J7/J8, which leave corpora and feature sets behind, so
"the newest corpus" and "the newest frozen set" are not stable facts across a
whole session. `POST /api/v1/evaluations` pins both by id, and the view then
shows *that* evaluation — which makes this journey independent of what ran
before it. ("Save draft" creating the row from nothing is covered at layer 3,
in `tests/ui/test_evaluation_view.py`.)

**The corpus is deliberately tiny** (three `unfall` records), so it is below
`RA2_EVAL_RECORD_MIN` and `EvaluationService.launch` stamps `is_dev` — which
is exactly the dev marker this journey has to assert, produced by the rule
rather than forced by a fixture.

**Nothing here touches a socket or a real GPU.** `tests/e2e/conftest.py`
builds the session server with `FakeLLMClient`, `StaticModelCatalog` and a
`StaticGpuProbe` (RTX 4090, 24 GB) injected through `create_app()`'s ordinary
keyword arguments (plan-phase-3.md §11).

**The journey runs past the launch.** A launched evaluation is where this view
used to stop: every setup control read-only, nothing on screen saying why, and
no way back to an editable one — while the step-2 copy this journey already
asserts tells the analyst to "clone into a new evaluation". So the last leg
presses **"New evaluation"** and asserts the exit is real in a browser: the
lock sentence goes, the selects come back, and the models are tickable again
(`sw-design.md` §13 `SD32`).

That leg leaves **one extra draft** on the session-scoped server, deliberately
and inertly. It is this journey's own second evaluation, it cites this
journey's corpus and feature set, and it has no runs. The one query that could
notice it is `_current_evaluation`'s "newest", and the only two rows sharing
the frozen clock's instant there are J10's draft and J10's clone — the journey
that does depend on being newest (`test_reset_discard.py`) stamps its own
`created_at` far past both, for exactly this reason.

**The second test is the dialog-clipping check.** L3's own suite proves
`ollama_settings_dialog` uses `dialog_card`'s 96vw wrapper *structurally*; only
a real viewport can prove the box that results actually fits, and the gear
button that opens it belongs to this view. Phase 2 shipped a dialog clipped by
Quasar's own `max-width:560px`, and that wrapper is its fix — so the regression
is asserted where it could actually be seen, at 1024px, the narrowest viewport
this app supports (sw-design.md §8.2).
"""

import json
import re
from pathlib import Path
from typing import cast

import pytest
from playwright.sync_api import Page, expect
from tests.fixtures.fake_llm import DEFAULT_MODELS

import ra2.ui.views.evaluation_view as evaluation_view

pytestmark = pytest.mark.e2e

#: `tests/e2e/` -> `tests/`.
_HAZARDS = Path(__file__).resolve().parents[1] / "fixtures" / "deliveries" / "hazards"

#: One complete cantonal set — the same combination J8 and the layer-3 suites
#: use, and small enough that two real runs finish inside a browser test.
DELIVERY: dict[str, str] = {
    "one.txt": "h08_all_empty_column/unfall.txt",
    "two.txt": "h10_count_mismatch/objekt.txt",
    "three.txt": "h10_count_mismatch/person.txt",
}

WEATHER_COLUMN = "Witter0Ausw"

#: Both required slots, no unknown one (`domain.prompt.validate_template`).
TEMPLATE_SOURCE = (
    "You extract structured facts from Swiss accident reports.\n\n"
    "{{feature_block}}\n\n"
    "--- narrative ---\n"
    "{{narrative}}\n"
)

#: The two models the journey selects. The third in `StaticModelCatalog` is
#: 42.5 GB against the fixture GPU's 24 GB, so it renders disabled and is
#: deliberately left alone.
MODEL_A = DEFAULT_MODELS[0].tag
MODEL_B = DEFAULT_MODELS[1].tag
OVER_VRAM = DEFAULT_MODELS[2].tag

JSON_HEADERS = {"Content-Type": "application/json"}
TIMEOUT_MS = 60_000

#: `dd.mm.yy - hh:mm:ss` (README §2, "Runs table").
TIMESTAMP_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2} - \d{2}:\d{2}:\d{2}$")
RESULTS_HREF_RE = re.compile(r"^/results\?run=.+$")


@pytest.fixture
def delivery_root(tmp_path: Path) -> Path:
    root = tmp_path / "j10-delivery"
    root.mkdir(parents=True)
    for name, source in DELIVERY.items():
        (root / name).write_bytes((_HAZARDS / source).read_bytes())
    return root


# --- seeding through /api/v1 --------------------------------------------------


def _post(
    page: Page, server_url: str, path: str, body: dict[str, object] | None = None
) -> dict[str, object]:
    response = page.request.post(
        f"{server_url}{path}",
        data=json.dumps(body if body is not None else {}),
        headers=JSON_HEADERS,
    )
    assert response.ok, f"POST {path}: {response.status} {response.text()}"
    return dict(response.json())


def _get(page: Page, server_url: str, path: str) -> dict[str, object]:
    response = page.request.get(f"{server_url}{path}")
    assert response.ok, f"GET {path}: {response.status} {response.text()}"
    return dict(response.json())


def _seed_corpus(page: Page, server_url: str, root: Path) -> str:
    """Register + analyse + freeze one small corpus, entirely through the API."""
    delivery = _post(
        page,
        server_url,
        "/api/v1/deliveries",
        {"name": "j10", "source_kind": "host_path", "root_path": str(root)},
    )
    delivery_id = str(delivery["delivery_id"])
    _post(page, server_url, f"/api/v1/deliveries/{delivery_id}/analyse")
    for _ in range(300):
        current = _get(page, server_url, f"/api/v1/deliveries/{delivery_id}")
        if current["status"] in ("analysed", "failed"):
            assert current["status"] == "analysed", current
            break
        page.wait_for_timeout(100)
    else:  # pragma: no cover - the assertion below reports it
        raise AssertionError("the delivery never finished analysing")
    corpus = _post(
        page,
        server_url,
        "/api/v1/corpora",
        {"delivery_id": delivery_id, "name": "j10-corpus"},
    )
    return str(corpus["corpus_id"])


def _seed_frozen_feature_set(page: Page, server_url: str) -> str:
    """One labelled free-text feature, then freeze.

    Free text rather than `enum` on purpose: an `enum` feature with no code
    table is one of mvp-spec.md §7's blocking evaluation-setup gates, and this
    journey is about launching, not about that refusal (J2 owns refusals).
    """
    config = _post(page, server_url, "/api/v1/feature-configs", {"name": "J10 weather"})
    config_id = str(config["feature_config_id"])
    _post(
        page,
        server_url,
        f"/api/v1/feature-configs/{config_id}/features",
        {
            "key": "weather",
            "kind": "labelled",
            "description": "The weather at the time of the accident.",
            "grain": "accident",
            "source_column": WEATHER_COLUMN,
            "value_type": "free_text",
            "matching_rule": {"kind": "exact"},
        },
    )
    frozen = _post(page, server_url, f"/api/v1/feature-configs/{config_id}/freeze")
    assert frozen["frozen_at"] is not None, frozen
    return config_id


def _seed_active_template(page: Page, server_url: str) -> str:
    template = _post(page, server_url, "/api/v1/prompt-templates", {"source": TEMPLATE_SOURCE})
    template_id = str(template["prompt_template_id"])
    _post(page, server_url, f"/api/v1/prompt-templates/{template_id}/activate")
    return template_id


def _seed_draft(page: Page, server_url: str, *, corpus_id: str, config_id: str) -> str:
    draft = _post(
        page,
        server_url,
        "/api/v1/evaluations",
        {"name": "J10", "corpus_id": corpus_id, "feature_config_id": config_id},
    )
    return str(draft["evaluation_id"])


# --- the journey --------------------------------------------------------------


def test_j10_launch_an_evaluation_and_watch_it_finish(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    corpus_id = _seed_corpus(page, server_url, delivery_root)
    config_id = _seed_frozen_feature_set(page, server_url)
    _seed_active_template(page, server_url)
    evaluation_id = _seed_draft(page, server_url, corpus_id=corpus_id, config_id=config_id)

    page.goto(f"{server_url}/evaluation")
    expect(page.locator('[data-testid="view-title"]')).to_have_text("Evaluation")

    # --- the setup column, as the design draws it -----------------------------
    expect(page.locator('[data-testid="step-label"]')).to_have_count(6)
    # The corrected step-2 copy (plan-phase-3.md C5 / R6) — not the stale note.
    note = page.locator('[data-testid="feature-set-note"]')
    expect(note).to_have_text(evaluation_view.FEATURE_SET_NOTE)
    expect(note).not_to_contain_text("Freezes when the first run executes")
    # The endpoint is reachable, so Launch is only waiting on a selection.
    expect(page.locator('[data-testid="endpoint-line"]')).to_contain_text("reachable")
    expect(page.locator('[data-testid="endpoint-reason"]')).to_have_count(0)
    expect(page.locator('[data-testid="launch"]')).to_have_text("Launch 0 runs")
    expect(page.locator('[data-testid="launch"]')).to_be_disabled()
    # The model that cannot fit 24 GB is the one drawn disabled.
    expect(page.locator(f'[data-testid="model-row"][data-model="{OVER_VRAM}"]')).to_have_attribute(
        "data-disabled", "true"
    )

    # --- select two models ----------------------------------------------------
    _select_model(page, MODEL_A)
    expect(page.locator('[data-testid="launch"]')).to_have_text("Launch 1 run")
    _select_model(page, MODEL_B)
    expect(page.locator('[data-testid="launch"]')).to_have_text("Launch 2 runs")
    expect(page.locator('[data-testid="models-count"]')).to_contain_text("2 selected")
    expect(page.locator('[data-testid="launch"]')).to_be_enabled()

    # --- launch, and poll to completion --------------------------------------
    page.click('[data-testid="launch"]')
    rows = page.locator('[data-testid="run-status"]')
    expect(rows).to_have_count(2, timeout=TIMEOUT_MS)
    done = page.locator('[data-testid="run-status"][data-status="done"]')
    expect(done).to_have_count(2, timeout=TIMEOUT_MS)

    # The service agrees with the screen: two `done` runs on this evaluation.
    runs = _get(page, server_url, f"/api/v1/runs?evaluation_id={evaluation_id}")
    items = cast("list[dict[str, object]]", runs["items"])
    assert sorted(str(run["status"]) for run in items) == ["done", "done"], runs

    # --- the runs table ------------------------------------------------------
    # Three records is far below `RA2_EVAL_RECORD_MIN`, so the launch stamped
    # `is_dev` and every row carries the marker — "smoke test, not a result".
    expect(page.locator('[data-testid="run-status"][data-dev="true"]')).to_have_count(2)
    # The marker is a chip **beside** the status word, not in place of it: the
    # design draws the replacement, and on a board where every run is dev-sized
    # that leaves a Status column showing one constant string.
    expect(page.locator('[data-testid="run-status"]').first).to_have_text("done")
    expect(page.locator('[data-testid="run-dev"]')).to_have_count(2)
    tags = page.locator('[data-testid="run-model"]')
    expect(tags).to_have_count(2)
    assert {MODEL_A, MODEL_B} == set(tags.all_text_contents())
    # `dd.mm.yy - hh:mm:ss`, on one line, for a started run.
    started = page.locator('[data-testid="run-started"]').first
    expect(started).to_have_text(TIMESTAMP_RE)
    # A run is named by its ordinal and links to Results — a placeholder route
    # this phase. The id is a 36-character uuid7 that does not fit the column
    # and does not distinguish two runs launched together; it rides the title.
    first_link = page.locator('[data-testid="run-link"]').first
    expect(first_link).to_have_attribute("href", RESULTS_HREF_RE)
    expect(first_link).to_have_text("run 1")
    assert first_link.get_attribute("title"), "the full id stays reachable"
    expect(page.locator('[data-testid="pagination-range"]')).to_have_text("1–2 of 2")
    # One progress card per run (the card's own body is L3's).
    expect(page.locator('[data-testid="progress-card"]')).to_have_count(2)
    expect(page.locator('[data-testid="progress-card-model"]')).to_have_count(2)

    # --- the reproducibility card --------------------------------------------
    provenance = page.locator('[data-testid="provenance-line"]')
    expect(provenance).to_have_count(1)
    line = provenance.inner_text()
    # Every field mvp-spec.md §19.8 requires, by name.
    assert "8fa1c3d0" in line or "c17b904e" in line, line  # model digest
    assert MODEL_A in line or MODEL_B in line, line  # model name
    assert "prompt template v1" in line, line
    assert "temperature 0.0" in line, line
    assert "seed 42" in line, line
    assert f"cfg {config_id}" in line, line  # feature config + fingerprints
    assert "weather " in line, line  # the per-feature fingerprint, by key
    assert f"corpus {corpus_id} v1" in line, line
    assert "host " in line, line
    assert "gpu RTX 4090" in line, line
    assert "endpoint 127.0.0.1:11434/v1" in line, line
    expect(page.locator('[data-testid="provenance-explainer"]')).to_have_text(
        evaluation_view.PROVENANCE_EXPLAINER
    )

    # --- launched is locked, and now says why ---------------------------------
    expect(page.locator('[data-testid="launch"]')).to_be_disabled()
    expect(page.locator('[data-testid="corpus-select"]')).to_be_disabled()
    # The column states the reason instead of simply going dead (SD32).
    expect(page.locator('[data-testid="launched-note"]')).to_have_text(
        evaluation_view.LAUNCHED_MESSAGE
    )
    # Nothing on a launched evaluation is left to save, so the toolbar offers
    # the only thing that can still act.
    expect(page.locator('[data-testid="save-draft"]')).to_have_count(0)
    expect(page.locator('[data-testid="new-evaluation"]')).to_have_text(
        evaluation_view.NEW_EVALUATION_LABEL
    )

    # --- and it is not a dead end ---------------------------------------------
    page.click('[data-testid="new-evaluation"]')
    # The toolbar swapping is the redraw landing on the new draft.
    expect(page.locator('[data-testid="save-draft"]')).to_have_count(1, timeout=TIMEOUT_MS)
    expect(page.locator('[data-testid="launched-note"]')).to_have_count(0)
    expect(page.locator('[data-testid="corpus-select"]')).to_be_enabled()
    expect(page.locator('[data-testid="launch"]')).to_have_text("Launch 0 runs")
    expect(page.locator('[data-testid="new-evaluation"]')).to_have_count(0)

    # The clone cites the same corpus and the same frozen feature set — the
    # "clone into a new evaluation" step 2 asks for, not a blank one. Read
    # back through the API, so this is about the row and not about the screen
    # that just redrew.
    clone = _clone_of(page, server_url, corpus_id=corpus_id, besides=evaluation_id)
    assert clone["feature_config_id"] == config_id, clone
    assert clone["launched_at"] is None, clone

    # Step 4's ticks are live again, which is the point of the exit. The clone
    # is deliberately **not** launched: a second worker pass buys this journey
    # nothing and the launch itself is already asserted above.
    _select_model(page, MODEL_A)
    expect(page.locator('[data-testid="launch"]')).to_have_text("Launch 1 run")
    expect(page.locator('[data-testid="launch"]')).to_be_enabled()
    # The launched evaluation is untouched — a clone adds a row (Do-NOT #2).
    original = _get(page, server_url, f"/api/v1/evaluations/{evaluation_id}")
    draft = cast("dict[str, object]", original["draft"])
    assert draft["launched_at"] is not None, original


def _clone_of(page: Page, server_url: str, *, corpus_id: str, besides: str) -> dict[str, object]:
    """The one evaluation citing this journey's corpus that is not `besides`.

    Scoped by corpus rather than taken as "the newest", because the server is
    shared and `created_at` is the frozen clock's for every row on it.
    """
    response = page.request.get(f"{server_url}/api/v1/evaluations")
    assert response.ok, f"GET /api/v1/evaluations: {response.status} {response.text()}"
    rows = cast("list[dict[str, object]]", response.json())
    matching = [
        row
        for row in rows
        if row["corpus_id"] == corpus_id and str(row["evaluation_id"]) != besides
    ]
    assert len(matching) == 1, matching
    return matching[0]


def _select_model(page: Page, tag: str) -> None:
    page.locator(f'[data-testid="model-row"][data-model="{tag}"] [data-testid="tick"]').click()
    expect(
        page.locator(f'[data-testid="model-row"][data-model="{tag}"] [data-testid="tick"]')
    ).to_have_attribute("aria-checked", "true")


def test_j10_the_connection_settings_dialog_opens_unclipped_at_1024px(
    page: Page, server_url: str
) -> None:
    """The Models card's gear opens L3's settings dialog **fully inside** a
    1024px viewport.

    L3's layer-3 suite can only prove `dialog_card`'s 96vw wrapper is *used*;
    whether the box that results actually fits needs a laid-out page, which
    this layer is what provides — and the gear that opens the dialog is this
    view's button, so the check belongs here (module docstring).

    Nothing is seeded: the Models card and its gear render whatever the
    database holds, which is what makes this assertion independent of every
    other journey on the session-scoped server.
    """
    page.set_viewport_size({"width": 1024, "height": 800})
    page.goto(f"{server_url}/evaluation")
    expect(page.locator('[data-testid="view-title"]')).to_have_text("Evaluation")

    page.click('[aria-label="Ollama connection settings"]')
    dialog = page.locator('[data-testid="ollama-settings-dialog"] [data-testid="card"]')
    expect(dialog).to_be_visible()
    # Quasar scales the dialog in, so a box measured the instant it becomes
    # visible is a fraction of the final one — and a fraction of a card always
    # fits, which would make the clipping assertion below pass on a dialog that
    # actually clips. Wait for the box to stop changing first. This matters
    # more since the dialog grew to five controls (P3-D19).
    page.wait_for_function(
        """() => {
            const el = document.querySelector(
                '[data-testid="ollama-settings-dialog"] [data-testid="card"]');
            if (!el) return false;
            const now = el.getBoundingClientRect().height;
            const settled = window.__ra2DialogHeight === now && now > 0;
            window.__ra2DialogHeight = now;
            return settled;
        }"""
    )

    box = dialog.bounding_box()
    assert box is not None, "the dialog card has no layout box"
    assert box["x"] >= 0, f"the dialog is clipped on the left: {box}"
    assert box["x"] + box["width"] <= 1024, f"the dialog is clipped on the right: {box}"

    # Every control is laid out and reachable, not merely in the DOM. The
    # dialog grew from three controls to five (P3-D19) and its height is the
    # reason this assertion is worth keeping: the clipping fix has to hold for
    # the taller dialog too.
    for testid in (
        "ollama-endpoint",
        "ollama-timeout",
        "ollama-test",
        "ollama-refresh",
        "ollama-save",
    ):
        expect(page.locator(f'[data-testid="{testid}"]')).to_be_visible()
    assert not page.evaluate("document.body.scrollWidth > document.body.clientWidth + 1"), (
        "the open dialog made the page scroll horizontally"
    )

    # The connection test is wired end to end: press it and a verdict appears.
    # `StaticEndpointProber` answers (e2e/conftest.py) — no journey dials 11434.
    page.click('[data-testid="ollama-test"]')
    expect(page.locator('[data-testid="ollama-test-sentence"]')).to_be_visible()

    # The loopback gate, in a real browser: a LAN address disables Save.
    endpoint = page.locator('[data-testid="ollama-endpoint"]')
    endpoint.fill("http://192.168.1.5:11434/v1")
    endpoint.blur()
    expect(page.locator('[data-testid="ollama-endpoint-error"]')).to_be_visible()
    expect(page.locator('[data-testid="ollama-save"]')).to_be_disabled()

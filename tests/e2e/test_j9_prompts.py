"""J9 — copy-on-write a prompt template through the Prompts UI (sw-design.md §11.5).

> Seed templates **through the API**, edit the active version, save as the next
> one, and assert the old version is **still present, still byte-identical, and
> now shows `locked`**.

**Why this journey seeds a whole launch and not just a template.** `locked` is
not a styling choice — the design defines it as "only a version with zero runs
can be deleted; all others show `locked`", and `PromptTemplateView.deletable`
is a live `COUNT(run WHERE prompt_template_id = …)`. So the only way to reach
that marker honestly is for a real `run` row to cite the seeded version, and a
`run` needs an `evaluation`, which needs a corpus and a **frozen** feature set.
Every one of those is seeded through the already-live API
(`/api/v1/prompt-templates`, `/feature-configs`, `/evaluations`) except the
corpus, which has no API shortcut past the delivery pipeline and is therefore
registered and frozen through the Import UI exactly as
`test_j8_features.py` does it. The bodies are the ones
`tests/backend/api/evaluations/_seed.py` already proves: one `exploratory`
`free_text` feature, so the launch never needs a codelist snapshot.

The launch is `dev`-sized on purpose — `RA2_DEV_RECORD_MAX` caps the worker's
scope, and the E2E server's `FakeLLMClient` answers instantly, so the run rows
this journey needs exist without the journey waiting on a corpus-sized pass.

Everything after the seeding is this view's own controls: selecting the
version, opening the editor on the rendered source, typing, and pressing the
primary "Save as vN" button.
"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

#: `tests/e2e/` -> `tests/`.
_HAZARDS = Path(__file__).resolve().parents[1] / "fixtures" / "deliveries" / "hazards"

#: One complete cantonal set — the same combination J8 uses, for the same
#: reason: it freezes into a real corpus with real records.
DELIVERY: dict[str, str] = {
    "one.txt": "h08_all_empty_column/unfall.txt",
    "two.txt": "h10_count_mismatch/objekt.txt",
    "three.txt": "h10_count_mismatch/person.txt",
}

#: `tests/fixtures/fake_llm.py`'s first fixture model — 8.5 GB against the
#: E2E server's 24 GB `StaticGpuProbe`, so the launch is feasible.
MODEL = "llama3.1:8b-instruct-q8_0"

#: The version this journey seeds. Both required slots, so it saves; the
#: trailing newline and the blank lines are part of it — whitespace is part of
#: a prompt, and the byte-identity assertion below depends on saying so.
SEEDED_SOURCE = (
    "You extract structured facts from Swiss accident reports.\n"
    "\n"
    "Never guess to fill a field.\n"
    "\n"
    "{{feature_block}}\n"
    "\n"
    "--- narrative ---\n"
    "{{narrative}}\n"
)

#: The edit the analyst makes. Still valid — both required slots survive.
EDITED_SOURCE = SEEDED_SOURCE.replace(
    "Never guess to fill a field.",
    "Never guess to fill a field. If the narrative is silent, leave it empty.",
)

_JSON = {"Content-Type": "application/json"}


@pytest.fixture
def delivery_root(tmp_path: Path) -> Path:
    root = tmp_path / "j9-delivery"
    root.mkdir(parents=True)
    for name, source in DELIVERY.items():
        (root / name).write_bytes((_HAZARDS / source).read_bytes())
    return root


# --- seeding -----------------------------------------------------------------


def _register_and_freeze_corpus(page: Page, server_url: str, root: Path) -> str:
    """Register + analyse + freeze one corpus through the Import UI, then read
    its id back from the API.

    `test_j1_delivery_to_census.py`'s own first act, repeated rather than
    imported (tests/e2e has no shared per-journey helper module by design).
    The corpus count is asserted as **one more than before**: the E2E server is
    session-scoped and the earlier journeys legitimately leave corpora behind.
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

    response = page.request.get(f"{server_url}/api/v1/corpora?sort_key=imported_at&sort_dir=desc")
    assert response.ok, response.text()
    corpus_id: str = response.json()["items"][0]["corpus_id"]
    return corpus_id


def _seed_template(page: Page, server_url: str, source: str) -> dict[str, object]:
    """ "Seed templates through the API" — `POST /api/v1/prompt-templates`,
    then activate it, since the active version is the one the board opens on
    and the one a new evaluation pins."""
    response = page.request.post(
        f"{server_url}/api/v1/prompt-templates",
        data=json.dumps({"source": source}),
        headers=_JSON,
    )
    assert response.status == 201, response.text()
    template = response.json()
    activated = page.request.post(
        f"{server_url}/api/v1/prompt-templates/{template['prompt_template_id']}/activate"
    )
    assert activated.ok, activated.text()
    body: dict[str, object] = activated.json()
    return body


def _seed_frozen_feature_set(page: Page, server_url: str) -> str:
    """One `exploratory` `free_text` feature, frozen — the least setup a
    launch accepts (see the module docstring)."""
    response = page.request.post(
        f"{server_url}/api/v1/feature-configs",
        data=json.dumps({"name": "J9 notes"}),
        headers=_JSON,
    )
    assert response.status == 201, response.text()
    config_id: str = response.json()["feature_config_id"]
    response = page.request.post(
        f"{server_url}/api/v1/feature-configs/{config_id}/features",
        data=json.dumps(
            {
                "key": "note",
                "kind": "exploratory",
                "description": "A free-text note.",
                "grain": "accident",
                "source_column": "Bemerkung",
                "value_type": "free_text",
                "matching_rule": {"kind": "none"},
            }
        ),
        headers=_JSON,
    )
    assert response.ok, response.text()
    response = page.request.post(f"{server_url}/api/v1/feature-configs/{config_id}/freeze")
    assert response.ok, response.text()
    return config_id


def _launch(page: Page, server_url: str, *, corpus_id: str, config_id: str) -> None:
    """One `dev`-sized evaluation over one model, launched — which is what
    makes the active template *cited* (see the module docstring)."""
    response = page.request.post(
        f"{server_url}/api/v1/evaluations",
        data=json.dumps(
            {"name": "J9 evaluation", "corpus_id": corpus_id, "feature_config_id": config_id}
        ),
        headers=_JSON,
    )
    assert response.status == 201, response.text()
    evaluation_id: str = response.json()["evaluation_id"]
    response = page.request.put(
        f"{server_url}/api/v1/evaluations/{evaluation_id}",
        data=json.dumps({"selected_models": [MODEL], "size": "dev"}),
        headers=_JSON,
    )
    assert response.ok, response.text()
    response = page.request.post(f"{server_url}/api/v1/evaluations/{evaluation_id}/launch")
    assert response.ok, response.text()


def _template(page: Page, server_url: str, template_id: str) -> dict[str, object]:
    response = page.request.get(f"{server_url}/api/v1/prompt-templates/{template_id}")
    assert response.ok, response.text()
    body: dict[str, object] = response.json()
    return body


def _row(version: int) -> str:
    return f'[data-testid="version-row"][data-version="{version}"]'


# --- the journey -------------------------------------------------------------


def test_j9_saving_a_new_version_leaves_the_cited_one_byte_identical(
    page: Page, server_url: str, delivery_root: Path
) -> None:
    """The design's own story, end to end: v_n is active and cited; the
    analyst edits it; "Save as v_n+1" writes a **new** row and the old one is
    still there, still byte-identical, now `locked`."""
    corpus_id = _register_and_freeze_corpus(page, server_url, delivery_root)
    seeded = _seed_template(page, server_url, SEEDED_SOURCE)
    template_id = str(seeded["prompt_template_id"])
    version = int(str(seeded["version"]))
    config_id = _seed_frozen_feature_set(page, server_url)
    _launch(page, server_url, corpus_id=corpus_id, config_id=config_id)

    page.goto(f"{server_url}/prompts")
    page.wait_for_selector('[data-testid="slot-table"]')

    # The board opens on the active version, which the launch has now cited.
    row = page.locator(_row(version))
    expect(row).to_have_attribute("data-marker", "active")
    expect(row).to_have_attribute("aria-current", "true")
    expect(row.locator('[data-testid="active-pill"]')).to_have_text("ACTIVE")
    expect(page.locator('[data-testid="version-sub"]').first).to_contain_text("cited by")

    # Every slot in the source is picked out inline, and the copy-on-write
    # footer names the version the save will create.
    expect(page.locator('[data-testid="source-body"] [data-testid="slot-token"]')).to_have_count(2)
    expect(page.locator('[data-testid="cow-footer"]')).to_contain_text(
        f"Saving creates v{version + 1}. v{version} stays as it is"
    )

    # Edit the active version…
    page.click('[data-testid="source-body"]')
    page.wait_for_selector('[data-testid="source-editor"]')
    page.fill('[data-testid="source-editor"]', EDITED_SOURCE)

    # …and save it as the next one.
    save = page.locator('[data-testid="save-template"]')
    expect(save).to_have_text(f"Save as v{version + 1}")
    save.click()
    expect(page.locator(_row(version + 1))).to_have_count(1, timeout=15_000)

    # The old version is still present — and now `locked`, because runs cite it.
    old = page.locator(_row(version))
    expect(old).to_have_count(1)
    expect(old).to_have_attribute("data-marker", "locked")
    expect(old.locator('[data-testid="locked"]')).to_have_text("locked")
    expect(old.locator('[data-testid="delete-version"]')).to_have_count(0)

    # …and still byte-identical, asserted on the bytes the API hands back.
    kept = _template(page, server_url, template_id)
    assert str(kept["source"]).encode("utf-8") == SEEDED_SOURCE.encode("utf-8")
    assert kept["fingerprint"] == seeded["fingerprint"]
    assert kept["deletable"] is False
    assert kept["is_active"] is False

    # The new version carries the edit, and is the one new evaluations get.
    listed = page.request.get(f"{server_url}/api/v1/prompt-templates")
    assert listed.ok, listed.text()
    saved = next(t for t in listed.json() if t["version"] == version + 1)
    assert saved["source"] == EDITED_SOURCE
    assert saved["is_active"] is True
    assert saved["prompt_template_id"] != template_id
    expect(page.locator(_row(version + 1))).to_have_attribute("data-marker", "active")

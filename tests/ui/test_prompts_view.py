"""Layer 3 — the Prompts view (sw-design.md §11.3, `design/prompt-evaluation`).

Everything below drives the **real** view through the **real** `PromptService`
over a real migrated temp-file SQLite database. Nothing is mocked: the template
sources are H1's committed hazard fixtures
(`tests/fixtures/prompts/hazards/p01..p05`), saved through
`PromptService.save_as_next_version`, and every marker asserted on is a
`PromptTemplateView` field the service computed — the citation count behind
`locked` is the live `COUNT(run …)`, which is why the fixture below inserts a
real `run` row rather than pretending one exists.

**Three pieces of test plumbing, and why each is here.**

1. *The route needs no help.* Unlike phase 2's view suites, this branch is
   allowed to flip its own `built` flag (plan-phase-3.md §6.1), so `/prompts`
   is the real view as soon as `create_app()` returns and nothing has to
   re-register it.

2. *The placed component is stubbed, deliberately.* `prompt_preview_panel`
   (`ra2/ui/components/prompt_preview.py`) is L3's, built in parallel this same
   wave against a signature frozen at M17 — its body was still `raise
   NotImplementedError` in this worktree (based on `p3w3-green`) when this
   suite was written, and it has since landed on `main`. `stub_preview_panel`
   patches it in this test file only (never in production code — Do-NOT #12),
   and it stays patched now that the real body exists: what this view is
   responsible for is **placing** the panel and **what it hands it**, which is
   exactly what the fake records. That the panel then renders identically from
   both entry points is L3's own exit criterion, asserted against its golden
   string in L3's suite, not re-asserted here.

3. *The `locked` marker needs a citation.* `locked` is "some run cites this
   version", and a `run` row needs an `evaluation`, which needs a `corpus` and a
   `feature_config`. Those four rows are inserted straight through the session
   factory, exactly as `tests/ui/test_features_view.py` inserts a `Corpus` and
   an `Evaluation` to reach the frozen-set board: the alternative is launching a
   real evaluation, which is J10's journey, not this view's unit of behaviour.

The seeded lineage puts one version in each of the design's three marker
states, which is what makes "all four row markers" assertable in one render:

| version | citations | active | marker            |
|---------|-----------|--------|-------------------|
| v1      | 0         | no     | delete button     |
| v2      | 1         | no     | `locked`          |
| v3      | 0         | yes    | `ACTIVE` pill + selected-row treatment |
"""

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.element import Element
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction

import ra2.ui.views.prompts_view as prompts_view
from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.domain.prompt import PromptValidationCode
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.persistence.models import Corpus, Evaluation, Record, Run
from ra2.services.container import Services
from ra2.services.readmodels import PromptTemplateView, ResolvedPromptView
from ra2.ui.views.prompts_view import (
    ACTIVE_PILL,
    LOCKED,
    NO_PREVIEW_INPUTS_MESSAGE,
    NO_VERSIONS_MESSAGE,
    SLOTS_AVAILABLE,
    SOURCE_TITLE,
    WELL_HEIGHT_PX,
    citation_text,
    save_label,
    versions_label,
)

pytestmark = pytest.mark.ui

#: `tests/ui/` -> `tests/`.
_TESTS_ROOT = Path(__file__).resolve().parents[1]
_PROMPTS = _TESTS_ROOT / "fixtures" / "prompts" / "hazards"

CORPUS_ID = "corpus-prompts"
EVALUATION_ID = "eval-prompts"
RUN_ID = "run-prompts"
RECORD_ID = "record-prompts-1"


def hazard(name: str) -> str:
    """One committed hazard fixture's template source, verbatim."""
    return (_PROMPTS / name / "template.txt").read_text(encoding="utf-8")


@dataclass(frozen=True)
class Seeded:
    user: User
    services: Services
    versions: tuple[PromptTemplateView, ...]

    def version(self, number: int) -> PromptTemplateView:
        return next(v for v in self.versions if v.version == number)


# --- fixtures ----------------------------------------------------------------


async def _seed_citation(
    app: FastAPI,
    *,
    template: PromptTemplateView,
    clock: Clock,
    with_record: bool,
    with_evaluation: bool = True,
) -> None:
    """A `corpus` + `feature_config` + `evaluation` + `run` citing `template`.

    See the module docstring: `locked` is a live `COUNT(run …)`, so the only
    honest way to reach that marker is a real row.

    `with_evaluation=False` stops after the corpus, the record and the feature
    set — the state a fresh install is in before anyone has created an
    evaluation, which is the path `_preview_inputs` falls back to once L1's
    `CorpusService.first_record` amendment landed. No evaluation means no run,
    so nothing is `locked` in that variant.
    """
    services: Services = app.state.services
    config = await services.feature.create_draft(name="prompts-fixture")
    session_factory = app.state.session_factory
    async with session_factory() as session:
        session.add(
            Corpus(
                id=CorpusId(CORPUS_ID),
                name="prompts",
                imported_at=clock.now(),
                source_file_manifest_json="[]",
                import_report_json="[]",
                record_count=1 if with_record else 0,
            )
        )
        await session.flush()
        if with_record:
            session.add(
                Record(
                    id=RecordId(RECORD_ID),
                    corpus_id=CorpusId(CORPUS_ID),
                    unfall_uid="prompts-u1",
                    language="de",
                    language_confidence=1.0,
                    text_raw="Am 14.03.2026 gegen 07:40 Uhr, bei starkem Regen.",
                )
            )
        if not with_evaluation:
            await session.commit()
            return
        session.add(
            Evaluation(
                id=EvaluationId(EVALUATION_ID),
                name="a trivial evaluation",
                corpus_id=CorpusId(CORPUS_ID),
                feature_config_id=config.feature_config_id,
                prompt_template_id=template.prompt_template_id,
            )
        )
        await session.flush()
        session.add(
            Run(
                id=RunId(RUN_ID),
                evaluation_id=EvaluationId(EVALUATION_ID),
                model_name="llama3.1:8b-instruct-q8_0",
                model_digest="8fa1c3d0",
                prompt_template_version=template.version,
                prompt_template_id=PromptTemplateId(template.prompt_template_id),
                prompt_template_fingerprint=template.fingerprint,
                temperature=0.0,
                seed=42,
                host_platform="linux-x64",
            )
        )
        await session.commit()


async def _build(
    app_factory: Callable[..., FastAPI],
    *,
    frozen_clock: Clock,
    versions: tuple[str, ...],
    cite: int | None,
    activate: int | None,
    with_record: bool = False,
    with_evaluation: bool = True,
) -> AsyncIterator[Seeded]:
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True)
            services: Services = app.state.services
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                saved = [await services.prompt.save_as_next_version(s) for s in versions]
                if cite is not None:
                    await _seed_citation(
                        app,
                        template=saved[cite - 1],
                        clock=frozen_clock,
                        with_record=with_record,
                        with_evaluation=with_evaluation,
                    )
                if activate is not None:
                    await services.prompt.activate(saved[activate - 1].prompt_template_id)
                listed = tuple(await services.prompt.list_versions())
                yield Seeded(User(client), services, listed)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


@pytest.fixture
async def seeded(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """Three versions in the three marker states (see the module docstring)."""
    async for seeded in _build(
        app_factory,
        frozen_clock=frozen_clock,
        versions=(
            hazard("p01_valid_all_slots"),
            hazard("p04_duplicate_feature_block"),
            hazard("p07_narrative_literal_braces"),
        ),
        cite=2,
        activate=3,
    ):
        yield seeded


@pytest.fixture
async def single(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """One active version, nothing citing it — the save-flow fixture."""
    async for seeded in _build(
        app_factory,
        frozen_clock=frozen_clock,
        versions=(hazard("p01_valid_all_slots"),),
        cite=None,
        activate=1,
    ):
        yield seeded


@pytest.fixture
async def previewable(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """One active version plus an evaluation with a record in scope, so
    "Preview with record 1" has a feature set, a language and a record."""
    async for seeded in _build(
        app_factory,
        frozen_clock=frozen_clock,
        versions=(hazard("p01_valid_all_slots"),),
        cite=1,
        activate=1,
        with_record=True,
    ):
        yield seeded


@pytest.fixture
async def previewable_without_an_evaluation(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """A corpus with a record and a feature set, but **no evaluation** — a
    fresh install that has imported data and configured features but not yet
    set up a run."""
    async for seeded in _build(
        app_factory,
        frozen_clock=frozen_clock,
        versions=(hazard("p01_valid_all_slots"),),
        cite=1,
        activate=1,
        with_record=True,
        with_evaluation=False,
    ):
        yield seeded


@pytest.fixture
async def paged(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """Eleven versions — one more than the well's 10-row page."""
    source = hazard("p01_valid_all_slots")
    async for seeded in _build(
        app_factory,
        frozen_clock=frozen_clock,
        versions=tuple(f"{source}\n<!-- v{n} -->\n" for n in range(1, 12)),
        cite=None,
        activate=11,
    ):
        yield seeded


@pytest.fixture
async def empty(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """No template at all — the undesigned empty state."""
    async for seeded in _build(
        app_factory, frozen_clock=frozen_clock, versions=(), cite=None, activate=None
    ):
        yield seeded


def _restore_nicegui_functions() -> None:
    from nicegui.functions.download import download
    from nicegui.functions.navigate import Navigate
    from nicegui.functions.notify import notify

    ui.navigate = Navigate()
    ui.notify = notify
    ui.download = download


@pytest.fixture
def stub_preview_panel(monkeypatch: pytest.MonkeyPatch) -> list[ResolvedPromptView]:
    """L3's panel, stubbed in this test file only (see the module docstring).

    Returns the list it records its calls in, so the one thing this view is
    responsible for — *what it hands the panel* — is assertable.
    """
    calls: list[ResolvedPromptView] = []

    def _fake(*, resolved: ResolvedPromptView) -> Element:
        calls.append(resolved)
        return ui.element("div").props('data-testid="resolved-panel"').mark("resolved-panel")

    monkeypatch.setattr(prompts_view, "prompt_preview_panel", _fake)
    return calls


# --- helpers -----------------------------------------------------------------


def _own_text(element: Element) -> str:
    """A `ui.label`'s own text. `Element` itself has no `text`, which is why
    this goes through `getattr` rather than a cast."""
    return str(getattr(element, "text", ""))


def _ordered(elements: Iterable[Element]) -> list[Element]:
    """NiceGUI hands out ids in creation order, which is document order here."""
    return sorted(elements, key=lambda e: e.id)


def _find(user: User, testid: str) -> list[Element]:
    return _ordered(
        e for e in user.find(kind=ui.element).elements if e._props.get("data-testid") == testid
    )


def _one(user: User, element: Element) -> UserInteraction[Element]:
    return UserInteraction(user, {element}, None)


def _rows(user: User) -> list[Element]:
    return _find(user, "version-row")


def _row(user: User, version: int) -> Element:
    (element,) = [e for e in _rows(user) if e._props.get("data-version") == str(version)]
    return element


def _markers(user: User) -> dict[int, str]:
    return {int(str(e._props["data-version"])): str(e._props["data-marker"]) for e in _rows(user)}


def _texts(user: User, testid: str) -> list[str]:
    return [_own_text(e) for e in _find(user, testid)]


def _deep_text(element: Element) -> str:
    """An element's own text plus its children's, in document order — what a
    `<button>` or an `<h2>` built from a `ui.label` actually reads as."""
    parts = [_own_text(e) for e in [element, *_ordered(element.descendants())]]
    return " ".join(part for part in parts if part).strip()


def _deep_texts(user: User, testid: str) -> list[str]:
    return [_deep_text(e) for e in _find(user, testid)]


def _within(root: Element, testid: str) -> list[Element]:
    return _ordered(e for e in root.descendants() if e._props.get("data-testid") == testid)


async def _until(predicate: Callable[[], bool]) -> None:
    """Poll until `predicate()` is true.

    A click's handler is dispatched but not awaited by `UserInteraction.click`,
    so an async handler's effects are not guaranteed to be visible the instant
    `.click()` returns.
    """
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


async def _edit_source(user: User, text: str) -> None:
    """Open the editor on the rendered source and type a new template."""
    (body,) = _find(user, "source-body")
    _one(user, body).click()
    await _until(lambda: bool(_find(user, "source-editor")))
    (editor,) = _find(user, "source-editor")
    _one(user, editor).trigger("input", args=text)


# --- the four row markers (the exit criterion) --------------------------------


async def test_all_four_row_markers_render(seeded: Seeded) -> None:
    """README §1, Version list: the ACTIVE pill, `locked`, the `--danger`
    delete button on an uncited version, and the selected-row treatment.

    Every one of the three right-hand markers is a `PromptTemplateView` field
    (`is_active`, `cited_by_run_count`, `deletable`) the service computed; this
    view only decides which of them a row wears (§8.1.1).
    """
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SLOTS_AVAILABLE)

    # Newest first, exactly as `list_versions()` returned them.
    assert [str(e._props["data-version"]) for e in _rows(user)] == ["3", "2", "1"]
    assert _markers(user) == {3: "active", 2: "locked", 1: "deletable"}

    # 1 · the ACTIVE pill, on the active version and nowhere else.
    (pill,) = _find(user, "active-pill")
    assert _own_text(_ordered(pill.descendants())[0]) == ACTIVE_PILL
    assert _within(_row(user, 3), "active-pill")
    assert not _within(_row(user, 2), "active-pill")

    # 2 · `locked`, on the cited-but-inactive version.
    assert _texts(user, "locked") == [LOCKED]
    assert _within(_row(user, 2), "locked")

    # 3 · the 22x22 `--danger` delete button, on the uncited version only.
    (delete,) = _find(user, "delete-version")
    assert _within(_row(user, 1), "delete-version")
    assert "var(--danger)" in str(delete._style.get("color"))
    assert delete._style.get("width") == "22px"
    assert delete._style.get("height") == "22px"

    # 4 · the selected-row treatment, on the active version the board opens on.
    assert _row(user, 3)._props["aria-current"] == "true"
    assert _row(user, 3)._style.get("background") == "var(--accent-soft)"
    assert _row(user, 3)._style.get("border-left") == "2px solid var(--accent)"
    assert _row(user, 2)._props["aria-current"] == "false"
    assert _row(user, 2)._style.get("background") == "none"


async def test_selecting_a_version_moves_the_selected_row_treatment(seeded: Seeded) -> None:
    """README, Interactions: selecting a version loads it into the editor."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SLOTS_AVAILABLE)

    _one(user, _row(user, 1)).click()
    await _until(lambda: _row(user, 1)._props["aria-current"] == "true")

    assert _row(user, 3)._props["aria-current"] == "false"
    assert _deep_texts(user, "editing-title") == ["Template v1"]
    # …and the editor now shows that version's own source.
    (body,) = _find(user, "source-body")
    assert "{{language}}" in _slot_tokens(body)


def _slot_tokens(root: Element) -> list[str]:
    return [_own_text(e) for e in _within(root, "slot-token")]


# --- the rows' own copy -------------------------------------------------------


async def test_the_row_subtitles_name_the_citation_count(seeded: Seeded) -> None:
    """The design's `.rsub`: "created · citation count", and "never run" for a
    version no run cites."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SLOTS_AVAILABLE)

    assert _texts(user, "versions-count") == [versions_label(3)]
    assert _texts(user, "version-sub") == [
        citation_text(seeded.version(3)),
        citation_text(seeded.version(2)),
        citation_text(seeded.version(1)),
    ]
    assert citation_text(seeded.version(2)).endswith("cited by 1 run")
    assert citation_text(seeded.version(1)).endswith("never run")


# --- slot highlighting (the exit criterion) -----------------------------------


async def test_the_source_body_highlights_every_slot(seeded: Seeded) -> None:
    """README §1, Source card: "each slot token highlighted inline".

    p01 carries all three slots, so all three are picked out — and the prose
    between them is still rendered, byte-for-byte.
    """
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SOURCE_TITLE)

    _one(user, _row(user, 1)).click()
    await _until(lambda: _deep_texts(user, "editing-title") == ["Template v1"])

    (body,) = _find(user, "source-body")
    assert _slot_tokens(body) == ["{{language}}", "{{feature_block}}", "{{narrative}}"]
    for token in _within(body, "slot-token"):
        assert token._style.get("background") == "var(--accent-soft)"
    # The whole source survives the highlighting, unchanged.
    rendered = "".join(_own_text(e) for e in _ordered(body.descendants()) if _own_text(e))
    assert rendered == seeded.version(1).source


async def test_a_duplicated_slot_is_highlighted_twice(seeded: Seeded) -> None:
    """p04 places `{{feature_block}}` twice — legal, and both are marked."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SOURCE_TITLE)

    _one(user, _row(user, 2)).click()
    await _until(lambda: _deep_texts(user, "editing-title") == ["Template v2"])

    (body,) = _find(user, "source-body")
    assert _slot_tokens(body).count("{{feature_block}}") == 2


# --- save as the next version (the exit criterion) ----------------------------


async def test_save_as_next_version_writes_a_new_row_and_leaves_the_old_one(
    single: Seeded,
) -> None:
    """README, Interactions: "saving never mutates a version that any run
    cites — it creates the next version and leaves the old text
    byte-identical"."""
    user = single.user
    original = single.version(1)
    await user.open("/prompts")
    await user.should_see(save_label(2))

    edited = original.source.replace("Answer as JSON only", "Answer as JSON only, nothing else")
    await _edit_source(user, edited)
    _one(user, _find(user, "save-template")[0]).click()
    await _until(lambda: len(_rows(user)) == 2)

    versions = await single.services.prompt.list_versions()
    assert [v.version for v in versions] == [2, 1]
    saved = next(v for v in versions if v.version == 2)
    assert saved.source == edited
    # Byte-identical, on the bytes — not on equality of a parsed form.
    kept = next(v for v in versions if v.version == 1)
    assert kept.source.encode("utf-8") == original.source.encode("utf-8")
    assert kept.fingerprint == original.fingerprint
    # The new version is the one new evaluations default to, and the one the
    # editor is now on.
    assert saved.is_active
    assert not kept.is_active
    assert _markers(user) == {2: "active", 1: "deletable"}
    assert _deep_texts(user, "editing-title") == ["Template v2"]
    # …and the button now offers the version after that.
    assert _deep_texts(user, "save-template") == [save_label(3)]


async def test_new_version_seeds_the_editor_and_writes_nothing(single: Seeded) -> None:
    """ "New version" is not a save: under copy-on-write the write *is*
    "Save as vN"."""
    user = single.user
    await user.open("/prompts")
    await user.should_see(save_label(2))

    _one(user, _find(user, "new-version")[0]).click()
    await _until(lambda: bool(_find(user, "source-editor")))

    (editor,) = _find(user, "source-editor")
    assert editor._props["value"] == single.version(1).source
    assert [v.version for v in await single.services.prompt.list_versions()] == [1]


# --- a refused save (the exit criterion) --------------------------------------


@pytest.mark.parametrize(
    ("fixture", "code", "slot"),
    [
        ("p02_missing_narrative", PromptValidationCode.MISSING_REQUIRED_SLOT, "narrative"),
        ("p03_unknown_slot", PromptValidationCode.UNKNOWN_SLOT, "corpus"),
    ],
)
async def test_a_refused_save_renders_its_validation_codes(
    single: Seeded, fixture: str, code: PromptValidationCode, slot: str
) -> None:
    """README, Interactions: "an unknown slot, or a template missing
    `{{feature_block}}`/`{{narrative}}`, is an error".

    Asserted on `PromptValidationCode`, never on message text (CLAUDE.md,
    "Findings, not prose") — and **nothing is written**.
    """
    user = single.user
    await user.open("/prompts")
    await user.should_see(save_label(2))

    await _edit_source(user, hazard(fixture))
    _one(user, _find(user, "save-template")[0]).click()
    await _until(lambda: bool(_find(user, "validation-errors")))

    codes = [str(e._props["data-code"]) for e in _find(user, "validation-error")]
    assert code.value in codes
    assert slot in " ".join(_texts(user, "validation-error"))
    # Nothing was written, and the draft is still in the editor to be fixed.
    assert [v.version for v in await single.services.prompt.list_versions()] == [1]
    assert len(_rows(user)) == 1
    (editor,) = _find(user, "source-editor")
    assert editor._props["value"] == hazard(fixture)


async def test_an_empty_template_is_refused_with_its_own_code(single: Seeded) -> None:
    """A blank source never reaches the store."""
    user = single.user
    await user.open("/prompts")
    await user.should_see(save_label(2))

    await _edit_source(user, "   ")
    _one(user, _find(user, "save-template")[0]).click()
    await _until(lambda: bool(_find(user, "validation-errors")))

    assert [str(e._props["data-code"]) for e in _find(user, "validation-error")] == [
        PromptValidationCode.EMPTY_SOURCE.value
    ]


# --- delete ------------------------------------------------------------------


async def test_deleting_an_uncited_version_removes_its_row(seeded: Seeded) -> None:
    """ "Only a version with zero runs can be deleted; all others show
    `locked`" — and the cited one offers no button at all."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SLOTS_AVAILABLE)

    assert len(_find(user, "delete-version")) == 1
    _one(user, _find(user, "delete-version")[0]).click()
    await _until(lambda: len(_rows(user)) == 2)

    assert [v.version for v in await seeded.services.prompt.list_versions()] == [3, 2]
    assert _markers(user) == {3: "active", 2: "locked"}


# --- the well, the pagination row and the two reference strips ---------------


async def test_the_well_is_capped_at_ten_rows_and_530px(seeded: Seeded) -> None:
    """README §1: "The well is capped at **10 rows (530px)** and scrolls
    beyond; below it the standard pagination row"."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SLOTS_AVAILABLE)

    (well,) = _find(user, "scroll-well")
    assert well._props["data-max-height-px"] == str(WELL_HEIGHT_PX)
    assert well._style.get("max-height") == f"{WELL_HEIGHT_PX}px"
    assert well._style.get("overflow-y") == "auto"
    assert _texts(user, "pagination-range") == ["1–3 of 3"]
    assert prompts_view.PAGE_SIZE == 10


async def test_the_well_pages_at_ten_rows(paged: Seeded) -> None:
    """Eleven versions fill the well and spill onto a second page; the range
    label and the arrows are `pagination_row`'s, over the totals."""
    user = paged.user
    await user.open("/prompts")
    await user.should_see(SLOTS_AVAILABLE)

    assert len(_rows(user)) == 10
    assert _texts(user, "pagination-range") == ["1–10 of 11"]

    _one(user, _find(user, "page-next")[0]).click()
    await _until(lambda: len(_rows(user)) == 1)

    assert _texts(user, "pagination-range") == ["11–11 of 11"]
    assert [str(e._props["data-version"]) for e in _rows(user)] == ["1"]
    # …and the editor still holds the selected (active) version, off-page.
    assert _deep_texts(user, "editing-title") == ["Template v11"]


async def test_the_slot_strips_come_from_the_service(seeded: Seeded) -> None:
    """README §1: "Slots available" + a mono count, then the slot table — one
    row per slot of `domain.prompt.SLOTS`, never assembled here."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SLOTS_AVAILABLE)

    slots = await seeded.services.prompt.slots()
    assert _texts(user, "slot-count") == [str(len(slots))]
    assert [str(e._props["data-slot"]) for e in _find(user, "slot-row")] == [
        s.name.value for s in slots
    ]
    rendered = " ".join(_own_text(e) for e in _find(user, "slot-row")[0].descendants())
    assert slots[0].token in rendered
    assert slots[0].resolves_to in rendered


async def test_the_toolbar_has_no_left_chip_group(seeded: Seeded) -> None:
    """README §1, Toolbar: "There is deliberately **no left chip group** here"
    — two buttons, both right-aligned."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SLOTS_AVAILABLE)

    (toolbar,) = _find(user, "prompts-toolbar")
    assert not _within(toolbar, "chip")
    (group,) = [e for e in _ordered(toolbar.descendants()) if e._style.get("margin-left") == "auto"]
    assert [str(e._props["data-testid"]) for e in _within(group, "preview-template")] == [
        "preview-template"
    ]
    assert _deep_texts(user, "save-template") == [save_label(4)]


# --- the copy-on-write footer -------------------------------------------------


async def test_the_copy_on_write_footer_names_the_runs_that_cite_the_version(
    seeded: Seeded,
) -> None:
    """README §1: "Saving creates v5. v4 stays as it is — the 3 runs citing it
    must keep resolving to the exact text they used"."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SOURCE_TITLE)

    _one(user, _row(user, 2)).click()
    await _until(lambda: _deep_texts(user, "editing-title") == ["Template v2"])

    (footer,) = _find(user, "cow-footer")
    text = " ".join(_own_text(e) for e in footer.descendants())
    assert "Saving creates v4. v2 stays as it is" in text
    assert "the 1 run citing it must keep resolving to the exact text they used" in text


# --- the Resolved card --------------------------------------------------------


async def test_the_resolved_card_renders_its_empty_state_without_a_preview(
    seeded: Seeded,
) -> None:
    """Undesigned state (README, "Loading / empty / error"), capped at the
    design's own 210px so the column does not jump when a preview arrives."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SOURCE_TITLE)

    (empty,) = _find(user, "resolved-empty")
    assert empty._style.get("max-height") == "210px"
    assert not _find(user, "resolved-panel")


async def test_preview_with_record_1_hands_the_panel_a_resolved_prompt(
    previewable: Seeded, stub_preview_panel: list[ResolvedPromptView]
) -> None:
    """C4: one component, two entry points. This view **places** the panel and
    is responsible only for what it hands it — a `ResolvedPromptView` the
    service produced with **no model call**."""
    user = previewable.user
    await user.open("/prompts")
    await user.should_see(SOURCE_TITLE)

    _one(user, _find(user, "preview-template")[0]).click()
    await _until(lambda: bool(_find(user, "resolved-panel")))

    (resolved,) = stub_preview_panel
    assert resolved.record_key == "prompts-u1"
    assert "Am 14.03.2026" in resolved.text
    assert "{{narrative}}" not in resolved.text
    assert resolved.token_estimate > 0
    assert not _find(user, "resolved-empty")


async def test_preview_with_record_1_works_before_any_evaluation_exists(
    previewable_without_an_evaluation: Seeded, stub_preview_panel: list[ResolvedPromptView]
) -> None:
    """The design's "Preview with record 1" means the corpus's first record —
    not "the first record of some evaluation you happen to have created".

    This is what L1's accepted amendment bought (`CorpusService.first_record`,
    contracts/amendments/feat-p3-prompts-view.md): before it, authoring a
    template on a fresh install and pressing Preview showed an empty state,
    for a reason the analyst could not see.
    """
    user = previewable_without_an_evaluation.user
    await user.open("/prompts")
    await user.should_see(SOURCE_TITLE)

    _one(user, _find(user, "preview-template")[0]).click()
    await _until(lambda: bool(_find(user, "resolved-panel")))

    (resolved,) = stub_preview_panel
    assert resolved.record_key == "prompts-u1"
    assert "Am 14.03.2026" in resolved.text
    assert "{{narrative}}" not in resolved.text
    assert not _find(user, "resolved-empty")


async def test_preview_says_so_when_there_is_nothing_to_resolve_against(single: Seeded) -> None:
    """No evaluation yet means no feature set, no prompt language and no
    record — the card says that rather than guessing."""
    user = single.user
    await user.open("/prompts")
    await user.should_see(SOURCE_TITLE)

    _one(user, _find(user, "preview-template")[0]).click()
    await _until(lambda: _texts(user, "resolved-empty") == [NO_PREVIEW_INPUTS_MESSAGE])


# --- the undesigned empty state ----------------------------------------------


async def test_the_empty_state_is_one_line(empty: Seeded) -> None:
    """No template at all (README, "Loading / empty / error" — not designed)."""
    user = empty.user
    await user.open("/prompts")
    await user.should_see(SLOTS_AVAILABLE)

    assert _texts(user, "list-empty") == [NO_VERSIONS_MESSAGE]
    assert _texts(user, "versions-count") == [versions_label(0)]
    assert not _rows(user)
    # …and the editor offers the first version rather than a dead pane.
    assert _texts(user, "detail-empty")


# --- the page is reachable from the nav --------------------------------------


async def test_the_nav_entry_is_built_and_active(seeded: Seeded) -> None:
    """plan-phase-3.md §6.1 — this branch flips its own `built` flag, so
    `/prompts` is the real view and the nav marks it active."""
    user = seeded.user
    await user.open("/prompts")
    await user.should_see(SOURCE_TITLE)
    await user.should_see("Prompt templates")
    assert prompts_view._ITEM.built

"""Layer 3 — the Evaluation view (sw-design.md §11.3, "evaluation").

`/evaluation` is live: this branch flips its own `NavItem.built` and adds its
own line to `views.register_all()` (plan-phase-3.md §6.1's two-line nav
exception), so the fixtures below build the app the ordinary way and the real
page is what answers.

**Three of this view's components are L3's** — `progress_card`,
`ollama_settings_dialog` and `prompt_preview_panel`, built in parallel this
same wave against the signatures frozen at M17 (plan-phase-3.md §3.1). They
have landed, so this suite runs against the real ones and asserts only that
they are **placed and handed the right read model** — their own contracts
(every status variant, the golden resolved string, the three settings
controls) are `tests/ui/test_components.py`'s, not this file's.

`run` rows are seeded straight through `app.state.session_factory` where no
service can be asked to produce the state under test: a `failed` run needs a
worker that failed, and an `interrupted` one needs a process that died. The
mirror image of `test_features_view.py`'s `frozen` fixture, and for the same
reason — the row is the precondition, not the thing being asserted.

`launched_at` is seeded the same way, for the same reason (`_seed_launch`).
The launch *transaction* (sw-design.md §15.2) snapshots `evaluation_feature`,
resolves every fingerprint **and submits one worker per selected model**; none
of that is what the setup column reads, and a background worker writing rows
under the assertions below is exactly the flakiness
`test_an_interrupted_run_offers_resume` already documents paying for. What
locks the column is one timestamp, so one timestamp is what these cases seed.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

import httpx
import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.element import Element
from nicegui.testing.general import nicegui_reset_globals
from nicegui.testing.user import User
from nicegui.testing.user_interaction import UserInteraction
from sqlalchemy import delete, update
from tests.fixtures.fake_llm import DEFAULT_MODELS, StaticModelCatalog

import ra2.ui.views.evaluation_view as evaluation_view
from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.ids import CorpusId, EvaluationId, PromptTemplateId, RunId, TaskId
from ra2.domain.llm import EndpointStatus
from ra2.infra.config import Settings
from ra2.persistence.models import Corpus, Evaluation, Run
from ra2.services.container import Services
from ra2.services.readmodels import EvaluationDraftView, FeatureSetSummary, PromptTemplateView
from ra2.ui import theme

pytestmark = pytest.mark.ui

#: A valid template: both required slots present, no unknown one
#: (`domain.prompt.validate_template`).
TEMPLATE_SOURCE = (
    "You extract structured facts from Swiss accident reports.\n\n"
    "{{feature_block}}\n\n"
    "--- narrative ---\n"
    "{{narrative}}\n"
)

#: The three models `StaticModelCatalog` offers, by the role each plays here.
FITS_A = DEFAULT_MODELS[0].tag
FITS_B = DEFAULT_MODELS[1].tag
#: 42.5 GB against the root fixture's RTX 4090 / 24 GB — the design's disabled
#: row, and the only one whose `fits_vram` is `False`.
OVER_VRAM = DEFAULT_MODELS[2].tag

FROZEN_NOW = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)
RECORD_COUNT = 4978


@dataclass(frozen=True)
class Seeded:
    user: User
    services: Services
    app: FastAPI
    corpus_id: CorpusId
    config: FeatureSetSummary
    template: PromptTemplateView
    draft: EvaluationDraftView


# --- seeding ------------------------------------------------------------------


async def _seed(app: FastAPI, services: Services, user: User, *, name: str) -> Seeded:
    """One corpus row, one **frozen** feature set, one active template and one
    saved draft.

    Every piece is built through the service the view itself calls, except the
    bare `Corpus` row: the view only ever reads its name, version and record
    count, and a real delivery-and-freeze would add seconds per test for
    nothing this suite asserts (`test_features_view.py`'s `frozen` fixture
    makes the same trade in the other direction).
    """
    corpus_id = CorpusId(f"corpus-{name}")
    async with app.state.session_factory() as session:
        session.add(
            Corpus(
                id=corpus_id,
                name=name,
                imported_at=FROZEN_NOW,
                source_file_manifest_json="[]",
                import_report_json="[]",
                record_count=RECORD_COUNT,
            )
        )
        await session.commit()

    config = await services.feature.create_draft(name=f"Weather & conditions ({name})")
    config = await services.feature.add_feature(
        config.feature_config_id,
        key="weather",
        kind=Kind.LABELLED,
        description="The weather at the time of the accident.",
        grain=Grain.ACCIDENT,
        source_column="Witter0Ausw",
        derivation=None,
        value_type=ValueType.FREE_TEXT,
        matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
    )
    frozen = await services.feature.freeze(config.feature_config_id)
    assert frozen.is_frozen

    template = await services.prompt.save_as_next_version(TEMPLATE_SOURCE)
    template = await services.prompt.activate(template.prompt_template_id)

    draft = await services.evaluation.save_draft(
        name=f"eval-{name}",
        corpus_id=corpus_id,
        feature_config_id=frozen.feature_config_id,
    )
    summary = next(
        s
        for s in await services.feature.list_configs()
        if s.feature_config_id == frozen.feature_config_id
    )
    return Seeded(
        user=user,
        services=services,
        app=app,
        corpus_id=corpus_id,
        config=summary,
        template=template,
        draft=draft,
    )


async def _seed_run(
    app: FastAPI,
    *,
    run_id: str,
    evaluation_id: EvaluationId,
    template_id: PromptTemplateId,
    model_tag: str,
    status: RunStatus,
    started_at: datetime | None,
    error: str | None = None,
) -> None:
    """One `run` row in a state no service can be asked to produce here."""
    async with app.state.session_factory() as session:
        session.add(
            Run(
                id=RunId(run_id),
                evaluation_id=evaluation_id,
                model_name=model_tag,
                model_digest="8fa1c3d0",
                prompt_template_version=1,
                prompt_template_id=template_id,
                prompt_template_fingerprint="t4e1980cab7",
                temperature=0.0,
                seed=42,
                status=status,
                started_at=started_at,
                error=error,
                host_platform="win11-x64",
                gpu_name="RTX 4090",
                llm_endpoint="http://127.0.0.1:11434/v1",
            )
        )
        await session.commit()


async def _seed_launch(
    app: FastAPI, evaluation_id: EvaluationId, *, models: tuple[str, ...] = (FITS_A,)
) -> None:
    """Stamp `launched_at` — the whole of what makes the setup column
    read-only (`EvaluationDraftView.is_launched`, module docstring)."""
    async with app.state.session_factory() as session:
        await session.execute(
            update(Evaluation)
            .where(Evaluation.id == evaluation_id)
            .values(launched_at=FROZEN_NOW, selected_models_json=json.dumps(list(models)))
        )
        await session.commit()


async def _mounted_bare(
    app_factory: Callable[..., FastAPI], **overrides: object
) -> AsyncIterator[User]:
    """`_mounted` without the seeding — a migrated but otherwise empty
    database, which is what a fresh install actually looks like."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True, **overrides)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                yield User(client)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


async def _mounted(
    app_factory: Callable[..., FastAPI], *, name: str, **overrides: object
) -> AsyncIterator[Seeded]:
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app = app_factory(mount_ui=True, **overrides)
            services: Services = app.state.services
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                yield await _seed(app, services, User(client), name=name)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


@pytest.fixture
async def seeded(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[Seeded]:
    async for value in _mounted(app_factory, name="ui"):
        yield value


@pytest.fixture
async def unsaved(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[User]:
    """The view on a database with **no evaluation** — a fresh install, or any
    moment before the first "Save draft".

    Every other fixture here seeds a draft, which is why the Models card could
    be dead in exactly this state without a single test noticing: the
    catalogue was reached through `EvaluationView`, so no evaluation meant no
    models, however reachable the endpoint was.
    """
    async for value in _mounted_bare(app_factory):
        yield value


@pytest.fixture
async def unsaved_and_unreachable(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[User]:
    """No evaluation **and** no endpoint — the two empty causes at once, which
    must not produce the same sentence."""
    async for value in _mounted_bare(
        app_factory, model_catalog=StaticModelCatalog(status=EndpointStatus.UNREACHABLE)
    ):
        yield value


@pytest.fixture
async def launched(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[Seeded]:
    """The state the view had no way out of: an evaluation with `launched_at`
    set, so every setup control is read-only."""
    async for value in _mounted(app_factory, name="launched"):
        await _seed_launch(value.app, value.draft.evaluation_id)
        yield value


@pytest.fixture
async def unreachable(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> AsyncIterator[Seeded]:
    """The same screen against an endpoint that is not there — an empty model
    catalogue and a reason (plan-phase-3.md C3)."""
    async for value in _mounted(
        app_factory,
        name="down",
        model_catalog=StaticModelCatalog(status=EndpointStatus.UNREACHABLE),
    ):
        yield value


def _restore_nicegui_functions() -> None:
    from nicegui.functions.download import download
    from nicegui.functions.navigate import Navigate
    from nicegui.functions.notify import notify

    ui.navigate = Navigate()
    ui.notify = notify
    ui.download = download


# --- helpers -----------------------------------------------------------------


def _ordered(elements: Iterable[Element]) -> list[Element]:
    return sorted(elements, key=lambda e: e.id)


def _find(user: User, testid: str) -> list[Element]:
    return _ordered(
        e for e in user.find(kind=ui.element).elements if e._props.get("data-testid") == testid
    )


def _own_text(element: Element) -> str:
    return str(getattr(element, "text", ""))


def _element_text(element: Element) -> str:
    own = _own_text(element)
    if own:
        return own
    return " ".join(t for t in (_own_text(d) for d in element.descendants()) if t)


def _all_text(user: User, testid: str) -> str:
    return " ".join(_element_text(e) for e in _find(user, testid))


def _one(user: User, element: Element) -> UserInteraction[Element]:
    return UserInteraction(user, {element}, None)


def _is_disabled(element: Element) -> bool:
    return "disabled" in element._props


def _style(element: Element) -> str:
    """The element's inline style as one `key:value;` string, whitespace
    stripped — NiceGUI keeps it as a dict, and the design's numbers are
    written as declarations."""
    return "".join(f"{k}:{v};" for k, v in element._style.items()).replace(" ", "")


def _pick_select(user: User, testid: str, value: str) -> None:
    """Choose `value` on a native `<select>`, the way
    `test_features_view._pick_select` documents: the in-process simulation
    never runs the browser-side `js_handler`, so the Python listener is
    triggered directly with the raw value as `event.args`."""
    (element,) = _find(user, testid)
    _one(user, element).trigger("change", args=value)


def _model_row(user: User, tag: str) -> Element:
    return next(e for e in _find(user, "model-row") if e._props.get("data-model") == tag)


def _model_tick(user: User, tag: str) -> Element:
    return next(
        d for d in _model_row(user, tag).descendants() if d._props.get("data-testid") == "tick"
    )


def _statuses(user: User) -> set[str]:
    return {str(e._props["data-status"]) for e in _find(user, "run-status")}


def _has_model_rows(user: User) -> bool:
    return bool(_find(user, "model-row"))


async def _until(predicate: Callable[[], bool]) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


# --- the six numbered steps ---------------------------------------------------


async def test_the_setup_column_renders_all_six_numbered_steps(seeded: Seeded) -> None:
    """README §2, "Setup column — six numbered steps": each is `.lbl`
    "N · Title" plus its control and an optional explanatory line."""
    user = seeded.user
    await user.open("/evaluation")
    await user.should_see("Evaluation")

    labels = _all_text(user, "step-label")
    for number, title in enumerate(evaluation_view.STEP_TITLES, start=1):
        assert _find(user, f"step-{number}"), f"step {number} is missing"
        assert f"{number} · {title}" in labels

    # 1 · Corpus — the record count is the service's.
    assert "4 978 records" in _all_text(user, "corpus-select")
    # 2 · Feature set — the **corrected** note (plan-phase-3.md C5 / R6).
    assert _all_text(user, "feature-set-note") == evaluation_view.FEATURE_SET_NOTE
    assert "Freezes when the first run executes" not in _all_text(user, "feature-set-note")
    # 3 · Prompt — the active template, and the design's note verbatim.
    assert "template · v1" in _all_text(user, "prompt-select")
    assert "active" in _all_text(user, "pill")
    assert _all_text(user, "prompt-note") == evaluation_view.PROMPT_NOTE
    # 4 · Models — a 4-row (196px) well, a footer count and the endpoint line.
    (well,) = _find(user, "scroll-well")
    assert well._props["data-max-height-px"] == str(evaluation_view.MODELS_WELL_PX)
    assert len(_find(user, "model-row")) == len(DEFAULT_MODELS)
    assert _all_text(user, "models-count") == f"{len(DEFAULT_MODELS)} available · 0 selected"
    assert "reachable" in _all_text(user, "endpoint-line")
    assert not _find(user, "endpoint-reason")
    # 5 · Determinism — two `labeled_field`s, label above the control.
    assert len(_find(user, "labeled-field")) == 2
    assert "0.0" in _all_text(user, "temperature-select")
    (seed_input,) = _find(user, "seed-input")
    assert seed_input._props["value"] == "42"
    assert _all_text(user, "determinism-note") == evaluation_view.DETERMINISM_NOTE
    # 6 · Size — two `radio_option`s, both reading their numbers from a service.
    assert len(_find(user, "sel-radio")) == 2
    radios = _all_text(user, "sel-radio")
    assert "Evaluation · all 4 978" in radios
    assert "Dev · 50 records" in radios
    assert _all_text(user, "size-note") == evaluation_view.SIZE_NOTE


async def test_the_toolbar_pins_the_inputs_and_right_aligns_without_a_spacer(
    seeded: Seeded,
) -> None:
    """README §2, "Toolbar": the pinned-inputs line, and a right group on
    `margin-left:auto` — **not** a `flex:1` spacer, which breaks right
    alignment when the row wraps."""
    user = seeded.user
    await user.open("/evaluation")

    pinned = _all_text(user, "pinned-inputs")
    assert pinned.endswith(evaluation_view.PINNED_SUFFIX)
    assert seeded.config.name in pinned
    assert "margin-left:auto" in evaluation_view.RIGHT_GROUP_STYLE
    assert "flex:1" not in evaluation_view.RIGHT_GROUP_STYLE
    assert _all_text(user, "save-draft") == "Save draft"


async def test_the_split_never_wraps_and_the_setup_column_hugs_its_content(
    seeded: Seeded,
) -> None:
    """README §2, "Layout" — both constraints were regressions at some point.

    Without `align-self:flex-start` the setup column stretches and its
    `margin-top:auto` launch row is pushed to the bottom, leaving a ~530px gap;
    without `flex-wrap:nowrap` the split wraps instead of shrinking both
    columns to their 320px / 360px floors.
    """
    user = seeded.user
    await user.open("/evaluation")

    # The never-wrap rule lives in the one stylesheet, so it is asserted there.
    assert ".split{flex:1;min-height:0;display:flex;flex-wrap:nowrap;}" in theme.STYLESHEET

    (setup,) = _find(user, "split-list")
    assert "align-self:flex-start" in _style(setup)
    assert "min-width:320px" in _style(setup)
    assert "flex:01430px" in _style(setup)

    (progress,) = _find(user, "split-detail")
    assert "min-width:360px" in _style(progress)
    assert "flex:11520px" in _style(progress)

    (launch_row,) = _find(user, "launch-row")
    assert "margin-top:auto" in _style(launch_row)


# --- step 4: the VRAM-disabled row --------------------------------------------


async def test_a_model_that_exceeds_vram_is_disabled_and_says_why(seeded: Seeded) -> None:
    """README §2 step 4: `opacity:.55` with the size line in `--warn`
    ("42.5 GB — exceeds 24 GB VRAM"), and the tick inert."""
    user = seeded.user
    await user.open("/evaluation")

    row = _model_row(user, OVER_VRAM)
    assert row._props["data-disabled"] == "true"
    assert "opacity:.55" in _style(row)
    size = next(d for d in row.descendants() if d._props.get("data-testid") == "model-size")
    assert "warn" in size._classes
    assert _own_text(size) == "42.5 GB — exceeds 24.0 GB VRAM"

    for tag in (FITS_A, FITS_B):
        fitting = _model_row(user, tag)
        assert fitting._props["data-disabled"] == "false"
        assert "digest" in _element_text(fitting)

    # The disabled row's tick is inert: clicking it selects nothing.
    _one(user, _model_tick(user, OVER_VRAM)).click()
    await asyncio.sleep(0.05)
    assert _all_text(user, "models-count").endswith("0 selected")


# --- the launch label follows the selection -----------------------------------


async def test_the_launch_label_counts_the_selected_models(seeded: Seeded) -> None:
    """README §2: "Launch 3 runs" — "the count follows the model selection"."""
    user = seeded.user
    await user.open("/evaluation")
    assert _all_text(user, "launch") == "Launch 0 runs"
    (launch,) = _find(user, "launch")
    assert _is_disabled(launch), "nothing selected — `can_launch` is False"

    _one(user, _model_tick(user, FITS_A)).click()
    await _until(lambda: _all_text(user, "launch") == "Launch 1 run")

    _one(user, _model_tick(user, FITS_B)).click()
    await _until(lambda: _all_text(user, "launch") == "Launch 2 runs")
    assert _all_text(user, "models-count").endswith("2 selected")
    (launch,) = _find(user, "launch")
    assert not _is_disabled(launch)

    # And back down again — the label is the selection's, not a high-water mark.
    _one(user, _model_tick(user, FITS_A)).click()
    await _until(lambda: _all_text(user, "launch") == "Launch 1 run")


# --- C3: an unreachable endpoint disables Launch ------------------------------


async def test_an_unreachable_endpoint_disables_launch_and_says_why_beside_the_line(
    unreachable: Seeded,
) -> None:
    """plan-phase-3.md C3: an unreachable endpoint **disables Launch**, with
    the reason rendered beside the endpoint line — **never as a toast**."""
    user = unreachable.user
    notifications: list[str] = []
    ui.notify = lambda message, *_args, **_kwargs: notifications.append(str(message))

    await user.open("/evaluation")

    assert "unreachable" in _all_text(user, "endpoint-line")
    reason = _all_text(user, "endpoint-reason")
    assert reason, "the reason must be rendered beside the endpoint line"
    assert not notifications, "the reason is not a toast (C3)"

    (launch,) = _find(user, "launch")
    assert _is_disabled(launch)

    # The view reads the service's own judgement rather than re-deriving it.
    view = await unreachable.services.evaluation.get(unreachable.draft.evaluation_id)
    assert view.can_launch is False
    assert view.connection.reason == reason


# --- the runs table: the five columns and the three row states ----------------


async def test_the_runs_table_renders_its_five_columns_and_three_row_states(
    seeded: Seeded,
) -> None:
    """README §2, "Runs table": the five columns at their exact widths,
    `dd.mm.yy - hh:mm:ss` timestamps, `—` for a queued run's records, the
    `failed` row state with its muted "log" action, and 10-row pagination."""
    user = seeded.user
    evaluation_id = seeded.draft.evaluation_id
    template_id = seeded.template.prompt_template_id
    await _seed_run(
        seeded.app,
        run_id="r-0412",
        evaluation_id=evaluation_id,
        template_id=template_id,
        model_tag=FITS_A,
        status=RunStatus.DONE,
        started_at=datetime(2026, 9, 4, 8, 12, 4, tzinfo=UTC),
    )
    await _seed_run(
        seeded.app,
        run_id="r-0413",
        evaluation_id=evaluation_id,
        template_id=template_id,
        model_tag=FITS_B,
        status=RunStatus.FAILED,
        started_at=datetime(2026, 9, 4, 9, 31, 17, tzinfo=UTC),
        error="the endpoint stopped answering",
    )
    await _seed_run(
        seeded.app,
        run_id="r-0414",
        evaluation_id=evaluation_id,
        template_id=template_id,
        model_tag=FITS_A,
        status=RunStatus.QUEUED,
        started_at=None,
    )

    await user.open("/evaluation")
    await user.should_see("Runs in this evaluation")

    widths = {
        str(column._props["data-column"]): _style(column)
        for column in user.find(kind=ui.element).elements
        if column.tag == "th" and "data-column" in column._props
    }
    assert "width:74px" in widths["run_id"]
    assert "width:132px" in widths["model_tag"]
    assert "width:66px" in widths["records_done"]
    assert "width:152px" in widths["started_at"]
    assert "width:84px" in widths["status"]

    assert _statuses(user) == {"done", "failed", "queued"}
    assert "04.09.26 - 08:12:04" in _all_text(user, "run-started")
    # A queued run has neither a record count nor a start time yet.
    assert _all_text(user, "run-records").split().count("—") == 1
    assert _all_text(user, "run-started").count("—") == 1
    # The failed row: `--danger-soft`, and a muted "log" action, not "results".
    failed_rows = [
        e
        for e in user.find(kind=ui.element).elements
        if e.tag == "tr" and "danger-soft" in str(e._style)
    ]
    assert len(failed_rows) == 1
    assert len(_find(user, "run-log")) == 1
    assert "3 · 0 dev · 1 failed" in _all_text(user, "card-header")
    # A run id is a real link to Results — a placeholder route this phase.
    hrefs = {str(e._props.get("href", "")) for e in _find(user, "run-link")}
    assert "/results?run=r-0412" in hrefs
    # Paginated at 10 (README §2), not at the component kit's default ladder.
    (pagination,) = _find(user, "pagination")
    assert "1–3 of 3" in _element_text(pagination)
    assert _all_text(user, "page-size") == "10"


async def test_a_dev_sized_run_paints_the_row_and_carries_the_dev_marker(
    seeded: Seeded,
) -> None:
    """README §2: "dev-sized runs get `background:--warn-soft`", with `DEV` in
    `--warn` — the third row state."""
    user = seeded.user
    evaluation_id = seeded.draft.evaluation_id
    await seeded.services.evaluation.update_draft(evaluation_id, size=EvaluationSize.DEV)
    await _seed_run(
        seeded.app,
        run_id="r-0409",
        evaluation_id=evaluation_id,
        template_id=seeded.template.prompt_template_id,
        model_tag=FITS_A,
        status=RunStatus.DONE,
        started_at=datetime(2026, 9, 3, 16, 40, 52, tzinfo=UTC),
    )

    await user.open("/evaluation")
    await user.should_see("Runs in this evaluation")

    (status,) = _find(user, "run-status")
    # The drawn marker replaces the word; the run's real state stays readable.
    assert status._props["data-status"] == "done"
    assert status._props["data-dev"] == "true"
    assert _own_text(status) == "DEV"
    assert "warn" in status._classes
    dev_rows = [
        e
        for e in user.find(kind=ui.element).elements
        if e.tag == "tr" and "warn-soft" in str(e._style)
    ]
    assert len(dev_rows) == 1
    assert "1 · 1 dev · 0 failed" in _all_text(user, "card-header")


async def test_an_interrupted_run_offers_resume(
    seeded: Seeded, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sw-design.md §15.4 / §15 F8: a process death leaves the run
    `interrupted` and the view offers **Resume** — explicitly, because nothing
    auto-restarts at app start.

    The row is seeded `running`: `RunService`'s read paths relabel a `running`
    run this process is not executing, which is precisely what "the process
    died under it" looks like from here.

    The assertion is that the click **reaches `RunService.resume`** with this
    run's id, not that the resumed run reaches some later status: what happens
    after the submit is the worker's, it runs on a background task, and timing
    it out of a UI test made this assertion flaky under a full-suite load. The
    recorder below delegates to the real service, so the real path still runs.
    """
    user = seeded.user
    await _seed_run(
        seeded.app,
        run_id="r-0410",
        evaluation_id=seeded.draft.evaluation_id,
        template_id=seeded.template.prompt_template_id,
        model_tag=FITS_A,
        status=RunStatus.RUNNING,
        started_at=datetime(2026, 9, 3, 11, 5, 33, tzinfo=UTC),
    )

    await user.open("/evaluation")
    await user.should_see("Runs in this evaluation")

    assert _statuses(user) == {RunStatus.INTERRUPTED.value}
    assert _all_text(user, "run-status").startswith(RunStatus.INTERRUPTED.value)
    (resume,) = _find(user, "run-resume")
    assert _element_text(resume) == "Resume"

    resumed: list[str] = []
    real_resume = seeded.services.run.resume

    async def _recording_resume(run_id: RunId) -> TaskId:
        resumed.append(str(run_id))
        return await real_resume(run_id)

    monkeypatch.setattr(seeded.services.run, "resume", _recording_resume)

    _one(user, resume).click()
    await _until(lambda: resumed == ["r-0410"])


# --- the progress column ------------------------------------------------------


async def test_the_progress_column_places_a_card_per_run_and_the_reproducibility_card(
    seeded: Seeded,
) -> None:
    """README §2, "Progress column": the header line, one per-model card, and
    the reproducibility card naming every field mvp-spec.md §19.8 requires."""
    user = seeded.user
    await user.open("/evaluation")

    assert _all_text(user, "progress-caption") == evaluation_view.PROGRESS_CAPTION
    # No runs yet: the standard empty note, and no provenance to claim.
    assert evaluation_view.NO_RUNS_MESSAGE in _all_text(user, "empty-note")
    assert _all_text(user, "provenance-title") == evaluation_view.PROVENANCE_TITLE
    assert not _find(user, "provenance-line")

    await _seed_run(
        seeded.app,
        run_id="r-0411",
        evaluation_id=seeded.draft.evaluation_id,
        template_id=seeded.template.prompt_template_id,
        model_tag=FITS_A,
        status=RunStatus.DONE,
        started_at=FROZEN_NOW,
    )
    await user.open("/evaluation")
    await user.should_see("Runs in this evaluation")

    cards = _find(user, "progress-card")
    assert len(cards) == 1
    # Placed and handed this run's read model — the card's own rendering is
    # `tests/ui/test_components.py`'s to assert, not this suite's.
    assert _all_text(user, "progress-card-model") == FITS_A
    assert "done" in _all_text(user, "progress-card-status")

    line = _all_text(user, "provenance-line")
    for expected in (
        FITS_A,
        "8fa1c3d0",
        "prompt template v1",
        "temperature 0.0",
        "seed 42",
        f"cfg {seeded.config.feature_config_id}",
        f"corpus {seeded.corpus_id} v1",
        "host win11-x64",
        "gpu RTX 4090",
        "endpoint 127.0.0.1:11434/v1",
    ):
        assert expected in line, expected
    assert _all_text(user, "provenance-explainer") == evaluation_view.PROVENANCE_EXPLAINER


# --- the gear button ----------------------------------------------------------


async def test_the_models_footer_gear_opens_the_connection_settings(seeded: Seeded) -> None:
    """README §2 step 4: "a 24×24 gear icon button on the right opening
    **Ollama connection settings**". The dialog itself is L3's."""
    user = seeded.user
    await user.open("/evaluation")

    gear = next(
        e
        for e in user.find(kind=ui.element).elements
        if e._props.get("aria-label") == "Ollama connection settings"
    )
    _one(user, gear).click()
    await _until(lambda: bool(_find(user, "ollama-endpoint")))
    # L3's three controls, and only three (sw-design.md §15.8).
    assert _find(user, "ollama-timeout")
    assert _find(user, "ollama-refresh")
    assert _find(user, "ollama-save")


# --- the empty state ----------------------------------------------------------


async def test_with_no_evaluation_the_view_offers_new_evaluation_rather_than_crashing(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> None:
    """plan-phase-3.md C3: the standard empty card, no new pattern. Steps 1
    and 2 are the two picks the creation affordance needs; the rest wait for
    the row, because their defaults are `EvaluationService.save_draft`'s to
    supply.

    **This case used to assert "Save draft" here** — a label describing an
    update to a row that does not exist, sitting in the toolbar while four of
    the six steps named it as the thing that would wake them up. The gate it
    tested is unchanged (P3-D21: nothing is selectable before the row exists);
    the affordance that opens the gate is what it asserts now (SD32).
    """
    async for seeded in _mounted(app_factory, name="empty"):
        await _assert_empty_state(seeded)


async def _assert_empty_state(seeded: Seeded) -> None:
    user = seeded.user
    # Drop the draft the seed made, so the page meets a database with a corpus
    # and a frozen set but no evaluation.
    async with seeded.app.state.session_factory() as session:
        await session.execute(delete(Evaluation))
        await session.commit()

    await user.open("/evaluation")
    await user.should_see("Evaluation")

    assert _all_text(user, "pinned-inputs") == evaluation_view.NO_SETUP_MESSAGE
    assert _find(user, "corpus-select")
    assert _find(user, "feature-set-select")
    assert not _find(user, "prompt-select")
    (launch,) = _find(user, "launch")
    assert _is_disabled(launch)

    # The one toolbar button reads as creation, and the four inert steps name
    # it by that label rather than pointing at a save.
    assert not _find(user, "save-draft")
    (create,) = _find(user, "new-evaluation")
    assert _element_text(create) == evaluation_view.NEW_EVALUATION_LABEL
    assert not _is_disabled(create)
    notes = _all_text(user, "empty-note")
    assert evaluation_view.UNSAVED_MESSAGE in notes
    assert evaluation_view.MODELS_UNSAVED_MESSAGE in notes
    for message in (
        evaluation_view.NO_SETUP_MESSAGE,
        evaluation_view.UNSAVED_MESSAGE,
        evaluation_view.MODELS_UNSAVED_MESSAGE,
    ):
        assert evaluation_view.NEW_EVALUATION_LABEL in message, message

    _pick_select(user, "corpus-select", str(seeded.corpus_id))
    await _until(lambda: bool(_find(user, "new-evaluation")))
    (create,) = _find(user, "new-evaluation")
    _one(user, create).click()
    await _until(lambda: bool(_find(user, "prompt-select")))
    evaluations = await seeded.services.evaluation.list_evaluations()
    assert len(evaluations) == 1
    assert evaluations[0].corpus_id == seeded.corpus_id
    # And the toolbar swaps: an editable draft is a thing "Save draft" can act
    # on, and a second draft beside it would be debris (SD32).
    assert _find(user, "save-draft")
    assert not _find(user, "new-evaluation")


async def test_an_unlaunched_draft_offers_save_draft_and_no_second_create(
    seeded: Seeded,
) -> None:
    """The two toolbar buttons are **mutually exclusive**, and this is the
    state that decides it (SD32).

    A repeated press cannot pile up rows, because after the first one the view
    is on an editable draft and the creation affordance is gone. That is the
    deliberate answer to `evaluation.name` having no unique constraint and
    `save_draft` not deduping: nothing here needs to dedupe, because nothing
    offers the second press.
    """
    user = seeded.user
    await user.open("/evaluation")
    await user.should_see("Evaluation")

    (save,) = _find(user, "save-draft")
    assert _element_text(save) == evaluation_view.SAVE_DRAFT_LABEL
    assert not _is_disabled(save)
    assert not _find(user, "new-evaluation")
    assert not _find(user, "launched-note")

    _one(user, save).click()
    await asyncio.sleep(0.05)
    assert len(await seeded.services.evaluation.list_evaluations()) == 1


# --- the launched state: locked, and no longer a dead end ---------------------
#
# Before this branch a launched evaluation froze the view permanently. Every
# setup control was read-only and nothing on screen said why; "Save draft" was
# disabled by `not view.draft.is_launched`; and `_current_evaluation` falls
# back to the newest evaluation, so there was no switcher and nothing to clone
# into — while both the design's step-2 copy and `FEATURE_SET_NOTE` instructed
# the analyst to "clone into a new evaluation".


async def test_a_launched_evaluation_says_why_the_setup_column_is_locked(
    launched: Seeded,
) -> None:
    """sw-design.md §15.2 locks the column; SD32 makes it say so.

    The sentence covers the **column**, not step 4: five other controls are
    locked by the same fact, and it is not step 4's fact to state.
    """
    user = launched.user
    await user.open("/evaluation")
    await user.should_see("Evaluation")

    (note,) = _find(user, "launched-note")
    assert _element_text(note) == evaluation_view.LAUNCHED_MESSAGE
    assert "warn" in note._classes
    # It precedes step 1 — the whole column is what it is about.
    (step_one,) = _find(user, "step-1")
    assert note.id < step_one.id

    # And it is telling the truth: every control in the column is read-only.
    for testid in ("corpus-select", "feature-set-select", "prompt-select", "temperature-select"):
        (element,) = _find(user, testid)
        assert _is_disabled(element), testid
    (seed_input,) = _find(user, "seed-input")
    assert _is_disabled(seed_input)
    assert all("disabled" in t._props for t in _find(user, "tick"))


async def test_new_evaluation_clones_a_launched_one_into_an_editable_draft(
    launched: Seeded,
) -> None:
    """Exit from the dead end: the same corpus and the same frozen feature
    set, in a row that can be edited again.

    "Save draft" is absent here on purpose — there is nothing on a launched
    evaluation left to save, and a button disabled without a word about why is
    what the old toolbar offered instead.
    """
    user = launched.user
    services = launched.services
    await user.open("/evaluation")
    await user.should_see("Evaluation")

    assert not _find(user, "save-draft")
    (create,) = _find(user, "new-evaluation")
    assert _element_text(create) == evaluation_view.NEW_EVALUATION_LABEL
    assert not _is_disabled(create)

    _one(user, create).click()
    await _until(lambda: bool(_find(user, "save-draft")))

    evaluations = await services.evaluation.list_evaluations()
    assert len(evaluations) == 2
    clone = next(e for e in evaluations if e.evaluation_id != launched.draft.evaluation_id)
    # Cites the same two things — the "clone into a new evaluation" the design
    # asks for, not a blank one.
    assert clone.corpus_id == launched.draft.corpus_id
    assert clone.feature_config_id == launched.draft.feature_config_id
    assert clone.launched_at is None

    # The view is on the clone, and the clone is editable.
    assert not _find(user, "launched-note")
    (corpus_select,) = _find(user, "corpus-select")
    assert not _is_disabled(corpus_select)
    assert _all_text(user, "launch") == "Launch 0 runs"

    # Step 4's ticks are live again — the point of the exit.
    _one(user, _model_tick(user, FITS_A)).click()
    await _until(lambda: _all_text(user, "launch") == "Launch 1 run")
    current = await services.evaluation.get(clone.evaluation_id)
    assert current.draft.selected_models == (FITS_A,)
    # The launched evaluation is untouched — a clone adds a row (Do-NOT #2).
    original = await services.evaluation.get(launched.draft.evaluation_id)
    assert original.draft.is_launched


# --- the Models card without an evaluation ------------------------------------
#
# The regression tests for "refresh model list does nothing". The card used to
# read `() if view is None else view.models`, so on any database with no
# evaluation row it said "0 available" and "the endpoint returned an empty
# catalogue" — while the endpoint was reachable and offering models, and while
# the settings dialog's Test button said so. Refresh could not help: it
# re-asked reachability and never asked for models at all.


async def test_the_models_card_lists_the_catalogue_with_no_evaluation(
    unsaved: User,
) -> None:
    """**The regression test.** Nothing saved, and the models are still there.

    Which models the endpoint offers is the *endpoint's* fact. Only the ticks
    belong to the evaluation.
    """
    await unsaved.open("/evaluation")
    await unsaved.should_see("Evaluation")

    assert len(_find(unsaved, "model-row")) == len(DEFAULT_MODELS)
    assert _all_text(unsaved, "models-count") == f"{len(DEFAULT_MODELS)} available · 0 selected"
    assert "reachable" in _all_text(unsaved, "endpoint-line")


async def test_the_models_are_not_selectable_before_a_draft_is_saved(
    unsaved: User,
) -> None:
    """A tick writes into the evaluation, so there has to be one to write into.

    Withheld *visibly*: `_toggle_model` has always returned early without an
    evaluation, which meant a live-looking tick that swallowed the click.
    """
    await unsaved.open("/evaluation")
    await unsaved.should_see("Evaluation")

    ticks = _find(unsaved, "tick")
    assert ticks, "the rows render, so their ticks exist"
    assert all("disabled" in t._props for t in ticks)
    assert evaluation_view.MODELS_UNSAVED_MESSAGE in _all_text(unsaved, "empty-note")


async def test_an_unreachable_endpoint_does_not_claim_an_empty_catalogue(
    unsaved_and_unreachable: User,
) -> None:
    """Two different emptinesses, two different sentences.

    "The endpoint returned an empty catalogue" was the single message for
    both, and it is a lie when nothing was returned at all — which is the
    wording that made this read as a broken refresh rather than a reachable
    endpoint with nothing asked of it.
    """
    user = unsaved_and_unreachable
    await user.open("/evaluation")
    await user.should_see("Evaluation")

    notes = _all_text(user, "empty-note")
    assert evaluation_view.NO_MODELS_UNREACHABLE_MESSAGE in notes
    assert evaluation_view.NO_MODELS_MESSAGE not in notes
    assert not _find(user, "model-row")
    # The reason line under the card is what names *which* refusal it was, so
    # the card body deliberately does not repeat it.
    assert _find(user, "endpoint-reason")


async def test_a_reachable_endpoint_with_nothing_pulled_says_how_to_fix_it(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> None:
    """Reachable and genuinely empty — an ordinary fresh install. The message
    names the fix rather than only the symptom."""
    async for user in _mounted_bare(app_factory, model_catalog=StaticModelCatalog(models=())):
        await user.open("/evaluation")
        await user.should_see("Evaluation")

        notes = _all_text(user, "empty-note")
        assert evaluation_view.NO_MODELS_MESSAGE in notes
        assert evaluation_view.NO_MODELS_UNREACHABLE_MESSAGE not in notes
        assert "reachable" in _all_text(user, "endpoint-line")


async def test_refresh_picks_up_a_model_that_appeared(
    app_factory: Callable[..., FastAPI], migrated_db: Settings
) -> None:
    """The journey the bug report describes: the endpoint was down, you start
    Ollama, you press "Refresh model list" — and the card fills in.

    Before the fix this could never pass with no evaluation saved, because
    refresh re-asked reachability and the model list came from somewhere that
    was empty by construction.
    """
    catalog = StaticModelCatalog(status=EndpointStatus.UNREACHABLE)
    async for user in _mounted_bare(app_factory, model_catalog=catalog):
        await user.open("/evaluation")
        await user.should_see("Evaluation")
        assert not _find(user, "model-row")

        catalog.set_status(EndpointStatus.REACHABLE)
        user.find(marker="ollama-connection-settings").click()
        await user.should_see(marker="ollama-refresh")
        user.find(marker="ollama-refresh").click()
        # `functools.partial`, not a closure: `user` is the `async for`
        # target, and a late-binding closure over a loop variable is what
        # B023 catches.
        await _until(partial(_has_model_rows, user))

        assert len(_find(user, "model-row")) == len(DEFAULT_MODELS)
        assert "reachable" in _all_text(user, "endpoint-line")

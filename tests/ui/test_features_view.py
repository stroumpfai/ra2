"""Layer 3 — the Features view (sw-design.md §11.3, "features").

`features_view.register()` is not yet wired into `views.register_all()` —
that lands centrally when the lead merges this branch alongside G1's
Codelists view (the Features view's own module docstring and this repo's
CLAUDE.md ownership rule both name `ra2/ui/shell.py` and
`ra2/ui/views/__init__.py` as files this branch must not touch). So every
fixture below builds the app the ordinary way (`app_factory(mount_ui=True)`,
same as `test_census_view.py`) and then calls `features_view.register(...)`
itself, directly, against the already-built `Services`. This is not a
work-around: `nicegui.page.page.__call__` explicitly removes any existing
route at the same path before adding its own ("make sure only the latest
route definition is used"), which is exactly what lets a still-a-placeholder
`/features` route be replaced by the real page here, in-process, without
touching `views/__init__.py`.

**Two of this view's placed components are still stubs.** `derivation_builder`
and `feature_sets_table` (`ra2/ui/components/derivation_builder.py`,
`feature_sets_table.py`) are G3's, built in parallel this same wave against a
frozen signature (plan-phase-2.md §3, M9); both bodies are
`raise NotImplementedError` as this suite is written. The feature-sets strip
is unconditionally on screen and the derivation builder renders for any
selected derived-aggregate feature, so **every** test below would otherwise
crash on render regardless of what it is testing. `_stub_wave4_components`
patches both to a two-line fake, in this test file only (never in production
code — Do-NOT #12) — this suite's job is G2's view, Case C included only as
far as it can be exercised without G3's body (selecting a derived-aggregate
feature is deliberately left out of the covered cases below, matching the
brief's own list: "all three built cases (A, B, D)").
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

import ra2.ui.views.features_view as features_view
from ra2.domain.delivery import DeliveryStatus, SourceKind
from ra2.domain.feature import (
    EXPLORATORY_FEATURE_CAP,
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    ValueType,
)
from ra2.domain.ids import CorpusId, EvaluationId
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.persistence.models import Corpus, Evaluation
from ra2.services.container import Services
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.ui

#: `tests/ui/` -> `tests/`.
_TESTS_ROOT = Path(__file__).resolve().parents[1]
_HAZARDS = _TESTS_ROOT / "fixtures" / "deliveries" / "hazards"

#: One complete cantonal set, the same fixture `test_census_view.py` uses for
#: the same reason: real `unfall`/`objekt`/`person` columns, including the
#: enum `Witter0Ausw` and the time `UnfZeitFeld` this suite's Case A/B
#: features are built on.
DELIVERY: dict[str, str] = {
    "one.txt": "h08_all_empty_column/unfall.txt",
    "two.txt": "h10_count_mismatch/objekt.txt",
    "three.txt": "h10_count_mismatch/person.txt",
}

WEATHER_COLUMN = "Witter0Ausw"
TIME_COLUMN = "UnfZeitFeld"

#: `{attribute_key: {name: {...}, codes: {code: {lang: label}}}}`
#: (`ra2.domain.codes.CodelistImportSchema`) — the corpus's one `Witter0Ausw`
#: value ("6") is labelled, so Case A's coverage reads "1 of 1".
CODELIST_JSON = b'{"weather_codes": {"name": {"de": "Witterung"}, "codes": {"6": {"de": "Klar"}}}}'


@dataclass(frozen=True)
class Seeded:
    user: User
    services: Services
    corpus_id: CorpusId
    config: FeatureConfigView


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def delivery_root(tmp_path: Path) -> Path:
    root = tmp_path / "features-delivery"
    root.mkdir(parents=True)
    for name, source in DELIVERY.items():
        (root / name).write_bytes((_HAZARDS / source).read_bytes())
    return root


@pytest.fixture(autouse=True)
def _stub_wave4_components(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch G3's two still-`NotImplementedError` components (module
    docstring). Neither fake computes or asserts anything about G3's own
    contract — that suite is G3's, not this one's."""

    def _fake_sets_table(**_kwargs: object) -> Element:
        return ui.element("div").props('data-testid="feature-sets-table-stub"')

    def _fake_derivation_builder(**_kwargs: object) -> Element:
        return ui.element("div").props('data-testid="derivation-builder-stub"')

    monkeypatch.setattr(features_view, "feature_sets_table", _fake_sets_table)
    monkeypatch.setattr(features_view, "derivation_builder", _fake_derivation_builder)


async def _build_app(app_factory: Callable[..., FastAPI]) -> tuple[FastAPI, Services]:
    app = app_factory(mount_ui=True)
    services: Services = app.state.services
    # Replaces the `built=False` placeholder NiceGUI/`register_all()` already
    # registered at "/features" — see the module docstring.
    features_view.register(services)
    return app, services


@pytest.fixture
async def seeded(
    app_factory: Callable[..., FastAPI],
    migrated_db: Settings,
    delivery_root: Path,
) -> AsyncIterator[Seeded]:
    """One real corpus (with census + a mapped codelist), and one draft
    feature set holding a Case A (enum), Case B (time) and Case D
    (exploratory) feature — everything built through the real services this
    view itself calls, never invented in the test."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app, services = await _build_app(app_factory)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                delivery_id = await services.delivery.register(
                    "features", source_kind=SourceKind.HOST_PATH, root_path=delivery_root
                )
                await services.delivery.analyse(delivery_id)
                await _until_analysed(services, delivery_id)
                corpus_id = await services.corpus.freeze(delivery_id, name="features")

                import_result = await services.codelist.import_file("codes.json", CODELIST_JSON)
                assert not import_result.no_change
                attributes = await services.codelist.list_attributes()
                (weather_attribute,) = [a for a in attributes if a.key == "weather_codes"]
                await services.codelist.map_column(
                    corpus_id, WEATHER_COLUMN, weather_attribute.code_attribute_id
                )

                config = await services.feature.create_draft(name="Weather & conditions")
                config = await services.feature.add_feature(
                    config.feature_config_id,
                    key="weather",
                    kind=Kind.LABELLED,
                    description="The weather at the time of the accident.",
                    grain=Grain.ACCIDENT,
                    source_column=WEATHER_COLUMN,
                    derivation=None,
                    value_type=ValueType.ENUM,
                    matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
                    validate_against=corpus_id,
                )
                config = await services.feature.add_feature(
                    config.feature_config_id,
                    key="accident_time",
                    kind=Kind.LABELLED,
                    description="The time the accident was recorded.",
                    grain=Grain.ACCIDENT,
                    source_column=TIME_COLUMN,
                    derivation=None,
                    value_type=ValueType.TIME,
                    matching_rule=MatchingRule(
                        kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=15
                    ),
                    validate_against=corpus_id,
                )
                config = await services.feature.add_feature(
                    config.feature_config_id,
                    key="phone_use_mentioned",
                    kind=Kind.EXPLORATORY,
                    description="The narrative mentions phone use.",
                    grain=Grain.ACCIDENT,
                    source_column=None,
                    derivation=None,
                    value_type=ValueType.BOOLEAN,
                    matching_rule=MatchingRule(kind=MatchingRuleKind.NONE),
                )

                yield Seeded(User(client), services, corpus_id, config)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


@pytest.fixture
async def frozen(
    app_factory: Callable[..., FastAPI], migrated_db: Settings, frozen_clock: Clock
) -> AsyncIterator[Seeded]:
    """A **real, frozen** feature config with real features, cited by a
    **trivial** seeded `Evaluation` row — the mirror image of
    `tests/backend/services/corpus/conftest.py`'s `seed_evaluation` (that
    fixture seeds a trivial `FeatureConfig` alongside a real corpus; this one
    needs the opposite emphasis, per the task brief, so it is built here
    rather than reused)."""
    with nicegui_reset_globals():
        os.environ["NICEGUI_USER_SIMULATION"] = "true"
        try:
            app, services = await _build_app(app_factory)
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app), base_url="http://test"
                ) as client,
            ):
                config = await services.feature.create_draft(name="Injury & persons")
                config = await services.feature.add_feature(
                    config.feature_config_id,
                    key="worst_injury",
                    kind=Kind.LABELLED,
                    description="The most severe injury reported.",
                    grain=Grain.ACCIDENT,
                    source_column="VerletzungsgradAusw",
                    derivation=None,
                    value_type=ValueType.ENUM,
                    matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
                )
                # No `validate_against`: mvp-spec.md §7's codelist tier is
                # simply not run (feature_service's own docstring) — the set
                # still freezes clean, which is the point of this fixture.
                config = await services.feature.freeze(config.feature_config_id)
                assert config.is_frozen

                corpus_id = CorpusId("corpus-frozen-features")
                evaluation_id = EvaluationId("eval-frozen-features")
                session_factory = app.state.session_factory
                async with session_factory() as session:
                    session.add(
                        Corpus(
                            id=corpus_id,
                            name="frozen-features",
                            imported_at=frozen_clock.now(),
                            source_file_manifest_json="[]",
                            import_report_json="[]",
                            record_count=0,
                        )
                    )
                    await session.flush()
                    session.add(
                        Evaluation(
                            id=evaluation_id,
                            name="a trivial evaluation",
                            corpus_id=corpus_id,
                            feature_config_id=config.feature_config_id,
                        )
                    )
                    await session.commit()

                yield Seeded(User(client), services, corpus_id, config)
        finally:
            os.environ.pop("NICEGUI_USER_SIMULATION", None)
            _restore_nicegui_functions()


def _restore_nicegui_functions() -> None:
    from nicegui.functions.download import download
    from nicegui.functions.navigate import Navigate
    from nicegui.functions.notify import notify

    ui.navigate = Navigate()
    ui.notify = notify
    ui.download = download


async def _until_analysed(services: Services, delivery_id: str) -> None:
    for _ in range(500):
        delivery = await services.delivery.get(delivery_id)  # type: ignore[arg-type]
        if delivery.status in (DeliveryStatus.ANALYSED, DeliveryStatus.FAILED):
            assert delivery.status is DeliveryStatus.ANALYSED, delivery.status
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the delivery never finished analysing")


async def _until(predicate: Callable[[], bool]) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition never became true")


# --- helpers -------------------------------------------------------------------


def _own_text(element: Element) -> str:
    return str(getattr(element, "text", ""))


def _ordered(elements: Iterable[Element]) -> list[Element]:
    return sorted(elements, key=lambda e: e.id)


def _one(user: User, element: Element) -> UserInteraction[Element]:
    return UserInteraction(user, {element}, None)


def _find(user: User, testid: str) -> list[Element]:
    return _ordered(
        e for e in user.find(kind=ui.element).elements if e._props.get("data-testid") == testid
    )


def _find_marker(user: User, marker: str) -> list[Element]:
    """Elements carrying `marker`, or `[]` — unlike `user.find(marker=...)`,
    which raises when nothing matches (built for `should_see`-style
    assertions, not for "assert this is absent")."""
    return _ordered(e for e in user.find(kind=ui.element).elements if marker in e._markers)


def _element_text(element: Element) -> str:
    """The element's own text if it is a label, else its descendants' —
    some testids mark a wrapping `<span>`/`<h2>` rather than the `ui.label`
    inside it (e.g. `danger-chip`, `frozen-feature-name`)."""
    own = _own_text(element)
    if own:
        return own
    return " ".join(t for t in (_own_text(d) for d in element.descendants()) if t)


def _all_text(user: User, testid: str) -> str:
    return " ".join(_element_text(e) for e in _find(user, testid))


def _pick_select(user: User, testid: str, value: str) -> None:
    """Simulate choosing `value` on a native `<select>` built by this view's
    own `_select()` helper.

    NiceGUI's in-process `User` simulation never runs the browser-side
    `js_handler` a real `<select>`'s "change" listener is wired with (that
    JS only exists to make a *live* browser emit the raw DOM value) — but
    `UserInteraction.trigger(event, args)` calls the registered Python
    listener directly with `args` as `event.args`, which is exactly the
    shape `_select()`'s handler expects (`str(event.args)`). This is the
    same trick a real `<select>` needs no JS simulation for once it is
    driven by Playwright (J8's `page.select_option`), just done at the
    Python layer instead.
    """
    (element,) = _find(user, testid)
    _one(user, element).trigger("change", args=value)


async def _select_feature_row(user: User, key: str) -> None:
    button = next(
        e for e in _find(user, "feature-row") if e._props.get("aria-label") == f"Edit {key}"
    )
    _one(user, button).click()
    await _until(
        lambda: (
            bool(_find(user, "editing-feature-name")) or bool(_find(user, "frozen-feature-name"))
        )
    )


# --- Case A · labelled enum on a native column --------------------------------


async def test_case_a_enum_feature_renders(seeded: Seeded) -> None:
    """README, Case A: native-column source, "N distinct in corpus", the
    codelist coverage line, exact/none-for-enum/scored-yes."""
    user = seeded.user
    await user.open("/features")
    await user.should_see("Weather")

    await _select_feature_row(user, "weather")
    await _until(lambda: bool(_find(user, "source-column-select")))

    _pick_select(user, "validate-corpus-select", str(seeded.corpus_id))
    await _until(lambda: bool(_find(user, "codelist-coverage")))
    await user.should_see("distinct in corpus")
    assert _all_text(user, "codelist-coverage") == "1 of 1 codes labelled"
    await user.should_see("open codelist ↗")
    await user.should_see("exact")
    await user.should_see("none for enum")
    await user.should_see("Yes — scalar")


# --- Case B · labelled time with a tolerance ----------------------------------


async def test_case_b_time_feature_renders_and_the_stepper_works(seeded: Seeded) -> None:
    """README, Case B: native column + HH:MM, "within tolerance", and the
    real ± stepper editing `MatchingRule.tolerance_minutes`."""
    user = seeded.user
    await user.open("/features")
    await _select_feature_row(user, "accident_time")
    await _until(lambda: bool(_find(user, "tolerance-value")))

    assert _all_text(user, "tolerance-value") == "± 15 min"
    await user.should_see("within tolerance")
    await user.should_see("HH:MM")

    (increase,) = [
        e
        for e in user.find(kind=ui.element).elements
        if e._props.get("aria-label") == "Increase tolerance"
    ]
    _one(user, increase).click()
    await _until(lambda: _all_text(user, "tolerance-value") == "± 20 min")


# --- Case D · exploratory ------------------------------------------------------


async def test_case_d_exploratory_feature_renders(seeded: Seeded) -> None:
    """README, Case D: the dashed "narrative only" source, disabled matching
    rule, "discovery rate" parameter, "No — reported, not scored", and the
    exploratory budget bar."""
    user = seeded.user
    await user.open("/features")
    await _select_feature_row(user, "phone_use_mentioned")
    await _until(lambda: bool(_find(user, "exploratory-budget")))

    await user.should_see("narrative only — no source column exists for this")
    await user.should_see("n/a — no ground truth")
    await user.should_see("discovery rate")
    await user.should_see("No — reported, not scored")
    assert (
        _all_text(user, "exploratory-budget")
        == f"1 / {EXPLORATORY_FEATURE_CAP} used in this config"
    )


# --- the exploratory cap blocks a 21st feature --------------------------------


async def test_a_21st_exploratory_feature_blocks_set_creation(seeded: Seeded) -> None:
    """mvp-spec.md §8.1: capped at 20. Seeded up to 19 more directly through
    the same `FeatureService` this view calls (20 total with the fixture's
    own `phone_use_mentioned`), then the 21st is opened **through the UI**'s
    own "Add feature" panel — already Kind-defaulted to exploratory-adjacent
    enough that a brand-new draft is the 21st the moment it exists, which is
    exactly what the design's budget bar and over-cap note are about. The
    server-side error only firms up once `key` is saved, so this asserts the
    render this brief actually names ("rendering an error") rather than a
    round trip through the text-entry mechanics `feature-key` would need."""
    user = seeded.user
    services = seeded.services
    config = seeded.config
    for i in range(EXPLORATORY_FEATURE_CAP - 1):
        config = await services.feature.add_feature(
            config.feature_config_id,
            key=f"exploratory_{i}",
            kind=Kind.EXPLORATORY,
            description=f"Exploratory attribute {i}.",
            grain=Grain.ACCIDENT,
            source_column=None,
            derivation=None,
            value_type=ValueType.BOOLEAN,
            matching_rule=MatchingRule(kind=MatchingRuleKind.NONE),
        )
    assert sum(1 for f in config.features if f.kind is Kind.EXPLORATORY) == EXPLORATORY_FEATURE_CAP

    await user.open("/features")
    await _until(lambda: bool(_find_marker(user, "add-feature")))
    (add,) = _find_marker(user, "add-feature")
    _one(user, add).click()
    await _until(lambda: bool(_find(user, "feature-key")))

    (seg_exploratory,) = _find_marker(user, "seg-exploratory")
    _one(user, seg_exploratory).click()
    await _until(lambda: bool(_find(user, "exploratory-budget")))

    assert (
        _all_text(user, "exploratory-budget")
        == f"{EXPLORATORY_FEATURE_CAP + 1} / {EXPLORATORY_FEATURE_CAP} used in this config"
    )
    assert _find(user, "exploratory-cap-error") != []


# --- frozen state --------------------------------------------------------------


async def test_the_frozen_variant_is_read_only_and_lists_its_evaluation(frozen: Seeded) -> None:
    """README, "Frozen state": every control renders `.ro`, no Add feature,
    the primary action reads "Clone to new evaluation", and the Reminder
    card is replaced by the citing-evaluations list — asserted against a
    **seeded** frozen `feature_config` with a seeded evaluation citing it
    (the task brief's own seeded-row pattern, M0-D1)."""
    user = frozen.user
    await user.open("/features")
    await user.should_see("Injury")
    await _until(lambda: bool(_find(user, "frozen-banner")))

    assert "cited by 1 evaluation" in _all_text(user, "frozen-banner")
    assert _find_marker(user, "add-feature") == []
    (clone,) = _find(user, "clone-feature-set")
    assert _element_text(clone) == "Clone to new evaluation"
    assert _find(user, "create-feature-set") == []

    await _select_feature_row(user, "worst_injury")
    await _until(lambda: bool(_find(user, "frozen-feature-name")))
    assert _all_text(user, "frozen-feature-name") == "worst_injury"
    await user.should_see("Evaluations citing this config")
    await user.should_see("1 evaluation(s) cite this config.")

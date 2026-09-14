"""The Models card and the endpoint line (sw-design.md §15.5, §15.6).

Three rules are asserted here and nowhere else:

- **Unreachable is a state, not an error**: an empty list and a reason, never
  an exception into the UI and never a traceback.
- **"Unknown" is not "does not fit"**: no GPU answer means `fits_vram=None`
  and every model stays selectable.
- **Never on a timer** (plan-phase-3.md C3): reachability is asked once per
  view load and once per refresh, which `StaticModelCatalog`'s counters make
  a countable claim rather than a stylistic one.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import DEFAULT_MODELS, StaticEndpointProber, StaticModelCatalog

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.domain.llm import PROBE_TIMEOUT_S, EndpointStatus, ProbeCode, ProbeResult
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuInfo, StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import Evaluation
from ra2.services.errors import FeatureValidationError
from ra2.services.evaluation_service import (
    CONNECTION_REASON_NOT_LOOPBACK,
    CONNECTION_REASON_UNREACHABLE,
    EVAL_ERROR_MODEL_EXCEEDS_VRAM,
    EvaluationService,
)
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend


def _unknown_vram_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    clock: FrozenClock,
    ids: SeededFactory,
    settings: Settings,
) -> EvaluationService:
    """The same service against `StaticGpuProbe()` — the honest "unknown",
    which is what a laptop with no NVIDIA GPU gets."""
    return EvaluationService(
        session_factory=db_session_factory,
        model_catalog=model_catalog,
        endpoint_prober=StaticEndpointProber(),
        gpu_probe=StaticGpuProbe(),
        clock=clock,
        ids=ids,
        settings=settings,
    )


async def test_list_models_judges_every_row_against_the_hosts_vram(
    evaluation_service: EvaluationService,
    fitting_model: str,
    oversized_model: str,
) -> None:
    models = await evaluation_service.list_models()

    by_tag = {model.tag: model for model in models}
    assert set(by_tag) == {model.tag for model in DEFAULT_MODELS}
    assert by_tag[fitting_model].fits_vram is True
    assert by_tag[fitting_model].disabled is False
    # 42.5 GB against the fixture host's 24 GB.
    assert by_tag[oversized_model].fits_vram is False
    assert by_tag[oversized_model].disabled is True


async def test_unknown_vram_leaves_every_model_selectable(
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
) -> None:
    """§15.6: `None` is not an error. No NVIDIA GPU means no `fits_vram`
    judgement, and the design's disabled row simply does not occur."""
    service = _unknown_vram_service(db_session_factory, model_catalog, clock, ids, eval_settings)

    models = await service.list_models()

    assert models != []
    assert all(model.fits_vram is None for model in models)
    assert all(model.disabled is False for model in models)
    connection = await service.connection_status()
    assert connection.gpu_name is None
    assert connection.gpu_vram_bytes is None


async def test_an_unreachable_endpoint_yields_a_reason_not_a_traceback(
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
    fixture_gpu: GpuInfo,
) -> None:
    """§15.5: the service hands the view an empty model list and a reason.
    Never a toast, never an exception."""
    catalog = StaticModelCatalog(status=EndpointStatus.UNREACHABLE)
    service = EvaluationService(
        session_factory=db_session_factory,
        model_catalog=catalog,
        endpoint_prober=StaticEndpointProber(),
        gpu_probe=StaticGpuProbe(fixture_gpu),
        clock=clock,
        ids=ids,
        settings=eval_settings,
    )

    models = await service.list_models()
    connection = await service.connection_status()

    assert models == []
    assert connection.status is EndpointStatus.UNREACHABLE
    assert connection.is_reachable is False
    assert connection.reason == CONNECTION_REASON_UNREACHABLE


async def test_a_non_loopback_endpoint_has_its_own_reason(
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
    fixture_gpu: GpuInfo,
) -> None:
    """N1's refusal is a *different* sentence from "nothing is listening" —
    the analyst's next action is not the same in the two cases."""
    catalog = StaticModelCatalog(status=EndpointStatus.REFUSED_NOT_LOOPBACK)
    service = EvaluationService(
        session_factory=db_session_factory,
        model_catalog=catalog,
        endpoint_prober=StaticEndpointProber(),
        gpu_probe=StaticGpuProbe(fixture_gpu),
        clock=clock,
        ids=ids,
        settings=eval_settings,
    )

    connection = await service.connection_status()

    assert connection.reason == CONNECTION_REASON_NOT_LOOPBACK
    assert await service.list_models() == []


async def test_connection_status_reports_the_endpoint_timeout_and_probe(
    evaluation_service: EvaluationService,
    eval_settings: Settings,
    fixture_gpu: GpuInfo,
) -> None:
    connection = await evaluation_service.connection_status()

    assert connection.endpoint == eval_settings.llm_base_url
    assert connection.timeout_s == eval_settings.llm_timeout_s
    assert connection.status is EndpointStatus.REACHABLE
    assert connection.reason is None
    assert connection.gpu_name == fixture_gpu.name
    assert connection.gpu_vram_bytes == fixture_gpu.total_vram_bytes


async def test_reachability_is_asked_on_demand_and_never_on_a_timer(
    evaluation_service: EvaluationService,
    model_catalog: StaticModelCatalog,
) -> None:
    """C3: re-checked on view load and when "refresh" is pressed. One ask per
    call, and **no** ask when nothing asked."""
    assert model_catalog.reachable_calls == 0

    await evaluation_service.connection_status()
    assert model_catalog.reachable_calls == 1

    # The dialog's "refresh": the endpoint came back between the two asks.
    model_catalog.set_status(EndpointStatus.UNREACHABLE)
    assert (await evaluation_service.connection_status()).is_reachable is False
    model_catalog.set_status(EndpointStatus.REACHABLE)
    assert (await evaluation_service.connection_status()).is_reachable is True
    assert model_catalog.reachable_calls == 3


async def test_a_vram_infeasible_model_cannot_be_selected(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    fitting_model: str,
    oversized_model: str,
) -> None:
    """The design disables the row; the service refuses it too, so a request
    that bypasses the view cannot queue a run that will never load."""
    _, _, evaluation_id = await launchable(models=(fitting_model,))

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.update_draft(
            EvaluationId(evaluation_id), selected_models=(fitting_model, oversized_model)
        )

    assert excinfo.value.validation_errors == (
        EVAL_ERROR_MODEL_EXCEEDS_VRAM.format(tag=oversized_model, size_gb=42.5, vram_gb=24.0),
    )
    # Nothing changed: the refusal is not a partial write.
    async with db_session_factory() as session:
        stored = await session.scalar(
            select(Evaluation.selected_models_json).where(Evaluation.id == evaluation_id)
        )
    assert stored is not None
    assert oversized_model not in stored


async def test_an_unknown_vram_refuses_nothing(
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    oversized_model: str,
) -> None:
    """ "Unknown" is ignorance, not a verdict: with no GPU answer even the
    70B model stays selectable (§15.6)."""
    _, _, evaluation_id = await launchable()
    service = _unknown_vram_service(db_session_factory, model_catalog, clock, ids, eval_settings)

    updated = await service.update_draft(
        EvaluationId(evaluation_id), selected_models=(oversized_model,)
    )

    assert updated.selected_models == (oversized_model,)


async def test_list_models_flags_the_evaluations_own_selection(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    fitting_model: str,
) -> None:
    _, _, evaluation_id = await launchable(models=(fitting_model,))

    models = await evaluation_service.list_models(EvaluationId(evaluation_id))

    assert {model.tag for model in models if model.selected} == {fitting_model}


# ===========================================================================
# test_connection — the settings dialog's Test button
# ===========================================================================
#
# A different question from `connection_status()`. That one asks about the
# **configured** endpoint and answers in one bit for the Models card; this asks
# about a value the analyst has typed into the dialog and not committed to
# anywhere, which is the only value worth testing while setting Ollama up.


async def test_test_connection_probes_the_endpoint_it_was_given(
    evaluation_service: EvaluationService,
    endpoint_prober: StaticEndpointProber,
) -> None:
    """The typed value, not `settings.llm_base_url`.

    Probing the configured endpoint instead would make the button useless for
    the one job it has: telling you whether the URL you are about to put in
    `.env` works.
    """
    typed = "http://127.0.0.1:9999/v1"

    view = await evaluation_service.test_connection(typed, 30)

    assert [url for url, _ in endpoint_prober.calls] == [typed]
    assert view.endpoint == typed


async def test_test_connection_carries_the_probes_verdict_through_unchanged(
    evaluation_service: EvaluationService,
    endpoint_prober: StaticEndpointProber,
) -> None:
    endpoint_prober.set_result(
        ProbeResult(code=ProbeCode.HTTP_ERROR, detail="404 page not found", http_status=404)
    )

    view = await evaluation_service.test_connection("http://127.0.0.1:11434/v1", 30)

    assert view.code is ProbeCode.HTTP_ERROR
    assert view.http_status == 404
    assert view.detail == "404 page not found"
    assert view.ok is False


async def test_test_connection_falls_back_to_the_configured_timeout(
    evaluation_service: EvaluationService,
    endpoint_prober: StaticEndpointProber,
    eval_settings: Settings,
) -> None:
    """`timeout_s=None` means "whatever the app is configured with" — the API
    route's `timeout_s` is optional and this is what fills it in."""
    await evaluation_service.test_connection("http://127.0.0.1:11434/v1", None)

    assert [timeout for _, timeout in endpoint_prober.calls] == [eval_settings.llm_timeout_s]


async def test_test_connection_reports_the_bound_the_probe_actually_used(
    evaluation_service: EvaluationService,
) -> None:
    """The dialog names this number in the timeout sentence.

    The configured timeout is 120 s by default — right for a model that is
    thinking, wrong for a dialog waiting on a reachability check. The view
    carries the **lower** of the two so a five-second failure does not read as
    contradicting the 120 in the field above it.
    """
    view = await evaluation_service.test_connection("http://127.0.0.1:11434/v1", 120)

    assert view.probe_timeout_s == PROBE_TIMEOUT_S


async def test_test_connection_keeps_a_shorter_timeout_than_the_cap(
    evaluation_service: EvaluationService,
) -> None:
    view = await evaluation_service.test_connection("http://127.0.0.1:11434/v1", 2)

    assert view.probe_timeout_s == 2


async def test_test_connection_does_not_raise_for_a_refused_host(
    evaluation_service: EvaluationService,
    endpoint_prober: StaticEndpointProber,
) -> None:
    """A non-loopback host is a **result**, not an exception.

    This is the one place the rule behaves differently from the startup guard,
    and deliberately so: `require_loopback` fails `create_app()` outright,
    because an app configured that way must not run. A dialog has to be able
    to say "that host is not local" and stay open — an exception here would
    become a toast, and the design does not have one.
    """
    endpoint_prober.set_result(ProbeResult(code=ProbeCode.REFUSED_NOT_LOOPBACK))

    view = await evaluation_service.test_connection("http://192.168.1.5:11434/v1", 30)

    assert view.code is ProbeCode.REFUSED_NOT_LOOPBACK
    assert view.ok is False


async def test_test_connection_never_touches_the_catalogue(
    evaluation_service: EvaluationService,
    model_catalog: StaticModelCatalog,
) -> None:
    """Testing a typed endpoint must not re-ask the configured one. The Models
    card's reachability is re-checked on view load and on refresh, **never on
    a timer** and never as a side effect of something else (C3)."""
    await evaluation_service.test_connection("http://127.0.0.1:11434/v1", 30)

    assert model_catalog.reachable_calls == 0
    assert model_catalog.models_calls == 0

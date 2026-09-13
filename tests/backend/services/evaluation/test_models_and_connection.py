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
from tests.fixtures.fake_llm import DEFAULT_MODELS, StaticModelCatalog

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.domain.llm import EndpointStatus
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

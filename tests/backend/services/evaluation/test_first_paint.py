"""The Evaluation screen paints before the endpoint answers (`SD55`).

NiceGUI gives a page function 3 s to return. Windows takes 2 s to refuse a
closed loopback port, and the page used to ask `/api/tags` twice in a row
before it returned, so with Ollama down it never rendered. Three properties
at the service seam make the fix hold:

- `get(..., probe=False)` and `connection_status(probe=False)` ask the
  endpoint **nothing**, and say `UNCHECKED` instead of guessing;
- `catalogue(evaluation_id)` is the half of `get()` that asks, so a caller
  can paint first and ask second and end up with exactly what one `get()`
  would have returned;
- what is asked is asked **at once**: reachability beside the catalogue, and
  one `/api/show` per model beside each other.
"""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import (
    DEFAULT_MODELS,
    GatedModelCatalog,
    StaticConnectionSettings,
    StaticEndpointProber,
)

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.domain.llm import EndpointStatus
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.services.evaluation_service import EvaluationService
from ra2.services.prompt_service import PromptService
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend

Launchable = Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]]


@pytest.fixture
def gated() -> GatedModelCatalog:
    return GatedModelCatalog()


@pytest.fixture
def service(
    db_session_factory: async_sessionmaker[AsyncSession],
    gated: GatedModelCatalog,
    endpoint_prober: StaticEndpointProber,
    gpu_probe: StaticGpuProbe,
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
) -> EvaluationService:
    """Wired as `create_app()` wires it, prompt previewer included, so the
    context check (SD53) runs and asks `/api/show`."""
    return EvaluationService(
        session_factory=db_session_factory,
        model_catalog=gated,
        endpoint_prober=endpoint_prober,
        gpu_probe=gpu_probe,
        clock=clock,
        ids=ids,
        settings=eval_settings,
        connection=StaticConnectionSettings.from_settings(eval_settings),
        prompt_preview=PromptService(session_factory=db_session_factory, clock=clock, ids=ids),
    )


def _asks(catalog: GatedModelCatalog) -> tuple[int, int, int, int]:
    return (
        catalog.reachable_calls,
        catalog.models_calls,
        catalog.parameters_calls,
        catalog.version_calls,
    )


async def _until_waiting(catalog: GatedModelCatalog, **expected: int) -> None:
    for _ in range(200):
        if all(catalog.waiting[name] == n for name, n in expected.items()):
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"never waiting {expected}: {catalog.waiting}")


async def test_a_read_told_not_to_probe_asks_the_endpoint_nothing(
    service: EvaluationService, gated: GatedModelCatalog, launchable: Launchable
) -> None:
    """The first paint. With every read held, a read that asked anything
    would hang here rather than return."""
    _, _, evaluation_id = await launchable()
    before = _asks(gated)
    gated.hold()

    view = await service.get(EvaluationId(evaluation_id), probe=False)

    assert _asks(gated) == before
    assert view.connection.status is EndpointStatus.UNCHECKED
    assert view.connection.reason is None
    assert view.models == ()
    # Selected, templated and unlaunched: only the endpoint keeps it shut.
    assert view.draft.selected_models
    assert view.can_launch is False


async def test_an_unchecked_connection_names_the_endpoint_and_asks_nothing(
    service: EvaluationService, gated: GatedModelCatalog, eval_settings: Settings
) -> None:
    gated.hold()

    connection = await service.connection_status(probe=False)

    assert _asks(gated) == (0, 0, 0, 0)
    assert connection.status is EndpointStatus.UNCHECKED
    assert connection.endpoint == eval_settings.llm_base_url
    assert connection.reason is None
    assert connection.gpu_name is None


async def test_painting_first_and_asking_second_ends_where_one_get_does(
    service: EvaluationService, launchable: Launchable
) -> None:
    """The view's two halves, against the one call they replace. Same
    models, same context fits, same Launch."""
    _, _, evaluation_id = await launchable()
    eid = EvaluationId(evaluation_id)

    fresh = await service.catalogue(eid)
    handed = await service.get(eid, connection=fresh.connection, models=fresh.models)
    whole = await service.get(eid)

    assert handed.connection == whole.connection
    assert handed.models == whole.models
    assert all(model.context_fit is not None for model in handed.models)
    assert handed.can_launch is whole.can_launch is True


async def test_reachability_and_the_catalogue_are_asked_at_once(
    service: EvaluationService, gated: GatedModelCatalog
) -> None:
    """Asked one after the other, `models()` cannot start until
    `reachable()` is let through, so both waiting together is the proof. The
    adapter answers the pair with one `/api/tags` request, so a dead endpoint
    costs one refusal and not two in a row."""
    gated.hold("reachable", "models")

    asked = asyncio.ensure_future(service.catalogue())
    await _until_waiting(gated, reachable=1, models=1)
    gated.answer()

    catalogue = await asked
    assert catalogue.connection.is_reachable
    assert len(catalogue.models) == len(DEFAULT_MODELS)


async def test_every_models_api_show_is_asked_at_once(
    service: EvaluationService, gated: GatedModelCatalog, launchable: Launchable
) -> None:
    """SD53's context check: one `/api/show` per model with no measured
    context. Sequentially, that was a dozen round trips on a view load for a
    dozen tags."""
    _, _, evaluation_id = await launchable()
    gated.hold("parameters")

    asked = asyncio.ensure_future(service.catalogue(EvaluationId(evaluation_id)))
    await _until_waiting(gated, parameters=len(DEFAULT_MODELS))
    gated.answer()

    assert len((await asked).models) == len(DEFAULT_MODELS)

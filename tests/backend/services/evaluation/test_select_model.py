"""One tick, one model: `EvaluationService.select_model` (`SD56`).

The Evaluation view used to send the whole selection, worked out from the
last evaluation it had read, and asked the endpoint on every tick. Each
property below is one half of what that cost:

- the click names **one model and its state**, so the rest of the selection
  is whatever is on disk, not whatever the screen last read;
- two clicks in flight both land: the read and the write are serialised;
- the endpoint is asked only when the answer could refuse the tick, which is
  a model being **added** on a host whose VRAM is **known**.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import (
    GatedModelCatalog,
    StaticConnectionSettings,
    StaticEndpointProber,
)

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.services.errors import EvaluationLockedError, FeatureValidationError
from ra2.services.evaluation_service import EvaluationService
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend

Launchable = Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]]


@pytest.fixture
def model_catalog() -> GatedModelCatalog:
    """Overrides the package fixture, so `evaluation_service` asks a catalogue
    the test can hold shut. Open until a test says otherwise."""
    return GatedModelCatalog()


@pytest.fixture
def cpu_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: GatedModelCatalog,
    endpoint_prober: StaticEndpointProber,
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
) -> EvaluationService:
    """The same service on a host with no NVIDIA GPU: VRAM unknown, so
    nothing can be refused for size (sw-design.md §15.6)."""
    return EvaluationService(
        session_factory=db_session_factory,
        model_catalog=model_catalog,
        endpoint_prober=endpoint_prober,
        gpu_probe=StaticGpuProbe(),
        clock=clock,
        ids=ids,
        settings=eval_settings,
        connection=StaticConnectionSettings.from_settings(eval_settings),
    )


def _asks(catalog: GatedModelCatalog) -> tuple[int, int, int]:
    return (catalog.reachable_calls, catalog.models_calls, catalog.parameters_calls)


async def _selection(service: EvaluationService, evaluation_id: EvaluationId) -> tuple[str, ...]:
    return (await service.get(evaluation_id, probe=False)).draft.selected_models


async def test_a_tick_adds_one_model_and_keeps_the_rest_in_order(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    fitting_model: str,
    second_fitting_model: str,
) -> None:
    _, _, raw_id = await launchable(models=(fitting_model,))
    evaluation_id = EvaluationId(raw_id)

    draft = await evaluation_service.select_model(
        evaluation_id, second_fitting_model, selected=True
    )

    assert draft.selected_models == (fitting_model, second_fitting_model)
    assert await _selection(evaluation_service, evaluation_id) == draft.selected_models


async def test_an_untick_removes_one_model_and_keeps_the_rest(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    fitting_model: str,
    second_fitting_model: str,
) -> None:
    _, _, raw_id = await launchable(models=(fitting_model, second_fitting_model))
    evaluation_id = EvaluationId(raw_id)

    draft = await evaluation_service.select_model(evaluation_id, fitting_model, selected=False)

    assert draft.selected_models == (second_fitting_model,)


async def test_the_state_is_set_not_flipped(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    fitting_model: str,
    second_fitting_model: str,
) -> None:
    """A click names the state the analyst wants. Sent twice, by a double
    click or by two tabs, it is the same state, not a toggle back. The
    order is left alone, because launch queues runs in that order."""
    _, _, raw_id = await launchable(models=(fitting_model, second_fitting_model))
    evaluation_id = EvaluationId(raw_id)

    await evaluation_service.select_model(evaluation_id, fitting_model, selected=True)
    assert await _selection(evaluation_service, evaluation_id) == (
        fitting_model,
        second_fitting_model,
    )

    await evaluation_service.select_model(evaluation_id, fitting_model, selected=False)
    await evaluation_service.select_model(evaluation_id, fitting_model, selected=False)
    assert await _selection(evaluation_service, evaluation_id) == (second_fitting_model,)


async def test_two_clicks_in_flight_both_land(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    monkeypatch: pytest.MonkeyPatch,
    fitting_model: str,
    second_fitting_model: str,
) -> None:
    """Each tick reads the selection and writes it back, and SQLite opens no
    transaction until the write. Unserialised, both read `()` and the second
    write drops the first model.

    Left to the scheduler, the two reads rarely overlap, so a test that only
    fires both at once passes with or without the lock. Here each read waits,
    once it has the row, until the other click has read too, or 0.2 s has
    passed. Without the lock both reads overlap every time. With it, the
    second cannot read until the first has written, so the first waits out
    its 0.2 s alone."""
    _, _, raw_id = await launchable(models=())
    evaluation_id = EvaluationId(raw_id)
    editable = EvaluationService._editable
    reading = 0
    both_reading = asyncio.Event()

    async def overlapping(self: EvaluationService, *args: object, **kwargs: object) -> object:
        nonlocal reading
        row = await editable(self, *args, **kwargs)  # type: ignore[arg-type]
        reading += 1
        if reading == 2:
            both_reading.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(both_reading.wait(), timeout=0.2)
        return row

    monkeypatch.setattr(EvaluationService, "_editable", overlapping)

    await asyncio.gather(
        evaluation_service.select_model(evaluation_id, fitting_model, selected=True),
        evaluation_service.select_model(evaluation_id, second_fitting_model, selected=True),
    )

    assert set(await _selection(evaluation_service, evaluation_id)) == {
        fitting_model,
        second_fitting_model,
    }


async def test_an_untick_asks_the_endpoint_nothing(
    evaluation_service: EvaluationService,
    model_catalog: GatedModelCatalog,
    launchable: Launchable,
    fitting_model: str,
) -> None:
    """Removing a model cannot make a selection infeasible. With every read
    held, an untick that asked anything would hang here."""
    _, _, raw_id = await launchable(models=(fitting_model,))
    before = _asks(model_catalog)
    model_catalog.hold()

    draft = await evaluation_service.select_model(
        EvaluationId(raw_id), fitting_model, selected=False
    )

    assert draft.selected_models == ()
    assert _asks(model_catalog) == before


async def test_with_no_known_vram_a_tick_asks_the_endpoint_nothing(
    cpu_service: EvaluationService,
    model_catalog: GatedModelCatalog,
    launchable: Launchable,
    oversized_model: str,
) -> None:
    """The reported host: no NVIDIA GPU. An unknown VRAM refuses nothing, so
    no answer from `/api/tags` could change the outcome, and asking it was a
    second or more of waiting on every tick. Even the model that would be
    refused on a 24 GB card is selectable here."""
    _, _, raw_id = await launchable(models=())
    before = _asks(model_catalog)
    model_catalog.hold()

    draft = await cpu_service.select_model(EvaluationId(raw_id), oversized_model, selected=True)

    assert draft.selected_models == (oversized_model,)
    assert _asks(model_catalog) == before


async def test_with_no_known_vram_update_draft_asks_the_endpoint_nothing(
    cpu_service: EvaluationService,
    model_catalog: GatedModelCatalog,
    launchable: Launchable,
    fitting_model: str,
    second_fitting_model: str,
) -> None:
    """The same judgement, reached through the whole-list write the API uses."""
    _, _, raw_id = await launchable(models=())
    before = _asks(model_catalog)
    model_catalog.hold()

    draft = await cpu_service.update_draft(
        EvaluationId(raw_id), selected_models=(fitting_model, second_fitting_model)
    )

    assert draft.selected_models == (fitting_model, second_fitting_model)
    assert _asks(model_catalog) == before


async def test_a_tick_the_vram_cannot_hold_is_refused_and_changes_nothing(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    fitting_model: str,
    oversized_model: str,
) -> None:
    """The VRAM is known here, so the endpoint is asked for the model's size
    and the 42.5 GB model is refused, exactly as `update_draft` refuses it."""
    _, _, raw_id = await launchable(models=(fitting_model,))
    evaluation_id = EvaluationId(raw_id)

    with pytest.raises(FeatureValidationError) as excinfo:
        await evaluation_service.select_model(evaluation_id, oversized_model, selected=True)

    (message,) = excinfo.value.validation_errors
    assert oversized_model in message
    assert await _selection(evaluation_service, evaluation_id) == (fitting_model,)


async def test_a_launched_evaluation_refuses_a_tick(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    fitting_model: str,
    second_fitting_model: str,
) -> None:
    _, _, raw_id = await launchable(models=(fitting_model,))
    evaluation_id = EvaluationId(raw_id)
    await evaluation_service.launch(evaluation_id)

    with pytest.raises(EvaluationLockedError):
        await evaluation_service.select_model(evaluation_id, second_fitting_model, selected=True)
    with pytest.raises(EvaluationLockedError):
        await evaluation_service.select_model(evaluation_id, fitting_model, selected=False)

    assert await _selection(evaluation_service, evaluation_id) == (fitting_model,)

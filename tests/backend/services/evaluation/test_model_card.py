"""The Models card's third line (sw-design.md SD40, design README §2 step 4,
`plan-model-choice.md` Stage 5).

Each row carries what this host has measured about that model: the newest
qualification of its digest, or a stale one flagged as such, or nothing. The
service hands over numbers and a state; the wording is `ui/`'s.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import StaticEndpointProber, StaticModelCatalog

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.domain.qualification import GateVerdict, QualificationState
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.services.evaluation_service import EvaluationService
from ra2.services.readmodels import FeatureConfigView, ModelChoiceView

pytestmark = pytest.mark.backend

DIGEST = "8fa1c3d0"
#: `record_gate`'s serial rate and its gate's speedup.
SERIAL_MS = 1745.0
SPEEDUP = 2.4

Launchable = Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]]
RecordGate = Callable[..., Awaitable[None]]


def _row(models: tuple[ModelChoiceView, ...], tag: str) -> ModelChoiceView:
    return next(model for model in models if model.tag == tag)


async def test_an_unmeasured_model_has_no_qualification(
    evaluation_service: EvaluationService, fitting_model: str
) -> None:
    catalogue = await evaluation_service.catalogue()

    assert _row(catalogue.models, fitting_model).qualification is None


async def test_model_choices_carry_the_latest_qualification_per_digest(
    evaluation_service: EvaluationService, record_gate: RecordGate, fitting_model: str
) -> None:
    await record_gate(fitting_model, DIGEST, gated_at=())

    card = _row((await evaluation_service.catalogue()).models, fitting_model).qualification

    assert card is not None
    assert card.state is QualificationState.QUALIFIED
    assert card.measured_digest == DIGEST
    assert (card.seed_macro_f1, card.ms_per_record, card.entity_fill) == (0.895, SERIAL_MS, 0.0)
    assert card.parallel_calls == 1
    assert card.launch_ms_per_record == SERIAL_MS


async def test_a_qualification_of_other_weights_is_shown_stale(
    evaluation_service: EvaluationService, record_gate: RecordGate, fitting_model: str
) -> None:
    await record_gate(fitting_model, "00aa11bb", gated_at=())

    card = _row((await evaluation_service.catalogue()).models, fitting_model).qualification

    assert card is not None
    assert card.state is QualificationState.STALE_DIGEST
    assert card.measured_digest == "00aa11bb"


async def test_a_model_whose_serial_answers_move_on_a_multi_slot_server_is_flagged(
    evaluation_service: EvaluationService, record_gate: RecordGate, fitting_model: str
) -> None:
    await record_gate(fitting_model, DIGEST, verdict=GateVerdict.FAILS_SERVER)

    card = _row((await evaluation_service.catalogue()).models, fitting_model).qualification

    assert card is not None
    assert card.state is QualificationState.SERVER_SENSITIVE


@pytest.fixture
def mapped_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    endpoint_prober: StaticEndpointProber,
    gpu_probe: StaticGpuProbe,
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
    fitting_model: str,
) -> EvaluationService:
    return EvaluationService(
        session_factory=db_session_factory,
        model_catalog=model_catalog,
        endpoint_prober=endpoint_prober,
        gpu_probe=gpu_probe,
        clock=clock,
        ids=ids,
        settings=eval_settings.model_copy(update={"llm_parallel_calls": {fitting_model: 4}}),
    )


async def test_the_card_says_parallel_only_where_the_launch_would_honour_it(
    mapped_service: EvaluationService, record_gate: RecordGate, fitting_model: str
) -> None:
    """The same `parallel_decision` the launch calls, so the card can't
    promise a parallelism the launch then refuses."""
    await record_gate(fitting_model, DIGEST)

    card = _row((await mapped_service.catalogue()).models, fitting_model).qualification

    assert card is not None
    assert card.parallel_calls == 4
    assert card.launch_ms_per_record == pytest.approx(SERIAL_MS / SPEEDUP)


async def test_a_stale_gate_shows_serial_on_the_card(
    mapped_service: EvaluationService, record_gate: RecordGate, fitting_model: str
) -> None:
    await record_gate(fitting_model, DIGEST, ollama_version="0.33.2")

    card = _row((await mapped_service.catalogue()).models, fitting_model).qualification

    assert card is not None
    assert card.parallel_calls == 1


async def test_estimate_uses_the_evaluation_scope(
    evaluation_service: EvaluationService,
    launchable: Launchable,
    record_gate: RecordGate,
    fitting_model: str,
) -> None:
    """Time per record at the launch's parallelism, times the records this
    evaluation would visit. The catalogue alone has no scope, so no estimate."""
    await record_gate(fitting_model, DIGEST, gated_at=())
    _, _, evaluation_id = await launchable(record_count=10, models=(fitting_model,))

    view = await evaluation_service.get(EvaluationId(evaluation_id))
    catalogue = await evaluation_service.catalogue()

    card = _row(view.models, fitting_model).qualification
    assert card is not None
    assert card.estimated_ms == round(SERIAL_MS * 10)
    catalogue_card = _row(catalogue.models, fitting_model).qualification
    assert catalogue_card is not None and catalogue_card.estimated_ms is None


async def test_the_progress_timer_reads_no_qualification_and_asks_no_version(
    mapped_service: EvaluationService,
    model_catalog: StaticModelCatalog,
    launchable: Launchable,
    record_gate: RecordGate,
    fitting_model: str,
) -> None:
    """The timer hands `get()` the models it holds. The card must survive that
    unchanged, apart from the scoped estimate, without a round trip to the
    endpoint (plan-phase-3.md C3: never on a timer)."""
    await record_gate(fitting_model, DIGEST)
    _, _, evaluation_id = await launchable(models=(fitting_model,))
    loaded = await mapped_service.get(EvaluationId(evaluation_id))
    asked = (model_catalog.version_calls, model_catalog.models_calls)

    ticked = await mapped_service.get(
        EvaluationId(evaluation_id), connection=loaded.connection, models=loaded.models
    )

    assert (model_catalog.version_calls, model_catalog.models_calls) == asked
    assert (
        _row(ticked.models, fitting_model).qualification
        == _row(loaded.models, fitting_model).qualification
    )

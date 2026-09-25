"""The launch checks a parallel-calls entry against a gate (sw-design.md SD40,
`plan-model-choice.md` Stage 4).

`RA2_LLM_PARALLEL_CALLS` used to apply as written: a docstring sentence was
the only check that an entry had been measured, and a re-pull kept the entry
applying to weights nobody had gated. Now the launch pins the map's value only
when a passing gate for that digest, on this Ollama version, is on record.
Every other case pins 1 and logs why.

The rule itself is `domain.qualification.parallel_decision`, unit-tested one
reason at a time. These tests are about the launch using it: the right
qualification found, the right version asked, the pin written, the reason
logged.
"""

import re
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import StaticEndpointProber, StaticModelCatalog

from ra2.domain.ids import CorpusId, EvaluationId
from ra2.domain.qualification import GateVerdict
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import Run
from ra2.services.evaluation_service import EvaluationService
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend

REPO_ROOT = Path(__file__).resolve().parents[4]
#: `DEFAULT_MODELS`' digest for the fitting model.
DIGEST = "8fa1c3d0"

Launchable = Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]]
RecordGate = Callable[..., Awaitable[None]]


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
    """The service with `{fitting_model: 4}` in the map."""
    return EvaluationService(
        session_factory=db_session_factory,
        model_catalog=model_catalog,
        endpoint_prober=endpoint_prober,
        gpu_probe=gpu_probe,
        clock=clock,
        ids=ids,
        settings=eval_settings.model_copy(update={"llm_parallel_calls": {fitting_model: 4}}),
    )


async def _pinned(
    service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    model: str,
    *,
    measuring: bool = False,
) -> int:
    _, _, evaluation_id = await launchable(models=(model,))
    await service.launch(EvaluationId(evaluation_id), measuring=measuring)
    async with db_session_factory() as session:
        run = await session.scalar(select(Run).where(Run.evaluation_id == evaluation_id))
    assert run is not None
    return run.llm_parallel_calls


async def test_launch_honours_the_map_for_a_gated_digest(
    mapped_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    record_gate: RecordGate,
    fitting_model: str,
) -> None:
    await record_gate(fitting_model, DIGEST)

    assert await _pinned(mapped_service, launchable, db_session_factory, fitting_model) == 4


async def test_launch_runs_serially_without_a_qualification(
    mapped_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    fitting_model: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The case every host with a map is in until it runs `qualify-model`."""
    with caplog.at_level("INFO", logger="ra2.services.evaluation_service"):
        assert await _pinned(mapped_service, launchable, db_session_factory, fitting_model) == 1

    assert f"{fitting_model} parallel=1 (map=4, gate=missing)" in caplog.text


async def test_launch_runs_serially_after_a_re_pull(
    mapped_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    record_gate: RecordGate,
    fitting_model: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same tag, different weights: the gate described weights that are gone."""
    await record_gate(fitting_model, "00aa11bb")

    with caplog.at_level("INFO", logger="ra2.services.evaluation_service"):
        assert await _pinned(mapped_service, launchable, db_session_factory, fitting_model) == 1

    assert "gate=digest" in caplog.text


async def test_the_current_digest_wins_over_a_newer_gate_for_other_weights(
    mapped_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    record_gate: RecordGate,
    fitting_model: str,
) -> None:
    """Gated these weights, then gated other weights later (a re-pull, then a
    rollback): the weights that will run are the ones that count."""
    await record_gate(fitting_model, DIGEST)
    await record_gate(fitting_model, "00aa11bb")

    assert await _pinned(mapped_service, launchable, db_session_factory, fitting_model) == 4


async def test_launch_runs_serially_on_a_different_ollama_version(
    mapped_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    record_gate: RecordGate,
    fitting_model: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await record_gate(fitting_model, DIGEST, ollama_version="0.33.2")

    with caplog.at_level("INFO", logger="ra2.services.evaluation_service"):
        assert await _pinned(mapped_service, launchable, db_session_factory, fitting_model) == 1

    assert "gate=ollama_version" in caplog.text


async def test_launch_runs_serially_when_the_gate_failed(
    mapped_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    record_gate: RecordGate,
    fitting_model: str,
) -> None:
    await record_gate(fitting_model, DIGEST, verdict=GateVerdict.FAILS_PARALLEL)

    assert await _pinned(mapped_service, launchable, db_session_factory, fitting_model) == 1


async def test_a_map_above_the_gated_n_runs_serially_not_at_the_gated_n(
    mapped_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    record_gate: RecordGate,
    fitting_model: str,
) -> None:
    """Gated at 2 only, map says 4: pin 1 (plan-model-choice.md Q5)."""
    await record_gate(fitting_model, DIGEST, gated_at=(2,))

    assert await _pinned(mapped_service, launchable, db_session_factory, fitting_model) == 1


async def test_a_later_quality_only_qualification_keeps_the_gate(
    mapped_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    record_gate: RecordGate,
    fitting_model: str,
) -> None:
    await record_gate(fitting_model, DIGEST)
    await record_gate(fitting_model, DIGEST, gated_at=())

    assert await _pinned(mapped_service, launchable, db_session_factory, fitting_model) == 4


async def test_an_unmapped_model_is_unaffected(
    evaluation_service: EvaluationService,
    model_catalog: StaticModelCatalog,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    record_gate: RecordGate,
    fitting_model: str,
) -> None:
    """A gate on record doesn't make a model parallel: the map decides whether
    to try, and the gate whether that's allowed. With an empty map, today's
    default, the launch doesn't even ask for the version."""
    await record_gate(fitting_model, DIGEST)

    assert await _pinned(evaluation_service, launchable, db_session_factory, fitting_model) == 1
    assert model_catalog.version_calls == 0


async def test_a_measuring_launch_pins_the_map_without_a_gate(
    mapped_service: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
    fitting_model: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`just qualify-model`'s passes are the gate measurement, in a database
    that can't hold a gate yet."""
    with caplog.at_level("INFO", logger="ra2.services.evaluation_service"):
        pinned = await _pinned(
            mapped_service, launchable, db_session_factory, fitting_model, measuring=True
        )

    assert pinned == 4
    assert "gate=measuring" in caplog.text


@pytest.mark.parametrize("adapter", ["api", "ui"])
def test_no_adapter_launches_as_a_measurement(adapter: str) -> None:
    """The exception exists for the qualifier alone. An analyst's evaluation,
    launched from the Evaluation screen or `POST …/launch`, is never one."""
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "ra2" / adapter).rglob("*.py"))
        if re.search(r"\bmeasuring\s*=", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []

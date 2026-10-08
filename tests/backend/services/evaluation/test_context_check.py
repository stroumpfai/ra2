"""The longest prompt is checked against each model's known context before a
launch (`SD53`, risk D1's second recommendation).

Ollama truncates rather than refuses, so a model whose context cannot hold the
prompt spends GPU-hours being scored on text it never read. The check runs on
the Models card (a fresh catalogue only, never on the progress timer) and
again, authoritatively, at launch, where a model **known** not to fit is
refused like one too big for the VRAM. Unknown never refuses.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.backend.services.evaluation.conftest import FITTING_MODEL
from tests.fixtures.fake_llm import (
    StaticConnectionSettings,
    StaticEndpointProber,
    StaticModelCatalog,
)

from ra2.domain.context_fit import ANSWER_RESERVE_TOKENS, ContextSource
from ra2.domain.ids import CorpusId, EvaluationId
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import Run
from ra2.services.errors import FeatureValidationError
from ra2.services.evaluation_service import EVAL_ERROR_CONTEXT_TOO_SMALL, EvaluationService
from ra2.services.prompt_service import PromptService
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend

Launchable = Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]]


@pytest.fixture
def checked(
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    endpoint_prober: StaticEndpointProber,
    gpu_probe: StaticGpuProbe,
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
) -> EvaluationService:
    """The service as `create_app()` wires it: with a prompt previewer."""
    return EvaluationService(
        session_factory=db_session_factory,
        model_catalog=model_catalog,
        endpoint_prober=endpoint_prober,
        gpu_probe=gpu_probe,
        clock=clock,
        ids=ids,
        settings=eval_settings,
        connection=StaticConnectionSettings.from_settings(eval_settings),
        prompt_preview=PromptService(session_factory=db_session_factory, clock=clock, ids=ids),
    )


async def _runs(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(Run)) or 0)


def _fit_for(view: object, tag: str) -> object:
    return next(m for m in view.models if m.tag == tag).context_fit  # type: ignore[attr-defined]


async def test_a_modelfile_context_too_small_refuses_the_launch_and_writes_nothing(
    checked: EvaluationService,
    launchable: Launchable,
    model_catalog: StaticModelCatalog,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    model_catalog.server_parameters[FITTING_MODEL] = {"num_ctx": ("512",)}
    _, _, evaluation_id = await launchable()

    view = await checked.get(EvaluationId(evaluation_id))
    fit = _fit_for(view, FITTING_MODEL)
    assert fit.fits is False and fit.source is ContextSource.MODELFILE  # type: ignore[attr-defined]
    assert next(m for m in view.models if m.tag == FITTING_MODEL).disabled

    with pytest.raises(FeatureValidationError) as refused:
        await checked.launch(EvaluationId(evaluation_id))

    (message,) = refused.value.validation_errors
    assert message.startswith(f"{FITTING_MODEL}: the longest record's prompt needs about")
    assert message == EVAL_ERROR_CONTEXT_TOO_SMALL.format(
        tag=FITTING_MODEL,
        needed=fit.needed_tokens,  # type: ignore[attr-defined]
        context=512,
        source="its Modelfile",
    )
    assert await _runs(db_session_factory) == 0


async def test_a_context_that_fits_launches(
    checked: EvaluationService,
    launchable: Launchable,
    model_catalog: StaticModelCatalog,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The positive control: the same corpus and template, a roomy context."""
    model_catalog.server_parameters[FITTING_MODEL] = {"num_ctx": ("8192",)}
    _, _, evaluation_id = await launchable()

    view = await checked.get(EvaluationId(evaluation_id))
    fit = _fit_for(view, FITTING_MODEL)
    assert fit.fits is True  # type: ignore[attr-defined]
    assert fit.prompt_tokens > 0  # type: ignore[attr-defined]
    assert fit.needed_tokens == fit.prompt_tokens + ANSWER_RESERVE_TOKENS  # type: ignore[attr-defined]

    await checked.launch(EvaluationId(evaluation_id))
    assert await _runs(db_session_factory) == 1


async def test_an_unknown_context_never_refuses(
    checked: EvaluationService,
    launchable: Launchable,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No Modelfile `num_ctx` and no earlier run: *cannot check*, and the
    launch goes ahead. Nothing is refused on a guess."""
    _, _, evaluation_id = await launchable()

    view = await checked.get(EvaluationId(evaluation_id))
    fit = _fit_for(view, FITTING_MODEL)
    assert fit.fits is None and fit.context_length is None  # type: ignore[attr-defined]

    await checked.launch(EvaluationId(evaluation_id))
    assert await _runs(db_session_factory) == 1


async def test_a_measured_context_wins_over_the_modelfile(
    checked: EvaluationService,
    launchable: Launchable,
    model_catalog: StaticModelCatalog,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """What an earlier run of the same tag and digest was actually loaded with
    on this host is better evidence than what the Modelfile asks for."""
    model_catalog.server_parameters[FITTING_MODEL] = {"num_ctx": ("8192",)}
    _, config, first = await launchable()
    await checked.launch(EvaluationId(first))
    async with db_session_factory() as session:
        await session.execute(update(Run).values(context_length=512))
        await session.commit()
    second = await checked.save_draft(
        name="again", corpus_id=CorpusId("corpus-1"), feature_config_id=config.feature_config_id
    )
    await checked.update_draft(second.evaluation_id, selected_models=(FITTING_MODEL,))

    view = await checked.get(EvaluationId(second.evaluation_id))
    fit = _fit_for(view, FITTING_MODEL)
    assert fit.source is ContextSource.MEASURED  # type: ignore[attr-defined]
    assert fit.context_length == 512  # type: ignore[attr-defined]
    assert fit.fits is False  # type: ignore[attr-defined]


async def test_the_progress_timer_path_asks_the_endpoint_nothing(
    checked: EvaluationService,
    launchable: Launchable,
    model_catalog: StaticModelCatalog,
) -> None:
    """Models handed back keep their fit; no `/api/show` on the timer (C3)."""
    model_catalog.server_parameters[FITTING_MODEL] = {"num_ctx": ("8192",)}
    _, _, evaluation_id = await launchable()
    loaded = await checked.get(EvaluationId(evaluation_id))
    asked = model_catalog.parameters_calls

    again = await checked.get(
        EvaluationId(evaluation_id), connection=loaded.connection, models=loaded.models
    )

    assert model_catalog.parameters_calls == asked
    assert _fit_for(again, FITTING_MODEL) == _fit_for(loaded, FITTING_MODEL)

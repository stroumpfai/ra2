# STUB — bodies owned by I2 (feat/p3-evaluation-service). Not frozen.
"""Evaluation drafts, the model catalogue, and the launch transaction
(mvp-spec.md §9, sw-design.md §15.2).

**An evaluation pins; a launch snapshots.** A draft is a saved setup and is
editable while `launched_at IS NULL`. `launch()` is the moment the inputs stop
being editable — and therefore the moment "evaluation creation" in
mvp-spec.md §8.5's sense happens: the `evaluation_feature` snapshot and every
final fingerprint resolve there, in one transaction, or not at all.

`ModelCatalog` and `GpuProbe` arrive injected, so this service never imports
`openai` or `pynvml` and the suite runs on a laptop with no GPU and nothing
listening on 11434.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.extraction import EvaluationSize
from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    FeatureConfigId,
    PromptTemplateId,
)
from ra2.domain.llm import ModelCatalog
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuProbe
from ra2.infra.idgen import IdFactory
from ra2.services.readmodels import (
    ConnectionView,
    EvaluationDraftView,
    EvaluationView,
    ModelChoiceView,
)

__all__ = ["EvaluationService"]


class EvaluationService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        model_catalog: ModelCatalog,
        gpu_probe: GpuProbe,
        clock: Clock,
        ids: IdFactory,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._model_catalog = model_catalog
        self._gpu_probe = gpu_probe
        self._clock = clock
        self._ids = ids
        self._settings = settings

    async def list_evaluations(self) -> list[EvaluationDraftView]:
        """Every evaluation, drafts included, newest first."""
        raise NotImplementedError

    async def get(self, evaluation_id: EvaluationId) -> EvaluationView:
        """One whole Evaluation screen: setup, models, connection, progress,
        runs and provenance.

        :raises NotFoundError: no such evaluation.
        """
        raise NotImplementedError

    async def save_draft(
        self,
        *,
        name: str,
        corpus_id: CorpusId,
        feature_config_id: FeatureConfigId,
    ) -> EvaluationDraftView:
        """Create an unlaunched evaluation with the design's defaults —
        the active template, temperature 0.0, seed 42, size `full`."""
        raise NotImplementedError

    async def update_draft(
        self,
        evaluation_id: EvaluationId,
        *,
        name: str | None = None,
        corpus_id: CorpusId | None = None,
        feature_config_id: FeatureConfigId | None = None,
        prompt_template_id: PromptTemplateId | None = None,
        prompt_language: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        size: EvaluationSize | None = None,
        selected_models: tuple[str, ...] | None = None,
    ) -> EvaluationDraftView:
        """Edit any of the six steps. **Draft only.**

        :raises EvaluationLockedError: `launched_at` is set; nothing changed.
        :raises NotFoundError: no such evaluation.
        """
        raise NotImplementedError

    async def list_models(self, evaluation_id: EvaluationId | None = None) -> list[ModelChoiceView]:
        """The endpoint's catalogue, each row judged against the host's VRAM.

        An **unreachable endpoint yields an empty list and a reason** through
        `connection_status()`, never an exception into the UI (§15.5). An
        unknown VRAM yields `fits_vram=None` — every model stays selectable,
        because "unknown" is not "does not fit" (§15.6).
        """
        raise NotImplementedError

    async def connection_status(self) -> ConnectionView:
        """Endpoint, timeout, reachability and the probe's GPU answer.

        Re-checked on view load and when the settings dialog's "refresh" is
        pressed — **never on a timer** (plan-phase-3.md C3).
        """
        raise NotImplementedError

    async def launch(self, evaluation_id: EvaluationId) -> EvaluationView:
        """The launch transaction (sw-design.md §15.2). In **one** transaction:

        1. verify the cited `feature_config` is frozen — an unfrozen one is
           refused and **nothing is created**;
        2. write one `evaluation_feature` per feature, carrying
           `enum_codelist_json` snapshotted from the corpus's *current*
           `column_mapping` generation and the final fingerprint from
           `domain.fingerprint.compute_fingerprint`;
        3. set `is_dev` from the size choice against `RA2_EVAL_RECORD_MIN` /
           `RA2_DEV_RECORD_MAX`;
        4. stamp `launched_at`;
        5. create one `queued` `run` per selected model, provenance and all.

        After it, every edit path raises. Submitting the work is
        `RunService.launch_runs`'s job, not this one's — the transaction ends
        here.

        :raises FeatureValidationError: the cited config is still a draft —
            reused rather than given a type of its own, because "the set this
            launch cites is not frozen" is exactly a blocking validation
            message and 422 is exactly its status. Nothing is created.
        :raises EvaluationLockedError: already launched.
        :raises NotFoundError: no such evaluation.
        """
        raise NotImplementedError

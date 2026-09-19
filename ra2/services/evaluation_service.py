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

---

## The snapshot codec

`snapshot_to_json` / `snapshot_from_json` are the one encoding of
`evaluation_feature.enum_codelist_json`. They live here because this is the
only module that **writes** the column — `prompt_service.resolve` (I1) and
`run_service` (I3) read it back through `snapshot_from_json` rather than each
inventing a parser. The bytes matter beyond round-tripping: this string goes
into `compute_fingerprint` verbatim (mvp-spec.md §8.5), so two writers of the
same code table must produce the same string or the fingerprints disagree.
Hence key-sorted, compact, `ensure_ascii=False`, and the codes ordered by
`code` — the M0-D8 convention `matching_rule_json` already follows.
"""

import json
import platform
import statistics
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.codes import CodeValue as DomainCodeValue
from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.feature import Grain, Kind, ValueType, requires_codelist
from ra2.domain.fingerprint import FingerprintInput, compute_fingerprint
from ra2.domain.ids import (
    CodeAttributeId,
    CorpusId,
    EvaluationId,
    FeatureConfigId,
    FeatureId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.domain.llm import (
    PROBE_TIMEOUT_S,
    EndpointProber,
    EndpointStatus,
    ModelCatalog,
    ModelInfo,
)
from ra2.infra.clock import Clock
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuProbe
from ra2.infra.idgen import IdFactory
from ra2.persistence.models import (
    Corpus,
    Evaluation,
    EvaluationFeature,
    Extraction,
    Feature,
    FeatureConfig,
    PromptTemplate,
    Record,
    Run,
)
from ra2.persistence.repositories.codelist_repo import CodelistRepository
from ra2.persistence.repositories.corpus_repo import CorpusRepository
from ra2.persistence.repositories.evaluation_repo import EvaluationRepository
from ra2.persistence.repositories.feature_repo import FeatureRepository
from ra2.persistence.repositories.prompt_repo import PromptRepository
from ra2.persistence.repositories.run_repo import RunRepository
from ra2.persistence.session import session_scope
from ra2.services.errors import (
    EvaluationLockedError,
    FeatureValidationError,
    NotFoundError,
)
from ra2.services.readmodels import (
    CatalogueView,
    ConnectionProbeView,
    ConnectionView,
    EvaluationDraftView,
    EvaluationView,
    ModelChoiceView,
    Page,
    ProvenanceView,
    RunProgressView,
    RunView,
    SortDir,
)
from ra2.services.run_service import run_ordinals

__all__ = [
    "CONNECTION_REASON_NOT_LOOPBACK",
    "CONNECTION_REASON_TIMED_OUT",
    "CONNECTION_REASON_UNREACHABLE",
    "EVAL_ERROR_CONFIG_NOT_FROZEN",
    "EVAL_ERROR_ENDPOINT_UNREACHABLE",
    "EVAL_ERROR_ENUM_NO_CODELIST",
    "EVAL_ERROR_ENUM_NO_LABEL_IN_LANGUAGE",
    "EVAL_ERROR_MODEL_EXCEEDS_VRAM",
    "EVAL_ERROR_MODEL_NOT_AVAILABLE",
    "EVAL_ERROR_NO_MODELS_SELECTED",
    "EVAL_ERROR_NO_TEMPLATE",
    "EvaluationService",
    "snapshot_from_json",
    "snapshot_to_json",
]

#: `NotFoundError.kind` values — stable identifiers the API and UI switch on,
#: the way `FindingCode` values are (CLAUDE.md).
_EVALUATION_KIND: Final = "evaluation"
_CORPUS_KIND: Final = "corpus"
_CONFIG_KIND: Final = "feature config"
_TEMPLATE_KIND: Final = "prompt template"

#: The design's step 5 defaults, and C1's language.
_DEFAULT_TEMPERATURE: Final = 0.0
_DEFAULT_SEED: Final = 42
_DEFAULT_LANGUAGE: Final = "de"

# --- launch validation messages --------------------------------------------
#
# `FeatureValidationError` carries plain strings, so — exactly as
# `feature_service` reasons about its own four — these templates *are* the
# stable identifiers. Tests and the UI format them; neither re-types the
# wording.

#: sw-design.md §15.2 / mvp-spec.md §9: an evaluation only ever cites an
#: already-frozen config, it never freezes one itself.
EVAL_ERROR_CONFIG_NOT_FROZEN: Final = (
    "{name}: a launch can only cite a frozen feature set; this one is still a draft."
)
#: §15.2 — `prompt_template_id` is nullable so a draft can exist before any
#: template does; the launch transaction is what requires one.
EVAL_ERROR_NO_TEMPLATE: Final = "no prompt template is selected; a launch needs one."
#: The design's "Launch N runs" with N = 0 has nothing to launch.
EVAL_ERROR_NO_MODELS_SELECTED: Final = "no models are selected; a launch needs at least one."
#: mvp-spec.md §19.8 — a run's record must carry the model **digest**, and the
#: digest comes from the endpoint. Nothing to ask means nothing to pin.
EVAL_ERROR_ENDPOINT_UNREACHABLE: Final = (
    "the LLM endpoint {endpoint} is not reachable; a launch cannot pin a model digest."
)
EVAL_ERROR_MODEL_NOT_AVAILABLE: Final = (
    "{tag}: the endpoint does not offer this model, so its digest cannot be pinned."
)
#: sw-design.md §15.6 — only ever raised when the VRAM is actually *known*.
EVAL_ERROR_MODEL_EXCEEDS_VRAM: Final = (
    "{tag}: {size_gb:.1f} GB exceeds the host's {vram_gb:.1f} GB of VRAM."
)
#: mvp-spec.md §7: "A feature whose column has no mapping, or whose mapped
#: attribute has no code table, and whose type is `enum` cannot be run — hard
#: validation error at evaluation setup."
EVAL_ERROR_ENUM_NO_CODELIST: Final = (
    "{key}: enum column {column} has no code table in this corpus; it cannot be run."
)
#: mvp-spec.md §7's known gap — `main_cause*` has no `it` — "not a fallback to
#: another language".
EVAL_ERROR_ENUM_NO_LABEL_IN_LANGUAGE: Final = (
    "{key}: the code table mapped to {column} has no {language} labels; "
    "there is no fallback to another language."
)

# --- connection reasons ----------------------------------------------------
#
# The reason is rendered **beside the endpoint line, never as a toast**
# (plan-phase-3.md C3). `ui/` keeps its own rendering table keyed on
# `EndpointStatus`; these are the service-level sentences the API returns and
# the fallback the UI shows, and they exist as constants so a test asserts on
# the identifier rather than on wording.

CONNECTION_REASON_UNREACHABLE: Final = (
    "Nothing is listening at this endpoint. Start Ollama, then press refresh."
)
CONNECTION_REASON_NOT_LOOPBACK: Final = (
    "This endpoint is not on the local machine, so it is refused: "
    "no data leaves this host, and there is no opt-out."
)
CONNECTION_REASON_TIMED_OUT: Final = (
    "This endpoint answered but did not finish in time. "
    "Raise RA2_LLM_TIMEOUT_S, or pick a model that answers faster."
)

#: Every `EndpointStatus` but `REACHABLE`, which has no reason to give.
#: Exhaustive by test rather than by convention: this is a dict keyed on an
#: enum and read with `[]`, so a member added without an entry here is a
#: `KeyError` on the Evaluation view's load path and nowhere else.
_CONNECTION_REASONS: Final[dict[EndpointStatus, str]] = {
    EndpointStatus.UNREACHABLE: CONNECTION_REASON_UNREACHABLE,
    EndpointStatus.TIMED_OUT: CONNECTION_REASON_TIMED_OUT,
    EndpointStatus.REFUSED_NOT_LOOPBACK: CONNECTION_REASON_NOT_LOOPBACK,
}

#: The snapshot's serialisation. Key-sorted and compact for the same reason
#: `matching_rule_json` is: the string is hashed, so two writers of one code
#: table must emit one byte sequence. `ensure_ascii=False` so label text hashes
#: as text rather than as `\uXXXX` escapes, matching `domain.fingerprint`.
_JSON_KWARGS: Final = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": False}

#: Decimal GB, matching `GpuInfo.total_vram_gb` and how Ollama reports sizes.
_BYTES_PER_GB: Final = 1_000_000_000


def snapshot_to_json(values: Sequence[DomainCodeValue]) -> str:
    """The `evaluation_feature.enum_codelist_json` encoding.

    A JSON array of `{"attribute_key", "code", "label"}` objects **ordered by
    code**, so the same code table always produces the same bytes and
    therefore the same fingerprint. Every language the import carried is kept:
    mvp-spec.md §7 stores all of them and the prompt picks one, and §8.5
    hashes "`enum_codelist_json` **including label text**".
    """
    payload = [
        {
            "attribute_key": value.attribute_key,
            "code": value.code,
            "label": dict(value.label),
        }
        for value in sorted(values, key=lambda value: value.code)
    ]
    return json.dumps(payload, **_JSON_KWARGS)  # type: ignore[arg-type]


def snapshot_from_json(payload: str) -> tuple[DomainCodeValue, ...]:
    """The exact inverse — what I1's `{{feature_block}}` and I3's
    `parse_output(enum_codelists=…)` read the snapshot back with."""
    raw: list[dict[str, Any]] = json.loads(payload)
    return tuple(
        DomainCodeValue(
            attribute_key=str(item["attribute_key"]),
            code=str(item["code"]),
            label={str(k): str(v) for k, v in dict(item["label"]).items()},
        )
        for item in raw
    )


class EvaluationService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        model_catalog: ModelCatalog,
        endpoint_prober: EndpointProber,
        gpu_probe: GpuProbe,
        clock: Clock,
        ids: IdFactory,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._model_catalog = model_catalog
        self._endpoint_prober = endpoint_prober
        self._gpu_probe = gpu_probe
        self._clock = clock
        self._ids = ids
        self._settings = settings

    async def list_evaluations(self) -> list[EvaluationDraftView]:
        """Every evaluation, drafts included, newest first."""
        async with self._session_factory() as session:
            rows = await EvaluationRepository(session).list_all()
            return [_draft_view(row) for row in rows]

    async def get(
        self,
        evaluation_id: EvaluationId,
        *,
        connection: ConnectionView | None = None,
        models: Sequence[ModelChoiceView] | None = None,
    ) -> EvaluationView:
        """One whole Evaluation screen: setup, models, connection, progress,
        runs and provenance.

        `connection` and `models` let a caller that **already holds** the
        endpoint's state hand it back instead of having it re-probed. That is
        not an optimisation, it is plan-phase-3.md C3 expressed at the seam:
        reachability is re-checked on view load and when the settings dialog's
        refresh is pressed, *never on a timer* — and the progress poll is a
        timer. Left out, both are read, which is what a view load does.

        `models is not None` rather than a truthiness test: an unreachable
        endpoint's catalogue is legitimately `()`, and treating that as
        "nothing supplied" would put the probe back on the timer for exactly
        the endpoint least able to answer it.

        :raises NotFoundError: no such evaluation.
        """
        connection = connection if connection is not None else await self.connection_status()
        models = models if models is not None else await self._model_choices(connection)
        async with self._session_factory() as session:
            evaluation = await self._require(session, evaluation_id)
            return await self._view(session, evaluation, connection, models)

    async def save_draft(
        self,
        *,
        name: str,
        corpus_id: CorpusId,
        feature_config_id: FeatureConfigId,
    ) -> EvaluationDraftView:
        """Create an unlaunched evaluation with the design's defaults —
        the active template, temperature 0.0, seed 42, size `full`."""
        async with session_scope(self._session_factory) as session:
            await self._require_corpus(session, corpus_id)
            await self._require_config(session, feature_config_id)
            active = await PromptRepository(session).get_active()
            evaluation = Evaluation(
                id=EvaluationId(self._ids.new_id()),
                name=name,
                corpus_id=corpus_id,
                feature_config_id=feature_config_id,
                created_at=self._clock.now(),
                # The active version is the one new evaluations default to
                # (§15.1). `None` before anything has ever been activated —
                # a draft may exist before a template does.
                prompt_template_id=(None if active is None else PromptTemplateId(active.id)),
                prompt_language=_DEFAULT_LANGUAGE,
                temperature=_DEFAULT_TEMPERATURE,
                seed=_DEFAULT_SEED,
                size=EvaluationSize.FULL,
                selected_models_json=None,
            )
            await EvaluationRepository(session).add_draft(evaluation)
            return _draft_view(evaluation)

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

        A model the host is *known* not to have the VRAM for cannot be
        selected (`FeatureValidationError`): the design disables the row, and
        the service refuses it too, so a request that bypasses the view cannot
        queue a run that will never load. "Unknown" is never "does not fit" —
        with no GPU answer, and with an endpoint that cannot be asked, nothing
        is refused (sw-design.md §15.6).

        :raises EvaluationLockedError: `launched_at` is set; nothing changed.
        :raises FeatureValidationError: a selected model exceeds the host's
            VRAM; nothing changed.
        :raises NotFoundError: no such evaluation, or a cited row is missing.
        """
        async with session_scope(self._session_factory) as session:
            evaluation = await self._editable(session, evaluation_id)
            if name is not None:
                evaluation.name = name
            if corpus_id is not None:
                await self._require_corpus(session, corpus_id)
                evaluation.corpus_id = corpus_id
            if feature_config_id is not None:
                await self._require_config(session, feature_config_id)
                evaluation.feature_config_id = feature_config_id
            if prompt_template_id is not None:
                await self._require_template(session, prompt_template_id)
                evaluation.prompt_template_id = prompt_template_id
            if prompt_language is not None:
                evaluation.prompt_language = prompt_language
            if temperature is not None:
                evaluation.temperature = temperature
            if seed is not None:
                evaluation.seed = seed
            if size is not None:
                evaluation.size = size
            if selected_models is not None:
                await self._reject_infeasible(selected_models)
                evaluation.selected_models_json = json.dumps(list(selected_models), **_JSON_KWARGS)  # type: ignore[arg-type]
            await session.flush()
            return _draft_view(evaluation)

    async def list_models(self, evaluation_id: EvaluationId | None = None) -> list[ModelChoiceView]:
        """The endpoint's catalogue, each row judged against the host's VRAM.

        An **unreachable endpoint yields an empty list and a reason** through
        `connection_status()`, never an exception into the UI (§15.5). An
        unknown VRAM yields `fits_vram=None` — every model stays selectable,
        because "unknown" is not "does not fit" (§15.6).
        """
        selected: tuple[str, ...] = ()
        if evaluation_id is not None:
            async with self._session_factory() as session:
                evaluation = await self._require(session, evaluation_id)
                selected = _selected_models(evaluation)
        return list(await self._model_choices(selected=selected))

    async def catalogue(self) -> CatalogueView:
        """The endpoint's models and its connection line, **without an
        evaluation**.

        The Models card needs two facts that belong to two different owners:
        what the endpoint offers (the endpoint's) and which of them are ticked
        (the evaluation's). `get()` serves the card once an evaluation exists;
        this serves it before one does — on a fresh install, or any time
        before "Save draft" — where the catalogue is just as knowable and used
        to render as empty.

        **One `reachable()` and one `models()`**, because the connection is
        passed into `_model_choices` rather than re-fetched: `list_models()`
        asks for its own, so `connection_status()` + `list_models()` would
        cost three round trips for two facts. This mirrors `get()`, which has
        always done it the cheap way.
        """
        connection = await self.connection_status()
        return CatalogueView(connection=connection, models=await self._model_choices(connection))

    async def connection_status(self) -> ConnectionView:
        """Endpoint, timeout, reachability and the probe's GPU answer.

        Re-checked on view load and when the settings dialog's "refresh" is
        pressed — **never on a timer** (plan-phase-3.md C3).
        """
        # One `reachable()` per call, and this method is only ever called from
        # a view load, a refresh or a launch. `StaticModelCatalog.
        # reachable_calls` is what pins that in the tests.
        status = await self._model_catalog.reachable()
        gpu = self._gpu_probe.describe()
        return ConnectionView(
            endpoint=self._settings.llm_base_url,
            status=status,
            timeout_s=self._settings.llm_timeout_s,
            reason=None if status is EndpointStatus.REACHABLE else _CONNECTION_REASONS[status],
            gpu_name=None if gpu is None else gpu.name,
            gpu_vram_bytes=None if gpu is None else gpu.total_vram_bytes,
        )

    async def test_connection(
        self, endpoint: str, timeout_s: int | None = None
    ) -> ConnectionProbeView:
        """Probe an endpoint the analyst **typed**, and say why it did not answer.

        Not the same question as `connection_status()`. That one asks about
        the configured endpoint and answers in one bit for the Models card;
        this one asks about a value that is not configured anywhere yet, which
        is the only value worth testing while you are still setting Ollama up.
        Nothing here is persisted — `RA2_LLM_BASE_URL` is still the one source
        of the endpoint the app actually uses.

        `timeout_s` defaults to the configured timeout; the prober lowers it
        further to its own cap, and the bound it settled on comes back on the
        view so the dialog can name it.

        **Never raises**, including for a non-loopback host: the prober refuses
        that before opening a socket and returns
        `ProbeCode.REFUSED_NOT_LOOPBACK`. An exception here would become a
        toast, and the design does not have one.
        """
        requested = self._settings.llm_timeout_s if timeout_s is None else timeout_s
        result = await self._endpoint_prober.probe(endpoint, timeout_s=requested)
        return ConnectionProbeView(
            endpoint=endpoint,
            code=result.code,
            detail=result.detail,
            latency_ms=result.latency_ms,
            model_count=result.model_count,
            http_status=result.http_status,
            probe_timeout_s=min(requested, PROBE_TIMEOUT_S),
        )

    async def record_scope(self, evaluation_id: EvaluationId) -> tuple[RecordId, ...]:
        """The record ids this evaluation runs over, in scope order.

        **Deterministic**: `DEV` takes the first `RA2_DEV_RECORD_MAX` records
        **by id** and `FULL` takes every record, both ordered by id (§15 F9).
        "A re-run is a check, not a new sample" is false the moment the
        selection is random — the seed fixes what the model does with what it
        sees, and determinism has to cover what it is *shown* too.

        The same scope `ExtractionRepository.pending_record_ids(limit=…)`
        filters the resume set inside, which is why the cap is expressed as a
        `limit` on an id-ordered query in both places rather than as a set of
        ids one of them remembers.

        :raises NotFoundError: no such evaluation.
        """
        async with self._session_factory() as session:
            evaluation = await self._require(session, evaluation_id)
            return await self._scope(session, evaluation)

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
            message and 422 is exactly its status. Nothing is created. The
            same type carries mvp-spec.md §7's evaluation-setup gates (an
            `enum` feature with no code table, or no label in the evaluation's
            prompt language) and the launch's own preconditions — a template,
            at least one model, and a reachable endpoint to pin each model's
            digest against.
        :raises EvaluationLockedError: already launched.
        :raises NotFoundError: no such evaluation.
        """
        # Asked before the transaction opens, not inside it: it is a socket
        # call, and nothing holds a transaction open across one (§15.3).
        connection = await self.connection_status()
        catalogue = await self._model_catalog.models()
        models = self._judge(catalogue, connection)

        async with session_scope(self._session_factory) as session:
            evaluation = await self._editable(session, evaluation_id)
            corpus = await self._require_corpus(session, CorpusId(evaluation.corpus_id))
            config = await self._require_config(
                session, FeatureConfigId(evaluation.feature_config_id)
            )
            template = await self._launch_template(session, evaluation)
            chosen = self._launch_models(evaluation, connection, models)

            if config.frozen_at is None:
                # Raised inside `session_scope`, which rolls back: an
                # unfrozen config leaves no `evaluation_feature`, no `run`
                # and no `launched_at` behind.
                raise FeatureValidationError(
                    [EVAL_ERROR_CONFIG_NOT_FROZEN.format(name=config.name)]
                )

            features = await FeatureRepository(session).list_features(FeatureConfigId(config.id))
            snapshots = await self._snapshots(session, evaluation, features)

            launched_at = self._clock.now()
            await EvaluationRepository(session).launch(
                evaluation,
                features=[
                    EvaluationFeature(
                        evaluation_id=EvaluationId(evaluation.id),
                        feature_id=FeatureId(feature.id),
                        enum_codelist_json=snapshots[feature.id],
                        fingerprint=compute_fingerprint(
                            _fingerprint_input(feature, snapshots[feature.id])
                        ),
                    )
                    for feature in features
                ],
                runs=[self._new_run(evaluation, template, model, connection) for model in chosen],
                is_dev=await self._is_dev(session, evaluation, corpus),
                launched_at=launched_at,
            )
            return await self._view(session, evaluation, connection, models)

    # --- internals: lookups -------------------------------------------------

    async def _require(self, session: AsyncSession, evaluation_id: EvaluationId) -> Evaluation:
        evaluation = await EvaluationRepository(session).get(evaluation_id)
        if evaluation is None:
            raise NotFoundError(_EVALUATION_KIND, evaluation_id)
        return evaluation

    async def _editable(self, session: AsyncSession, evaluation_id: EvaluationId) -> Evaluation:
        """The evaluation, or the refusal every mutating path shares.

        `launched_at` is the whole lock: a draft is a saved setup, an
        evaluation is a pinned one (§15.2).
        """
        evaluation = await self._require(session, evaluation_id)
        if evaluation.launched_at is not None:
            raise EvaluationLockedError(evaluation.id)
        return evaluation

    async def _require_corpus(self, session: AsyncSession, corpus_id: CorpusId) -> Corpus:
        corpus = await CorpusRepository(session).get(corpus_id)
        if corpus is None:
            raise NotFoundError(_CORPUS_KIND, corpus_id)
        return corpus

    async def _require_config(
        self, session: AsyncSession, feature_config_id: FeatureConfigId
    ) -> FeatureConfig:
        config = await FeatureRepository(session).get_config(feature_config_id)
        if config is None:
            raise NotFoundError(_CONFIG_KIND, feature_config_id)
        return config

    async def _require_template(
        self, session: AsyncSession, prompt_template_id: PromptTemplateId
    ) -> PromptTemplate:
        template = await PromptRepository(session).get(prompt_template_id)
        if template is None:
            raise NotFoundError(_TEMPLATE_KIND, prompt_template_id)
        return template

    async def _launch_template(
        self, session: AsyncSession, evaluation: Evaluation
    ) -> PromptTemplate:
        """§15.2: the column is nullable so a draft can exist before any
        template does; **the launch transaction requires one**."""
        if evaluation.prompt_template_id is None:
            raise FeatureValidationError([EVAL_ERROR_NO_TEMPLATE])
        return await self._require_template(
            session, PromptTemplateId(evaluation.prompt_template_id)
        )

    # --- internals: models and VRAM ----------------------------------------

    def _judge(
        self, catalogue: Sequence[ModelInfo], connection: ConnectionView
    ) -> tuple[ModelChoiceView, ...]:
        """One `ModelChoiceView` per catalogue entry, VRAM judged.

        `fits_vram` is `None` whenever the host's VRAM is unknown — no NVIDIA
        GPU, no NVML, no override. That is not a failure: every model stays
        selectable and the design's disabled row simply does not occur
        (§15.6).
        """
        vram = connection.gpu_vram_bytes
        return tuple(
            ModelChoiceView(
                tag=model.tag,
                digest=model.digest,
                size_bytes=model.size_bytes,
                fits_vram=None if vram is None else model.size_bytes <= vram,
            )
            for model in catalogue
        )

    async def _model_choices(
        self,
        connection: ConnectionView | None = None,
        *,
        selected: Sequence[str] = (),
    ) -> tuple[ModelChoiceView, ...]:
        """The catalogue, judged and flagged. An unreachable endpoint returns
        **an empty tuple**: `ModelCatalog.models()` is documented to return
        `()` rather than raise, so nothing here catches anything (§15.5)."""
        connection = connection or await self.connection_status()
        catalogue = await self._model_catalog.models()
        chosen = set(selected)
        return tuple(
            ModelChoiceView(
                tag=choice.tag,
                digest=choice.digest,
                size_bytes=choice.size_bytes,
                fits_vram=choice.fits_vram,
                selected=choice.tag in chosen,
            )
            for choice in self._judge(catalogue, connection)
        )

    async def _reject_infeasible(self, tags: Sequence[str]) -> None:
        """Refuse a selection of a model the host is *known* not to fit.

        Only a model the endpoint actually offers is judged: with an
        unreachable endpoint the catalogue is empty and nothing is refused,
        because that is ignorance, not a verdict. Same for an unknown VRAM.
        """
        connection = await self.connection_status()
        choices = {choice.tag: choice for choice in await self._model_choices(connection)}
        # Named `validation_errors`, not `errors`: `tests/unit/parsing/
        # test_no_lenient_decoding.py` bans the token `errors =` anywhere
        # under `ra2/` (N4's strictest form — the keyword must not appear at
        # all), and this is also what `FeatureValidationError` calls the
        # sequence it carries.
        validation_errors: list[str] = [
            _exceeds_vram(choices[tag], connection.gpu_vram_bytes)
            for tag in tags
            if tag in choices and choices[tag].fits_vram is False
        ]
        if validation_errors:
            raise FeatureValidationError(validation_errors)

    def _launch_models(
        self,
        evaluation: Evaluation,
        connection: ConnectionView,
        models: Sequence[ModelChoiceView],
    ) -> tuple[ModelChoiceView, ...]:
        """The selected models, resolved to catalogue rows with digests.

        Every refusal here is a `FeatureValidationError` raised **before**
        anything is written: no selection, an endpoint that cannot be asked
        for a digest (mvp-spec.md §19.8 wants the digest, not just the tag),
        a tag the endpoint no longer offers, or a model the host is known not
        to fit.
        """
        tags = _selected_models(evaluation)
        if not tags:
            raise FeatureValidationError([EVAL_ERROR_NO_MODELS_SELECTED])
        if not connection.is_reachable:
            raise FeatureValidationError(
                [EVAL_ERROR_ENDPOINT_UNREACHABLE.format(endpoint=connection.endpoint)]
            )
        by_tag = {choice.tag: choice for choice in models}
        validation_errors: list[str] = []
        chosen: list[ModelChoiceView] = []
        for tag in tags:
            choice = by_tag.get(tag)
            if choice is None:
                validation_errors.append(EVAL_ERROR_MODEL_NOT_AVAILABLE.format(tag=tag))
                continue
            if choice.fits_vram is False:
                validation_errors.append(_exceeds_vram(choice, connection.gpu_vram_bytes))
                continue
            chosen.append(choice)
        if validation_errors:
            raise FeatureValidationError(validation_errors)
        return tuple(chosen)

    def _new_run(
        self,
        evaluation: Evaluation,
        template: PromptTemplate,
        model: ModelChoiceView,
        connection: ConnectionView,
    ) -> Run:
        """One `queued` run, **provenance and all** (mvp-spec.md §19.8).

        Written now rather than when the worker picks the run up: a run that
        dies mid-corpus — or never starts — is still a reproducible run
        (§15.4). `platform.platform()` is a stdlib call, not a shell-out (N3).
        """
        return Run(
            id=RunId(self._ids.new_id()),
            evaluation_id=EvaluationId(evaluation.id),
            model_name=model.tag,
            model_digest=model.digest,
            prompt_template_version=template.version,
            prompt_template_id=PromptTemplateId(template.id),
            prompt_template_fingerprint=template.fingerprint,
            temperature=evaluation.temperature,
            seed=evaluation.seed,
            status=RunStatus.QUEUED,
            host_platform=platform.platform()[:200],
            gpu_name=connection.gpu_name,
            llm_endpoint=connection.endpoint,
        )

    # --- internals: the snapshot -------------------------------------------

    async def _snapshots(
        self,
        session: AsyncSession,
        evaluation: Evaluation,
        features: Sequence[Feature],
    ) -> dict[str, str | None]:
        """`feature id -> enum_codelist_json`, from the corpus's **current**
        `column_mapping` generation (mvp-spec.md §8.5, §14.2).

        A copy, not a live reference: once written inside the launch
        transaction the row is never updated, so re-pointing the mapping or
        importing a new code table afterwards cannot move an already-launched
        evaluation's fingerprints (mvp-spec.md §19.3, §19.8).

        Two exemptions, the same two `feature_service._validation_errors`
        makes: a `DERIVED`-grain enum feature's codes are its derivation's
        `ordered_codes`, never a column lookup, and an `EXPLORATORY` feature
        has no ground truth to match at all.
        """
        repo = CodelistRepository(session)
        corpus_id = CorpusId(evaluation.corpus_id)
        language = evaluation.prompt_language
        snapshots: dict[str, str | None] = {}
        validation_errors: list[str] = []
        for feature in features:
            snapshots[feature.id] = None
            if (
                Kind(feature.kind) is Kind.EXPLORATORY
                or not requires_codelist(ValueType(feature.value_type))
                or Grain(feature.grain) is Grain.DERIVED
            ):
                continue
            column = feature.source_column
            if not column:
                validation_errors.append(
                    EVAL_ERROR_ENUM_NO_CODELIST.format(key=feature.key, column="(none)")
                )
                continue
            mapping = await repo.get_mapping(corpus_id, column)
            attribute = (
                None
                if mapping is None
                else await repo.get_attribute(CodeAttributeId(mapping.code_attribute_id))
            )
            if attribute is None or not attribute.values:
                validation_errors.append(
                    EVAL_ERROR_ENUM_NO_CODELIST.format(key=feature.key, column=column)
                )
                continue
            values = tuple(
                DomainCodeValue(
                    attribute_key=attribute.key,
                    code=value.code,
                    label=json.loads(value.label_json),
                )
                for value in attribute.values
            )
            # mvp-spec.md §7's known gap (`main_cause*` has no `it`) is an
            # attribute with **no** labels in that language at all — and "not
            # a fallback to another language" makes that a blocking error.
            # One code missing one label is a different thing: the code table
            # is usable and `render_feature_block` already handles the hole
            # (tests/fixtures/prompts/hazards/p06), so blocking on it would
            # refuse a launch mvp-spec.md §7 does not refuse.
            if not any(language in value.label for value in values):
                validation_errors.append(
                    EVAL_ERROR_ENUM_NO_LABEL_IN_LANGUAGE.format(
                        key=feature.key, column=column, language=language
                    )
                )
                continue
            snapshots[feature.id] = snapshot_to_json(values)
        if validation_errors:
            raise FeatureValidationError(validation_errors)
        return snapshots

    # --- internals: the dev sample -----------------------------------------

    async def _scope(self, session: AsyncSession, evaluation: Evaluation) -> tuple[RecordId, ...]:
        """The first `RA2_DEV_RECORD_MAX` record ids by id, or all of them."""
        stmt = select(Record.id).where(Record.corpus_id == evaluation.corpus_id).order_by(Record.id)
        if EvaluationSize(evaluation.size) is EvaluationSize.DEV:
            stmt = stmt.limit(self._settings.dev_record_max)
        rows = await session.scalars(stmt)
        return tuple(RecordId(row) for row in rows.all())

    def _scope_size(self, corpus: Corpus, size: EvaluationSize) -> int:
        """How many records this launch will actually visit."""
        if size is EvaluationSize.DEV:
            return min(corpus.record_count, self._settings.dev_record_max)
        return corpus.record_count

    async def _is_dev(self, session: AsyncSession, evaluation: Evaluation, corpus: Corpus) -> bool:
        """mvp-spec.md §9 — "a run over a corpus below the evaluation floor is
        marked **dev**", and the design's step 6 offers `Dev · N records` as
        the other way to land there.

        One rule covers both: the scope this launch will visit, measured
        against `RA2_EVAL_RECORD_MIN`. A `DEV` size is capped at
        `RA2_DEV_RECORD_MAX` and so is always below the floor; a `FULL` size
        over a 40-record corpus is below it too, and mvp-spec.md §9 wants that
        marked a smoke test exactly the same way.
        """
        return (
            self._scope_size(corpus, EvaluationSize(evaluation.size))
            < self._settings.eval_record_min
        )

    # --- internals: the read model -----------------------------------------

    async def _view(
        self,
        session: AsyncSession,
        evaluation: Evaluation,
        connection: ConnectionView,
        models: Sequence[ModelChoiceView],
        *,
        page_size: int = 25,
    ) -> EvaluationView:
        """The whole screen, read back through the repositories."""
        selected = _selected_models(evaluation)
        corpus = await self._require_corpus(session, CorpusId(evaluation.corpus_id))
        config = await self._require_config(session, FeatureConfigId(evaluation.feature_config_id))
        runs = await RunRepository(session).list_by_evaluation(EvaluationId(evaluation.id))
        total = self._scope_size(corpus, EvaluationSize(evaluation.size))
        progress = [await self._progress(session, run, total) for run in runs]
        ordinals = run_ordinals(runs)
        run_views = [
            RunView(
                run_id=RunId(run.id),
                ordinal=ordinals[run.id],
                evaluation_id=EvaluationId(evaluation.id),
                model_tag=run.model_name,
                model_digest=run.model_digest,
                records_done=card.done,
                started_at=run.started_at,
                status=RunStatus(run.status),
                is_dev=evaluation.is_dev,
                error=run.error,
            )
            for run, card in zip(runs, progress, strict=True)
        ]
        return EvaluationView(
            draft=_draft_view(evaluation),
            connection=connection,
            models=tuple(
                ModelChoiceView(
                    tag=choice.tag,
                    digest=choice.digest,
                    size_bytes=choice.size_bytes,
                    fits_vram=choice.fits_vram,
                    selected=choice.tag in set(selected),
                )
                for choice in models
            ),
            progress=tuple(progress),
            runs=Page(
                items=tuple(run_views),
                total=len(run_views),
                page=1,
                page_size=page_size,
                sort_key="started_at",
                sort_dir=SortDir.DESC,
            ),
            provenance=await self._provenance(session, evaluation, corpus, runs),
            feature_config_label=f"{config.name} · v{config.version}",
            corpus_label=f"{corpus.name} · v{corpus.version}",
            corpus_record_count=corpus.record_count,
            # The design's "Dev · 40 records" reads its number from config,
            # never from a literal.
            dev_record_max=self._settings.dev_record_max,
        )

    async def _progress(self, session: AsyncSession, run: Run, total: int) -> RunProgressView:
        """One progress card. Every count is **derived from committed
        `extraction` rows** (§15 F6) — there is no counter column to read."""
        repo = RunRepository(session)
        run_id = RunId(run.id)
        done = await repo.count_done(run_id)
        rows = await session.execute(
            select(Extraction.latency_ms, Extraction.prompt_tokens).where(
                Extraction.run_id == run_id
            )
        )
        latencies = []
        prompt_tokens = 0
        for latency, tokens in rows.all():
            if latency is not None:
                latencies.append(int(latency))
            prompt_tokens += int(tokens or 0)
        elapsed_ms = _elapsed_ms(run, self._clock.now())
        return RunProgressView(
            run_id=run_id,
            model_tag=run.model_name,
            status=RunStatus(run.status),
            done=done,
            total=total,
            parse_failures=await repo.count_parse_failures(run_id),
            retries=await repo.sum_retries(run_id),
            median_latency_ms=None if not latencies else int(statistics.median(latencies)),
            prompt_tokens=prompt_tokens,
            elapsed_ms=elapsed_ms,
            eta_ms=_eta_ms(done, total, elapsed_ms),
        )

    async def _provenance(
        self,
        session: AsyncSession,
        evaluation: Evaluation,
        corpus: Corpus,
        runs: Sequence[Run],
    ) -> ProvenanceView | None:
        """ "Every run's record alone is sufficient to reproduce it"
        (mvp-spec.md §19.8) — rendered for the most recent run.

        `feature_fingerprints` comes from `evaluation_feature`: the real
        fingerprints resolved in the launch transaction, never a draft
        preview. Re-queried rather than read off `evaluation.features`,
        because `EvaluationRepository.get()` eager-loaded that collection
        *before* `launch()` wrote into it — inside the launch transaction the
        relationship is still the empty list it was loaded as, while this
        query sees the flush.
        """
        if not runs:
            return None
        run = runs[0]
        snapshots = await _snapshot_rows(session, EvaluationId(evaluation.id))
        keys = await _feature_keys(session, [row.feature_id for row in snapshots])
        return ProvenanceView(
            model_name=run.model_name,
            model_digest=run.model_digest,
            prompt_template_version=run.prompt_template_version,
            prompt_template_fingerprint=run.prompt_template_fingerprint,
            temperature=run.temperature,
            seed=run.seed,
            feature_config_id=FeatureConfigId(evaluation.feature_config_id),
            feature_fingerprints={
                keys[snapshot.feature_id]: snapshot.fingerprint
                for snapshot in snapshots
                if snapshot.feature_id in keys
            },
            corpus_id=CorpusId(corpus.id),
            corpus_version=corpus.version,
            host_platform=run.host_platform,
            gpu_name=run.gpu_name,
            llm_endpoint=run.llm_endpoint,
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _fingerprint_input(feature: Feature, enum_codelist_json: str | None) -> FingerprintInput:
    """mvp-spec.md §8.5's eight fields, with **this evaluation's** snapshot.

    `feature_service._fingerprint_input` assembles the same eight from the row
    alone, where `enum_codelist_json` is always `None` — which is exactly why
    the draft-time preview and an evaluation's real fingerprint differ for an
    enum feature and agree for every other kind (phase 2 Q3).
    """
    return FingerprintInput(
        kind=Kind(feature.kind),
        grain=Grain(feature.grain),
        source_column=feature.source_column,
        derivation_json=feature.derivation_json,
        value_type=ValueType(feature.value_type),
        matching_rule_json=feature.matching_rule,
        enum_codelist_json=enum_codelist_json,
        description=feature.description,
    )


def _selected_models(evaluation: Evaluation) -> tuple[str, ...]:
    """Step 4, deserialised. `None` and `[]` both mean "nothing selected"."""
    if not evaluation.selected_models_json:
        return ()
    return tuple(str(tag) for tag in json.loads(evaluation.selected_models_json))


def _draft_view(evaluation: Evaluation) -> EvaluationDraftView:
    """One row's setup. `size` is coerced at this read boundary: it is mapped
    onto `String`, so SQLAlchemy hands back a plain `str` after a round trip
    (the convention `_feature_view` follows)."""
    return EvaluationDraftView(
        evaluation_id=EvaluationId(evaluation.id),
        name=evaluation.name,
        corpus_id=CorpusId(evaluation.corpus_id),
        feature_config_id=FeatureConfigId(evaluation.feature_config_id),
        prompt_template_id=(
            None
            if evaluation.prompt_template_id is None
            else PromptTemplateId(evaluation.prompt_template_id)
        ),
        prompt_language=evaluation.prompt_language,
        temperature=evaluation.temperature,
        seed=evaluation.seed,
        size=EvaluationSize(evaluation.size),
        selected_models=_selected_models(evaluation),
        launched_at=evaluation.launched_at,
    )


def _exceeds_vram(choice: ModelChoiceView, vram_bytes: int | None) -> str:
    """The message behind a `fits_vram is False` verdict.

    That verdict is unreachable with an unknown VRAM — `_judge` leaves
    `fits_vram` at `None` there — so `vram_bytes` is never `None` in practice;
    `or 0` is the total-order fallback rather than an assertion that would
    turn a message into a crash.
    """
    return EVAL_ERROR_MODEL_EXCEEDS_VRAM.format(
        tag=choice.tag,
        size_gb=choice.size_bytes / _BYTES_PER_GB,
        vram_gb=(vram_bytes or 0) / _BYTES_PER_GB,
    )


def _elapsed_ms(run: Run, now: datetime) -> int | None:
    """Wall time since the run started, or its full duration once finished."""
    if run.started_at is None:
        return None
    end = run.finished_at or now
    return max(0, int((end - run.started_at).total_seconds() * 1000))


def _eta_ms(done: int, total: int, elapsed_ms: int | None) -> int | None:
    """Linear extrapolation from committed rows. `None` until there is one —
    an ETA from zero observations is a guess dressed as a number."""
    if elapsed_ms is None or done <= 0 or total <= done:
        return None
    return int(elapsed_ms / done * (total - done))


async def _snapshot_rows(
    session: AsyncSession, evaluation_id: EvaluationId
) -> tuple[EvaluationFeature, ...]:
    """This evaluation's `evaluation_feature` rows, ordered by feature id.

    Written once inside the launch transaction and never updated, so a plain
    ordered read is all any caller ever needs.
    """
    rows = await session.scalars(
        select(EvaluationFeature)
        .where(EvaluationFeature.evaluation_id == evaluation_id)
        .order_by(EvaluationFeature.feature_id)
    )
    return tuple(rows.all())


async def _feature_keys(session: AsyncSession, feature_ids: Sequence[str]) -> dict[str, str]:
    """`feature id -> key`, for the provenance card's fingerprint map."""
    if not feature_ids:
        return {}
    rows = await session.execute(
        select(Feature.id, Feature.key).where(Feature.id.in_(list(feature_ids)))
    )
    return {str(feature_id): str(key) for feature_id, key in rows.all()}

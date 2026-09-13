"""Fixtures for `RunService` (I3, phase 3 Wave 2).

Same shape as `../corpus/conftest.py`: a real migrated temp-file SQLite
database from `tests/backend/conftest.py`, a frozen clock, seeded ids, and the
substitutes the worker is built against.

Two of those substitutes matter:

- **`StubPromptResolver`** — I1 implements the real `PromptResolver` in this
  same wave (`services/protocols.py`), and the seam exists so neither agent
  waits. These tests assert what the worker *does with* a resolved prompt,
  never how it was resolved. The stub still reads its record **through the
  session it is handed**, because that is the half of the protocol worth
  exercising: a resolver that opened its own session would read outside the
  worker's transaction.
- **`FakeLLMClient`** (`tests/fixtures/fake_llm.py`, H4) — `failures={i: exc}`
  is how a run is killed mid-corpus, and the default exception is the one the
  real adapter raises, so the worker's real handling is exercised rather than
  a stand-in.

Nothing here seeds through `EvaluationService.launch`: I2 builds that in this
same wave. The rows are written directly, which is also what lets a test put
an evaluation into states a launch would never produce (a run whose
`host_platform` is blank, for one — that is what proves provenance is written
at run *start*).
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import FakeLLMClient, StaticModelCatalog

from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    FeatureConfigId,
    FeatureId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.domain.llm import LLMClient
from ra2.domain.prompt import ResolvedPrompt
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuInfo, StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.infra.tasks import InlineTaskRunner
from ra2.main import create_app
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
from ra2.persistence.session import create_engine, create_session_factory
from ra2.services.feature_service import matching_rule_json
from ra2.services.run_service import RunService

#: The design's host, so a `gpu_name` assertion is the same on a laptop with
#: no GPU and on the target machine.
FIXTURE_GPU = GpuInfo(name="RTX 4090", total_vram_bytes=24_000_000_000)

#: The two features every seeded evaluation asks for: one `enum` with a
#: codelist snapshot, one free text. Both are needed — the enum exercises
#: `parse_output`'s codelist check and the free text exercises a value that
#: cannot be checked against anything.
WEATHER = "weather"
NOTE = "note"
FEATURE_KEYS: tuple[str, ...] = (WEATHER, NOTE)

#: The snapshot `evaluation_feature.enum_codelist_json` carries: `{code:
#: label}`, the shape `FingerprintInput.enum_codelist_json` hashes.
WEATHER_CODELIST = '{"01":"Regen","02":"Schnee"}'

DEFAULT_MODEL = "llama3.1:8b-instruct-q8_0"


def answer(*, weather: str = "01", note: str = "nichts", evidence: str = "es regnete") -> str:
    """One well-formed mvp-spec.md §10.3 response body."""
    return json.dumps(
        {
            "features": {
                WEATHER: {"value": weather, "present": True, "evidence": evidence},
                NOTE: {"value": note, "present": True, "evidence": evidence},
            },
            "entities": [{"kind": "vehicle", "ref": "B1", "attributes": {"type": "car"}}],
        }
    )


@dataclass(frozen=True, slots=True)
class SeededEvaluation:
    """What one seeded evaluation is, in the ids a test needs to assert on."""

    corpus_id: CorpusId
    evaluation_id: EvaluationId
    #: In `id` order — which is `pending_record_ids`' order and the dev
    #: sample's order (§15 F9).
    record_ids: tuple[RecordId, ...]
    #: `unfall_uid` per record, in the same order. Each is unique in the
    #: resolved prompt, so `FakeLLMClient(responses={uid: body})` scripts one
    #: body per record without knowing the call order.
    markers: tuple[str, ...]
    feature_ids: dict[str, FeatureId]
    run_ids: tuple[RunId, ...]

    @property
    def run_id(self) -> RunId:
        return self.run_ids[0]


class StubPromptResolver:
    """A `PromptResolver` that renders the record's own narrative.

    Records every `(evaluation_id, record_id)` it was asked for, so "the
    prompt was resolved once per record" is assertable.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[EvaluationId, RecordId]] = []

    async def resolve(
        self,
        session: AsyncSession,
        evaluation_id: EvaluationId,
        record_id: RecordId,
    ) -> ResolvedPrompt:
        self.calls.append((evaluation_id, record_id))
        record = await session.get(Record, record_id)
        assert record is not None, f"resolver handed an unknown record: {record_id}"
        text = f"[{record.unfall_uid}] {record.text_raw}"
        return ResolvedPrompt(text=text, token_estimate=len(text) // 4, slots_used=())


class RecordingReporter:
    """A `ProgressReporter` that keeps every report, in order."""

    def __init__(self) -> None:
        self.reports: list[tuple[int, int, str]] = []

    def report(self, done: int, total: int, message: str = "") -> None:
        self.reports.append((done, total, message))


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def ids() -> SeededFactory:
    return SeededFactory(seed=31337)


@pytest.fixture
def gpu() -> StaticGpuProbe:
    return StaticGpuProbe(FIXTURE_GPU)


@pytest.fixture
def resolver() -> StubPromptResolver:
    return StubPromptResolver()


@pytest.fixture
def reporter() -> RecordingReporter:
    return RecordingReporter()


@pytest.fixture
def task_runner(ids: SeededFactory) -> InlineTaskRunner:
    """Runs submitted work to completion before `submit()` returns, so a
    backend test needs no polling loop."""
    return InlineTaskRunner(ids)


@pytest.fixture
def make_run_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    resolver: StubPromptResolver,
    gpu: StaticGpuProbe,
    clock: FrozenClock,
    ids: SeededFactory,
    task_runner: InlineTaskRunner,
    backend_settings: Settings,
) -> Callable[..., RunService]:
    """Build a `RunService` over the migrated temp-file database."""

    def _make(
        llm_client: LLMClient,
        *,
        settings: Settings | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        id_factory: SeededFactory | None = None,
    ) -> RunService:
        return RunService(
            session_factory=session_factory or db_session_factory,
            llm_client=llm_client,
            prompt_resolver=resolver,
            gpu_probe=gpu,
            task_runner=task_runner,
            clock=clock,
            ids=id_factory or ids,
            settings=settings or backend_settings,
        )

    return _make


@pytest.fixture
def run_service(make_run_service: Callable[..., RunService], fake_llm: FakeLLMClient) -> RunService:
    """The common case: a client that answers `{}` to everything."""
    return make_run_service(fake_llm)


@pytest.fixture
def dev_settings(backend_settings: Settings) -> Settings:
    """`RA2_DEV_RECORD_MAX = 2` against the same database, so a dev run's
    first-N-by-id scope is two records rather than fifty."""
    return Settings(data_dir=backend_settings.data_dir, dev_record_max=2, _env_file=None)


@pytest_asyncio.fixture
async def build_app(
    run_upgrade_head: Settings,
    resolver: StubPromptResolver,
    gpu: StaticGpuProbe,
) -> AsyncIterator[Callable[..., FastAPI]]:
    """Build a whole app over the migrated database — one per "process".

    The resume criterion is about a **second process** reading the first's
    database: a fresh `create_app()` gives a fresh engine, a fresh
    `TaskRunner` and — the one that decides the answer — a `RunService` whose
    in-memory "runs I am executing" set is empty, which is how a run left
    `running` by a dead process is recognised as interrupted rather than live.

    `create_app()` is frozen and takes no `prompt_resolver` keyword (the seam
    is satisfied structurally by `prompt_service`, which I1 is implementing in
    this same wave), so the resolver is substituted on the built service here.
    That is the shim CLAUDE.md's ownership rule asks for instead of editing a
    frozen file, and it lives in this test package only.
    """
    built: list[FastAPI] = []

    def _build(
        *, llm_client: LLMClient, settings: Settings | None = None, seed: int = 0
    ) -> FastAPI:
        app = create_app(
            settings=settings or run_upgrade_head,
            clock=FrozenClock(),
            # A distinct id sequence per app: two processes must not mint the
            # same `extraction.id`, and `SeededFactory` is deterministic by
            # design. Production uses `Uuid7Factory`, where this is free.
            ids=SeededFactory(seed=seed),
            task_runner=InlineTaskRunner(SeededFactory(seed=seed + 1)),
            llm_client=llm_client,
            model_catalog=StaticModelCatalog(),
            gpu_probe=gpu,
            mount_ui=False,
        )
        app.state.services.run._prompt_resolver = resolver
        built.append(app)
        return app

    yield _build

    for app in built:
        await app.state.engine.dispose()


@pytest_asyncio.fixture
async def other_engine(
    run_upgrade_head: Settings,
) -> AsyncIterator[Callable[[], async_sessionmaker[AsyncSession]]]:
    """A second session factory over the **same database file**.

    What "committed" means is "visible to a connection that was not part of
    the writing transaction" — asserting durability through the same session
    factory the worker writes with would prove less than it looks like.

    Disposed at teardown: an undisposed aiosqlite engine finalises on the
    garbage collector's schedule, and `filterwarnings = ["error"]` turns that
    into a failure in whichever test happens to be running at the time.
    """
    engines: list[AsyncEngine] = []

    def _make() -> async_sessionmaker[AsyncSession]:
        engine = create_engine(run_upgrade_head.database_url)
        engines.append(engine)
        return create_session_factory(engine)

    yield _make

    for engine in engines:
        await engine.dispose()


@pytest.fixture
def seed(
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> Callable[..., Awaitable[SeededEvaluation]]:
    """Seed one corpus, one frozen feature set, one launched evaluation with
    its `evaluation_feature` snapshot, and one `queued` run per model."""

    async def _seed(
        *,
        records: int = 5,
        models: Sequence[str] = (DEFAULT_MODEL,),
        size: EvaluationSize = EvaluationSize.FULL,
        is_dev: bool = False,
        seed_value: int = 42,
        suffix: str = "a",
        snapshot: bool = True,
        codelist_json: str | None = WEATHER_CODELIST,
    ) -> SeededEvaluation:
        """:param snapshot: write the `evaluation_feature` rows the launch
            transaction would. `False` reproduces a run whose evaluation was
            never launched — the one state the worker cannot execute.
        :param codelist_json: what the snapshot carries for the `enum`
            feature. Anything but `{code: label}` means "no snapshot to check
            against", never a guess.
        """
        now = clock.now().replace(tzinfo=None)
        corpus_id = CorpusId(f"corpus-{suffix}")
        config_id = FeatureConfigId(f"config-{suffix}")
        template_id = PromptTemplateId(f"template-{suffix}")
        evaluation_id = EvaluationId(f"eval-{suffix}")
        record_ids = tuple(RecordId(f"rec-{suffix}-{n:03d}") for n in range(1, records + 1))
        markers = tuple(f"U-{suffix}-{n:03d}" for n in range(1, records + 1))
        feature_ids = {
            WEATHER: FeatureId(f"feature-{suffix}-weather"),
            NOTE: FeatureId(f"feature-{suffix}-note"),
        }

        async with db_session_factory() as session:
            session.add(
                Corpus(
                    id=corpus_id,
                    name=f"Corpus {suffix}",
                    imported_at=now,
                    version=1,
                    source_file_manifest_json="[]",
                    import_report_json="[]",
                    record_count=records,
                )
            )
            for record_id, marker in zip(record_ids, markers, strict=True):
                session.add(
                    Record(
                        id=record_id,
                        corpus_id=corpus_id,
                        unfall_uid=marker,
                        language="de",
                        language_confidence=0.99,
                        text_raw=f"Der Unfall {marker} geschah bei Regen.",
                    )
                )
            session.add(
                FeatureConfig(
                    id=config_id,
                    name=f"Set {suffix}",
                    version=1,
                    created_at=now,
                    frozen_at=now,
                )
            )
            session.add(
                Feature(
                    id=feature_ids[WEATHER],
                    feature_config_id=config_id,
                    ordinal=1,
                    key=WEATHER,
                    kind=Kind.LABELLED,
                    description="Das Wetter zum Unfallzeitpunkt.",
                    grain=Grain.ACCIDENT,
                    source_column="Wetter",
                    value_type=ValueType.ENUM,
                    matching_rule=matching_rule_json(MatchingRule(kind=MatchingRuleKind.EXACT)),
                    fingerprint="fp-weather",
                )
            )
            session.add(
                Feature(
                    id=feature_ids[NOTE],
                    feature_config_id=config_id,
                    ordinal=2,
                    key=NOTE,
                    kind=Kind.EXPLORATORY,
                    description="Freitext-Notiz.",
                    grain=Grain.ACCIDENT,
                    value_type=ValueType.FREE_TEXT,
                    matching_rule=matching_rule_json(MatchingRule(kind=MatchingRuleKind.NONE)),
                    fingerprint="fp-note",
                )
            )
            session.add(
                PromptTemplate(
                    id=template_id,
                    version=1,
                    source="{{feature_block}}\n{{narrative}}",
                    created_at=now,
                    activated_at=now,
                    fingerprint="fp-template",
                )
            )
            # Flushed in dependency order by hand: SQLAlchemy's unit of work
            # orders inserts from `relationship()` declarations, and
            # `Evaluation` declares none to `corpus`, `feature_config` or
            # `prompt_template` — only raw FKs, which it does not sort on.
            await session.flush()
            session.add(
                Evaluation(
                    id=evaluation_id,
                    name=f"Evaluation {suffix}",
                    corpus_id=corpus_id,
                    feature_config_id=config_id,
                    created_at=now,
                    is_dev=is_dev,
                    prompt_template_id=template_id,
                    prompt_language="de",
                    temperature=0.0,
                    seed=seed_value,
                    size=size,
                    selected_models_json=json.dumps(list(models)),
                    launched_at=now,
                )
            )
            await session.flush()
            if snapshot:
                for key, feature_id in feature_ids.items():
                    session.add(
                        EvaluationFeature(
                            evaluation_id=evaluation_id,
                            feature_id=feature_id,
                            enum_codelist_json=codelist_json if key == WEATHER else None,
                            fingerprint=f"fp-{key}-snapshot",
                        )
                    )
            run_ids = tuple(RunId(f"run-{suffix}-{n}") for n in range(1, len(models) + 1))
            for run_id, model in zip(run_ids, models, strict=True):
                session.add(
                    Run(
                        id=run_id,
                        evaluation_id=evaluation_id,
                        model_name=model,
                        model_digest=f"digest-{model}",
                        prompt_template_version=1,
                        prompt_template_id=template_id,
                        prompt_template_fingerprint="fp-template",
                        temperature=0.0,
                        seed=seed_value,
                        status=RunStatus.QUEUED,
                        # Blank on purpose: the host half of the provenance is
                        # the worker's to write, **at run start** (§15.4).
                        host_platform="",
                        llm_endpoint="",
                    )
                )
            await session.commit()

        return SeededEvaluation(
            corpus_id=corpus_id,
            evaluation_id=evaluation_id,
            record_ids=record_ids,
            markers=markers,
            feature_ids=feature_ids,
            run_ids=run_ids,
        )

    return _seed


@pytest.fixture
def extractions_of(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[RunId], Awaitable[list[Extraction]]]:
    """Every committed `extraction` of one run, children loaded, by record."""

    async def _read(run_id: RunId) -> list[Extraction]:
        async with db_session_factory() as session:
            rows = await session.scalars(
                select(Extraction).where(Extraction.run_id == run_id).order_by(Extraction.record_id)
            )
            found = list(rows.all())
            for row in found:
                await session.refresh(row, ["values", "entities"])
            return found

    return _read


@pytest.fixture
def run_row(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[RunId], Awaitable[Run]]:
    """One `run` row as stored — the provenance assertions read it directly,
    because a read model that dropped a field would hide exactly the bug."""

    async def _read(run_id: RunId) -> Run:
        async with db_session_factory() as session:
            run = await session.get(Run, run_id)
            assert run is not None
            return run

    return _read


@pytest.fixture
def set_run_status(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[None]]:
    """Force a run's status column, with no service in the way.

    Used to reproduce the one state no service writes: a run whose process
    died **between** the last committed extraction and any status update, so
    the row still says `running` although nothing is executing it.
    """

    async def _set(run_id: RunId, status: RunStatus, *, error: str | None = None) -> None:
        async with db_session_factory() as session:
            run = await session.get(Run, run_id)
            assert run is not None
            run.status = status
            run.error = error
            await session.commit()

    return _set


__all__ = [
    "DEFAULT_MODEL",
    "FEATURE_KEYS",
    "FIXTURE_GPU",
    "NOTE",
    "WEATHER",
    "WEATHER_CODELIST",
    "RecordingReporter",
    "SeededEvaluation",
    "StubPromptResolver",
    "answer",
]

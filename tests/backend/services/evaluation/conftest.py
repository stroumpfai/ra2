"""Fixtures for `EvaluationService` (I2, phase 3 Wave 2).

Same shape as `../feature/conftest.py`: a real migrated temp-file SQLite
database from `tests/backend/conftest.py`, a frozen clock, seeded ids, and the
two substitutes phase 3 adds — `StaticModelCatalog` for the endpoint and
`StaticGpuProbe` for the host's VRAM. **Nothing here talks to a live
endpoint**, so the whole suite passes on a machine with no GPU and nothing
listening on 11434 (plan-phase-3.md §11).

The seeding is deliberately done against the **real** collaborators rather
than doubles wherever the launch transaction reads them: a frozen
`feature_config` comes from `FeatureService.freeze()` (so the draft-time
preview fingerprint under test is the one that service actually computes), and
the code table plus its `column_mapping` are real rows (so re-pointing a
mapping after launch exercises the same write path Codelists does).
"""

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.fake_llm import (
    DEFAULT_MODELS,
    DEFAULT_OLLAMA_VERSION,
    StaticEndpointProber,
    StaticModelCatalog,
)

from ra2.domain.codelist_coverage import ColumnCoverage, CoverageStatus
from ra2.domain.feature import Grain, Kind, MatchingRule, MatchingRuleKind, ValueType
from ra2.domain.ids import (
    CodeAttributeId,
    CodeTableImportId,
    ColumnMappingId,
    CorpusId,
    PromptTemplateId,
    QualificationId,
    RecordId,
)
from ra2.domain.qualification import (
    GateResult,
    GateVerdict,
    Qualification,
    QualitySummary,
)
from ra2.infra.clock import FrozenClock
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuInfo, StaticGpuProbe
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import (
    CodeAttribute,
    CodeTableImport,
    CodeValue,
    ColumnMapping,
    Corpus,
    PromptTemplate,
    Record,
)
from ra2.persistence.repositories.qualification_repo import QualificationRepository
from ra2.persistence.session import session_scope
from ra2.services.evaluation_service import EvaluationService
from ra2.services.feature_service import FeatureService
from ra2.services.readmodels import FeatureConfigView

NOW = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)

#: The design's host: "gpu RTX 4090 24 GB". Big enough for two of
#: `DEFAULT_MODELS` and too small for the third, which is what makes a
#: `fits_vram is False` row testable without inventing a fourth model.
FIXTURE_GPU = GpuInfo(name="RTX 4090", total_vram_bytes=24_000_000_000)

#: `DEFAULT_MODELS` by role, so a test names what it means rather than a tag.
FITTING_MODEL = DEFAULT_MODELS[0].tag
SECOND_FITTING_MODEL = DEFAULT_MODELS[1].tag
#: 42.5 GB against 24 GB of VRAM.
OVERSIZED_MODEL = DEFAULT_MODELS[2].tag

#: The enum column every fixture feature maps onto.
ENUM_COLUMN = "WitterungAusw"
#: A second imported attribute, so a mapping can be **re-pointed** after a
#: launch at a code table with visibly different labels (mvp-spec.md §19.3).
ATTRIBUTE_WEATHER = "weather"
ATTRIBUTE_ROAD = "road_type"

_WEATHER_CODES: Mapping[str, Mapping[str, str]] = {
    "01": {"de": "Klar", "fr": "Clair", "it": "Chiaro"},
    # A hole on purpose: mvp-spec.md §7 stores what the annex has and no more,
    # and one missing label must not block a launch the spec does not block.
    "02": {"de": "Regen", "it": "Pioggia"},
}
_ROAD_CODES: Mapping[str, Mapping[str, str]] = {
    "01": {"de": "Autobahn", "fr": "Autoroute", "it": "Autostrada"},
    "02": {"de": "Nebenstrasse", "fr": "Route secondaire", "it": "Strada secondaria"},
}
#: mvp-spec.md §7's known gap — `main_cause*` has no `it` at all. Mapped onto
#: a `de`-only table so "no fallback to another language" is testable.
_DE_ONLY_CODES: Mapping[str, Mapping[str, str]] = {
    "01": {"de": "Nur Deutsch"},
    "02": {"de": "Auch nur Deutsch"},
}

ATTRIBUTE_DE_ONLY = "main_cause"

_CODE_TABLES: Mapping[str, Mapping[str, Mapping[str, str]]] = {
    ATTRIBUTE_WEATHER: _WEATHER_CODES,
    ATTRIBUTE_ROAD: _ROAD_CODES,
    ATTRIBUTE_DE_ONLY: _DE_ONLY_CODES,
}


class AlwaysCoveredProvider:
    """An `EnumCodeTableProvider` that always answers "covered".

    `FeatureService` is only here to *produce* a frozen config and its
    draft-time preview fingerprints; its codelist tier is phase 2's and is
    tested in `../feature/`. Answering `OK` keeps a freeze from depending on
    the mapping rows these tests re-point on purpose.
    """

    async def coverage(
        self, session: AsyncSession, corpus_id: CorpusId, source_column: str
    ) -> ColumnCoverage | None:
        return ColumnCoverage(
            status=CoverageStatus.OK,
            language="de",
            codes=(),
            labelled_count=0,
            total_count=0,
            coverage_pct=100.0,
        )


# `tests/` carries no `__init__.py`, so a sibling suite cannot
# `from .conftest import ...` (the same reason `../feature/conftest.py` hands
# its helpers out as fixtures). Every shared constant below is therefore a
# fixture, not an import.


@pytest.fixture
def fitting_model() -> str:
    """A model the fixture host has the VRAM for."""
    return FITTING_MODEL


@pytest.fixture
def second_fitting_model() -> str:
    return SECOND_FITTING_MODEL


@pytest.fixture
def oversized_model() -> str:
    """42.5 GB against the fixture host's 24 GB — the design's disabled row."""
    return OVERSIZED_MODEL


@pytest.fixture
def fixture_gpu() -> GpuInfo:
    return FIXTURE_GPU


@pytest.fixture
def enum_column() -> str:
    return ENUM_COLUMN


@pytest.fixture
def attribute_keys() -> dict[str, str]:
    """The fixture code tables, by role."""
    return {
        "weather": ATTRIBUTE_WEATHER,
        "road": ATTRIBUTE_ROAD,
        "de_only": ATTRIBUTE_DE_ONLY,
    }


@pytest.fixture
def make_enum_feature() -> Callable[..., dict[str, object]]:
    return enum_feature


@pytest.fixture
def make_text_feature() -> Callable[..., dict[str, object]]:
    return text_feature


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def ids() -> SeededFactory:
    return SeededFactory(seed=20260913)


@pytest.fixture
def model_catalog() -> StaticModelCatalog:
    """A reachable endpoint with the design's fixture models."""
    return StaticModelCatalog()


@pytest.fixture
def endpoint_prober() -> StaticEndpointProber:
    """A connection test that succeeds. Call `set_result()` for the failures —
    no test in this layer opens a socket (plan-phase-3.md §11)."""
    return StaticEndpointProber()


@pytest.fixture
def gpu_probe() -> StaticGpuProbe:
    return StaticGpuProbe(FIXTURE_GPU)


@pytest.fixture
def eval_settings(backend_settings: Settings) -> Settings:
    """`RA2_DEV_RECORD_MAX` / `RA2_EVAL_RECORD_MIN` small enough to seed
    against without writing 200 records per test, and **never literals** in the
    assertions — the design's "Dev · 40 records" reads its number from config
    and so does every test here."""
    return backend_settings.model_copy(update={"dev_record_max": 3, "eval_record_min": 8})


@pytest.fixture
def evaluation_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    model_catalog: StaticModelCatalog,
    endpoint_prober: StaticEndpointProber,
    gpu_probe: StaticGpuProbe,
    clock: FrozenClock,
    ids: SeededFactory,
    eval_settings: Settings,
) -> EvaluationService:
    return EvaluationService(
        session_factory=db_session_factory,
        model_catalog=model_catalog,
        endpoint_prober=endpoint_prober,
        gpu_probe=gpu_probe,
        clock=clock,
        ids=ids,
        settings=eval_settings,
    )


@pytest.fixture
def feature_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
    ids: SeededFactory,
) -> FeatureService:
    return FeatureService(
        session_factory=db_session_factory,
        codelist_provider=AlwaysCoveredProvider(),
        clock=clock,
        ids=ids,
    )


@pytest.fixture
def seed_corpus(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[CorpusId]]:
    """A corpus and `record_count` records.

    Record ids are **deliberately not** created in ascending order: the ids go
    in shuffled so that "the first N records by id" is a claim the test can
    actually fail, rather than one insertion order would satisfy by accident.
    """

    async def _seed(
        *,
        corpus_id: str = "corpus-1",
        name: str = "Zurich 2024",
        record_count: int = 10,
    ) -> CorpusId:
        async with db_session_factory() as session:
            session.add(
                Corpus(
                    id=CorpusId(corpus_id),
                    name=name,
                    imported_at=NOW,
                    source_file_manifest_json="[]",
                    import_report_json="[]",
                    record_count=record_count,
                )
            )
            await session.flush()
            # Inserted last-id-first; `record_scope` must still return them
            # in id order.
            for n in reversed(range(record_count)):
                session.add(
                    Record(
                        id=RecordId(f"{corpus_id}-rec-{n:03d}"),
                        corpus_id=CorpusId(corpus_id),
                        unfall_uid=f"UID{n:05d}",
                        language="de",
                        language_confidence=0.99,
                        text_raw=f"Narrative {n}",
                    )
                )
            await session.commit()
        return CorpusId(corpus_id)

    return _seed


@pytest.fixture
def seed_codelists(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[dict[str, CodeAttributeId]]]:
    """One `code_table_import` carrying every fixture attribute.

    Returns `{attribute key: CodeAttributeId}` so a test can re-point a
    mapping at a different attribute by name.

    **Idempotent per import id.** A test that re-points a mapping calls this
    again to get the attribute ids, and the `code_table_import` primary key
    would otherwise refuse the second call — asking twice for the same
    generation is not a second import.
    """
    seeded: dict[str, dict[str, CodeAttributeId]] = {}

    async def _seed(*, import_id: str = "cti-1") -> dict[str, CodeAttributeId]:
        if import_id in seeded:
            return seeded[import_id]
        attribute_ids: dict[str, CodeAttributeId] = {}
        async with db_session_factory() as session:
            session.add(
                CodeTableImport(
                    id=CodeTableImportId(import_id),
                    source_file="codes-2018.json",
                    source_hash=f"hash-{import_id}",
                    imported_at=NOW,
                )
            )
            await session.flush()
            for key, codes in _CODE_TABLES.items():
                attribute_id = CodeAttributeId(f"{import_id}-{key}")
                attribute_ids[key] = attribute_id
                session.add(
                    CodeAttribute(
                        id=attribute_id,
                        code_table_import_id=CodeTableImportId(import_id),
                        key=key,
                        name_json=json.dumps({"de": key}),
                    )
                )
                await session.flush()
                for code, label in codes.items():
                    session.add(
                        CodeValue(
                            id=f"{attribute_id}-{code}",
                            code_attribute_id=attribute_id,
                            code=code,
                            label_json=json.dumps(label, sort_keys=True),
                        )
                    )
            await session.commit()
        seeded[import_id] = attribute_ids
        return attribute_ids

    return _seed


@pytest.fixture
def map_column(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[None]]:
    """Point (or **re-point**) `(corpus, column)` at an imported attribute.

    The same in-place update `CodelistRepository.set_mapping` performs —
    mvp-spec.md §7's "freely re-editable without affecting the code table it
    points at".
    """

    async def _map(
        corpus_id: CorpusId,
        code_attribute_id: CodeAttributeId,
        *,
        source_column: str = ENUM_COLUMN,
        mapping_id: str = "cm-1",
    ) -> None:
        from ra2.persistence.repositories.codelist_repo import CodelistRepository

        async with db_session_factory() as session:
            await CodelistRepository(session).set_mapping(
                ColumnMapping(
                    id=ColumnMappingId(mapping_id),
                    corpus_id=corpus_id,
                    source_column=source_column,
                    code_attribute_id=code_attribute_id,
                    mapped_at=NOW,
                )
            )
            await session.commit()

    return _map


@pytest.fixture
def seed_template(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[PromptTemplateId]]:
    """One `prompt_template` version, active by default — the version new
    evaluations pick up in `save_draft`."""

    async def _seed(
        *,
        template_id: str = "pt-1",
        version: int = 1,
        active: bool = True,
    ) -> PromptTemplateId:
        async with db_session_factory() as session:
            session.add(
                PromptTemplate(
                    id=PromptTemplateId(template_id),
                    version=version,
                    source="{{feature_block}}\n{{narrative}}",
                    created_at=NOW,
                    activated_at=NOW if active else None,
                    fingerprint=f"fp-template-{version}",
                )
            )
            await session.commit()
        return PromptTemplateId(template_id)

    return _seed


def enum_feature(**overrides: object) -> dict[str, object]:
    """A labelled enum feature on `ENUM_COLUMN` — the one whose fingerprint
    moves when the codelist snapshot does."""
    defaults: dict[str, object] = {
        "key": "weather",
        "kind": Kind.LABELLED,
        "description": "The weather at the time of the accident.",
        "grain": Grain.ACCIDENT,
        "source_column": ENUM_COLUMN,
        "derivation": None,
        "value_type": ValueType.ENUM,
        "matching_rule": MatchingRule(kind=MatchingRuleKind.EXACT),
    }
    defaults.update(overrides)
    return defaults


def text_feature(**overrides: object) -> dict[str, object]:
    """A non-enum feature — no snapshot, so its evaluation fingerprint must
    equal its draft preview."""
    return enum_feature(
        key="injury_note",
        value_type=ValueType.FREE_TEXT,
        source_column="Bemerkung",
        matching_rule=MatchingRule(kind=MatchingRuleKind.NONE),
        **overrides,
    )


@pytest.fixture
def frozen_config(
    feature_service: FeatureService,
) -> Callable[..., Awaitable[FeatureConfigView]]:
    """A frozen feature set holding the given features."""

    async def _build(
        *features: dict[str, object],
        name: str = "Weather & conditions",
    ) -> FeatureConfigView:
        view = await feature_service.create_draft(name=name)
        for overrides in features or (enum_feature(),):
            view = await feature_service.add_feature(
                view.feature_config_id,
                **overrides,  # type: ignore[arg-type]
            )
        return await feature_service.freeze(view.feature_config_id)

    return _build


@pytest.fixture
def draft_config(
    feature_service: FeatureService,
) -> Callable[..., Awaitable[FeatureConfigView]]:
    """The same set, **left a draft** — what a launch must refuse."""

    async def _build(
        *features: dict[str, object],
        name: str = "Unfrozen set",
    ) -> FeatureConfigView:
        view = await feature_service.create_draft(name=name)
        for overrides in features or (enum_feature(),):
            view = await feature_service.add_feature(
                view.feature_config_id,
                **overrides,  # type: ignore[arg-type]
            )
        return view

    return _build


@pytest.fixture
def launchable(
    evaluation_service: EvaluationService,
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    seed_codelists: Callable[..., Awaitable[dict[str, CodeAttributeId]]],
    map_column: Callable[..., Awaitable[None]],
    seed_template: Callable[..., Awaitable[PromptTemplateId]],
    frozen_config: Callable[..., Awaitable[FeatureConfigView]],
) -> Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]]:
    """Everything a launch needs, wired: corpus + records, code tables, a
    mapping, an active template, a frozen config, and a saved draft with
    models selected. Returns `(corpus_id, config, evaluation_id)`."""

    async def _build(
        *features: dict[str, object],
        record_count: int = 10,
        models: Sequence[str] = (FITTING_MODEL,),
        attribute: str = ATTRIBUTE_WEATHER,
    ) -> tuple[CorpusId, FeatureConfigView, str]:
        corpus_id = await seed_corpus(record_count=record_count)
        attributes = await seed_codelists()
        await map_column(corpus_id, attributes[attribute])
        await seed_template()
        config = await frozen_config(*features)
        draft = await evaluation_service.save_draft(
            name="Weather eval",
            corpus_id=corpus_id,
            feature_config_id=config.feature_config_id,
        )
        await evaluation_service.update_draft(draft.evaluation_id, selected_models=tuple(models))
        return corpus_id, config, draft.evaluation_id

    return _build


__all__ = [
    "ATTRIBUTE_DE_ONLY",
    "ATTRIBUTE_ROAD",
    "ATTRIBUTE_WEATHER",
    "ENUM_COLUMN",
    "FITTING_MODEL",
    "FIXTURE_GPU",
    "NOW",
    "OVERSIZED_MODEL",
    "SECOND_FITTING_MODEL",
    "AlwaysCoveredProvider",
    "enum_feature",
    "text_feature",
]


@pytest.fixture
def record_gate(
    db_session_factory: async_sessionmaker[AsyncSession], ids: SeededFactory
) -> Callable[..., Awaitable[None]]:
    """Put a qualification on record, as `just qualify-model` would (SD40).

    `gated_at=()` records a quality-only qualification. Each call adds a row
    measured one minute after the last, so "the newest" is unambiguous.
    """
    measured = [datetime(2026, 9, 25, 10, 0, tzinfo=UTC)]

    async def record(
        tag: str,
        digest: str,
        *,
        gated_at: Sequence[int] = (4,),
        verdict: GateVerdict = GateVerdict.PASSES,
        ollama_version: str | None = DEFAULT_OLLAMA_VERSION,
    ) -> None:
        at = measured[-1].replace(minute=len(measured))
        measured.append(at)
        qualification = Qualification(
            model_tag=tag,
            model_digest=digest,
            ollama_version=ollama_version,
            gpu_name=None,
            ra2_version=None,
            measured_at=at,
            seed_records=200,
            quality=QualitySummary(
                records=200,
                reasoning_effort="none",
                macro_f1=0.895,
                macro_f1_low=0.870,
                macro_f1_high=0.905,
                f1_by_language={"de": 0.91},
                median_latency_ms=1710,
                ms_per_record=1745.0,
                median_completion_tokens=121,
                entity_fill=0.0,
                parse_failures=0,
            ),
            gates=tuple(
                GateResult(
                    n=n,
                    records=48,
                    noise_band=2,
                    serial_on_n_slot_differ=0,
                    parallel_differ=0,
                    speedup=2.4,
                    verdict=verdict,
                )
                for n in gated_at
            ),
        )
        async with session_scope(db_session_factory) as session:
            await QualificationRepository(session).add(QualificationId(ids.new_id()), qualification)

    return record

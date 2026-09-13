"""Fixtures for `PromptService` (I1, phase 3 Wave 2).

Same real-temp-file-SQLite idiom every other backend service suite uses
(`../feature/conftest.py`, `../codelist/conftest.py`): `db_session_factory`
comes from `tests/backend/conftest.py`'s `alembic upgrade head` chain, never
`Base.metadata.create_all()` (Do-NOT #10).

Builders here seed exactly the rows `prompt_service.py` reads: a corpus and
one record on it (for `preview()`'s live enum lookup and `resolve()`'s
narrative), a feature set with a labelled-enum, a labelled-non-enum and an
exploratory feature (so `render_feature_block`'s three code paths are all
exercised through the service, not just through `domain/prompt.py`'s own
unit tests), a mapped code table, and an evaluation pinned to a template with
its `evaluation_feature` snapshot rows.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from tests.fixtures.factories import seed_corpus

from ra2.domain.feature import Grain, Kind, ValueType
from ra2.domain.ids import (
    CodeAttributeId,
    CodeTableImportId,
    ColumnMappingId,
    CorpusId,
    EvaluationId,
    FeatureConfigId,
    FeatureId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.infra.clock import FrozenClock
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import (
    CodeAttribute,
    CodeTableImport,
    CodeValue,
    ColumnMapping,
    Corpus,
    Evaluation,
    EvaluationFeature,
    Feature,
    FeatureConfig,
    PromptTemplate,
    Record,
    Run,
)
from ra2.persistence.session import create_session_factory
from ra2.services.prompt_service import PromptService

__all__ = [
    "NOW",
    "clock",
    "ids",
    "prompt_service",
    "seed_evaluation_with_snapshot",
    "seed_mapped_enum_column",
    "seed_minimal_feature_config",
    "seed_record",
    "seed_template",
]

#: A fixed instant, matching the rest of the suite's `FROZEN_NOW` convention.
NOW = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)

#: The enum feature's mapped attribute — one code, two languages, so a
#: rendered feature block is easy to eyeball in a failing assertion.
_WEATHER_CODES = (("01", {"de": "Klar", "fr": "Clair"}), ("02", {"de": "Regen", "fr": "Pluie"}))


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def ids() -> SeededFactory:
    return SeededFactory(seed=20260913)


@pytest_asyncio.fixture
async def prompt_service(
    migrated_engine: AsyncEngine, clock: FrozenClock, ids: SeededFactory
) -> PromptService:
    return PromptService(
        session_factory=create_session_factory(migrated_engine), clock=clock, ids=ids
    )


@pytest.fixture
def seed_template(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[PromptTemplateId]]:
    """Seed one `prompt_template` row directly — bypassing the service, the
    same way `../feature/conftest.py`'s `seed_evaluation` bypasses
    `feature_service` to set up a citation-guard test."""

    async def _seed(
        template_id: str,
        *,
        version: int = 1,
        source: str = "Describe {{narrative}} using {{feature_block}}.",
    ) -> PromptTemplateId:
        async with db_session_factory() as session:
            session.add(
                PromptTemplate(
                    id=PromptTemplateId(template_id),
                    version=version,
                    source=source,
                    created_at=NOW,
                    fingerprint=f"fingerprint-{template_id}",
                )
            )
            await session.commit()
        return PromptTemplateId(template_id)

    return _seed


@pytest.fixture
def seed_record(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[RecordId]]:
    async def _seed(
        record_id: str,
        *,
        corpus_id: str,
        unfall_uid: str = "uid-0001",
        text_raw: str = "The car skidded on ice near the intersection.",
        language: str = "de",
    ) -> RecordId:
        async with db_session_factory() as session:
            await seed_corpus(session, corpus_id)
            session.add(
                Record(
                    id=RecordId(record_id),
                    corpus_id=CorpusId(corpus_id),
                    unfall_uid=unfall_uid,
                    language=language,
                    language_confidence=1.0,
                    text_raw=text_raw,
                )
            )
            await session.commit()
        return RecordId(record_id)

    return _seed


@pytest.fixture
def seed_minimal_feature_config(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[FeatureConfigId]]:
    """One frozen feature set: a labelled enum feature (`weather`, mapped to
    `_WEATHER_CODES`), a labelled non-enum feature (`injured_count`) and an
    exploratory attribute (`notes`) — the three branches
    `render_feature_block` takes, all through one config."""

    async def _seed(config_id: str, *, source_column: str = "WitterungAusw") -> FeatureConfigId:
        async with db_session_factory() as session:
            session.add(
                FeatureConfig(
                    id=FeatureConfigId(config_id), name=f"config-{config_id}", created_at=NOW
                )
            )
            await session.flush()
            session.add_all(
                [
                    Feature(
                        id=FeatureId(f"{config_id}-weather"),
                        feature_config_id=FeatureConfigId(config_id),
                        ordinal=0,
                        key="weather",
                        kind=Kind.LABELLED,
                        description="The weather at the time of the accident.",
                        grain=Grain.ACCIDENT,
                        source_column=source_column,
                        value_type=ValueType.ENUM,
                        matching_rule=(
                            '{"kind":"exact","tolerance_minutes":null,"decimal_precision":null}'
                        ),
                    ),
                    Feature(
                        id=FeatureId(f"{config_id}-injured"),
                        feature_config_id=FeatureConfigId(config_id),
                        ordinal=1,
                        key="injured_count",
                        kind=Kind.LABELLED,
                        description="Number of injured persons.",
                        grain=Grain.ACCIDENT,
                        source_column="VerletztAnz",
                        value_type=ValueType.INTEGER,
                        matching_rule=(
                            '{"kind":"exact","tolerance_minutes":null,"decimal_precision":null}'
                        ),
                    ),
                    Feature(
                        id=FeatureId(f"{config_id}-notes"),
                        feature_config_id=FeatureConfigId(config_id),
                        ordinal=2,
                        key="notes",
                        kind=Kind.EXPLORATORY,
                        description="Anything else worth flagging.",
                        grain=Grain.ACCIDENT,
                        source_column=None,
                        value_type=ValueType.FREE_TEXT,
                        matching_rule=(
                            '{"kind":"none","tolerance_minutes":null,"decimal_precision":null}'
                        ),
                    ),
                ]
            )
            await session.commit()
        return FeatureConfigId(config_id)

    return _seed


@pytest.fixture
def seed_mapped_enum_column(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[None]]:
    """A `code_table_import` + one attribute + `_WEATHER_CODES`, mapped onto
    `(corpus_id, source_column)` — what `preview()`'s live lookup reads."""

    async def _seed(
        *, corpus_id: str, source_column: str, import_id: str, attribute_id: str
    ) -> None:
        code_table_import_id = CodeTableImportId(import_id)
        code_attribute_id = CodeAttributeId(attribute_id)
        async with db_session_factory() as session:
            session.add(
                CodeTableImport(
                    id=code_table_import_id,
                    source_file="codes.json",
                    source_hash=f"hash-{import_id}",
                    imported_at=NOW,
                )
            )
            await session.flush()
            session.add(
                CodeAttribute(
                    id=code_attribute_id,
                    code_table_import_id=code_table_import_id,
                    key="weather",
                    name_json='{"de":"Witterung"}',
                )
            )
            await session.flush()
            session.add_all(
                CodeValue(
                    id=f"{attribute_id}-{code}",
                    code_attribute_id=code_attribute_id,
                    code=code,
                    label_json=_dump(label),
                )
                for code, label in _WEATHER_CODES
            )
            session.add(
                ColumnMapping(
                    id=ColumnMappingId(f"mapping-{corpus_id}-{source_column}"),
                    corpus_id=CorpusId(corpus_id),
                    source_column=source_column,
                    code_attribute_id=code_attribute_id,
                    mapped_at=NOW,
                )
            )
            await session.commit()

    return _seed


@pytest.fixture
def seed_evaluation_with_snapshot(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[EvaluationId]]:
    """An evaluation pinned to a template + feature config + corpus, with the
    `evaluation_feature` snapshot rows `resolve()` reads — the enum feature's
    snapshot uses this module's own agreed `enum_codelist_json` shape (see
    `ra2/services/prompt_service.py`'s module docstring)."""

    async def _seed(
        evaluation_id: str,
        *,
        corpus_id: str,
        feature_config_id: str,
        prompt_template_id: str,
        weather_feature_id: str,
        injured_feature_id: str,
        notes_feature_id: str,
        prompt_language: str = "de",
        is_dev: bool = False,
        run_ids: tuple[str, ...] = (),
    ) -> EvaluationId:
        async with db_session_factory() as session:
            existing_corpus = await session.get(Corpus, CorpusId(corpus_id))
            if existing_corpus is None:
                await seed_corpus(session, corpus_id)
            session.add(
                Evaluation(
                    id=EvaluationId(evaluation_id),
                    name=f"eval-{evaluation_id}",
                    corpus_id=CorpusId(corpus_id),
                    feature_config_id=FeatureConfigId(feature_config_id),
                    created_at=NOW,
                    prompt_template_id=PromptTemplateId(prompt_template_id),
                    prompt_language=prompt_language,
                    is_dev=is_dev,
                    launched_at=NOW,
                )
            )
            await session.flush()
            session.add_all(
                [
                    EvaluationFeature(
                        evaluation_id=EvaluationId(evaluation_id),
                        feature_id=FeatureId(weather_feature_id),
                        enum_codelist_json=_dump(
                            [{"code": code, "label": label} for code, label in _WEATHER_CODES]
                        ),
                        fingerprint="fingerprint-weather-snapshot",
                    ),
                    EvaluationFeature(
                        evaluation_id=EvaluationId(evaluation_id),
                        feature_id=FeatureId(injured_feature_id),
                        enum_codelist_json=None,
                        fingerprint="fingerprint-injured-snapshot",
                    ),
                    EvaluationFeature(
                        evaluation_id=EvaluationId(evaluation_id),
                        feature_id=FeatureId(notes_feature_id),
                        enum_codelist_json=None,
                        fingerprint="fingerprint-notes-snapshot",
                    ),
                ]
            )
            for run_id in run_ids:
                session.add(
                    Run(
                        id=RunId(run_id),
                        evaluation_id=EvaluationId(evaluation_id),
                        model_name="llama3.1:8b-instruct-q8_0",
                        model_digest="sha256:abc",
                        prompt_template_version=1,
                        prompt_template_id=PromptTemplateId(prompt_template_id),
                        prompt_template_fingerprint="fingerprint-run",
                        temperature=0.0,
                        seed=42,
                        host_platform="linux-x64",
                    )
                )
            await session.commit()
        return EvaluationId(evaluation_id)

    return _seed


def _dump(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

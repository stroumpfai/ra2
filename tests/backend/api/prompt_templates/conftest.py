"""Fixtures for `/api/v1/prompt-templates/*` (K1, phase 3 Wave 3).

`api_client` comes from `tests/backend/api/conftest.py` (shared across every
`tests/backend/api/**` suite, the same way `tests/backend/api/features/**`
uses it without a local override). The builders here seed exactly the rows
the router's `PromptService` calls read — a template row, a corpus + record,
a minimal feature set, and (for the delete-conflict test) an evaluation + run
that cites a template — the same idiom
`tests/backend/services/prompt/conftest.py` (I1) uses one layer down, kept
deliberately small since `PromptService`'s own behaviour is asserted there,
not re-asserted here beyond what the wire layer must preserve.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.factories import seed_corpus

from ra2.domain.feature import Grain, Kind, ValueType
from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    FeatureConfigId,
    FeatureId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.persistence.models import (
    Evaluation,
    Feature,
    FeatureConfig,
    PromptTemplate,
    Record,
    Run,
)

__all__ = [
    "NOW",
    "seed_cited_template",
    "seed_minimal_feature_config",
    "seed_record",
    "seed_template",
]

#: A fixed instant, matching the rest of the suite's `FROZEN_NOW` convention.
NOW = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)


@pytest.fixture
def seed_template(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[str]]:
    """Seed one `prompt_template` row directly — bypassing the API, the same
    way `../features/**`'s tests build a config through the API but a lower
    layer's conftest seeds rows directly when a test's point is the *read*,
    not the write."""

    async def _seed(
        template_id: str,
        *,
        version: int = 1,
        source: str = "Describe {{narrative}} using {{feature_block}}.",
    ) -> str:
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
        return template_id

    return _seed


@pytest.fixture
def seed_record(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[str]]:
    """A corpus and one record on it — what `resolve` (mapped from
    `PromptService.preview`) reads for the narrative."""

    async def _seed(
        record_id: str,
        *,
        corpus_id: str,
        unfall_uid: str = "uid-0001",
        text_raw: str = "The car skidded on ice near the intersection.",
        language: str = "de",
    ) -> str:
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
        return record_id

    return _seed


@pytest.fixture
def seed_minimal_feature_config(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[str]]:
    """One feature set with a single labelled, non-enum feature — enough for
    `resolve` to render a feature block without needing a mapped code table
    (that lookup path belongs to I1's own suite)."""

    async def _seed(config_id: str, *, source_column: str = "VerletztAnz") -> str:
        async with db_session_factory() as session:
            session.add(
                FeatureConfig(
                    id=FeatureConfigId(config_id), name=f"config-{config_id}", created_at=NOW
                )
            )
            await session.flush()
            session.add(
                Feature(
                    id=FeatureId(f"{config_id}-injured"),
                    feature_config_id=FeatureConfigId(config_id),
                    ordinal=0,
                    key="injured_count",
                    kind=Kind.LABELLED,
                    description="Number of injured persons.",
                    grain=Grain.ACCIDENT,
                    source_column=source_column,
                    value_type=ValueType.INTEGER,
                    matching_rule=(
                        '{"kind":"exact","tolerance_minutes":null,"decimal_precision":null}'
                    ),
                )
            )
            await session.commit()
        return config_id

    return _seed


@pytest.fixture
def seed_cited_template(
    db_session_factory: async_sessionmaker[AsyncSession],
    seed_template: Callable[..., Awaitable[str]],
    seed_minimal_feature_config: Callable[..., Awaitable[str]],
) -> Callable[..., Awaitable[str]]:
    """A template version cited by exactly one `run` — what makes `DELETE`
    return 409. Builds the evaluation + run chain a `run.prompt_template_id`
    FK requires, the same shape
    `tests/backend/services/prompt/conftest.py`'s `seed_evaluation_with_snapshot`
    uses, trimmed to what `citation_count()` (a plain `COUNT(run WHERE
    prompt_template_id = …)`) actually reads — no `evaluation_feature` rows
    needed."""

    async def _seed(template_id: str) -> str:
        await seed_template(template_id)
        config_id = await seed_minimal_feature_config(f"{template_id}-fc")
        async with db_session_factory() as session:
            await seed_corpus(session, f"{template_id}-corpus")
            session.add(
                Evaluation(
                    id=EvaluationId(f"{template_id}-eval"),
                    name=f"eval-{template_id}",
                    corpus_id=CorpusId(f"{template_id}-corpus"),
                    feature_config_id=FeatureConfigId(config_id),
                    created_at=NOW,
                    prompt_template_id=PromptTemplateId(template_id),
                    prompt_language="de",
                    launched_at=NOW,
                )
            )
            await session.flush()
            session.add(
                Run(
                    id=RunId(f"{template_id}-run"),
                    evaluation_id=EvaluationId(f"{template_id}-eval"),
                    model_name="llama3.1:8b-instruct-q8_0",
                    model_digest="sha256:abc",
                    prompt_template_version=1,
                    prompt_template_id=PromptTemplateId(template_id),
                    prompt_template_fingerprint=f"fingerprint-{template_id}",
                    temperature=0.0,
                    seed=42,
                    host_platform="linux-x64",
                )
            )
            await session.commit()
        return template_id

    return _seed

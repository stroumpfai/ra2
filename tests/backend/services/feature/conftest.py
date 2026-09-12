"""Fixtures for `FeatureService` (E2, phase 2 Wave 2).

Same shape as `../corpus/conftest.py`: a real migrated temp-file SQLite
database from `tests/backend/conftest.py`, a frozen clock, seeded ids, and one
substitute — the `EnumCodeTableProvider`.

E1 builds the real provider (`codelist_service.coverage`) in the same wave, so
the double here **answers from a dict and records what it was asked**. That is
the whole point of the seam (`services/protocols.py`, plan-phase-2.md §3):
neither agent waits, and these tests assert on `feature_service`'s reaction to
a coverage answer, never on how that answer was computed.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.codelist_coverage import ColumnCoverage, CoverageStatus
from ra2.domain.feature import (
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    ValueType,
)
from ra2.domain.ids import CorpusId, EvaluationId, FeatureConfigId
from ra2.infra.clock import FrozenClock
from ra2.infra.idgen import SeededFactory
from ra2.persistence.models import Corpus, Evaluation, Feature
from ra2.services.feature_service import FeatureService
from ra2.services.readmodels import FeatureConfigView

#: The corpus a test passes as `validate_against`. It is never persisted and
#: never looked up by `feature_service` — the provider is the only thing that
#: resolves it — so a plain literal is honest here.
VALIDATION_CORPUS = CorpusId("corpus-under-validation")


def coverage(status: CoverageStatus, *, language: str = "de") -> ColumnCoverage:
    """A `ColumnCoverage` carrying nothing but its status.

    The counts are what `compute_coverage` would produce for an empty column;
    `feature_service` reads `status` and nothing else, and pretending
    otherwise would make this fixture a second, competing implementation of
    D1's rules.
    """
    return ColumnCoverage(
        status=status,
        language=language,
        codes=(),
        labelled_count=0,
        total_count=0,
        coverage_pct=0.0,
    )


class StubCodeTableProvider:
    """An `EnumCodeTableProvider` that answers from a dict.

    A column absent from `answers` returns `None` — "no mapping at all",
    which is the protocol's own default for an unmapped column and the
    commonest failing case in the design ("VortrittAusw · no codes").
    """

    def __init__(self) -> None:
        self.answers: dict[str, ColumnCoverage | None] = {}
        self.calls: list[tuple[AsyncSession, CorpusId, str]] = []
        #: `feature` rows visible through the session it was handed, per call.
        #: Recorded at call time: the caller's uncommitted flush is visible
        #: only from the caller's own session and transaction, which is what
        #: the seam promises (`services/protocols.py`).
        self.features_visible: list[int] = []

    async def coverage(
        self, session: AsyncSession, corpus_id: CorpusId, source_column: str
    ) -> ColumnCoverage | None:
        self.calls.append((session, corpus_id, source_column))
        self.features_visible.append(
            await session.scalar(select(func.count()).select_from(Feature)) or 0
        )
        return self.answers.get(source_column)

    @property
    def columns_asked(self) -> list[str]:
        return [source_column for _, _, source_column in self.calls]


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def ids() -> SeededFactory:
    return SeededFactory(seed=20260912)


@pytest.fixture
def codelist_provider() -> StubCodeTableProvider:
    return StubCodeTableProvider()


@pytest.fixture
def feature_service(
    db_session_factory: async_sessionmaker[AsyncSession],
    codelist_provider: StubCodeTableProvider,
    clock: FrozenClock,
    ids: SeededFactory,
) -> FeatureService:
    return FeatureService(
        session_factory=db_session_factory,
        codelist_provider=codelist_provider,
        clock=clock,
        ids=ids,
    )


def _feature_kwargs(**overrides: object) -> dict[str, object]:
    """A minimal valid labelled feature: accident grain, enum, exact match.

    Every test that is not *about* one of these fields overrides only the one
    it cares about, so the hazard under test is visible in the call.
    """
    defaults: dict[str, object] = {
        "key": "weather",
        "kind": Kind.LABELLED,
        "description": "The weather at the time of the accident.",
        "grain": Grain.ACCIDENT,
        "source_column": "WitterungAusw",
        "derivation": None,
        "value_type": ValueType.ENUM,
        "matching_rule": MatchingRule(kind=MatchingRuleKind.EXACT),
    }
    defaults.update(overrides)
    return defaults


@pytest.fixture
def feature_kwargs() -> Callable[..., dict[str, object]]:
    """Handed out as a fixture rather than imported: sibling suites have
    their own `conftest.py`, and `tests/` carries no `__init__.py`, so
    `from conftest import ...` is ambiguous by construction."""
    return _feature_kwargs


@pytest.fixture
def column_coverage() -> Callable[..., ColumnCoverage]:
    return coverage


@pytest.fixture
def validation_corpus() -> CorpusId:
    return VALIDATION_CORPUS


@pytest.fixture
def draft_with(
    feature_service: FeatureService,
) -> Callable[..., Awaitable[FeatureConfigView]]:
    """A draft holding one feature per `_feature_kwargs` override dict."""

    async def _build(
        *features: dict[str, object],
        name: str = "Weather & conditions",
        validate_against: CorpusId | None = None,
    ) -> FeatureConfigView:
        view = await feature_service.create_draft(name=name)
        for overrides in features:
            view = await feature_service.add_feature(
                view.feature_config_id,
                validate_against=validate_against,
                **_feature_kwargs(**overrides),  # type: ignore[arg-type]
            )
        return view

    return _build


@pytest.fixture
def seed_evaluation(
    db_session_factory: async_sessionmaker[AsyncSession],
    clock: FrozenClock,
) -> Callable[..., Awaitable[None]]:
    """Seed one `evaluation` row citing a feature config.

    Phase 2 still has no evaluation-creation flow (that is phase 3), so the
    `LOCKED · N eval` count is tested against a hand-seeded row rather than a
    mock — the same reasoning `../corpus/conftest.py` gives for the corpus
    delete guard. `evaluation.corpus_id` is a real FK, hence the corpus.
    """

    async def _seed(feature_config_id: FeatureConfigId, name: str = "eval-1") -> None:
        corpus_id = CorpusId(f"corpus-{name}")
        async with db_session_factory() as session:
            session.add(
                Corpus(
                    id=corpus_id,
                    name=name,
                    imported_at=clock.now(),
                    source_file_manifest_json="[]",
                    import_report_json="[]",
                    record_count=0,
                )
            )
            await session.flush()
            session.add(
                Evaluation(
                    id=EvaluationId(f"eval-{name}"),
                    name=name,
                    corpus_id=corpus_id,
                    feature_config_id=feature_config_id,
                )
            )
            await session.commit()

    return _seed


__all__ = [
    "VALIDATION_CORPUS",
    "StubCodeTableProvider",
    "coverage",
    "feature_kwargs",
]

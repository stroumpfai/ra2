"""Round-trip tests for `QualificationRepository` against a real temp-file
SQLite database (sw-design.md SD40).

The table is append-only. A re-qualification adds a row and the newest wins,
and the repository has no method that could do otherwise. These tests pin
both halves.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import QualificationId
from ra2.domain.qualification import GateResult, GateVerdict, Qualification, QualitySummary
from ra2.persistence.models import ModelQualification
from ra2.persistence.repositories.qualification_repo import QualificationRepository

pytestmark = pytest.mark.backend

T0 = datetime(2026, 9, 25, 10, 0, tzinfo=UTC)
TAG = "qwen3:8b"
OLD_DIGEST = "500a1f067a9f"
NEW_DIGEST = "7c1e2f3a4b5d"


def _quality(macro_f1: float = 0.895) -> QualitySummary:
    return QualitySummary(
        records=200,
        macro_f1=macro_f1,
        macro_f1_low=macro_f1 - 0.025,
        macro_f1_high=macro_f1 + 0.010,
        f1_by_language={"de": 0.91, "fr": 0.88, "it": 0.93},
        median_latency_ms=1710,
        ms_per_record=1745.5,
        median_completion_tokens=121,
        entity_fill=0.0,
        parse_failures=0,
    )


GATE_4 = GateResult(
    n=4,
    records=48,
    noise_band=2,
    serial_on_n_slot_differ=0,
    parallel_differ=1,
    speedup=2.4,
    verdict=GateVerdict.PASSES,
)


def _qualification(
    *,
    digest: str = OLD_DIGEST,
    at: datetime = T0,
    macro_f1: float = 0.895,
    gates: tuple[GateResult, ...] = (),
) -> Qualification:
    return Qualification(
        model_tag=TAG,
        model_digest=digest,
        ollama_version="0.34.0",
        gpu_name="NVIDIA GeForce RTX 5060 Ti",
        ra2_version="0.1.0",
        measured_at=at,
        seed_records=200,
        quality=_quality(macro_f1),
        gates=gates,
    )


async def _add(
    factory: async_sessionmaker[AsyncSession], qualification_id: str, q: Qualification
) -> None:
    async with factory() as session, session.begin():
        await QualificationRepository(session).add(QualificationId(qualification_id), q)


async def test_a_qualification_round_trips_with_its_gates(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    written = _qualification(gates=(GATE_4,))
    await _add(db_session_factory, "q-1", written)

    async with db_session_factory() as session:
        read = await QualificationRepository(session).latest_for(TAG)
    assert read == written


async def test_an_unknown_tag_has_no_qualification(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        assert await QualificationRepository(session).latest_for("never:pulled") is None


async def test_qualifications_are_appended_never_updated(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two qualifications of one (tag, digest): `latest_for` returns the newer,
    and the older is still there."""
    await _add(db_session_factory, "q-1", _qualification(macro_f1=0.890))
    await _add(
        db_session_factory, "q-2", _qualification(macro_f1=0.899, at=T0 + timedelta(hours=1))
    )

    async with db_session_factory() as session:
        latest = await QualificationRepository(session).latest_for(TAG, OLD_DIGEST)
        count = await session.scalar(select(func.count()).select_from(ModelQualification))
    assert latest is not None
    assert latest.quality.macro_f1 == 0.899
    assert count == 2


def test_the_repository_offers_no_way_to_change_a_row() -> None:
    public = {name for name in vars(QualificationRepository) if not name.startswith("_")}
    assert public == {"add", "latest_for"}


async def test_latest_for_a_digest_ignores_newer_rows_of_other_weights(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add(db_session_factory, "q-old", _qualification(digest=OLD_DIGEST))
    await _add(
        db_session_factory, "q-new", _qualification(digest=NEW_DIGEST, at=T0 + timedelta(days=1))
    )

    async with db_session_factory() as session:
        repo = QualificationRepository(session)
        by_digest = await repo.latest_for(TAG, OLD_DIGEST)
        any_digest = await repo.latest_for(TAG)
    assert by_digest is not None and by_digest.model_digest == OLD_DIGEST
    assert any_digest is not None and any_digest.model_digest == NEW_DIGEST


async def test_a_later_quality_only_run_does_not_hide_the_gate(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Re-measuring quality alone mustn't take a gated model back to serial:
    the launch asks for the newest *gated* qualification."""
    await _add(db_session_factory, "q-gated", _qualification(gates=(GATE_4,)))
    await _add(db_session_factory, "q-plain", _qualification(at=T0 + timedelta(hours=1)))

    async with db_session_factory() as session:
        repo = QualificationRepository(session)
        newest = await repo.latest_for(TAG, OLD_DIGEST)
        gated = await repo.latest_for(TAG, OLD_DIGEST, gated=True)
    assert newest is not None and newest.gates == ()
    assert gated is not None and gated.gates == (GATE_4,)


async def test_two_rows_in_the_same_instant_resolve_by_id(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Ids are uuid7, so in time order too. Same timestamp: the larger id wins,
    deterministically, rather than whichever row SQLite happens to return."""
    await _add(db_session_factory, "0190-a", _qualification(macro_f1=0.880))
    await _add(db_session_factory, "0190-b", _qualification(macro_f1=0.881))

    async with db_session_factory() as session:
        latest = await QualificationRepository(session).latest_for(TAG)
    assert latest is not None and latest.quality.macro_f1 == 0.881

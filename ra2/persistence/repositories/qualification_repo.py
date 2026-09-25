"""`model_qualification` persistence (sw-design.md SD40).

**Append-only, and it shows in the API.** There's `add` and there's
`latest_for`, and no update and no delete. Re-qualifying a model adds a row,
and the newest per (tag, digest) wins, the way a re-run adds runs rather than
rewriting one (Do-NOT #2, treated as a rule here although this table isn't
named in it). `just reset` is the one thing that removes a row, and it
removes the database with it.

It takes and returns `domain.qualification.Qualification`, not the ORM row,
so the two JSON columns are encoded and decoded here and nowhere else.
"""

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import QualificationId
from ra2.domain.qualification import GateResult, Qualification, QualitySummary
from ra2.persistence.models import ModelQualification

__all__ = ["QualificationRepository"]

_GATES = TypeAdapter(tuple[GateResult, ...])
_NO_GATES = "[]"


class QualificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, qualification_id: QualificationId, qualification: Qualification) -> None:
        self._session.add(
            ModelQualification(
                id=qualification_id,
                model_tag=qualification.model_tag,
                model_digest=qualification.model_digest,
                ollama_version=qualification.ollama_version,
                gpu_name=qualification.gpu_name,
                ra2_version=qualification.ra2_version,
                measured_at=qualification.measured_at,
                seed_records=qualification.seed_records,
                quality_json=qualification.quality.model_dump_json(),
                gate_json=_GATES.dump_json(qualification.gates).decode("utf-8"),
            )
        )
        await self._session.flush()

    async def latest_for(
        self, model_tag: str, model_digest: str | None = None, *, gated: bool = False
    ) -> Qualification | None:
        """The newest qualification of `model_tag`, or `None`.

        `model_digest` narrows it to one set of weights. `gated=True` skips
        qualifications without a parallel gate, so a later quality-only
        re-run doesn't hide the gate a launch needs (`parallel_decision`).

        Newest by `measured_at`, then by id, which is a uuid7 and so also in
        time order, for two rows stamped in the same instant.
        """
        stmt = select(ModelQualification).where(ModelQualification.model_tag == model_tag)
        if model_digest is not None:
            stmt = stmt.where(ModelQualification.model_digest == model_digest)
        if gated:
            stmt = stmt.where(ModelQualification.gate_json != _NO_GATES)
        stmt = stmt.order_by(
            ModelQualification.measured_at.desc(), ModelQualification.id.desc()
        ).limit(1)
        row: ModelQualification | None = await self._session.scalar(stmt)
        return None if row is None else _to_domain(row)


def _to_domain(row: ModelQualification) -> Qualification:
    return Qualification(
        model_tag=row.model_tag,
        model_digest=row.model_digest,
        ollama_version=row.ollama_version,
        gpu_name=row.gpu_name,
        ra2_version=row.ra2_version,
        measured_at=row.measured_at,
        seed_records=row.seed_records,
        quality=QualitySummary.model_validate_json(row.quality_json),
        gates=_GATES.validate_json(row.gate_json),
    )

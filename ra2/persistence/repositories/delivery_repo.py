# STUB — bodies owned by A3 (feat/m2-persistence). Not frozen.
"""Delivery and delivery-file persistence."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ra2.domain.ids import DeliveryId, FileId
from ra2.persistence.models import Corpus, Delivery, DeliveryFile

__all__ = ["DeliveryRepository"]


class DeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, delivery: Delivery) -> None:
        self._session.add(delivery)
        await self._session.flush()

    async def get(self, delivery_id: DeliveryId) -> Delivery | None:
        stmt = (
            select(Delivery).where(Delivery.id == delivery_id).options(selectinload(Delivery.files))
        )
        result: Delivery | None = await self._session.scalar(stmt)
        return result

    async def list_all(self) -> list[Delivery]:
        stmt = (
            select(Delivery)
            .options(selectinload(Delivery.files))
            .order_by(Delivery.created_at.desc())
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_file(self, file_id: FileId) -> DeliveryFile | None:
        stmt = select(DeliveryFile).where(DeliveryFile.id == file_id)
        result: DeliveryFile | None = await self._session.scalar(stmt)
        return result

    async def list_files(self, delivery_id: DeliveryId) -> list[DeliveryFile]:
        stmt = (
            select(DeliveryFile)
            .where(DeliveryFile.delivery_id == delivery_id)
            .order_by(DeliveryFile.filename)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    # --- discard (sw-design.md §18) ----------------------------------------

    async def count_citing_corpora(self, delivery_id: DeliveryId) -> int:
        """Corpora frozen from this delivery.

        The database will **not** refuse on its own: `corpus.delivery_id` is
        `ondelete="SET NULL"` (SD4 — a corpus outlives its delivery), so a
        delete would quietly null the provenance link that
        `corpus.source_file_manifest_json` exists to make traceable. The guard
        that turns that into a refusal is in the service, and this is the
        query behind it (§18.2).
        """
        count = await self._session.scalar(
            select(func.count()).select_from(Corpus).where(Corpus.delivery_id == delivery_id)
        )
        return int(count or 0)

    async def delete(self, delivery: Delivery) -> None:
        """Remove the delivery and its `delivery_file` rows (`CASCADE`).

        **The stored bytes are not this class's business.** Removing them is
        `LifecycleService`'s, through the same `FileStore` seam intake used —
        a repository that reached the filesystem would be the first one that
        did.
        """
        await self._session.delete(delivery)
        await self._session.flush()

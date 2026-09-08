# STUB — bodies owned by A3 (feat/m2-persistence). Not frozen.
"""Delivery and delivery-file persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ra2.domain.ids import DeliveryId, FileId
from ra2.persistence.models import Delivery, DeliveryFile

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

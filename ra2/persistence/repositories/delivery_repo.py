# STUB — bodies owned by A3 (feat/m2-persistence). Not frozen.
"""Delivery and delivery-file persistence."""

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.ids import DeliveryId, FileId
from ra2.persistence.models import Delivery, DeliveryFile

__all__ = ["DeliveryRepository"]


class DeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, delivery: Delivery) -> None:
        raise NotImplementedError

    async def get(self, delivery_id: DeliveryId) -> Delivery | None:
        raise NotImplementedError

    async def list_all(self) -> list[Delivery]:
        raise NotImplementedError

    async def get_file(self, file_id: FileId) -> DeliveryFile | None:
        raise NotImplementedError

    async def list_files(self, delivery_id: DeliveryId) -> list[DeliveryFile]:
        raise NotImplementedError

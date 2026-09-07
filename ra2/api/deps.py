# FROZEN — see CONTRACTS.md
"""How a router reaches the services `create_app()` wired.

`create_app()` puts the `Services` bundle and the `TaskRunner` on
`app.state`; these dependencies are the only place that is read, and they are
typed, so no router handles an `Any`.

There is **no test-mode branch here** (§12.12): tests build the app with
substitute adapters through `create_app()`'s keyword arguments, and this code
cannot tell the difference.
"""

from typing import Annotated, cast

from fastapi import Depends, Request

from ra2.infra.tasks import TaskRunner
from ra2.services.census_service import CensusService
from ra2.services.container import Services
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.export_service import ExportService

__all__ = [
    "CensusServiceDep",
    "CorpusServiceDep",
    "DeliveryServiceDep",
    "ExportServiceDep",
    "TaskRunnerDep",
    "get_services",
]


def get_services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


def get_task_runner(request: Request) -> TaskRunner:
    return cast(TaskRunner, request.app.state.task_runner)


def get_delivery_service(services: Annotated[Services, Depends(get_services)]) -> DeliveryService:
    return services.delivery


def get_corpus_service(services: Annotated[Services, Depends(get_services)]) -> CorpusService:
    return services.corpus


def get_census_service(services: Annotated[Services, Depends(get_services)]) -> CensusService:
    return services.census


def get_export_service(services: Annotated[Services, Depends(get_services)]) -> ExportService:
    return services.export


DeliveryServiceDep = Annotated[DeliveryService, Depends(get_delivery_service)]
CorpusServiceDep = Annotated[CorpusService, Depends(get_corpus_service)]
CensusServiceDep = Annotated[CensusService, Depends(get_census_service)]
ExportServiceDep = Annotated[ExportService, Depends(get_export_service)]
TaskRunnerDep = Annotated[TaskRunner, Depends(get_task_runner)]

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
from ra2.services.codelist_service import CodelistService
from ra2.services.container import Services
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.evaluation_service import EvaluationService
from ra2.services.export_service import ExportService
from ra2.services.feature_service import FeatureService
from ra2.services.lifecycle_service import LifecycleService
from ra2.services.prompt_service import PromptService
from ra2.services.ranking_service import RankingService
from ra2.services.results_service import ResultsService
from ra2.services.run_service import RunService
from ra2.services.scoring_service import ScoringService

__all__ = [
    "CensusServiceDep",
    "CodelistServiceDep",
    "CorpusServiceDep",
    "DeliveryServiceDep",
    "EvaluationServiceDep",
    "ExportServiceDep",
    "FeatureServiceDep",
    "LifecycleServiceDep",
    "PromptServiceDep",
    "RunServiceDep",
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


def get_codelist_service(services: Annotated[Services, Depends(get_services)]) -> CodelistService:
    return services.codelist


def get_feature_service(services: Annotated[Services, Depends(get_services)]) -> FeatureService:
    return services.feature


def get_prompt_service(services: Annotated[Services, Depends(get_services)]) -> PromptService:
    return services.prompt


def get_evaluation_service(
    services: Annotated[Services, Depends(get_services)],
) -> EvaluationService:
    return services.evaluation


def get_run_service(services: Annotated[Services, Depends(get_services)]) -> RunService:
    return services.run


def get_lifecycle_service(services: Annotated[Services, Depends(get_services)]) -> LifecycleService:
    return services.lifecycle


def get_scoring_service(services: Annotated[Services, Depends(get_services)]) -> ScoringService:
    return services.scoring


def get_results_service(services: Annotated[Services, Depends(get_services)]) -> ResultsService:
    return services.results


def get_ranking_service(services: Annotated[Services, Depends(get_services)]) -> RankingService:
    return services.ranking


DeliveryServiceDep = Annotated[DeliveryService, Depends(get_delivery_service)]
CorpusServiceDep = Annotated[CorpusService, Depends(get_corpus_service)]
CensusServiceDep = Annotated[CensusService, Depends(get_census_service)]
ExportServiceDep = Annotated[ExportService, Depends(get_export_service)]
CodelistServiceDep = Annotated[CodelistService, Depends(get_codelist_service)]
FeatureServiceDep = Annotated[FeatureService, Depends(get_feature_service)]
PromptServiceDep = Annotated[PromptService, Depends(get_prompt_service)]
EvaluationServiceDep = Annotated[EvaluationService, Depends(get_evaluation_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
LifecycleServiceDep = Annotated[LifecycleService, Depends(get_lifecycle_service)]
ScoringServiceDep = Annotated[ScoringService, Depends(get_scoring_service)]
ResultsServiceDep = Annotated[ResultsService, Depends(get_results_service)]
RankingServiceDep = Annotated[RankingService, Depends(get_ranking_service)]
TaskRunnerDep = Annotated[TaskRunner, Depends(get_task_runner)]

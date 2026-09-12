# FROZEN — see CONTRACTS.md
"""The bundle of services both adapters are handed.

`create_app()` builds this once and gives the same instance to the API routers
and to the UI views. Neither adapter constructs a service, and neither reaches
for a global (sw-design.md §3).
"""

from dataclasses import dataclass

from ra2.services.census_service import CensusService
from ra2.services.codelist_service import CodelistService
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.export_service import ExportService
from ra2.services.feature_service import FeatureService

__all__ = ["Services"]


@dataclass(frozen=True, slots=True)
class Services:
    delivery: DeliveryService
    corpus: CorpusService
    census: CensusService
    export: ExportService
    codelist: CodelistService
    feature: FeatureService

# FROZEN (constructor + signatures) — see CONTRACTS.md; bodies owned by B2
"""CSV writers (sw-design.md §7).

Every export is **UTF-8 with a BOM** (Excel on Windows, N3), `;`-delimited,
and carries a header comment line naming the corpus id and version. It writes
the **currently filtered, currently sorted** table — never the whole thing.

Returns `bytes`, not a path: the API streams them and B2's test asserts them
byte-wise, including the BOM.
"""

from typing import Final

from ra2.domain.ids import CorpusId, DeliveryId, FileId
from ra2.infra.clock import Clock
from ra2.services.census_service import CensusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.readmodels import SortDir

__all__ = ["CSV_BOM", "CSV_DELIMITER", "ExportService"]

#: N3 — Excel on Windows needs the BOM to read UTF-8 at all.
CSV_BOM: Final = b"\xef\xbb\xbf"
CSV_DELIMITER: Final = ";"


class ExportService:
    def __init__(
        self,
        *,
        census_service: CensusService,
        delivery_service: DeliveryService,
        clock: Clock,
    ) -> None:
        self._census_service = census_service
        self._delivery_service = delivery_service
        self._clock = clock

    async def census_csv(
        self,
        corpus_id: CorpusId,
        *,
        table_name: str | None = None,
        min_populated_rate: float | None = None,
        sort_key: str = "populated_rate",
        sort_dir: SortDir = SortDir.DESC,
    ) -> bytes:
        """The Census view's "Export CSV" — the current filter and sort.

        No paging: an export is the whole filtered set.
        """
        raise NotImplementedError

    async def findings_csv(self, delivery_id: DeliveryId, file_id: FileId) -> bytes:
        """The file report modal's "Export findings CSV" (sw-design.md §8.3).

        One row per `Finding`: code, severity, key, line number, and the
        `detail` pairs. Never a pre-formatted sentence.
        """
        raise NotImplementedError

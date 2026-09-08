# FROZEN (constructor + signatures) — see CONTRACTS.md; bodies owned by B2
"""CSV writers (sw-design.md §7).

Every export is **UTF-8 with a BOM** (Excel on Windows, N3), `;`-delimited,
and carries a header comment line naming the corpus id and version. It writes
the **currently filtered, currently sorted** table — never the whole thing.

Returns `bytes`, not a path: the API streams them and B2's test asserts them
byte-wise, including the BOM.
"""

import csv
import io
from collections.abc import Sequence
from typing import Final

from ra2.domain.ids import CorpusId, DeliveryId, FileId
from ra2.infra.clock import Clock
from ra2.services.census_service import CensusService
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.errors import NotFoundError
from ra2.services.readmodels import CensusColumnView, SortDir

__all__ = ["CSV_BOM", "CSV_DELIMITER", "ExportService"]

#: N3 — Excel on Windows needs the BOM to read UTF-8 at all.
CSV_BOM: Final = b"\xef\xbb\xbf"
CSV_DELIMITER: Final = ";"

#: Large enough that a real corpus's filtered column set fits on one page;
#: exports have no paging (sw-design.md §7), so this only bounds how many
#: round trips `_all_census_columns` makes, never what it returns.
_EXPORT_PAGE_SIZE: Final = 1000

_CENSUS_CSV_HEADER: Final = (
    "table_name",
    "column_name",
    "type_hint",
    "record_count",
    "populated_count",
    "populated_rate",
    "distinct_count",
    "top_value_share",
    "long_tail",
    "top_values",
)

_FINDINGS_CSV_HEADER: Final = ("code", "severity", "key", "line_no", "detail")


class ExportService:
    def __init__(
        self,
        *,
        census_service: CensusService,
        delivery_service: DeliveryService,
        corpus_service: CorpusService,
        clock: Clock,
    ) -> None:
        self._census_service = census_service
        self._delivery_service = delivery_service
        self._corpus_service = corpus_service
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
        items = await self._all_census_columns(
            corpus_id,
            table_name=table_name,
            min_populated_rate=min_populated_rate,
            sort_key=sort_key,
            sort_dir=sort_dir,
        )
        version = await self._corpus_version(corpus_id)
        comment = (
            f"# corpus {corpus_id} v{version}" if version is not None else f"# corpus {corpus_id}"
        )
        rows = [
            (
                item.table_name,
                item.column_name,
                str(item.type_hint),
                str(item.record_count),
                str(item.populated_count),
                str(item.populated_rate),
                str(item.distinct_count),
                str(item.top_value_share),
                str(item.long_tail),
                "|".join(f"{value.value_raw}:{value.count}" for value in item.top_values),
            )
            for item in items
        ]
        return self._write_csv(comment, _CENSUS_CSV_HEADER, rows)

    async def findings_csv(self, delivery_id: DeliveryId, file_id: FileId) -> bytes:
        """The file report modal's "Export findings CSV" (sw-design.md §8.3).

        One row per `Finding`: code, severity, key, line number, and the
        `detail` pairs. Never a pre-formatted sentence.
        """
        delivery = await self._delivery_service.get(delivery_id)
        file_view = next((f for f in delivery.files if f.file_id == file_id), None)
        if file_view is None:
            raise NotFoundError("delivery_file", file_id)

        comment = f"# delivery {delivery_id} file {file_id}"
        rows = [
            (
                finding.code.value,
                finding.severity.value,
                finding.key or "",
                str(finding.line_no) if finding.line_no is not None else "",
                "|".join(f"{key}={value}" for key, value in sorted(finding.detail.items())),
            )
            for finding in file_view.findings
        ]
        return self._write_csv(comment, _FINDINGS_CSV_HEADER, rows)

    # --- helpers -------------------------------------------------------------

    async def _all_census_columns(
        self,
        corpus_id: CorpusId,
        *,
        table_name: str | None,
        min_populated_rate: float | None,
        sort_key: str,
        sort_dir: SortDir,
    ) -> list[CensusColumnView]:
        """Gathers every page: an export has no paging of its own (sw-design.md
        §7), so this is the one place that walks `CensusService.columns`'s
        pages to completion."""
        items: list[CensusColumnView] = []
        page = 1
        while True:
            result = await self._census_service.columns(
                corpus_id,
                table_name=table_name,
                min_populated_rate=min_populated_rate,
                sort_key=sort_key,
                sort_dir=sort_dir,
                page=page,
                page_size=_EXPORT_PAGE_SIZE,
            )
            items.extend(result.items)
            if not result.items or len(items) >= result.total:
                break
            page += 1
        return items

    async def _corpus_version(self, corpus_id: CorpusId) -> int | None:
        """Best-effort corpus version for the header comment (sw-design.md
        §7's "a header comment line naming the corpus id and version").

        Returns `None` if the corpus is gone (SD4: a corpus outlives its
        delivery, but nothing outlives its own row being deleted) — the
        comment line degrades gracefully rather than raising out of an export.
        """
        try:
            corpus = await self._corpus_service.get(corpus_id)
        except NotFoundError:
            return None
        return corpus.version

    @staticmethod
    def _write_csv(
        comment: str,
        header: Sequence[str],
        rows: Sequence[Sequence[str]],
    ) -> bytes:
        """UTF-8 with BOM, `;`-delimited, comment line before the header row
        (N3, sw-design.md §7). `\\r\\n` throughout so the file is one
        consistent line ending, the way Excel writes its own CSVs."""
        buffer = io.StringIO()
        buffer.write(comment + "\r\n")
        writer = csv.writer(buffer, delimiter=CSV_DELIMITER, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)
        return CSV_BOM + buffer.getvalue().encode("utf-8")

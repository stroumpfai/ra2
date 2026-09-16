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

from ra2.domain.ids import CorpusId, DeliveryId, EvaluationId, FileId
from ra2.infra.clock import Clock
from ra2.services.census_service import CensusService
from ra2.services.corpus_service import CorpusService
from ra2.services.delivery_service import DeliveryService
from ra2.services.errors import NotFoundError
from ra2.services.readmodels import CensusColumnView, PerRecordRow, SortDir

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

#: Tab 2's per-record list. `anonymised` is a column rather than a footnote
#: because mvp-spec.md §13 requires the marking wherever the text is shown, and
#: a CSV is shown somewhere this app cannot see.
_PRESENCE_CSV_HEADER: Final = (
    "record_id",
    "anonymised",
    "record_value",
    "finding",
    "language",
    "language_confidence",
)


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

    def presence_records_csv(
        self,
        rows: Sequence[PerRecordRow],
        *,
        evaluation_id: EvaluationId,
        model_id: str,
        feature_key: str,
    ) -> bytes:
        """Tab 2's per-record list — "the actionable form of Goal 2".

        **Takes the rows rather than fetching them** (`P4-D3`, a correction to
        the signature M27 froze). Two reasons, and the second is the one that
        matters: `ExportService` would otherwise need a `ResultsService` in its
        constructor and a reorder of `create_app`'s wiring for a dependency
        nothing else wants — and, more to the point, §7's rule is that an
        export writes "the **currently filtered, currently sorted** table".
        Re-fetching inside the exporter is how a CSV comes to disagree with the
        screen it was exported from. The caller holds the view; it hands it
        over.

        The conventions are the ones already settled in this module and are
        reused, not re-derived: UTF-8 with a BOM (Excel on Windows, N3),
        `;`-delimited, and a comment line naming what this is a list of.
        """
        comment = (
            f"# evaluation {evaluation_id} · model {model_id} · feature {feature_key} · "
            f"{len(rows)} records recorded but not written"
        )
        return self._write_csv(
            comment,
            _PRESENCE_CSV_HEADER,
            [
                (
                    row.record_id,
                    "yes" if row.anonymised else "no",
                    row.record_value,
                    row.finding,
                    row.language,
                    f"{row.language_confidence:.2f}",
                )
                for row in rows
            ],
        )

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

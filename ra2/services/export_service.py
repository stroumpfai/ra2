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
from ra2.services.readmodels import (
    CensusColumnView,
    MismatchRowView,
    PerRecordRow,
    RunExportView,
    SortDir,
)

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

#: The two tables a run takes with it when it is discarded (sw-design.md
#: §18.3). `analyst_tag` is in the second one because it is the only
#: human-authored column in the pipeline — exporting the rows without it would
#: preserve everything except the part nobody can regenerate.
_RUN_SCORES_CSV_HEADER: Final = (
    "feature_key",
    "language",
    "metric",
    "value",
    "n",
    "ci_low",
    "ci_high",
)

_RUN_MISMATCHES_CSV_HEADER: Final = (
    "mismatch_id",
    "record_id",
    "feature_key",
    "record_value",
    "extracted_value",
    "evidence_span",
    "analyst_tag",
    "tagged_at",
    "note",
)

#: The Mismatches view's export (mvp-spec.md §12, sw-design.md §17.8). Close
#: to `_RUN_MISMATCHES_CSV_HEADER` and deliberately not the same: that one is a
#: run's rows on their way out of the database for good (§18.3), while this one
#: is the **currently filtered, currently sorted** review list, so it carries
#: `anonymised` — the span is record text, and mvp-spec.md §13 requires the
#: marking wherever text is shown, including in a file this app cannot see.
_MISMATCHES_CSV_HEADER: Final = (
    "mismatch_id",
    "record_id",
    "anonymised",
    "feature_key",
    "record_value",
    "extracted_value",
    "evidence_span",
    "analyst_tag",
    "tagged_at",
    "note",
)

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

    def mismatches_csv(
        self,
        rows: Sequence[MismatchRowView],
        *,
        evaluation_id: EvaluationId,
        run_label: str,
        filter_label: str,
    ) -> bytes:
        """The Mismatches view's export — mvp-spec.md §12's "exportable list".

        **Takes the rows** (`P4-D3`, and §7's rule): an export writes the
        currently filtered, currently sorted table, and re-fetching inside the
        exporter is how a CSV comes to disagree with the screen it was
        exported from. The caller holds the view; it hands it over.

        It carries **the tag and the note**, because an export whose whole
        point is review has to carry the review — and because those three
        columns are the only data in the pipeline no re-run can reproduce
        (`SD21`).

        `run_label` and `filter_label` go in the comment line rather than
        being re-derived here: the file has to say which run and which filter
        produced it, and the screen is the only place that knows.

        **M35 freezes this signature. Y1 writes the body.**
        """
        raise NotImplementedError

    def run_scores_csv(self, view: RunExportView) -> bytes:
        """A run's `score` rows, on their way out of the database for good.

        **Takes the view rather than fetching it** — `P4-D3`'s reasoning, and
        here it is load-bearing rather than tidy: the caller has already shown
        these counts to the analyst in the discard dialog, and a second read
        could disagree with what they agreed to.

        `language` is written as stored, `'*'` included (`SD16`): this file
        outlives the database, so translating the all-languages row into
        something prettier would lose the one value that says which row it is.
        """
        comment = (
            f"# run {view.run_id} · evaluation {view.evaluation_id} · "
            f"model {view.model_tag} · {len(view.scores)} score rows"
        )
        return self._write_csv(
            comment,
            _RUN_SCORES_CSV_HEADER,
            [
                (
                    row.feature_key,
                    row.language,
                    row.metric,
                    "" if row.value is None else str(row.value),
                    str(row.n),
                    "" if row.ci_low is None else str(row.ci_low),
                    "" if row.ci_high is None else str(row.ci_high),
                )
                for row in view.scores
            ],
        )

    def run_mismatches_csv(self, view: RunExportView) -> bytes:
        """A run's `mismatch` rows, **with the analyst's own columns**.

        This is the file that makes a discard defensible (§18.3): the tag, the
        timestamp and the note are the only things in the pipeline a re-run
        cannot produce again.

        The evidence spans in it are verbatim narrative. That is what makes the
        export useful to review and what makes the file itself sensitive; it is
        the analyst's to keep, not the app's to circulate (N1 bounds the
        application, not the file it wrote).
        """
        comment = (
            f"# run {view.run_id} · evaluation {view.evaluation_id} · "
            f"model {view.model_tag} · {len(view.mismatches)} mismatches, "
            f"{sum(1 for m in view.mismatches if m.analyst_tag)} tagged"
        )
        return self._write_csv(
            comment,
            _RUN_MISMATCHES_CSV_HEADER,
            [
                (
                    row.mismatch_id,
                    row.record_id,
                    row.feature_key,
                    row.record_value or "",
                    row.extracted_value or "",
                    row.evidence_span or "",
                    row.analyst_tag or "",
                    "" if row.tagged_at is None else row.tagged_at.isoformat(),
                    row.note or "",
                )
                for row in view.mismatches
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

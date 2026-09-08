"""The golden import report (plan-m0-m5.md §6, B1).

`FrozenClock` + `SeededFactory` make the whole flow — register, analyse,
select, freeze — reproducible, so the artefact it produces can be committed and
diffed byte-for-byte. Two independent runs of the same flow, each with fresh
fixtures and a fresh database, must produce the *same bytes*: that is what the
`run` parameter below buys, and it catches the failures a single run cannot —
a dict iterated in insertion order that happens to vary, a `uuid4()` at a call
site, a `datetime.now()` that escaped the `Clock` seam.

Regenerate after an intentional change:

    RA2_GOLDEN_UPDATE=1 uv run pytest tests/backend/services/corpus/test_golden_import_report.py

and read the diff before committing it. A golden file updated without reading
the diff is worse than no golden file.
"""

import json
import os

import pytest

from ra2.persistence.models import Corpus
from ra2.services.delivery_service import dump_json
from ra2.services.protocols import CensusInput
from ra2.services.readmodels import CorpusView, DeliveryView

pytestmark = pytest.mark.backend

GOLDEN_FILE = "import_report_hazards.json"


def _artefact(
    corpus_view: CorpusView,
    corpus_row: Corpus,
    delivery_view: DeliveryView,
    census: CensusInput,
) -> bytes:
    """Everything one import produced, in a fixed key order (M0-D8).

    `*_json` columns are re-parsed and re-embedded so the committed file is one
    readable document rather than JSON inside JSON. `json.loads` preserves
    order, so the app still controls it end to end.
    """
    assert delivery_view.analysed_at is not None, "the golden delivery is analysed by construction"
    payload = {
        "delivery": {
            "name": delivery_view.name,
            "source_kind": delivery_view.source_kind.value,
            "status": delivery_view.status.value,
            "created_at": delivery_view.created_at.isoformat(),
            "analysed_at": delivery_view.analysed_at.isoformat(),
            "selected_record_count": delivery_view.selected_record_count,
        },
        "files": [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "relative_path": f.relative_path,
                "byte_size": f.byte_size,
                "sha256": f.sha256,
                "file_kind": f.file_kind.value,
                "set_key": f.set_key,
                "canton": f.canton,
                "encoding": f.encoding,
                "encoding_detected": f.encoding_detected,
                "delimiter": f.delimiter,
                "quote_char": f.quote_char,
                "row_count": f.row_count,
                "ok_count": f.ok_count,
                "recovered_count": f.recovered_count,
                "rejected_count": f.rejected_count,
                "header_ok": f.header_ok,
                "selected": f.selected,
                "findings": [
                    {
                        "code": finding.code.value,
                        "severity": finding.severity.value,
                        "key": finding.key,
                        "line_no": finding.line_no,
                        "detail": {name: finding.detail[name] for name in sorted(finding.detail)},
                    }
                    for finding in f.findings
                ],
            }
            for f in delivery_view.files
        ],
        "corpus": {
            "corpus_id": corpus_view.corpus_id,
            "name": corpus_view.name,
            "version": corpus_view.version,
            "description": corpus_view.description,
            "imported_at": corpus_view.imported_at.isoformat(),
            "record_count": corpus_view.record_count,
            "is_dev_sized": corpus_view.is_dev_sized,
            "cp1252_canary_count": corpus_view.cp1252_canary_count,
            "language_counts": dict(corpus_view.language_counts),
        },
        "source_file_manifest": json.loads(corpus_row.source_file_manifest_json),
        "import_report": json.loads(corpus_row.import_report_json),
        "census_input": {
            "record_count": census.record_count,
            "tables": [
                {
                    "table_name": table.table_name,
                    "column_count": len(table.columns),
                    "cell_count": len(table.cells),
                }
                for table in census.tables
            ],
        },
    }
    # `write_bytes`, not `write_text`: the committed file must be identical on
    # Windows and Linux, and text mode would translate the newline (N3).
    return (dump_json(payload) + "\n").encode("utf-8")


@pytest.mark.parametrize("run", [1, 2])
async def test_the_golden_import_report_is_byte_identical_on_every_run(
    run,
    corpus_service,
    delivery_service,
    analysed_golden_delivery,
    census_materialiser,
    golden_dir,
    db_session_factory,
):
    delivery_id = await analysed_golden_delivery()
    corpus_id = await corpus_service.freeze(
        delivery_id, name="hazards", description="the twelve hazards, frozen"
    )

    async with db_session_factory() as session:
        corpus_row = await session.get(Corpus, corpus_id)
        produced = _artefact(
            await corpus_service.get(corpus_id),
            corpus_row,
            await delivery_service.get(delivery_id),
            census_materialiser.only[2],
        )

    path = golden_dir / GOLDEN_FILE
    if os.environ.get("RA2_GOLDEN_UPDATE"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(produced)

    assert path.is_file(), f"missing golden file {path}; regenerate with RA2_GOLDEN_UPDATE=1"
    assert produced == path.read_bytes(), (
        f"run {run} diverged from the committed golden report; "
        "regenerate with RA2_GOLDEN_UPDATE=1 and read the diff"
    )


async def test_the_golden_report_still_names_every_hazard_it_was_cut_for(golden_dir):
    """A guard on the fixture itself.

    A golden file is only worth diffing while it still contains the hazards it
    was built to pin down. If a future change quietly stops emitting one of
    these, the byte comparison above would fail — but so would a hundred
    cosmetic changes, and the reason would be buried in the diff. This says it
    out loud.
    """
    payload = json.loads((golden_dir / GOLDEN_FILE).read_bytes().decode("utf-8"))
    codes = {finding["code"] for finding in payload["import_report"]}

    assert "ROW_REJECTED_FIELD_COUNT" in codes  # h03: a stray `|` in a wide row
    assert "COUNT_MISMATCH_OBJ" in codes  # h10: AnzObjFeld disagrees
    assert "COUNT_MISMATCH_PERS" in codes  # h10: BeteiligtePersTotalFeld too
    assert "TEXT_KEY_UNMATCHED" in codes  # a narrative with no `unfall` row
    assert "CP1252_CANARY_ZERO" in codes  # h09: French, and zero canary chars
    assert payload["corpus"]["cp1252_canary_count"] == 0
    assert payload["corpus"]["language_counts"] == {"fr": 2}
    # Every rejected and recovered row is named by its key (§4.2.4, §12.6).
    assert all(
        finding["key"]
        for finding in payload["import_report"]
        if finding["code"].startswith(("ROW_", "COUNT_MISMATCH", "TEXT_KEY"))
    )

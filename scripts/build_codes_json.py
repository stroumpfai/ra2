#!/usr/bin/env python
"""Build an importable `codes.json` from the ASTRA `UAP_Referenzen.csv` export.

    uv run python scripts/build_codes_json.py SRC.csv OUT.json [--as-of YYYYMMDD]

The output is the shape `ra2.domain.codes.CodelistImportSchema` validates
(sw-design.md §14.1) and is uploaded through the Codelists view like any other
input. It is **not** committed: it is the analyst's working copy, and it lives
outside the repo.

Rules, all of them visible in the printed report rather than applied quietly:

- **Only codes valid on `--as-of`** (default: today) are kept: `Gültig von` on
  or before it, `Gültig bis` empty or on/after it. `Gültig bis` arrives as a
  float (`20171231.0`).
- **One attribute per `Kategorie`**, keyed by the category number; the code is
  `Code UAP`.
- **A category with no `Code UAP` at all** is keyed by `Referenz` instead —
  there is nothing else to key it by.
- **A row with no `Code UAP` in a category that has codes** is a group heading
  (e.g. 1700 "Auffahrunfall"); it is left out and listed in the report.
- **Two current rows with the same code in one category** fail the build: the
  CSV is ambiguous and choosing one would be a silent repair.

The CSV carries no category names, so each attribute is named
"Kategorie N" in all three languages, except where `NAMES` says otherwise.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from ra2.domain.codes import validate_import

LANG_COLUMNS = (("de", "Beschreibung DE"), ("fr", "Beschreibung FR"), ("it", "Beschreibung IT"))

# The category's own heading row, where the CSV has one.
NAMES: dict[str, dict[str, str]] = {
    "1700": {"de": "Unfalltyp", "fr": "Type d'accident", "it": "Tipo di incidente"},
}


def _date(cell: str) -> int | None:
    return int(float(cell)) if cell.strip() else None


def _is_current(row: dict[str, str], as_of: int) -> bool:
    valid_from = _date(row["Gültig von"])
    valid_to = _date(row["Gültig bis"])
    return (valid_from is None or valid_from <= as_of) and (valid_to is None or valid_to >= as_of)


def _labels(row: dict[str, str]) -> dict[str, str]:
    return {lang: row[column] for lang, column in LANG_COLUMNS if row[column].strip()}


def _category_order(category: str) -> tuple[bool, int, str]:
    return (not category.isdigit(), int(category) if category.isdigit() else 0, category)


def build(
    rows: list[dict[str, str]], as_of: int
) -> tuple[dict[str, object], list[tuple[str, str, str]]]:
    """Return the codelist document and the rows left out as group headings."""
    by_category: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if _is_current(row, as_of):
            by_category[row["Kategorie"]].append(row)

    document: dict[str, object] = {}
    headings: list[tuple[str, str, str]] = []
    for category in sorted(by_category, key=_category_order):
        category_rows = by_category[category]
        keyed_by_referenz = all(not row["Code UAP"].strip() for row in category_rows)
        codes: dict[str, dict[str, str]] = {}
        for row in category_rows:
            code = (row["Referenz"] if keyed_by_referenz else row["Code UAP"]).strip()
            if not code:
                headings.append((category, row["Referenz"], row["Beschreibung DE"]))
                continue
            if code in codes:
                raise SystemExit(f"category {category}: code {code!r} is current on two rows")
            codes[code] = _labels(row)
        name = NAMES.get(
            category,
            {
                "de": f"Kategorie {category}",
                "fr": f"Catégorie {category}",
                "it": f"Categoria {category}",
            },
        )
        document[category] = {"name": name, "codes": codes}
    return document, headings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("src", type=Path, help="UAP_Referenzen.csv (UTF-8)")
    parser.add_argument("out", type=Path, help="codes.json to write")
    parser.add_argument(
        "--as-of", type=int, default=int(date.today().strftime("%Y%m%d")), help="YYYYMMDD"
    )
    args = parser.parse_args()

    with args.src.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    document, headings = build(rows, args.as_of)
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"

    result = validate_import(text)
    if isinstance(result, list):
        for error in result:
            print(f"invalid: {error.path}: {error.message}", file=sys.stderr)
        return 1

    args.out.write_bytes(text.encode("utf-8"))
    print(f"{len(rows)} rows read, as of {args.as_of}")
    print(f"{len(result.attributes)} attributes, {len(result.values)} codes -> {args.out}")
    print(f"{len(headings)} group-heading rows left out:")
    for category, referenz, label in headings:
        print(f"  {category} / {referenz}: {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

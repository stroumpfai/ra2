# Golden import reports (B1)

`import_report_hazards.json` is the byte-for-byte output of one whole import —
register, analyse, select, freeze — over a delivery composed from four of the
committed hazard fixtures. It is asserted by
`tests/backend/services/corpus/test_golden_import_report.py`.

## What is in the delivery, and why

| File in the delivery | Comes from | What it pins down |
|---|---|---|
| `unfall.txt` | `h03_stray_delimiter` | a stray `\|` in a 67-column row: **detected, never repaired**, rejected and reported with its key |
| `objekt.txt` | `h10_count_mismatch` | two `objekt` rows against an `AnzObjFeld` that says otherwise |
| `person.txt` | `h10_count_mismatch` | `person` hanging off `objekt`, not off `record` |
| `text.csv` | `h09_fr_lossy` | French whose cp1252-only characters were already deleted upstream |

Together they produce a report with something in every section: a rejected row,
both count mismatches, a narrative whose `UNFALLUID` matches no surviving
`unfall` row (the rejected one), and — because the corpus contains French and
**zero** Windows-1252-only characters — `CP1252_CANARY_ZERO`, the one finding
that proves the lossy conversion happened (mvp-spec.md §4.4).

Nothing here comes from a real delivery: the hazards are synthesised
byte-exactly by `../deliveries/generate_hazards.py` (§12.11).

## What makes it reproducible

`FrozenClock` (one fixed instant) and `SeededFactory` (same seed, same id
sequence) are injected through the service constructors, and the language
detector is real and pure. Nothing in the flow calls `datetime.now()` or
`uuid4()` at a call site, which is exactly what this file catches if it ever
starts to.

Upload order is part of the fixture — ids are handed out in call order — so
`GOLDEN_DELIVERY` in `../../backend/services/corpus/conftest.py` is a tuple,
not a directory listing.

## Regenerating

```
RA2_GOLDEN_UPDATE=1 uv run pytest tests/backend/services/corpus/test_golden_import_report.py
```

Then **read the diff before committing it**. A golden file updated without
reading the diff is worse than no golden file: it converts a caught regression
into a committed one.

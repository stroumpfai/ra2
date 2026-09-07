# Fixtures

Real data is gitignored and **must never reach a test** (sw-design.md §12.11),
so every hazard is synthesised byte-exactly by `generate_hazards.py` and
committed.

```
deliveries/hazards/     synthetic, byte-crafted, committed   (A1)
generate_hazards.py     regenerates them, readable           (A1)
factories.py            corpus/record/census builders        (B2)
golden/                 committed golden import reports      (B1)
```

Clean fixtures are not acceptable (mvp-spec.md §15). The twelve hazards are
h01 cp1252 · h02 undecodable · h03 stray delimiter · h04 embedded newline ·
h05 unquoted newline · h06 orphan objekt · h07 duplicate UID across cantons ·
h08 all-empty column · h09 French already lossy · h10 count mismatch ·
h11 unmatched text key · h12 unknown header.

Each has a named test asserting the exact `FindingCode` **and** that the
offending key appears in the report.

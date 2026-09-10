# Amendment: `ra2/domain/findings.py`

## Which file

`ra2/domain/findings.py` — the `FindingCode` enum and `DEFAULT_SEVERITY`
table.

## Why

Support for the second (Astrana) structured-file import format needs to drop
a wholly-blank artifact record (Astrana's doubled-CRLF line terminator,
`\r\r\n`, produces one blank physical line after every real row). Left in
place, that blank row is never a key anchor, so `recover_rows` would fold it
into the *next* real record as an unrepairable continuation and reject the
wrong row.

The fix filters the blank row out in `ra2/domain/parsing/analysis.py`,
before `recover_rows` ever sees it — but CLAUDE.md Do-NOT #6 and this same
file's own documented invariant ("a parser that drops ... a row without
emitting one of these is a bug with a named regression test") require every
dropped row to still carry a `Finding`. No existing code fit: `ROW_RECOVERED`
is for a row that *was* reassembled, not dropped; `ROW_REJECTED_*` codes
apply to a real (non-blank) row that failed to parse or match the expected
field count. A blank row is neither.

## The diff

Added one `FindingCode` member and its default severity entry:

```python
# FindingCode, after ROW_REJECTED_PARSE_ERROR:
ROW_BLANK_DROPPED = "ROW_BLANK_DROPPED"

# DEFAULT_SEVERITY:
FindingCode.ROW_BLANK_DROPPED: Severity.REPORTED,
```

`REPORTED`, not `BLOCKING` — matches `ROW_RECOVERED`'s treatment: this is
routine export-tool noise, not a delivery defect. `Finding.key` is `None`
for this code (a blank row has none), the same pattern already used by
`CP1252_CANARY_ZERO`.

## What I did instead

Nothing — this amendment documents a change already applied directly
(`RESOLVED`), the same way `feat-m2-persistence.md` records a settled fix.
The phase-1 parallel-wave process this file's "propose only, don't touch"
instructions were written for has concluded (M0–M8 merged); this is a
single-agent change under direct user approval, recorded here for the
historical trail `CONTRACTS.md` asks for.

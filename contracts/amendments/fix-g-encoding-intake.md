# Amendment: `fix-g-encoding-intake` (risks G1, G2, G4)

> **APPLIED in the same commit**, as `fix-a5-bound-parameters` and the other
> risk slices were. No wave is running.

One frozen file, three enum members and their three severities.
`risk-assesment.md` §5 rows **22**, **23** and **24** (G2, G1, G4), all
*verified* at `12268ed` and all in Gate 1: *before the code freeze*.

| Row | Asked for | State before this commit |
|---|---|---|
| 22 · G2 | Refuse UTF-16/32 BOMs and NUL bytes in `detect_encoding`, each with its own `FindingCode` | **Absent.** Only the UTF-8 BOM was recognised. A UTF-16-LE file with a BOM decoded as cp1252 (`ÿþU\x00n\x00…`), one without decoded as UTF-8, and both then failed as `UNKNOWN_HEADER` |
| 23 · G1 | An intake mojibake canary, the mirror image of `CP1252_CANARY_ZERO`: one `FindingCode`, no schema change | **Absent.** One cp1252 byte turned a whole UTF-8 file into cp1252. The analyst saw `ENCODING_DETECTED: cp1252`, REPORTED, and nothing else |
| 24 · G4 | `h15_mixed_encoding`, the hazard `CLAUDE.md` has required by name since month one | **Absent.** `h01`–`h14`, none of them mixed |

---

## 1. `ra2/domain/findings.py`: three codes

```diff
     FILE_UNDECODABLE = "FILE_UNDECODABLE"
+
+    #: The bytes open with a UTF-16 or UTF-32 byte-order mark. The file
+    #: **fails**, under an encoding override too: decoded as UTF-8 or cp1252
+    #: it would be NUL-riddled text failing later as `UNKNOWN_HEADER`, which
+    #: names the wrong cause.
+    #: detail: {"bom": "utf-16-le"}                                    (h16)
+    FILE_UNSUPPORTED_BOM = "FILE_UNSUPPORTED_BOM"
+
+    #: The bytes contain a NUL, which no delivery format uses. The file
+    #: **fails**, under an encoding override too. Usually a UTF-16 file
+    #: written without a byte-order mark.
+    #: detail: {"byte_offset": "..."}                                  (h17)
+    FILE_CONTAINS_NUL = "FILE_CONTAINS_NUL"
+
+    #: A file decoded as cp1252 contains well-formed multi-byte UTF-8
+    #: sequences, so some of its text was written as UTF-8 and now reads as
+    #: mojibake (`Ã¼` for `ü`). ...
+    #: detail: {"sequences": "3", "first_byte_offset": "...",
+    #:          "first_line_no": "..."}                                (h15)
+    UTF8_READ_AS_CP1252 = "UTF8_READ_AS_CP1252"
```

```diff
     FindingCode.FILE_UNDECODABLE: Severity.BLOCKING,
+    FindingCode.FILE_UNSUPPORTED_BOM: Severity.BLOCKING,
+    FindingCode.FILE_CONTAINS_NUL: Severity.BLOCKING,
+    FindingCode.UTF8_READ_AS_CP1252: Severity.REPORTED,
```

The class docstring's hazard range goes from `h01-h12` to `h01-h17`.

**Why three codes and not one.** The whole of G2 is that the finding named the
wrong cause. A single "bad encoding" code would repeat the defect one level
up. The BOM case names the encoding; the NUL case names the offset, because
a UTF-16 file without a mark is recognisable only by its NULs.

**Why the two refusals are blocking and ignore the override.** They match
`FILE_UNDECODABLE` (h02), including `test_h02_fails_under_an_explicit_override_too`.
Neither refusal is a guess: no delivery format has a use for NUL. An override
is exactly how the text would get through, because cp1252 decodes a UTF-16
file without complaint. So `refuse` runs ahead of the override in
`analyse_file` as well as inside `detect_encoding`.

**Why the canary is REPORTED, per file, at analysis.** G1 proposed a
corpus-level count at freeze. It is per file instead, for two reasons.
Analysis is when the analyst can still ask for a re-export. And a
non-blocking file finding already reaches `corpus.import_report_json`, so the
corpus carries it anyway (`test_mojibake_found_at_analysis_reaches_the_import_report`).
It is not blocking because a genuine cp1252 file can contain the same bytes,
for example `ß` followed by a non-breaking space. This is the reasoning that
keeps `CP1252_CANARY_ZERO` REPORTED. It is evidence, not a verdict.

**Why no schema change.** The count, the first byte offset and the first line
all live in `detail`. `corpus.cp1252_canary_count` has no sibling column, and
none is needed: the finding is per file, and the file's findings are already
stored on `delivery_file.findings_json`.

## What else changed (not frozen)

| Path | What |
|---|---|
| `ra2/domain/parsing/encoding.py` | + `refuse`, `UnsupportedBom`, `NulByte`, `Refused`; + `utf8_sequences`, `Utf8Sequences` (RFC 3629 well-formed only: no overlongs, surrogates or code points past U+10FFFF; a leading UTF-8 BOM is not counted) |
| `ra2/domain/parsing/analysis.py` | `refuse` before detection *and* override; `UTF8_READ_AS_CP1252` after `ENCODING_DETECTED` whenever the effective encoding is cp1252, whether detected or chosen; the three identical failure returns folded into `_failed` |
| `ra2/ui/views/file_report_modal.py` | Labels for the three codes, plus `ROW_BLANK_DROPPED`, which had none since `feat-astrana-import` and rendered as its bare enum name |
| `tests/fixtures/deliveries/generate_hazards.py`, `hazards/h15`–`h17` | `h15_mixed_encoding` (UTF-8 rows then one cp1252 row), `h16_utf16_bom`, `h17_utf16_no_bom`. The existing fourteen regenerate byte-identical |
| `tests/unit/parsing/test_encoding_detection.py`, `test_hazards_h01_h12.py` | Every wide BOM by name (UTF-32-LE before UTF-16-LE), NUL offsets, the override path, `utf8_sequences` on well-formed and malformed input, and **h01 as the negative control**: genuine cp1252 German raises no mojibake finding |
| `tests/backend/services/{delivery/test_analyse,corpus/test_freeze}.py` | Through the service and the JSON round trip; a refused file blocks the freeze until it is deselected; the mojibake finding reaches the corpus report |
| `tests/api/openapi_snapshot.json` | Regenerated: `FindingCode` is on the wire, so there are three additive enum values and the docstring's `h01-h17`. Nothing else moved |
| `tests/ui/test_import_view.py` | `test_every_finding_code_has_a_label`, so the next new code cannot fall through to the fallback silently |
| `sw-design.md` | §6.2 step 1, §11.4's table (h13–h17), `SD44` |
| `mvp-spec.md` | §4.2 step 1 and §4.3's reported list. A *what* change, so it lands here as well |
| `README.md` | *Fixtures contain the real hazards*: seventeen, and the "one named hazard is still missing" callout replaced |
| `docs/risk-assesment.md` | §5 rows 22–24, §8.8 |

## What I did instead of a shim

Nothing. The amendment is applied in this commit.

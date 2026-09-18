# Amendment — `fix/b1-census-value-samples` (risk B1)

> **APPLIED in the same commit**, as `fix-c1-real-data-guard` and
> `fix-c2-agent-data-access` were. No wave is running.

Three frozen files. `risk-assesment.md` B1: *the census export contains
verbatim identifying values*, severity **High**, control status **absent**,
verified by aggregate query against the working corpus:

| column | stored top values | of which occur exactly once |
|---|---|---|
| `unfall.Koordinate X` / `Y` / `E` / `N` | 20 each | 16–18 each |
| `unfall.Unfall-UID`, `objekt.Objekt-UID`, `person.Person-UID` | 20 each | 20 each |

A coordinate that occurs once is one accident, at metre precision. A UID is the
record key. Both were exported, in the file whose entire purpose is to be shown
to other people, and nothing marked it.

---

## 1. `ra2/domain/census.py` — the rule, stated once

```diff
+SHAREABLE_TYPE_HINTS: Final = frozenset({TypeHint.ENUM})
+
+
+def sample_is_shareable(type_hint: TypeHint) -> bool: ...
```

**Why in `domain`.** Two callers need the same answer: `census_service` builds
the read model the Census view and the API render, and `export_service` writes
the CSV. A rule stated twice is a rule that drifts, and the half that drifts is
the half nobody looks at. This is the shape `classify_endpoint` has for the
loopback rule, and the set is written out the way `LOOPBACK_HOSTS` is so the
whole of what is permitted is one readable line with a test asserting it by
equality.

**Why `ENUM`.** It is the delivery's own marking that a column holds codes
rather than data — the suffix rule (`Ausw` in RADIS, `` UAP`` in Astrana)
decides it from the header before any value is inspected, so the judgement
comes from the data dictionary rather than from a guess about the values.

**The cost, chosen rather than discovered.** A code appearing in a single
record is still exported, because the line is drawn at the header rather than
at a frequency; and Astrana's `Kanton Kürzel` — a two-letter canton code by any
reading — loses its sample because that format does not use the suffix. Both
follow from deciding by header, and the alternative considered was a frequency
floor reusing `Settings.min_cell_count` (20), which would have caught the rare
code and kept the canton. The header rule was chosen: it is one sentence a
reader can check against the data dictionary, and it does not make the
deliverable's contents depend on how large the corpus happens to be.

---

## 2. `ra2/services/readmodels.py` — `CensusColumnView.top_values_withheld`

```diff
     top_values: tuple[ValueCount, ...] = ()
     in_config: bool = False
+    top_values_withheld: bool = False
```

**The flag is not decoration.** `top_values == ()` already had a meaning: the
column is **empty in every row** — a real delivered state, hazard h08, and the
Reminder card exists because it is easy to misread. "Empty in every row" says
*do not pick this as a feature*. "Withheld" says *nothing about this column at
all*. Collapsing the two would hand a reader the opposite conclusion from the
one the data supports.

`ra2/api/schemas.py` gains the matching field so the distinction survives the
wire, and `ra2/api/v1/census.py` maps it.

**`tests/api/openapi_snapshot.json` is regenerated**, which is the committed
wire contract and its own drift gate. The diff is exactly five lines — one
optional boolean with a `false` default on `CensusColumnResponse` — so the
change is additive and no existing client breaks. Worth stating because a
regenerated snapshot is the easiest place in this repository for an unintended
wire change to ride along unnoticed; this one was checked line by line.

---

## 3. `ra2/services/export_service.py` — `CLASSIFICATION_COMMENT`, and one column

```diff
+CLASSIFICATION_COMMENT: Final = (
+    "# SENSITIVE — derived from non-anonymised police accident records."
+)
```

Written by `_write_csv`, which is the one place **all six** exports pass
through — census columns, findings, the per-record presence list, the mismatch
list with its evidence spans, and a discarded run's two files. One place means
the line is guaranteed rather than remembered. It is written **first**, above
the corpus comment, because the first line of a file is the one a reader sees
before deciding what to do with it.

It states a fact about provenance rather than a classification level. This
project has agreed no classification scheme and `vision.md` defines none;
a label invented here would claim an authority it does not have. When the
governance page exists (risk F1), a formal marking belongs in this constant and
nowhere else.

`_CENSUS_CSV_HEADER` gains `top_values_withheld`, for the reason in §2.

---

## 4. Not frozen, and changed

`ra2/services/census_service.py` applies the rule in `_to_view` — **read time,
never write time**. The values stay in `census_value`; they are on the host
either way, and a corpus is immutable, so a write-time filter would leave every
corpus frozen before today still carrying them into every export. Suppressing
on the way out covers the corpora that already exist and needs no migration. It
is the shape `SD19` settled for scoring cells, for the same reason.

`ra2/ui/views/census_view.py` renders the third bar state. The view branches on
the **flag**, not on an empty tuple, so the property holds for any caller of
this read model and not only for the one that empties it —
`test_the_view_withholds_on_the_flag_even_if_it_is_handed_values` hands it the
contradictory state to prove the branch is load-bearing.

The screen holds to the rule the export holds to because the screen is the
easier of the two places to copy a value out of by hand.

---

## 5. Tests

Nineteen assertions across four layers. The ones worth naming:

- `tests/unit/census/test_sample_rule.py` — the boundary on its own terms, the
  way `test_long_tail.py` tests `_is_long_tail` rather than only `compute_census`.
- `tests/backend/services/census/test_census_service.py` — the existing
  hand-computed fixture already held all three states (`UnfallUid`: five values
  each occurring once; `WetterAusw`: coded; `StrasseName`: empty in every row),
  so it now asserts them rather than needing a new fixture. The same is true of
  `tests/backend/api/census/test_census_columns.py` over the wire.
- `tests/backend/api/census/test_census_export.py` — the finding in two rows,
  byte-exact, plus the classification line.
- `tests/ui/test_census_view.py` — three harness rows and the contradictory
  one. Verified to fail with the view's branch removed.

Twenty-five existing tests moved by one line because the preamble grew. Where a
file indexed positionally in more than one place, the offsets are now named
constants rather than repeated literals.

---

## What this does not do

**B2 is untouched.** The mismatch list carries **evidence spans** — verbatim
narrative fragments, mandatory by design — and the per-record lists and the
evaluation report carry their own content. Those now leave with a line saying
what they are, which is not the same as a rule about what may be in them. B1
was about a sample nobody had decided to include; B2 is about content the
design requires, and it needs a decision rather than a predicate.

**Nothing here screens an export before it is shared.** The file says what it
is; a person still has to read it. That is B1's third recommendation and it is
a runbook sentence, which this repository does not yet have (risk F1).

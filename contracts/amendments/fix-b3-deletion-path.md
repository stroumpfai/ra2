# Amendment — `fix/b3-deletion-path` (risk B3)

> **APPLIED in the same commit**, as `fix-c1-real-data-guard`,
> `fix-c2-agent-data-access` and `fix-b1-census-value-samples` were. No wave is
> running.

Four frozen files. `risk-assesment.md` **B3** — *no retention limit, no
deletion path, no end-of-PoC destruction*, severity **High**, control status
**absent** — re-checked at §8.5 against `af0150f`, which had already built the
deletion path from `plan-reset-and-discard.md`. What that left is what this
amendment closes:

| B3 asked for | State before this commit |
|---|---|
| A delete for a delivery | **Done** in `af0150f`, along with run and evaluation discard |
| `VACUUM` after a delete | **Absent.** Reproduced: 572 readable occurrences of a deleted evidence span remained in the file |
| A retention period and a destruction path | **Absent.** The words appeared in no document in the repository |

---

## 1. `ra2/persistence/session.py` — a fourth connect-time PRAGMA

```diff
         cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
+        cursor.execute("PRAGMA secure_delete=ON")
```

The contract row reads *"the three connect-time PRAGMAs"*; it now reads four.
The module docstring and `_apply_pragmas`'s docstring carry the reason.

**Why here and not a `VACUUM` after each discard**, which is what B3's
recommendation asked for:

- a `VACUUM` is a **second thing to remember**, at every call site that ever
  deletes, and the first one forgotten is silent;
- in WAL mode a `VACUUM` alone changes nothing observable — the rebuild lands
  in `-wal` and the main file is untouched until a checkpoint, so the
  instruction is only half an instruction;
- it **cannot run inside the transaction** `discard_run` already holds, so it
  would need its own connection and its own failure handling, for an operation
  whose failure nobody would notice;
- `secure_delete` zeroes the page **as it is freed**, which is the property
  actually wanted, and it is stated once in the file that §4.4 already says
  owns the pragmas — *nowhere else*.

**Why it is set rather than trusted.** `PRAGMA secure_delete` defaults from a
compile-time flag of whatever SQLite the interpreter bundles. It reads back
`0` here (3.50.4), and a different build could read back `1` — which is
precisely why neither value is a thing to assume.

**The cost.** Zeroing freed pages costs write throughput on delete-heavy
workloads. This application deletes in exactly one place, by a person, at
human speed. `SD29`.

---

## 2. `ra2/infra/config.py` — `Settings.exports_dir` is removed

```diff
-    @property
-    def exports_dir(self) -> Path:
-        """Where CSV exports are written."""
-        return self.data_dir / "exports"
```

It was documented as *"where CSV exports are written"*. Nothing in `ra2/`
wrote there — every one of the six exports is built in memory and streamed to
the browser — and its only readers were `scripts/reset_data.py` and that
script's test. So `just reset` cleared an empty directory and reported having
cleared it, while the exports that matter sat in the analyst's Downloads
folder.

This is `Settings.host` from finding A4, the same shape: **a setting that
implies a control nobody implemented.** A4's recommendation is *honour it or
delete it*, and the same choice applies here.

**§8.5's proposition said to build it, and looking at the code changed the
answer.** Building it means five UI call sites and five API routes writing
through a store; and, decisively, **a server-side copy does not replace the
downloaded one — it adds a second copy at rest**, unpruned, of the artefact
`B2` says nothing governs. For a finding about data that outlives its purpose,
that is the wrong direction. `SD30`.

`mvp-spec.md` is untouched: N7 is about *the database* being a single SQLite
file under a configurable directory and says nothing about exports. The
overstatement was in `sw-design.md` §10's gloss and in `README.md`, and both
are corrected.

---

## 3. `ra2/ui/components/discard_dialog.py` — what the export costs

```diff
+EXPORT_LEAVES_RA2 = (
+    "The file carries verbatim narrative and leaves RA2's control — "
+    "nothing the app deletes can reach it again."
+)
```

Rendered beside `EXPORT_PROMPT`, in the same `has_exportable` branch, with
`data-testid="discard-export-warning"`.

`SD23` pays for the one destructive verb with an export, and
`run_mismatches_csv` carries `evidence_span` — verbatim narrative. So the
single place in the product where a person is told *this cannot be undone* is
also the single place it offers to make a copy that nothing here can ever
delete. Saying both costs one string, and the sentence is asserted like
`DISCARD_KEEPS` and `DISCARD_IRREVERSIBLE` are: load-bearing copy is a
deliverable in this project (`plan-phase-4.md` R8).

---

## 4. `scripts/reset_data.py` — one fewer target

```diff
         settings.deliveries_dir,
         settings.codelists_dir,
-        settings.exports_dir,
     ]
```

Consequence of §2. The docstring now says why there is no `exports/` target,
so the absence reads as a decision rather than an omission, and points at
`data-handling.md` §4 — where a person is told to go and delete the downloads
by hand, which is the only thing that actually works.

---

## 5. Not frozen, and changed

| Path | What |
|---|---|
| `tests/backend/persistence/test_session_pragmas.py` | + `test_secure_delete_pragma_is_on`, reading the pragma back off the real engine |
| `tests/backend/services/lifecycle/test_discard_erasure.py` *(new)* | The property the pragma exists for, through the real service against the real temp-file database: after `discard_run`, a planted evidence span is **not in the database or its WAL**. With a positive control before the discard, and a control (`secure_delete` off) showing the bytes survive without it |
| `tests/backend/scripts/test_reset_data.py` | + `test_a_reset_has_no_exports_target` — the absence is the contract, asserted on both halves |
| `tests/ui/test_discard_dialog.py` | + `test_the_export_offer_says_the_file_leaves_ra2`, and the "nothing to export" test now also asserts the warning is absent |
| `tests/e2e/test_reset_discard.py` | The discard journey asserts the new sentence beside `DISCARD_KEEPS` and `DISCARD_IRREVERSIBLE`, the two it already asserted. Load-bearing copy is checked in the browser as well as in the component (`sw-design.md` §8.2) |
| `sw-design.md` | §4.4 (the fourth pragma), §10 (the `RA2_DATA_DIR` gloss), `SD29` + `SD30`, and **§18.7 — *What a discard erases***, which is the section that did not exist: §18.1 said *whole objects*, and nothing said what *removed* meant |
| `README.md` | Two claims corrected — exports do **not** live under the data directory — plus a pointer to `data-handling.md` from *Real data never enters the repository* and the documentation map |
| `data-handling.md` *(new)* | Outputs, retention, the numbered destruction procedure, the incident path, the decommission condition. Recommendations 11, 14 and 20 of the review. **Every project decision in it is marked DECISION REQUIRED and left blank** — an implementing agent can write the procedure, and must not invent a retention period or a named owner |
| `risk-assesment.md` | §8.6, and the statuses in §1 and §5 |

**Unchanged, deliberately:** `ra2/persistence/models.py`, `alembic` (no
migration — nothing about this is schema), `ra2/services/export_service.py`
(the exports themselves are correct; what was missing was a rule about where
they go), `.importlinter`, `pyproject.toml`, `tests/conftest.py`, `mvp-spec.md`.

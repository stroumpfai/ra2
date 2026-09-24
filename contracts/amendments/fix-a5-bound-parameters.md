# Amendment — `fix/a5-bound-parameters` (risk A5)

> **APPLIED in the same commit**, as `fix-b3-deletion-path`,
> `fix-c1-real-data-guard` and `fix-b1-census-value-samples` were. No wave is
> running.

One frozen file, one line. `risk-assesment.md` **A5** — *a database error
writes the narrative and the record key into `run.error`, and from there into
the log*, severity **High**, control status **absent**, **verified** at
`12268ed` — re-reproduced here through the real service rather than through a
harness:

```
WARNING ra2.services.run_service: run run-a-1: failed — IntegrityError:
  (sqlite3.IntegrityError) synthetic insert failure
[SQL: INSERT INTO extraction (id, run_id, record_id, raw_output_text, …)]
[parameters: ('4d447c82-…', 'run-a-1', 'rec-a-001',
  '{"features": {"weather": {…, "evidence": "SYNTHETIC-EVIDENCE es regnete in
  Strengelbach"}, …}}', 1, None, 1, 11, 76, 0)]
```

That is the model's entire answer, on stderr, at `WARNING`, from a run that
failed — which is the only kind anybody reads.

| A5 asked for | State before this commit |
|---|---|
| `hide_parameters=True` on `create_async_engine` | **Absent.** `grep` over `ra2/` and `tests/`: no occurrence |
| A provoked-`IntegrityError` test with a positive control | **Absent.** `test_run_log_carries_no_data.py` drives a *successful* run |
| `data-handling.md` §5.1 to say the list is enforced by the engine too | **Absent**, and §5.1 positively asserted the opposite: `run.error` sat on the "may appear" side |

---

## 1. `ra2/persistence/session.py` — one keyword argument

```diff
-    engine = create_async_engine(database_url, echo=echo, future=True)
+    engine = create_async_engine(
+        database_url, echo=echo, future=True, hide_parameters=True
+    )
```

The docstring carries the reason; the contract row now names the flag beside
the four pragmas.

**Why the engine and not `_error_text`.** No call site was wrong, which is the
whole difficulty. `_error_text` is a reasonable function, `_finish` logs a
reasonable line, and a reviewer reading either would have seen nothing: the
row was appended by the driver, below both. A rule enforced only where log
lines are *written* cannot reach that. Filtering the string afterwards means a
regex for SQLAlchemy's `[parameters: …]` formatting — a parser for a format
nobody promised, wrong under a different driver or a later SQLAlchemy, and
**silent** when it misses. It would also leave `echo=` alone, which prints the
same values by another path. `hide_parameters` is the vendor's own switch and
covers both.

**The cost, accepted.** A constraint violation no longer says which values
caused it. A genuine data bug is then diagnosed from the constraint name plus
a query the developer runs *on the machine* — which is the trade
`data-handling.md` §5 already makes everywhere else, and is the direction
§9.1.1 argues for: the diagnostic path is the egress path.

**Why it is set rather than trusted.** Same argument as `secure_delete` in
`fix-b3-deletion-path`, with one difference: `hide_parameters` is not a
compile-time property but a documented default of `False`, so it is not merely
unknown — it is known to be wrong for this application.

---

## 2. `ra2/services/run_service.py` — a comment that asserted the premise A5 broke

Not frozen. The comment above the log call read:

> `error` is this module's own sentence about the run — a count of records and
> an endpoint status — and never the model's words, so it is safe to repeat
> here.

True of every error this module **writes**, false of the ones it **catches**,
and the assumption was written down — which is what made it findable. It now
says which half the engine is responsible for.

---

## 3. Not frozen, and changed

| Path | What |
|---|---|
| `tests/backend/persistence/test_engine_hides_parameters.py` *(new)* | A real `IntegrityError` from the real driver over the real migrated `record` table, with a planted synthetic narrative and key, asserted absent from exactly `_error_text`'s expression. Plus **the positive control** — the same insert through a default-built engine, failing if the narrative is *not* there — and a read-back of the flag off `create_engine` itself |
| `tests/backend/services/run/test_run_log_carries_no_data.py` | + `test_a_database_error_under_a_run_logs_no_row_content`: the channel the other three cannot reach. A `RAISE(ABORT)` trigger on `extraction` provokes a real driver error inside a real run; the persisted `run.error` **and** the log are both asserted clean. A mock session was rejected — what is under test is what a real `IntegrityError` says about the row it was given, and a fake says what it was told to |
| `data-handling.md` | §5.1 gains the two-halves rule: what a line is *given*, at the call sites, and what an exception is *allowed to say*, at the engine. The `run.error` entry on the "may appear" side is qualified rather than removed — it is correct for the sentences this code writes |
| `sw-design.md` | §4.4 (the flag, beside the pragmas) and **`SD39`** |
| `CONTRACTS.md` | The `session.py` row names the flag |
| `docs/risk-assesment.md` | A5 closed in §9.2, item 21 in both action tables, §1's superseded-claims row, and the §9.1.1 chain — where link 5 is now broken and the chain is stated as no longer closing on its own |

**Unchanged, deliberately:** `ra2/persistence/models.py` and `alembic` (nothing
here is schema — no migration, no new head), `ra2/infra/logging.py` (the rule
was right; its perimeter was not), `.importlinter`, `pyproject.toml`,
`tests/conftest.py`, `mvp-spec.md`.

**Not closed by this amendment.** Item 31 — *a stated support path*: what may
be copied off the machine when something breaks, and to where. A5 was link 5
of §9.1.1's six. Breaking it means a log line pasted into a bug report no
longer carries a row, which is the specific hazard; it does not make links 1,
2, 3 and 6 go away, and a screenshot or a hand-typed description still can.

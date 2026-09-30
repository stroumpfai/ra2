# Amendment: `fix-e4-d8-f6-real-or-synthetic` (risks E4, D8, F6)

> **APPLIED in the same commit**, as the other risk slices were. No wave is
> running. **One schema change**, revision `5e1d7a3c9b20`, so it has to land
> before real data is in the database (`risk-assesment.md` §5 row 27).

`risk-assesment.md` §5 rows **25**, **26** and **27**, all Gate 1.

| Row | Asked for | State before this commit |
|---|---|---|
| 25 · E4 | `reset_data.py` prints records and corpora, not bytes, and refuses a non-dev corpus without a second token | The plan printed `ra2.sqlite 281.0 MB`, and `yes` destroyed anything. Worse, and not in the register: **`just reset-seed` without `yes` removed nothing, exited 0, and then ran the seed**, putting a synthetic corpus on top of whatever database was there, real or not |
| 26 · F6, E3 | Correct the README, and gate it | The *Not built yet* claim F6 quoted had already been corrected. There was no gate, and an audit found eleven other stale statements |
| 27 · D8 | A synthetic-corpus marker, rendered beside the dev chip and refused by the ranking | `is_dev_sized` was the only marker, and it is a size threshold. A 3000-record seed was unmarked |

Decisions taken with the project owner before building:
- The marker is **explicit and inferred**.
- The ranking **renders, but names no winner**.
- The reset guard counts **any corpus that is not synthetic**, not "not dev-sized".
- The second token is **`destroy-real-data`**.
- There is **no backfill**. It would be an `UPDATE corpus`, and Do-NOT #2 does not bend for a migration.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/persistence/models.py` | + `Corpus.is_synthetic: Mapped[bool]`, `default=False`, `server_default="0"`. The server default is declared on the mapper too, so `alembic check` sees no drift |
| `ra2/services/corpus_service.py` | `freeze(..., synthetic: bool = False)`, a keyword with a default, so every existing caller is unchanged. Step 8 sets `is_synthetic = synthetic or all_invented(keys)`. `_corpus_view` carries it |
| `ra2/services/readmodels.py` | + `CorpusView.is_synthetic = False`, + `RunDescriptorView.is_synthetic = False`. Both are defaulted, so every existing constructor still builds |
| `ra2/api/schemas.py` | + `CorpusResponse.is_synthetic`, + `RunDescriptorResponse.is_synthetic`, both defaulted `False`. `tests/api/openapi_snapshot.json` is regenerated: two additive optional booleans and nothing else |
| `justfile` | `reset token=""` becomes `reset *tokens`, so `just reset yes destroy-real-data` reaches the script. `reset-seed` passes `--for-seed` |
| `.gitattributes` | **Comment only.** It named `FindingCode.DOUBLED_CRLF`, which does not exist (it is `ROW_BLANK_DROPPED`), and counted "twenty" CRLF fixtures. The rules are unchanged |
| `tests/test_p5_contract.py` | `5e1d7a3c9b20` is registered in `POST_PHASE_5_REVISIONS`, with its reason, like the five before it |

```diff
# ra2/persistence/models.py
     is_dev_sized: Mapped[bool] = mapped_column(default=False)
+    is_synthetic: Mapped[bool] = mapped_column(default=False, server_default="0")
```

```diff
# ra2/services/corpus_service.py
         name: str,
         description: str | None = None,
+        synthetic: bool = False,
     ) -> CorpusId:
```

```diff
# justfile
-reset token="":
-    uv run python scripts/reset_data.py {{token}}
+reset *tokens:
+    uv run python scripts/reset_data.py {{tokens}}
 ...
 reset-seed token="" *seed-args:
-    uv run python scripts/reset_data.py {{token}}
+    uv run python scripts/reset_data.py --for-seed {{token}}
     uv run python scripts/seed_dev.py {{seed-args}}
```

## The migration

`20260929_1200_5e1d7a3c9b20_mark_a_synthetic_corpus.py` adds
`corpus.is_synthetic`: NOT NULL, `server_default="0"`, **no backfill**. It is
the only revision in the slice, written by hand because `just revision`
autogenerates against `./var`. It is registered in `tests/test_p5_contract.py`,
and the chain keeps one head.

The cost of no backfill: a seed corpus frozen before this revision reads as
real. The reset guard then asks for `destroy-real-data` once, which is the safe
direction. Its ranking still names a leader until it is re-seeded, which is
the unsafe one, and closing it takes one re-seed.

## Not frozen, changed

| Path | What |
|---|---|
| `ra2/domain/synthetic.py` *(new)* | `is_invented_key`, `all_invented`. The shape is a short hex tag, ten zeros, then a decimal number, 32 characters in all. A random key matches with odds near 10^-12, every key must match, and an empty corpus stays real |
| `ra2/services/run_descriptor.py` | `is_synthetic` from the corpus row |
| `ra2/services/ranking_service.py` | On a synthetic corpus: `SYNTHETIC_HEADLINE`, `SYNTHETIC_DETAIL`, and every row's verdict becomes `synthetic`. Ranks and numbers are unchanged |
| `ra2/api/v1/{corpora,results}.py` | Map the field |
| `ra2/ui/views/results/chrome.py` | `SYNTHETIC_PILL`, beside the run or dev pill and never instead of it |
| `ra2/ui/views/results/ranking_tab.py` | Rank 1 is not tinted or accent-pilled on a synthetic corpus |
| `ra2/ui/views/import_view.py` | `· synthetic` in `--danger` beside `· dev-sized` |
| `scripts/reset_data.py` | `holdings()` reads with `sqlite3` in `mode=ro`, at any revision. It prints corpora, records and runs. It asks for `destroy-real-data` while any corpus is not synthetic, and treats an unreadable or pre-`SD45` database as real. `--for-seed` refuses real data outright and exits non-zero when nothing was reset |
| `scripts/seed_dev.py` | `freeze(..., synthetic=True)`. `real_corpus_count` refuses to seed beside a real corpus, independently of the reset |
| `README.md` | Row 26's corrections (below), plus the reset, seed and synthetic behaviour |
| `data-handling.md` | §4.1 step 4 now names both tokens. §4.3 says `reset-seed` refuses a machine holding real data, and how to rehearse instead |
| `docs/seed.md` | The seed corpus is synthetic, and what refuses what |
| `mvp-spec.md` | §9 and §13: the synthetic marker. A *what* change, so it lands here |
| `sw-design.md` | §6.3 step 8, `SD45`, `SD46`, `SD47` |

**README, corrected by audit** (none of these had a gate):
- the port is not fixed;
- models *have* been measured on the development host;
- `RA2_LLM_PARALLEL_CALLS` was missing from the configuration table;
- `RA2_DEV_RECORD_MAX` described the wrong threshold;
- the seed is 48 records and takes `--records`, not a `RECORDS` constant (twice);
- `FindingCode.DOUBLED_CRLF` does not exist;
- the "twenty" CRLF fixtures;
- `just check-data` and `just qualify-model` were missing;
- `tests/eval` and `just eval` are reserved and empty;
- layers 1–4 do open a loopback socket;
- `just census-export` does write to disk.

## Tests

| Layer | File | What |
|---|---|---|
| unit | `tests/unit/synthetic/test_invented_keys.py` | The generators' keys match; delivered-shaped, short, long, five-character-tag and non-hex keys do not; an empty corpus proves nothing |
| backend | `tests/backend/services/corpus/test_freeze.py` | Invented keys mark the corpus; delivered-shaped keys (made up for the test) do not, which is the negative control; `synthetic=True` marks it whatever the keys |
| backend | `tests/backend/services/ranking/test_ranking_tab.py` | The same scored rows, synthetic and not: verdict and pills replaced, ranks and macro F1 identical |
| backend | `tests/backend/scripts/test_reset_data.py` | The plan's counts; `yes` alone refused over a real corpus; both tokens needed, neither enough alone; all-synthetic needs only `yes`; pre-`SD45` and unreadable databases count as real; `holdings` runs against head and writes nothing; `--for-seed` exits 1 without `yes` and refuses real data whatever the tokens |
| backend | `tests/backend/scripts/test_seed_guard.py` | `real_corpus_count` |
| UI | `tests/ui/test_results_view.py`, `test_import_view.py` | The pill beside both run pills, absent on a delivered corpus; the Import marker present and absent |
| E2E | `tests/e2e/test_j1_delivery_to_census.py` | J1's hazard-fixture corpus shows `synthetic`, and nobody said so |
| root | `tests/test_readme_not_built_yet.py` | No built nav label in a *Not built yet* bullet's lead, with a positive control on F6's original bullet |

## What I did instead of a shim

Nothing. The amendment is applied in this commit.

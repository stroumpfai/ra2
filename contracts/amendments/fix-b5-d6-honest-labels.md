# Amendment: `fix-b5-d6-honest-labels` (risks B5, D6)

> **APPLIED in the same commit**, as the other risk slices were. No wave is
> running. **No schema change.**

`risk-assesment.md` §5 rows **5** and **10**.

| Row | Asked for | State before this commit |
|---|---|---|
| 5 · B5 | Render the anonymisation marking as three states until its semantics are confirmed | A chip reading *anonymised* on fallback-column narratives, and nothing at all on every other row, so nearly every record read as *not anonymised* |
| 10 · D6 | Standing copy: a mismatch rate is not a model error rate until the list is read | The sentence was in the README only |

Decisions taken with the project owner before building:
- **Two states now, the third by a setting.** A fallback-column narrative is
  *anonymised column*. A delivered narrative is *anonymisation unknown* until
  `RA2_DELIVERED_TEXT_ANONYMISED` records the supplier's `yes` or `no`, which
  makes it *anonymised* or *not anonymised*.
- **A chip on every row**, in every state.
- **The D6 sentence** goes on the extraction tab and on the ranking.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/infra/config.py` | + `delivered_text_anonymised: DeliveredTextAnonymised = UNKNOWN`. It has a reader (`main.py`) |
| `ra2/services/readmodels.py` | + `anonymisation: AnonymisationMarking` on `PerRecordRow` and `MismatchRowView`, defaulted to `UNKNOWN`. `anonymised: bool` stays, as the raw source fact |
| `ra2/api/schemas.py` | + `anonymisation: str` on `PerRecordResponse` and `MismatchRowResponse`, defaulted. `tests/api/openapi_snapshot.json` is regenerated: 10 lines added, none removed |
| `ra2/services/export_service.py` | **Body only**, no signature changes. The two CSVs that carry `anonymised` now write the marking's stable value, so the frozen constructor did not need the setting: the rows it is handed carry the marking already |

```diff
# ra2/infra/config.py
+    delivered_text_anonymised: DeliveredTextAnonymised = DeliveredTextAnonymised.UNKNOWN
```

## Not frozen, changed

| Path | What |
|---|---|
| `ra2/domain/anonymisation.py` *(new)* | `DeliveredTextAnonymised`, `AnonymisationMarking`, and `anonymisation_marking(from_anonymised_column, delivered)`, the one rule |
| `ra2/services/{results,mismatch}_service.py` | A defaulted `delivered_text_anonymised` constructor argument, wired from `Settings` in `main.py`; both fill `anonymisation` |
| `ra2/api/v1/{presence,mismatches}.py` | Map the field |
| `ra2/ui/views/results/chrome.py` | `ANONYMISATION_LABELS`, `ANONYMISATION_TITLES`, `anonymisation_chip()` (testid `anonymised-chip`, state in `data-marking`), `MISMATCH_RATE_NOTE` |
| `ra2/ui/views/results/presence_tab.py`, `ra2/ui/views/mismatches_view.py` | A chip on every row, through `anonymisation_chip` |
| `ra2/ui/views/results/{extraction,ranking}_tab.py` | `MISMATCH_RATE_NOTE`, under the legend and in the ranking's footer |
| `tests/fixtures/scored_corpus.py` | `text_anonymised_flag` is now true for one record in five, the realistic mix; it was true for every record, which hid the unknown state |
| `mvp-spec.md` | §13 names the four states; a *what* change |
| `sw-design.md` | §10's settings table, `SD50` |
| `README.md` | The configuration row |
| `docs/risk-assesment.md` | §5 rows 5 and 10, §8.12 |

## Tests

| Layer | File | What |
|---|---|---|
| unit | `tests/unit/anonymisation/test_marking.py` | The fallback column wins whatever the answer; a delivered narrative follows `unknown` / `yes` / `no`; the default is `unknown` |
| backend | `tests/backend/services/mismatch/test_mismatch_service.py` | Each answer, over the fixture's mix: both sources present and marked correctly; the CSV writes the same word and never `yes` / `no` |
| backend | `tests/backend/services/results/test_presence_tab.py` | The per-record list under a `yes` answer |
| backend | `tests/backend/api/results/test_presence_ranking_api.py` | The source fact and the marking agree on the wire |
| UI | `tests/ui/test_results_view.py`, `test_mismatches_view.py` | A chip per row with a valid state and its label; the mismatch list shows both `anonymised_column` and `unknown`; the D6 note on the extraction tab and the ranking |

## What I did instead of a shim

Nothing. The amendment is applied in this commit.

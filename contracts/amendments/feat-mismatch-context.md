# Amendment — `feat/mismatch-context`

> **APPLIED in the same commits**, as `fix-b1-census-value-samples`,
> `fix-results-visibility` and `feat-codelists-usability` were.
> No wave is running.

The Mismatches view gains what an analyst needs to tell a hallucination from a
record error ([`plan-mismatch-context.md`](../../plan-mismatch-context.md),
`SD70`): the `UnfallUid`, both values decoded against the launch-time codelist
snapshot, and a detail row with the narrative and the evidence span
highlighted in it. The pure halves are two new domain modules,
`ra2/domain/code_label.py` and `ra2/domain/span_locate.py`, which are not
frozen. Three frozen files are amended, all additively, and a fourth is frozen
for its signatures only and changes only in its body. No schema change and no
migration: everything shown is already stored.

---

## 1. `ra2/services/readmodels.py` — `MismatchRowView` widened, `MismatchDetailView` added

**Why.** The UI may not see an ORM row (§12.7), so the UID, the decodings and
the detail have to arrive in read models. `record_id` stays on the row, where
the API and the CSV carry it; the detail carries only the UID, which is all the
screen shows (step 4's review).

```diff
+from ra2.domain.code_label import UNDECODED, DecodedValue
+from ra2.domain.feature import DerivationSpec, Kind, MatchingRule, ValueType
 ...
 class MismatchRowView:
     mismatch_id: MismatchId
     record_id: RecordId
     anonymised: bool
     ...
     anonymisation: AnonymisationMarking = AnonymisationMarking.UNKNOWN
+    #: mvp-spec.md §12's record key — what the screen and the CSV show (SD70).
+    unfall_uid: str = ""
+    #: Both values decoded against the launch snapshot (SD70).
+    record_decoded: DecodedValue = UNDECODED
+    extracted_decoded: DecodedValue = UNDECODED
 ...
+@dataclass(frozen=True, slots=True)
+class MismatchDetailView:
+    mismatch_id: MismatchId
+    unfall_uid: str
+    narrative: str | None
+    highlights: tuple[tuple[int, int], ...]
+    language: str
+    language_confidence: float
+    anonymisation: AnonymisationMarking
+    feature_key: str
+    feature_description: str
+    kind: Kind
+    value_type: ValueType
+    matching_rule: MatchingRule
+    source_column: str | None
+    derivation: DerivationSpec | None
+    record_decoded: DecodedValue
+    extracted_decoded: DecodedValue
+    evidence_span: str | None
```

`__all__` gains `MismatchDetailView`. **`unfall_uid` is defaulted and last**,
not required beside `record_id`: `tests/test_p5_contract.py` is frozen and
builds a row without it, and a required field cannot follow a defaulted one.
The one production constructor, `mismatch_service._row_view`, always sets it.

## 2. `ra2/api/schemas.py` — `MismatchResponse`, additive

**Why.** The API row mirrors the read model row (`SD24`'s "carried as data so
a client does not re-derive a rule the service owns").

```diff
 class MismatchResponse(_Schema):
     mismatch_id: str
     record_id: str
+    unfall_uid: str
     ...
+    record_label: str | None
+    record_label_state: LabelState
+    extracted_label: str | None
+    extracted_label_state: LabelState
```

**All five are required**, `unfall_uid` included (step 2's review): a
response that forgot one fails rather than shipping an empty key. The one
constructor is `api/v1/mismatches._row`. The OpenAPI snapshot is regenerated:
additions only. **No route is added**:
`MismatchService.detail` is reached in-process only (plan §6, settled §10).

## 3. `ra2/services/mismatch_service.py` — one signature

**Why.** Phase 5 froze this service's constructor and signatures (CONTRACTS.md).
The detail row reads one opened mismatch, only when it is opened, so it needs
its own entry point.

```diff
+    async def detail(self, mismatch_id: MismatchId) -> MismatchDetailView: ...
```

`NotFoundError` for an unknown id. Existing signatures unchanged. *(Added by
the branch review: this section was missing, though the plan named it.)*

## 4. Frozen for signatures only, body changed

- `ra2/services/export_service.py`: `_MISMATCHES_CSV_HEADER` and the
  `mismatches_csv` body gain `unfall_uid`, `record_label`, `extracted_label`,
  `record_label_state` and `extracted_label_state`, **appended**. The signature
  is unchanged, and the signature is what is frozen.

## 5. Not frozen, named for completeness

- `ra2/persistence/repositories/mismatch_repo.py`, `ra2/ui/state.py`,
  `ra2/ui/components/data_table.py`, and the bodies in `mismatch_service.py`:
  stub-owned, not frozen.

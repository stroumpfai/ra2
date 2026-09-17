# Amendment — `feat/p5-mismatch-domain-persistence` (W1)

> **APPLIED at integration**, in the Wave 1 commit. One field, removed from two
> frozen files, plus the two wire schemas that mirror them.

---

## `ra2/services/readmodels.py` and `ra2/api/schemas.py` — drop `name`

**Why.** M35 gave `MismatchFeatureView` and `ReviewTallyView` both a
`feature_key` and a `name`. There is nothing for the second one to hold.

`Feature` has `key`, `description` and `ordinal` — no display name — and every
read model in the app that needed to label a feature already resolved this the
same way: `results_service` writes `name=feature.key` in all three places it
builds one, and pairs it with `source_label` where a *second, different* string
is genuinely wanted (`Witter0Ausw · enum`). The Mismatches view needs no second
string: §3.2's Feature column is "the feature key, mono", and the tally strip
and the filter dropdown both name the same key.

So `name` would be populated as `feature.key` at every call site and rendered
identically to `feature_key` at every use — two fields that are always equal,
which is the second-source-of-truth this codebase refuses everywhere else. It
is cheaper to remove now, in the wave that first has to populate it, than after
Y1, Y2 and Z1 have each carried it through a layer.

```diff
 class MismatchFeatureView:
     feature_id: FeatureId
     feature_key: str
-    name: str
     #: Mismatches for this feature in this run, unfiltered by tag state.
     total: int

 class ReviewTallyView:
     feature_id: FeatureId
     feature_key: str
-    name: str
     tally: ReviewTally
```

and the same two lines from `MismatchFeatureResponse` and
`ReviewTallyResponse` in `ra2/api/schemas.py`, so the wire keeps mirroring the
read models one-for-one.

**Not shimmed.** A shim would mean populating a field this wave is deleting,
inside the wave that discovered it, and `mismatch_service.py`, `mismatches.py`
and `mismatches_view.py` are all still stubs — nothing reads either field yet,
so there is nothing to shim *for*. `tests/test_p5_contract.py` does not name
`name` and stays green unedited.

**Consequence.** `tests/api/openapi_snapshot.json` is regenerated with the
Wave 1 commit; verified by set comparison — two properties removed from two
schemas, nothing else.

# Amendment: `ra2/services/readmodels.py` and `ra2/api/schemas.py`

**Rename `errors` -> `validation_errors` on the phase-2 feature read model
and the phase-2 response schemas**, finishing a rename Wave 0 already
started. One test is `xfail`ed in the meantime; see "Status in this branch".

## Which files

| File | Field |
|---|---|
| `ra2/services/readmodels.py` | `FeatureView.errors` |
| `ra2/api/schemas.py` | `CodelistImportResponse.errors` (line 309), `FeatureResponse.errors` (line 449), `FeatureValidationErrorResponse.errors` (line 492) |

Both frozen at `p2-frozen`; neither is one of E2's paths.

## Why

`tests/unit/parsing/test_no_lenient_decoding.py` scans every `ra2/**/*.py`
with comments and docstrings tokenized away and fails on **any** occurrence
of `\berrors\s*=` — not only on a lenient decode. It is the strictest of that
file's three §12.4 gates, and the codebase was in that state until now.

Wave 0 already decided how to live with it: **frozen** `ra2/services/errors.py`
names its constructor parameters and attributes `import_errors` and
`validation_errors`, not `errors`, precisely so that constructing one does not
write the banned keyword —

```python
class FeatureValidationError(ServiceError):
    def __init__(self, validation_errors: Sequence[str]) -> None:
        ...
        self.validation_errors = tuple(validation_errors)
```

That rename was simply not carried across to `readmodels.py` and
`schemas.py`, which declare a plain `errors` field. Since `FeatureView.errors`
is not a default-only field — `feature_service` has to populate it, and F2's
router has to map it — *some* caller must write `errors=`, and there is no
other spelling. So the gate now fails on production code that has nothing to
do with decoding, and it will fail again for F1 and F2 for the same reason.

The fix belongs at the field name, not at the regex. Loosening
`ANY_ERRORS_KEYWORD` would carry a permanently weakened decode-safety gate
forward to buy consistency with two field names that are themselves the
inconsistency; renaming them makes phase 2 match `errors.py`, and
`validation_errors` is also the more accurate name — these are
mvp-spec.md §7/§8.2 validation messages, not errors in any other sense.

Contorting the call site instead (splatting a `{"errors": ...}` dict,
splitting the keyword across lines) was rejected: that is the same class of
mistake as Do-NOT #12, production code shaped by a test.

## Proposed diff

```diff
--- a/ra2/services/readmodels.py
+++ b/ra2/services/readmodels.py
@@ class FeatureView:
     #: Blocking validation messages (mvp-spec.md §7/§8.2). Non-empty rows
     #: render as errors and block "Create a feature set".
-    errors: tuple[str, ...] = ()
+    #: Named to match `FeatureValidationError.validation_errors`, which
+    #: avoids the banned `errors=` keyword for the same reason (§12.4).
+    validation_errors: tuple[str, ...] = ()
```

```diff
--- a/ra2/api/schemas.py
+++ b/ra2/api/schemas.py
@@ class CodelistImportResponse:
-    errors: list[CodeImportErrorResponse]
+    import_errors: list[CodeImportErrorResponse]
@@ class FeatureResponse:
-    errors: list[str] = Field(default_factory=list)
+    validation_errors: list[str] = Field(default_factory=list)
@@ class FeatureValidationErrorResponse:
     detail: str = "blocking feature validation errors; the set was not frozen"
-    errors: list[str]
+    validation_errors: list[str]
```

`CodelistImportResponse.errors` -> `import_errors` mirrors
`CodelistImportError.import_errors` and is E1/F1's to confirm; it is listed
here only because it is the same root cause and will bite F1 identically.

## What lands with it

E2's side of the rename is two mechanical edits, both inside E2's own paths,
and is **not** applied in this branch (the frozen field is still `errors`, so
applying it early would leave the worktree red):

```
ra2/services/feature_service.py    1 line: `errors=errors,` -> `validation_errors=by_feature[...]`
tests/backend/services/feature/**  sed -i 's/\.errors\b/.validation_errors/g'
```

E2 has already reduced its own footprint to that single production line: the
other two `errors =` hits were local variables, renamed to `by_feature`.

## Status in this branch

`tests/unit/parsing/test_no_lenient_decoding.py::test_the_errors_keyword_is_not_passed_at_all`
is marked `pytest.mark.xfail(reason="amendment: feat-p2-feature-service")` so
the rest of the suite is green, per CLAUDE.md's "keep going" rule. Nothing
else in that file is touched, and the two stricter-than-`grep` §12.4 gates
next to it (`test_errors_replace_appears_nowhere_in_ra2`,
`test_no_decode_or_open_call_asks_for_any_lenient_error_handler`) still pass
unmodified, so the actual rule stays enforced throughout.

Remove the marker when the rename lands.

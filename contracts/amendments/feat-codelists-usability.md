# Amendment — `feat/codelists-usability`

> **APPLIED in the same commit**, as `fix-b1-census-value-samples`,
> `fix-results-visibility` and `feat-evaluation-view-improvements` were.
> No wave is running.

Automap ([`plan-codelists-usability.md`](../../plan-codelists-usability.md) §4)
proposes column mappings the analyst confirms. Its pure half is a new domain
module, `ra2/domain/codelist_suggest.py`, which is not frozen. Two frozen files
are touched, both additively. No schema change and no migration: nothing new
is stored.

---

## 1. `ra2/services/readmodels.py` — `MappingSuggestionView`, `UnresolvedCopyView`, `MappingSuggestionsView`

**Why.** `suggest_mappings` has to tell the UI what to propose, where each
proposal comes from, how well it covers the column, and which copied keys
the current import can no longer honour. `ui/` may not see an ORM row
(§12.7), so this needs read models.

```diff
+from ra2.domain.codelist_suggest import SuggestionSource
 ...
+@dataclass(frozen=True, slots=True)
+class MappingSuggestionView:
+    column_name: str
+    table_name: str
+    code_attribute_id: CodeAttributeId
+    attribute_key: str
+    source: SuggestionSource
+    contained: int
+    distinct: int
+    currently: str | None
+
+@dataclass(frozen=True, slots=True)
+class UnresolvedCopyView:
+    column_name: str
+    table_name: str
+    attribute_key: str
+
+@dataclass(frozen=True, slots=True)
+class MappingSuggestionsView:
+    source_corpus_id: CorpusId | None
+    sources: tuple[CorpusId, ...]
+    suggestions: tuple[MappingSuggestionView, ...]
+    unresolved: tuple[UnresolvedCopyView, ...]
```

`__all__` gains the three names. No existing read model changes.

## 2. `ra2/services/codelist_service.py` — two method signatures

**Why.** These are the service halves of "propose" and "apply". `apply_mappings`
is not N calls to `map_column`: one transaction means all or nothing, and the
census columns are resolved once for the batch rather than once per pick.

```diff
+    async def suggest_mappings(
+        self, corpus_id: CorpusId, *, source_corpus_id: CorpusId | None = None
+    ) -> MappingSuggestionsView: ...
+
+    async def apply_mappings(
+        self, corpus_id: CorpusId, picks: Sequence[tuple[str, CodeAttributeId]]
+    ) -> int: ...
```

The existing signatures, `EnumCodeTableProvider` included, are unchanged.

## 3. Not frozen, named for the integration check

- `ra2/persistence/repositories/codelist_repo.py`: `get_latest_import` gains
  `id DESC` as its tie-breaker (plan §7a).
- `design/code-feature/README.md`: Screen 1 amended (plan §2–§4.3). This
  file is not in CONTRACTS.md, but E2E asserts it, so it is named here too.

## 4. What was done instead

Nothing: applied in place. No `xfail` was left behind.

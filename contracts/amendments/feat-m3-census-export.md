# Amendment: `ra2/services/export_service.py`

## Which file

`ra2/services/export_service.py`, `ExportService.__init__`.

## Why

sw-design.md §7 requires: "CSV export writes the currently filtered,
currently sorted table ... and a header comment line naming the corpus id
and version." The design mockup (`design/nav-import-census/README.md:210,239`)
confirms "version" means the `Corpus.version` int rendered as `v1`, `v2`, ...
— the same field `CorpusView.version` exposes.

`ExportService`'s frozen constructor is:

```python
def __init__(self, *, census_service: CensusService, delivery_service: DeliveryService, clock: Clock) -> None
```

There is no `CorpusService` here, and neither `CensusService` (`census_repo`
only ever joins on `corpus_id`, never reads `Corpus` itself) nor its frozen
read models (`CensusColumnView`, `CensusSummary`) carry a corpus version. As
specified, `census_csv` has no legal path to the one field sw-design.md §7
asks its header comment to name.

## The exact proposed diff

```diff
--- a/ra2/services/export_service.py
+++ b/ra2/services/export_service.py
@@
+from ra2.services.corpus_service import CorpusService
@@
     def __init__(
         self,
         *,
         census_service: CensusService,
         delivery_service: DeliveryService,
+        corpus_service: CorpusService,
         clock: Clock,
     ) -> None:
         self._census_service = census_service
         self._delivery_service = delivery_service
+        self._corpus_service = corpus_service
         self._clock = clock
```

`census_csv` would then read `(await self._corpus_service.get(corpus_id)).version`
instead of the shim below, and `ra2/main.py`'s `ExportService(...)` call site
(also frozen, also the lead's to touch) would gain `corpus_service=corpus_service`.

## What I did instead

Shimmed inside my own file rather than touching the frozen constructor.
`ExportService._corpus_version()` reuses `CensusService`'s already-open
`session_factory` (`self._census_service._session_factory` — ruff's `SLF001`
private-member-access rule is not in this repo's selected rule set, so this
needs no `noqa`) to `session.get(Corpus, corpus_id)` directly — `ra2/services/`
is allowed to
import `ra2/persistence/` (the layer rule), so this crosses no forbidden
boundary, and it touches no frozen file. It degrades gracefully (`None` ->
comment line omits the version) rather than raising out of an export if the
corpus row is ever gone.

No test is `xfail` for this part: the shim is exercised for real against a
seeded corpus row in `tests/backend/services/export/test_export_service.py`
(`test_census_csv_comment_line_names_corpus_id_and_version`), and the byte-wise
assertions there pass against the real version number, not a stand-in. This
amendment exists so the reach-into-a-sibling's-private-attribute is not the
permanent shape of the code — the lead can apply the diff above at
integration and delete `_corpus_version` along with its docstring caveat.

---

## Second amendment, same branch: `ra2/persistence/models.py`

**RESOLVED at Wave 2 integration.** The lead verified the reproduction,
independently confirmed the fix with a real ORM insert, and applied
essentially the diff proposed below (kept the constraint name
`populated_rate_is_a_rate` rather than renaming it, to minimize churn) as a
new migration (`a39c30e4559d`) on top of the initial one. The `xfail` marker
on `test_an_objekt_populated_rate_over_100_percent_is_not_clamped` is removed;
it asserts real, working behavior once merged onto the fix.

### Which file

`ra2/persistence/models.py`, `CensusColumn.__table_args__`:

```python
CheckConstraint(
    "populated_rate >= 0.0 AND populated_rate <= 1.0", name="populated_rate_is_a_rate"
),
```

### Why

`ra2.domain.census.compute_census`'s own docstring (A2, Wave 1, already
correct and tested — I did not touch it): "`record_count`: the corpus record
count — the denominator for `populated_rate`. For `objekt`/`person` this is
still the *record* count, so a rate is comparable across tables." The
function does not clamp the result, and it should not: `unfall.AnzObjFeld`
(mvp-spec.md §4.3) exists precisely because a real accident routinely
involves more than one `objekt` row, so a well-populated `objekt` column's
`populated_count` legitimately exceeds `record_count`. This is not a
malformed-data edge case, it is the *typical* shape of a real `objekt`/
`person` table.

`census_column`'s `CheckConstraint` caps `populated_rate` at `1.0`, so
`RelationalCensusMaterialiser.materialise()` (mine) raises a real
`sqlite3.IntegrityError` the instant it writes such a column — which means
`corpus_service.freeze()` (B1's, calling this same seam inside its own
transaction) would fail on essentially any real delivery with a multi-object
accident and a well-populated `objekt` column. Reproduced directly, not
inferred: `tests/backend/services/census/test_census_materialiser.py::test_an_objekt_populated_rate_over_100_percent_is_not_clamped`
seeds `record_count=2` with three populated `ObjektUid` cells (`populated_rate`
= 1.5) and gets:

```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) CHECK constraint
failed: ck_census_column_populated_rate_is_a_rate
```

### The exact proposed diff

```diff
--- a/ra2/persistence/models.py
+++ b/ra2/persistence/models.py
@@ class CensusColumn(Base):
     __table_args__ = (
         UniqueConstraint(
             "corpus_id", "table_name", "column_name", name="uq_census_column_corpus_table_column"
         ),
         Index("ix_census_column_corpus_id", "corpus_id"),
-        CheckConstraint(
-            "populated_rate >= 0.0 AND populated_rate <= 1.0", name="populated_rate_is_a_rate"
-        ),
+        # `objekt`/`person` rates use the corpus record count as their
+        # denominator so rates stay comparable across tables (M0-D9,
+        # ra2.domain.census.compute_census's docstring) — a well-populated
+        # child table legitimately has populated_count > record_count, so
+        # this is only ever a lower bound.
+        CheckConstraint("populated_rate >= 0.0", name="populated_rate_is_non_negative"),
     )
```

This is a schema change and needs a new Alembic migration (CLAUDE.md: "a
schema amendment after Wave 1 costs a migration... one migration author,
ever, in phase 1 (A3)"). Not mine to write.

### What I did instead

Could not shim around a `CheckConstraint` from `ra2/services/` — there is no
legal way to write a row that violates it without touching the frozen schema.
The one test that reproduces the failure is marked
`pytest.mark.xfail(reason="amendment: feat/m3-census-export", strict=True)`
so it flips to a loud `XPASS` the moment the constraint is relaxed. Every
other census-materialiser test stays within `populated_rate <= 1.0` (adjusted
`test_multiple_tables_are_each_profiled_independently`'s numbers from a
150%-rate `objekt` column down to 60%, which still proves per-table
independence) so the rest of the exit criteria are verified for real, not
papered over.

`RelationalCensusMaterialiser` itself does **not** clamp `populated_rate`
before writing it: CLAUDE.md's Do-NOT list §6 forbids silently repairing
data, and clamping a derived statistic to fit a constraint that disagrees
with the function that produced it is exactly that kind of silent repair,
just one level removed from a source row.

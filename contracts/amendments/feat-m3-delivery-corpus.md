# Amendment — `feat/m3-delivery-corpus` (B1, Wave 2)

Two items. The first blocks a design rule and needs the diff below; the second
is an observation with a proposed fix that nothing in Wave 2 depends on.

**Item 1 resolved at integration** — see its own note below. **Item 2 left
open**, per B1's own assessment that it is not a phase-1 blocker; a future
wave should apply the drafted `UtcDateTime` diff.

---

# Item 1 — `CorpusService` has no `FileStore`

**RESOLVED at Wave 2 integration.** The lead applied essentially the diff
below: `upload_store`/`host_path_store` added to `CorpusService.__init__`,
wired in `ra2/main.py` from the same two instances `DeliveryService` already
gets. The `_store_for`/`_read_bytes` shim now just picks between the injected
stores (mirroring `DeliveryService._store_for`) instead of reconstructing one.
One consequence for tests: `corpus_service` and `delivery_service` test
fixtures must now share the same `upload_store`/`host_path_store` fixture
instances (they didn't before, since each built its own) — otherwise a
host-path delivery's `.bind()` registration made through `delivery_service`
would not be visible to `corpus_service`'s freeze. Fixed in
`tests/backend/services/corpus/conftest.py`.

## 1. Which file

`ra2/services/corpus_service.py` — the **frozen constructor** of `CorpusService`.

## 2. Why

`corpus_service.freeze()` has to write `record`, `unfall_row`, `objekt_row`,
`objekt_cell`, `person_row` and `person_cell` — the actual **cells** of every
selected file — and it has to hand those same cells to the
`CensusMaterialiser`.

`delivery_file` deliberately stores only the *summary* of a file (counts,
effective/detected encoding and dialect, findings) and never its cells; that is
what keeps the staging table lean and keeps
`ra2.domain.parsing.analysis.analyse_file` the single source of truth for what
a file's rows are. So at freeze time the rows have to be produced again, which
means re-reading each selected file's **bytes**.

Bytes come from a `FileStore`. `DeliveryService` is given both stores through
its constructor. `CorpusService` is given none:

```python
def __init__(
    self,
    *,
    session_factory, census_materialiser, language_detector,
    task_runner, clock, ids, settings,
) -> None: ...
```

There is no other way to reach a file's bytes from `CorpusService` without
either duplicating cell storage into `delivery_file` (a schema amendment, and a
stale-cache hazard on every re-parse) or reaching around the seam.

sw-design.md §3 is explicit that **every seam arrives through the constructor**,
so building a store inside the service is a deviation, not a design.

## 3. The exact proposed diff

```diff
--- a/ra2/services/corpus_service.py
+++ b/ra2/services/corpus_service.py
@@
 from ra2.infra.clock import Clock
 from ra2.infra.config import Settings
+from ra2.infra.filestore import FileStore
 from ra2.infra.idgen import IdFactory
 from ra2.infra.tasks import TaskRunner
 from ra2.services.protocols import CensusMaterialiser
@@ class CorpusService:
     def __init__(
         self,
         *,
         session_factory: async_sessionmaker[AsyncSession],
         census_materialiser: CensusMaterialiser,
         language_detector: LanguageDetector,
+        upload_store: FileStore,
+        host_path_store: FileStore,
         task_runner: TaskRunner,
         clock: Clock,
         ids: IdFactory,
         settings: Settings,
     ) -> None:
         self._session_factory = session_factory
         self._census_materialiser = census_materialiser
         self._language_detector = language_detector
+        self._upload_store = upload_store
+        self._host_path_store = host_path_store
         self._task_runner = task_runner
         self._clock = clock
         self._ids = ids
         self._settings = settings
```

and, in `ra2/main.py` (also frozen — the two go together):

```diff
     corpus_service = CorpusService(
         session_factory=session_factory,
         census_materialiser=census_materialiser,
         language_detector=language_detector,
+        upload_store=upload_store,
+        host_path_store=host_path_store,
         task_runner=task_runner,
         clock=clock,
         ids=ids,
         settings=settings,
     )
```

Both keywords already exist in `create_app()`'s signature and are already
constructed there for `DeliveryService`, so the composition root gains no new
concept — the two services simply share the same two store instances.

## 4. What I did instead

`corpus_service.py` carries a private `_store_for(delivery)` shim that
**reconstructs** the right store from state that is already persisted, rather
than from an injected seam:

- `SourceKind.UPLOAD` → `UploadedFileStore(settings.deliveries_dir,
  max_bytes=settings.max_upload_bytes)` — the same arguments `create_app()`
  passes.
- `SourceKind.HOST_PATH` → `HostPathFileStore({delivery_id: Path(delivery.root_path)})`
  — `delivery.root_path` is a column, so the reconstruction is exact.

It is marked `# SHIM (amendment: feat/m3-delivery-corpus)` at the definition.

**What the shim gets wrong, and why the amendment still matters:** a caller who
passes a *substitute* `upload_store`/`host_path_store` to `create_app()` gets it
honoured by `DeliveryService` and silently ignored by `CorpusService`, which
builds a real filesystem-backed store instead. Every backend test in
`tests/backend/services/` therefore uses the real `UploadedFileStore` over a
`tmp_path`, so nothing here is asserted against a seam the shim bypasses. No
test is `xfail`; the shim is behaviourally correct for the wired-up default and
for every real deployment. It is the *injectability* that is missing, and that
is what the diff above restores.

No test is disabled by this amendment.

---

# Item 2 — every stored timestamp round trips **naive**

## 1. Which file

`ra2/persistence/models.py` — `Base.type_annotation_map`.

## 2. Why

`ra2/infra/clock.py` (frozen) states the contract:

> Timezone-aware, UTC. Never naive — **every stored timestamp carries its
> offset so a Windows and a Linux run agree.**

It does not survive the database. `datetime: DateTime(timezone=True)` on
SQLite has no offset storage, so what SQLAlchemy hands back has `tzinfo=None`:

```
FrozenClock().now()            -> datetime(2026, 9, 2, 9, 30, tzinfo=UTC)
(await service.get(id)).created_at -> datetime(2026, 9, 2, 9, 30)
```

Every `DeliveryView.created_at`, `analysed_at` and `CorpusView.imported_at`
therefore reaches the UI and the API as a naive datetime whose zone the reader
has to *assume* is UTC. The values are correct; the type lies about them, and
the first consumer to call `.astimezone()` on one will silently reinterpret it
in the host's local zone — which is precisely the Windows/Linux disagreement
the `Clock` docstring exists to prevent.

Not a phase-1 blocker: nothing in Wave 2 does arithmetic across zones, and the
golden report serialises the naive value reproducibly.

## 3. The exact proposed diff

A `TypeDecorator` that stamps UTC back on load. Additive, and **no migration**:
the bytes SQLite already holds do not change, only how they are read.

```diff
--- a/ra2/persistence/models.py
+++ b/ra2/persistence/models.py
@@
+class UtcDateTime(TypeDecorator[datetime]):
+    """`DateTime(timezone=True)` that really is timezone-aware.
+
+    SQLite stores no offset, so a naive value comes back out. Everything
+    written here is UTC by construction (`Clock.now()`), so re-attaching UTC
+    on load is a restatement of a fact, not a guess.
+    """
+
+    impl = DateTime(timezone=True)
+    cache_ok = True
+
+    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
+        if value is None:
+            return None
+        if value.tzinfo is None:
+            raise ValueError("naive datetime reached the database; use Clock.now()")
+        return value.astimezone(UTC)
+
+    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
+        return None if value is None else value.replace(tzinfo=UTC)
+
+
 class Base(DeclarativeBase):
@@
-        datetime: DateTime(timezone=True),
+        datetime: UtcDateTime(),
```

## 4. What I did instead

Nothing was worked around: the behaviour is asserted **as it is**, out loud, in
`tests/backend/services/delivery/test_intake.py`:

```python
# SQLite has no offset storage, so a `DateTime(timezone=True)` column round
# trips **naive** even though `Clock.now()` is UTC-aware. Asserted as-is
# rather than papered over — see contracts/amendments/feat-m3-delivery-corpus.md.
assert view.created_at.replace(tzinfo=UTC) == clock.now()
```

If the lead applies the diff, that one line becomes
`assert view.created_at == clock.now()` and everything else is unaffected. No
test is `xfail`.

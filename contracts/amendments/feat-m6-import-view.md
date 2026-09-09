# Amendment: `ra2/services/delivery_service.py`, `ra2/services/corpus_service.py`, `ra2/ui/theme.py`

Filed by `feat/m6-import-view` (M6, the Import view). Four items. Items 1, 2
and 4 are shimmed inside `ra2/ui/views/import_view.py` and are marked there
with a pointer back to this file; item 3 is **not shimmable** — the layer rule
forbids the only import that would implement it — and the one test that would
cover it is `xfail(reason="amendment: feat/m6-import-view")`.

---

## Item 1 — `DeliveryService` has no paged, sorted file query

### Which file

`ra2/services/delivery_service.py` — a new read method beside `get()`.

### Why

sw-design.md §8.1.1 and §8.1.4 are explicit:

> Sorting, filtering, paging, derived counts and validation are service calls
> or domain functions. A view function that computes a rate is a bug.
>
> Sort/page parameters are always part of the **service call signature**, even
> when the current dataset is small enough to sort in memory.

`CorpusService.list_corpora(sort_key=…, sort_dir=…, page=…, page_size=…) ->
Page[CorpusView]` complies. `DeliveryService` does not: its only read of a
delivery's files is

```python
async def get(self, delivery_id: DeliveryId) -> DeliveryView: ...
```

which returns every file of the delivery in `relative_path` order. The Import
view has **two independently sorted and independently paged tables** over that
one list (design README §1a: "Sort state is per-table and independent between
the two tables"; "Pagination: page size selector (10 default) and prev/next"),
so with the frozen surface the only place the sort and the page can happen is
the view — which is exactly what §8.1 bans.

### Proposed diff

```python
--- a/ra2/services/delivery_service.py
+++ b/ra2/services/delivery_service.py
@@
+#: `sort_key` -> the `DeliveryFileView` attribute the file tables sort on.
+#: An unknown key falls back to `filename`, the design's default (README §1a:
+#: "Sortable, currently sorted ascending").
+_FILE_SORT_KEYS: frozenset[str] = frozenset({"filename", "row_count", "state"})
+
@@ class DeliveryService:
     async def get(self, delivery_id: DeliveryId) -> DeliveryView:
         """Raises `NotFoundError`."""
         async with self._session_factory() as session:
             repo = DeliveryRepository(session)
             delivery = await self._require(repo, delivery_id)
             return delivery_view(delivery, await repo.list_files(delivery_id))
 
+    async def files(
+        self,
+        delivery_id: DeliveryId,
+        *,
+        kinds: Collection[FileKind] | None = None,
+        exclude_kinds: Collection[FileKind] | None = None,
+        sort_key: str = "filename",
+        sort_dir: SortDir = SortDir.ASC,
+        page: int = 1,
+        page_size: int = 10,
+    ) -> Page[DeliveryFileView]:
+        """One page of one of the Import view's two file tables.
+
+        The left card is every non-`TEXT` file, the right card is the text
+        file, and each has its own sort and its own page (README §1a). Sort
+        and page are service-call parameters, always (§8.4).
+
+        `state` sorts by severity — ok, recovered, rejected, failed — because
+        that is the order the column's colour ramp implies, not the
+        lexicographic order of the rendered string.
+        """
+        key = sort_key if sort_key in _FILE_SORT_KEYS else "filename"
+        view = await self.get(delivery_id)
+        rows = [
+            f
+            for f in view.files
+            if (kinds is None or f.file_kind in kinds)
+            and (exclude_kinds is None or f.file_kind not in exclude_kinds)
+        ]
+        rows.sort(key=lambda f: _file_sort_value(f, key), reverse=sort_dir is SortDir.DESC)
+        start = max(page - 1, 0) * page_size
+        return Page(
+            items=tuple(rows[start : start + page_size]),
+            total=len(rows),
+            page=page,
+            page_size=page_size,
+            sort_key=key,
+            sort_dir=sort_dir,
+        )
```

plus the module-level `_file_sort_value(file, key)` helper and a
`_STATE_RANK` mapping — both are transcribed verbatim from
`ra2/ui/views/import_view.py`'s shim, which is where they live today.

---

## Item 2 — the "N locked by an evaluation" count is not available

### Which file

`ra2/services/corpus_service.py` — a new read method beside `list_corpora()`.

### Why

The Corpora card's header count is, verbatim from the design README §1b:

> Left `.lbl` "Corpora" + mono 11px `--ink2` "4 imported · 2 locked by an
> evaluation".

`Page[CorpusView].total` supplies "4 imported". Nothing supplies "2 locked":
`locked_by_evaluations` is per row, and the header count is over the whole
table, not over the current page. Deriving it in the view means either
counting a page (wrong number) or fetching every corpus and summing
`is_locked` in a view function — a derived count in `ui/`, which §8.1.1 bans.

### Proposed diff

```python
--- a/ra2/services/readmodels.py
+++ b/ra2/services/readmodels.py
@@
+@dataclass(frozen=True, slots=True)
+class CorpusSummary:
+    """The Corpora card's header count: "4 imported · 2 locked by an
+    evaluation" (design README §1b)."""
+
+    total: int
+    locked: int
```

```python
--- a/ra2/services/corpus_service.py
+++ b/ra2/services/corpus_service.py
@@ class CorpusService:
+    async def summary(self) -> CorpusSummary:
+        """How many corpora exist, and how many an evaluation cites.
+
+        Over the whole table, not over a page: the Corpora card's header
+        count is a property of the corpus set, not of what is on screen.
+        """
+        async with self._session_factory() as session:
+            repo = CorpusRepository(session)
+            corpora = await repo.list_all()
+            locked = 0
+            for corpus in corpora:
+                if await repo.count_citing_evaluations(CorpusId(corpus.id)) > 0:
+                    locked += 1
+            return CorpusSummary(total=len(corpora), locked=locked)
```

(`readmodels.py` is also frozen, hence the two-file diff.)

---

## Item 3 — there is no read path from `ui/` for the file report's raw preview

### Which file

`ra2/services/delivery_service.py` — a new read method.

### Why

sw-design.md §8.3 specifies the minimum content of the file report modal:

> per-file findings grouped by `FindingCode` with counts and keys, the
> detected vs. effective encoding/delimiter/quote char with override
> selectors, a re-parse button, **a 20-row raw preview**, remove, and
> "Export findings CSV".

Every other item is reachable from `ui/`. The preview is not. Reading a
delivery file's bytes means `FileStore`, which lives in `ra2.infra`, and
`.importlinter`'s `ui-reaches-only-services-and-domain` contract lists
`ra2.infra` as a forbidden module for `ra2.ui` — so the import that would
implement the preview **fails the build**, and there is no legal shim.
`DeliveryFileView` carries no line content either.

The read also cannot be done naively: N4 bans opening a file without an
explicit `encoding=`, and §4.2.1 bans `errors="replace"`. The file's
*effective* encoding is the one the service already resolved, so the decode
belongs beside `reparse_file`, not in a view.

### Proposed diff

```python
--- a/ra2/services/delivery_service.py
+++ b/ra2/services/delivery_service.py
@@ class DeliveryService:
+    async def preview(
+        self, delivery_id: DeliveryId, file_id: FileId, *, lines: int = 20
+    ) -> tuple[str, ...]:
+        """The first `lines` physical lines of a file, decoded with its
+        **effective** encoding (sw-design.md §8.3's "20-row raw preview").
+
+        Physical lines, not parsed rows: the preview exists so an analyst can
+        see what the parser saw before recovery and rejection, which is the
+        only way an encoding or delimiter override can be chosen on evidence.
+        A file whose bytes decode under neither encoding previews as empty —
+        `errors="replace"` is banned and U+FFFD is never rendered (§12.4).
+        """
+        async with self._session_factory() as session:
+            repo = DeliveryRepository(session)
+            delivery = await self._require(repo, delivery_id)
+            row = await self._require_file(repo, delivery_id, file_id)
+            data = await self._store_for(delivery).read_bytes(delivery_id, row.relative_path)
+        encoding = Encoding(row.encoding) if row.encoding else None
+        for candidate in ((encoding,) if encoding else (Encoding.UTF_8, Encoding.CP1252)):
+            try:
+                text = data.decode(candidate.value)
+            except UnicodeDecodeError:
+                continue
+            return tuple(text.splitlines()[:lines])
+        return ()
```

### Until then

`ra2/ui/views/file_report_modal.py` renders the preview section with an
explicit "unavailable" line naming this amendment, and
`tests/ui/test_import_view.py::test_the_file_report_shows_a_twenty_line_raw_preview`
is `xfail(reason="amendment: feat/m6-import-view")`.

---

## Item 4 — two colour utility classes the design requires are missing

### Which file

`ra2/ui/theme.py`, `_UTILITIES`.

### Why

`theme.py` injects **one** stylesheet (§8.2) and defines `.ok`, `.warn` and
`.danger`, but no class for `--ink2`, `--ink3` or `--accent`. The design
README §1a and §1b put all three on text the Import view renders through
`card_header(count=…, count_class=…)`, whose only styling hook is a CSS
class:

- structured card count "9 files · 9 selected" → `--ink2`;
- text card count "1 file · 1 selected" → `--accent`;
- the corpora action "delete blocked" and a not-yet-analysed state → `--ink3`.

`ra2/ui/theme.py` is A5's and is not this milestone's to edit, so the three
classes are injected from `import_view.py` instead — a second `ui.add_css`
call, which is precisely what §8.2's "one injection" rule exists to prevent.

### Proposed diff

```css
--- a/ra2/ui/theme.py
+++ b/ra2/ui/theme.py
@@ _UTILITIES
 .ok{color:var(--ok);}
 .warn{color:var(--warn);}
 .danger{color:var(--danger);}
+.ink2{color:var(--ink2);}
+.ink3{color:var(--ink3);}
+.accent{color:var(--accent);}
```

and the deletion of `import_view.py`'s `_SHIM_CSS` block plus its
`ui.add_css` call, renaming `ra2-ink2` / `ra2-ink3` / `ra2-accent` to
`ink2` / `ink3` / `accent` at their six use sites.

---

## Not an amendment, but the integrator should know

`ra2/api/v1/{deliveries,corpora,census}.py` are **still the M0 stubs**: every
handler raises `HTTPException(501)`. M4 (C1/C2) is not in this worktree's
history, although the M6 brief assumed it was. sw-design.md §11.5 says
"seeding beyond the journey under test goes through `/api/v1`" — for J1 and
J2 there is no seeding *beyond* the journey (registering and analysing the
delivery **is** the first step of both journeys), so both tests drive the real
UI end to end and need no API. `tests/e2e/test_j1_delivery_to_census.py` and
`test_j2_blocking_validation.py` therefore pass as written, and will keep
passing once M4 lands.

Separately: nothing in `create_app()` runs `alembic upgrade head`, and the
session `server_url` fixture in `tests/e2e/conftest.py` (A5's, not this
milestone's) does not either — so the E2E server starts against an empty
database. Both new E2E modules migrate it themselves before use. When
`tests/e2e/conftest.py` next has an owner, the migration belongs in
`server_url`, once, rather than in every journey module that touches data.

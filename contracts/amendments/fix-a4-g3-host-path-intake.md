# Amendment: `fix-a4-g3-host-path-intake` (risks A4, G3)

> **APPLIED in the same commit**, as the other risk slices were. No wave is
> running. **No schema change.**

`risk-assesment.md` §5 row **9**, and half of row **30**.

| Asked for | State before this commit |
|---|---|
| Constrain `root_path` to an allowed root | Any directory on the machine was accepted, through the Import view and the API |
| Bound the walk | `rglob("*")` over the whole tree, reading every file in full into memory to hash it |
| Honour `Settings.host` or drop it | **Already closed** by `SD42` (`ra2 serve` refuses a non-loopback bind) |

Decisions taken with the project owner before building:
- The allowed root is **`RA2_IMPORT_ROOT`, default `{data_dir}/import`**.
- **`just reset` does not delete it**: files registered in place are the
  analyst's own, so destruction step 5 stays manual, with one address.
- The bounds are **200 files and 2 GB**.
- A refusal writes **nothing**: it is a `ServiceError` and a 422, not a
  delivery with a blocking finding.

---

## Frozen files changed

| File | Change |
|---|---|
| `ra2/infra/config.py` | + `import_root: Path \| None` (defaulted to `{data_dir}/import` by a validator, like `db_path`), `import_max_files = 200`, `import_max_gb = 2.0`; + properties `import_root_path` and `import_max_bytes`. Every field has a reader (`SD42`'s gate) |
| `ra2/services/errors.py` | + `HostPathRefusedError(ServiceError)` with a stable `reason`. Registered in `tests/test_p5_contract.py`'s `POST_PHASE_5_ERRORS` |
| `ra2/infra/filestore.py` | **Implementation half only.** The protocol, `StoredFile`, `FileStoreError` and `ReadOnlyFileStoreError` are untouched. + `HostPathRefusedError(FileStoreError)` with four reason codes; `HostPathFileStore` gains keyword-only `allowed_root`, `max_files` and `max_bytes` (all defaulted to *unbounded*, so a test's own store behaves as before); `bind` checks the root; `list_files` is bounded and refuses a link out of the root; `_stat_file` hashes in chunks |
| `ra2/services/delivery_service.py` | **Body only.** `register` translates the store's refusal into the service error; no signature changes |
| `tests/test_p5_contract.py` | + `HostPathRefusedError` in `POST_PHASE_5_ERRORS` |

```diff
# ra2/infra/config.py
     max_upload_mb: int = 512
+    import_root: Path | None = None
+    import_max_files: int = 200
+    import_max_gb: float = 2.0
```

```diff
# ra2/main.py
-    host_path_store = host_path_store or HostPathFileStore()
+    host_path_store = host_path_store or HostPathFileStore(
+        allowed_root=settings.import_root_path,
+        max_files=settings.import_max_files,
+        max_bytes=settings.import_max_bytes,
+    )
```

## Not frozen, changed

| Path | What |
|---|---|
| `ra2/infra/files.py` | + `open_binary_reader` |
| `ra2/api/v1/deliveries.py` | `HostPathRefusedError` → 422 |
| `scripts/seed_dev.py` | The seed's delivery is written to `{import_root}/seed`, not `{data_dir}/seed` |
| `scripts/qualify_model.py` | The same, in its throwaway directory; `import_root` is named explicitly for `db_path`'s reason, so the environment cannot move it |
| `README.md` | Configuration rows for the three settings; the seed's directory |
| `data-handling.md` | §4.1 step 5 has one address; §4.2's P5 is marked half settled |
| `sw-design.md` | §6.1, §10's table, `SD49` |
| `docs/risk-assesment.md` | §5 rows 9 and 30, §8.11 |

## Tests

| Layer | File | What |
|---|---|---|
| backend | `tests/backend/infra/test_filestore_contract.py` | Inside the root accepted; outside, `..` and the parent refused at `bind`; stops past the file count and past the byte total; accepted exactly at both bounds; a link out refused (skipped on Windows without symlink privilege, runs on the Linux CI leg); the streamed digest equals the whole-file digest past a chunk boundary |
| backend | `tests/backend/services/delivery/test_host_path_refusal.py` | Outside the root and past a bound, both refused, with zero `delivery` and `delivery_file` rows; the positive control; `create_app()` builds the store from `Settings`; the root's default and override |
| backend | `tests/backend/api/deliveries/test_host_path_refusal_api.py` | 422, and nothing listed afterwards |
| UI, E2E | `tests/ui/test_{import,census,features}_view.py`; `tests/e2e/test_j{1,2,7,8,9,10}_*.py` | Their deliveries now live under the test settings' import root, as an operator's must. The E2E journeys nest each under the test's own directory, since the server's root is shared by the session |

## Found, not fixed

`HostPathFileStore` holds each delivery's root in memory only, and nothing
rebinds it from `delivery.root_path` at startup. After a restart, an analysed
host-path delivery cannot be re-read, so it cannot be frozen. It is
pre-existing and unrelated to the constraint, and belongs in its own change.

## What I did instead of a shim

Nothing. The amendment is applied in this commit.

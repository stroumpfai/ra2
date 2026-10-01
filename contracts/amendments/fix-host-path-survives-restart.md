# Amendment: `fix-host-path-survives-restart`

> **APPLIED in the same commit.** No wave is running. No schema change, and
> no frozen signature changes.

**The defect.** `HostPathFileStore` kept each delivery's root in a dict, and
only `DeliveryService.register` ever filled it. After a restart the dict was
empty, and an analysed host-path delivery failed on its next read with
`FileStoreError: no host path registered for delivery …`. Freezing it is
exactly that read. The docstring of `CorpusService._store_for` stated the
assumption outright: *"the same injected, already-bound stores … a host-path
delivery's registered root is not reconstructed"*. That holds only within one
process.

It was found during `fix-a4-g3-host-path-intake` (`risk-assesment.md` §8.11)
and fixed separately.

## Changed

| File | Frozen part | Change |
|---|---|---|
| `ra2/infra/filestore.py` | Protocol untouched; implementation half | + `HostPathFileStore.restore(delivery_id, root)`: rebinds a delivery registered earlier. **Not** checked against `allowed_root`, because `SD49`'s rule applies at registration and a delivery registered before it has to stay readable |
| `ra2/services/delivery_service.py` | Constructor and signatures untouched | + a module-level `store_for(delivery, *, upload_store, host_path_store)`, which restores the binding from `delivery.root_path` before returning the store; `_RootBindingStore` gains `restore`; `_store_for` delegates to it |
| `ra2/services/corpus_service.py` | Constructor and signatures untouched | `_store_for` delegates to the same helper, and its docstring now says why |

Restoring on every use, not once at startup, is deliberate. It costs one
dict write, and a startup step is one more thing a composition root can
forget, which is how this defect happened.

## Tests

`tests/backend/services/corpus/test_freeze.py`:
- `…freezes_after_a_restart`: registers and analyses through one store, then
  freezes and re-analyses through services built on a **fresh** store, which
  is what a restart looks like. Without the fix it fails with the original
  error.
- `…is_not_rechecked_against_the_import_root`: a restored binding outside the
  import root still reads.

## Also in this commit

- **Row 28** is marked done in `risk-assesment.md` §5. It was built as
  `SD42` and its status row was never updated.
- **Row 29 (B6)**, `SD51`. The Mismatches view has no note field, so the
  warning is the description of `TagMismatchRequest.note`
  (`ra2/api/schemas.py`, frozen, additive: `NOTE_LEAVES_RA2`, with a `Field`
  description), asserted by
  `tests/backend/api/mismatches/test_mismatches_api.py`. The OpenAPI snapshot
  gains one description line. `data-handling.md` §3 lists `note` and gains
  rule 5; the `tagged_by` gap is written as a proposal for the project to
  accept.

## What I did instead of a shim

Nothing. The amendment is applied in this commit.

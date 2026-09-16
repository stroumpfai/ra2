# Amendment — `feat/reset-discard-service` (R1)

> **APPLIED at integration**, with the whole slice, in one commit. R1, R2 and
> R3 were implemented by one agent rather than three in parallel, so the shims
> the amendment process exists to make unnecessary were never written: each
> frozen file below was changed directly, at integration, exactly as proposed
> here. `plan-reset-and-discard.md` §7 lists the four rows it anticipated; two
> of the four below (`readmodels.py`, `container.py` + `main.py`) were missing
> from it and were added to that table in the same commit.

Four frozen files. Nothing in `ra2/persistence/models.py` — **no schema
change, no migration, no new Alembic head** — which is the direct consequence
of choosing export-before-discard over an audit table (`R-D2`, SD23).

---

## 1. `ra2/services/errors.py` — three errors, one per guard

**Why.** The guards in `sw-design.md` §18.2 are refusals a caller has to be
able to tell apart, and this file is where every service refusal is named.
Without them the service would have to raise `ValueError` and the routers
would have to guess a status.

```diff
+class RunActiveError(ServiceError):
+    """G1 — a `queued` or `running` run cannot be discarded. -> HTTP 409."""
+
+class TaggedWorkPresentError(ServiceError):
+    """G2 — the discard would destroy analyst tags. -> HTTP 409 **with the
+    count**, and it is overridable."""
+
+class DeliveryCitedError(ServiceError):
+    """A corpus was frozen from this delivery. -> HTTP 409."""
```

`TaggedWorkPresentError` carries `tagged_count`; the other two carry the ids
and the status that explain the refusal. **No new `FindingCode`** — a refused
discard is a rendered state, not an import defect, which is the precedent
phases 2, 3 and 4 each set once already.

## 2. `ra2/services/readmodels.py` — the views the dialog and the export render

**Why.** `ra2/ui/` may not touch a session or an ORM object (§12.7), so the
dialog's counts, the export's rows and the header's data directory all have to
arrive as read models. There is nowhere else they can live.

```diff
+class DiscardPreviewView:   # counts + `active` + `cited_by`, one shape for
+                            # all three kinds, with `has_exportable` and
+                            # `blocked` as computed properties
+class ScoreExportRow: ...
+class MismatchExportRow:    # including analyst_tag / tagged_at / note
+class RunExportView: ...
+class DataDirView: ...
```

`MismatchExportRow.record_value` is `str | None`, matching the column: the
corpus value is authoritative but a `wrong` outcome can be recorded against an
absent one.

## 3. `ra2/services/container.py` — `Services.lifecycle`

**Why.** Both adapters reach the new service, and neither may construct one
(§3). This is the bundle they are handed.

```diff
     ranking: RankingService
+    # --- reset and discard (sw-design.md §18) ---
+    lifecycle: LifecycleService
```

## 4. `ra2/main.py` — the construction, wiring only

**Why.** The composition root is the only place a service is built.

```diff
+    lifecycle_service = LifecycleService(
+        session_factory=session_factory,
+        upload_store=upload_store,
+        settings=settings,
+    )
     services = Services(
         ...
+        lifecycle=lifecycle_service,
     )
```

`upload_store` is the same instance intake uses, because the bytes a delivery
discard removes are the bytes intake wrote. **No host-path store is wired**:
a host-path delivery's files are the analyst's own and are never removed, so
the service has no use for one — and not having it is what makes that
impossible rather than merely intended.

---

## What was built outside `plan-reset-and-discard.md` §6's file list

Three repositories gained methods the plan's ownership table did not
anticipate. None is frozen; they are recorded here because the table said R1
owned two repositories and the work needed three.

| File | Added | Why |
|---|---|---|
| `run_repo.py` | `count_scores`, `count_mismatches` (`(all, tagged)` in one query), `delete` | The preview's counts and G2's number |
| `evaluation_repo.py` | `delete` | As planned |
| `delivery_repo.py` | `count_citing_corpora`, `delete` | The delivery guard. `corpus.delivery_id` is `SET NULL`, so **the database will not refuse on its own** — the query behind the service guard has to live somewhere, and the delivery repository is where the other delivery queries are |

# Amendment — `feat/reset-discard-api` (R2)

> **APPLIED at integration**, with the whole slice, in one commit. See
> `feat-reset-discard-service.md`'s note on why no shim was written.

Three frozen files, and one addition to `plan-reset-and-discard.md` §7's table
(`deps.py`, which a new service both adapters reach cannot do without).

---

## 1. `ra2/services/export_service.py` — two writers

**Why.** §18.3 makes the export the *only* trace a discard leaves, so the
writers are what make the trade defensible. They take the rows rather than
fetching them, which is `P4-D3`'s reasoning applied again: the caller has
already shown these counts to the analyst in the dialog, and a CSV assembled
from a second read can disagree with what they agreed to.

```diff
+    def run_scores_csv(self, view: RunExportView) -> bytes: ...
+    def run_mismatches_csv(self, view: RunExportView) -> bytes: ...
```

The module's existing conventions are reused unchanged: UTF-8 with a BOM,
`;`-delimited, a comment line naming the run, the evaluation and the model.
`language` is written as stored, `'*'` included (`SD16`) — the file outlives
the database, so prettifying the all-languages row would lose the one value
that says which row it is.

**The mismatch export carries verbatim evidence spans.** That is what makes it
worth keeping and what makes the file sensitive; N1 bounds the application,
not the file it wrote. Said in the docstring rather than left to be
discovered.

## 2. `ra2/api/schemas.py` — `DiscardPreview`, `DiscardResponse`

**Why.** The two shapes the three routes answer with. `DiscardResponse` is a
body rather than a bare `204` for a reason worth keeping: nothing is written
anywhere recording that a discard happened (§18.3), so the response **is** the
receipt.

```diff
+class DiscardPreview(_Schema):   # the counts, plus `has_exportable` and
+                                 # `blocked` carried as data
+class DiscardResponse(_Schema):  # what went, and whether G2 was overridden
```

`has_exportable` and `blocked` travel as data rather than being re-derived by
a client: they are §18.2's rules, and a second copy is the first thing to fall
out of step when a guard changes.

## 3. `ra2/api/deps.py` — `LifecycleServiceDep`

**Why.** The typed `Depends` is the only way a router reaches a service.

```diff
+def get_lifecycle_service(...) -> LifecycleService:
+    return services.lifecycle
+LifecycleServiceDep = Annotated[LifecycleService, Depends(get_lifecycle_service)]
```

---

## What was built, beyond the three `DELETE` routes

| Route | Why it exists |
|---|---|
| `GET /runs/{id}/discard-preview`, `GET /evaluations/{id}/discard-preview`, `GET /deliveries/{id}/discard-preview` | §7 of the plan asks for a `DiscardPreview` **schema**; a response model with no route is dead code. The preview is also what §4's dialog contract looks like from outside the UI, and a caller that cannot see what it is about to destroy is being asked to guess |
| `GET /runs/{id}/scores.csv`, `GET /runs/{id}/mismatches.csv` | §4's "Export" — the two writers above, over the wire |

`ra2/api/v1/discard.py` is **new and not a router**: it holds the two mapping
functions and the 409 builder the three routers share. Three copies of one
status mapping is three places for one of them to drift into a 400.

## The UI, and the one deviation

The run row action and the confirm dialog are R2's last commit, as §6 says.
Two things differ from what the plan describes, both recorded in
`plan-reset-and-discard.md` itself and in `sw-design.md` §18.5/§18.6:

1. **No sixth column.** Discard lives in the runs table's **status cell**,
   beside `log` and `Resume`. The table's five widths are the design's own
   (`design/prompt-evaluation/README.md` §2), and that cell is already where a
   row's secondary actions go.
2. **No delivery affordance.** The Import view shows exactly one delivery and
   has no delivery list to hang a row action on. The route exists; the UI does
   not, and adding a delivery table would be a design amendment, which `R-D4`'s
   own reasoning refuses.

**The dialog's callbacks are awaitable** (`Callable[[bool], Awaitable[None]]`),
not the plan's implied sync ones. Found by the E2E journey: a handler that
merely *returns* a coroutine has done nothing, because NiceGUI awaits what a
handler returns and the component was discarding it. `ollama_settings_dialog`'s
`on_test` already had the shape; this now matches it.

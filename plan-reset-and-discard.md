# Plan — Reset and Discard

Gives an analyst a way back to a clean state after exploratory or inconclusive
work, and gives a developer a one-command wipe of the data directory. Both
problems look like "reset"; they are not the same problem and this plan keeps
them apart.

**Authority order**, as everywhere else: `mvp-spec.md` (what) → `sw-design.md`
(how) → this file (who builds what, and what they may touch). Where this file
and `sw-design.md` disagree, `sw-design.md` wins and this file is corrected in
the same commit.

This is a small slice, not a phase. One wave, three agents, no migration.

---

## 1. The problem, split

Two users share a symptom and need opposite things.

**The developer.** `var/` fills with throwaway deliveries, corpora and runs
across a day of manual testing. The need is a hard wipe with no ceremony, and
— more useful — a wipe that lands on a *working* initial state rather than an
empty one.

**The analyst.** Three inconclusive evaluations are cluttering the Evaluation
and Results views. The need is to clear those without losing anything
expensive: the delivery files, the frozen corpus and its materialised census,
the codelist import, the feature config, the prompt versions, and above all
any mismatch they have already tagged.

What separates the two is cost of recreation. `run`, `extraction*`, `score`
and `mismatch` are the bulk of the rows and are all regenerable from immutable
inputs; everything upstream of a run is curated by hand. **So "reset", for an
analyst, almost always means "discard runs"** — and that is the verb the app
does not have. `corpus`, `prompt_template` and `feature_config` each have a
delete with a citation guard already (`corpus_service.delete`,
`prompt_service.delete`, `feature_service.delete`). `run` and `evaluation`
have none.

---

## 2. Scope

### 2.1 In

1. **`DELETE /api/v1/runs/{run_id}`** — discards one run and, by the existing
   FK cascade, its `extraction`, `extraction_value`, `extraction_entity`,
   `score` and `mismatch` rows.
2. **`DELETE /api/v1/evaluations/{evaluation_id}`** — discards an evaluation
   and its runs. The corpus, feature config and prompt versions it cites are
   untouched; those are `ondelete="RESTRICT"` and stay that way.
3. **`DELETE /api/v1/deliveries/{delivery_id}`** — discards a delivery, its
   `delivery_file` rows and its files under `{data_dir}/deliveries/{id}/`.
4. **A discard affordance in the UI** — a row action on the run list in the
   Evaluation view, behind a confirm dialog that carries the export step
   described in §4.

   > **Corrected during implementation.** This item also asked for one "on the
   > delivery list in the Import view". **There is no delivery list.** The
   > Import view shows exactly one delivery — the most recently registered,
   > remembered per client — and has no switcher and no table of deliveries
   > (`import_view._current_delivery`). A row action has nothing to hang on,
   > and adding a delivery table is a change to
   > `design/nav-import-census/README.md`, which R-D4's own reasoning refuses.
   > So delivery discard ships as the **route** of item 3 and no UI
   > affordance; the analyst's route to the same end is `just reset`, and §1
   > already says the delivery files are the expensive half this feature
   > exists to *keep*. Recorded in `sw-design.md` §18.6.
5. **`just reset` and `just reset-seed`** — the developer's wipe, and the
   wipe-then-seed that lands on a usable state.
6. **The active data directory, shown in the header** — read-only, so which
   database you are looking at is never a guess.

### 2.2 Out

- **Snapshot and restore.** Deferred until discarding runs is shown to be
  insufficient. A file-level snapshot (`VACUUM INTO` plus a manifest carrying
  the Alembic revision, and a restore that refuses when the revision is not
  head) is the design if it is ever wanted; it is not wanted yet.
- **An audit table.** Explicitly rejected in favour of export-before-discard
  (§4). This is why **this slice needs no migration** — no new table, no
  column, no `alembic revision`.
- **Corpus discard.** It already exists, with its 409-when-cited guard and its
  `LOCKED · N eval` pill (J3). Unchanged here.
- **Bulk or filtered discard** ("delete every run older than a week"). One
  object at a time. A bulk verb over a destructive operation is how the wrong
  thing gets deleted.

---

## 3. What the API guarantees, and what it does not

Two guards, both enforced in the service and both asserted at the backend
layer. They are invariants:

**G1 — nothing active is discarded.** A run whose status is `queued` or
`running` returns 409. An evaluation with any such run returns 409. `failed`,
`interrupted` and `done` are all discardable; an interrupted run is exactly
the kind of debris this feature exists to clear.

**G2 — human work is never destroyed silently.** The only human-authored data
in the pipeline is `mismatch.analyst_tag`. `sw-design.md` SD21 already spends a
paragraph arguing that a re-score must not lose it; deletion earns the
identical argument. So a discard counts tagged mismatches first, and when the
count is non-zero returns **409 with the count** unless the caller passes
`force=true`. Warn and allow, not block: an analyst who cannot clean up will
work around the app, and the workaround is editing the SQLite file by hand.

**What the API does not guarantee: that anything was exported.** The
export-before-discard flow (§4) is a dialog affordance. The server never
tracks "has this run been exported" — that would be a mutable per-run flag
recording a UI event, which is the kind of state this codebase does not keep.
An implementing agent must not add one.

---

## 4. Export before discard

The trace a discard leaves lives outside the database, in a file the analyst
chose to keep.

The confirm dialog has two states:

- **Nothing to export** — the run produced no `score` and no `mismatch` rows
  (never launched, failed early). Confirm is enabled immediately.
- **Something to export** — the dialog shows what will be lost (n extractions,
  n scores, n mismatches, of which n tagged) and offers **Export** beside
  **Discard**. Export downloads a CSV bundle of the run's scores and its
  mismatches, `analyst_tag` included, through `export_service`'s existing
  conventions unchanged: UTF-8 with BOM, `;`-delimited, header comment naming
  the run and evaluation (`sw-design.md` §7).

When G2 fires, the same dialog re-renders with the tagged count in the lead
sentence and Discard relabelled to carry the `force` call. One dialog, two
states, not two dialogs.

---

## 5. The developer's wipe

`scripts/reset_data.py`, sibling of `scripts/dev_agent.py` and written to the
same rules — pathlib only, explicit encodings, no subprocess (N3, N4).

`just reset` resolves `Settings` exactly as the app does, so it honours
`RA2_DATA_DIR` and can never surprise someone whose data directory is not
`./var`. It prints what it will remove — database path, `deliveries/`,
`codelists/`, `exports/`, with file counts and total size — and refuses
without an explicit token (`just reset yes`). Then it removes them and brings
the schema up with `alembic upgrade head` in-process. **Never
`metadata.create_all()`** (Do-NOT 10).

`just reset-seed` runs the wipe and then drives the **services** — not raw SQL
and not the ORM — to register one fixture delivery, analyse it, freeze a
corpus, import the codelist, create the feature config and save one prompt
version. Driving the services is the point: the seed cannot drift from the
schema, and it doubles as a smoke test of the import path.

`justfile` is frozen and its recipe list is final, so both recipes ship as an
amendment (§7).

---

## 6. Ownership

| Agent | Branch | Owns |
|---|---|---|
| **R1** | `feat/reset-discard-service` | `ra2/services/lifecycle_service.py` (new), `ra2/persistence/repositories/run_repo.py`, `evaluation_repo.py` and `delivery_repo.py` (discard and count methods), `ra2/services/container.py` + `ra2/main.py` wiring, `tests/backend/services/lifecycle/` |
| **R2** | `feat/reset-discard-api` | `ra2/api/v1/runs.py`, `ra2/api/v1/evaluations.py`, `ra2/api/v1/deliveries.py` (the `DELETE` routes and the two export routes), `tests/backend/api/lifecycle/` |
| **R3** | `feat/reset-cli` | `scripts/reset_data.py`, `scripts/seed_dev.py`, the `justfile` amendment, the header data-dir chip in `ra2/ui/shell.py` **and the `shell()` call site in each of the eight views**, `tests/backend/scripts/` |

> **The chip is not contained in `shell.py`.** The data directory is a
> `Settings` value, `ra2/ui/` may not import `ra2/infra/` (§1.1), and
> Do-NOT #8 forbids parking it in a module global — so it reaches the header
> the way every other value reaches a view: as an argument, reading it from
> the service layer. `shell()` takes `data_dir`, and each view passes
> `services.lifecycle.data_dir()`. Eight one-line call-site changes, and the
> layer rule stays intact.

The UI discard dialog is R2's last commit rather than a fourth agent: it is one
component and two call sites, and splitting it across a boundary costs more
than it saves.

**No new nav item.** The nav is four groups and eight items, transcribed from
`design/nav-import-census/README.md` and asserted in E2E. A ninth entry is a
design amendment, not a feature. Discard lives as a row action on lists that
already exist.

---

## 7. Frozen files this slice needs amended

Each is one amendment file under `contracts/amendments/`, named for the branch,
per `CLAUDE.md`.

| File | What | Whose amendment |
|---|---|---|
| `ra2/services/errors.py` | `RunActiveError` (→409), `TaggedWorkPresentError` (→409, carries the count), `DeliveryCitedError` (→409) | R1 |
| `ra2/services/readmodels.py` | `DiscardPreviewView`, `RunExportView` and its two row types, `DataDirView` — the dialog, the export and the header chip all render read models, and `ui/` may not see an ORM object | R1 |
| `ra2/services/container.py` | `Services.lifecycle` | R1 |
| `ra2/main.py` | `LifecycleService` construction — wiring only | R1 |
| `ra2/services/export_service.py` | two writers: `run_scores_csv`, `run_mismatches_csv` | R2 |
| `ra2/api/schemas.py` | `DiscardPreview` (the counts the dialog renders), `DiscardResponse` | R2 |
| `ra2/api/deps.py` | `LifecycleServiceDep` | R2 |
| `justfile` | `reset`, `reset-seed` | R3 |

> **Four rows added during implementation** — `readmodels.py`, `container.py`,
> `main.py` and `deps.py`. Each is frozen and each is unavoidable for a new
> service that both adapters reach: the original table listed only the files
> whose *contents* this slice designs, and missed the four it merely has to
> pass through. `ra2/persistence/models.py` is still **not** amended, and the
> "no migration" consequence in the paragraph below still holds.

`ra2/persistence/models.py` is **not** amended. No schema change, no migration,
no new Alembic head — a direct consequence of choosing export-before-discard
over an audit table.

---

## 8. Tests

`tests/unit` — nothing. There is no new domain logic; this slice is entirely
service, persistence and adapter.

`tests/backend` — the layer that carries this slice.

- G1: a `running` run returns 409; `done`, `failed` and `interrupted` discard.
- G2: a run with two tagged mismatches returns 409 carrying `2`; the same call
  with `force=true` succeeds.
- **The cascade is real, not assumed.** Discard a run on the temp-file SQLite
  fixture and assert that its `extraction`, `extraction_value`,
  `extraction_entity`, `score` and `mismatch` rows are gone, that the
  evaluation, corpus, features and prompt version are untouched, and that
  *another* run of the same evaluation is untouched. `foreign_keys=ON` is a
  connect-time PRAGMA in `session.py`; this test is what keeps it honest.
- Delivery discard removes the files under `{data_dir}/deliveries/{id}/` as
  well as the rows, and a delivery cited by a corpus is refused.
- `reset_data.py` against a temp `RA2_DATA_DIR`: refuses without the token,
  removes what it listed, leaves the schema at head.

`tests/ui` — the dialog's two states, and that Discard is disabled until the
confirm is explicit.

`tests/e2e` — one journey extending J-series: launch a dev-sized run, let it
finish, discard it from the run list, assert the row is gone and the
evaluation still lists its other run. No new journey number is claimed here;
the lead assigns it.

---

## 9. Decisions this plan makes

| # | Decision | Why |
|---|---|---|
| R-D1 | Discard is **whole-object only** — a run, an evaluation, a delivery. Never a partial delete inside one | Do-NOT 2 forbids mutating an extraction, record or corpus. Deleting a whole object is not mutation; deleting *some* of an object's rows is mutation by another name, and it would leave a run whose numbers no longer reproduce |
| R-D2 | The trace is an exported file, not an audit row | Chosen over an audit table. It costs no migration, and a CSV the analyst kept is more useful than a row nobody reads |
| R-D3 | Tagged mismatches warn with a count and allow `force`, rather than blocking | A hard block leaves no way to ever remove the run, and pushes people to the SQLite file |
| R-D4 | No new nav item; no new top-level view | The nav is fixed at eight items and asserted in E2E (`sw-design.md` §8.2) |
| R-D5 | Snapshot/restore deferred, with the design recorded in §2.2 rather than built | Discarding runs may well be the whole need. Restore-compatibility across migrations is a permanent maintenance cost to take on only once it is asked for |

---

## 10. What `sw-design.md` needs first

**Write this before R1 is spawned**, per `CLAUDE.md`: where the design is
silent an agent follows the nearest pattern, and here the nearest pattern is
`corpus_service.delete` — which does not answer whether deleting scored,
immutable rows is permitted at all.

A short section, in the shape of §15.8, stating:

1. whole-object discard is permitted and partial deletion never is (R-D1);
2. the two guards of §3, and that no third guard is added quietly;
3. that discard state is never persisted — no `deleted_at`, no soft-delete
   flag, no export bookkeeping;
4. that `mismatch.analyst_tag` is the one thing in the pipeline a destructive
   operation must announce before destroying, which is SD21's argument
   extended from re-scoring to deletion.

`sw-design.md` §13 gains `SD23` for R-D2 — the deviation being that a system
which is append-only everywhere else acquires one destructive verb, and pays
for it with an export rather than an audit trail.

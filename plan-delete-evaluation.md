# Plan — Deleting an evaluation from the front end

Reported in use. Analysts test by changing a parameter or two and launching
again, and the evaluations they no longer care about pile up in the Evaluation,
Results and Mismatches screens. They want to delete them from the UI, behind at
least a confirmation, and with whatever other guardrails make an attention
error unlikely.

**Authority order**, as everywhere else: `mvp-spec.md` (what) → `sw-design.md`
(how) → this file. Where this file and `sw-design.md` disagree, `sw-design.md`
wins and this file is corrected in the same commit.

A small slice, not a phase. One branch, no migration, no API change.

---

## 1. What already exists

The destructive verb is built (`sw-design.md` §18, `SD23`, `SD35`):

- **"Discard evaluation"** in the runs card header of the Evaluation screen,
  and a per-run `discard` in each row's status cell.
- **One confirm dialog** (`ui/components/discard_dialog.py`) that counts what
  goes (runs, extractions, scores, mismatches), offers Export first, and says
  "This cannot be undone."
- **G1**: refused while any run is `queued` or `running`, naming the run.
- **G2**: tagged mismatches are counted in the lead sentence, and the button
  becomes "Discard anyway" (warn and allow, `R-D3`).
- The corpus, feature set and prompt versions are `RESTRICT` and never go with
  it.
- Discard state is never persisted (§18.3), and SQLite zeroes freed pages
  (`SD29`).

So the request is not "add a delete". It is "make the delete reachable, and
make it hard to aim at the wrong thing".

## 2. Why it does not solve the pile-up

1. **Only one evaluation is reachable.** The Evaluation screen has no switcher
   and no `?evaluation=` (`SD32`), and `app.storage.client` starts empty on
   every page load (`SD54`). So `_current_evaluation` shows the one this tab
   last created, or else the newest. After "New evaluation" the older ones
   cannot be opened there at all. To discard the third of ten, the analyst has
   to discard the seven above it first.
2. **Results and Mismatches can switch, but cannot discard**, and their lists
   hold launched evaluations only. A draft nobody launched is reachable
   nowhere but as the newest.
3. **The dialog does not say which evaluation it is.** Its target line is
   `"{name} · N run(s)"`. Names are not unique, and "New evaluation" copies the
   feature set's name (`SD32`), so ten evaluations can read "Weather &
   conditions". The same is true of the chip's options on Results and
   Mismatches, which show the name alone.

## 3. Propositions

| # | Proposition | Cost | Status |
|---|---|---|---|
| **P1** | **Make every evaluation reachable on the Evaluation screen.** `?evaluation=<id>`, and the `evaluation · <name> ▼` chip Results and Mismatches already use (`SD54`), drafts included. The URL follows the evaluation on screen (`history.replace`, `features_view`'s precedent), so a reload or a copied link lands on the same one. The existing header discard then works on any evaluation. Discard stays in **one** place: no discard action on the Results picker | UI only | done, `SD59` |
| **P2** | **Make the confirm dialog say which evaluation it is.** The preview carries when it was launched (or that it never was), the models its runs used, the corpus · feature set · prompt version it pins, and its id. The service states the facts, the dialog formats the time in the host's zone (`SD37`). The chip's options carry the launch time beside the name, for the same reason | Additive fields on `DiscardPreviewView`; no API change | done, `SD59` |
| **P3** | **Make the confirmation match what would be lost.** Unlaunched draft or no scores: one click (today). Scores, no tagged work: today's dialog. **Tagged work: type the tagged count** before "Discard anyway" enables, instead of a relabelled button. `analyst_tag` is the only thing a re-run cannot recreate | UI only | done, `SD60` (§5) |
| P4 | **A "keep" marker.** An evaluation marked as a baseline is refused by discard until unmarked. Analyst-authored, like `analyst_tag`, so it is not a soft-delete flag | A column and a migration (phase author rule) | proposed, only if P1–P3 are not enough |
| P5 | **Show what is debris before choosing.** Each switcher option carries runs · scored · failed · tagged counts, so an analyst can tell an inconclusive evaluation from a reviewed one without opening it | Read-only counts on `EvaluationDraftView` or a sibling read model | proposed |

### Rejected

- **An undo window or soft delete.** §18.3 forbids persisted discard state
  (`deleted_at`, a flag, export bookkeeping). A deferred delete held in memory
  is lost or half-done on a restart. The export is the trace (`SD23`).
- **Bulk or multi-select discard.** §18.6 refuses a bulk verb over a
  destructive operation. With P1 and P5, one at a time is quick enough.
- **A discard on the Results / Mismatches picker.** A second place for the one
  destructive verb, on screens whose job is reading.

## 4. This branch: P1 and P2

### 4.1 P1 — the switcher

- `/evaluation?evaluation=<id>`. The page function takes the parameter and
  `build` hands it to `_current_evaluation`, which prefers it over the
  remembered id **once**: later redraws follow the remembered id, which is now
  the same one.
- An id that does not resolve (a discarded evaluation, a stale link) falls back
  to the newest and **says so** in a toast, rather than silently showing a
  different evaluation.
- The chip leads the toolbar's left group, as it leads the identity row on
  Results and Mismatches (`SD57`). Its options are all evaluations, drafts
  included, newest first, as links to `/evaluation?evaluation=<id>`.
- The toolbar's right group still holds exactly one secondary button (`SD32`).
  The chip is a `<button>` but not a `.btn`, so the test that counts the
  toolbar's buttons counts the right group's.
- After every paint, if the evaluation on screen is not the one the URL names,
  the URL is replaced (not pushed): after "New evaluation", after a discard
  that fell back to another evaluation, and on a bare `/evaluation`.

### 4.2 P2 — identity in the dialog and the chip

- `DiscardPreviewView` + `launched_at: datetime | None`, `models: tuple[str, ...]`,
  `inputs: str`, all defaulted, so run and delivery previews are unchanged.
  `api/v1/discard.py` maps fields explicitly, so the API and its OpenAPI
  snapshot do not change.
- `lifecycle_service.evaluation_preview` fills them: `launched_at` from the
  row; `models` from its runs' `model_name`, distinct and sorted; `inputs` as
  `"<corpus> · v<n> · <feature set> · v<n> · prompt v<n>"`, the labels the
  Evaluation toolbar already uses.
- The dialog, for an evaluation: a line saying `launched <dd.mm.yy - hh:mm:ss>`
  or `draft · never launched`, the models, the inputs, and the id in full.
- `evaluation_chip`'s options read `<name> · <launched time>` or
  `<name> · draft`, on all three screens.

### 4.3 Tests

| Layer | What |
|---|---|
| backend | `evaluation_preview` carries `launched_at`, the run models and the inputs; two evaluations sharing a name preview differently; a draft with no runs previews with `launched_at is None` and no models |
| ui | the chip leads the toolbar and lists every evaluation, drafts included, with their launch time; `?evaluation=<id>` opens that evaluation and not the newest; a stale id falls back and says so; the URL follows "New evaluation"; the discard dialog names launch time, models, inputs and id; discarding an older evaluation from its own URL leaves the newer ones untouched |

### 4.4 Overlap with `feat/evaluation-rename` (`SD58`)

That branch, in progress beside this one, puts an `evaluation-name` field at
the head of the same left group. Both are about telling evaluations apart, and
they meet in `_render_toolbar`. Whichever merges second resolves it: chip
first, then the name field, then the pinned inputs. The chip then repeats the
name the field shows; if that reads as noise, the chip's text can shrink to
`evaluation ▼` once the field is there. This branch takes `SD59`.

## 5. P3 — typing the tagged count (`SD60`)

- **Where it applies:** the dialog's tagged-work state, for a run and an
  evaluation alike, because both open the one dialog. Nothing changes for a
  draft, for work with no tags, or for a blocked discard (G1 first: typing
  cannot unblock a run that is still being written).
- **What is typed: the count**, `DiscardPreviewView.tagged_mismatches`. Not
  the name, which repeats (`SD32`) and can be copied off the screen. The
  count is the one figure about what cannot be recreated, and typing it means
  having read it. Surrounding spaces are ignored; anything else is not.
- **"Discard anyway" stays disabled** until the field holds the count, and
  follows the field both ways. The press handler checks the same state,
  because `disabled` is a UI state and a click can still arrive.
- **The server is unchanged.** G2 is still `force=true` on the route and the
  service. The typing guards against attention errors; it is not an access
  control, and the API stays scriptable.

### 5.1 Tests

| Layer | What |
|---|---|
| ui | the prompt and the field appear with tagged work and only then; Discard is disabled until the count is typed, and again when it is taken back; a wrong value (empty, off by one, a word) leaves it dead and a press does nothing; spaces are accepted; a blocked dialog asks for nothing; the Evaluation screen's tagged discard needs the count |
| e2e | `test_reset_discard.py`: tag a run's mismatches through the API, open its discard; a wrong count keeps the button disabled, the right one enables it, and the run goes |

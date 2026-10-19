# Name a corpus when it is created

A feature request, not a defect. Status: **built** on `worktree-corpus-naming`, from `78ccc9c`.

---

## 1. What was asked

> It would be useful to name and/or rename a corpus so it can be easily
> identified (ex: data-2023, only-canton-x, …).

Settled with the project owner before this was written:

| # | Question | Answer |
|---|---|---|
| 1 | Name at creation only, or relabel existing corpora too? | **At creation is enough for now** |
| 2 | Should a name be unique? | **No** — `v1`, `v2` per name stays as it is |
| 3 | A free-text description as well? | **Yes** |
| 4 | Suggest a name from the data (cantons in the selection)? | **No** — the analyst types something meaningful to them |
| 5 | Show the name more prominently in the evaluation / Results chips? | **No** — as it is |

## 2. What exists

| # | Finding | Anchor |
|---|---|---|
| F1 | The service and the API already take a free `name` (1–200) and `description` | `corpus_service.py:147-155`, `api/schemas.py:278-285` |
| F2 | The UI never offers either: it passes the delivery's own name, i.e. the host folder name, so every corpus frozen from one delivery carries the same name and differs only by `vN` | `import_view.py:893` |
| F3 | `CorpusView.description` is already on the read model and returned; nothing in `ui/` draws it | `readmodels.py:209`, `corpus_service.py:858` |
| F4 | The service does not check the name it is given: the 1–200 rule lives only in the API's pydantic model, so a caller of `freeze()` can store `"   "` or 300 characters (the column is `String(200)`) | `corpus_service.py:217` |
| F5 | `(name, version)` is unique and `version` is `next_version(name)`, so re-using a name is how a second freeze becomes `v2` | `models.py:324`, `corpus_repo.py:32` |
| F6 | `corpus` rows are never updated (Do-NOT #2), which is why renaming an existing corpus is **out of scope** (answer 1) and would need its own amendment | `models.py:315-320` |

## 3. Design

**Two optional fields beside the two freeze buttons, shared by both paths.**
The view holds `_corpus_name` and `_corpus_description` as attributes of the
per-page `_ImportPage` (not module globals — Do-NOT #8). The plain **Create
corpus** button and the scrub-preview dialog's own **Create** both read them,
so the analyst names the corpus once whichever route they take.

- **Name** is pre-filled with the delivery's name and can be overwritten.
  Leaving it as it is changes nothing from today.
- **Description** is empty by default and optional. It is a single line of
  text, shown as a second line under the name in the corpora table.
- **Validation lives in the service** (Do-NOT #7): `freeze()` strips the name,
  refuses blank and refuses more than 200 characters with a `ServiceError`,
  which the view already shows as a toast. The description is stripped and an
  empty one is stored as `NULL`, capped at 500 characters. The API's pydantic
  limits stay; the service no longer depends on its caller for them (F4).
- **The fields survive a redraw.** `reload()` redraws the corpora card, so the
  typed values are kept on the page object and re-applied; they are cleared
  only after a successful freeze, back to the delivery's name.
- **No schema change, no migration, no new route.** The API already carries
  both fields. The OpenAPI snapshot does not move.

Rejected: renaming an existing corpus (F6, answer 1); a unique name (answer 2);
a separate editable label (a migration for a need not yet stated); suggesting
names from the data (answer 4).

## 4. Stages

### Stage 1 — the service refuses what the column cannot hold

`CorpusService.freeze` checks `name` and `description` (F4).

**Done when:** `tests/backend` has a blank name, a 201-character name, an
untrimmed name (stored trimmed) and an empty description (stored `NULL`), each
asserting on the stored row or the raised error, never on message text.

### Stage 2 — the fields

Name and description inputs in the corpora card, wired into both
`_create_corpus` call sites; the description drawn under the name by
`_render_corpus_name`. Text-carrying props go through `data_props` (SD34): a
corpus name is typed by a person.

**Done when:** `tests/ui` shows (a) the default is the delivery name, (b) a
typed name and description reach `freeze` through the plain button, (c) the
same through the scrub-preview dialog, (d) the row shows the description, (e) a
second freeze under the same name is `v2`, (f) the typed values survive a
`reload()`.

### Stage 3 — end to end

One Playwright journey: type `only-canton-x` and a description, create, see
both in the table.

**Done when:** it is green in `just e2e`, and `just lint` and `just test` pass.

## 5. Contracts and amendments

None. `freeze` already has `name` and `description` in its frozen signature;
`CorpusView.description` and `CreateCorpusRequest` already exist. If Stage 1
turns out to need a new error type, it is named in an amendment under
`contracts/amendments/` rather than added to a frozen file.

`sw-design.md` gets `SD68` (`SD67` was taken meanwhile) in the same commit as
Stage 2: *a corpus is named at creation and the name is validated in the
service; renaming stays out because a corpus row is immutable.*

## 6. Open points

- **Placement.** The corpora card's header already holds two buttons, so the
  inputs probably go on a row of their own under it. That is a layout choice
  against `design/nav-import-census/README.md`, whose tokens are asserted in
  E2E; it will be checked there before it is built.

## 7. Where reality differed

- **API.** `CorpusNameError` is a `ServiceError` defined in `corpus_service.py`
  (no frozen file changed); `POST /api/v1/corpora` answers it with a plain 422.
  The OpenAPI snapshot did not move.
- **Reload test.** Not written as its own test. The typed state lives on the
  page object and the reset-after-freeze test covers its lifecycle; a faithful
  "survives a redraw" test needs a busy redraw mid-freeze, which the
  simulated user cannot hold open.
- **E2E.** A separate file, `tests/e2e/test_corpus_naming.py`, reusing J1's
  delivery and its deselect step, rather than editing the J1 journey.

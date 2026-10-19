# plan-codelists-usability.md — a usable JSON-key picker, a filterable column list, and automap

**Status.** Written 2026-10-19 against `78ccc9c`, from three requests made
while testing the Codelists screen rather than from a reproduced defect.
Authority as always: `mvp-spec.md` on *what*, `sw-design.md` on *how*
(CLAUDE.md). The first two changes are presentation. The third adds one pure
domain module, two service methods and one read model, so it touches **two
frozen files** (`ra2/services/readmodels.py`, `ra2/services/codelist_service.py`'s
signatures) under
[`contracts/amendments/feat-codelists-usability.md`](contracts/amendments/feat-codelists-usability.md),
and it amends `design/code-feature/README.md` first, in the same commit
(CLAUDE.md: "where it is wrong, change *that file first*"). **No Alembic
revision**: nothing new is stored. Branch `feat/codelists-usability`. No wave
is running, so the amendment is applied in the same commits, as has been
standard practice since `fix-b1-census-value-samples`.

---

## 1. What was asked, and what was settled

| # | Asked | Settled as |
|---|---|---|
| a | The JSON-key dropdown is too narrow and too long. Wider, and searchable | A **popover picker**, about 440 px wide and anchored to the field's right edge, with a search field that has focus on open. Each option is two lines: key and code count, then the attribute's name in the prompt language and its chapter. Search matches key, name and chapter |
| b | Filter the column list by table (accident, person, object) and by text | A **`table ·` chip** whose options come from the rows' own `table_name`, plus a **search box** in the list header. Both are display filters over the complete list, like the status chip |
| c | A way to automap the codes | **Suggestions the analyst confirms**, from two sources: **copied** from another corpus's mappings, and **code-value overlap**. Shown in a review dialog, and nothing is written until "Apply selected" |

Three decisions behind (c) need stating, because each rules something out.

**Name matching is out.** The real `codes-2018.json` uses English keys
(`weather`, `accident_type`, mvp-spec.md §7). A census column is called
`WitterungAusw`. The key never resembles the column, and the attribute's
German `name` only sometimes does. A matcher that is right on the synthetic
seed (where key = column, docs/seed.md §6) and wrong on the real file is worse
than none, because it teaches the analyst to trust it.

**Confirmed, never silent.** mvp-spec.md §7 calls the mapping
"analyst-set". A mapping also feeds every enum feature's fingerprint (§8.5),
so a mapping applied silently would change what a later evaluation asks
without anyone choosing to. Automap only *proposes*. Each write still goes
through `CodelistService`, to `column_mapping` only, and never to `code_value`.

**Overlap ranks; it never decides by itself.** Codes are mostly small
integers, so `{1, 2, 3}` lies inside half the attributes in the file. An
overlap suggestion is offered and left **unchecked**. Only a copied
suggestion is pre-checked.

---

## 2. The JSON-key picker (a)

Today: [`_json_key_select`](ra2/ui/views/codelists_view.py) uses
`JSON_KEY_BOX_STYLE = max-width:210px` (from the design README, line 100). It
draws a `_MENU_STYLE` panel with `min-width:100%` and `max-height:280px`, and
each option is a single `nowrap` mono line `key count`. `CodeAttributeView`
already carries `name` and `chapter`, but nothing displays them.

After:

- **The field** keeps its place in the edit header and grows to
  `max-width:320px`. Its closed text stays `key count`, as today. *Built
  that way rather than `key · name`:* the key is the identifier the mapping
  line, the prompt preview and J7 all name, and the name is one click away in
  the popover.
- **The popover** is a separate element, `width:440px`,
  `max-width:calc(100vw - 32px)`, `right:0`. *Not* `min(440px, 100%)`: the
  percentage resolves against the 320 px field box, which would make the
  popover no wider than the field it replaces. It opens leftwards, so it never pushes past the pane's right
  gutter (README: the header-right group "pushes past the pane's right gutter"
  otherwise). It is `max-height:60vh` with the option list scrolling inside
  it.
- **Search** is a plain `<input>` at the top of the popover, built from
  `ui.element` like every other control on this page rather than from Quasar's
  `ui.input` (R2: hit target, type scale). The filter runs **client-side, in
  the browser**, over options already in the DOM. Each option carries one
  `data-search` attribute set through `data_props` (SD31: key, name and
  chapter come from an imported file). A keystroke then costs no round trip
  and no re-render of the whole page. Case and diacritics are folded
  (`Witterung` matches `witterung`, `chaussée` matches `chaussee`).
- **Keyboard**: ↑/↓ move, Enter picks, Esc closes and returns focus to the
  field. `role="listbox"` / `role="option"` / `aria-activedescendant`.
- **"— not mapped —"** stays pinned above the search results and is never
  filtered away.
- **Overlap hint (optional, from §4).** Once `suggest_mappings` exists, each
  option for the selected column can carry `5 / 5 codes`. The list can also
  sort by that number, with ties in file order. It reuses the domain function
  and adds no new logic. It is listed here because it is the cheapest form of
  "automap" there is. **It is cut first if the slice runs long.**

`field_select` stays as it is: the change is local to the Codelists view,
whose JSON-key control is the only place the README clamps.

---

## 3. Filtering the column list (b)

`CodelistsState` gains two fields, so a table and a query survive a reload in
the same tab, as `status` already does:

```python
table: str | None = None   # None = "table · all"
query: str = ""
```

- **The `table ·` chip** sits between the language and status chips. Its
  options are `sorted({c.table_name for c in self._columns})`, read from the
  data. The UI holds no fixed list of tables: Do-NOT #5 is about filenames,
  but the reason behind it applies here too. Each option carries its live
  count, like the status chip. Labels are the table names as stored (`unfall`,
  `person`, `objekt`), the same words `_row_name` already prints.
- **The search box** sits in a second strip under the list header. The
  header itself has no room left: README measures 69 px + 157 px in a 299 px
  box. It matches the column name and the mapped key. This one
  *does* round-trip, because it changes the groups, the counts and the "N of M
  shown" footer, all of which are drawn on the server. Debounced at 250 ms,
  re-rendering only `_list_slot` rather than the whole page, so the input
  keeps its focus and caret.
- `_shown()` becomes status ∧ table ∧ query. The chip counts stay `len()` over
  the **complete** list, which the module docstring already insists on. The
  status chip's counts are taken *after* the table filter, so "status · missing
  4" is the number you see on screen.
- An empty result keeps `NO_COLUMNS_MESSAGE`, which already says "match this
  filter".

---

## 4. Automap (c)

### 4.1 The pure part — `ra2/domain/codelist_suggest.py` (new)

```python
class SuggestionSource(StrEnum):
    COPIED = "copied"     # the source corpus mapped this column to this key
    OVERLAP = "overlap"   # ranked by code-value overlap alone

@dataclass(frozen=True, slots=True)
class MappingSuggestion:
    column_name: str
    attribute_key: str
    source: SuggestionSource
    #: Distinct corpus values present among the attribute's codes / distinct values.
    distinct_contained: float
    #: The same, weighted by record count — a rare stray value weighs little.
    records_contained: float
    #: |values ∩ codes| / |values ∪ codes| — prefers the attribute that is *just* big enough.
    jaccard: float

def suggest_mappings(
    columns: Mapping[str, Sequence[tuple[str, int]]],   # column → GROUP BY value_raw
    attributes: Mapping[str, frozenset[str]],          # key → its codes (latest import)
    copied: Mapping[str, str],                         # column → key, from the source corpus
) -> tuple[MappingSuggestion, ...]: ...
```

The rules, each one with a unit test:

1. **Copied wins.** If `copied[column]` names a key that exists in the latest
   import, that is the suggestion, with its overlap numbers attached so a bad
   copy is visible (`3 / 7 codes`). A copied key **absent** from the latest
   import gives *no* suggestion for that column. The service reports it as an
   unresolved row (§4.2) and never falls back silently to overlap
   (Do-NOT #6).
2. **Overlap otherwise.** Rank by `records_contained`, then `jaccard`, then key,
   so the order is deterministic. Suggest the top candidate only if
   `distinct_contained == 1.0` and its `jaccard` beats the runner-up's. A tie
   gives no suggestion, because a coin-flip is not a proposal.
3. **Exact codes only.** `"04"` does not match `"4"`. The coverage check
   (`compute_coverage`) applies the same rule, and coercing to the nearest
   code is what §7 forbids. A column whose leading zeros were lost shows up
   here as *no overlap*, which is the truth.
4. **An all-empty column** (no cells) gets no suggestion.
5. **One distinct value is no evidence.** A column holding a single value
   gets no *overlap* suggestion (`MIN_OVERLAP_DISTINCT = 2`). That value sits
   inside every attribute that has it, so the tightest fit would just be the
   smallest attribute. *Added after looking at the dialog:* on the E2E
   delivery, every single-valued column was proposed `injury_severity`. A
   copy has no such floor, because it rests on a decision, not on the data.

Pure, as §1 requires: no session, no I/O, plain values in and out.

*As built*, `Overlap` carries counts (`contained`, `distinct`) rather than
one `distinct_contained` ratio, because the dialog prints `5 / 5`. "Beats the
runner-up" means beating the runner-up **among the attributes that also cover
the column**. One that covers less can have a higher Jaccard and still not
be a candidate.

### 4.2 The service part — `CodelistService`

```python
async def suggest_mappings(
    self, corpus_id: CorpusId, *, source_corpus_id: CorpusId | None
) -> MappingSuggestionsView: ...

async def apply_mappings(
    self, corpus_id: CorpusId, picks: Sequence[tuple[str, CodeAttributeId]]
) -> int: ...
```

- `suggest_mappings` reads the corpus's enum census columns, the
  `GROUP BY value_raw` of each one (the query `coverage()` already runs,
  through `CodelistRepository.coverage_counts`), the latest import's
  attributes and codes, and, if a source is given, that corpus's
  `column_mapping` rows resolved to **attribute keys**. Keys, not ids: the
  source may have been mapped against an older `code_table_import`, and
  `list_attributes` offers only the latest generation.
- `source_corpus_id=None` defaults to **the newest other corpus with the same
  `name`** (the previous version) that has any mappings. Failing that, it
  falls back to **the most recently imported other corpus that has any
  mappings**: once `plan-corpus-naming.md` lands, a name is the analyst's
  choice (`only-canton-x`), and two corpora cut from one delivery no longer
  have to share one. With no mapped corpus at all, there is no copy source and
  the result is overlap-only. The dialog names the source it chose and lets
  the analyst pick any other corpus.
- The read model, `MappingSuggestionsView`, holds `source_corpus_id`,
  `suggestions`, and `unresolved`: the columns whose copied key is not in the
  latest import, each with the key. Columns that are already mapped are
  **included**, flagged `currently: <key>`, so the dialog can show a
  disagreement. They are never pre-checked.
- `apply_mappings` writes every pick in **one transaction**, through
  `repo.set_mapping`, and returns how many it wrote. An unknown attribute id
  raises `NotFoundError` and writes nothing. It resolves the census columns
  once for the whole batch. Calling `map_column` once per row would be N
  transactions, and `_matching_census_column` pages every census column
  each time, so 100 picks would mean about 10 000 rows read.

### 4.3 The dialog — `codelists_view.py`

- An **"Automap…"** secondary button at the right end of the search strip
  (§3), for the same reason the search box is there. It is disabled until
  there is a corpus and a codelist import.
- A dialog parented to `_root`, the same surface as `_open_import`. It shows a
  `from corpus …` chip with the default source from §4.2, then a table:
  ☐ · column (with `_row_name`) · suggested key and name · source pill
  (`copied` / `overlap`) · `distinct_contained` as `5 / 5 codes` ·
  `currently` if mapped.
- **Pre-checked**: copied suggestions for columns that are currently
  unmapped. Everything else is unchecked. Unresolved rows are listed beneath
  the table in `--warn`, with no checkbox. A suggestion whose
  `distinct_contained < 1` shows its number in `--warn`.
- "Apply selected (N)" calls `apply_mappings` once, notifies "Mapped N
  columns.", closes and runs `reload()`. "Cancel" writes nothing.
- All the wording lives in this file's copy table, and the source pill
  renders from `SuggestionSource`'s value (*Findings, not prose*).

### 4.4 The API

Not in this slice. The UI calls services in-process (§1), and nothing outside
the UI needs bulk mapping yet. If a script ever does, it is two thin routes in
`api/v1/codelists.py` plus a refreshed `openapi_snapshot.json`. **Open
question for review**: should those routes ship now so the API and the UI stay
equal?

---

## 5. Frozen files, and the amendment

| File | Change | Why it is frozen |
|---|---|---|
| `ra2/services/readmodels.py` | + `MappingSuggestionView`, `MappingSuggestionsView`, `UnresolvedCopyView` | Phase 2 read models (CONTRACTS.md) |
| `ra2/services/codelist_service.py` | + `suggest_mappings`, `apply_mappings` signatures | "constructor + typed method signatures" frozen |
| `design/code-feature/README.md` | the 210 px clamp replaced by §2's popover; the `table ·` chip, the search box and the Automap button and dialog added to Screen 1 and to its `filters:` state block | design fidelity is asserted (sw-design.md §8.2) |

`domain/codes.py` and `domain/codelist_coverage.py` are **not** touched:
the new types live in their own module, as `codelist_coverage.py` was split
from `codes.py` (sw-design.md §14.3).

---

## 6. Tests

| Layer | File | Asserts |
|---|---|---|
| unit | `tests/unit/test_codelist_suggest.py` (new) | copied wins; a copied key missing from the import gives no suggestion; overlap needs full containment and a clear margin; a tie gives none; `"04"` ≠ `"4"`; an all-empty column gives none; deterministic order |
| backend | `tests/backend/test_codelist_suggest_service.py` (new) | default source = previous version of the same name; keys resolved across import generations; `unresolved` populated; already-mapped columns flagged and never altered by `suggest`; `apply_mappings` is one transaction and writes nothing on an unknown id; `code_value` row count unchanged |
| ui | `tests/ui/test_codelists_view.py` (extend) | table chip options come from the rows; table ∧ status ∧ query; counts over the complete list; the search box keeps focus across a debounced redraw; the picker shows name and chapter; the dialog pre-checks only copied-and-unmapped; Apply calls the service once |
| e2e | `tests/e2e/test_j7_codelists.py` (extend) | the popover stays inside the edit pane; typing filters options with no server round trip; ↑/↓/Enter/Esc; the column search keeps its focus while the list re-filters; a hand-made mapping is copied into a second corpus, pre-ticked, and the checkbox survives a real browser |

Fixtures: one corpus at version 1 and version 2 under the same name, v1
mapped. A codelist import with an attribute whose codes are `01..04` and
another whose codes are `1..4`, so the leading-zero hazard is in the fixture
(mvp-spec.md §15). A second import generation that drops one key, so
`unresolved` has something to say.

---

## 7. What this plan does not do

- **No name matching**, for the reason in §1. If a later codelist file uses
  column-shaped keys, adding it is one more `SuggestionSource` and one more
  rule in a pure function.
- **No automatic carry-over on corpus freeze.** It was considered and
  declined: it is the silent version of §4.
- **No mapping file export/import.** Copy-from-corpus covers moving
  mappings between versions on one host. A file would be the way to move them
  between hosts, and nobody has asked for that.
- **No fix to `list_columns`' O(N²) census paging** (`_matching_census_column`
  per column). It is real but separate, and §4.2 avoids it on the new path.
  It is worth its own `fix-` branch if the screen feels slow on a full corpus.
- No change to the stale "blocks 0 features" wording on the danger chip.
  That is noted, but it is not one of the three requests.

## 7a. Found on the way

Three defects that the new E2E journeys exposed. Each is fixed on this
branch, with a test.

- **`CodelistRepository.get_latest_import` had no total order.** It sorted by
  `imported_at` alone. Two generations in one clock tick (Windows ticks every
  ~15 ms; the E2E server's clock is frozen) made "the current code table"
  whichever row SQLite returned first, so the JSON-key options could be
  another file's. The fix adds `id DESC` as the tie-breaker. Production ids are
  UUIDv7 and sort by creation time; the E2E ids (`id-%08d`) do too.
- **A NiceGUI `<input>` carrying a `value` prop is reset by any update
  anywhere on the page.** NiceGUI renders the whole tree from one function,
  and Vue re-applies `value` on every render. So the column search lost its
  text mid-word as the list it filters redrew. The field now carries no
  `value` prop, and the browser alone owns the text. `features_view._text_input`
  has the same shape. It is not touched here, because nothing redraws while
  those fields are being typed in, but it is worth knowing.

- **J8 and J9 counted corpora on a page that shows ten.** Both asserted
  `before + 1` rows in the Import view's corpora table after freezing one. On
  `main`, the session-scoped E2E server reaches J9 holding nine corpora, so
  *any* new journey that freezes one fails J9, and only in a full run. This
  branch's J7 journeys did; so will `worktree-corpus-naming`'s new journey.
  Both now count the API's unpaged `meta.total` instead
  (`_corpus_total`), and the new J7 journeys share one corpus between them
  anyway.

## 8. Order of work

1. README amendment + `contracts/amendments/feat-codelists-usability.md`.
2. (b) list filters: `CodelistsState`, the chip and the search box, with UI
   tests. Standalone and low-risk.
3. (a) picker: popover and client-side search, with UI and E2E tests.
4. (c) domain → service → dialog, each with its own layer's tests, then the
   optional overlap hint in the picker.
5. **Code review**, before anything is merged. The diff since `78ccc9c` is
   reviewed along the two axes `/code-review` (the mattpocock skill) uses, in
   parallel sub-agents:
   - **Standards**: CLAUDE.md's Do-NOT list and layer rule (no logic in
     `ui/`, no session in `ui/`, no module globals, every value from the
     delivery or the codelist through `data_props`, no write to `code_value`,
     no test-only branch), and whether the code matches what is around it.
   - **Spec**: this plan against the diff. Every row of §1 and §6 delivered,
     nothing from §7 added, and the amendment file naming every frozen file
     the diff touches (`git diff --name-only` against CONTRACTS.md).

   A finding is either fixed in a follow-up commit on the branch or written
   up as a deliberate deviation in this plan, with its reason. After the
   fixes, `just lint`, `just test` and the E2E suite are run again from
   scratch. The final report lists the findings and what happened to each.

Each implementation step ends with `just lint` and `just test` green, and is
checked by eye with `just dev-agent`. Steps 2–4 are committed separately, so
the review in step 5 can read them one at a time.

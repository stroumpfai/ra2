# plan-mismatch-context.md — enough context on a mismatch row to tell a hallucination from a record error

**Status.** Written 2026-10-20 against `543eb0f`, from a request made while
reviewing mismatches rather than from a reproduced defect. Authority as
always: `mvp-spec.md` on *what*, `sw-design.md` on *how* (CLAUDE.md). The
change is mostly presentation. It adds two pure domain modules, one service
method and one read model, and widens two existing read models, so it
touches **frozen files**: `ra2/services/readmodels.py`, `ra2/api/schemas.py`,
and the signatures of `ra2/services/mismatch_service.py` (+ `detail()`).
`ra2/services/export_service.py` is frozen for its signatures only, and only
its body changes. Those three changes are made under
[`contracts/amendments/feat-mismatch-context.md`](contracts/amendments/feat-mismatch-context.md).
*(Corrected by the branch review: this paragraph first also listed
`mismatch_repo.py` and `ui/state.py`, whose headers say they are not frozen.)*
It corrects `plan-phase-5.md` C5 and adds `SD71` to `sw-design.md` first, in
the same commit. **No Alembic revision**: everything shown is already stored.
Branch `feat/mismatch-context`. No wave is running, so the amendment is
applied in the same commits, as has been standard practice since
`fix-b1-census-value-samples`.

---

## 1. What was asked, and what was settled

The analyst tags each mismatch `hallucination` · `structured_data_error` ·
`unclear` (mvp-spec.md §12). Today the row gives them the feature key, a
truncated **internal** record id, two bare codes and the evidence span.
That is not enough to decide.

| # | Asked | Settled as |
|---|---|---|
| P1 | A reference to the UnfallUid | The **`UnfallUid`** replaces the internal `RecordId` in the Record column, in the CSV and as the `record` sort key |
| P2 | The structured data, with its codes and enum | **`code · label`** for both values, in the table and in the detail, decoded from the **launch-time codelist snapshot** (`evaluation_feature.enum_codelist_json`) in the evaluation's prompt language |
| P3 | The accident description | An **inline detail row**, opened from the row, one at a time: the full narrative with the evidence span **highlighted** where it occurs |
| P5 | (structured data, scope) | **This feature only**: its description, matching rule, source column or derivation expression, and both values decoded. Not the whole record |

Three decisions behind this need stating, because each rules something out.

**P1 is a spec gap, not a feature.** mvp-spec.md §12 lists "record key" as
part of every mismatch row, and plan-phase-5.md C3 makes "record key" a sort.
`MismatchRowView.record_id` is the surrogate key, so the screen shows an id
no delivery contains and sorts on it. `MISMATCH_SORT_KEYS` keeps the name
`record`; only what it sorts on changes.

**The labels come from the snapshot, not from Codelists.** A mapping or a
codelist import can change after launch. The snapshot is what the model was
actually shown (§8.5 hashes it, label text included), so decoding against
anything else could put a label on screen that the model never saw. A code
that isn't in the snapshot is shown as a fact, `4 · not in code table`, and
never left blank (Do-NOT #6's reasoning: nothing disappears silently).

**Highlight only. The screen never says "span not found".** A span that
doesn't occur in the narrative is strong evidence of a hallucination, and
flagging it is the first step of the automatic triage that mvp-spec.md §16
defers as `D1`. The highlight is display; if nothing lights up, the analyst
sees that for themselves. If D1 is ever taken up, the domain function in §4.1
is already the input it needs.

---

## 2. The UnfallUid (P1)

Today: `MismatchRepository.list_for` and `_row` join `Feature.key` and
`Record.text_anonymised_flag`. `_view` in
[`mismatches_view.py`](ra2/ui/views/mismatches_view.py) prints
`str(row.record_id)[:RECORD_ID_CHARS]` (14) in a 190 px cell beside the
anonymisation chip.

After:

- **Repository.** Both queries also select `Record.unfall_uid`;
  `MismatchListRow` gains `unfall_uid: str`. `_order("record")` sorts on
  `Record.unfall_uid`, then `Mismatch.id` as the tie-breaker, so the order is
  total.
- **Read model.** `MismatchRowView` gains `unfall_uid: str`. `record_id`
  stays: the detail (§4) and the API need it to address the record.
- **View.** The Record cell shows the **whole** UID, mono, with
  `overflow-wrap:anywhere`, and the chip on a line of its own beneath it. The
  column stays 190 px and the fixed total stays 956 px. `RECORD_ID_CHARS` is
  deleted. A UID is up to 32 characters (`_UID_LEN`); one that is longer than
  the column wraps onto a second line instead of being cut. A truncated key
  can't be searched for in the source system, and that search is the reason
  it's on screen.
- **CSV.** `unfall_uid` is **appended** to `_MISMATCHES_CSV_HEADER`, so
  every existing column keeps its position.
- **API.** `MismatchResponse.unfall_uid: str`, additive. OpenAPI snapshot
  regenerated.

---

## 3. Code · label (P2)

### 3.1 The pure part — `ra2/domain/code_label.py` (new)

```python
class LabelState(StrEnum):
    LABELLED = "labelled"          # the code is in the snapshot, with a label in the language
    NO_LABEL = "no_label"          # in the snapshot, but no label in that language
    NOT_IN_TABLE = "not_in_table"  # an enum feature, and the code is not in its snapshot
    NOT_ENUM = "not_enum"          # nothing to decode; the value is shown as it is
    EMPTY = "empty"                # no value at all (as built, rule 3)

@dataclass(frozen=True, slots=True)
class DecodedValue:
    raw: str | None
    label: str | None
    state: LabelState
    language: str | None = None    # as built: so "no de label" can name the language

def decode(
    value: str | None,
    codes: Sequence[CodeValue] | None,   # snapshot_from_json(...) or None
    language: str,
) -> DecodedValue: ...
```

The rules, each with a unit test:

1. **Exact codes only.** `"04"` does not decode as `"4"`, which is the rule
   `compute_coverage` and the scorer already apply.
2. **The prompt language, and no fallback to another one.** A `de` evaluation
   with only an `fr` label gives `NO_LABEL`. Showing the French label would
   show the analyst words the model was never given.
3. ~~`None` or empty stays `None` with the state of its feature (`NOT_ENUM`, or
   `LABELLED` with `label=None`).~~ *As built:* `None` or empty is its own
   state, `EMPTY`, whatever the feature. `LABELLED` with no label would have
   been a state that contradicts its name. The view renders `—`, as it does
   today. (In practice an empty value is scored `missing`, never `wrong`, so it
   doesn't reach this list; the state exists so the decoder is total.)
4. Pure: no session, no JSON. The service parses the snapshot with the
   existing `snapshot_from_json` and hands over values.

### 3.2 The service and the table

- `MismatchService._view` already loads the evaluation's features. It also
  loads their `EvaluationFeature` rows: **one query per page**, not one per
  row, with each snapshot parsed once per feature. `MismatchRowView` gains
  `record_decoded: DecodedValue` and `extracted_decoded: DecodedValue`, and
  `record_value` / `extracted_value` stay as they are, verbatim.
- **In record** and **Extracted** (110 px each) show the code on the first
  line, as today. Under it, the label in `--ink2`, clamped to two lines. The
  full label is in the detail, so the clamp hides nothing that isn't
  reachable by keyboard. `NOT_IN_TABLE` renders `not in code table` in
  `--warn`, and `NO_LABEL` renders `no <lang> label` in `--ink3`. The words
  live in this view's copy table, keyed by `LabelState` (*Findings, not
  prose*).
- **CSV**: `record_label` and `extracted_label` are appended after
  `unfall_uid` (empty unless `LABELLED`). *As built (step 3's review, 3.1):*
  `record_label_state` and `extracted_label_state` follow them, so an
  invented code is not a blank in the file.
- **API**: `MismatchResponse.record_label`, `.extracted_label`,
  `.record_label_state`, `.extracted_label_state`, additive.

---

## 4. The detail row (P3 + P5)

### 4.1 The pure part — `ra2/domain/span_locate.py` (new)

```python
def locate(text: str, span: str) -> tuple[tuple[int, int], ...]:
    """Every non-overlapping occurrence of `span` in `text`, as (start, end)
    offsets into `text`, left to right. Empty when there is none."""
```

1. **Exact first.** Every non-overlapping verbatim occurrence.
2. **Whitespace-tolerant second, only if exact found nothing.** Runs of
   whitespace on both sides compare equal, and offsets map back into the
   original text. This is the embedded-newline hazard: the narrative breaks
   a line where the model's quote has a space.
3. **Nothing else**: case-sensitive, no Unicode normalisation, no fuzzy
   distance. A lossy French `chauss?e` in the narrative matches only a span
   that carries the same `?`. Anything looser would be a similarity
   threshold, and that is `D1`.
4. An empty span or a `None` text gives `()`.

### 4.2 The service part — `MismatchService.detail`

```python
async def detail(self, mismatch_id: MismatchId) -> MismatchDetailView: ...
```

`MismatchDetailView` (new, frozen dataclass in `readmodels.py`):

| Field | From |
|---|---|
| `mismatch_id`, `unfall_uid` | `mismatch`, `record` |
| `narrative: str \| None` | `record.text_raw`, which was scrubbed at freeze (§19) |
| `highlights: tuple[tuple[int, int], ...]` | `span_locate.locate(narrative, evidence_span)` |
| `language`, `language_confidence` | `record` (French loses characters to encoding, §4.5; the analyst should see which language a text is in) |
| `anonymisation: AnonymisationMarking` | the same resolution `_row_view` already uses (§13, SD50) |
| `feature_key`, `feature_description` | `feature` |
| `matching_rule: MatchingRule` | `feature.matching_rule`, through `feature_service.matching_rule_from_json` |
| `source_column: str \| None`, `derivation: DerivationSpec \| None` | `feature`: one or the other |
| `record_decoded`, `extracted_decoded` | §3.1, with the full label |
| `evidence_span` | verbatim |

**Structured values, worded in `ui/`.** The words for a rule and for a
derivation already exist, but they're private to Features:
`features_view._matching_rule_label` (which takes a `_FeatureDraft`) and
`derivation_builder._expression`. Step 4 makes them public, as
`rule_label(MatchingRule)` and `expression(DerivationSpec)` in
`ui/components/`, and has Features and Mismatches call the same functions.
That's a move, not a rewrite. Features' existing UI tests pin the wording.
*As built:* `components/matching_rule.py` has `rule_label(kind, rule)` and
`rule_help(kind, value_type, rule)`, because Features words an exploratory
feature and an enum feature differently. After review 4.4, it also has
`rule_parameter(rule)` (`± N min`, `N decimals`); `derivation_builder.expression`
is the derivation's line.

**Fetched when the row opens, not with the page.** Loading 25 narratives to
show at most one would move narrative text through every page render for
nothing. `NotFoundError` if the mismatch is gone (a discarded run under an
open tab), and the view shows the existing refusal toast.

### 4.3 The view

- **A toggle, not a clickable row.** A chevron button at the start of the
  Feature cell: a real `<button>` with `aria-expanded` and `aria-controls`,
  so Tab reaches it. A row-wide click target would also capture clicks on
  the Tag control. Extraction's breakdown row has to `stopPropagation` its
  link for exactly that reason.
- **One open at a time.** `MismatchesState` gains `open_mismatch_id: str = ""`
  (`app.storage.client`, Do-NOT #8). Changing a filter, the sort or the page
  clears it. A tag written while a detail is open leaves it open.
- **The row** is a `<tr>` with `colspan="7"` on the `--accent-soft`
  background, the shape of Extraction's `_breakdown_row`. Inside it, two
  columns:
  - **left, flexible:** the narrative, `white-space:pre-wrap`,
    `max-height:240px`, scrolling inside its box, with the language and the
    anonymisation `chip` above it. Each highlight is a `<mark>` styled with an
    **existing** token (chosen while building; no new colour, R2). Text goes
    in through `ui.label`/text nodes, never as HTML (SD31). With no narrative,
    `no narrative on this record` in `--ink3`.
  - **right, 320 px:** the feature facts as label/value pairs: key and
    description · rule · source · In record `code · label` · Extracted
    `code · label` · the evidence span. *The structured record is
    authoritative in every case* stays in the toolbar caption, not repeated
    here.
- `data-testid`s: `mismatch-toggle`, `mismatch-detail`, `detail-narrative`,
  `detail-highlight`, `detail-facts`.

*As built:* the detail row needed a way into `data_table`, which draws only
body rows. It gained an `after_row` hook that draws whatever the caller
returns under a row, inside the `<tbody>`, and decides nothing itself. The
facts are a `<dl>`. The mark is `--warn-soft` over `--ink`, existing tokens
(R2). The row's DOM id goes through `data_props`, like every other
data-derived prop (`SD31`).

---

## 5. Documents this changes first

| Document | Change |
|---|---|
| `plan-phase-5.md` C5 | The premise was false: there is **no** Results per-record drill-down that shows the narrative (only Goal 2's per-record list, which shows none). The answer becomes "not in the list; in an on-demand detail row, `plan-mismatch-context.md`". §3.2's column table gets the UID and label lines |
| `sw-design.md` §17.8 | + `MismatchDetailView`, `DecodedValue`; **`SD71`**: labels decode from the launch snapshot in the prompt language with no fallback, and the span is highlighted but never judged |
| `mvp-spec.md` | **Nothing.** §12 already asks for the record key, and §13 already allows text on a drill-down |

**Found on the way, not fixed here:** mvp-spec.md §13 surface 6 asks for a
Results "per-record drill-down showing text, extracted values, spans" and it
doesn't exist. This plan's detail row covers the need *for a mismatch*. A
record page for Results is its own plan, and `detail()` is half of it.

---

## 6. Frozen files, and the amendment

| File | Frozen? | Change |
|---|---|---|
| `ra2/services/readmodels.py` | yes | `MismatchRowView` + `unfall_uid`, `record_decoded`, `extracted_decoded`; + `MismatchDetailView` |
| `ra2/services/mismatch_service.py` | signatures | + `detail()` signature |
| `ra2/api/schemas.py` + OpenAPI snapshot | yes | additive fields on `MismatchResponse` |
| `ra2/services/export_service.py` | signatures; body changed only | ~~three~~ *as built:* five appended CSV columns (`unfall_uid`, two labels, two label states) |
| `ra2/persistence/repositories/mismatch_repo.py` | no | `MismatchListRow` + `unfall_uid`; the `record` sort key's column |
| `ra2/ui/state.py` | no | `MismatchesState.open_mismatch_id` |

**Not in this slice:** an API route for `detail()`. The UI calls services
in-process, and nothing outside the UI needs it yet (settled, §10).

---

## 7. Tests

| Layer | File | Asserts |
|---|---|---|
| unit | `tests/unit/test_code_label.py` (new) | each `LabelState`; `"04"` ≠ `"4"`; no fallback across languages; ~~`None` stays `None`~~ `None` is `EMPTY` (rule 3 as built) |
| unit | `tests/unit/test_span_locate.py` (new) | every exact occurrence, non-overlapping; whitespace-tolerant only when exact misses, offsets back into the original across a `\n` and a `\r\n`; case-sensitive; a lossy `?` matches only itself; empty span / `None` text gives `()` |
| backend | `tests/backend/services/mismatch/test_mismatch_context.py` (new) | list rows carry `unfall_uid` and both decodings; `record` sorts by UID with a total order; snapshot queries bounded per page (statement count, not wall clock, §16.2); labels come from the **snapshot** after the live mapping has been changed; `detail()` carries narrative, highlights, marking, rule and source for a native, a derived and a non-enum feature; `NotFoundError` on a missing id |
| backend | `tests/backend/services/export/…` (extend) | the three columns appended, earlier columns unmoved |
| backend | `tests/backend/api/…` (extend) + snapshot | the additive fields; snapshot diff is additions only |
| ui | `tests/ui/test_mismatches_view.py` (extend) | the full UID in the Record cell; `code · label` and the two non-label states' words; the toggle opens one detail, a second toggle moves it, filter/sort/page close it; highlights rendered as `<mark>`; no-narrative state; the chip present in the detail |
| e2e | `tests/e2e/test_results_j14_mismatches.py` (extend) | at 1280 px: a 32-character UID wraps and stays inside its cell; the fixed total is still 956 px; the detail row spans the table; the toggle is reachable by Tab and Enter; the Tag control inside an open row still writes; **J6 unchanged**: no request leaves the server under test |

**Fixtures** (synthetic and committed, mvp-spec.md §15, never from `data/`):
a narrative whose span crosses an embedded newline; a span that occurs
twice; a span that isn't in the text; lossy French in both text and span; a
record with `text_raw = None`; a `NULL` record value; an extracted code
missing from the snapshot; a code with only an `fr` label under a `de`
evaluation; a derived feature and a time feature with a tolerance; a
32-character UID; and the live mapping changed after launch, so a test that
reads labels from Codelists instead of the snapshot fails.

*As built:*
- **The unit tests live in `tests/unit/mismatch/`**, beside `test_tally.py`.
- **There is no separate `tests/backend/services/export/` test.** The CSV
  columns are asserted in `test_mismatch_context.py`, through a real CSV
  reader.
- **There is no time feature with a tolerance.** `scored_corpus` has none,
  and the rule's words are the ones Features already renders and tests
  (`components.matching_rule`); the detail passes the rule through
  unchanged.
- **A `NULL` record value and an empty extracted value never become
  mismatches**: they score `missing`, not `wrong`. The `empty` state is
  covered by the unit tests only.
- **The derived mismatch is made by changing one `vehicles` answer** before
  scoring, because the shared fixture gets every count right.
- **The keyboard check is focus and Enter on the toggle, not a Tab walk.**
  The toggle is a real `<button>`, so it is in the tab order by
  construction.

---

## 8. What this plan does not do

- **No "span not found" marker**, no similarity score, no sort or filter by
  either (§1, `D1`, and plan-phase-5.md §3.2's "one thing this screen must
  not grow").
- **No whole-record view.** Other `unfall` cells and `objekt`/`person` rows
  are out, by the scope choice. That includes a derived feature's inputs: the
  detail shows the expression and the derived value, not the objects behind
  it.
- **No raw model output and no other mismatches of the same record.** Both
  were offered and not chosen.
- **No narrative in the CSV.** The file already carries spans and is
  sensitive for it; the full text would make it a copy of the corpus.
- **No record page** (§5, found on the way).
- **No UID in the discard-time export.** `run_mismatches_csv` (the discard
  dialog's file, sw-design.md §18.3) still keys records by the surrogate
  `record_id`, and after a discard that id points at nothing. It is the same
  gap as P1 in a different file, found by step 2's review. It is left for its
  own `fix-` slice because it touches `MismatchExportRow` and the discard path,
  neither of which is on this plan's path.

---

## 9. Order of work

1. **Docs and amendment**: `plan-phase-5.md` C5 and §3.2, `sw-design.md`
   §17.8 + `SD71`, `contracts/amendments/feat-mismatch-context.md`.
2. **P1 UID**: repo → read model → view → CSV → API, with backend, UI and
   the E2E width test. Standalone, low risk, and a spec fix on its own.
3. **P2 labels**: `domain/code_label.py` → service → table cells → CSV → API.
4. **P3/P5 detail**: `domain/span_locate.py` → `detail()` → state → view,
   then the E2E journey.
   **A step review closes each of steps 2–4**, before the next one starts.
   `/code-review` runs on that step's commit alone (`git diff HEAD~1`), and
   it looks for correctness bugs and breaks of the layer rule. Each finding
   is fixed in the same step, or carried into this plan as a deliberate
   deviation with its reason. Both go into §11's table under the step's
   number. A bug in P1 is cheaper to fix before P2 builds on the same read
   model.
5. **Branch review**, before anything is merged. The diff since `543eb0f` is
   reviewed along the two axes `/code-review` (the mattpocock skill) uses, in
   parallel sub-agents:
   - **Standards**: CLAUDE.md's Do-NOT list and layer rule. The places this
     slice is most likely to slip: decoding or span logic in `ui/` (#7), the
     open row in a module global (#8), narrative or labels reaching the page
     as HTML rather than text (SD31), a test-only branch (#12), and any
     fixture or debug step that read `data/` (#13).
   - **Spec**: this plan against the diff. Every row of §1 and §7
     delivered, nothing from §8 added, and the amendment file naming every
     frozen file the diff touches (`git diff --name-only` against
     CONTRACTS.md).

   A finding is either fixed in a follow-up commit on the branch or written
   up here as a deliberate deviation, with its reason. After the fixes,
   `just lint`, `just test` and the E2E suite run again from scratch, and
   §11's table records every finding and its outcome.

Each implementation step ends with `just lint` and `just test` green, and is
checked by eye in the E2E harness or `just dev-agent` with a throwaway seed,
never a real corpus. Steps 2–4 are committed separately, so the review in
step 5 can read them one at a time.

---

## 10. Questions settled (2026-10-20)

1. **UID length.** 32 characters is fine. The Record column stays 190 px and
   a long UID wraps onto two lines (§2).
2. **Labels in the table.** Taller rows are acceptable. The label stays under
   the code in both value columns (§3.2).
3. **API route for `detail()`.** Not now (§6). It waits until something
   outside the UI asks for it.

---

## 11. Code review findings, and what happened to each

Filled in as the reviews run: step reviews under their step number (2, 3,
4), the branch review under 5.

| # | Step | Finding | Outcome |
|---|---|---|---|
| 2.1 | 2 | `MismatchRowView.unfall_uid` and `MismatchResponse.unfall_uid` default to `""`, so a forgotten field ships an empty key | **Fixed** on the wire: `MismatchResponse.unfall_uid` is required. **Kept** on the read model: the frozen `tests/test_p5_contract.py` builds a row without it. The backend test asserts every row's UID against its record |
| 2.2 | 2 | `data-handling.md` §3's export table no longer says what the review-list CSV carries (a delivery key now) | **Fixed** |
| 2.3 | 2 | `run_mismatches_csv` (the discard dialog) still keys records by the surrogate id | **Recorded** in §8 as its own `fix-` slice |
| 2.4 | 2 | The CSV test split lines and fields by hand, which misreads a quoted `;` or newline | **Fixed**: `csv.reader`, and every row's UID asserted |
| 2.5 | 2 | Frozen files edited in place | **Kept**: house practice since `fix-b1-census-value-samples` while no wave runs; the amendment says "applied", and CONTRACTS.md now has the slice entry the review asked for |
| 2.6 | 2 | The `j14` fixture's UIDs are 34 characters, past `String(32)`, which SQLite does not enforce | **Kept**: it is the shared fixture, and a longer value is the harder test of the wrap. The UI test pins the 32-character case |
| 2.7 | 2 | `UID_STYLE`'s comment promised a line count nothing enforces | **Fixed**: the comment says what happens, not a bound |
| 2.8 | 2 | Sorting by `Record.unfall_uid` across the join sorts the whole filtered run per page | **Kept**: runs are thousands of rows; the old `record_id` order had no usable index either |
| 3.1 | 3 | The CSV wrote only the label, so `not_in_table`, `no_label`, `not_enum` and `empty` were all one blank cell | **Fixed**: `record_label_state`, `extracted_label_state` appended; the invented `99` asserted in the file |
| 3.2 | 3 | The tag write checked its evaluation with `assert`, gone under `-O` | **Fixed**: `NotFoundError` |
| 3.3 | 3 | An empty-string label decoded as `no_label`, where the prompt printed `[no de label]` only for an absent language | **Fixed**: `no_label` means the language is absent; an empty label is `labelled` with `""`, and the cell shows nothing under the code, as the model was shown nothing. Unit-tested |
| 3.4 | 3 | Each tag write read and parsed every snapshot of the evaluation to decode one row | **Fixed**: `_codebook(..., feature_id=)` reads that feature's only |
| 3.5 | 3 | `decode` scanned the code table per value | **Fixed**: `by_code` keys each snapshot once; `decode` takes the mapping |
| 3.6 | 3 | `_value_meaning`'s docstring names a detail row that did not exist yet | **Kept**: step 4 adds it, in the next commit |
| 3.7 | 3 | `_value_meaning` re-checks that a `labelled` value has a label; a `no_label` without a language reads "no  label" | **Kept**: the check is what makes an empty label render nothing (3.3); the service always sets the language |
| 3.8 | 3 | The API's label states were plain `str` | **Fixed**: typed `LabelState`, so OpenAPI lists the five values |
| 4.1 | 4 | `reload()` re-reads the detail and redraws the table on every poll tick, resetting the narrative's scroll | **Kept**: polling runs only while a run or scoring pass is in flight; a diffing redraw is a larger change than this slice. Opening a row no longer reloads at all (4.3) |
| 4.2 | 4 | A detail that vanished closed without a word, where §4.2 said it would say so | **Fixed**: `DETAIL_GONE` notice; UI-tested by deleting the row under an open page |
| 4.3 | 4 | Opening a row ran the whole `reload()` (evaluations, statuses, list) | **Fixed**: `_toggle` reads the detail and redraws; nothing else |
| 4.4 | 4 | The rule said "within tolerance" without the tolerance | **Fixed**: `± N min` / `N decimals` beside the shared rule words; tested directly, as the fixture has no tolerance feature |
| 4.5 | 4 | The toggle's name said "Show" while open; `aria-controls` named a missing element while closed | **Fixed**: "Hide" while open; `aria-controls` only while the row exists; tests find rows by `data-mismatch` |
| 4.6 | 4 | The feature key's ellipsis could never apply | **Fixed**: `white-space:nowrap;min-width:0` |
| 4.7 | 4 | `MismatchDetailView.record_id` and `.unfall_uid` were read by nothing | **Fixed**: `record_id` removed; the UID is now shown in the narrative's header, where a scrolled-away row still needs its key |
| 4.8 | 4 | `Kind(...)` / `ValueType(...)` re-wrap typed columns | **Kept, and commented**: the backend test failed without them; a row the session holds comes back as written, which may be the plain string |
| 5.S1 | 5 · Standards | Duplicated code: the code-then-label block was written twice (cell and detail) | **Fixed**: `_meaning_label`, one renderer taking the style |
| 5.S2 | 5 · Standards | The label states' words and ink were split across a dict and an if-chain, where CLAUDE.md asks for one rendering table | **Fixed**: `LABEL_STATE_WORDS` maps each state to `(words, ink)` |
| 5.S3 | 5 · Standards | `_rule_parameter` worded a rule outside the module that exists to word rules once | **Fixed**: `components.matching_rule.rule_parameter` |
| 5.S4 | 5 · Standards | The tag path raised `NotFoundError("evaluation", mismatch_id)` | **Fixed**: `"mismatch"` |
| 5.S5 | 5 · Standards | `span_locate`'s whitespace set was written twice | **Fixed**: the set is derived from the string |
| 5.S6 | 5 · Standards | `detail()` queries in the service rather than the repository | **Kept**: this service already ran its own `select`s (`_runs_for`, `_features_for`); one read with no paging gains nothing from a repository method |
| 5.P1 | 5 · Spec | Closing on filter and page untested | **Fixed** for filter (UI test); paging shares `_close_detail` and the fixture has no second page |
| 5.P2 | 5 · Spec | No UI test for the no-narrative state | **Fixed** |
| 5.P3 | 5 · Spec | Lossy French not tested through the detail | **Kept**: the matching rule is `locate`'s and is unit-tested byte-exactly; the backend's record 0 is the lossy narrative, opened and asserted unmarked |
| 5.P4 | 5 · Spec | Scope additions (decimals, UID in the header, `rule_help`, `DETAIL_GONE`, the state columns) | **Kept**: each came out of a step review and is recorded above (3.1, 4.2, 4.4, 4.7) |
| 5.P5 | 5 · Spec | The plan, the amendment and CONTRACTS.md disagreed on which files are frozen; `detail()`'s frozen signature was filed as "not frozen" | **Fixed**: the Status paragraph and §6 corrected, the amendment gains §3 (`detail`) and §4, CONTRACTS.md lists `mismatch_service` under amended files |
| 5.P6 | 5 · Spec | The plan was stale on the CSV columns, on rule 3's test, and on the rule functions' signatures; data-handling.md omitted the label states; CONTRACTS.md omitted the API test | **Fixed**, each where it was stale |

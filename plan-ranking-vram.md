# plan-ranking-vram.md — the one tie-breaker the ranking never reported

**Status.** Written 2026-09-26 against `2eaa89b`, out of an audit of every
performance metric the documents say is on a screen against the code that
renders it. Fifteen of sixteen were there; the audit and its two small fixes
are `contracts/amendments/fix-ranking-token-format.md`. **This is the
sixteenth.** Nothing here is built yet. Authority as always: `mvp-spec.md` on
*what*, `sw-design.md` on *how* (CLAUDE.md). One revision, one amendment,
named in §6.

**Stage 1 done on 2026-09-26** on `fix/ranking-vram`: `SD41` in `sw-design.md`
with §10's `run` block and §16.5's sentence, the note on §3b of
`design/results/README.md`, `contracts/amendments/fix-ranking-vram.md` and this
slice's `CONTRACTS.md` section. No code changed. §10's three questions are
answered as this plan recommends. **Stage 2 done on 2026-09-26**:
`run.model_size_bytes` and revision `9874691cc8eb`, the launch pin, the
renamed read-model and API field, four tests. **Stage 3 done on 2026-09-26**:
the VRAM column, the Model column's `digest · size`, the em dash, the note —
and the design's "must agree with the model sub-line" asserted in the browser.
**Stage 4 done on 2026-09-26** (§5): two real 48-record runs against this
host's Ollama in a throwaway data dir reproduce the pin exactly, and
`docs/performance.md` §6 no longer lists the gap. **All stages done; merged
into `main` as `fe1c0e4`.**

---

## 1. What four documents promise

| Document | Says |
|---|---|
| `mvp-spec.md` §11.5 | "**Latency, VRAM and the macro presence rate are reported, never scored** — the tie-breaker the analyst applies, not one the tool applies" |
| `design/results/README.md` §3b | A **VRAM** column, 78px, "mono size — **must agree with the model sub-line**"; and the Model column is "mono 12px tag over mono 10.5px `--ink3` **"digest · size"**". Fixtures: `15.6 GB`, `12.1 GB`, `8.9 GB` |
| `design/results/README.md` §3d | Rule 4, rendered verbatim under the table: "Latency and VRAM are **reported, never scored**" |
| `sw-design.md` §16.5 | "Three columns on that tab are **reported, never scored** — median latency, prompt tokens and **VRAM**" |
| `plan-phase-4.md` T3 | Build "the *reported-never-scored* group: median latency…, prompt tokens (summed), **VRAM (from the evaluation's `selected_models_json`, which is why the design insists it "must agree with the model sub-line")**" |

## 2. What the code does

```python
# ra2/services/ranking_service.py:140
vram_bytes=0,
```

No VRAM column is rendered. `RankingRow.vram_bytes` is `0` for every row, and
`RankingRowResponse` ships that `0` to API clients as if it were a
measurement. **The Model column's sub-line lost its size too** — it renders
`row.digest[:8]` and nothing else — which is the same omission seen from the
other side: the read model has no size to render in either cell.

No test touches `vram_bytes`. No deviation is recorded in `CONTRACTS.md`; the
only acknowledgement anywhere is a bullet under "Known gaps in the
application" in `docs/performance.md` §6. And rule 4 still renders **verbatim**
under a table with no VRAM in it, which is the part that makes this worth a
plan rather than a column: the tab promises the reader a number and then does
not show it.

### 2.1 Why it was never built

**The source `plan-phase-4.md` T3 named does not hold a size.**
`evaluation.selected_models_json` is a JSON array of model **tags**:

```python
# ra2/services/evaluation_service.py:1224
return tuple(str(tag) for tag in json.loads(evaluation.selected_models_json))
```

`run` has no size column either. So T3's instruction was unbuildable as
written, and `0` is what that looked like from inside the wave. This is the
same class as `P2-D4` — a plan naming a source that turned out not to exist —
except that here nobody recorded it, so the placeholder shipped with the
promise still printed above it.

### 2.2 What is already in place

| Where | What |
|---|---|
| `ra2/domain/llm.py` `ModelInfo.size_bytes` | The catalogue's size for a tag, already read on every Models-card load |
| `ra2/services/readmodels.py` `ModelChoiceView.size_bytes` | Frozen, populated, and already rendered on the Evaluation screen as `digest 8fa1c3d0 · 5.2 GB` |
| `ra2/services/evaluation_service.py` `_new_run(…, model: ModelChoiceView, …)` | **Already holds the number at launch.** It pins nine other provenance fields off the same objects |
| `ra2/ui/views/evaluation_view.py` `_gigabytes` | `8_500_000_000 -> "8.5 GB"`, private to that view |
| `ra2/services/evaluation_service.py` `_exceeds_vram`, `fits_vram` | Already decide *selectability* from this same number against `GpuInfo.total_vram_bytes` |

So the missing piece is one pinned column, not a measurement.

---

## 3. The decisions

**D1. The number is pinned on the run at launch, not read at ranking time.**
`run.model_size_bytes`, nullable, no backfill. Four reasons, any one of which
is sufficient:

1. **A ranking must be reproducible.** §16.5's rule is that every number on the
   tab comes from rows already stored — "if the two disagree, Ranking is wrong
   by construction". A figure fetched live changes under a stored ranking.
2. **`ollama pull` moves it.** The run records the digest precisely so a
   re-pull is visible; reading today's catalogue would silently attach new
   weights' size to old weights' scores.
3. **The endpoint is not there.** Results are read long after a run, with
   Ollama stopped. A read model that needs the network has a failure mode the
   tab has never had.
4. **No network call from a read path.** `plan-phase-3.md` C3 — "re-checked on
   view load and when refresh is pressed, **never on a timer**" — and the
   Results tabs poll while scoring runs.

**D2. The value is the catalogue's `size_bytes`, as the Models card showed it
at launch.** This makes the design's "must agree with the model sub-line" true
**by construction** rather than by discipline: one field, rendered twice, from
the same `ModelChoiceView` the tick was drawn from. It is also the number
`fits_vram` already uses to disable a model, so the tab that reports the
tie-breaker and the card that enforces it stop being able to disagree.

**D3. The column is labelled `VRAM` and carries a footnote saying what the
number is.** The figure is the model's size as the endpoint reports it. A
loaded model's footprint is *not* that number: `docs/performance.md` §4.2
measured `qwen3:8b` at 5.2 GB on disk and 5.6 GB loaded, `gemma4:12b` at 7.6
and 8.1 — and `qwen3.5:2b` at 2.7 and **2.4**, so the gap has no single sign.
§5.4 measured a further 1.9 GB for `qwen3:8b` at four slots, one KV cache per
parallel call.

Keeping the spec's word and stating the caveat beats both alternatives:
renaming the column `Size` puts a second vocabulary on one datum (the
Models card, `fits_vram` and `RA2_GPU_VRAM_GB` all say VRAM about it), and
printing the loaded footprint is D4. The footnote goes where `PARALLEL_NOTE`
goes, under the table, and only says what the table cannot:

> VRAM: the model's size as the endpoint reported it at launch. A loaded model
> needs somewhat more, and one more KV cache per parallel call.

**D4. The loaded footprint is deliberately not what this reports.** `/api/ps`
gives `size` and `size_vram` per loaded model, which is the honest VRAM number
— and it is rejected here: it exists only while the model is loaded (so it is
unreadable for a `queued` run and gone after a finished one), it needs a
second call per run inside the worker's hot path, `ModelCatalog.loaded()` is a
**frozen protocol** returning tags only, it is `0` on a CPU-bound host where
the column is most interesting, and it would disagree with the Models card
sub-line — breaking the one rule the design states about this column. §9 keeps
it as a later refinement with its own amendment.

**D5. A run from before the revision renders `—`, never `0`.** `SuppressedCell`'s
rule one layer down: never print a number that says something the datum does
not. `0` is how this defect shipped, and a nullable column with an em dash is
the fix for exactly that. Both cells — the VRAM column and the Model
sub-line's `digest · size` — degrade to `digest` alone and `—`.

**D6. `RankingRow.vram_bytes` becomes `model_size_bytes: int | None`.** A
rename, not an addition, and **not additive on the wire**: the field name has
to say which datum it carries, because D3 keeps the *screen's* word (the
analyst's vocabulary) and the schema keeps the *datum's*. Nothing is lost —
the value it replaces was a constant `0` no client could read a meaning into.
`tests/api/openapi_snapshot.json` is regenerated; the amendment names both
frozen files.

**D7. It does not join `ProvenanceView`.** mvp-spec.md §19.8's list is the
reproducibility contract — the inputs that decide an answer. A model's size
decides no answer; it is a cost fact, and the ranking is where costs are
compared. `llm_parallel_calls` rides on provenance because it is a pinned
*input* (`SD38`); this is not one.

---

## 4. The design, in detail

### 4.1 The two cells

| Cell | Today | After |
|---|---|---|
| Model column sub-line | `4b81e2d5` | `4b81e2d5 · 15.6 GB` (design §3b), `4b81e2d5` when unknown |
| VRAM column, 78px, after Prompt tokens | absent | `15.6 GB`, or `—` |

The column goes **after** Prompt tokens and before Verdict, which is the
design's order; the table's `min-width` grows by 78px to 978px. `format_gigabytes`
moves from `evaluation_view._gigabytes` into `primitives`, exactly as
`format_tokens` moved there today and `format_duration_ms` became public
before it — two callers now, so one rule.

### 4.2 The test the design's own rule asks for

"Must agree with the model sub-line" is a sentence about two cells, so it is an
assertion about two cells, in the browser:

```python
# tests/e2e/test_results_j11_to_j13.py
size = row.locator('[data-testid="model-size"]').inner_text()
assert row.locator('[data-testid="vram"]').inner_text() == size
```

It cannot fail while both read one field, which is the point of D2: the rule
becomes structural and the test is what says so.

### 4.3 Rule 4 stays verbatim

`COMPUTATION_RULES[3]` already names latency and VRAM. It has been printing a
promise the table did not keep; it is unchanged, and the table keeps it.
`docs/performance.md` §6 loses its VRAM bullet in the same stage.

---

## 5. The stages

Each is a commit; each leaves `just lint` and `just test` green.

### Stage 1 — the contract, before the code

- `sw-design.md`: **`SD41`** — *the model's size is pinned on the run and the
  ranking reports it as VRAM* — plus the §10 schema block's `run` comment and
  the §16.5 sentence that currently lists a column that does not exist.
- `design/results/README.md` §3b: a footnote-marker on the VRAM row naming
  what the number is (D3). The drawn widths and copy are otherwise untouched.
- `contracts/amendments/fix-ranking-vram.md`, and this plan's `CONTRACTS.md`
  section.

**Exit:** no code changed; the documents agree with each other and with what
Stage 2 will build.

### Stage 2 — the column, the pin and the read model

- Revision `…_pin_the_model_size_on_the_run.py`: `run.model_size_bytes`,
  `Integer`, **nullable**, no backfill — unlike `llm_parallel_calls`'s `1`
  there is no fact to backfill, and D5 renders the absence. Registered in
  `tests/test_p5_contract.py`'s `POST_PHASE_5_REVISIONS`. **One author, this
  branch's implementer**; no parallel head.
- `_new_run` pins `model.size_bytes`. One line beside `model_digest`.
- `RankingRow.vram_bytes` → `model_size_bytes: int | None` (D6);
  `ranking_service` reads `run.model_size_bytes` instead of writing `0`;
  `RankingRowResponse` and the OpenAPI snapshot follow.

**Exit:** a launched run carries its size; `ranking_tab`'s read model carries
it per row; a run created before the revision carries `None` through every
layer without a `0` appearing anywhere. Backend tests per §7.

### Stage 3 — the two cells

- `primitives.format_gigabytes`; `evaluation_view._gigabytes` deleted.
- `ranking_tab`: the VRAM column (78px, `data-testid="vram"`), the sub-line's
  `· 15.6 GB`, the `—` for an unknown, the footnote (D3) beside
  `PARALLEL_NOTE`'s slot.

**Exit:** UI tests per §7, plus the E2E agreement assertion of §4.2. The
Ranking tab prints no promise it does not keep.

### Stage 4 — seen working, and the documents closed

- `just reset-seed yes --records 50` in a **throwaway `RA2_DATA_DIR`**, two
  models, one evaluation, scored — then `just dev-agent` and read the tab.
  Never the real data dir (Do-NOT #13).
- One run's row hand-nulled in that throwaway database, to see `—` rather than
  to trust it.
- `docs/performance.md`: the VRAM bullet leaves §6, §4.2 gains the
  cross-reference the footnote points at, and the header's revision note takes
  the date. **No measured number changes.**

**Exit:** the audit table in `fix-ranking-token-format.md` reads sixteen of
sixteen.

**Measured, 2026-09-26.** `qwen3.5:2b` + `llama3.2:3b` over the 48-record seed
in a throwaway `RA2_DATA_DIR`, launched and scored through the real services
against this host's Ollama, both runs `done` at 48/48:

| Model | Digest | Macro F1 | Median latency | Pinned size | Catalogue | Renders |
|---|---|---|---|---|---|---|
| `qwen3.5:2b` | `324d162b` | 0.737 | 2 287 ms | 2 741 192 820 | 2 741 192 820 | `2.7 GB` |
| `llama3.2:3b` | `a80c4f17` | 0.807 | 2 164 ms | 2 019 393 189 | 2 019 393 189 | `2.0 GB` |

Both share rank 1 — six scored features on 48 records do not separate them,
which is the verdict the tab composes. The pin equals the catalogue's
`size_bytes` for both, so the Models card and the ranking cannot disagree.
With the column nulled on both runs, as a pre-revision run carries it, the
VRAM cell reads `—` and the sub-line falls back to `324d162b` / `a80c4f17`
alone. Nothing but ids, counts, scores and sizes was printed (Do-NOT #13).

---

## 6. Frozen files, and the amendment

One amendment file, `contracts/amendments/fix-ranking-vram.md`, applied in the
stage whose code needs it.

| File | Change | Stage |
|---|---|---|
| `ra2/persistence/models.py` | + `Run.model_size_bytes`, nullable | 2 |
| `ra2/services/readmodels.py` | `RankingRow.vram_bytes` → `model_size_bytes: int \| None` | 2 |
| `ra2/api/schemas.py` | The same on `RankingRowResponse`; snapshot regenerated (**not additive** — D6) | 2 |
| `ra2/ui/components/primitives.py` *(addition)* | + `format_gigabytes` | 3 |
| `ra2/ui/views/results/ranking_tab.py` | The VRAM column, the sub-line's size, the footnote | 3 |
| `ra2/ui/views/evaluation_view.py` | `_gigabytes` deleted, imports the shared one. No rendered change | 3 |

Not frozen, and changed: `ra2/services/evaluation_service.py` (`_new_run`),
`ra2/services/ranking_service.py`, `ra2/api/v1/ranking.py`, `sw-design.md`,
`design/results/README.md`, `docs/performance.md`, `tests/test_p5_contract.py`.

---

## 7. Tests

| Test | Layer | What it pins |
|---|---|---|
| `test_launch_pins_each_models_size` | backend | A launched run carries the catalogue's `size_bytes` for its own tag, per model, from the same view the tick was drawn from |
| `test_ranking_reports_the_pinned_size` | backend | `RankingRow.model_size_bytes` is the run's, not the catalogue's, and **takes no part in `rank`** — change it and the order must not move (the shape every reported-never-scored figure is asserted in) |
| `test_ranking_reports_no_size_for_a_run_that_has_none` | backend | `None`, never `0`, end to end through the API |
| `test_the_ranking_vram_column_agrees_with_the_model_sub_line` | ui | D2 made structural: one field, two cells, same string |
| `test_a_run_without_a_pinned_size_renders_an_em_dash` | ui | D5, in both cells |
| `test_j13_the_ranking_vram_agrees_with_the_model_sub_line` | e2e | §4.2 — the design's own rule, in the browser, at the drawn width |
| `tests/api/openapi_snapshot.json` | api | The rename is deliberate and reviewed, not a drift |

---

## 8. Risks

| Risk | Why it is small | Cover |
|---|---|---|
| The number understates the loaded footprint | It is the number `fits_vram` already gates selection on, so the tab and the card cannot disagree | D3's footnote; `docs/performance.md` §4.2 |
| Ollama reports a size the analyst does not recognise | It is the size the Models card showed when they ticked the box, by construction | D2 |
| A rename breaks an API client | The field carried a constant `0`; the snapshot test makes the change reviewed | D6 |
| Two more numbers per row on a 900px table | The design drew the width; the well is `overflow:auto` | §4.1 |

---

## 9. Deliberately not in this plan

- **The loaded footprint from `/api/ps`** (D4). It is the truer number and it
  needs a frozen-protocol amendment, a call inside the worker's path and an
  answer for the CPU-bound host. Worth its own slice, after this one makes the
  column exist.
- **Sorting the ranking by VRAM.** The tab is read-only by design; §3b draws no
  sort control on it.
- **VRAM in the Ollama settings dialog.** Still out, still `P3-D19`.
- **Anything about `fits_vram`'s own approximation.** `sw-design.md` §15.6
  owns that, and this plan does not reopen it.

---

## 10. For the lead, before Stage 1

| # | Question | This plan's answer |
|---|---|---|
| Q1 | Column labelled `VRAM` with a footnote (D3), or renamed `Size`? | **`VRAM` with the footnote.** The spec's word, and the same word the card and the setting already use for this datum. Renaming is defensible and cheaper to read; it costs a second vocabulary |
| Q2 | Rename the wire field (D6), or keep `vram_bytes` holding a size? | **Rename.** A name that says the wrong datum is how `vram_bytes=0` survived a phase |
| Q3 | Nullable column, or NOT NULL backfilled `0`? | **Nullable.** `0` is the defect being fixed |

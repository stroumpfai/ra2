# Handoff: RA2 — Prompts & Evaluation (+ navigation change)

## Overview
Third handoff package for RA2 ("Accident report analysis"). It covers two views plus one change to the
already-implemented app shell:

0. **Left navigation — one new entry** ("Prompts"), to be added to every view
1. **Prompts** — the prompt template: the wording around the feature descriptions, versioned
2. **Evaluation** — pick corpus + feature set + prompt + models, launch runs, watch them, list them

**Already implemented, not respecified here:** the app shell (header + left navigation), Import,
Census, Codelists, Features. Those were handed off in the first two packages; reuse their shell,
tokens, table and pagination patterns. Where this document says "same as Census/Features", build on
what exists rather than re-deriving it.

Pipeline position: Data (Import → Census → Codelists) → **Configure (Features → Prompts)** →
**Run (Evaluation)** → Review (Results, Mismatches). Results and Mismatches come later.

## About the Design Files
The `.dc.html` files are **design references authored in HTML** — prototypes showing layout, hierarchy,
copy and behaviour. They are **not production code to copy**. Recreate them in the existing codebase
with its components, routing, state and styling.

- Styling is inline, plus one `<style>` block per file with the CSS custom properties and small utility
  classes (`.card .lbl .th .td .navitem .sl .sel .btn .pill .bar .tick .row .rname .rsub .ibp .stamp
  .mono`). Nearly all have an Import/Census/Features equivalent already built.
- The mocks are static: dropdowns, filters, pagination and checkboxes render in a chosen state.
- Each board has a fixed `height` on its root (Prompts 1110px, Evaluation 1230px) so the artboard is
  fully visible on the design canvas. **Do not port that** — in the app the shell fills the viewport and
  the content column scrolls.
- `WIREFRAME` stamps are artboard annotations, not UI. Drop them.

## Fidelity
**High-fidelity layout, medium-fidelity styling** — same contract as the earlier packages. Structure,
spacing, exact column widths, copy and affordances are deliberate; the visual skin comes from the
implemented shell's tokens. Column widths given below are load-bearing — several were tuned against
real content and clip when reduced.

---

## 0 · Navigation change (affects every view)

One entry is added to the sidebar, in the **Configure** group, immediately after *Features*:

| Group | Item | Route | Icon |
|---|---|---|---|
| Data | Import | /import | download |
| Data | Census | /census | bar-chart |
| Data | Codelists | /codelists | list |
| Configure | Features | /features | sliders |
| Configure | **Prompts** | **/prompts** | **align-left** (4 left-aligned lines of decreasing length) |
| Run | Evaluation | /evaluation | play-circle |
| Review | Results | /results | table |
| Review | Mismatches | /mismatches | alert-triangle |

The label is **"Prompts"** (not "Prompt templates" — that string was rejected). Markup, states and
metrics are exactly the existing `.navitem`: `display:flex; align-items:center; gap:9px;
padding:6px 14px`, 12.5px, `--ink2`, 2px transparent left border; hover `--ink` on `--rule2`; active
`--ink` on `--accent-soft` with `border-left-color:--accent` and `font-weight:500`. Icon is inline SVG
on a 24×24 viewBox at 15×15, `stroke-width:1.8`, `stroke-linecap/linejoin:round`, paths
`M4 5h16 · M4 10h10 · M4 15h13 · M4 20h7`.

Nothing else in the shell changes. All twelve existing boards in the design project were updated, so
any of them can be used as the reference.

---

## 1 · Prompts
File: `PromptTemplate - A source.dc.html`
Title "Prompt templates" / "The wording around your feature descriptions. Versioned, because changing
it changes every answer."

**Purpose** — the prompt template is everything the model is told *except* the feature descriptions: the
role framing, the rules about not guessing, the output format, and where the narrative is placed. It is
versioned independently of feature sets because changing a single word changes every answer while no
feature has changed. Runs cite a template version and its fingerprint, so old versions can never be
edited in place.

**Layout** — master/detail, identical in structure to Codelists and Features:
```
main
├── toolbar strip      flex:none, padding 11px 28px, surface, border-bottom
└── split              flex:1, min-height:0, display:flex   (NEVER wraps)
    ├── version list   flex:0 1 452px; min-width:300px; border-right; surface
    │   ├── header     46px
    │   ├── list       flex:1; min-height:0; max-height:530px; overflow:auto  (10 rows)
    │   ├── pagination flex:none, padding 9px 16px, border-top
    │   ├── slots row  flex:none, padding 9px 16px, border-top --rule2
    │   └── slot table flex:none, padding 10px 16px, border-top --rule2
    └── editor         flex:1 1 520px; min-width:360px; padding 20px 28px; overflow:auto
```

### Toolbar
**Right group only** — `display:flex; gap:10px; margin-left:auto; flex:none`: WIREFRAME stamp,
a secondary **"Preview with record 1"** button, and the primary **"Save as v5"** button. There is
deliberately **no left chip group** here: a template/language selector was designed and then removed,
because the version being edited is chosen in the list and the prompt language belongs to the
evaluation, not the template.

### Version list (master)
Header: `.lbl` "4 versions" (truncating, `min-width:0`) + secondary **"New version"** button
(12px plus icon).

Rows are the standard `.row` (`padding:9px 16px`, `border-bottom:1px solid --rule2`,
`display:flex; justify-content:space-between; align-items:center; gap:10px`; hover `--rule2`;
53px tall). Left: `.rname` version + `.rsub` (mono 10.5px, `--ink3`) "created · citation count".
Right marker:
- **active version** — selected row treatment (`background:--accent-soft`,
  `border-left:2px solid --accent`, `padding-left:14px`, name weight 600) + a `.pill` "ACTIVE"
  (`--ok-soft` / `--ok`). Fixture: v4, 2026‑09‑04 14:22, cited by 3 runs.
- **cited but not active** — mono 11px `--ink3` "locked". Fixtures: v3 (cited by 6 runs),
  v2 (cited by 2 runs).
- **never run** — a 22×22 `.ibp` delete icon button in `--danger`. Fixture: v1, never run.

The well is capped at **10 rows (530px)** and scrolls beyond; below it the standard pagination row
(`.lbl` "Rows per page" + `10 ▾` select; mono 11px "1–4 of 4" + two 24×24 arrow buttons, both
disabled at `oklch(0.80 0.006 260)` for a 4-item list).

Two reference strips close the column:
- **"Slots available"** + a mono count (3).
- The slot table itself — one row per slot, mono 11.5px name + 11px `--ink3` description:
  `{{feature_block}}` "13 features" · `{{narrative}}` "record text" · `{{language}}` "de · unused".

### Editor (detail)
Header: `.lbl` "Editing" + `h2` 16px weight 600 "Template v4"; right block
(`flex:1 1 240px; min-width:0; text-align:right`) `.lbl` "Template fingerprint", mono 12px truncated
hash `t4e1980cab7…`, 11px `--ink3` "Every run stores this alongside the model digest."

**Source card** — 42px tinted header (`oklch(0.988 0.003 260)`, `border-bottom:1px solid --rule2`):
`.lbl` "Source" + mono 10.5px `--ink3` "plain text · slots in {{ }}". Body is mono 12px,
`line-height:1.75`, `white-space:pre-wrap`, with each slot token highlighted inline
(`background:--accent-soft; padding:1px 4px; border-radius:2px`). Footer (`--warn-soft`,
`oklch(0.40 0.10 72)`, 14px icon): "Saving creates v5. v4 stays as it is — the 3 runs citing it must
keep resolving to the exact text they used."

Template text (fixture, verbatim):
```
You extract structured facts from Swiss accident reports.

Read the narrative below. For each feature, emit the value the
narrative supports — nothing inferred, nothing assumed.
If the narrative does not state a value, leave it empty.
Never guess to fill a field.

{{feature_block}}

Answer as JSON only, one key per feature, no prose.

--- narrative ---
{{narrative}}
```

**Resolved card** — same 42px header: `.lbl` "Resolved — record 1, all 13 features" + mono 10.5px
`--ink3` token count ("1 842 tokens"). Body mono 11.5px `--ink2`, `white-space:pre-wrap`,
**`max-height:210px; overflow:auto`** (intentional — a resolved prompt is long). It shows the template
with every slot expanded: the feature block rendered as `name — type` lines plus codelist labels, and
the real narrative text.

---

## 2 · Evaluation
File: `Evaluation.dc.html`
Title "Evaluation" / "One corpus and one feature set, run across several models."

**Purpose** — an evaluation pins one corpus, one frozen feature set and one prompt template, then runs
them across several local models under fixed decoding settings. Everything needed to reproduce a run is
recorded; the point of the view is that a re-run is a *check*, not a new sample.

**Layout**
```
main
├── toolbar strip   flex:none, padding 11px 28px, wrap, surface, border-bottom
└── split           flex:1, min-height:0, display:flex   (NEVER wraps)
    ├── setup       flex:0 1 430px; min-width:320px; align-self:flex-start;
    │               border-right; padding 16px 20px 20px; gap:14px; overflow:hidden
    └── progress    flex:1 1 520px; min-width:360px; padding 16px 28px 20px; gap:12px; overflow:auto
```
Two constraints matter and were both regressions at some point:
- The setup column is **`align-self:flex-start`** — it sizes to its content. Without it, its
  `margin-top:auto` launch row is pushed to the bottom of a stretched column, leaving a ~530px gap.
- The split must never wrap; both columns shrink to their min-widths instead.

### Toolbar
Left group (`flex-wrap:wrap; min-width:0`): mono 11px `--ink2` "Weather & conditions · v2 — only the
model varies". Right group (`margin-left:auto; flex:none`): WIREFRAME stamp + secondary "Save draft".
Use `margin-left:auto` on the group, **not** a `flex:1` spacer — the spacer breaks right alignment when
the row wraps.

### Setup column — six numbered steps
Each step is `.lbl` "N · Title" + its control(s) + an optional 11.5px explanatory line.
`.sel` is the full-width select used here: `display:flex; justify-content:space-between;
border:1px solid --rule; radius 3px; padding:7px 10px; surface; mono 11.5px`, with a 9px `▾` caret.

1. **Corpus** — `.sel` "corpus 2026‑09‑02 · v1 · 4 978 records".
2. **Feature set** — `.sel` "set · Weather & conditions v2" + a `--warn` note: "Freezes when the first
   run executes. After that, editing is blocked — clone into a new evaluation instead."
3. **Prompt** — `.sel` "template · v4 *active*" + an `--ink2` note: "The wording around the feature
   descriptions. Travels in the run's fingerprint." (Deliberately **no link** to the Prompts view.)
4. **Models** — a `.card` holding a scroll well **capped at 4 visible rows (`max-height:196px`,
   `overflow-y:auto`)** over a footer strip. Each row: a 13×13 `.tick` checkbox (checked = `--ink` fill),
   then mono 12px model tag over mono 10.5px `--ink3` "digest … · size". A model that cannot fit VRAM is
   `opacity:.55` with its size line in `--warn` ("42.5 GB — exceeds 24 GB VRAM").
   **Since SD40, a third line** under the size line, mono 10.5px, says what this host has measured about
   the model (`just qualify-model`). Four states, each carried as `data-state` on the line:
   `qualified` in `--ink3` "seed F1 0.895 · 1.75 s/rec · entities 0% · ~1 h 27 m", the duration being this evaluation's scope at the
   rate the launch would run, plus
   " · parallel ×4" when the launch would honour the map, with a tooltip "seed-sized narratives; real ones
   are longer"; `stale-digest` in `--warn` "measured on digest 500a1f06 — re-qualify";
   `server-sensitive` in `--warn`, the qualified line plus " · changes when Ollama runs >1 slot";
   `unmeasured` in `--ink3` "not measured on this host". "Not measured" never disables the tick. The
   duration is left out before an evaluation exists, because only an evaluation has a scope. **No "recommended"
   badge** — the seed can't separate the leaders (`docs/choosing-models.md` §3). The row grows from 49px
   to ~65px (64.8px measured in Chromium), so the well that shows **4 visible rows** grows from 196px
   to **260px**; the rule is the row
   count, and E2E measures the rendered row rather than trusting the arithmetic. Footer: mono 10.5px
   `--ink3` "6 available · 3 selected" (truncating) + a 24×24 gear icon button on the right opening
   **Ollama connection settings**. Below the card, mono 10.5px `--ink3`
   "endpoint http://127.0.0.1:11434/v1 · reachable".
   Fixtures: llama3.1:8b-instruct-q8_0 (8fa1c3d0, 8.5 GB, selected) · qwen2.5:14b-instruct-q6_K
   (c17b904e, 12.1 GB, selected) · mistral-nemo:12b-instruct-2407-q8_0 (5d2e71ab, 13.0 GB, selected) ·
   llama3.3:70b-instruct-q4_K_M (over VRAM, disabled) · gemma2:27b-instruct-q5_K_M (9b3fd402, 19.2 GB) ·
   phi4:14b-q8_0 (2ac8e611, 15.4 GB).
5. **Determinism** — two fields side by side, each with its **label above the field** (`.lbl` in
   `--ink3`, `margin-bottom:4px`) so input and label can't be confused: **Temperature** shows `0.0`
   with a `▾` caret (fixed choice), **Seed** shows `42` with a mono 10px `edit` hint (typed). Note:
   "Temperature 0.0 takes the most likely token every time; the seed fixes what remains random. Same
   inputs, same output — a re-run is a check, not a new sample."
6. **Size** — two `.sel` radio-style options: "Evaluation · all 4 978" (selected: `border-color:--ink`,
   `●`) and "Dev · 40 records" (`--ink3`, `○`). Note: "Below 200 records a run is marked *dev* and every
   view carries 'smoke test, not a result'."

Launch row — `margin-top:auto; display:flex; gap:8px`: primary **"Launch 3 runs"** (`flex:1`, centred;
the count follows the model selection) + secondary **"Preview prompt"**. *Preview prompt* renders exactly
what would be sent for the first record and makes **no model call** — it replaced an earlier
"Dry run 5" button whose record count was arbitrary and unexplained.

### Progress column
Header row: `.lbl` "In progress" + mono 11px `--ink3` "in-process asyncio worker · restart-safe ·
resumes from last committed extraction". `.lbl` is `white-space:nowrap` with a 14px gap to its sibling.

**Per-model progress card** (`.card`, `padding:14px`, `gap:14px`) — one block per selected model:
mono 12.5px model tag + a right-aligned mono 11.5px status ("4 978 / 4 978 · done · 1 h 12 m",
"3 106 / 4 978 · running · ETA 38 m", "queued"), a `.bar` (6px, `--rule2` track, `--ink3` fill) at the
completion percentage, and for active/finished runs a mono 10.5px `--ink3` metrics line
("parse failures 14 (0.3 %) · median latency 812 ms · 2.1 M prompt tok" /
"parse failures 6 · retries 11 (bounded, counted) · median latency 1 340 ms"). A queued model is
`--ink2`/`--ink3` with a 0 % bar and no metrics.

**Runs table** (`.card`, `flex:none`, `overflow:hidden`) — 42px tinted header: `.lbl`
"Runs in this evaluation" (`min-width:0`, ellipsis) + mono 10.5px `--ink3` "14 · 2 dev · 1 failed".
Table is `table-layout:fixed; width:100%; min-width:508px` in an `overflow:auto` well, so it scrolls
horizontally rather than collapsing a column below the design width:

| Column | Width | Content |
|---|---|---|
| Run | 74px | run id, mono 11.5px, **links to Results** |
| Model | 132px | short model tag, mono, `--ink2` (ellipsises) |
| Records | 66px, right | mono count, `—` when queued |
| Start time | 152px | mono 11.5px `--ink3`, format **`dd.mm.yy - hh:mm:ss`** on one line |
| Status | 84px | `done` / `running` / `queued` (`--ink3`); `DEV` in `--warn`; `FAILED` in `--danger` |

Row states: dev-sized runs get `background:--warn-soft`; failed runs get `background:--danger-soft`
with a mono 10.5px `FAILED` marker and a muted "log" action instead of "results".
Paginated at **10 rows** with the standard pagination row ("Rows per page 10 ▾", "1–10 of 14",
24×24 arrows). 14 fixtures across r‑0403…r‑0414.

**Reproducibility card** — `.lbl` "Stored on every run — enough to reproduce it" + a mono 11px `--ink2`
list: "model + digest · prompt template v4 · temperature 0.0 · seed 42 · cfg 4f9a2c1e + per-feature
fingerprints · corpus 2026‑09‑02 v1 · host win11‑x64 · gpu RTX 4090 24 GB · endpoint 127.0.0.1:11434",
then a 11.5px `--ink2` explainer: "The prompt template is the wording around your feature descriptions
— the instructions, the output format, where the narrative is placed. It is versioned separately because
changing it changes every answer without any feature changing."

---

## Interactions & Behavior

**Prompts**
- Selecting a version loads it into the editor. The **active** version is the one new evaluations
  default to.
- Editing is **copy-on-write**: saving never mutates a version that any run cites — it creates the next
  version ("Save as v5") and leaves the old text byte-identical. Only a version with zero runs can be
  deleted; all others show "locked".
- Slots are a **closed set** (`{{feature_block}}`, `{{narrative}}`, `{{language}}`). Validate on save:
  an unknown slot, or a template missing `{{feature_block}}`/`{{narrative}}`, is an error.
- "Preview with record 1" / the Resolved card expand the template against the current feature set and a
  real record, and report the token count — the practical check before saving.
- Each version carries a **template fingerprint** that is stored on every run alongside the model digest.

**Evaluation**
- Steps 1–3 pin the inputs; step 4 selects models (multi-select, VRAM-infeasible models disabled);
  steps 5–6 set decoding and size. The Launch button's label counts the selected models.
- The gear button in the Models footer opens **Ollama connection settings** (endpoint, timeouts,
  refresh model list). The endpoint's reachability is shown under the card.
- **Launch** enqueues one run per selected model against the same pinned inputs. The worker is
  in-process and restart-safe: it resumes from the last committed extraction rather than restarting.
- Runs are immutable once started. A dev-sized run (< 200 records) is marked `dev` and every downstream
  view must label it "smoke test, not a result".
- The runs table is the history for this evaluation; a run id opens its Results, a failed run opens its
  log.
- Creating an evaluation is what **freezes** the feature set (see the Features package) — after the
  first run, editing the set is blocked and the user must clone.

**Transitions** — none designed. Progress bars and counters update in place; no entrance animation.

**Loading / empty / error** — partially designed here: run failure is a row state plus a log action, and
an unreachable endpoint should read next to the endpoint line rather than as a toast. Empty states
(no versions, no runs yet) are not designed.

**Responsive** — desktop-only. Both splits never wrap; columns shrink to their min-widths. The runs
table scrolls horizontally below the design width. Toolbar rows may wrap with the right group staying
right-aligned.

## State Management

**Prompts**
```
versions: PromptTemplate[]
  { id, version, source, createdAt, activeFlag,
    citedByRunCount, fingerprint, deletable }
selectedVersionId
page, pageSize:10
slots:    { name, description, required }[]   // closed catalogue
preview:  { resolvedText, tokenCount, recordId }
```
Data: list versions; POST a new version (copy-on-write, never PATCH a cited one); DELETE only when
`citedByRunCount === 0`; a resolve/preview endpoint that expands a template against a feature set + record.

**Evaluation**
```
setup: { corpusId, featureSetId, promptTemplateId,
         modelIds: string[], temperature, seed, size:'full'|'dev' }
models: OllamaModel[] { tag, digest, sizeBytes, fitsVram, selected,
                        qualification?: { state:'qualified'|'stale-digest'|'server-sensitive'|'unmeasured',
                          seedF1, msPerRecord, entityFill, estimatedMs?, parallelCalls, measuredDigest } }
connection: { endpoint, reachable }
progress: RunProgress[]
  { runId, modelTag, done, total, state:'queued'|'running'|'done'|'failed',
    etaMs, elapsedMs, parseFailures, retries, medianLatencyMs, promptTokens }
runs: Run[]
  { id, modelTag, digest, records, startedAt, state, dev, failed }
runsPage, runsPageSize:10
provenance: { modelDigest, promptTemplateVersion+fingerprint, temperature, seed,
              featureSetId + perFeatureFingerprints, corpusId, host, gpu, endpoint }
```
Data: model list + reachability from the Ollama endpoint; POST launch (one run per model); a progress
stream or poll; runs list per evaluation. Every run persists the full `provenance` block.

## Design Tokens
Unchanged from the implemented shell — reuse the existing definitions. This package uses
`--ink/--ink2/--ink3`, `--rule/--rule2`, `--bg/--surface`, `--accent/--accent-soft`,
`--ok/--ok-soft`, `--warn/--warn-soft`, `--danger/--danger-soft`, plus two literals already in use:
`oklch(0.988 0.003 260)` (card-header tint) and `oklch(0.80 0.006 260)` (disabled pagination arrow).
Note `Evaluation.dc.html` had to add `--danger/--danger-soft` to its own `:root` — they belong in the
shared token set.

Type, spacing, radius, borders and the no-shadow rule are as implemented. **One lesson worth carrying
into the code:** the runs table was first built on a bespoke miniature scale (9px headers, 10px cells,
5px padding, 20px pager buttons) and read as unfinished. Every table in this product uses the same
scale — `.th` mono 10px uppercase, `.td` 12.5px, 9px×12px padding, ~37px rows, 24×24 pagination
buttons, 42–46px card headers. Do not introduce a second table scale.

Fixed sizes that matter here: setup column basis 430px (min 320); detail/progress basis 520px (min 360);
version list well 530px = 10 × 53px rows; models well 260px = 4 rows (196px before SD40 added the qualification line); resolved-prompt body 210px;
runs table min-width 508px.

## Assets
No images. Icons are inline SVG on a 24×24 viewBox, `fill:none; stroke:currentColor`, stroke-width
1.8–2.2, rendered at 12–15px — Lucide-equivalent (align-left, plus, trash, gear/settings, info, alert,
play-circle). Fonts: IBM Plex Sans + IBM Plex Mono, already loaded. Carets and pagination chevrons are
text glyphs (`▾ ▼ ‹ › ● ○`) — swap for real icons if the codebase has them.

## Files
- `PromptTemplate - A source.dc.html` — Prompts view (also shows the updated navigation)
- `Evaluation.dc.html` — Evaluation view
- `support.js` — design-canvas runtime so the files open locally. **Not application code; port nothing.**

Already implemented, not included: shell + navigation, Import, Census, Codelists, Features.
Still to be designed: Results, Mismatches, the Ollama settings dialog, the Add-feature panel state, and
the Import file-report modal.

## Open questions for the team
1. **Ollama connection settings** — the gear button exists; the dialog (endpoint, timeout, model refresh,
   VRAM reporting) is not designed. **Built to the plan's own design in the meantime** (plan-phase-3.md Q4,
   sw-design.md §15.8), and since extended to five controls: the endpoint field now refuses a non-loopback
   host inline and disables Save, and a "Test connection" button probes the typed endpoint and reports a
   named cause (P3-D19). VRAM reporting is still **not** in the dialog — that judgement needs the GPU probe
   and belongs on the Models card (§15.6). A design round is still wanted; this is what ships until then.
2. **Prompt language** — `{{language}}` is listed as an available slot but marked "unused". Decide
   whether the prompt language belongs to the evaluation (as the Codelists view assumes) or to the
   template.
3. **Template naming** — versions are bare integers (v1…v4) with no title. If templates will ever
   diverge into variants rather than a single lineage, they need names.
4. Empty states for both views, and whether an unreachable endpoint should block Launch outright.
5. Whether "Preview with record 1" (Prompts) and "Preview prompt" (Evaluation) are the same screen —
   they currently share a purpose and differ in label.

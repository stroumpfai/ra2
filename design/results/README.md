# Handoff: RA2 — Results (three tabs)

## Overview
Fourth handoff package for RA2 ("Accident report analysis"). It covers the **Results** view — one
sidebar entry with three tabs:

1. **Goal 1 — Extraction** (`Main.dc.html`) — per feature × model F1 against ground truth
2. **Goal 2 — Presence** (`Presence.dc.html`) — did the narrative actually say it?
3. **Ranking** (`Ranking.dc.html`) — which model to pick, and where the evidence does not separate them

**Already implemented, not respecified here:** the app shell (header + left navigation), Import,
Census, Codelists, Features, Prompts, Evaluation. Reuse their shell, tokens, table and pagination
patterns. Mismatches is a separate sidebar entry and is **not** in this package.

Pipeline position: Data → Configure → Run (Evaluation) → **Review (Results)** → Mismatches.

The three tabs are one route with a tab parameter, not three routes in the sidebar. The sidebar's
"Results" entry stays active on all three.

## About the Design Files
The `.dc.html` files are **design references authored in HTML** — prototypes showing layout, hierarchy,
copy and behaviour. They are **not production code to copy**. Recreate them in the existing codebase.

- Styling is inline, plus one `<style>` block per file with the CSS custom properties and utility
  classes. Nearly all already exist in the codebase from earlier packages.
- The mocks are static: tabs, dropdowns, sorting and pagination render in a chosen state.
- Each board has a fixed `height` on its root (Main 1440px, Presence 1180px, Ranking 1270px) so the
  artboard is fully visible on the design canvas. **Do not port that.**
- `WIREFRAME` stamps are artboard annotations, not UI. Drop them.

## Fidelity
**High-fidelity layout and copy, medium-fidelity styling.** On this view the *copy is the design*: the
suppression notices, the caveat panels and the tie language are the product's honesty guarantees, not
decoration. Reproduce them verbatim unless the team changes the statistics. Column widths are
load-bearing.

⚠ **Palette note:** this tab family defines `--accent: oklch(0.52 0.13 255)` — a **blue** accent — while
Codelists / Features / Evaluation use the neutral `oklch(0.50 0.008 260)`. The divergence is pre-existing
across all three Results boards and is used as a *data* colour here (best-value marks, evidence links,
breakdown panels). Decide deliberately: either adopt the blue accent in the Results family only, or
unify on the neutral and re-pick a data colour. Do not let it drift per component.

---

## Shared chrome (all three tabs)

**Tab strip** — `flex:none; display:flex; align-items:center; gap:10px; padding:11px 28px`, surface,
`border-bottom:1px solid --rule`. The tabs themselves are a `display:flex; gap:22px; align-self:stretch;
align-items:flex-end; margin-bottom:-11px` group so the active underline sits on the strip's own border:
- active: `padding:0 0 9px; border-bottom:2px solid --accent; color:--ink; font-size:12.5px;
  font-weight:500`
- inactive: same box, `border-bottom-color:transparent; color:--ink2`, no underline on hover
(`Presence.dc.html` has these as a `.tab` / `.tab.on` class pair; `Main.dc.html` uses inline styles —
pick one, the class pair is cleaner.)

Right side (`margin-left:auto`): a mono 11px run descriptor — "Corpus 2026‑09‑02 · 4 978 records ·
3 models" — an "Evaluation run" pill (`--ok-soft` / `--ok`), and a `cfg 4f9a2c1e` chip. **Every tab must
carry the corpus + config identity**: a score without its config is not a result. A dev-sized run shows
"DEV · smoke test, not a result" here instead of the "Evaluation run" pill.

**Statistical conventions, applied identically on all three tabs**
- F1 with a **Wilson 95 % interval**, always shown with the point estimate, never alone.
- `n` = labelled cases for that feature, not corpus size. Records whose source column is empty leave
  the denominator entirely (§8.6).
- **Cells below n = 20 are suppressed** — replaced by italic mono `--ink3` text stating the count and
  why, never by a number in grey. The card header states the rule: "cells below n = 20 suppressed".
- **Ties are shown as ties.** A model is marked *best* only if no other model's interval overlaps it;
  otherwise every overlapping model is marked *tied with best*. No strict ordering is implied anywhere.
- Per-language rows carry a standing, unquantifiable caveat (see Goal 1).

**`.mk` marker** (the tie vocabulary, used on Goal 1 and in Ranking's legend): a 7×7 inline-block,
`border-radius:2px`, `margin-right:6px`; filled `background:--accent` = best; `border:1.5px solid
--accent` = statistically tied with best; empty = neither. Legend strip below the table:
"● Best · ○ Statistically tied with best — intervals overlap", right-aligned note "Ties are shown as
ties. No strict order is implied."

---

## Tab 1 · Goal 1 — Extraction
File: `Main.dc.html`. Title "Results" / "Extraction and presence scores for one evaluation."

**Purpose** — for each labelled feature, how often did each model produce the value the record already
holds. This is the only tab with ground truth, and it is the input every other tab is read against.

**Content column** — `flex:1; min-height:0; padding:18px 28px 22px; display:flex;
flex-direction:column; gap:16px`.

### 1a · Per feature × model (the primary table)
`.card` with `display:flex; flex-direction:column; overflow:hidden`. Header (`padding:11px 14px`,
`border-bottom:1px solid --rule`): `.lbl` "Per feature × model" + mono 11px `--ink2`
"F1, Wilson 95% · n = labelled cases"; right side mono 11px `--ink3` "cells below n = 20 suppressed".

The table lives in an `overflow:auto` well with `min-width:738px` so it scrolls horizontally rather
than bleeding past the card at narrow widths.

| Column | Width | Content |
|---|---|---|
| Feature | 246px | name (weight 500) over mono 10.5px `--ink3` source (`Witter0Ausw · enum`, `derived · count_objects · integer`) |
| n | 78px, right | mono labelled-case count; `--danger` when below the n = 20 floor |
| one column per model | flexible | `.val` = `.mk` marker + F1 to 3 decimals; `.ci` = mono 10.5px `--ink3` interval on a second line, `padding-left:13px` to align under the value. A model that is neither best nor tied is `color:--ink2`. |

Fixture rows (n · qwen3:14b · mistral‑small:24b · gemma3:12b, with best/tied marks):
- Weather `Witter0Ausw · enum` — 1 842 · **0.842** .824–.859 · ○0.831 .812–.849 · 0.744 .723–.764
- Light conditions `LichtVerhAusw · enum` — 2 004 · **0.911** .897–.923 · ○0.903 .889–.916 · ○0.898 .883–.911
- Road condition `StrZu0Ausw · enum` — 1 611 · 0.688 .665–.710 · **0.752** .730–.773 · 0.640 .616–.663
- Main cause `HauptUrsaAusw · enum` — 3 902 · **0.594** .578–.609 · ○0.587 .572–.603 · 0.501 .485–.517
- Vehicles involved `derived · count_objects · integer` — 4 978 · **0.939** .932–.946 · 0.921 .913–.929 · 0.884 .875–.893
- Bicycle involved `derived · any_object_matches · boolean` — 4 978 · ○0.963 .957–.968 · **0.967** .962–.972 · ○0.959 .953–.965
- Speed limit `HoechstGeschwKmHFeld · integer` — 4 512 · 0.812 .801–.823 · **0.847** .836–.857 · 0.790 .778–.801
- **Right of way** `VortrittAusw · enum` — **17** (`--danger`), row tinted `oklch(0.985 0.002 260)`,
  all three model cells replaced by one `colspan="3"` italic note: "Insufficient data — 17 labelled
  cases, below the minimum of 20. Column populated in 0.3% of the corpus."

**Expandable breakdown row.** Directly under the selected feature (Weather in the mock) a
`colspan="5"` row tinted `--accent-soft` holds a nested table: one row per model with Precision ·
Recall · F1 · Hit · Wrong (`--warn`) · Missing (`--ink2`). Left of it, `.lbl` "Breakdown · Weather" in
`oklch(0.45 0.08 255)` and the note "Hallucination is *not* computed — it is a review tag on the
mismatch list." Only one breakdown is open at a time.
Weather fixtures: qwen3 .887/.802/**0.842**/1 477/188/177 · mistral .851/.812/**0.831**/1 496/262/84 ·
gemma3 .769/.721/**0.744**/1 328/399/115.

Then the standard **pagination row** (Rows per page `10 ▾`; "1–8 of 13"; 24×24 arrows) and below it,
on a lighter `--rule2` divider, the **tie legend**.

### 1b · Two cards below (a 2-column grid, `gap:16px`)
**"By language · Weather"** (right header: mono 11px `--ink3` model tag) — Language · n · F1 · 95% CI.
German 1 241 / 0.871 / .852–.888 · French 498 / 0.774 / .735–.809 · Italian 88 / 0.750 / .650–.829 ·
"Mixed / undetermined" 15 in `--danger` with a `colspan="2"` "Insufficient data".
Footer (`--warn-soft`, `oklch(0.40 0.10 72)`, alert-triangle icon), **verbatim**: "The upstream encoding
conversion drops characters that are commoner in French than in German. French input may simply be
noisier. **This cannot be quantified** — do not read the gap as a model weakness."

**"Goal 3 — Exploratory"** — header carries mono 10.5px `--danger` "no ground truth · not ranked" and
right-side "7 of 20 attributes". Columns: Attribute · Discovery (weight 500) · Reviewed (`0 / 15` in
`--ink3` when unreviewed, `12 / 15` when done) · Evidence (an accent "15 spans" link).
Fixtures: Phone use mentioned 4.1% · Animal on carriageway 7.8% (12/15 reviewed) · Driver distraction
stated 31.2% · Witness account present 78.4%.
Footer (`--ink3`, info icon), **verbatim**: "A discovery rate is a screening signal, not a score. A
freely hallucinating model wins it — never compare these between models."

---

## Tab 2 · Goal 2 — Presence
File: `Presence.dc.html`.

**Purpose** — a populated record column says nothing about whether the officer *wrote* it in the
narrative. That gap is the finding. This tab reports presence **rate**, the Goal 1 × presence cross-tab,
and flag inconsistency — and deliberately refuses to report presence precision/recall/F1.

**Content column** — `padding:16px 28px 24px; gap:14px`.

### 2a · Scope banner (first element, not dismissible)
`border:1px solid --warn; background:--warn-soft; border-radius:3px; padding:11px 14px`, a mono 10.5px
`--warn` label "GOAL 2 SCOPE" beside 12.5px body text. **Verbatim:** "**There is no gold label for
presence.** A populated record column says nothing about whether the officer wrote it in the narrative —
that gap *is* the finding. Deriving gold presence from Goal 1 correctness would be circular, so this tab
reports presence rate, the Goal 1 × presence cross-tab, and flag inconsistency. `Presence precision /
recall / F1 are deferred` until a human-labelled subset (≈50 records × features) exists."

### 2b · Model selector row
Three `.chip`s (active: `border-color:--ink; color:--ink`) + right-aligned mono 11px `--ink3`
"n = labelled cases · Wilson 95 % · cells under n = 20 suppressed". This tab shows **one model at a
time** — presence is per-flag, so a 3-model grid would not be readable.

### 2c · Presence rate table
Section label above the card (`.lbl`, `margin-bottom:7px`): "Presence rate — share of labelled cases
where the model flags the text as containing the feature".

| Column | Width | Content |
|---|---|---|
| Feature | 200px | mono feature key (`weather_code`, `light_conditions`, …) |
| All · presence rate | flexible | `.val` percentage over `.ci` "[low – high] n N" |
| de / fr / it | flexible ×3 | same pair per language; below n = 20 the cell becomes a single `.ins` chip "insufficient data · n 12" |
| Goal 1 F1 — never shown apart | 230px | `.val` F1 over `.ci` "P 0.86 · R 0.77" |

The last column's header text is part of the design: **presence numbers are never published without the
Goal 1 numbers beside them**, because a weak extractor manufactures false "missing" flags.
Fixtures: weather_code 61.4 % / F1 0.81 · light_conditions 72.8 % / 0.88 · road_surface 48.2 % / 0.74 ·
speed_limit 31.0 % / 0.63 (it insufficient, n 12) · object_count 89.7 % / 0.92 ·
obstacle_present 14.2 % / 0.44 (it insufficient, n 32).
Caption below (11.5px `--ink2`): the Windows‑1252 loss caveat, "The loss is real but **cannot be
quantified** — it is never corrected for and never a column."

### 2d · Two cards (`display:flex; gap:14px`)
**Cross-tab** (`flex:1.15`) — `.lbl` "Goal 1 × presence cross-tab · weather_code · llama3.1:8b", then a
3×3 contingency table with row/column totals in `--ink3`: hit 2 190 / **114** (`--warn`) / 2 304 ·
wrong 301 / 62 / 363 · missing 94 / 1 286 / 1 380 · total 2 585 / 1 462 / 4 047. Note beneath: "The
**114** in *hit × present = false* is self-contradiction: the model said the text does not contain the
feature and then extracted the record's exact value from it." That cell is the whole point of the card —
style it as the finding.

**Flag inconsistency rate** (`flex:.85`) — "present = false, yet the extracted value matched.
Automatically countable — a genuine quality signal on the flag itself." Then one row per model, mono tag
left, `.val` percentage + inline `.ci` right: llama3.1:8b 2.8 % [2.4–3.4] · qwen2.5:14b 1.1 % [0.8–1.4] ·
mistral-nemo:12b 4.6 % [4.0–5.3], all n 4 047. Bottom note (`margin-top:auto`): "Goal 2 numbers are
never published without the Goal 1 numbers beside them — a weak extractor manufactures false 'missing'
flags."

### 2e · Per-record output
`.lbl` "Per-record output — the actionable form of Goal 2" + right-side mono 11px `--ink3`
"1 462 records where weather is recorded but not written · export CSV". Table columns: Record 250px
(mono truncated id + an "anonymised" `.chip`) · Record value 150px (mono `3 · Schneefall`) · Finding
(plain sentence, "This report does not say what the weather was.") · Language 110px (mono
`de · 0.98`, `mixed · 0.41`). Last row is a muted `colspan="4"` "1 458 more".
**This list is the deliverable** — presence findings are consumed as a record list to act on, not as a
rate. It needs the standard pagination treatment in the implementation.

---

## Tab 3 · Ranking
File: `Ranking.dc.html`. Subtitle "Which model to pick — and where the evidence does not separate them."

**Purpose** — the one question the other tabs don't answer, answered honestly: usually "two models are
tied, pick on cost".

**Every number on this tab is derived from tab 1's scored rows — nothing here is independent.** That is
the invariant to preserve in the implementation:
- **Macro F1** = unweighted mean of the model's F1 over the **7 scored features** (Right of way is
  excluded because it is suppressed). mistral 5.808/7 = 0.830 · qwen3 5.749/7 = 0.821 ·
  gemma3 5.416/7 = 0.774.
- **Best / tied / worse** = counts of tab 1's `.mk` markers per model: 3/3/1 · 4/1/2 · 0/2/5 (each row
  sums to 7; the *best* column sums to 7 — exactly one highest value per feature).
- **Separating features** = the features where the two leaders' Wilson intervals do **not** overlap.
- Never let these be authored by hand — compute them.

**Content column** — `padding:18px 28px 22px; gap:16px`.

### 3a · Verdict banner
`.card` tinted `--accent-soft` with `border-color:oklch(0.86 0.006 260)`, a 16px info icon, a 13.5px
weight-600 headline and a 12.5px `--ink2` body, plus a right-aligned mono 11px `--ink3` "rank 1 shared".
Fixture: "Two models are tied at the top. This run does not separate them." / "mistral‑small:24b and
qwen3:14b tie on 4 of the 7 scored features and their macro intervals cross. Pick on cost, not on score
— or run more records to break the tie."

### 3b · Ranking table
46px header: `.lbl` "Ranking" + mono 11px "macro F1 across 7 scored features · Wilson 95%"; right side
"equal weight · 6 features unscored". Table in an `overflow:auto` well, `min-width:900px`.

| Column | Width | Content |
|---|---|---|
| # | 44px | mono 13px rank. **Tied models repeat the same number** (1, 1, 3) — never 1, 2, 3. |
| Model | 186px | mono 12px tag over mono 10.5px `--ink3` "digest · size" |
| Macro F1 · extraction | 196px | a 72×6 `.bar` (`--rule2` track, `--ink3` fill) + mono 11.5px value over mono 10.5px interval |
| Presence | 92px, right | mono presence score from tab 2 |
| Best / tied / worse | 120px | three mono 11px counts in `--ink` / `--ink2` / `--ink3` |
| Median latency | 104px, right | mono value over mono 10.5px token count |
| VRAM | 78px | mono size — **must agree with the model sub-line** |
| Verdict | 134px | `.pill`: "tied for best" as filled accent (leader) and outlined accent (tied), "behind on 5" as neutral `--rule2` / `--ink2` — the same vocabulary as tab 1's `.mk` |

Fixtures: **1** mistral‑small:24b 4b81e2d5 · 15.6 GB · 0.830 [0.815–0.844] · 0.907 · 3/3/1 · 1 505 ms ·
2.4 M tok — **1** qwen3:14b a7d3f19c · 12.1 GB · 0.821 [0.806–0.836] · 0.914 · 4/1/2 · 968 ms ·
2.1 M tok — **3** gemma3:12b 6c05ba73 · 8.9 GB · 0.774 [0.758–0.790] · 0.871 · 0/2/5 · 640 ms ·
1.9 M tok. The two rank-1 rows are tinted `--accent-soft`. Tie legend below, as on tab 1.

### 3c · "Where they actually differ"
46px header: `.lbl` + "3 of 7 scored features"; right "non‑overlapping intervals". Columns: Feature
(name + mono source) · n 56px · one 74px column per model **in ranking order** · Δ 58px (`--ok`) ·
Reading 172px (a plain sentence).
Rows: Road condition 1 611 · 0.752 / 0.688 / 0.640 · +0.064 "mistral leads alone — intervals clear by
.020" · Speed limit 4 512 · 0.847 / 0.812 / 0.790 · +0.035 "mistral again, on the largest scored n" ·
Vehicles involved 4 978 · 0.921 / 0.939 / 0.884 · +0.018 "the only feature where qwen3 clears mistral".
Footer (`--ink3`, info icon): "On the other 4 scored features the two leaders' intervals overlap, so
neither leads. gemma3 is behind on 5 of the 7 and ties on 2 — it is separated from the pair, the pair is
not separated from itself."

### 3d · "How this ranking is computed"
Four numbered rules (mono `--ink3` index in a 16px column + 12.5px `--ink2` text):
1. Per labelled feature, F1 with a Wilson 95 % interval; empty source columns leave the denominator (§8.6).
2. Features averaged with **equal weight** — not weighted by n, so a feature with 4 978 cases does not
   outvote one with 1 611.
3. Models whose macro intervals overlap **share a rank**. Exploratory features are excluded — no ground
   truth, cannot be scored.
4. Latency and VRAM are **reported, never scored** — the tie-breaker you apply, not one the tool applies.
Footer (`--warn-soft`): "This ranking is valid for `cfg 4f9a2c1e` on `corpus 2026‑09‑02` only. Change a
feature, a codelist label or the prompt template and it must be re-run."

---

## Interactions & Behavior
- **Tabs** switch within the Results route; the run descriptor, config chip and selected corpus persist
  across all three.
- **Goal 1**: clicking a feature row expands/collapses its per-model breakdown (one at a time).
  Sorting by feature or by any model column is expected; suppressed rows sort last, never as 0.
  Pagination 10/page over 13 labelled features. "Evidence"/span links and mismatch drill-downs open the
  Mismatches view filtered to that run × feature.
- **Goal 2**: the chip row switches model and re-renders every number on the tab. "export CSV" exports
  the per-record list for the current feature × model, in the filtered/sorted order.
- **Ranking**: read-only. It must recompute whenever tab 1's numbers change, and must never be cached
  independently — if the two disagree, Ranking is wrong by construction.
- **Suppression is a hard rule, not a display preference**: a cell below n = 20 emits the notice, and a
  suppressed feature is excluded from macro aggregates and from tie counting.
- **Transitions** — none designed beyond the breakdown expand.
- **Loading / empty** — not designed. A run with zero labelled features should say so rather than
  render an empty table.
- **Responsive** — desktop-only. Wide tables live in `overflow:auto` wells with `min-width`
  (Goal 1 738px, Ranking 900px, differ card 560px). Ranking's bottom pair is
  `repeat(auto-fit, minmax(340px, 1fr))` and stacks below ~700px.

## State Management
```
route:   { view:'results', tab:'extraction'|'presence'|'ranking', evaluationId }
context: { corpusId, corpusLabel, records, modelCount, cfgHash, devRun:boolean }

// tab 1
features:  FeatureScore[]
  { name, source, kind, n, suppressed,
    perModel: { modelId, f1, ciLow, ciHigh, mark:'best'|'tied'|'none',
                precision, recall, hit, wrong, missing }[] }
expandedFeatureId, page, pageSize:10, sort
byLanguage: { featureId, modelId, rows:{ lang, n, f1, ciLow, ciHigh, suppressed }[] }
exploratory: { attribute, discoveryRate, reviewed, reviewTotal, spanCount }[]

// tab 2
presence: { modelId,
            rows:{ featureKey, all:Rate, de:Rate, fr:Rate, it:Rate,
                   goal1:{ f1, precision, recall } }[] }   // Rate = {pct, ciLow, ciHigh, n, suppressed}
crossTab: { featureKey, modelId, cells:{ hit, wrong, missing } × { present, absent }, totals }
flagInconsistency: { modelId, pct, ciLow, ciHigh, n }[]
perRecord: { recordId, anonymised, recordValue, finding, lang, langConfidence }[]  // + paging, CSV export

// tab 3 — ALL DERIVED, never stored independently
ranking: derive(features) →
  { modelId, rank, macroF1, ciLow, ciHigh, best, tied, worse,
    presenceScore, medianLatencyMs, promptTokens, vramBytes, verdict }[]
separating: features where the top two models' intervals do not overlap
```
Shared rules to implement once: `wilson(successes, n)`, `suppress(n) = n < 20`,
`markTies(perModel)` (best = no overlapping rival; all overlappers = tied),
`macro(features) = mean over non-suppressed`.

## Design Tokens
Reuse the implemented set. Specific to this family:

| Token / literal | Value | Use |
|---|---|---|
| `--accent` | `oklch(0.52 0.13 255)` **(blue — see Fidelity note)** | best marks, evidence links, breakdown tint, verdict pill |
| `--accent-soft` | breakdown row, tied rank rows, verdict banner |  |
| `--ok / --ok-soft` | "Evaluation run" pill, positive Δ |  |
| `--warn / --warn-soft` | scope banner, language caveat, "wrong" counts, the 114 cell, validity footer |  |
| `--danger` | below-floor n, "no ground truth · not ranked" |  |
| `oklch(0.985 0.002 260)` | suppressed row tint (Goal 1) |  |
| `oklch(0.45 0.08 255)` / `oklch(0.85 0.03 255)` | breakdown label / its table rules |  |
| `oklch(0.86 0.006 260)` | verdict banner border |  |
| `oklch(0.40 0.10 72)` | body text on `--warn-soft` |  |
| `oklch(0.80 0.006 260)` | disabled pagination arrow |  |

Classes this family adds to the shared set: `.val` (point estimate line), `.ci` (interval line, mono
10.5px `--ink3`), `.ins` (insufficient-data chip), `.mk` (tie marker), `.tab`/`.tab.on`.
`.bar` and `.pill` are the shared definitions —
`.bar{height:6px;background:var(--rule2);border-radius:1px;overflow:hidden;flex:none;}` and
`.pill{display:inline-flex;align-items:center;border-radius:3px;padding:2px 7px;font-family:var(--mono);
font-size:10.5px;font-weight:500;white-space:nowrap;}` — do not re-derive them per view.

**Do not introduce a second table scale.** `.th` mono 10px uppercase, `.td` 12.5px, ~8×12px padding,
24×24 pagination buttons, 42–46px card headers, everywhere.

## Assets
No images. Icons are inline SVG on a 24×24 viewBox, `fill:none; stroke:currentColor`, stroke-width 1.8,
rendered at 14–16px — Lucide-equivalent (info, alert-triangle, table). Fonts: IBM Plex Sans + IBM Plex
Mono, already loaded. Carets, chevrons and markers are text glyphs (`▾ ‹ ›`).

## Files
- `Main.dc.html` — Results ▸ Goal 1 — Extraction
- `Presence.dc.html` — Results ▸ Goal 2 — Presence
- `Ranking.dc.html` — Results ▸ Ranking
- `support.js` — design-canvas runtime so the files open locally. **Not application code; port nothing.**

Already implemented, not included: shell + navigation, Import, Census, Codelists, Features, Prompts,
Evaluation. Not in this package: Mismatches (separate sidebar entry, to be handed off later).

## Open questions for the team
1. **Two model rosters exist in the fixtures.** Evaluation uses qwen2.5:14b / mistral-nemo:12b /
   gemma2:27b / llama3.1:8b / phi4:14b; the Results tabs use qwen3:14b / mistral‑small:24b / gemma3:12b
   (and Presence's cards still name the Evaluation roster). Unify on one roster before implementing —
   a digest is a model's identity here.
2. **Accent divergence** (blue in Results, neutral elsewhere) — adopt or unify, deliberately.
3. **Feature-name drift**: Goal 1 uses `Witter0Ausw` / `LichtVerhAusw` / `StrZu0Ausw`, while Census,
   Codelists and Features use `WitterungAusw` / `LichtverhaeltnisAusw` / `StrassenzustandAusw`. Same
   columns, two spellings.
4. **Presence precision/recall/F1** are deferred pending a human-labelled subset (≈50 records ×
   features) — that labelling tool is not designed.
5. The **n = 20 floor** and the **200-record dev threshold** are hard-coded in the copy. Confirm they are
   product constants, not settings.
6. **Goal 3 (Exploratory)** currently appears only as a card on tab 1. If review workflows grow
   ("0 / 15 reviewed" implies one), it needs its own tab or view.

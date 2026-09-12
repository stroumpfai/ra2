# Handoff: RA2 — Codelists & Features

## Overview
Second handoff package for RA2 ("Accident report analysis"). The **app shell (header + left
navigation), Import view and Census view are already implemented** — this package does not respecify
them. It covers the two remaining configuration views:

1. **Codelists** — the code → label tables the prompt reads, imported as one JSON file
2. **Features** — the feature set being configured: what gets asked of the model and how it is scored

Both reuse the shell, tokens, table and pagination patterns already in the codebase. Where this
document says "same as Import/Census", build on what is there rather than re-deriving it.

Pipeline position: **Data** (Import → Census → Codelists) → **Configure** (Features) → **Run**
(Evaluation) → **Review** (Results, Mismatches). Evaluation, Results and Mismatches come later.

## About the Design Files
The `.dc.html` files are **design references authored in HTML** — prototypes showing layout, hierarchy,
copy and behaviour. They are **not production code to copy**. Recreate them in the existing codebase
with its components, routing, state and styling.

- Styling is inline, plus one `<style>` block per file with the CSS custom properties and small utility
  classes (`.card .lbl .th .td .sth .std .navitem .chip .sl .rof .btn .pill .bar .fp .fld .row .ibp
  .seg .tok .stamp .sorth .sarr`). Map to your own components — most have an Import/Census equivalent.
- The mocks are static: dropdowns, filters, sorts and pagination render in a chosen state.
- Each board has a fixed `height` on its root (1080–1180px) so the artboard is fully visible on the
  design canvas. **Do not port that.**
- `WIREFRAME` stamps are artboard annotations, not UI. Drop them.

## Fidelity
**High-fidelity layout, medium-fidelity styling** — same contract as the first package. Structure,
spacing, exact column widths, copy and affordances are deliberate; the visual skin should come from the
implemented shell's tokens. Column widths in the tables below are load-bearing: several were tuned
against real content and clip when reduced. Where a width is given, honour it or re-measure.

---

## Screen 1 · Codelists
File: `Codelists.dc.html`
Title "Codelists" / "Code → label tables the prompt reads. Imported as JSON; a changed label changes
what every feature using it asks."

**Purpose** — every `enum` column found by the census needs a code → label table before a feature can be
built on it. The analyst imports one JSON file holding all of them, maps each column to a key in that
file, and checks coverage. A column with no codes blocks any feature using it.

**Layout** — master/detail, identical in structure to the Features view:

```
main
├── toolbar strip          flex:none, padding 11px 28px, surface, border-bottom
└── split                  flex:1, min-height:0, display:flex   (NEVER wraps)
    ├── master list        flex:0 1 452px; min-width:300px; border-right; surface
    │   ├── header         46px, padding 0 16px, overflow:hidden
    │   ├── list           flex:1; min-height:0; overflow:auto   (grouped rows)
    │   └── footer         flex:none, padding 9px 16px, border-top
    └── edit zone          flex:1 1 520px; min-width:360px; padding 20px 28px; overflow:auto
```

### Toolbar
Left group (`display:flex; gap:10px; flex-wrap:wrap; min-width:0`): three `.sl` dropdown chips —
`corpus 2026‑09‑02 · v1 ▾`, `prompt language · de ▾`, `status · all 18 ▾` — then a danger chip
(background `--danger-soft`, colour `--danger`, 11.5px, weight 500, 13px warning icon):
"2 columns have no codes · blocks 1 feature".
Right group: `margin-left:auto; flex:none` (WIREFRAME stamp only — no actions).

### Master list
Header: `.lbl` "18 columns" (truncating, `min-width:0`) + a secondary button **"Import Codes as JSON"**
(12px download icon). This is the **only** import action — codelists arrive as ONE file for all columns,
not one file per column. Measured fit: 69px + 157px in a 299px content box.

Rows are grouped by status, group label = `.lbl` in a `padding:12px 16px 6px` (first) /
`16px 16px 6px` (subsequent) div; the counts live in the group labels:
- **"2 missing — blocks any feature using it"** — row background `--danger-soft`, name and meta in
  `--danger`, right side a `.pill` outline marker "no codes" (border + colour `--danger`, white fill).
  Fixtures: `VortrittAusw` (unfall · 4 distinct in corpus · used by Right of way),
  `objekt.SchadenAusw` (objekt · 6 distinct · unused).
- **"2 partial — codes with no label"** — right side a `.bar` (44×6px, `--rule2` track) with a `--warn`
  fill + mono 11px percentage. Fixtures: `WitterungAusw` 88.9 % (selected), `HindernisAusw` 91.7 %.
- **"14 ok — fully labelled"** — right side a `.pill` "100 %" (`--ok-soft` / `--ok`). Fixtures:
  `LichtverhaeltnisAusw`, `UnfallTypAusw`, `StrassenzustandAusw`, `StrassenartAusw`,
  `objekt.FahrzeugartAusw`, `person.VerletzungsgradAusw`.

Row anatomy (`.row`: `padding:9px 16px; border-bottom:1px solid --rule2; display:flex;
justify-content:space-between; align-items:center; gap:10px`; hover `background:--rule2`):
`.rname` (12.5px, weight 500) over `.rsub` (mono 10.5px, `--ink3`) on the left, status marker
`flex:none` on the right. The selected row gets `background:--accent-soft`,
`border-left:2px solid --accent`, `padding-left:14px`, name at weight 600, sub at `--ink2`.

Footer: `.lbl` "Sorted by status" + mono 11px "10 of 18 shown".

### Edit zone (right) — read-only codes table
Header row (`display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap`):
- Left: `.lbl` "Codelist", then `h2` mono 16px weight 600 `WitterungAusw`, then 12px `--ink2`
  "unfall · 8 codes · used by Weather" (link to Features), then mono 11px `--ink3`
  "mapped to witterung_codes in codes‑vum‑2026‑09.json · 24 keys, 18 mapped".
- Right group — **must be `flex:1 1 auto; min-width:0; flex-wrap:wrap; justify-content:flex-end`**, or it
  pushes past the pane's right gutter: `.lbl` "Labels" + three `.chip`s `de` (active: border
  `--accent`, colour `--ink`, weight 500) / `fr` / `it`, then `.lbl` "JSON key" + a `.sl` dropdown
  `witterung_codes 9 ▾` (`max-width:210px`). **The JSON-key dropdown is the mapping control**: it lists
  the attribute names found in the imported file so each census column can be pointed at the right key.

Codes table (inside a `.card`, `table-layout:fixed`):

| Column | Width | Content |
|---|---|---|
| Code | 44px | mono code. `9` and `0` (unknown / not collected) rendered in `--ink3`. |
| Label · de (prompt) | flexible | **read-only text** (`.fld` = plain 12.5px, `line-height:1.4`, `text-wrap:pretty`, wraps over two lines rather than truncating). No border, no hover, not editable. |
| Usage | 96px, right | mono count over mono 10.5px `--ink3` percentage — the Census "Populated" stack. Sorted descending. |

Fixtures (`WitterungAusw`): 1 Trocken 2 744 / 55.1 % · 2 Regen — anhaltender Niederschlag 402 / 8.1 % ·
3 Schneefall oder Schneeregen 611 / 12.3 % · 4 Hagel 18 / 0.4 % · 5 Nebel — Sichtweite unter 100 m
144 / 2.9 % · 6 Starker Wind 52 / 1.0 % · **7 (danger row: background `--danger-soft`, code and label in
`--danger`, label reads "no label — not in the codelist") 31 / 0.6 %** · 8 Andere 61 / 1.2 % ·
9 Unbekannt 15 / 0.3 % · 0 Nicht erhoben 0 / 0 %.

Two footers inside the same card, each `flex:none`, 11.5px, 14px icon + text:
1. **Danger** (`--danger-soft` / `--danger`, `border-top:1px solid --rule`): "Code 7 appears in 31
   records but has no label. The prompt cannot name it, and those records score against an unnamed
   code." + a secondary **"Add label"** button in `--danger`.
2. **Neutral** (`oklch(0.982 0.003 260)` / `--ink2`, `border-top:1px solid --rule2`): "Read-only. Labels
   come from the imported JSON — to change one, import a corrected file. Any change gives Weather a new
   fingerprint, so runs before and after it are not comparable."

Below the card, two `.card`s in a wrapping row (`gap:14px`): **"Prompt preview · what the model is
shown"** (`flex:1.4 1 300px`, mono 11.5px `white-space:pre-wrap` showing `weather — enum. Emit the
code.` and the first three code = label lines) and **"Reminder"** (`flex:1 1 240px`): "A label is prompt
text, not a display string. All stored languages travel with the codelist; only the configured prompt
language is sent (§7)."

---

## Screen 2 · Features
Files: `FeatureConfig.dc.html` (draft, canonical), `FeatureConfig -frozen-.dc.html` (read-only), and
three variants of the same board showing other feature types in the edit zone:
`FeatureConfig - enum.dc.html`, `FeatureConfig - time tolerance.dc.html`,
`FeatureConfig - exploratory.dc.html`.

**These five files are ONE view.** The variants exist only because a static mock can show one selected
feature at a time — implement a single Features screen whose edit zone renders per feature type.

Title: the feature set's name — `Weather & conditions` + mono `v3` in `--ink3`. Subtitle: "Draft — 10
labelled · 4 exploratory · never run. Creating a feature set freezes this configuration."

**Purpose** — the analyst assembles a **feature set**: the list of things the model is asked to extract
from each accident narrative, each with its source, description, and how it will be scored. Creating a
feature set freezes the configuration; frozen sets are what evaluations cite.

**Layout**
```
main
├── toolbar strip       flex:none, padding 11px 28px, surface, border-bottom
├── split               flex:1, min-height:0, display:flex   (NEVER wraps — nowrap is required)
│   ├── feature list    flex:0 1 452px; min-width:300px; border-right; surface
│   │   ├── header      46px
│   │   ├── filter row  flex:none, padding 8px 16px, border-bottom --rule2, tinted
│   │   ├── table       flex:1; min-height:0; overflow:auto  (10 rows)
│   │   └── pagination  flex:none, padding 9px 16px, border-top
│   └── edit zone       flex:1 1 520px; min-width:360px; padding 20px 28px; overflow:auto
└── feature sets        flex:none; margin-top:16px; border-top; surface; max-height:302px
```
The split must be `nowrap`: with `flex-wrap:wrap` the edit zone drops below the list and falls off a
fixed-height artboard. The shrink rules alone fit (list floors at 300px, edit zone at 360px).

### Toolbar
Left group: `.sl` chip **`set · Weather & conditions v3 ▾`** — the **feature set** is what you select
here, *not* the corpus — then `prompt language · de ▾`, then a danger chip "2 errors block set
creation".
Right group (`margin-left:auto; flex:none`): WIREFRAME stamp + the primary button
**"Create a feature set"** (disabled at `opacity:.45` while errors exist).

### Feature list (flat table + filters)
Header: `.lbl` "10 + 4 features" (truncating) + a secondary **"Add feature"** button (12px plus icon).
Filter row: two `.sl` chips at `padding:3px 8px; font-size:10.5px` — **`type · all ▾`** and
`state · all ▾`.

The list is **one flat table**, not grouped by type (`table-layout:fixed`):

| Column | Width | Content |
|---|---|---|
| Feature | flexible | name (12.5px, weight 500; selected row weight 600) over mono 10.5px `--ink3` source line. Both ellipsize — the only columns allowed to. `padding-left:16px`. |
| Type | 74px | mono 10.5px `--ink2`: `accident` · `derived` · `object` · `exploratory`. This replaced the former group headers. |
| — | 72px, right, `padding-left:4px` | `.fp` (mono 10px `--ink3`) 6-char definition fingerprint, or a 14px `--danger` warning icon on a blocking row. 72px is the minimum that shows all six characters. |

Row states: default; **selected** = `background:--accent-soft`; **error** = `background:--danger-soft`
with name and source line in `--danger`.

Page 1 (10 rows): Weather `WitterungAusw` accident a91f4c · Light conditions
`LichtverhaeltnisAusw` accident 3d02b8 · **Right of way `VortrittAusw · no codes` accident ERROR** ·
Speed limit `HoechstGeschwKmHFeld` accident 7e5511 · Accident time `UnfallZeitFeld · ± 15 min`
accident f10c73 · Vehicles involved `native AnzObjFeld` derived c40ade · Bicycle involved
`any_object_matches` derived 18bb90 · Worst injury severity `max_ordinal · Verletzungsgrad` derived
5a7e02 · Vehicle type per object `objekt.FahrzeugartAusw` object — · **Damage per vehicle
`objekt.SchadenAusw · non‑scalar` object ERROR**.
Page 2 (4 rows, all `exploratory`): Phone use mentioned 6602fa · Animal on carriageway bb1d47 ·
Roadworks mentioned 2c9081 · Emergency vehicle on scene db44e6.

Pagination row: same component as Import/Census — `.lbl` "Rows per page" + `10 ▾` select on the left,
mono 11px "1–10 of 14" + prev/next `.ibp` buttons on the right (disabled arrow
`oklch(0.80 0.006 260)`).

### Edit zone — one card per feature, shape depends on type
Header: `.lbl` "Editing" + `h2` 16px weight 600 feature name on the left; on the right a block that
**must be `flex:1 1 240px; min-width:0; text-align:right`** (not `flex:none`): `.lbl` "Definition
fingerprint" (+ `· preview` in `--warn` on the draft), mono 12px truncated hash, and an 11px `--ink3`
note ("Final value is computed when the evaluation is created.").

Then a `.card` (`padding:16px; display:flex; flex-direction:column; gap:14px`) containing, in order:

1. **Kind / Grain / Value type** — a `display:grid; grid-template-columns:repeat(auto-fit,
   minmax(160px,1fr)); gap:14px` row (auto-fit is required: at 396px the pane drops it to fewer
   columns instead of crushing the fields). Kind is a `.seg` two-segment control
   (Labelled | Exploratory); Grain and Value type are `.rof` selects (`display:flex; width:100%;
   justify-content:space-between` — **not** the `.sl` inline chip, which must stay nowrap for toolbars).
2. **Source or Derivation** — differs by type, see the four cases below.
3. **A contextual note** — `--warn-soft` / `--accent-soft` panel explaining the one non-obvious rule
   that applies to this feature.
4. **Description** — `.lbl` "Description — goes into the prompt verbatim" + a bordered 12.5px box,
   `line-height:1.55`. This text is sent to the model as written.
5. **Matching rule / Parameter / Scored in MVP** — same auto-fit grid; each has an 11px `--ink3`
   helper line beneath.

Then one or two `.card`s in a wrapping row for the type-specific caveat and the Reminder.

#### Case A · labelled enum on a native column — `FeatureConfig - enum.dc.html` (Weather)
Grain `Accident level`, value type `enum (code)`. Section 2 is **Source — native column**: a tinted
box with a `.tok` chip `WitterungAusw ▾` + mono 11px `--ink3` "unfall · 9 distinct in corpus", and below
it `.lbl` "Codelist" + "8 of 9 codes labelled" + a link "open codelist ↗".
Note: `--warn-soft` — code 7 unlabelled, 31 records, "the feature still runs; those records score
against an unnamed code", linking to Codelists.
Matching `exact` ("enum → the emitted code must equal the ground-truth code"), parameter
"none for enum" (dashed, `--ink3`), scored "Yes — scalar" in `--ok`.
Bottom card: "What the model is shown" — the prompt preview, mono `pre-wrap`.

#### Case B · labelled time with a tolerance — `FeatureConfig - time tolerance.dc.html` (Accident time)
Grain `Accident level`, value type `time`. Source native `UnfallZeitFeld` · "unfall · 96.2 % populated ·
HH:MM". Matching `within tolerance`; **Parameter is a real control**: `± 15 min` with a mono bold value
and `− +` steppers. Note (`--accent-soft`): "At ± 15 min this feature scores 0.91; at ± 5 min it scores
0.62 on the same run… a tolerance is a claim about what counts as right… so it travels in the
fingerprint". Header note: "The ± tolerance is part of the definition — changing it changes the
fingerprint."
Bottom card: "Empty is not a guess" — 3.8 % of records carry no time and leave the denominator.

#### Case C · labelled derived aggregate — `FeatureConfig.dc.html` (Bicycle involved)
Grain `Derived aggregate`, value type `boolean`. Section 2 is the **derivation builder** — a closed
catalogue, not free text: `.lbl` "Derivation — closed catalogue" + mono 10.5px "7 types · 6 operators",
then a tinted box of `.tok` chips: `any_object_matches ▾` `objekt.FahrzeugartAusw ▾` `in ▾` `M12 ×`
`M13 ×` `+ code` (dashed). Below: `.lbl` "Saved as" + the mono expression
"any_object_matches · objekt.FahrzeugartAusw in M12, M13 — Fahrrad, E‑Bike".
Note (`--warn-soft`): no native column carries this, so a derivation is right — but where one does
(`AnzObjFeld` for *vehicles involved*) the builder offers the native column instead before you save.
Bottom card: "Also captured, not scored" — per-vehicle and per-person detail keyed by the narrative's
role codes (`B1`, `G1`, `P`) is stored on every extraction; only the aggregate is scored.

#### Case D · exploratory — `FeatureConfig - exploratory.dc.html` (Phone use mentioned)
Kind `Exploratory` selected. Source is a **dashed** box: "narrative only — no source column exists for
this". Matching rule is **disabled** (`.rof` dashed, `--rule2`, `--ink3`): "n/a — no ground truth";
parameter is `discovery rate`; scored "No — reported, not scored" in `--ink2`.
Note (`--warn-soft`): "An exploratory feature can never be wrong, only surprising… Promote it to
labelled only once a column or a manual sample exists to score against."
Bottom card: "Exploratory budget" — mono 15px "4 / 20 used in this config", a 6px progress bar at 20 %,
and "Each one lengthens the prompt for every record in the run."

### Feature sets table (full-width strip)
Sits **below the split**, spanning the full content width so its right edge aligns with the edit zone's:
`flex:none; margin-top:16px; border-top:1px solid --rule; background:--surface; max-height:302px`.
Header 42px (`padding:0 28px`, tinted `oklch(0.988 0.003 260)`, `border-bottom:1px solid --rule2`):
`.lbl` "Feature sets" + secondary **"New set"** button.

`table-layout:fixed`. All content columns are **fixed width and a trailing empty filler column takes
all remaining space** — so a wide window adds space on the right instead of opening a gap mid-table:

| Column | Width | Content |
|---|---|---|
| Set | 164px, `padding-left:28px` | set name (weight 500; selected 600) + mono 10.5px `--ink3` version |
| Description | 132px | 12px `--ink2`. Short strings — this column is the tightest; the fixtures were shortened to fit it. |
| Created | 126px | mono 11.5px `2026‑09‑04` + time in `--ink3` on the **same line** |
| Features | 66px, right | mono count. 66px is the minimum that fits the header label. |
| State | 138px | mono 11px "draft · never run", or a `.pill` "LOCKED · n evals" (`--accent-soft` / `--accent`) |
| action | 72px, right | drafts: rename + delete `.ibp` icon buttons (delete in `--danger`). Locked: mono 11px `--ink3` "locked"; on draft boards the v2 row instead links "open ↗" to the frozen board. |
| filler | flexible, `padding:0` | empty; absorbs all slack |

Fixtures: **Weather & conditions v3** · Conditions + probes · 2026‑09‑04 14:22 · 14 · draft · never run
(selected, rename/delete) · **Weather & conditions v2** · v3 predecessor · 2026‑08‑21 09:07 · 11 ·
LOCKED · 2 evals · **Injury & persons v1** · Severity + counts · 2026‑08‑04 16:40 · 6 · LOCKED · 1 eval ·
**Scratch — objekt grain** · Per‑vehicle damage · 2026‑09‑09 11:58 · 3 · draft · never run.
Footnote (`padding:8px 28px; border-top:1px solid --rule2`, 11px `--ink3`): "A set locked by an
evaluation cannot be renamed or deleted — its runs cite it by name."

### Frozen state — `FeatureConfig -frozen-.dc.html`
Same view, read-only, for a set an evaluation already cites. Differences:
- Subtitle "Frozen — read-only. 8 labelled · 3 exploratory, cited by 2 evaluations."; toolbar chip
  becomes an `--accent-soft` lock chip "Frozen 2026‑08‑21 · cited by 2 evaluations".
- Primary action is **"Clone to new evaluation"**; no Add feature (list header shows
  "8 + 3 features" + mono "read-only"), no New-set action semantics for locked rows.
- Every control renders as a static `.ro` readout (`1px solid --rule2`, tinted background, no caret);
  the derivation builder collapses to its saved mono expression; the "· preview" fingerprint qualifier
  is gone and the note reads "Fixed at freeze. Results citing this config compare against it."
- Error rows are absent — they were fixed before freezing. The Reminder card is replaced by
  **"Evaluations citing this config"** listing eval‑2026‑08‑22 (4 978 records) and eval‑2026‑08‑21
  (400), plus "Editing anything here would break their reproducibility — clone instead."

---

## Interactions & Behavior

**Codelists**
- The three toolbar chips filter the master list; selecting a row loads it into the edit zone.
- **Import Codes as JSON** takes one file for all columns. After import, each column's **JSON key**
  dropdown maps it to a key in that file; unmapped columns show as "no codes". Expect
  `{ "<key>": [ { "code": …, "label_de": …, "label_fr": …, "label_it": … } ] }` or equivalent — the exact
  schema is still open (see below).
- Labels are **read-only**. A correction means importing a fixed file; there is no inline editing,
  no autosave and no undo.
- Any change to a codelist re-fingerprints every feature that reads it, so runs before and after are
  not comparable — surface that wherever a codelist changes, not only here.
- A column with no codes blocks evaluation of any feature using it; the toolbar chip counts those.

**Features**
- Selecting a feature loads it into the edit zone; the edit zone's shape follows Kind × Grain × Value
  type (cases A–D). Changing Value type changes which Matching rules and Parameters are legal.
- The **derivation catalogue is closed** — a fixed list of derivation types and operators, never free
  text. Where a native column already carries the value, offer it instead of a derivation.
- Type and State filters + pagination (10 per page) over the flat list.
- **Create a feature set** freezes the configuration and computes the real fingerprints (the draft shows
  a preview value). Blocked while any error row exists.
- Feature sets: drafts can be renamed and deleted; a set cited by an evaluation is locked — rename and
  delete are unavailable, and the row links to the frozen view instead.
- **Fingerprints** are the spine: every feature has one, it changes when the column, derivation,
  description, matching rule, parameter or codelist labels change, and results cite it.

**Transitions** — none designed; at most a 100–150ms ease on hover/background changes.

**Loading / empty / error** — not designed. Suggested: skeleton rows at the same row height inside the
list; empty state = one centred 12.5px `--ink2` line; blocking problems surface as the row's error state
plus the contextual note in the edit zone, not as toasts.

**Responsive** — desktop-only.
- The Features split and the Codelists split must **never wrap**; the list shrinks to 300px, the edit
  zone to 360px, and inside the edit zone the auto-fit grids drop to fewer columns.
- Tables are `table-layout:fixed`; only the Feature/Label/Description columns may ellipsize.
- Toolbar chip rows may wrap; the right-hand group stays right-aligned via `margin-left:auto`
  (not a `flex:1` spacer).

## State Management

**Codelists**
```
filters:  { corpusId, promptLanguage, status }
selected: columnName
columns:  CodelistColumn[]
  { name, table, distinctInCorpus, codeCount, coveragePct,
    status: 'ok'|'partial'|'missing', usedBy: FeatureRef[], jsonKey }
codes:    { code, labels: {de,fr,it}, usageCount, usagePct, unlabelled }[]
import:   { fileName, keys: string[], mappedCount }
```
Coverage = **% of codes appearing in the corpus that have a label** (confirmed). Data: census enum
columns + code frequencies per corpus; one JSON import per delivery; the mapping is persisted per column.

**Features**
```
sets:      FeatureSet[]
  { id, name, version, description, createdAt, featureCount,
    state:'draft'|'frozen', lockedByEvalCount, frozenAt }
selectedSetId
features:  Feature[]
  { id, name, kind:'labelled'|'exploratory',
    grain:'accident'|'derived'|'object'|'person',
    valueType:'enum'|'integer'|'decimal'|'time'|'boolean'|'code',
    source: { type:'native', column } | { type:'derived', op, column, operator, codes[] } | { type:'narrative' },
    description, matching:{ rule, parameter }, scored, fingerprint, errors[] }
listFilters: { type, state }   listSort   page   pageSize:10
errors:      blocking count → disables "Create a feature set"
```
Data: read the census for available columns and the codelists for enum validity; POST to create
(freeze) a set; PATCH/DELETE only while draft.

## Design Tokens
Unchanged from the implemented shell — reuse the existing definitions. Additions used by these two
views:

| Token | Value | Use |
|---|---|---|
| `--danger` | `oklch(0.53 0.15 27)` | missing codelist, error rows, delete, blocking chips |
| `--danger-soft` | `oklch(0.962 0.030 27)` | error row background, danger footer |
| `--ok` | `oklch(0.50 0.11 152)` | "100 %" pill text, "Yes — scalar" |
| `--ok-soft` | `oklch(0.958 0.030 152)` | "100 %" pill background |
| `--warn` / `--warn-soft` | `oklch(0.56 0.13 72)` / `oklch(0.965 0.035 80)` | partial coverage bar, contextual notes |
| note text on warn | `oklch(0.40 0.10 72)` | body text inside `--warn-soft` panels |
| field/tint background | `oklch(0.982 0.003 260)` | `.ro`/`.rof` readouts, derivation box, neutral footer |
| strip header tint | `oklch(0.988 0.003 260)` | Feature sets header, filter row |

New utility classes worth naming in the implementation:
`.sth`/`.std` (the tighter 10px-padded table pair used by the list and sets tables),
`.rof` (full-width field readout — must not be confused with `.sl`, the nowrap toolbar chip),
`.ro` (frozen static readout), `.tok` (derivation chip), `.fp` (fingerprint),
`.ibp` (22×22 icon button), `.seg` (segmented control), `.pill`, `.bar`.

Type, spacing, radius, borders and the no-shadow rule are as already implemented. Minimum sizes that
matter: card/strip headers 42–46px, icon buttons 22×22, fingerprint column 72px, Features column 66px.

## Assets
No images. Icons are inline SVG on a 24×24 viewBox, `fill:none; stroke:currentColor`, stroke-width
1.8–2.2, rendered at 12–15px — Lucide-equivalent (download, plus, pencil, trash, lock, info, alert,
chevron). Fonts: IBM Plex Sans + IBM Plex Mono, already loaded. Carets and pagination chevrons are text
glyphs (`▾ ▼ ‹ ›`) — swap for real icons if the codebase has them.

## Files
- `Codelists.dc.html` — Codelists view
- `FeatureConfig.dc.html` — Features, draft, derived-aggregate feature selected (canonical board)
- `FeatureConfig - enum.dc.html` — same view, native-enum feature selected
- `FeatureConfig - time tolerance.dc.html` — same view, time feature with ± tolerance
- `FeatureConfig - exploratory.dc.html` — same view, exploratory feature
- `FeatureConfig -frozen-.dc.html` — Features, frozen/read-only
- `support.js` — design-canvas runtime so the files open locally. **Not application code; port nothing.**

Already implemented, not included: shell + navigation, Import, Census.
Still to be designed: Evaluation, Results, Mismatches, the Add-feature panel state, and the Import
file-report modal.

## Open questions for the team
1. **Codelist JSON schema** — key naming and the label-per-language shape are placeholders
   (`witterung_codes`, `label_de/fr/it`). Confirm against the real VUM export.
2. **Add feature** — the button exists; the "new feature" state of the edit zone is not drawn yet.
   The intent is the same right-hand panel in a new-feature mode, not a modal (the derivation builder
   is too large for one).
3. Whether a **corpus** selector is still needed on the Features toolbar now that the feature set is
   selected there — currently only prompt language remains alongside it.
4. Loading, empty and error states for both views.
5. Whether the frozen board's **"Clone to new evaluation"** should read "Create a feature set" to match
   the draft board's renamed primary action.

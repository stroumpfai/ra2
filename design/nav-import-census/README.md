# Handoff: RA2 — Navigation, Import, Census

## Overview
RA2 ("Accident report analysis") is an internal data-management tool. An analyst delivers a batch of
source files, RA2 freezes that delivery into an **immutable corpus**, then profiles the corpus so the
analyst can choose which source columns become model features. This bundle covers three parts of the
application:

1. **Left navigation** (the app shell — header + sidebar, shared by every view)
2. **Import view** — turn a delivery of files into a corpus; browse existing corpora
3. **Census view** — how populated each source column is; the basis for feature selection

The remaining views (Codelists, Features/FeatureConfig, Evaluation, Results/Main, Mismatches) exist as
designs in the same project and will be handed off later. Their nav entries are already specified here,
so the shell can be built once and reused.

## About the Design Files
The `.dc.html` files in this bundle are **design references authored in HTML** — prototypes that show the
intended layout, hierarchy, copy and behaviour. They are **not production code to copy**. The task is to
**recreate these designs inside the target codebase's existing environment** (React, Vue, SwiftUI, native,
server-rendered templates…) using its established component library, routing, state and styling patterns.
If no environment exists yet, pick the framework most appropriate for the product and implement the
designs there.

Notes on how the files are built (so you can read them, not so you copy them):
- All styling is **inline** on elements, plus one small `<style>` block per file with CSS custom
  properties and a handful of utility classes (`.card`, `.th`, `.td`, `.navitem`, `.lbl`, `.chip`, `.btn`,
  `.bar`, `.sorth`, `.sarr`, `.tick`, `.sel`, `.selall`, `.stamp`). Map these to your own components.
- The mocks are **static**: dropdowns, sorts, checkboxes and pagination are rendered in a chosen state
  and do not react to clicks. Nav links are real `<a href>`s between files.
- Each board has a fixed `height` on its root (Import 1400px, Census 1240px) purely so the artboard is
  fully visible in the design canvas. **Do not port that** — in the app the shell fills the viewport and
  the content column scrolls.
- `WIREFRAME` stamps are artboard annotations, not UI. Drop them.

## Fidelity
**Mixed — treat as high-fidelity layout / medium-fidelity styling.**

Structure, spacing, column widths, copy, information hierarchy and interaction affordances are
deliberate and should be reproduced closely. The visual skin is a deliberately neutral, near-monochrome
"instrument panel" palette defined in the tokens below; colours and type are exact values, but if the
target codebase already has a design system, **apply its equivalents** (its neutrals, its data-table
component, its dropdowns) rather than hand-rolling these values. The one thing to preserve verbatim is
the *semantics* of colour: state and severity are the only places any hue appears.

---

## Screens / Views

### 0. App shell (header + left navigation)
Shared by all views. Files: any board; identical markup in each.

**Purpose** — permanent orientation: which product, which view, and where that view sits in the
pipeline (Data → Configure → Run → Review).

**Layout**
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ header (flex, align-items:stretch, full window width)                        │
│ ┌──────────────┬─────────────────────────────────────────────────────────────┐│
│ │ brand block  │ view title block                                            ││
│ │ width 196px  │ flex:1, padding 14px 28px                                   ││
│ │ padding 14px │ h1 + one-line description                                   ││
│ └──────────────┴─────────────────────────────────────────────────────────────┘│
├──────────────┬───────────────────────────────────────────────────────────────┤
│ nav 196px    │ main (flex:1, min-width:0, flex column)                       │
│ (fixed)      │                                                              │
└──────────────┴───────────────────────────────────────────────────────────────┘
```
- Outer: `display:flex; flex-direction:column`, background `--bg`.
- Header: `flex:none`, background `--surface`, `border-bottom:1px solid --rule`. It spans the **full
  window width** — the sidebar does not start above it. The brand cell is exactly the nav width (196px)
  with `border-right:1px solid --rule`, so the vertical rule is continuous from header into sidebar.
- Below the header: `display:flex; flex:1; min-height:0` containing nav + main.
- Nav: `width:196px; flex:none`, background `--surface`, `border-right:1px solid --rule`,
  `padding-top:14px; padding-bottom:14px`, items in a column with `gap:2px`.

**Brand block**
- "RA2" — mono, 15px, weight 600, letter-spacing −0.01em, colour `--ink`.
- "Accident report analysis" — `.lbl` (mono, 10px, uppercase, letter-spacing .09em, weight 500,
  colour `--ink3`), `margin-top:3px`.

**View title block**
- `h1` — 19px, weight 600, letter-spacing −0.012em, colour `--ink`, margin 0.
- Description — 12.5px, colour `--ink2`, `margin-top:2px`. Exactly one line, no controls. All view
  controls live in a toolbar **below** the header, never in it.
- Copy: Import → "One delivery becomes one immutable corpus."; Census → "How populated each source
  column is — the basis for choosing features."

**Nav groups and items** (group label = `.lbl`, `padding:0 14px 6px` for the first group and
`16px 14px 6px` for subsequent groups)

| Group | Item | Route/file | Icon (Lucide-equivalent, 15×15, stroke 1.8) |
|---|---|---|---|
| Data | Import | Import.dc.html | download / arrow-down-to-tray |
| Data | Census | Census.dc.html | bar-chart (4 ascending bars on a baseline) |
| Data | Codelists | Codelists.dc.html | list |
| Configure | Features | FeatureConfig.dc.html | sliders / settings-2 |
| Run | Evaluation | Evaluation.dc.html | play inside a circle |
| Review | Results | Main.dc.html | table / layout |
| Review | Mismatches | Mismatches.dc.html | alert-triangle |

Icons are inline SVG, `fill:none; stroke:currentColor; stroke-width:1.8; stroke-linecap:round`
(some also `stroke-linejoin:round`), 24×24 viewBox rendered at 15×15. Substitute the codebase's icon
set — the exact paths are in the HTML if you want to match them.

**`.navitem` states**
- Rest: `display:flex; align-items:center; gap:9px; padding:6px 14px`, font 12.5px, colour `--ink2`,
  `border-left:2px solid transparent`, no underline.
- Hover: colour `--ink`, background `--rule2`, still no underline.
- Active (current view): colour `--ink`, background `--accent-soft`, `border-left-color:--accent`,
  `font-weight:500`.
- Focus: not designed — add a visible focus ring from the codebase's standard.
- The 2px left border is present-but-transparent at rest so nothing shifts between states.

---

### 1. Import view
File: `Import.dc.html`. Title "Import" / "One delivery becomes one immutable corpus."

**Purpose** — the analyst reviews the files of an incoming delivery (fixing encoding problems and
deselecting files), then creates one immutable corpus from the selected files. Below that, they browse
the corpora that already exist and see which are locked by an evaluation.

**Content column** — `main > div`: `flex:1; min-height:0; padding:20px 28px;
display:flex; flex-direction:column; gap:16px`. In the app, this column scrolls vertically.

#### 1a. Two file tables, side by side
A CSS grid, **not** flex wrapping:
`display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; align-items:start`.
Left = **Structured sets**, right = **Text file**. `minmax(0,1fr)` is required so the columns can shrink
below their content width instead of wrapping — **the two columns must never stack or wrap**, at any
window width.

Each is a `.card` (background `--surface`, `1px solid --rule`, radius 3px), `display:flex;
flex-direction:column; min-width:0`, with four stacked zones. **The zones are height-matched between the
two cards so the header rules and the pagination rows line up horizontally** — this alignment is a
requirement, not a nicety:

1. **Card header** — fixed `height:46px`, `padding:0 14px`, `flex:none`, `overflow:hidden`,
   `display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:nowrap`,
   `border-bottom:1px solid --rule`.
   - Left: `.lbl` title + a mono 11px count, `align-items:baseline; gap:10px`, both `white-space:nowrap`.
     Structured: "Structured sets" + "9 files · 9 selected" (colour `--ink2`).
     Text: "Text file" + "1 file · 1 selected" (colour `--accent`).
   - Right: a single **icon-only add button** — 24×24, centred, `1px solid --rule`, radius 3px,
     colour `--ink2`, background `--surface`, containing a 12×12 plus glyph (stroke 2.2).
     Tooltip/aria-label: "Add set" (left card) / "Add file" (right card).
   - There is deliberately **no** "Select all / None" pair here — select-all is the checkbox in the
     table's own header row.
   - `overflow:hidden` matters: without it the header content can bleed over the neighbouring card.
2. **Table well** — fixed `height:404px; overflow:auto`. Sized to hold **10 rows plus the header row**
   at the page size of 10, so both cards are the same height regardless of how many rows they hold.
3. **Pagination row** — `flex:none`, `padding:9px 14px`, `border-top:1px solid --rule`,
   `display:flex; align-items:center; justify-content:space-between; gap:12px`.
   - Left: `.lbl` "Rows per page" + a mono 11px select showing `10 ▼` (`padding:3px 8px`,
     `1px solid --rule`, radius 3px, caret `--ink3` at 9px).
   - Right: mono 11px range label ("1–7 of 9" / "1–1 of 1"), then prev/next buttons — 24×24, centred,
     `1px solid --rule`, radius 3px. Disabled prev is `oklch(0.80 0.006 260)`; enabled next is `--ink2`.
4. **Footnote** — `padding:10px 14px`, `border-top:1px solid --rule2`, 11.5px, a 14×14 info circle
   (`flex:none; margin-top:1px`) + text, `gap:7px; align-items:flex-start`.
   - Structured (colour `--ink3`, no background): "Deselected files stay in the list and are excluded
     from the corpus. The report icon opens that file's parse findings; re-parse after changing its
     encoding or delimiter."
   - Text (background `--accent-soft`, colour `oklch(0.38 0.10 255)`): "A `UnfallUid` collision attaches
     the wrong narrative — uniqueness is checked across the whole delivery." (`UnfallUid` in mono.)
   Footnote heights may differ between the two cards; that is fine because it sits *below* the
   pagination row, which is what has to align.

**Both file tables use `table-layout:fixed` with these column widths** so the table can never exceed its
card and no column becomes unreachable:

| # | Column | Width | Content |
|---|---|---|---|
| 1 | selection | 30px, `padding-right:0` | `.tick` checkbox, 14×14, radius 2px, `1px solid --ink3`; checked = background+border `--accent`, white 10px check (stroke 3.2). Header cell holds the select-all checkbox. |
| 2 | File | flexible (takes all remaining width) | filename, mono 11.5px, single line, `overflow:hidden; text-overflow:ellipsis` inside `display:flex; align-items:center; overflow:hidden`. **This is the only column allowed to truncate** — it does so only below ≈1030px window width. Sortable, currently sorted ascending. |
| 3 | Rows | 52px, right-aligned | mono row count with thin space as thousands separator ("1 204", "4 982"). Sortable. |
| 4 | State | 86px | 12.5px text: "ok" in `--ok`, "2 rejected" in `--danger`, "3 recovered" in `--warn`. Sortable. Must stay ≥86px — its longest value needs ~67px + padding, and `.td` is `white-space:nowrap` with no clipping. |
| 5 | action | 46px, right-aligned, `padding-right:14px` | one 22×22 button, `1px solid --rule`, radius 3px, colour `--ink3`, 13px clipboard glyph → **opens that file's parse-findings report** (modal, not yet designed). Re-parse, preview and remove live inside that modal. |

`.th`: mono 10px, uppercase, letter-spacing .07em, weight 500, colour `--ink3`,
`padding:0 9px 7px` (+`padding-top:10px`), `border-bottom:1px solid --rule`, left-aligned,
`white-space:nowrap`. `.td`: `padding:8px 9px`, `border-bottom:1px solid --rule2`, 12.5px,
`vertical-align:middle`, `white-space:nowrap`.

Sort affordance `.sorth`: label + `.sarr` glyph (9px, letter-spacing −1px, colour
`oklch(0.80 0.006 260)`); `▲▼` = unsorted, single `▲`/`▼` in `--ink` (`.sarr.on`) = active direction.
Sorting is two-direction on File, Rows and State.

Fixture data — structured sets (9 files, page shows 7 rows):
`vum_AG_unfall.txt` 1 204 ok · `vum_AG_objekt.txt` 2 981 ok · `vum_AG_person.txt` 3 150 ok ·
`vum_BE_unfall.txt` 1 876 ok · `vum_BE_objekt.txt` 4 402 **2 rejected** · `vum_BE_person.txt` 4 613 ok ·
`vum_VD_… (3 files)` 7 848 ok (collapsed group row, filename and count in `--ink2`).
Text file (1 file): `Unfallhergang.csv` 4 982 **3 recovered**.

Encoding is **not** a column any more — per-file encoding/delimiter belongs to the report modal
(the earlier design had `UTF‑8` / `cp1252` chips inline; `cp1252` was flagged in `--warn`).

#### 1b. Corpora
A `.card` with `flex:none`, full content width.
- Header: same 46px strip pattern. Left `.lbl` "Corpora" + mono 11px `--ink2`
  "4 imported · 2 locked by an evaluation". Right: primary button —
  `.btn` with background `--accent`, colour `#fff`, `padding:8px 16px`, radius 3px, 12.5px weight 500 —
  **"Create corpus · 4 978 records"**. The record count is the sum of the selected files.
- Sub-caption strip: `padding:9px 14px`, `border-bottom:1px solid --rule2`, 11.5px `--ink2`:
  "A corpus is immutable. Once a run has touched it, it cannot be deleted — the runs that cite it would
  stop being reproducible."
- Table (auto layout, `overflow-x:auto`), columns: Corpus 150px · Description flexible · Created 118px ·
  Records 84px · Language composition flexible · Canary 78px · Status 184px · action 104px.
- Row content: corpus name mono weight 500 + mono 11px `--ink3` version ("v1"); description 12px `--ink2`;
  created timestamp mono 11.5px; records mono; language composition mono 11.5px
  ("de 2 812 · fr 1 402 · it 396"), dev-sized deliveries get a `--warn` suffix "· dev-sized";
  canary count mono, 0 in `--danger`, non-zero in `--warn`;
  status is either a pill (background `--accent-soft`, colour `--accent`, `padding:2px 7px`, radius 3px,
  mono 10.5px weight 500, "LOCKED · 1 eval") or 12px `--ink2` "Not used by any evaluation";
  action is mono 11px — "Delete" in `--danger` when allowed, "delete blocked" in `--ink3` when locked.
- Fixtures: 2026‑09‑02 (current), 2026‑08‑19 (locked, superseded), 2026‑08‑04 sample (40 records,
  dev-sized), 2026‑07‑28 trial (3 411 canary). This table is also paginated at 10 rows with the same
  pagination row as the file tables.

---

### 2. Census view
File: `Census.dc.html`. Title "Census" / "How populated each source column is — the basis for choosing
features."

**Purpose** — the analyst scans every source column's fill rate and value distribution to decide which
columns are viable features, then hands one off to Features (FeatureConfig).

**Content column** — `main > div`: `flex:1; min-height:0; padding:16px 28px 24px;
display:flex; flex-direction:column; gap:14px`.

#### 2a. Filter toolbar
`display:flex; align-items:center; gap:10px; flex-wrap:wrap`, with two children:
- **Left group** (`display:flex; align-items:center; gap:10px; flex-wrap:wrap; min-width:0`) — three
  dropdown chips, then a caption. Chip style: `display:inline-flex; align-items:center; gap:8px;
  1px solid --rule; radius 3px; padding:4px 9px; background:--surface; mono 11px; colour:--ink;
  white-space:nowrap`, with a 9px `▼` caret in `--ink3`.
  1. `corpus 2026‑09‑02 · v1 ▼` — which corpus is being profiled.
  2. `populated ≥ all ▼` — minimum fill-rate filter.
  3. `table · all 162 ▼` — source-table filter; the count is the number of columns matching.
     Options: All · 162 columns / unfall · 67 / objekt · 77 / person · 18. (This replaced a tab strip;
     it is a dropdown so the toolbar stays one row.)
  Caption: 12px `--ink2` "Feature selection reads this table."
- **Right group** (`display:flex; align-items:center; gap:10px; margin-left:auto; flex:none`) —
  `.btn` "Export CSV" (secondary: `1px solid --rule`, background `--surface`, colour `--ink`,
  `padding:7px 14px`, 12.5px weight 500). `margin-left:auto` on the group, **not** a `flex:1` spacer —
  the spacer breaks right alignment as soon as the row wraps.

#### 2b. Census table
`.card` with `flex:1; min-height:0; overflow:hidden; display:flex; flex-direction:column`; the table
well is `flex:1; min-height:0; overflow:auto`; the pagination row is the card's last child
(`flex:none`, same pattern as Import but page size **25**, label "1–25 of 162").

| Column | Width | Content |
|---|---|---|
| Column | 230px | column name, mono 12.5px. Sortable. |
| Table | 78px | source table (`unfall`/`objekt`/`person`), mono 11.5px, `--ink2`. Sortable. |
| Type hint | 96px | `date`/`integer`/`enum`/`time`/`text`, mono, `--ink2`. Sortable. |
| Populated | 180px | `.bar` (78×6px, background `--rule2`, radius 1px) with an `--ink3` fill at the fill-rate percentage, `gap:9px`, then a two-line readout: mono 11.5px percentage ("100 %", "99.4 %", "81.3 %") over mono 10.5px `--ink3` absolute record count ("4 978"). **Sorted descending by default** (`.sarr.on ▼`). |
| Distinct | 78px | distinct-value count, mono. Sortable. |
| Value distribution | 286px | an 8px-tall stacked bar (`display:flex; border-radius:1px; overflow:hidden; background:--rule2`, `max-width:230px`) whose segments are the top values, shaded from `--ink2` down through `oklch(0.70 / 0.80 / 0.88 0.005–0.008 260)`; below it a mono 10px `--ink3` legend of the top three ("2 · 62 %  1 · 26 %  3 · 9 %"), `margin-top:4px`. Long-tail columns render 24 equal alternating segments and the legend "long tail · 1 461 distinct, no value over 1 %". |
| action | 135px | mono 11px link "use as feature" → Features/FeatureConfig; or the static text "in config" in `--ink3` when the column is already configured. |

Row states: default; **already-in-config rows are highlighted** with `background:--accent-soft` and the
column name at `font-weight:500` (fixtures: `WitterungAusw`, `LichtverhaeltnisAusw`).
Census `.th`/`.td` use the wider `padding:0 12px 7px` / `8px 12px` (Import's tables were tightened to
9px because of their half-width columns — keep the 12px rhythm for full-width tables).

Fixture rows (in default sort order): UnfallDatumFeld date 100 % 4 978, 1 461 distinct (long tail) ·
AnzObjFeld integer 100 %, 7 · BeteiligtePersTotalFeld integer 100 %, 11 · UnfallTypAusw enum 99.4 %
4 948, 10 · StrassenzustandAusw enum 88.2 % 4 391, 6 · WitterungAusw enum 81.3 % 4 047, 8 *(in config)* ·
LichtverhaeltnisAusw enum 79.0 % 3 933, 5 *(in config)* · GeschwindigkeitssignalFeld integer 64.1 %
3 191, 9 · UnfallZeitFeld time … (162 columns total).

#### 2c. Two summary cards
`display:flex; gap:14px`, each `.card` `flex:1; padding:12px 14px`.
- **"Population profile · all tables"** (`.lbl`) — a wrapping row (`gap:18px; margin-top:8px`) of
  buckets, each a mono 15px weight-500 number + 12.5px `--ink2` label:
  21 / 100–80 %, 18 / 80–60 %, 22 / 60–40 %, 27 / 40–20 %, 31 / 20–0 %, 43 / empty.
- **"Reminder"** (`.lbl`) — 12.5px `--ink2`, `margin-top:6px`: "Empty means *no value provided* — not
  'not applicable'. Records with an empty cell leave that feature's denominator entirely (§8.6)."
  ("no value provided" in `<em>`.)

---

## Interactions & Behavior

**Navigation** — nav items are links; the active item is derived from the current route. The header title
and description change per view. No nested/secondary nav.

**Import**
- Per-file checkbox toggles inclusion. Deselected files stay listed but are excluded from the corpus;
  the header count ("9 files · 9 selected") and the "Create corpus · N records" button label both
  recompute live from the selection.
- Header-row checkbox = select all / none for that table (indeterminate when partially selected).
- Sorting: click File / Rows / State to sort; clicking the active column flips direction. Sort state is
  per-table and independent between the two tables.
- Pagination: page size selector (10 default) and prev/next; disabled arrows are greyed, not hidden.
- Clipboard icon opens the **file report modal** — per-file parse findings. *Not yet designed.* It should
  carry the actions removed from the row: re-parse, preview, remove, and the encoding/delimiter
  selectors; whether "Export report" lives inside it is still open.
- "Create corpus" freezes the selection into a new immutable corpus and adds a row to Corpora.
- Corpora rows: "Delete" only when no evaluation cites the corpus; otherwise the row shows the
  LOCKED pill and a non-interactive "delete blocked".

**Census**
- The three chips are dropdown filters over the same table; changing any of them refilters and resets to
  page 1. The table chip's count reflects the current filter.
- Sorting on Column / Table / Type hint / Populated / Distinct, two-direction, default Populated ▼.
- "use as feature" navigates to Features with that column preselected; already-configured columns show
  "in config" instead and their row is tinted.
- "Export CSV" exports the currently filtered, currently sorted table.

**Transitions / motion** — none designed. Keep it instrument-like: no entrance animation on tables;
at most a 100–150ms ease on hover/background colour changes.

**Loading / empty / error** — not designed. Suggested, consistent with the tone: skeleton rows at the
same row height inside the fixed-height well; empty state = single centred 12.5px `--ink2` line inside
the well; parse errors surface as the per-row State value plus the report modal, not as a toast.

**Responsive behaviour** — desktop-only tool; no mobile layout designed.
- The two Import file tables **stay side by side at every width** and never wrap. Because they use
  `table-layout:fixed`, the total never exceeds the card; the File column absorbs all shrinkage and
  ellipsizes below ≈1030px window width.
- The Census toolbar chips may wrap onto a second line; the Export CSV group stays right-aligned.
- Below ~900px the design has no defined behaviour — treat as out of scope or allow the content column
  to scroll horizontally.

## State Management
Per view, the minimum needed:

**Shell** — `currentRoute` (drives active nav item, header title + description).

**Import**
- `delivery: { structuredFiles: File[], textFiles: File[] }` where
  `File = { id, name, rows, state: 'ok'|'recovered'|'rejected', stateCount, encoding, delimiter, selected, isGroup?, groupCount? }`
- `sort` and `page` **per table** (`{ key: 'name'|'rows'|'state', dir: 'asc'|'desc' }`, `pageSize: 10`)
- `selectedRecordCount` — derived, feeds the Create-corpus button
- `reportModal: { open, fileId }`
- `corpora: Corpus[]` where
  `Corpus = { id, name, version, description, createdAt, records, languages: {de,fr,it}, canary, lockedBy: evalCount, devSized? }`, plus its own `sort`/`page`
- Data: fetch delivery manifest + parse results; POST to create a corpus; DELETE guarded by `lockedBy`.

**Census**
- `filters: { corpusId, minPopulated, table }`
- `sort: { key, dir }` default `{ populated, desc }`, `page`, `pageSize: 25`
- `columns: ColumnCensus[]` where
  `ColumnCensus = { name, table, typeHint, populatedPct, populatedCount, distinct, topValues: [{value, pct}], longTail: boolean, inConfig: boolean }`
- `profile: { buckets: [{label, count}] }` for the summary card
- Data: one census request per corpus + filter set; CSV export of the same query.

## Design Tokens
Colours are authored in **oklch**; hex equivalents are approximate — prefer the oklch values, or the
nearest tokens in the target design system.

| Token | Value | Approx. hex | Use |
|---|---|---|---|
| `--ink` | `oklch(0.22 0.012 260)` | #2c3038 | primary text |
| `--ink2` | `oklch(0.47 0.010 260)` | #6b7078 | secondary text |
| `--ink3` | `oklch(0.63 0.008 260)` | #979ba2 | tertiary text, labels, icons |
| `--rule` | `oklch(0.895 0.006 260)` | #dfe1e4 | borders, dividers |
| `--rule2` | `oklch(0.945 0.004 260)` | #eef0f1 | row dividers, track fills, nav hover |
| `--bg` | `oklch(0.976 0.004 95)` | #f9f8f5 | app background |
| `--surface` | `oklch(1 0 0)` | #ffffff | cards, header, nav |
| `--accent` | `oklch(0.50 0.008 260)` | #74797f | active nav, primary button, pill text |
| `--accent-soft` | `oklch(0.935 0.004 260)` | #e9eaec | active nav bg, highlighted row, pill bg |
| `--ok` | `oklch(0.50 0.11 152)` | #2b7a4b | "ok" state |
| `--warn` | `oklch(0.56 0.13 72)` | #97690f | recovered / cp1252 / dev-sized |
| `--warn-soft` | `oklch(0.965 0.035 80)` | #f9f2e4 | warn background |
| `--danger` | (Import only) rejected/delete red | — | rejected state, Delete action, canary 0 |
| distribution shades | `--ink2`, `oklch(0.70 0.008 260)`, `oklch(0.80 0.006 260)`, `oklch(0.88 0.005 260)` | — | stacked-bar segments, in rank order |
| info-note text | `oklch(0.38 0.10 255)` | #2f5aa0 | text on `--accent-soft` note |

**Typography** — IBM Plex Sans (`--sans`) and IBM Plex Mono (`--mono`), weights 400/500/600, loaded from
Google Fonts. Base body 13px / line-height 1.45, `-webkit-font-smoothing:antialiased`.
All identifiers, numbers, timestamps, counts and codes are **mono**; prose is sans.

| Role | Font | Size | Weight | Notes |
|---|---|---|---|---|
| view title (h1) | sans | 19px | 600 | letter-spacing −0.012em |
| brand | mono | 15px | 600 | letter-spacing −0.01em |
| summary metric | mono | 15px | 500 | |
| body / nav item / button | sans | 12.5px | 400 / 500 (button, active nav) | |
| caption, secondary cell | sans | 12px | 400 | `--ink2` |
| table cell | sans | 12.5px | 400 | mono 11.5–12.5px for identifiers |
| section label (`.lbl`) / table head (`.th`) | mono | 10px | 500 | uppercase, letter-spacing .09em / .07em, `--ink3` |
| chips, pagination, dropdowns | mono | 10.5–11px | 400–500 | |
| sort arrows | — | 9px | — | letter-spacing −1px |

**Spacing** — 2, 3, 4, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 22, 28px. Content column padding 20–28px
horizontal; card padding 12–14px; table cell padding 8px×9px (half-width tables) or 8px×12px
(full-width tables); card-to-card gap 14–16px.

**Radius** — 1px (bars/track fills), 2px (checkbox), 3px (everything else: cards, chips, buttons, pills).

**Borders** — 1px `--rule` for containers and header/footer rules; 1px `--rule2` for row dividers;
2px left border for the active nav item; 1px dashed `--rule` for the artboard-only WIREFRAME stamp.

**Shadows** — none anywhere. Elevation is expressed with borders only. (The report modal, when designed,
is the one place a scrim/shadow may be needed.)

**Fixed sizes worth keeping** — nav/brand column 196px; card header 46px; Import table well 404px
(10 rows + header); `.bar` 78×6px; distribution bar 8px tall, max-width 230px; icon buttons 22×22
(row action) and 24×24 (header add, pagination); checkbox 14×14; nav/toolbar icons 15×15, row icons 13px.

## Assets
No image assets. All icons are inline SVG on a 24×24 viewBox with `fill:none; stroke:currentColor`,
stroke-width 1.8 (nav/notes) or 1.9–2.2 (row actions, plus glyph) — they match the Lucide icon set
closely enough to substitute directly. Fonts: IBM Plex Sans + IBM Plex Mono from Google Fonts (weights
400, 500, 600). Sort arrows, carets and pagination chevrons are text glyphs (`▲ ▼ ▾ ‹ ›`) — replace with
real icons if the codebase has them.

## Files
Included in this bundle:
- `Import.dc.html` — Import view (also contains the shell + nav)
- `Census.dc.html` — Census view (also contains the shell + nav)
- `support.js` — the design-canvas runtime that renders these prototype files. **Not application code**,
  and nothing in it should be ported; it is included only so the two HTML files open and render locally.

Not included, handed off later: `Codelists.dc.html`, `FeatureConfig.dc.html`, `Evaluation.dc.html`,
`Main.dc.html` (Results), `Mismatches.dc.html`.

## Open questions for the team
1. The **file report modal** (clipboard icon) is not designed yet: it needs per-file parse findings plus
   the actions taken out of the row (re-parse, preview, remove, encoding/delimiter). Whether
   "Export report" lives there or at delivery level is undecided.
2. Loading, empty and error states are undefined for both views.
3. Behaviour below ~900px viewport width is undefined.

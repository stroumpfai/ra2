# MVP Specification — Road Accident Report Analysis (RA2)

Source document for the first implementation. Derived from [vision.md](vision.md)
(what and why) and [ra2.md](ra2.md) (stack and process). Where those disagree with
this file, this file wins for implementation purposes and the divergence should be
raised.

**Budget:** one month, implemented with Claude Code. Every requirement below is
either *needed to answer the PoC's question* or *cheap to capture now and expensive
to retrofit*. Nothing else is here.

**Governing rule, inherited from the vision:**

> **Capture everything from day one. Build views later.**

A deferred view costs a week. A field not captured costs a full re-run of the
corpus across every model — GPU time this month does not have.

---

## 1. Scope

### In

| # | Capability |
|---|---|
| F1 | Import N cantonal structured sets plus one shared text file into one immutable corpus |
| F2 | Column-population census over an imported corpus |
| F3 | Codelist import and label editing |
| F4 | Feature configuration: labelled (accident-level + derived aggregates) and exploratory |
| F5 | Evaluation setup: one corpus + one frozen feature config + N models |
| F6 | Extraction runs against a configurable local LLM endpoint |
| F7 | Goal 1 scoring: precision / recall / F1 per feature, per model, per language |
| F8 | Goal 2 presence flags with consistency checking (see §11.2) |
| F9 | Goal 3 discovery rates with evidence spans |
| F10 | Within-evaluation model ranking with confidence intervals and tie detection |
| F11 | Flat mismatch list with analyst tagging |
| F12 | Full run provenance and result export |

### Out (MVP)

Cross-evaluation comparison views (fingerprint still computed and stored) · scoring
of object/person-grain features (output still captured) · per-entity alignment ·
mismatch clustering, cross-model agreement scoring, unbiased contradiction sampling
· automatic hallucination triage · single-command installer and runbook · auth,
roles, multi-user · write-back to any source system · sketches or any image
modality · fine-tuning.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Corpus** | An immutable snapshot produced by one import. Has an id and a version. |
| **Record** | One accident: `unfall` row + its `objekt`/`person` rows + its narrative text. Keyed by `UnfallUid`. |
| **Feature** | One configured thing to extract. Either **labelled** (has ground truth) or **exploratory** (does not). |
| **Feature config** | An ordered set of features. Frozen when an evaluation's first run executes. |
| **Fingerprint** | Hash over a feature's full definition. Identity for cross-evaluation comparison. |
| **Evaluation** | one corpus + one feature config + N models. |
| **Run** | One model executed once over one evaluation. Immutable. |
| **Extraction** | One model's output for one (run, record). Immutable, stored raw and parsed. |
| **Labelled case** | A (record, feature) pair where the structured column is populated. The denominator for all Goal 1/2 metrics. |

---

## 3. Stack

Fixed by [ra2.md](ra2.md); restated so the implementation has one place to look.

- **Python 3.14**, **uv** (`uv sync --frozen`) — uv provisions the interpreter, so
  the system Python is not a constraint; **just** as the entire command surface
- **FastAPI** + **NiceGUI** mounted in the same process and port
- **SQLite (WAL)** + SQLAlchemy 2.0 async + **Alembic**
- **Ollama** reached through the **`openai` SDK** at `/v1`; base URL is an env var
- Structured output: Pydantic model → JSON Schema → Ollama `format:` (constrained
  decoding), wrapped by PydanticAI
- Jobs: `runs` table + in-process asyncio worker. No Redis, no Celery.
- ruff, mypy, pytest, pytest-cov, pre-commit, GitHub Actions

**Invariant:** one `LLMClient` protocol, and nothing else in the codebase imports
`openai` or `ollama`.

```python
class LLMClient(Protocol):
    async def extract(self, text: str, schema: type[T], model: str,
                      *, temperature: float, seed: int) -> Extraction[T]: ...
```

---

## 4. Input contract

### 4.1 Files

One delivery is **N cantonal sets of three structured files, plus one text file
covering all cantons**. All are imported into **one** corpus. **Nothing is ever read
from a filename** — canton and language come from the data.

| File | Key | Delimiter | Quoting | Header case |
|---|---|---|---|---|
| `unfall` | `UnfallUid` (PK) | `\|` | selective, type-inconsistent | mixed (`UnfallUid`) |
| `objekt` | `ObjektUid` (PK), `UnfallUid` (FK) | `\|` | selective | mixed |
| `person` | `PersonUid` (PK), `ObjektUid` (FK) | `\|` | selective | mixed |
| text *(one file, all cantons)* | `UNFALLUID` | `;` | RFC4180, `"` doubled | upper (`UNFALLUID`) |

The asymmetry matters: the single text file is the join target for every cantonal
set, so a `UnfallUid` collision between two cantons would silently attach one
canton's narrative to another canton's record. Uniqueness is verified across the
whole delivery, not per file (§4.3).

Delimiter, quote character and encoding are **per-file settings**, defaulted by
detection and overridable in the import UI. Column names are matched
**case-insensitively** and whitespace-trimmed.

`person` links to `objekt`, not to `unfall`: person→accident is a two-hop join, and
a pedestrian still has an object row.

Value formats: dates `YYYYMMDD` integers; times `"HH:MM"` strings; decimals with
`.`; empty string means **no value provided** (§8.6).

### 4.2 Parsing — strict first, recover second

1. Detect encoding per file (UTF-8 first, then Windows-1252). Show the analyst what
   was detected. **Fail the file on undecodable bytes** — never substitute `U+FFFD`.
2. Parse with a real RFC4180 parser using the file's delimiter and quote char.
3. For any row that fails to parse, or whose field count ≠ the header's, apply
   **key-anchored recovery**: `UnfallUid` is exactly 32 hex characters, so a line
   that does not begin with `^[0-9A-Fa-f]{32}<delim>` is a **continuation of the
   preceding record**, not a new row.
   - Two-column text file: this repairs embedded newlines unambiguously.
   - Wide structured tables: this **detects** a stray delimiter; repair is not
     attempted. The row is rejected.
4. Every recovered or rejected row is reported with its key in the import report.
   **Never silently repaired, never silently dropped.**

### 4.3 Import validation

Blocking (import fails):
- duplicate `UnfallUid`, `ObjektUid` or `PersonUid` across the whole delivery
- `objekt.UnfallUid` or `person.ObjektUid` with no parent
- header not matching the expected column set for that table

Reported but non-blocking (surfaced in the import report, stored on the corpus):
- rows recovered or rejected by §4.2
- `unfall.AnzObjFeld` ≠ count of child `objekt` rows
- `unfall.BeteiligtePersTotalFeld` ≠ count of `person` rows via `objekt`
- text rows with no matching `unfall` row, and `unfall` rows with no text
- per-file detected encoding

### 4.4 Encoding loss — one corpus-level check, nothing more

The delivered text has been through a lossy cp1252→Latin-1 conversion that
**deletes** characters (`œ Œ`, typographic quotes, dashes, ellipsis) rather than
substituting them, so decoding cannot detect it.

**The app does not attempt to measure it per record.** The source system runs no
spell or grammar check, so dropped characters and ordinary typos are
indistinguishable in the delivered text; any per-record "damage score" would be
counting typos with extra steps. Encoding loss is treated as part of the text's
general noisiness.

One check is kept because it is decisive rather than suggestive:

- **Corpus canary.** Count characters from the Windows-1252-only set
  (`œŒ''""–—…€™šžŠŽŸ‚„†‡‰‹›ˆ˜•`) across the whole corpus, once at import. **Zero,
  in a corpus containing French, proves the conversion happened.** Stored on the
  corpus and shown in the import report.

Its only purpose is to justify the upstream ask: **a re-export in UTF-8 before the
evaluation corpus is cut.** No per-record markers, no per-language damage rate.

Per-language comparison still carries the confound — French loses more characters
than German — but it **cannot be quantified**, so it is carried as a stated caveat
on per-language conclusions (§13), never as a correction or a column.

### 4.5 Language detection

Detected **per record** from the narrative, stored with a confidence score. Low
confidence is stored as `mixed`, not forced to a winner. Recommended library:
`lingua-py` (pure Python, no model download, strong on short text); swappable
behind a one-function seam. Language is **never** inferred from the source file.

---

## 5. Data model

SQLite. Immutable where marked. Alembic migration from the first commit.

```
corpus(id, name, imported_at, version, source_file_manifest_json,
       import_report_json, record_count, is_dev_sized, cp1252_canary_count)

record(id, corpus_id, unfall_uid, language, language_confidence,
       text_raw, text_anonymised_flag)
      -- text_raw stored verbatim, never normalised in place

unfall_row(record_id, column_name, value_raw)      -- long/EAV form, 67 cols
objekt_row(id, record_id, objekt_uid, obj_nr, ...) + objekt_cell(objekt_row_id, column_name, value_raw)
person_row(id, objekt_row_id, person_uid, pers_nr, ...) + person_cell(...)

codelist(id, corpus_id, source_column, code, label, label_language, edited_by_analyst)

feature_config(id, name, created_at, frozen_at)
feature(id, feature_config_id, ordinal, key, kind, description,
        grain, source_column, derivation_json, value_type,
        matching_rule, enum_codelist_json, fingerprint)

evaluation(id, name, corpus_id, feature_config_id, created_at, is_dev)
run(id, evaluation_id, model_name, model_digest, prompt_template_version,
    temperature, seed, started_at, finished_at, status,
    host_platform, gpu_name, llm_endpoint)

extraction(id, run_id, record_id, raw_output_text, parse_ok, parse_error,
           latency_ms, prompt_tokens, completion_tokens)     -- IMMUTABLE
extraction_value(extraction_id, feature_id, value_raw, value_normalised,
                 present_flag, evidence_span)
extraction_entity(extraction_id, entity_kind, entity_ref, attributes_json)
           -- per-entity output: captured, not scored in MVP

score(run_id, feature_id, language|NULL, metric, value, n, ci_low, ci_high)
mismatch(id, run_id, record_id, feature_id, record_value, extracted_value,
         evidence_span, analyst_tag, tagged_at, note)
```

**Never overwrite an extraction.** A re-run creates a new `run` and new
`extraction` rows. `run_id` is the discriminator everywhere.

---

## 6. Census (F2)

Runs over a corpus, needs no model and no GPU. Per table, per column:

- populated count and rate (populated = non-empty string)
- distinct value count
- top 20 values with frequencies
- inferred type hint (`Ausw`/`Feld` suffix, plus value-shape inspection)

Exportable as CSV. **This is the input to feature selection** — the vision's
sparsity finding means features are chosen by populated rate, not by what sounds
interesting. Deliverable in week one, before any extraction work.

---

## 7. Codelists (F3)

- Imported per `source_column`, supplying `code → label`.
- **Labels are editable in the configuration UI.** Rewriting `"M5"` as
  `manual, 5-speed gearbox` is prompt engineering, not cosmetics.
- If labels exist per language, all are stored; the prompt uses the configured
  prompt language.
- **The label text is hashed into the feature fingerprint** (§8.5). Two runs with
  identical codes and different labels asked the model different questions.
- A feature whose column has no codelist and whose type is `enum` **cannot be run**
  — hard validation error at evaluation setup, not a silent degradation.

---

## 8. Feature configuration (F4)

### 8.1 Kinds

- **labelled** — has a structured counterpart; Goals 1 and 2 apply
- **exploratory** — description only, no counterpart; Goal 3 applies; capped at
  **20**; never mixed into Goal 1/2 aggregates and never feeds the ranking

### 8.2 Grain — MVP admits scalars only

| Grain | MVP |
|---|---|
| Accident (`unfall` column) | **scored** |
| Derived aggregate (computed scalar from child rows) | **scored** |
| Object / person grain | **captured, not scored** |

Where a native `unfall` column already provides an aggregate (`AnzObjFeld`,
`BeteiligtePersTotalFeld`, the casualty counts), **the native column is always
preferred** over deriving the same number.

### 8.3 Derived aggregates — a closed catalogue

Not an expression language. A fixed, testable set, each parameterised and each
fully described by its `derivation_json`:

| Type | Parameters | Result |
|---|---|---|
| `count_objects` | optional filter `(column, op, value)` | integer |
| `count_persons` | optional filter | integer |
| `any_object_matches` | `(column, op, value)` | boolean |
| `any_person_matches` | `(column, op, value)` | boolean |
| `max_ordinal` | `(table, column, ordered_code_list)` | code |
| `min_ordinal` | `(table, column, ordered_code_list)` | code |
| `distinct_count` | `(table, column)` | integer |

Operators: `eq`, `ne`, `in`, `not_in`, `is_empty`, `is_not_empty`. Anything beyond
this catalogue is out of scope for the MVP.

### 8.4 Types and matching rules

| Type | Normalisation | Match |
|---|---|---|
| `enum` | none — codes compared | exact on code |
| `integer` | strip separators | exact |
| `decimal` | parse, round to configured precision | exact after rounding |
| `date` | `YYYYMMDD` → ISO date | exact |
| `time` | `HH:MM` → minutes since midnight | exact, optional ± tolerance |
| `boolean` | truthy mapping | exact |
| `free_text` | NFKC → casefold → collapse whitespace → strip edge punctuation | exact on the normalised string |

**Free-text matching is deliberately strict in the MVP.** Fuzzy thresholds and
LLM-as-judge are deferred (§16) — both need a threshold that can be defended, and
that decision wants real data. Accent-folding is a configurable normalisation step
worth evaluating, because it interacts with §4.4 damage.

### 8.5 Fingerprint

`sha256` over a canonical JSON serialisation of, in order:

`kind` · `grain` · `source_column` · `derivation_json` · `value_type` ·
`matching_rule` (incl. parameters such as rounding and tolerance) ·
`enum_codelist_json` **including label text** · `description`

Computed when the evaluation is created; stored on the feature. Cross-evaluation
views (post-MVP) join on this, never on the feature name.

### 8.6 Empty cells

Empty means **no value was provided** — the data cannot distinguish "not
applicable". Therefore: **a record whose column is empty is excluded from that
feature's denominator entirely**, for Goal 1 and Goal 2 alike. No label, no score,
no presence flag scored.

Consequence: every reported metric carries its **labelled-case count**, not just
the corpus size.

---

## 9. Evaluations and runs (F5, F6)

> **evaluation = one corpus + one feature config + N models**

- The feature config is **frozen when the first run executes**. Editing it
  afterwards is blocked; the UI offers "clone into a new evaluation" instead.
- Corpus and config do not vary inside an evaluation. Only the model does — which
  is what makes the ranking valid.
- A run over a corpus below the evaluation floor is marked **dev** and every view
  showing its numbers carries a visible "smoke test, not a result" marker.
  Thresholds: dev 20–50 records; evaluation ≥ 200 (up to 3000).

Every run stores: model name **and digest**, prompt template version, temperature,
seed, feature config id + fingerprints, corpus id + version, host platform, GPU
name, LLM endpoint, plus per-extraction latency and token counts.

Jobs run in the in-process asyncio worker, are restart-safe, and report progress
(records done / total, ETA) in the UI.

---

## 10. Extraction

### 10.1 Call shape

**One LLM call per (record, model)** covering all configured features. Rationale:
3000 records × M models is the wall-clock budget; one call per feature multiplies
it by F. Splitting into batches of features is a configuration option to fall back
on if adherence proves poor, and the batch composition is part of the prompt
template version.

### 10.2 Prompt

Assembled from a versioned on-disk template plus config. One multilingual prompt
for all inputs (no per-language routing in the MVP). It contains:

- the narrative text, verbatim
- per labelled feature: key, description, type, and for enums the **full
  code → label list** as the analyst edited it
- per exploratory attribute: key and the expert's description verbatim
- instructions: emit the **code** for enums; `null` when the text does not support
  a value; an **evidence span quoted verbatim from the text** for every non-null
  value; a **presence flag** per feature
- a request for **per-entity detail** (vehicles and persons, referenced by the role
  codes the anonymisation uses — `B1`, `G1`, `P`)

Template version is stored on every run and any edit bumps it.

### 10.3 Output schema

Pydantic → JSON Schema → constrained decoding. Shape:

```jsonc
{
  "features": {
    "<feature_key>": {
      "value": "<code|string|number|null>",
      "present": true,
      "evidence": "verbatim span from the text, or null"
    }
  },
  "entities": [
    { "kind": "vehicle", "ref": "G1", "attributes": { "...": "..." } },
    { "kind": "person",  "ref": "B1", "attributes": { "...": "..." } }
  ]
}
```

`entities` is **captured and stored, never scored** in the MVP. It is the cheap
capture that makes set matching and per-entity alignment possible later without
re-running the corpus.

### 10.4 Persistence

Store the **raw output string verbatim** alongside the parsed values, plus
`parse_ok` and any parse error. A parse failure is a recorded outcome, not a
retry-until-quiet — retries are bounded, counted, and visible.

---

## 11. Scoring

Denominator for every Goal 1/2 metric: **labelled cases** — records where the
feature's structured column is populated (§8.6).

### 11.1 Goal 1 — extraction

Per (run, feature) and per (run, feature, language), classify each labelled case:

| Outcome | Condition |
|---|---|
| **hit** | model value non-null and matches the record under the matching rule |
| **wrong** | model value non-null and does not match |
| **missing** | model value null |

```
precision = hit / (hit + wrong)          # of what it claimed, how much was right
recall    = hit / (hit + wrong + missing) # of what it should have found
F1        = 2·P·R / (P + R)
```

⚠️ **The vision lists a third error class, *hallucinated*, which the MVP cannot
compute.** Distinguishing a hallucination from a misread requires judging whether
the evidence span supports the value, and automatic triage is deferred (§16). In
the MVP, `hallucinated` is **not a metric**: it is one of the analyst's tags on the
mismatch list (§12), reported as a review tally. Reports must not present a
hallucination rate as if it were measured.

### 11.2 Goal 2 — presence

⚠️ **Resolution of an ambiguity in the vision.** Goal 2 asks for precision, recall,
F1 and accuracy on a binary presence classification — but there is **no independent
gold label for presence**. The record being populated says nothing about whether
the officer wrote it down; that gap *is* the finding Goal 2 exists to surface.
Deriving gold presence from Goal 1 correctness makes the metric circular.

The MVP therefore reports, per (run, feature) and per language:

- **presence rate** — share of labelled cases where the model flags the text as
  containing the feature
- **the Goal 1 × presence cross-tab** — hit / wrong / missing against
  present / absent
- **flag inconsistency rate** — cases where `present = false` but the model
  extracted a value that matched the record. This is self-contradiction and is
  automatically countable; it is a genuine quality signal on the flag.
- the actionable per-record output itself: *"this report does not say what the
  weather was"*

**Deferred:** true presence P/R/F1, which requires a human-labelled presence subset
(≈50 records × features). Spec'd as the first Goal 2 extension, not built now.

Goal 2 numbers are **never published without the corresponding Goal 1 numbers** —
a weak extractor manufactures false "missing" flags.

### 11.3 Goal 3 — exploratory

- **discovery rate** = share of records where a value is reported, plus the
  distribution of returned values
- every finding carries its **evidence span** — mandatory, no exceptions
- excluded from the model ranking and from every Goal 1/2 aggregate; reported in
  its own table
- discovery rates are **never compared between models as a quality signal**. A
  freely hallucinating model wins this metric.

### 11.4 Confidence intervals and suppression

- **Wilson score interval, 95%**, for every proportion (chosen for correct
  behaviour at small n and near 0/1, where the normal approximation fails).
- Every metric is rendered with its **n** and its interval.
- **Cells with n below the minimum count render as "insufficient data"**, never as
  a number. Default **20**, configurable per evaluation. *(Chosen default — the
  vision left this open at 10 or 20.)*

### 11.5 Ranking (Goal 4)

- Computed **within an evaluation only**, across runs that differ solely in model.
- Per labelled feature, and macro-averaged across labelled features.
- **Overlapping confidence intervals are rendered as a tie**, not as an order.
- Exploratory attributes take no part.
- Every cross-corpus number, if ever shown, carries its corpus label.

---

## 12. Mismatch review (F11)

Every `wrong` outcome produces a `mismatch` row: record value, extracted value,
evidence span, record key, feature, run.

- Presented as a **flat, sortable, exportable list**. No clustering, no cross-model
  agreement, no sampling workflow (§16).
- The analyst tags each reviewed case: **`hallucination`** · **`structured_data_error`**
  · **`unclear`**.
- **The tag never feeds back into a metric.** Nothing is rescored. Its output is a
  tally per feature: *"of 40 reviewed, 32 hallucination, 8 record error"*.
- **The structured record is fully authoritative in every case.** No adjudication
  step exists anywhere in the pipeline.

*(`unclear` is included because a real list will contain cases that are neither —
the model read the text correctly and the text genuinely disagrees with the record.
It costs nothing and answers the question from data.)*

---

## 13. UI surfaces

NiceGUI, single mode, no login, everything permitted.

1. **Import** — file pickers, per-file detected encoding/delimiter with override,
   dry-run preview, import report (§4.3, §4.4).
2. **Census** — per-column population table, sortable, exportable.
3. **Codelists** — per column, code/label table, inline label editing.
4. **Feature config** — add/edit features: kind, grain, column or derivation,
   type, matching rule, description; exploratory attributes with descriptions;
   validation errors surfaced (missing codelist, non-scalar grain).
5. **Evaluation** — pick corpus + config + models; dev/evaluation marking; launch;
   live progress.
6. **Results** — per-feature × per-model table with n, CI, tie marking; language
   breakdown carrying a **standing caveat** that encoding loss affects French more
   than German and cannot be quantified; Goal 3 in its own table; per-record
   drill-down showing text, extracted values, spans and the anonymisation marking.
7. **Mismatches** — the flat list with tagging and export.

**Required everywhere text is shown:** the per-record anonymisation marking.
**Required on every dev-sized result:** the "smoke test, not a result" marker.

---

## 14. Non-functional requirements

| # | Requirement |
|---|---|
| N1 | **No data leaves the host.** No external API, no telemetry, no crash reporting, no font/CDN fetches in the UI. |
| N2 | LLM endpoint is an **env var / config value** from the first commit. GPU passthrough is never assumed (fails on macOS). |
| N3 | Runs on **Windows and Linux**. macOS not required but not designed out: no POSIX-only paths, no shell-outs, explicit encodings on every file operation. |
| N4 | All file I/O specifies encoding explicitly. Never rely on the platform default. |
| N5 | Extractions are **immutable**; a re-run adds rows, never updates them. |
| N6 | Long runs are restart-safe and resumable; progress is visible. |
| N7 | The database is a single SQLite file under a configurable data directory. |

---

## 15. Testing

Per [ra2.md](ra2.md), five layers; the first four gate every commit.

1. **Unit** — parsing, recovery, normalisation, matching rules, fingerprinting,
   derived-aggregate evaluation, Wilson intervals.
2. **Fake-LLM integration** — full pipeline against `FakeLLMClient`, including
   malformed and schema-violating payloads.
3. **Cassettes** — real Ollama responses recorded once, replayed forever.
4. **UI** — NiceGUI `User` fixture, headless, in-process.
5. **Eval suite** — `tests/eval/`, 30–100 hand-labelled records behind
   `@pytest.mark.eval`, run against real Ollama, failing if accuracy drops more
   than N% below `evals/baseline.json`. Nightly CI + `just eval`.

**Fixtures must include the real hazards**, not clean data: mixed encodings, a
stray `|` in a wide row, an embedded newline in a narrative, an unmatched key, a
key duplicated **across two cantonal sets**, a record with every candidate column
empty, and French text with characters already lost upstream.

---

## 16. Explicitly deferred, with the reason

| Deferred | Why it is safe to defer | What must be captured now |
|---|---|---|
| Cross-evaluation views | Pure view over stored data | Fingerprint on every feature |
| Object/person-grain scoring | Set matching is a scoring view | `extraction_entity` rows |
| Per-entity alignment | Second extension; may become a join if role codes map to `ObjNr`/`PersNr` | Per-entity output with role refs |
| Mismatch clustering, cross-model agreement, unbiased sampling | Ordering is a view | Mismatch rows with spans |
| Automatic hallucination triage | Needs a defensible fuzzy threshold; wants real span data | Evidence spans |
| Presence P/R/F1 | Needs a human-labelled subset | Presence flags on every extraction |
| Fuzzy / LLM-judge free-text matching | Same threshold decision | Raw + normalised values |
| Installer, runbook | Needed for handover, not for the answer | — |

---

## 17. Decisions taken in this spec

Defaults chosen where the vision left a gap. Each is cheap to change; none should
be changed silently.

| # | Decision | Basis |
|---|---|---|
| D1 | `hallucinated` is a review tag, not a computed metric | It is not computable without span adjudication (§11.1) |
| D2 | Goal 2 reports presence rate + cross-tab + inconsistency rate; P/R/F1 deferred | No independent gold label exists (§11.2) |
| D3 | Minimum cell count = **20** | Vision left 10 vs 20 open; 20 keeps a Wilson interval usable |
| D4 | Wilson score interval, 95% | Correct at small n and near 0/1 |
| D5 | One LLM call per record, all features | Wall-clock GPU budget |
| D6 | Free-text matching = normalised exact, no fuzzy | Threshold decision deferred (§16) |
| D7 | Derived aggregates = closed catalogue of 7 types | An expression language does not fit the month |
| D8 | `unclear` added as a third mismatch tag | Real lists contain cases that are neither |
| D9 | `lingua-py` for language detection | Local, no model download, good on short text |
| D10 | EAV storage for the 67/77/18 wide columns | Feature config selects arbitrary columns; avoids 3 migrations per config change |
| D11 | Encoding loss measured once per corpus, not per record | Indistinguishable from typos; no spell check upstream (§4.4) |

---

## 18. Blocking dependencies — not ours to build

| # | Dependency | Blocks |
|---|---|---|
| B1 | **VUM codelists** | Every enum feature. Goal 1 cannot be prompted without them. |
| B2 | **GPU model and VRAM confirmed** | Which models are testable at all |
| B3 | **Air-gap status** | Whether weights must be side-loaded; changes setup entirely |
| B4 | Real delivery files (not samples) | Import hardening, census |

Open questions carried from the vision, none blocking the first commit: codelist
label language · output language for normalised free text · `UnfHergangTextAnonym`
exact semantics · whether role codes (`B1`, `G1`, `P`) map to `ObjNr`/`PersNr` ·
whether escaping in the text file is guaranteed or incidental · whether a UTF-8
re-export upstream is possible.

---

## 19. Acceptance criteria

The MVP is done when, on the target machine:

1. A real delivery — N cantonal structured sets plus the single shared text file —
   imports into one corpus, with an import report naming every recovered row,
   rejected row, count mismatch, detected encoding and the cp1252 canary count.
2. The census exports a per-column population table for all three structured tables.
3. Codelists import, labels are editable, and an edit changes the affected
   features' fingerprints.
4. A feature config with ≥1 native accident-level feature, ≥1 derived aggregate and
   ≥1 exploratory attribute validates and freezes on first run.
5. An evaluation runs ≥200 records across ≥2 models against a local endpoint, with
   visible progress, and survives a restart mid-run.
6. Results show per-feature × per-model precision/recall/F1 with n and Wilson
   intervals, cells below 20 suppressed, ties rendered as ties, a language
   breakdown carrying the encoding caveat, and Goal 3 in a separate table.
7. The mismatch list is browsable, taggable and exportable, with evidence spans.
8. Every run's record alone is sufficient to reproduce it: model + digest, prompt
   version, temperature, seed, config fingerprints, corpus version.
9. A dev-sized run is visibly marked as a smoke test wherever its numbers appear.
10. No network egress occurs beyond the configured LLM endpoint.

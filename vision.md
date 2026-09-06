# Vision — Road Accident Report Analysis (RA2)

Proof of concept: can local LLMs extract structured features from police accident
reports, and flag reports where key information is missing?

---

## Context

Police record road accidents in a centralised system through a structured form and
a free-text field. The text describes the sequence of events, the vehicles and the
parties involved in that particular accident. The structured data and the text
overlap in information — more or less, depending on how much detail and care went
into the text.

Crucially, **the two are captured independently**: the structured form is filled in
on its own and passes a quality and plausibilisation check. It is not derived from
the free text. This is what makes the structured data usable as ground truth.

Three properties of the text drive most of the difficulty:

- **Multilingual.** All cantons are imported into one corpus, so reports arrive in
  German, French and Italian (Romansh possible but rare), and a single report may
  mix them. Language is a property of the record, derived per report and never
  inferred from which canton's file it arrived in.
- **Unchecked.** No grammar or spell check runs in the source system. Expect
  abbreviations, jargon, telegraphic style and typos — and, mixed in with them,
  characters lost to an upstream encoding conversion (see *Encoding loss*). These
  are not separable: `manuvre` may be a dropped `œ` or a plain typo, and nothing in
  the data says which. Treat the text as noisy by nature rather than as damaged in
  a measurable way.
- **Variable in quality.** Length and completeness vary widely between officers.
  This variability is not noise to be tolerated — measuring it is Goal 2.

The structured data and the text input are both classified sensitive. They must
remain on the same machine for any processing: no external API, no data leaving the
host, no telemetry.

### Input

The structured data arrives as **three pipe-delimited tables** (VUM export, one set
of files per canton), in a proper relational shape rather than flattened columns:

```
unfall   (UnfallUid PK)                      — 67 cols, accident level
  └─< objekt (ObjektUid PK, UnfallUid FK)    — 77 cols, one row per vehicle/object
        └─< person (PersonUid PK, ObjektUid FK) — 18 cols, one row per person
```

Two things about that shape are load-bearing. **Person hangs off *objekt*, not off
the accident** — so person-to-accident is a two-hop join, and a pedestrian still
needs an object row. And the accident row carries its own counts (`AnzObjFeld`,
`BeteiligtePersTotalFeld`), which give every import a free integrity check against
the number of child rows actually present.

The free text arrives as a **fourth file** (`UNFALLUID;HERGANG`), keyed on
`UnfallUid`. Features may be configured from the columns of all three structured
tables — subject to the grain rules below. Only **final-state records** are
delivered; no status filtering is needed on import.

**The delivery is asymmetric.** Each canton writes its own `unfall`, `objekt` and
`person` files, but the free text arrives as **a single file covering all
cantons**. So an import takes *N* structured sets and *one* text file, and the text
file is the join target for all of them. Nothing is ever read from a filename:
canton, language and every other attribute come from the record. `UnfallUid` is a
32-character hex key and is assumed globally unique across cantons — which the
importer verifies rather than trusts, since the single text file makes a collision
between two cantons silently destructive.

Format differs *between* files, so it is configured or detected **per file, never
globally**:

| | Structured tables | Text file |
|---|---|---|
| Extension | `.txt` | `.csv` |
| Delimiter | `\|` | `;` |
| Quoting | selective, type-inconsistent (`"5432"` quoted, `61.80` bare) | RFC4180 — quoted only when needed, `"` doubled inside |
| Header case | `UnfallUid` | `UNFALLUID` |

Column names are matched **case-insensitively** as a result. Dates are `YYYYMMDD`
integers, times `"HH:MM"` strings.

#### Import is the risky part, and it is hostile by design

Two properties of the delivery make a naive parser wrong:

- **Encoding varies and cannot be assumed.** Files are opened and saved on
  different devices on the way here, so UTF-8 and Windows-1252 will both appear —
  possibly within one delivery. The importer detects per file, shows the analyst
  what it detected, and **fails loudly on undecodable bytes rather than silently
  substituting replacement characters**. A mangled umlaut is a corrupted label that
  nobody notices until the metrics are wrong.
- **Escaping cannot be assumed.** The text sample *does* use proper RFC4180
  quoting (`""P""` inside a quoted field), but the structured tables do not appear
  to escape anything. So a stray `|`, `"` or newline must never be allowed to
  silently shift a row's columns.

The approach follows from that: **parse strictly first, recover second.** Run a
real RFC4180 parser with the file's delimiter; where a row fails or its field count
disagrees with the header, fall back on the key. `UnfallUid` is 32 hex characters,
so a line that does not begin with 32 hex characters followed by the delimiter is a
continuation of the preceding record, not a new one — which repairs embedded
newlines unambiguously in the two-column text file, and detects (though it cannot
always repair) a stray delimiter in the wide structured tables.

Every recovered or rejected row is reported to the analyst with its key — never
fixed silently, and never dropped silently.

#### Encoding loss

The sample text contains `manuvre` where the word is `manœuvre`. Every non-ASCII
character present (`à ä è é î ü`) falls inside ISO-8859-1 and **not one
Windows-1252-only character appears** — the signature of a cp1252 → Latin-1
conversion upstream, which deletes `œ Œ`, typographic quotes, dashes and the
ellipsis rather than substituting them.

**This is not separately measurable, and the app does not try.** The source system
runs no spell or grammar check, so a corpus of typos and a corpus of dropped
characters look identical from here; any per-record "damage" score would be
counting typos with extra steps. Encoding loss is simply part of *Unchecked*.

One cheap corpus-level check is worth keeping, because it is decisive rather than
suggestive: **count Windows-1252-only characters across the whole corpus. Zero, in
a corpus containing French, proves the conversion happened.** That is one number,
computed once at import, and its only purpose is to justify the ask — **a re-export
in UTF-8, upstream, before the evaluation corpus is cut.**

⚠️ These files must not be round-tripped through Excel. It rewrites `YYYYMMDD`
integers as dates, re-guesses encodings and re-quotes fields, and the damage is
invisible until scoring. One for the runbook.

**Corpus sizes serve two different purposes:**

- **20–50 records** — development and base testing. Small enough to iterate on
  quickly, and never used to draw conclusions about models.
- **≥ 200 records, up to 3000** — evaluation runs. Every reported metric comes from
  this range.

The distinction matters enough that the app should make it visible: a run over a
development-sized corpus is a smoke test, not a result.

---

## Goals

A PoC application running local LLMs should enable an evaluation of:

### Goal 1 — Feature extraction

Extract a configured set of features from the free text and measure extraction
quality against the structured record.

### Goal 2 — Quality assessment of the text input

For each configured feature, decide whether the free text contains it. Output is a
**presence flag per feature**, not a global score — the same shape as Goal 1, and
directly actionable ("this report doesn't say what the weather was").

Generated natural-language feedback for the officer is out of scope for this phase
(see Non-goals).

### Goal 3 — Exploratory attribute discovery

Test attributes that are **not** in the structured data, to find out whether the
free text carries information the form does not capture today. The metric is
**found / not found** — there is no label and no structured counterpart to check
against.

Candidates are **supplied by a domain expert and capped at 20**. They are not
discovered by the app, and the list is fixed for an evaluation like any other part
of the feature configuration.

That bound is what makes the goal tractable: at most 20 attributes means the entire
exploratory output fits in one table a human can actually read, and a review of a
sample of findings per attribute is a few hours of expert time rather than a
project of its own.

Each candidate arrives with a written description from the expert, and that
description goes straight into the prompt. It is therefore load-bearing: a vague
description ("driver behaviour") produces findings nobody can interpret, while a
sharp one ("an explicit mention that a driver was using a phone") produces a
reviewable claim. Sharpening the 20 descriptions is expert work that has to happen
before the first run, not after a disappointing one.

This goal answers a different question from Goals 1 and 2. Those ask *"how well
does a model read the text?"*. This one asks *"what else is in the text?"* — a
screening question, whose output is a candidate list for humans to judge, not a
score. It is measured, ranked and reported separately throughout (see Metrics).

### Goal 4 — Model comparison

Evaluate several local models under identical conditions and **rank** them per
model and per feature. Every evaluation run must be documented with all its
variables (see Reproducibility).

---

## Configuration — the feature set is not hard-coded

The features to extract are **defined as configuration**, by marking or listing
columns from the three structured tables. Enum value sets are likewise associated
to a feature through configuration.

The `Feld` / `Ausw` suffix convention in the source (`Ausw` = *Auswahl*, a codelist
field) is a useful default when typing a feature, but **not a reliable one**:
`UnfallStatus`, `ObjektArt` and `FahrzArtGetriebe` carry no suffix yet are plainly
coded, and `Ausw` values are numeric in some columns and alphanumeric in others.
The app suggests, the analyst overrides.

Coded values are **opaque internal codes** (`KantonAusw=380`, `FahrzArtGetriebe="M5"`).
A code→label dictionary is therefore not a nicety: without it a model cannot be
told what to extract, and results cannot be read.

**Codelists are imported and edited inside attribute configuration.** They are
supplied with the data, but the analyst can edit the labels — and that is not a
cosmetic feature, because *the label is what goes into the prompt*. Rewriting
`"M5"` as `manual, 5-speed` is prompt engineering, performed in the configuration
UI. Which has one hard consequence:

> **The code→label text is part of the feature definition and is hashed into the
> fingerprint**, not just the set of codes. Two runs with identical codes and
> different labels asked the model different questions and are not comparable.

Two kinds of feature exist, and the distinction runs through the whole app:

- **Labelled features** — mapped to a column of the structured data, which supplies
  the ground truth. Goals 1 and 2 apply.
- **Exploratory attributes** — defined by description only, with no structured
  counterpart and therefore no label. Goal 3 applies. These are never mixed into
  Goal 1 or Goal 2 metrics, and never feed the model ranking.

This is the load-bearing design decision in the whole PoC, and it has three
consequences worth stating plainly:

1. **Ground truth is automatic for labelled features.** Each maps to a CSV
   column, so it already has its label. There is no annotation step and no
   coverage gap. Exploratory attributes have no ground truth by definition —
   that is what makes them exploratory, and what limits what can be said about
   them.
2. **The configuration *is* the experiment.** It is recorded with every run,
   exactly like the model name and prompt version, and it scopes what the run's
   numbers mean. Two runs with different feature configs are not comparable.
3. **Data analysts will edit it, in the app.** Selecting attributes and defining
   enum values needs to be doable in the UI, not in a YAML file — and a config
   change must be an obvious, recorded event rather than a silent one.

Each configured feature carries:

- its kind: **labelled** (mapped to a structured CSV column) or **exploratory**
  (no counterpart)
- for labelled features: the source column it maps to, or — for a derived
  aggregate — the derivation rule that produces it
- a type: enum, date/time, number, or free text
- for enums: the allowed values, and how the model should be told about them
- a **matching rule** for scoring (see Metrics)
- a human-readable description, used in the prompt

### Feature grain — accident level only, for now

The three-table shape creates three possible grains for a feature, and they are not
equally scorable:

| Grain | Example | Cardinality per accident |
|---|---|---|
| Accident | weather, light conditions, speed limit | one value |
| Object | vehicle type, impact point, cause | N values |
| Person | injury severity, protective system, age | N values |

Only the first is a scalar, and every matching rule in this document assumes a
scalar. Scoring an object- or person-level feature means either comparing *sets*
(`{car, bicycle}` against `{car, bicycle}`, ignoring which is which) or making the
model align its "vehicle 1" with the record's `ObjNr 1` — and that alignment is a
research problem, because the record's ordering is arbitrary relative to the
narrative.

**The MVP therefore admits two kinds of feature, both scalar:**

1. **Native accident-level columns** — a column of `unfall`, used directly. No
   derivation, nothing to get wrong.
2. **Derived aggregates** — a scalar computed by the app from the child rows:
   *number of vehicles involved*, *was a bicycle involved*, *was a pedestrian
   involved*, *most severe injury*. Some of these already exist as native columns
   (`AnzObjFeld`, `BeteiligtePersTotalFeld`, the casualty counts), and **where a
   native column exists it is always preferred** — a column that is already there
   cannot be derived wrongly.

**Per-entity is the destination, not a discarded option.** The expert wants
*"vehicle 1 was a car, vehicle 2 a bicycle"* — the MVP simply does not score it
yet. Deferred in order: set matching over object- and person-level features first,
then per-entity aligned matching.

That changes what the MVP must *capture*, by the same rule that governs everything
else here (see *Timeline and scope*): **the model is prompted for per-entity detail
and its raw per-entity output is stored, even though only the aggregate is
scored.** Scoring is a view and can be added in a week; re-running the corpus
across every model to recover per-vehicle output cannot.

One consequence for the fingerprint: a derived feature's **derivation rule is part
of its definition**, so it is hashed alongside kind, column, type, enum values and
matching rule. Two evaluations that count "vehicles involved" differently are not
comparing the same feature.

### Attribute selection is set per evaluation

The feature configuration is chosen when an evaluation is set up, and fixed for its
duration. That gives a clean unit of work:

> **An evaluation = one corpus + one feature configuration + N models.**

Models vary *inside* an evaluation; the corpus and the configuration do not. Model
ranking is therefore always computed where it is valid — between runs that differ
only in the model.

Two rules follow, and the app should enforce rather than document them:

- **The configuration is part of the evaluation's identity**, stored with it and
  immutable once the first run has executed. Editing the feature set means starting
  a new evaluation, not amending this one.
- **Comparison across evaluations is allowed, per feature, only where the feature
  definition is identical.** Not merely the same column — the same *definition*:
  same kind, same source column, same type, same enum value set, same matching
  rule. A feature whose enum gained or lost a value is a different feature, and its
  scores from before and after the change do not belong in the same table.

The practical mechanism is a **definition fingerprint** per feature — a hash over
kind, source column, type, enum values and matching rule, computed when the
evaluation is created. Cross-evaluation views join on the fingerprint, not on the attribute
name. Features present in both evaluations but with differing fingerprints are
shown as excluded, with the reason, rather than silently dropped: "changed enum
values" is itself information the operator wants.

⚠️ Matching fingerprints make *feature definitions* comparable — they do not make
*corpora* comparable. Model A scored on one corpus and model B on another is not a
model comparison, however identical the feature. Cross-evaluation tables must show
the corpus alongside every number, and model ranking stays a within-evaluation
operation.

---

## Metrics

Terminology matters here, because the three analysis goals need different
measures — and Goal 3's are not scores at all.

**Goal 1 (extraction)** — per feature: **precision, recall, F1**, plus the error
breakdown that tells you *why* a score is low:

- *missing* — the value is in the text, the model didn't extract it
- *wrong* — extracted, but the value doesn't match the record
- *hallucinated* — extracted a value that isn't supported by the text

A *wrong* value is not automatically a model error: the text may genuinely say
something the record does not (see Data & ground truth). Scoring does not
distinguish the two — the structured record is authoritative either way — but every
mismatch carries the model's evidence span, so an analyst can tell the two apart on
review (see Data & ground truth). That review is manual and does not change the
score.

A **matching rule** per feature type, configured alongside the feature. All of them
compare scalars, which is exactly why the MVP admits only accident-level and
derived-aggregate features (see *Feature grain*):

- enums → exact match on the configured value
- dates/times/numbers → exact, after normalisation
- free text → normalised string match, with [TODO: decide — fuzzy match threshold,
  or an LLM-as-judge pass?]

**Goal 2 (presence)** — binary classification per feature: **precision, recall, F1
and accuracy**, macro-averaged across features.

**Reported per language as well as overall.** The breakdown is free once the
language of each report is recorded, and a model that is strong in one language and
weak in another is a finding, not a footnote.

### Goal 3 (exploratory) — a discovery rate, not a score

With no label, the only thing that can be counted is how often the model claims to
find the attribute: a **discovery rate** — the share of documents where it reports
a value — plus the distribution of values it returns.

That number is not a quality measure, and treating it as one inverts the ranking.
For a labelled feature, finding more is better. For an exploratory attribute, a
high discovery rate is ambiguous: it means either the information really is in the
text, or the model is inventing it. **A model that hallucinates freely wins this
metric.** So:

- Exploratory attributes are **excluded from the model ranking** and from all Goal
  1 / Goal 2 aggregates. They are reported in their own table.
- Discovery rates are **never compared between models** as a quality signal. Wide
  disagreement between models on the same attribute is a flag for human review, not
  a verdict on either model.

**Every exploratory finding must carry its evidence.** The output is the extracted
value *plus the supporting span or quotation from the source text*. This is the
single design decision that makes the goal worth pursuing: with evidence attached,
a human can review a sample of found instances in minutes and turn an
uninterpretable discovery rate into a real precision estimate. Without it, the
result is a number nobody can act on.

The useful reading of the output is a **screening signal**: an attribute found in
3% of reports is probably not worth adding to the form; one found in 78% with
plausible evidence is worth a serious look. The deliverable of Goal 3 is a ranked
candidate list for human judgement, not a metric.

**Review is by the expert who proposed the attribute** — they are the only person
who can say whether a finding is real. With the list capped at 20, a sample of
10–20 found instances per attribute is enough to screen with, and the whole review
stays within a day's work.

[TODO: confirm the sample size per attribute. 10 is a floor; below that the
precision estimate stops being worth stating.]

### Sample size and confidence intervals

Evaluation runs use at least 200 records, which puts overall per-feature scores on
solid footing. The exposure is in the **breakdowns**: 200 records split across
languages, or across the values of an enum, leaves individual cells small enough
that a difference between two models can be noise. Rare enum values may appear only
a handful of times.

So: every reported metric carries its sample size and a confidence interval, and
the model ranking shows where models are statistically indistinguishable rather
than implying a strict order. Cells below a minimum count are reported as
"insufficient data" rather than as a number.

[TODO: set that minimum cell count — 10? 20? — before the first evaluation run.]

Exploratory discovery rates need the same treatment: a rate over 200 documents is
stable enough to screen with, a rate over 20 is not.

---

## Data & ground truth

**A structured CSV record referencing a text input is the label.** The structured data is
captured independently of the text and passes its own quality and plausibilisation
check, so there is no circularity: agreement between model output and structured
record is genuine signal, not an artefact of one being copied from the other.

One residual subtlety, and it is Goal 2's entire subject rather than a problem: the
form may legitimately record something the officer never wrote down. A populated
field plus an absent mention is not a labelling error — it *is* the finding.

**Goal 2's definition** follows directly: *field populated in the structured
record + not
recoverable from the text = the text is missing it*. This is clean on the label
side, but it leans on the Goal 1 extractor being correct. Goal 2's metrics are
therefore conditional on Goal 1's, and both must be reported together — a weak
extractor produces false "missing" flags.

### Ground truth is only as dense as the record

A label exists only where the column is populated, so **sparsity caps the usable
corpus per feature**, independently of corpus size. A feature populated in 30% of
200 records yields 60 labelled cases — already too thin for the per-language
breakdown this document promises.

The single sample record examined so far shows a worrying pattern: the populated
fields were the system-filled ones (registry, geo reference, vehicle data, counts),
while every human-coded field was empty — accident type, main cause, weather,
light, road surface and condition, right of way, injury severity, causes. **That
empty list is close to the candidate feature set for the whole PoC.**

One row proves nothing about a corpus. But the benign explanation is gone: only
final-state records are delivered, so this is not a half-filled draft. Either the
pattern is an artefact of one accident, or the ground truth this PoC depends on is
thin — and which one it is has to be known before anything is built.

**Feature selection is therefore driven by a column-population census over the real
corpus, not by what sounds interesting** (see *Timeline and scope*). If the census
comes back bad, that is a finding about the data worth reporting on its own, and it
is far cheaper to learn in week one than in week four.

**Empty means no value was provided — nothing more.** The data does not distinguish
"not applicable" from "not recorded": `AutobBezFeld` is empty because the accident
was off-motorway, `Witter0Ausw` because nobody coded it, and both look identical.
The consequence is mechanical rather than difficult: **a record with an empty
column is excluded from that feature's denominator entirely**, for Goal 1 and Goal
2 alike. No label, no score, no "missing from text" flag.

What that costs is statistical power, and it is why the census is load-bearing —
every reported metric therefore carries the number of labelled cases behind it, not
just the corpus size. It also means a low populated rate is itself ambiguous: a
column may be sparse because the situation is rare, or because officers skip it.
Only the expert can say which, and only per column.

### Contradictions between text and record

Independent capture guarantees this happens: the text will sometimes state
something the record disagrees with. This is expected, not a data fault.

**The structured record is fully authoritative — without exception.** It is the
label in every case. A mismatch never changes a score, never corrects a label, and
there is no adjudication step anywhere in the pipeline. This is a deliberate
simplification for the first version: it keeps scoring mechanical and keeps
judgement out of the metrics.

**Resolution is manual and out of band.** Every mismatch is listed with the record
value, the extracted value, and the **evidence span** from the text — spans are
therefore mandatory for labelled features too, not only for Goal 3, though only on
mismatch. An analyst reads the list and tags each case:

- **hallucination** — the model produced a value the text does not support
- **structured-data error** — the record is wrong and the text is right

The tag is a note against the mismatch. It does not feed back into the metrics, no
run is rescored, and nothing is recomputed. Its value is the tally: *"of 40
reviewed mismatches on weather, 32 were hallucinations and 8 were record errors"*
says something useful about both the model and the data, and costs an afternoon
rather than a workstream.

Two things follow:

- **A high mismatch rate is ambiguous until someone reads the list.** Weak
  extractor, or a field the record gets wrong? Publishing the rate without the
  review invites the wrong conclusion.
- **Evidence spans cannot be retrofitted.** They are captured from day one even
  before any review workflow exists (see *Timeline and scope*) — recovering them
  later means re-running the corpus across every model.

Deliberately **not** in the first version: clustering mismatches by value pair,
cross-model agreement scoring, sampling for an unbiased contradiction rate, and any
attempt to triage hallucination from misread automatically. A flat, exportable list
is enough to start. Revisit when a real list exists and turns out to be too long to
read.

**Exploratory attributes have no ground truth, by construction.** Nothing in the
structured data can confirm or refute them, and no amount of processing changes
that. The only route to a trustworthy number is human review of a sample, which is
why evidence spans are mandatory for this goal (see Metrics).

**Real data.** The PoC processes real records. The app must display a **marking of
whether the text input is anonymised**, visible wherever text is shown and stored
with the record, so an analyst is never unsure what they are looking at. The
marking is **per record and read from the source data** — `UnfHergangTextAnonym` on
the accident row. [TODO: confirm the flag's exact semantics — "an anonymised text
exists" versus "this text has been anonymised".]

**Anonymisation replaces parties with role codes**, not with blanks: the samples
carry `"P"` in French and `B1` / `G1` in German. The text therefore keeps a
*consistent internal reference* to each party — which is more than a privacy
detail. If those codes correspond to `ObjNrFeld` / `PersNrFeld` in the structured
tables, the per-entity alignment deferred in *Feature grain* stops being a research
problem and becomes a join. That is worth confirming early, because it changes how
expensive the second extension is.

**The structured record is not anonymised, and the joined pair is identifying.**
Birth date, postcode, town, LV95 coordinates, street, vehicle make, model, colour
and insurer identify a person regardless of what was scrubbed from the narrative.
This risk is **understood and accepted**: the app runs locally, no data leaves the
host, and the analysts handling it are under NDA. It is recorded here so that the
acceptance is explicit rather than assumed, and so that nobody later mistakes the
anonymisation marking for a statement about the record.

---

## Language handling

One multilingual prompt for all inputs, extracted values normalised to a single
output language: [TODO: which? German is the likely default, but it is a reporting
decision, not a technical one]. Enum values are emitted as the configured codes
rather than free text, so the output language question only really applies to
free-text features.

⚠️ Per-language comparison carries a confound that cannot be quantified: the
upstream encoding conversion (see *Encoding loss*) drops characters that are more
common in French than in German, so French input may simply be noisier. There is no
way to measure how much, so it is carried as a **stated caveat on every
per-language conclusion**, not as a correction or a column.

Rationale: it is the simplest pipeline, it is the only approach that survives
genuinely mixed-language reports, and it tests what we actually want to know —
whether a local model can handle this corpus as it is. Per-language prompt routing
and translate-then-extract are recorded as fallbacks if the per-language metrics
show one language is dramatically worse.

---

## Success criteria

The PoC succeeds if it produces a defensible answer, not necessarily a positive
one. Concretely, it must deliver:

- Per-feature, per-model, per-language metrics for Goals 1 and 2, with sample
  sizes and confidence intervals.
- A **ranking of models per labelled feature**, showing which differences are
  meaningful and which are within noise. Exploratory attributes take no part in
  this ranking.
- For Goal 3: the ≤20 expert-supplied attributes with their discovery rates and
  reviewed evidence samples, ordered as a shortlist for human judgement.
- A **mismatch list per labelled feature** — record value, extracted value,
  evidence span — with the analyst's hallucination / structured-data-error tally
  for the cases reviewed.
- A recommendation: which model, at what quality, on what hardware.

No baseline comparison is required — the question is which model ranks best, not
whether LLMs beat a rule-based approach.

⚠️ A ranking answers *"which model is best"* but not *"is the best one good
enough"*. If a deployment decision follows this PoC, someone still has to name a
quality bar. Recording that as an explicit follow-up rather than a gap.

---

## Non-goals

- Not a production system. No integration with the records system, no write-back.
- No fine-tuning or training. Prompting, configuration and model selection only.
- No baseline / rule-based comparator.
- No generated feedback text for officers (Goal 2 stops at presence flags).
- No claim of *correctness* for exploratory attributes — Goal 3 screens, it does
  not validate.
- No automatic proposal or discovery of exploratory attributes. The candidate list
  comes from a domain expert and is capped at 20.
- No multi-user deployment, no authentication, no role model, no audit of *who*
  did what. Single user group: data analysts. If access control is ever needed,
  it is a later phase — but nothing should be designed that makes adding it
  impossible.
- Not a replacement for the structured form.

---

## Environment

- **Windows and Linux are required. macOS is not required yet, but must not be
  designed out.** Concretely, that means: no Linux-only assumptions, path and
  encoding handling that survives Windows, and — the one that is expensive to
  retrofit — **the LLM endpoint as a configuration value from day one**. GPU access
  differs on every platform, and GPU passthrough into a container does not work on
  macOS at all (see [ra2.md](ra2.md)), so a Mac deployment will need the model
  server running on the host. That is a config line if the seam exists and a
  rewrite if it does not.
- **Hardware:** a machine with a dedicated GPU. [TODO: model and VRAM — the hard
  constraint on which models are even testable.]
- **Network:** [TODO: is the machine air-gapped? If yes, model weights must be
  side-loaded, which changes the setup procedure entirely.]
- **Runtime:** Python, running locally.
- **Development:** AI-assisted coding (Claude).
- **Users:** data analysts, and for this phase nobody else. **One user group, no
  roles, no logins, no per-user state.** The app has a single mode in which
  everything is permitted; whoever opens it can import, configure, run and read.
  Attribute selection, running evaluations and interpreting the ranking are not
  separated by permission — they are separated, if at all, by who happens to do
  them.
- **Operation:** an analyst must be able to install the app, import a text/structured
  CSV pair, configure the feature set, launch a run and read the results — without
  touching a command line beyond a single documented command. They are fluent with
  data; they are not expected to manage a Python environment or a model server.

Architecture and stack recommendations are in [ra2.md](ra2.md).

---

## Reproducibility

Every evaluation run must be reproducible from its record alone. Each run stores:
model name **and digest**, prompt template version, temperature and seed, the
**feature configuration version**, the corpus version, the raw model output, plus
latency and token counts.

The question an analyst will ask repeatedly is *"did the output change
because of the prompt, the config or the model?"* — and it is unanswerable without
this. It is also what makes re-running the whole corpus across models and diffing
the results possible, which is the app's real purpose.

---

## Timeline and scope

**One month to an MVP**, implemented with Claude Code. That is the constraint the
scope has to fit, and the whole vision does not fit it — so the cut is stated here
rather than discovered in week four.

The month buys **Deliverable 1, the application**. Deliverables 2–4 (the
configurations used, the evaluation report, the runbook) are outputs of *operating*
it and follow after. Evaluation runs are not instant either: 3000 records × several
models is wall-clock GPU time that competes with the same month, so the MVP is
"the app can produce the numbers", not "the numbers exist".

### Week one, before any extraction work

Three things gate everything else and are all front-loadable:

1. **A column-population census** over the real corpus, per table — the input to
   feature selection, and the thing that decides whether the PoC has enough ground
   truth to run at all. It is also the cheapest possible week-one deliverable: it
   needs no model, no config UI and no GPU.
2. **Import against real files**, not samples — mixed encodings and unescaped
   delimiters (see *Import is the risky part*).
3. **Model serving on the target GPU**, which is unknown until the hardware is
   confirmed.

Plus one dependency that is not ours to build: **the VUM codelists**. Goal 1 cannot
be prompted without them.

### The rule that decides the cut

> **Capture everything from day one. Build views later.**

A view deferred costs a week whenever it is built. A field *not captured* costs a
full re-run of the corpus across every model to recover — GPU time the month does
not have, and in the worst case a result that can no longer be reproduced because
the models moved. The asymmetry is the whole basis for what follows.

So these are non-negotiable in the MVP even where nothing reads them yet: run
metadata in full (see Reproducibility), the feature-definition fingerprint,
evidence spans on every mismatch, the anonymisation marking, per-record language,
and raw model output stored verbatim.

### In the MVP

- CSV import of the text/structured pair, joined on the key, with the anonymisation
  marking.
- In-app feature configuration: labelled and exploratory, enum value sets, matching
  rules, descriptions — accident-level columns and derived aggregates only.
- **Codelist import and label editing**, inside that configuration. The labels are
  prompt text, so they are versioned and fingerprinted like any other part of the
  definition.
- Extraction against a configurable local LLM endpoint (Goal 1), multiple models.
- Presence flags (Goal 2), reported with Goal 1 as the doc requires.
- Per-feature, per-model, per-language metrics with sample sizes and confidence
  intervals; within-evaluation model ranking (Goal 4).
- Full run records, and the dev-vs-evaluation run marking.
- **Per-entity model output captured and stored**, though only aggregates are
  scored (see *Feature grain*).

### Deferred past the MVP

- **Cross-evaluation comparison views.** The fingerprint is computed and stored
  from day one; the views that join on it are not MVP. Nothing is lost by waiting.
- **Scoring** of object- and person-level features — set matching first, then
  per-entity alignment. The model is prompted for the detail and the output is
  stored from day one; only the scoring view waits.
- **Any contradiction UI beyond a flat, exportable list** with somewhere to record
  the analyst's tag. The underlying data (mismatch + span) is captured regardless.
- **Goal 3's exploratory table** if the month runs short. It shares the extraction
  pass, so it is cheap to *run*; it is the review workflow around it that costs.
  Cutting it drops a goal, so this is the last cut, not the first.
- **The single-command installer and runbook.** Needed for handover, not for the
  MVP to answer the question. A documented developer setup is enough until then.

### What would make the month fail

Not the modelling work. The two realistic sinks are **CSV import against real
data** — encoding, quoting, embedded newlines, the repeating-group shape, all still
open questions below — and **local model serving on the target GPU**, which is
unknown until the hardware is confirmed. Both are front-loadable, and both should
be attacked in week one against real files rather than samples.

---

## Deliverables

1. The PoC application: CSV import, feature configuration, extraction, quality
   assessment, evaluation runner, results view.
2. The feature configuration(s) used, versioned.
3. An evaluation report: ranked metrics per model, feature and language, with all
   run variables and sample sizes.
4. A handover runbook for the non-technical operators.

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Development-sized run mistaken for a result | Wrong model chosen on noise | Mark dev vs evaluation runs in the app; enforce the ≥200 floor for reported metrics |
| Per-language / per-enum cells too thin | Spurious differences read as real | Confidence intervals mandatory; suppress cells below the minimum count; show ties as ties |
| Goal 2 metrics depend on Goal 1 correctness | Compounding error, false "missing" flags | Always report the pair together; never publish Goal 2 alone |
| Feature config edited mid-evaluation | Results silently not comparable | Config immutable once the first run executes; a change starts a new evaluation |
| Feature definition drifts between evaluations | Scores silently compared across incompatible definitions | Join cross-evaluation views on a definition fingerprint; show mismatches as excluded, with the reason |
| Cross-corpus differences read as model differences | Wrong model preferred | Show the corpus with every cross-evaluation number; keep model ranking within-evaluation |
| GPU too small for the interesting models | Weak results, wrong conclusion | Confirm VRAM early; report what was *not* testable |
| Cross-platform GPU differences | Results not comparable across machines | Record host platform and GPU per run |
| macOS support retrofitted late | Rework at the LLM-access layer | Configurable LLM endpoint from day one; no container-GPU assumption in the design |
| Minority language underrepresented | Unmeasured blind spot | Report per-language counts alongside per-language metrics |
| Hallucinating model tops the exploratory table | A worthless attribute promoted as a finding | Exploratory results excluded from ranking; evidence spans mandatory; expert review of a sample before any attribute is recommended |
| Vague expert descriptions of candidates | Findings nobody can interpret | Sharpen the ≤20 descriptions before the first run; treat a description change as a config change |
| Exploratory and labelled metrics mixed in one view | Uninterpretable aggregate scores | Separate tables; exploratory attributes excluded from all Goal 1/2 aggregates |
| Text/record contradictions read as extraction errors | Model blamed for a record fault | Evidence span on every mismatch; analyst tags reviewed cases as hallucination or structured-data error |
| Mismatch list too long to review | List ignored; no tally ever produced | Accepted for now — flat list, exportable; revisit ordering only once a real list proves unreadable |
| Ground-truth columns too sparse to score | Features chosen that have no usable label; PoC answers nothing | Column-population census in week one; select features by populated rate; report labelled-case counts per feature |
| Empty read as a label | False "missing from text" flags on fields nobody filled in | Empty = no value provided; the record drops out of that feature's denominator for Goal 1 and Goal 2 alike |
| Labelled-case count mistaken for corpus size | Metrics quoted on far less data than they appear to rest on | Report labelled cases per feature next to every metric, not just corpus size |
| Codelists unavailable or incomplete | Coded features cannot be prompted or read | Treat as a week-one external dependency, not a refinement; fall back to features that need no codelist |
| Codelist label edited between runs | Same codes, different prompt, silently compared | Label text hashed into the definition fingerprint; a label edit is a config change like any other |
| Mixed or mis-detected file encodings | Corrupted labels; wrong metrics, discovered late | Detect per file, show what was detected, fail loudly on undecodable bytes; never round-trip through Excel |
| Upstream character loss read as a French-language weakness | Wrong model preferred; a data fault reported as a finding about a language | Not measurable — typos and dropped characters are indistinguishable; carry as a stated caveat on per-language conclusions; corpus canary at import to justify requesting a UTF-8 re-export |
| Per-file format assumed global | Text file parsed with the structured delimiter, or vice versa | Delimiter, quoting and header case configured or detected per file; column matching case-insensitive |
| Unescaped delimiter or newline shifts a row | Silent column misalignment across a whole record | Field-count check per row; key-prefix detection for text continuation lines; every recovered or rejected row reported with its key |
| Derived aggregate defined differently between evaluations | Silent incomparability behind an identical name | Derivation rule hashed into the definition fingerprint; prefer native columns wherever one exists |
| Real data mishandled | Compliance incident | Anonymisation marking visible in the app; no data leaves the host |
| Analysts can't operate the tool | PoC stalls after handover | Single-command install; runbook as a numbered deliverable |
| Full vision attempted in the one-month MVP | Nothing finished; no defensible answer | Cut stated up front in *Timeline and scope*: capture everything, build views later |
| A field not captured in the MVP | Recovering it costs a full re-run across all models | Run metadata, fingerprints, spans, language and raw output stored from day one, even where unread |
| CSV import or model serving eats the month | MVP slips with the interesting work untouched | Attack both in week one against real files and the real GPU, not samples |

---

## Settled

- **Roles and access.** None for this phase. Data analysts are the only users, the
  app has no logins and no role model, and attribute selection / running / reading
  results are not separated by permission (see Environment, Non-goals).
- **Text contradicting the record.** It happens, it is reported, and the structured
  record remains authoritative regardless (see Data & ground truth →
  *Contradictions between text and record*).
- **Feature grain.** MVP *scores* accident-level columns and derived scalar
  aggregates only, but per-entity ("vehicle 1 was a car, vehicle 2 a bicycle") is
  the destination the expert wants. Set matching is the first extension, per-entity
  alignment the second — and per-entity output is captured from day one so neither
  needs a re-run (see *Feature grain*).
- **Text file format.** `UNFALLUID;HERGANG` — semicolon-delimited, RFC4180
  quoting with doubled `"`, uppercase header. Different from the structured tables
  in delimiter, quoting and header case, so all three are per-file settings.
- **Delivery shape.** N cantonal sets of `unfall`/`objekt`/`person`, but **one
  text file for all cantons**. Key collisions across cantons are therefore
  blocking, not cosmetic.
- **Encoding loss is not measured per record.** Typos and dropped characters are
  indistinguishable in a corpus with no spell check upstream. One corpus-level
  canary at import, and a caveat on per-language conclusions.
- **Structured input shape.** Three related tables — unfall / objekt / person —
  plus a fourth file carrying the free text, all keyed on `UnfallUid`,
  pipe-delimited. Repeating groups are real rows, not flattened columns.
- **Corpus assembly.** All cantons imported into one corpus; nothing read from
  filenames; only final-state records are delivered, so no status filter is needed.
- **Codelists.** Supplied with the data, imported and label-edited inside attribute
  configuration. Labels are prompt text and are fingerprinted as such.
- **Empty cells.** Empty means no value provided; the data cannot distinguish
  "not applicable". Such records leave that feature's denominator entirely.
- **Sketches.** `UnfSkizzeAnonym` is not delivered and is out of scope. No image
  modality anywhere in this PoC.
- **Re-identification risk — accepted.** The joined record is identifying despite
  the anonymised text. Accepted on the basis that the app runs locally, no data
  leaves the host, and analysts are under NDA.
- **Timeline and effort budget.** One month to an MVP, implemented with Claude
  Code. The scope cut this forces is written out in *Timeline and scope*.
- **How contradictions are handled — kept deliberately simple for v1.** The
  structured record is fully authoritative; mismatches go to a flat list with
  evidence spans, and an analyst tags each reviewed case as *hallucination* or
  *structured-data error*. No rescoring, no clustering, no automatic triage. The
  earlier design (value-pair clustering, cross-model agreement, unbiased sampling)
  is parked, not discarded.

## Open questions

- **In which language are the codelist labels supplied?** They become prompt text,
  and a German-only codelist against French narratives is a per-language handicap
  that would show up in the metrics as a model weakness. If labels exist per
  language, the config needs to hold all of them.
- **Which output language** for normalised free-text values (see *Language
  handling*).
- **Do the text's role codes (`P`, `B1`, `G1`) map to `ObjNrFeld` / `PersNrFeld`?**
  If they do, per-entity alignment is a join rather than a research problem, and
  the second extension gets much cheaper.
- **Can the source re-export the text in UTF-8?** The only real fix for the
  character loss, and worth asking before the evaluation corpus is cut.
- **Is escaping guaranteed in the text file, or incidental?** The sample uses
  correct RFC4180 quoting, which contradicts the earlier "no escaping" answer. The
  importer handles both, but knowing which to expect decides whether malformed rows
  are an alarm or routine.
- **`UnfHergangTextAnonym` semantics** — "an anonymised text exists" or "this text
  has been anonymised"? Decides what the marking in the UI actually asserts.
- **Does a third tag turn out to be needed?** *Hallucination* and
  *structured-data error* cover the intent, but a real list will contain cases that
  are neither — the model read the text correctly and the text itself disagrees
  with the record, with no fault on either side. Starting with the two tags plus
  *unclear* costs nothing and answers this from real data.
- **Automatic *wrong* vs *hallucinated* triage** — parked, not rejected. Whether a
  verbatim-span check is usable on this corpus is a question for real span data,
  and it needs a fuzzy-matching threshold that can be defended (it interacts with
  the same open decision for free-text matching rules).

# Evaluation report — template

The evaluation report is deliverable 3 in `vision.md`: *ranked metrics per
model, feature and language, with all run variables and sample sizes*. Copy
this file, fill every field, and delete the guidance in *italics*.

Every number comes from the app's own screens. Nothing here is computed by
hand, and nothing is left out because it was inconvenient.

**Before it leaves the machine**, screen the report as `data-handling.md` §3
says. Example rows are **synthetic**, always. A real narrative, evidence span
or `unfall_uid` never goes in, not even to illustrate a point.

---

## 1. What was compared

| | |
|---|---|
| Evaluation | *name, as on the Evaluation screen* |
| Corpus | *name, version, record count* |
| Corpus is synthetic | *no. If the Results pill says SYNTHETIC, stop: this is not a result* |
| Dev-sized | *no. If the pill says DEV, stop: a smoke test is not a result* |
| Feature configuration | *cfg fingerprint (the `cfg` chip), and the features with their per-feature fingerprints* |
| Prompt template | *version and fingerprint* |
| Minimum n per cell | *the evaluation's floor* |

## 2. Run variables, per model

*One row per run. Copy these from the Evaluation screen's reproducibility
card ("Stored on every run"). A field the card reads as `unknown` is written
`unknown` here, never guessed.*

| Model | Digest | Temperature | Seed | Reasoning | Parallel calls | Ollama | Server options | Context |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |

| Host | GPU | Endpoint |
|---|---|---|
| | | |

## 3. Can each model read what it was given?

*From the Ranking tab's **Unreadable** column, or the line under each model
on the Results extraction tab. Report both figures for every model, whether
or not they are zero.*

| Model | Unreadable answers | Prompts at the context limit |
|---|---|---|
| | *rate, e.g. 2.1 %* | *count, or "context not recorded"* |

- **Unreadable** means the answer was not valid JSON. Every feature of that
  record then scored *missing*, so recall falls for a reason that is not
  reading. A model with a high rate cannot follow the output schema; that is a
  different finding from a model that reads badly.
- **At the limit** means the prompt reached 95 % of the context the model was
  loaded with. The server truncates such a prompt rather than refusing it, so
  the model may have answered about text it never saw. Any non-zero count
  here qualifies that model's recall.
- **Context not recorded** means the run cannot say whether any prompt was
  truncated. State that, and do not read it as zero.

## 4. Ranking

*From the Ranking tab. Copy the verdict as the tab states it; it is composed
from the computed ranks and never authored. Models whose intervals overlap
share a rank and are written as tied.*

| Rank | Model | Macro F1 [95 % CI] | Best / tied / worse | Median latency | Time / record | VRAM |
|---|---|---|---|---|---|---|
| | | | | | | |

Verdict: *…*

Latency, VRAM, the presence rate and the unreadable figures are **reported,
never scored**: they are the tie-breakers the reader applies, not ones the
tool applied.

## 5. Per feature and per language

*From the Results extraction tab: F1 with its interval and n for each
labelled feature and model; cells below the floor are written "insufficient
data", never as a number. Then the per-language breakdown, with its
Windows-1252 caveat as the tab states it.*

## 6. What a mismatch rate means

A mismatch rate is not a model error rate until the mismatch list has been
read and tagged. State how many mismatches were reviewed, how they were tagged
(model wrong, record wrong, ambiguous), and by whom.

## 7. Reproducibility

The run variables in §2 are what reproducing this evaluation requires. **They
are necessary, not sufficient**, and the report states that plainly:

> Not bit-identical. The same model, prompt, temperature and seed can still
> change a few answers between runs: GPU batching, cache reuse and
> floating-point order vary, and so do a different Ollama version or context
> size. A re-run is a check of these numbers, not a guarantee of them.

*This paragraph is the same sentence the app shows on the reproducibility card
and under the ranking (`sw-design.md` SD48). Keep it verbatim.*

If the comparison is re-run to confirm it, report both runs, and how many
answers differed.

## 8. Limits of this evaluation

*What the ground truth could and could not support (the floor, the features
too thin to score), what was out of scope, and anything the run log or the
operations log recorded as an incident.*

# Choosing models — RA2

**Which local models to compare in an evaluation, which to avoid, and how to
judge a model or a version nobody has measured yet.**

This page is for someone choosing the models an evaluation compares. It
assumes no knowledge of the codebase. How long a run takes, and the settings
that change that, are in [`performance.md`](performance.md).

**This page is not authority.** `mvp-spec.md` decides *what* the product must
do, `sw-design.md` decides *how* it is built, and where either disagrees with
this page, this page is wrong. Every number below was measured on one host,
on synthetic data. [`performance.md` §7](performance.md) says how. Re-measure
rather than edit them.

**Last reviewed:** 2026-09-25 · measurements of 2026-09-23 and 2026-09-24 ·
Linux, NVIDIA RTX 5060 Ti 16 GB · Ollama 0.34.0.

---

## 1. The short version

| If you want | Use | Why |
|---|---|---|
| **The default for feature extraction** | **`qwen3:8b`** | Tied for first, best on Italian, fastest per record. 3 000 records in ~1.5 h, or ~40 min with parallel calls (§5) |
| A second opinion in the same evaluation | `granite4.1:8b` | A different family and tokeniser, also tied for first. ~2.5 h at 3 000 records |
| Vehicles and people captured as entities | `gemma4:12b` | The only model that fills `entities` on every record. ~10 h at 3 000 records (§4) |
| Fast iteration on a prompt | `qwen3:8b` on a Dev-sized corpus | ~1.5 min per 50 records |
| **To avoid** | `qwen3.5:2b`, `qwen3.5:9b` | Rank last or near-last. `9b` is also 5× slower than `qwen3:8b` |
| A model not on this page, or a new version of one that is | `just qualify-model <tag>` | §6 |

**Keep two or three of the leaders in the first real evaluation, not one.**
The synthetic seed can't tell them apart (§3). Only real data can, and that's
the question RA2 exists to answer.

**Parallel calls are for `qwen3:8b` only**, and only after its gate has been
run on the host where the evaluation runs. The other models are either
slowed by the setting or give different answers under it (§5).

---

## 2. The models at a glance

Measured on the 200-record seed, with reasoning effort `none`, temperature 0
and seed 42. "Seed F1" is macro-F1. Anything above ~0.88 is at the seed's
ceiling (§3).

| Model | Seed F1 | Verdict on the seed | Per record | 3 000 records | Entities | Parallel calls |
|---|---|---|---|---|---|---|
| **`qwen3:8b`** | 0.895 | tied for best | **1.7 s** | 1 h 30 | never | **passes the gate** (×4, 2.4×) |
| `gemma4:12b` | 0.899 | tied for best | 11.3 s | 9 h 40 | **every record** | fails, narrowly |
| `granite4.1:8b` | 0.886 | tied for best | 3.1 s | 2 h 35 | never | fails |
| `gemma3:4b` | 0.881 | tied for best | 2.9 s | 2 h 35 | half the records | fails |
| `ministral-3:8b` | 0.888 | tied for best | 3.3 s | 2 h 55 | rarely | fails, **and changes serially** on a multi-slot server |
| `llama3.2:3b` | 0.830 | behind on 2 features | 2.2 s | 1 h 50 | most records, few each | not measured |
| `qwen3.5:9b` | 0.829 | behind on 1 feature | 9.1 s | 6 h 40 | most records | Ollama can't |
| `qwen3.5:2b` | 0.755 | behind on 2 features | 2.3 s | 2 h | never | Ollama can't |

Times are serial, from [`performance.md` §3](performance.md). Real
narratives are longer than the seed's, so expect real runs to be slower.

---

## 3. Quality

Scored and ranked by RA2 itself on the 200-record seed (6 labelled features, 1
exploratory). Macro-F1 has a 95 % Wilson interval. RA2 calls models **tied**
when their intervals cross.

| Rank | Model | Macro-F1 | 95 % interval | RA2's verdict |
|---|---|---|---|---|
| 1 | `gemma4:12b` | 0.899 | 0.874–0.909 | tied for best |
| 1 | `qwen3:8b` | 0.895 | 0.870–0.905 | tied for best |
| 1 | `ministral-3:8b` | 0.888 | 0.862–0.898 | tied for best |
| 1 | `granite4.1:8b` | 0.886 | 0.861–0.897 | tied for best |
| 1 | `gemma3:4b` | 0.881 | 0.855–0.892 | tied for best |
| 6 | `llama3.2:3b` | 0.830 | 0.803–0.844 | behind on 2 features |
| 6 | `qwen3.5:9b` | 0.829 | 0.801–0.843 | behind on 1 feature |
| 8 | `qwen3.5:2b` | 0.755 | 0.730–0.772 | behind on 2 features |

Per feature (F1):

| Feature | n | `llama3.2:3b` | `qwen3.5:2b` | `gemma3:4b` | `qwen3:8b` | `granite4.1:8b` | `ministral-3:8b` | `qwen3.5:9b` | `gemma4:12b` |
|---|---|---|---|---|---|---|---|---|---|
| `AnzObjFeld` | 200 | 0.93 | 0.92 | 0.93 | 0.93 | 0.91 | 0.86 | 0.88 | 0.92 |
| `UnfDatumFeld` | 200 | 0.84 | 0.88 | 0.84 | 0.88 | 0.88 | 0.88 | 0.84 | 0.88 |
| `UnfTypAusw` | 200 | 0.66 | 0.45 | 0.81 | 0.85 | 0.81 | 0.87 | 0.69 | 0.88 |
| `UnfZeitFeld` | 182 | 0.68 | 0.42 | 0.83 | 0.84 | 0.84 | 0.84 | 0.79 | 0.84 |
| `anyone_injured` | 200 | 0.94 | 0.93 | 0.94 | 0.94 | 0.94 | 0.94 | 0.89 | 0.94 |
| `objects_involved` | 200 | 0.94 | 0.92 | 0.94 | 0.93 | 0.93 | 0.93 | 0.88 | 0.93 |

Mean F1 by language, over the features whose language cell clears the 20-case
floor (6 for `de` and `fr`, 5 for `it`):

| Model | de | fr | it |
|---|---|---|---|
| `gemma4:12b` | 0.91 | **0.89** | **0.93** |
| `qwen3:8b` | **0.91** | 0.88 | **0.93** |
| `granite4.1:8b` | **0.91** | 0.85 | **0.93** |
| `ministral-3:8b` | 0.90 | 0.88 | 0.89 |
| `gemma3:4b` | 0.90 | 0.88 | 0.85 |
| `qwen3.5:9b` | 0.84 | 0.79 | 0.86 |
| `llama3.2:3b` | 0.86 | 0.79 | 0.82 |
| `qwen3.5:2b` | 0.85 | **0.63** | 0.71 |

**How far to trust this.** The seed is synthetic, and its contradictions and
silent narratives are unrecoverable by design, so a *perfect reader* tops out
around **90 %** macro-F1 (`docs/seed.md` §8: 89.6 % at 48 records). The five
leaders are at that ceiling. **This corpus can't separate them. Only real data
can.** What the seed *does* show reliably:

- **The bottom three are measurably worse.** They lose on the two features
  that need reading rather than copying: the accident type (`UnfTypAusw`) and
  the time (`UnfZeitFeld`).
- **`qwen3.5:2b` is weak outside German.** French 0.63, Italian 0.71.
- **Bigger isn't better here.** `qwen3.5:9b` ranks below `gemma3:4b` and
  `qwen3:8b`.

---

## 4. Entities: what the fast models leave out

The response schema has an `entities` list next to `features`. It holds the
object-level capture (vehicles, people) that RA2 stores but **never scores**
(`mvp-spec.md` §8.2). The models differ sharply in whether they fill it (20
seed records each):

| Model | Records with entities | Mean entities per record |
|---|---|---|
| `gemma4:12b` | **20 / 20** | 7.0 |
| `qwen3.5:9b` | 17 / 20 | 5.5 |
| `llama3.2:3b` | 17 / 20 | 1.2 |
| `gemma3:4b` | 10 / 20 | 2.1 |
| `ministral-3:8b` | 4 / 20 | 0.2 |
| `qwen3:8b` | **0 / 20** | 0 |
| `granite4.1:8b` | 0 / 20 | 0 |
| `qwen3.5:2b` | 0 / 20 | 0 |

**Most of the speed difference among the leaders is this list**
([`performance.md` §4.3](performance.md)). The ranking can't show it, because
entities aren't scored. If the object-level capture matters for the report,
`gemma4:12b` does it thoroughly at 6.6× the time of `qwen3:8b`, and
`gemma3:4b` does half of it at 1.7× the time.

---

## 5. Which models can take parallel calls

Parallel calls put several records of one model in flight at once. Whether a
model tolerates that is **measured per model, per host**, through a gate: its
answers must stay within the 0–2-of-48 noise that two ordinary runs already
show, both when it runs in parallel and when it runs one at a time on a
server set up for parallel calls. The full counts are in
[`performance.md` §5.3](performance.md), and the setup is in §5.4.

| Model | Verdict | What it means for you |
|---|---|---|
| **`qwen3:8b`** | **passes** | ~2.4× faster with identical scores. The only model in the map |
| `granite4.1:8b`, `gemma3:4b`, `gemma4:12b` | fail in parallel | Keep them serial. They're unaffected when the *server* is set up for parallel calls |
| `ministral-3:8b` | fails both | Its answers change on 6 of 48 records as soon as the server allows parallel calls, **even when it runs serially**. That's why `granite4.1:8b` replaced it as the second opinion |
| `qwen3.5:2b`, `qwen3.5:9b` | can't | Ollama 0.34 serves this architecture one call at a time whatever the setting |
| `llama3.2:3b` | not measured | |

**A verdict belongs to one digest on one Ollama version, and RA2 checks.**
The launch applies a parallel-calls entry only with a passing gate for the
digest that will run, on the Ollama version that's running. A re-pull or an
Ollama upgrade takes the model back to serial until the gate is re-run (§6.3).
The gate is `just qualify-model <tag> --gate 4 --n-slot URL` ([`performance.md` §5.4](performance.md)).

---

## 6. Trying a model this page doesn't cover

New models, and new versions of old tags, appear all the time. The table in
§2 describes the digests pulled on 2026-09-23, and nothing else.

### 6.1 Is it worth a run?

- **Does it fit?** On 16 GB, up to ~12 B parameters at 4-bit quantisation.
  The Models card greys out a model the GPU is known not to fit
  ([`performance.md` §6](performance.md)).
- **Does it write much?** Time per record is output tokens ÷ generation
  speed, not parameter count ([`performance.md` §4.3](performance.md)). A
  model that "thinks" by default is the slowest case, so leave reasoning
  effort at `none` unless you're measuring it.
- **Is it a newer version of a model that ranked low?** It's still worth a
  run. Qwen 3.5 ranks below Qwen 3 here, so a version number predicts nothing
  in either direction.

### 6.2 Measure it

```bash
just qualify-model <tag>
```

It runs the model over the 200-record synthetic seed in a temporary data
directory, scores it exactly as an evaluation would, prints the result and
stores it in RA2's database for this host. Your own evaluations aren't
touched, and the temporary directory is deleted afterwards. Unload other
models first (`ollama ps`, then `ollama stop <tag>`): the command refuses to
measure while another one is loaded, because it would distort the timings.

```
qwen3:8b · digest 500a1f067a9f · Ollama 0.34.0
  quality: macro-F1 0.895 (0.870–0.905) · 1.75 s/record · entities in 0% of records · 0 parse failures
Recorded as 01a0… in …/ra2.sqlite.
```

Read it against §2:

1. **Macro-F1.** Tied with the leaders, or behind? Ties are all the seed can
   tell you (§3). Qualify `qwen3:8b` too, if it isn't already: if it doesn't
   land near 0.895, something about the setup differs from this page, and
   the new model's number can't be compared either.
2. **Time per record**, times your corpus size.
3. **Entities.** The share of records where the model filled `entities`.
   No screen shows entities yet, so this line is the only place to see it.

Per-language F1 is stored with the result, but not printed yet. To see it,
and the per-feature table, launch an evaluation over a seeded trial data
directory. **`reset-seed` wipes the directory it's given, so never point it at
the one holding real evaluations.** Stop RA2 first:

```bash
RA2_DATA_DIR=/tmp/ra2-trial just reset-seed yes --records 200
RA2_DATA_DIR=/tmp/ra2-trial just dev
```

A model that holds German and drops French or Italian is the `qwen3.5:2b`
pattern. Delete `/tmp/ra2-trial` when you're done.

### 6.3 A new version of a tag you already use

`ollama pull` can replace the weights behind a tag without changing its name.
RA2 records the **digest** on every run, so the Evaluation screen's
reproducibility line shows which weights ran, and every qualification is
stored per digest.

- **Quality numbers** describe the old digest. Run `just qualify-model` again.
- **Parallel calls** stop automatically. The launch uses a map entry only
  with a gate for the digest that will run, so the new weights run one record
  at a time, and the log says `gate=digest`, until the gate is re-run
  ([`performance.md` §5.4](performance.md), "After a re-pull or an Ollama
  upgrade"). An Ollama upgrade does the same, with `gate=ollama_version`.
- **Evaluations already run** keep their digest. Comparing an old run with a
  new one compares two models, not one.

### 6.4 Planned

The Models card will show each model's stored result on its row: seed F1,
time per record, entity fill and, where the launch would honour it,
`parallel ×4` ([`plan-model-choice.md`](../plan-model-choice.md) Stage 5).
Until then, the command's output is where to read it.

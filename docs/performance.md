# Performance — RA2

**How long an evaluation takes, what makes it faster, what that costs, and
which local model to use.**

This page is for someone who has to plan evaluation runs on RA2, or choose the
models they compare. It assumes no knowledge of the codebase.

**This page is not authority.** `mvp-spec.md` decides *what* the product must
do, `sw-design.md` decides *how* it is built, and where either disagrees with
this page, this page is wrong. Every number below was measured on the host
named here. Re-measure rather than edit them (§7 says how).

**Last reviewed:** 2026-09-23 · against commit `12268ed` · Linux, 28 cores,
31 GB RAM, NVIDIA RTX 5060 Ti 16 GB · Ollama 0.34.0.

---

## 1. The short version

| | |
|---|---|
| Where the time goes | **The model.** Scoring 48 records × 7 features takes 0.14 s. Everything else waits on one LLM call per record |
| Wall time | **records × models × seconds per record.** Models run one after another |
| Seconds per record | **1.7 s** (`qwen3:8b`) to **11.3 s** (`gemma4:12b`) on this host, with reasoning off |
| A 3 000-record evaluation | **~1.5 h per model** with `qwen3:8b`, **~10 h** with `gemma4:12b` (§3.2) |
| Biggest lever | **Reasoning effort.** `none` vs the model's default: 6 s vs 190 s for one record |
| Second biggest | **The model**, mostly through how much it *writes*, not through its size (§4.3) |
| Recommended model | **`qwen3:8b`**. Tied for first on quality, fastest of the leaders. It captures no entities (§4.4) |
| Parallel calls | **Not implemented.** Measured at ~2× for `qwen3:8b` without changing answers (§5.3) |

---

## 2. Where the time goes

RA2 sends **one call per record, carrying every feature** (`mvp-spec.md` D5).
It waits for the answer, stores it in its own transaction, then sends the
next. The runs of an evaluation (one per model) execute **one after another**:
two models sharing a GPU are slower than two in sequence (`sw-design.md`
§15.4).

So:

```
wall time ≈ Σ over models ( records × seconds per record for that model )
```

A call's duration has three parts, largest first:

1. **Generating the answer.** Proportional to the number of output tokens. On
   this host that's 50–165 tokens/s depending on the model (§4.2).
2. **Reading the prompt.** ~350 tokens on the seed. Fast on a GPU, and cached
   when consecutive prompts share a prefix.
3. **Loading the model**, once per run, and only if it isn't already loaded:
   5.7 s cold vs 0.04 s warm for `qwen3.5:2b`.

Everything else RA2 does is negligible by comparison: prompt resolution,
parsing, the commit, scoring and ranking.

---

## 3. What to expect

### 3.1 Measured: 200 records, eight models

One evaluation, launched and scored through RA2's own services, over the
synthetic 200-record seed (`just reset-seed yes --records 200`), with reasoning
effort `none`, temperature 0 and seed 42. All eight runs finished 200/200 with
**0 parse failures and 0 retries**. Total wall time: **1 h 59 min**.

| Model | Wall time | Records/s | Median per record |
|---|---|---|---|
| `qwen3:8b` | 6 min | 0.56 | 1.71 s |
| `llama3.2:3b` | 7 min | 0.45 | 2.17 s |
| `qwen3.5:2b` | 8 min | 0.42 | 2.28 s |
| `gemma3:4b` | 10 min | 0.32 | 2.86 s |
| `granite4.1:8b` | 10 min | 0.32 | 3.07 s |
| `ministral-3:8b` | 12 min | 0.28 | 3.34 s |
| `qwen3.5:9b` | 27 min | 0.13 | 9.05 s |
| `gemma4:12b` | 39 min | 0.09 | 11.28 s |

### 3.2 Projected: the corpus sizes `vision.md` plans for

Linear in records, from §3.1's measured records/s:

| Model | 50 records (dev) | 200 records | 1 000 records | 3 000 records |
|---|---|---|---|---|
| `qwen3:8b` | 1.5 min | 6 min | 30 min | **1 h 30** |
| `llama3.2:3b` | 2 min | 7 min | 37 min | 1 h 50 |
| `qwen3.5:2b` | 2 min | 8 min | 40 min | 2 h |
| `gemma3:4b` / `granite4.1:8b` | 2.5 min | 10 min | 52 min | 2 h 35 |
| `ministral-3:8b` | 3 min | 12 min | 59 min | 2 h 55 |
| `qwen3.5:9b` | 7 min | 27 min | 2 h 13 | 6 h 40 |
| `gemma4:12b` | 10 min | 39 min | 3 h 14 | **9 h 40** |

All eight at 3 000 records: **~30 h**. The top four by quality/speed
(`qwen3:8b`, `ministral-3:8b`, `granite4.1:8b`, `gemma3:4b`): **~9.5 h**.

**Expect real data to be slower.** The seed's narratives are short and
generated: ~345 prompt tokens per record. Real narratives are longer, and a
model that quotes evidence writes more. Output length is what drives time
(§4.3), so a model's real rate can fall well below its seed rate. Run a
dev-sized evaluation first (§5, lever 4) and extrapolate from its ETA.

---

## 4. Model comparison

### 4.1 Quality

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
can**, and that's the question RA2 exists to answer. What the seed *does*
show reliably:

- **The bottom three are measurably worse.** They lose on the two features
  that need reading rather than copying: the accident type (`UnfTypAusw`) and
  the time (`UnfZeitFeld`).
- **`qwen3.5:2b` is weak outside German.** French 0.63, Italian 0.71.
- **Bigger isn't better here.** `qwen3.5:9b` ranks below `gemma3:4b` and
  `qwen3:8b`.

### 4.2 Speed, size and fit

| Model | On disk | Loaded (4 k context) | Generation | Median output tokens | Prompt tokens | Median per record |
|---|---|---|---|---|---|---|
| `llama3.2:3b` | 2.0 GB | 2.6 GB | 165 tok/s | 334 | ~345 | 2.17 s |
| `qwen3.5:2b` | 2.7 GB | 2.4 GB | 139 tok/s | 279 | ~345 | 2.28 s |
| `gemma3:4b` | 3.3 GB | 2.9 GB | 124 tok/s | 297 | ~345 | 2.86 s |
| `qwen3:8b` | 5.2 GB | 5.6 GB | 77 tok/s | **121** | ~348 | **1.71 s** |
| `granite4.1:8b` | 5.3 GB | 5.9 GB | 72 tok/s | 210 | ~345 | 3.07 s |
| `ministral-3:8b` | 6.0 GB | 5.6 GB | 73 tok/s | 232 | **~881** | 3.34 s |
| `qwen3.5:9b` | 6.6 GB | 5.5 GB | 67 tok/s | **565** | ~343 | 9.05 s |
| `gemma4:12b` | 7.6 GB | 8.1 GB | 49 tok/s | **466** | ~345 | 11.28 s |

"Generation" is raw decoding speed on a fixed prompt. Output and prompt tokens
are per seed record through RA2's own adapter. `ministral-3:8b`'s chat template
adds ~500 tokens to every prompt.

All eight fit in 16 GB. Only one is loaded at a time during a run, because runs
are serial. A model that doesn't fit entirely in VRAM spills layers to the CPU,
and it slows sharply. This happened once during measurement, with another model
still loaded (§6).

### 4.3 Why the fastest leader is the one with the shortest answers

`qwen3:8b` decodes at about half the speed of `llama3.2:3b` and is still the
fastest model per record, because it writes **121 tokens where the others write
200–565**. `qwen3.5:9b` decodes almost as fast as `qwen3:8b` and takes **five
times** longer, because it writes 4.7× more.

**Seconds per record ≈ output tokens ÷ generation speed.** A model's parameter
count predicts neither. Look at what the model *writes*.

### 4.4 What the short answers leave out: entities

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

**Most of the speed difference among the leaders is this list.** The ranking
can't show it, because entities aren't scored. If the object-level capture
matters for the report, `gemma4:12b` does it thoroughly at 6.6× the time of
`qwen3:8b`, and `gemma3:4b` does half of it at 1.7× the time.

### 4.5 Recommendation

| Use | Model | Why |
|---|---|---|
| **Default for feature extraction** | **`qwen3:8b`** | Tied for first, best on Italian, fastest per record. 3 000 records in ~1.5 h |
| Second opinion in the same evaluation | `ministral-3:8b` or `granite4.1:8b` | Different families and tokenisers, also tied for first. ~3 h each at 3 000 |
| When entities matter | `gemma4:12b` | The only model that fills `entities` on every record. ~10 h at 3 000 |
| Fast iteration on a prompt | `qwen3:8b` on a dev-sized corpus | ~1.5 min per 50 records |
| **Avoid** | `qwen3.5:2b`, `qwen3.5:9b` | Rank last or near-last; `9b` is also 5× slower than `qwen3:8b` |

All five leaders may still separate on real data. Keep **two or three** of them
in the first real evaluation rather than one.

---

## 5. The levers

Ordered by effect. "Measured" means on this host, as described in §7.

| # | Lever | Effect | Benefit | Downside |
|---|---|---|---|---|
| 1 | **Reasoning effort** (per evaluation; default from `RA2_LLM_REASONING_EFFORT`, default `none`) | 6 s vs 190 s for one record with a thinking model (`qwen3.5:latest` on CPU; `sw-design.md`, the `llm_reasoning_effort` entry in `config.py`) | The difference between a run that finishes and one that times out | Thinking might improve accuracy on hard features; `none` gives that up. It's recorded on the run, so a `none` run and a `high` run can be compared |
| 2 | **Model choice** | 1.7–11.3 s per record, 6.6× (§3.1) | See §4.5 | Faster models capture less (§4.4); the top five tie on the seed |
| 3 | **Output length** (the prompt template) | Seconds per record scale with output tokens (§4.3) | Asking for short evidence spans, or no entities, cuts time roughly in proportion | A new template version; entities and evidence are what a reviewer reads. Not measured on its own |
| 4 | **Corpus size** (Dev / Full) | Linear. Dev takes the first `RA2_DEV_RECORD_MAX` (50) records by id | Minutes instead of hours while a prompt or feature set is still changing | Dev runs are marked "smoke test, not a result" and are too small for per-language cells |
| 5 | **Number of models** | Linear, since runs are serial | Fewer runs, sooner | Fewer comparisons. The seed can't tell the leaders apart |
| 6 | **Model fits in VRAM** | Spilling ~20 % of a model to CPU took `qwen3:8b` from 1.7 s to ~3 s per record (§6) | Keep the GPU free of other models during a run | Nothing to set in RA2; see lever 7 |
| 7 | **Ollama keep-alive** (`OLLAMA_KEEP_ALIVE`, host setting) | Saves one model load per idle gap: 5.7 s cold vs 0.04 s warm (`qwen3.5:2b`) | Negligible per record; saves seconds per evaluation | A resident model holds VRAM until Ollama needs it for another |
| 8 | **Parallel calls** (not implemented) | ~2× at 4 calls for `qwen3:8b` (§5.3) | Halves wall time on models that support it | See §5.3. Needs `plan-parallel-calls.md` Stages 1–4 and a migration |
| 9 | **Timeout** (`RA2_LLM_TIMEOUT_S`, 600) | No effect on a healthy run | Lower it to fail fast on a model known to be quick | Too low and every record of a slow model times out. A timeout is **not** retried |
| 10 | **Retries** (`RA2_LLM_MAX_RETRIES`, 2) | No effect on a healthy run (0 retries in 1 600 records) | Survives a transient 5xx | Each retry of a failing endpoint costs another full call |

### 5.1 Reasoning effort in detail

The value is set per evaluation and pinned on each run, so it's part of what
a run *asked*. `none`, `low`, `medium` and `high` are accepted; Ollama maps
nothing else. Every number on this page is at `none`. Whether thinking improves
extraction is a question for an evaluation to answer: launch the same setup at
`none` and at `low`, and compare in Results.

### 5.2 What does not help

- **A larger model, by itself.** `qwen3.5:9b` is slower *and* ranks lower than
  `qwen3:8b` and `gemma3:4b`.
- **`OLLAMA_NUM_PARALLEL` on its own.** RA2 sends one call at a time, so extra
  server slots do nothing, and on `gemma3:4b` a four-slot server made even
  serial answers differ on 9 of 48 records.
  **Leave it at 1** until parallel calls exist in RA2.
- **Two models at once.** Refused (`RA2_RUN_CONCURRENCY` must be 1); on one GPU
  it's slower than two in sequence.

### 5.3 Parallel calls (measured, not built)

Several records in flight against one model. Measured with a private Ollama
server (`OLLAMA_NUM_PARALLEL=4`) and the same prompts RA2 sends, over the
48-record seed. "Differs" counts records whose JSON differs from the first
serial pass.

| Model | Architecture | Ollama allows it | 1 call | 2 calls | 4 calls | Differs at 2 / 4 |
|---|---|---|---|---|---|---|
| **`qwen3:8b`** | `qwen3` | yes | 83 s | 52 s (1.6×) | **43 s (1.96×)** | **2 / 0** of 48 |
| `gemma3:4b` | `gemma3` | yes | 142 s | 89 s (1.6×) | 70 s (2.0×) | **27 / 29** of 48 |
| `qwen3.5:2b` | `qwen35` | **no** | 111 s | 111 s | 111 s | 0 / 0 (requests queue) |
| `qwen3.5:9b` | `qwen35` | **no** | not run | | | |
| `llama3.2:3b`, `granite4.1:8b`, `ministral-3:8b`, `gemma4:12b` | `llama`, `granite`, `mistral3`, `gemma4` | yes | not run | | | |

For comparison, repeated **serial** passes differ on **0–2 of 48** on a
one-slot server.

- **`qwen3:8b` passes.** ~2× throughput, and answers change no more than
  serial noise. At 3 000 records that's ~45 min instead of ~1.5 h.
- **`gemma3:4b` fails.** The speedup is the same, but more than half of its
  answers change. Parallelism would become part of the question it's asked.
- **Qwen 3.5 can't.** Ollama 0.34 serves the `qwen35` architecture one request
  at a time whatever the setting (ollama#14510).

The design, tests and risks are in
[`plan-parallel-calls.md`](../plan-parallel-calls.md). Whatever it builds has to
record the parallelism on each run, because per-call latency rises with it:
median 1.7 s → 3.1 s for `qwen3:8b` at 4 calls, even as throughput doubles.

---

## 6. Limits to expect

**By design:**

- **One model at a time, one record at a time.** Wall time is the sum over
  models (§2). There is no way to shorten a single run except the §5 levers.
- **One GPU, 16 GB on this host.** Models to ~12 B parameters at 4-bit
  quantisation fit with their context. Larger models spill to the CPU and slow
  by an order of magnitude. `RA2_GPU_VRAM_GB` disables models that can't fit.
- **The LLM endpoint is loopback only** (`mvp-spec.md` N1). No remote GPU, no
  hosted API, and deliberately no setting to allow one.
- **A timeout is final for that record.** A record that doesn't answer within
  `RA2_LLM_TIMEOUT_S` (600 s) writes no row. After 3 consecutive such
  failures (1 if the run has committed nothing) the run stops as
  `interrupted`. Resume picks up only the missing records.

**Measured:**

- **Re-runs aren't bit-exact.** Temperature 0 and a fixed seed make a re-run
  *nearly* identical: 0–2 of 48 records changed between serial passes for
  both `gemma3:4b` and `qwen3:8b`. Treat a one- or two-record difference
  between two runs of the same setup as noise, not as a model difference.
- **Another loaded model slows a run.** A model left loaded by earlier work
  on the same GPU can force the next one to spill to CPU. Measured on
  `qwen3:8b` alongside a resident `gemma4:12b`: 1.7 s → ~3 s per record.
- **The synthetic seed saturates.** It can rank weak models below strong ones.
  It can't order strong models against each other (§4.1).

**Known gaps in the application:**

- **The Results ranking doesn't report VRAM.** Its caption names latency and
  VRAM as the tie-breakers you apply, but `ranking_service` fills
  `vram_bytes` with `0`, and no VRAM column is rendered. Use §4.2's table.
- **Latency is per call, not per run.** The ranking's median latency is the
  time one record takes. It's comparable between runs only while both ran
  serially, which today they always do.
- **The ETA is linear from records done so far.** Output length varies by
  record, so it wanders, and it only appears after the first record commits.

---

## 7. How these numbers were measured

Nothing on this page came from real data. Every measurement used the synthetic
seed in a throwaway `RA2_DATA_DIR`, and the scripts printed times, counts and
scores only, never prompt or output text (`CLAUDE.md` Do-NOT #13).

| What | How |
|---|---|
| §3.1, §4.1 | `RA2_DATA_DIR=<scratch> uv run python scripts/reset_data.py yes`, then `scripts/seed_dev.py --records 200`. One evaluation with all eight models, launched via `EvaluationService.launch` and `RunService.launch_runs` with an `InlineTaskRunner`, scored by the chained scoring job. Numbers read from `RunService.progress`, `RankingService.ranking_tab` and `ResultsService.extraction_tab` |
| §4.2 | Generation speed: Ollama's own `eval_count / eval_duration` on a fixed synthetic prompt, second call (warm), `think: false`. Token counts: `OllamaLLMClient.extract` on seed prompts resolved through `RunService._resolve_prompt` |
| §4.4 | 20 seed records per model through `OllamaLLMClient.extract`, counting the length of the `entities` array |
| §5.3 | A second `ollama serve` on `127.0.0.1:11435` (`OLLAMA_NUM_PARALLEL=4`, `OLLAMA_MODELS` pointing at the system store, `OLLAMA_NOPRUNE=1`), so the system service was never reconfigured. 48 seed prompts sent through `OllamaLLMClient.extract` under an `asyncio.Semaphore(N)`; outputs compared by SHA-256 of the raw text and of canonical JSON |

Models as pulled on 2026-09-23: `qwen3:8b`, `qwen3.5:2b`, `qwen3.5:9b`,
`gemma3:4b`, `gemma4:12b`, `granite4.1:8b`, `ministral-3:8b`, `llama3.2:3b`.
A re-pull can change a tag's digest; RA2 records the digest on every run.

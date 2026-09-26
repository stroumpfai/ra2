# Performance — RA2

**How long an evaluation takes, what makes it faster, and what that costs.**

This page is for someone who has to plan evaluation runs on RA2. It assumes
no knowledge of the codebase. **Which models to compare** is a separate
question, answered in [`choosing-models.md`](choosing-models.md).

**This page is not authority.** `mvp-spec.md` decides *what* the product must
do, `sw-design.md` decides *how* it is built, and where either disagrees with
this page, this page is wrong. Every number below was measured on the host
named here. Re-measure rather than edit them (§7 says how).

**Last reviewed:** 2026-09-23 · against commit `12268ed` · Linux, 28 cores,
31 GB RAM, NVIDIA RTX 5060 Ti 16 GB · Ollama 0.34.0.
Model choice split out to `choosing-models.md` on 2026-09-25; no number changed.
§5.4 rewritten around `just qualify-model` the same day (SD40).
§6's latency gap restated on 2026-09-26, when SD38's `×N` mark and time-per-record
column made the old wording ("both ran serially, which today they always do")
false; no number changed.

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
| Recommended model | **`qwen3:8b`**, the fastest of the leaders. Which models to compare, and why: [`choosing-models.md`](choosing-models.md) |
| Parallel calls | **Built, off by default.** `RA2_LLM_PARALLEL_CALLS='{"qwen3:8b": 4}'` plus `OLLAMA_NUM_PARALLEL=4` on the Ollama host: 2.4× for `qwen3:8b` with identical scores. The server setting changes `ministral-3:8b`'s answers, so it left the recommended set (§5.3, [`choosing-models.md` §5](choosing-models.md)). Setup: §5.4 |

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

## 4. Model speed

Quality, entities and the recommendation moved to
[`choosing-models.md`](choosing-models.md) on 2026-09-25. This section keeps
what decides how long a model takes. The subsection numbers are unchanged,
because other documents cite them.

### 4.1 Quality

Moved: [`choosing-models.md` §3](choosing-models.md).

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

Moved: [`choosing-models.md` §4](choosing-models.md). In short: the fast
leaders write no `entities`, and that list is most of the speed difference
among the leaders.

### 4.5 Recommendation

Moved: [`choosing-models.md` §1](choosing-models.md).

---

## 5. The levers

Ordered by effect. "Measured" means on this host, as described in §7.

| # | Lever | Effect | Benefit | Downside |
|---|---|---|---|---|
| 1 | **Reasoning effort** (per evaluation; default from `RA2_LLM_REASONING_EFFORT`, default `none`) | 6 s vs 190 s for one record with a thinking model (`qwen3.5:latest` on CPU; `sw-design.md`, the `llm_reasoning_effort` entry in `config.py`) | The difference between a run that finishes and one that times out | Thinking might improve accuracy on hard features; `none` gives that up. It's recorded on the run, so a `none` run and a `high` run can be compared |
| 2 | **Model choice** | 1.7–11.3 s per record, 6.6× (§3.1) | See [`choosing-models.md`](choosing-models.md) | Faster models capture less (§4.4); the top five tie on the seed |
| 3 | **Output length** (the prompt template) | Seconds per record scale with output tokens (§4.3) | Asking for short evidence spans, or no entities, cuts time roughly in proportion | A new template version; entities and evidence are what a reviewer reads. Not measured on its own |
| 4 | **Corpus size** (Dev / Full) | Linear. Dev takes the first `RA2_DEV_RECORD_MAX` (50) records by id | Minutes instead of hours while a prompt or feature set is still changing | Dev runs are marked "smoke test, not a result" and are too small for per-language cells |
| 5 | **Number of models** | Linear, since runs are serial | Fewer runs, sooner | Fewer comparisons. The seed can't tell the leaders apart |
| 6 | **Model fits in VRAM** | Spilling ~20 % of a model to CPU took `qwen3:8b` from 1.7 s to ~3 s per record (§6) | Keep the GPU free of other models during a run | Nothing to set in RA2; see lever 7 |
| 7 | **Ollama keep-alive** (`OLLAMA_KEEP_ALIVE`, host setting) | Saves one model load per idle gap: 5.7 s cold vs 0.04 s warm (`qwen3.5:2b`) | Negligible per record; saves seconds per evaluation | A resident model holds VRAM until Ollama needs it for another |
| 8 | **Parallel calls** (`RA2_LLM_PARALLEL_CALLS`, per model, default `{}`) | 2.38× for `qwen3:8b` at 4 calls: 200 records in 147 s instead of 349 s, identical scores (§5.3) | Less than half the wall time on a model that passed the gate | Needs `OLLAMA_NUM_PARALLEL` ≥ the largest entry, which is server-wide and grows every loaded model's KV cache. Only models measured through the gate belong in the map |
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

### 5.3 Parallel calls (built, off by default)

Several records in flight against one model. Measured with a private Ollama
server (`OLLAMA_NUM_PARALLEL=4`) and the same prompts RA2 sends, over the
48-record seed. "Differs" counts records whose JSON differs from a serial pass
on today's **one-slot** server. Repeated serial passes there differ on
**0–2 of 48**, and that's the band a model is allowed.

Raising the server setting has two separate effects, and a model has to
survive both:

- **Serial on 4 slots.** Nothing runs in parallel yet, but the server now has
  four slots for every model. Do serial runs still give the same answers?
- **Parallel calls.** Several records in flight at once for this model.

| Model | Architecture | Serial on 4 slots, differs | Parallel, differs at 2 / 4 | Throughput at 2 / 4 | Gate |
|---|---|---|---|---|---|
| **`qwen3:8b`** | `qwen3` | **0** | **0–1 / 0–1** | 1.5× / **2.3–2.5×** | **passes** |
| `ministral-3:8b` | `mistral3` | **6** (the same 6 every pass) | 4 / 5 | 1.8× / 2.6× | **fails both** |
| `granite4.1:8b` | `granite` | 0–2 | 15 / 14 | 1.8× / 2.7× | fails parallel |
| `gemma3:4b` | `gemma3` | 0–2 | 27 / 29 | 1.6× / 2.0× | fails parallel |
| `qwen3.5:2b`, `qwen3.5:9b` | `qwen35` | not run | Ollama refuses: requests queue, 1.0× | | cannot |
| `gemma4:12b` | `gemma4` | 0–3, identical pass for pass to one slot | — / 4 (one pass) | — / 2.3× | fails parallel, narrowly |
| `llama3.2:3b` | `llama` | not run | not run | | unknown |

- **`qwen3:8b` passes.** ~2.4× throughput at 4 calls, and answers change no
  more than serial noise. At 3 000 records that's ~35–40 min instead of
  ~1.5 h. One N=4 pass out of five took 59 s instead of ~33 s, for reasons
  not yet known.
- **`ministral-3:8b` is the problem.** Raising the server setting changes 6
  of its 48 answers even when it runs serially. The new answers are stable,
  but runs from before the change won't reproduce after it. This is the
  plan's stop condition while `ministral-3:8b` is in use (§4.5).
- **`granite4.1:8b`, `gemma3:4b` and `gemma4:12b`** tolerate the server
  setting but not parallel calls. They'd stay serial. `gemma4:12b`'s own
  serial passes vary on up to 3 of 48, but they vary identically on one slot
  and on four.
- **Qwen 3.5 can't.** Ollama 0.34 serves the `qwen35` architecture one request
  at a time whatever the setting (ollama#14510).
- **Memory.** Four slots reserve four KV caches in every loaded model.
  `gemma4:12b` grows from 8.1 GB to 10.4 GB, `qwen3:8b` from 5.6 GB to 7.5 GB.
  Each still fits in 16 GB on its own, but two of them loaded together no
  longer do.

Gate record, as `plan-parallel-calls.md` D6 requires: measured 2026-09-23
(Stage 0) and 2026-09-24 (Stage 0b), Ollama 0.34.0, digests `qwen3:8b`
`500a1f067a9f`, `ministral-3:8b` `1922accd5827`, `granite4.1:8b`
`444af1c4b2fe`, `gemma3:4b` `a2af6cc3eb7f`, `gemma4:12b` `4eb23ef187e2`.
Full counts are in `plan-parallel-calls.md` §1.1–1.2.

**Built and verified end to end** (`plan-parallel-calls.md` §1.3). Two
evaluations of `qwen3:8b` + `granite4.1:8b` on the 200-record seed, identical
except for `RA2_LLM_PARALLEL_CALLS`:

| | `{}` | `{"qwen3:8b": 4}` |
|---|---|---|
| `qwen3:8b` run | 349 s | **147 s (2.38×)** |
| `qwen3:8b` macro-F1 | 0.895 | 0.895 |
| `granite4.1:8b` run / macro-F1 | 641 s / 0.886 | 659 s / 0.886 |
| Per-feature F1, both models | | identical to four decimals |
| `qwen3:8b` raw answers differing | | 5 of 200, none moving a score |

To turn it on, follow §5.4. The ranking then shows **time per record**
(mean latency ÷ parallel calls) beside the median latency, which is marked
`×4`, because per-call latency rises with parallelism and stops being
comparable.

The design, tests and risks are in
[`plan-parallel-calls.md`](../plan-parallel-calls.md). Whatever it builds has to
record the parallelism on each run, because per-call latency rises with it:
median 1.7 s → 2.7 s for `qwen3:8b` at 4 calls, even as throughput more than doubles.


### 5.4 Turning parallel calls on

It takes three things, in this order:

1. **A gate on record.** `just qualify-model` measures whether the model's
   answers survive parallel calls on *this* host, and stores the result.
   Without one, RA2 runs the model one record at a time, whatever the map
   says (`sw-design.md` SD40).
2. **Ollama** must accept four requests at once: `OLLAMA_NUM_PARALLEL=4`.
3. **RA2** must send four at once, for that model only:
   `RA2_LLM_PARALLEL_CALLS={"qwen3:8b": 4}`.

If only Ollama is set, RA2 still sends one call at a time. If only RA2 is set,
Ollama queues the extra calls, the run is no faster, and every queued call
waits against `RA2_LLM_TIMEOUT_S`. If the gate is missing, stale or failed,
the launch runs the model serially and its log line says which
(`gate=missing`, `digest`, `ollama_version` or `failed`).

#### Step 0: Run the gate, before changing Ollama

The gate compares the model on a **one-slot** server with the same model on
a **four-slot** one. Your system Ollama is still one-slot, so it's the first
of the two. Start a private four-slot server beside it on another port, using
the same model store so nothing is downloaded again.

First, unload everything, because a model left in GPU memory spoils the
timings (the command refuses to start if one is loaded):

```bash
ollama ps                  # lists what's loaded
ollama stop <tag>          # for each one
```

Then, in a **second terminal**, start the private server and leave it
running:

**Linux** (the standard install keeps its models under the `ollama` user):

```bash
sudo -u ollama env OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NUM_PARALLEL=4 \
  OLLAMA_MODELS=/usr/share/ollama/.ollama/models OLLAMA_NOPRUNE=1 ollama serve
```

**Windows** (PowerShell):

```powershell
$env:OLLAMA_HOST="127.0.0.1:11435"; $env:OLLAMA_NUM_PARALLEL="4"; $env:OLLAMA_NOPRUNE="1"; ollama serve
```

**macOS:**

```bash
OLLAMA_HOST=127.0.0.1:11435 OLLAMA_NUM_PARALLEL=4 OLLAMA_NOPRUNE=1 ollama serve
```

`OLLAMA_NOPRUNE=1` stops the private server from tidying the shared model
store. Back in the first terminal:

```bash
just qualify-model qwen3:8b --gate 4 --n-slot http://127.0.0.1:11435/v1
```

It takes about 15 minutes for `qwen3:8b`: a 200-record quality pass
(~6 min), then five 48-record passes for the gate. `gemma4:12b` takes about
an hour. It ends with lines like:

```
  quality: macro-F1 0.895 (0.870–0.905) · 1.75 s/record · entities in 0% of records · 0 parse failures
  gate ×4: passes · band 2 · serial on 4 slots differs on 0 · parallel differs on 1 of 48 · 2.40×
Recorded as 01a0… in …/ra2.sqlite.
```

Only `passes` lets the map apply. Any other verdict means this model stays
serial on this host: leave it out of the map. Stop the private server with
Ctrl+C in its terminal.

#### Step 1: Set up Ollama

`OLLAMA_NUM_PARALLEL` is read when Ollama starts, so set it where Ollama gets
its environment, then restart Ollama.

**Linux (Ollama as a systemd service, the standard install):**

```bash
sudo systemctl edit ollama
```

In the editor that opens, between the comment lines, add:

```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=4"
```

Save, close, and restart:

```bash
sudo systemctl restart ollama
```

This writes `/etc/systemd/system/ollama.service.d/override.conf` and leaves the
unit file itself alone.

**Windows:** quit Ollama from the tray icon. Open *Edit environment variables
for your account*, add a variable named `OLLAMA_NUM_PARALLEL` with the value
`4`, click OK, and start Ollama again from the Start menu.

**macOS:** run `launchctl setenv OLLAMA_NUM_PARALLEL 4`, then quit and restart
the Ollama app.

**Keep-alive:** leave it at Ollama's default (5 minutes). Reloading
`qwen3:8b` after an idle gap costs a few seconds per run. `OLLAMA_KEEP_ALIVE=-1`
would keep a model in GPU memory indefinitely, and there's nothing to gain
from that here.

#### Step 2: Check that Ollama took it

Load `qwen3:8b` once and read its size. Each slot reserves its own cache, so
the size shows the slot count directly:

```bash
curl -s http://127.0.0.1:11434/api/generate -d '{"model":"qwen3:8b","prompt":"hi","stream":false,"think":false}' > /dev/null
curl -s http://127.0.0.1:11434/api/ps
```

- **`"size"` about 7.5 GB:** four slots. About 5.6 GB means one, so the
  setting didn't take and Ollama needs restarting from where the variable was
  set.
- **`"size_vram"` equal to `"size"`:** the model is fully on the GPU. If it's
  smaller, part of the model spilled to the CPU and the gain is gone (§6).
  Close whatever else is using GPU memory.

On Linux, `journalctl -u ollama -n 100 --no-pager | grep -o 'OLLAMA_NUM_PARALLEL:[0-9]*'`
should also print `OLLAMA_NUM_PARALLEL:4`.

#### Step 3: Set up RA2

Add one line to the `.env` file in the folder RA2 is started from (create the
file if it doesn't exist), then restart RA2:

```
RA2_LLM_PARALLEL_CALLS={"qwen3:8b": 4}
```

The value is a JSON map from model tag to calls in flight. A value outside
1–8, or an empty tag, stops RA2 at startup with a message naming the setting.
A model that isn't in the map runs one record at a time, as before.

#### Step 4: Check that RA2 uses it

Launch a new evaluation that includes `qwen3:8b`:

- **The run's log line** reads `…, timeout=600s, parallel=4`.
- **The Evaluation screen's reproducibility line** ends with
  `parallel calls 4`.
- **Results → Ranking:** `qwen3:8b`'s median latency carries a `×4` mark, and
  its time per record is about 0.7 s instead of about 1.7 s. A note under the
  table explains the mark.

The launch's own log line says why it pinned what it pinned:
`launch …: qwen3:8b parallel=4 (map=4, gate=gated)`. Anything other than
`gate=gated` means the gate from Step 0 doesn't match what's running now.

Only runs launched **after** the change use it. Each run records the value it
was launched with, and Resume continues at that value, so runs from before
the change stay at 1 and stay comparable with each other.

#### What the Ollama setting does to other models

`OLLAMA_NUM_PARALLEL` applies to **every** model Ollama loads, not only to the
ones in RA2's map. Each loaded model reserves four caches:

| Model | GPU memory, 1 slot → 4 | Answers when run one at a time on 4 slots |
|---|---|---|
| `qwen3:8b` | 5.6 → 7.5 GB | unchanged |
| `granite4.1:8b` | 5.9 → 8.0 GB | unchanged |
| `gemma3:4b` | 2.9 → 3.8 GB | unchanged |
| `gemma4:12b` | 8.1 → 10.4 GB | unchanged |
| `ministral-3:8b` | 5.6 → 7.5 GB | **6 of 48 change**, which is why it left the recommended set ([`choosing-models.md` §5](choosing-models.md)) |
| `llama3.2:3b`, `qwen3.5:2b`, `qwen3.5:9b` | not measured | not measured |

Every model still fits in 16 GB on its own, but two of them loaded together
don't. Ollama unloads an idle model when a new one needs the room, so this
takes care of itself. Just don't run anything else on the GPU during an
evaluation.

#### Adding another model to the map

Only `qwen3:8b` belongs in it today. `granite4.1:8b`, `gemma3:4b` and
`gemma4:12b` change 4–29 of 48 answers when their calls overlap, and Qwen 3.5
can't run in parallel at all in Ollama 0.34. For any other model, run its
gate (Step 0) and add it to the map only if the verdict is `passes`. Adding
it without a gate does nothing but put `gate=missing` in the log.

#### After a re-pull or an Ollama upgrade

A gate belongs to one set of weights on one Ollama version. After
`ollama pull` changes a mapped model's digest, or after Ollama is upgraded,
RA2 runs that model serially again (`gate=digest` or `gate=ollama_version`)
until the gate is re-run. Nothing gives different answers without warning;
the only loss is speed.

Your system server now has four slots, so for a re-run the roles swap: start
the private server with **one** slot, and point the flags the other way:

```bash
# second terminal, Linux
sudo -u ollama env OLLAMA_HOST=127.0.0.1:11436 OLLAMA_NUM_PARALLEL=1 \
  OLLAMA_MODELS=/usr/share/ollama/.ollama/models OLLAMA_NOPRUNE=1 ollama serve
# first terminal
just qualify-model qwen3:8b --gate 4 \
  --one-slot http://127.0.0.1:11436/v1 --n-slot http://127.0.0.1:11434/v1
```

#### Undoing it

Linux: `sudo systemctl revert ollama`, then `sudo systemctl restart ollama`.
Windows: delete the variable and restart Ollama. macOS:
`launchctl unsetenv OLLAMA_NUM_PARALLEL`, then restart Ollama. In every case,
remove the `RA2_LLM_PARALLEL_CALLS` line from `.env` and restart RA2. Runs
already stored keep the value they recorded.

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
  It can't order strong models against each other
  ([`choosing-models.md` §3](choosing-models.md)).

**Known gaps in the application:**

- **The Results ranking doesn't report VRAM.** Its caption names latency and
  VRAM as the tie-breakers you apply, but `ranking_service` fills
  `vram_bytes` with `0`, and no VRAM column is rendered. Use §4.2's table.
- **Latency is per call, not per run.** The ranking's median latency is the
  time one record takes, so it is comparable down its column only between runs
  at the same parallelism. A run above 1 carries the `×N` mark for exactly
  that reason, and **time per record** is the column to compare instead
  (§5.3).
- **The ETA is linear from records done so far.** Output length varies by
  record, so it wanders, and it only appears after the first record commits.

---

## 7. How these numbers were measured

Nothing on this page came from real data. Every measurement used the synthetic
seed in a throwaway `RA2_DATA_DIR`, and the scripts printed times, counts and
scores only, never prompt or output text (`CLAUDE.md` Do-NOT #13).

| What | How |
|---|---|
| §3.1, `choosing-models.md` §3 | `RA2_DATA_DIR=<scratch> uv run python scripts/reset_data.py yes`, then `scripts/seed_dev.py --records 200`. One evaluation with all eight models, launched via `EvaluationService.launch` and `RunService.launch_runs` with an `InlineTaskRunner`, scored by the chained scoring job. Numbers read from `RunService.progress`, `RankingService.ranking_tab` and `ResultsService.extraction_tab` |
| §4.2 | Generation speed: Ollama's own `eval_count / eval_duration` on a fixed synthetic prompt, second call (warm), `think: false`. Token counts: `OllamaLLMClient.extract` on seed prompts resolved through `RunService._resolve_prompt` |
| `choosing-models.md` §4 | 20 seed records per model through `OllamaLLMClient.extract`, counting the length of the `entities` array |
| §5.3 | A second `ollama serve` on `127.0.0.1:11435` (`OLLAMA_NUM_PARALLEL=4`, `OLLAMA_MODELS` pointing at the system store, `OLLAMA_NOPRUNE=1`), so the system service was never reconfigured. 48 seed prompts sent through `OllamaLLMClient.extract` under an `asyncio.Semaphore(N)`; outputs compared by SHA-256 of the raw text and of canonical JSON |

Models as pulled on 2026-09-23: `qwen3:8b`, `qwen3.5:2b`, `qwen3.5:9b`,
`gemma3:4b`, `gemma4:12b`, `granite4.1:8b`, `ministral-3:8b`, `llama3.2:3b`.
A re-pull can change a tag's digest; RA2 records the digest on every run.

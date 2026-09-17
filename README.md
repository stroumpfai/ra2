# RA2 — Accident report analysis

RA2 imports Swiss road-accident deliveries into an immutable corpus, profiles
what is actually in them, and measures how well **local** LLMs can extract
structured facts from the free-text accident narratives.

It runs entirely on one machine. **No data leaves the host** — the only
outbound call the application makes is to a local LLM endpoint, and it refuses
to start if that endpoint is not on loopback. See [Local LLMs](#local-llms).

**Why it exists:** the structured columns of these deliveries are sparse, while
the narrative text is rich. RA2 is the instrument for finding out whether a
local model can recover the missing structure well enough to be worth using —
and for proving the answer with numbers rather than impressions.

---

## Contents

- [At a glance](#at-a-glance)
- [Requirements](#requirements)
- [Setup](#setup)
- [Running the application](#running-the-application)
- [Local LLMs](#local-llms)
- [Data formats](#data-formats)
- [Configuration](#configuration)
- [Developing](#developing)
- [Running the tests](#running-the-tests)
- [Not built yet](#not-built-yet)
- [Documentation map](#documentation-map)

---

## At a glance

One process serves both the API and the UI on one port: FastAPI with NiceGUI
mounted on it, SQLite (WAL) underneath, and an in-process asyncio worker for
long runs. The pipeline the navigation follows:

```
Data                       Configure              Run           Review
Import → Census → Codelists → Features → Prompts → Evaluation → Results ·
                                                                Mismatches
```

- **Import** — one delivery becomes one immutable corpus.
- **Census** — how populated each source column is, per table and column. This
  is the input to choosing features.
- **Codelists** — the code→label tables the prompt reads, imported as JSON and
  read-only in the app.
- **Features** — what to extract: labelled features and exploratory attributes.
- **Prompts** — the wording around the feature descriptions, versioned, because
  changing one word changes every answer.
- **Evaluation** — pin one corpus, one frozen feature set and one prompt
  template; run them across several local models; watch progress.
- **Results / Mismatches** — not built yet; see [Not built yet](#not-built-yet).

---

## Requirements

| | |
|---|---|
| **OS** | Windows or Linux. macOS is not a target but nothing is designed out of it. |
| **Python** | 3.14 — **provisioned by `uv`**, so your system Python does not matter. |
| **`uv`** | The only thing you install by hand. https://docs.astral.sh/uv/ |
| **`just`** | The command surface. Every command below is a `just` recipe. https://github.com/casey/just |
| **Disk** | The database, uploaded deliveries and CSV exports live under one directory (`./var` by default). |
| **GPU** | Only for actually running models. Import, Census, Codelists, Features and Prompts need no GPU and no LLM. |

You do **not** need Docker, a database server, Redis, or a network connection
at runtime.

---

## Setup

```bash
git clone <this repo>
cd ra2
uv sync --frozen        # provisions Python 3.14 and every dependency, locked
just migrate            # creates the SQLite database and brings it to head
```

`uv sync --frozen` is deliberate: it installs exactly what `uv.lock` pins, so
"works on my machine" does not happen. Never use bare `pip` or
`python -m venv` here.

`just` with no arguments lists every available recipe.

---

## Running the application

```bash
just dev
```

Then open **http://127.0.0.1:8080**.

This binds the fixed port 8080 and uses `./var` as its data directory — your
real local database.

> **If you are an AI agent, or running an automated check, use `just dev-agent`
> instead.** It picks a random free port and a throwaway temporary data
> directory, so it cannot collide with a developer's live test data. Sharing
> port 8080 and `./var` has clobbered real work before.

The API is on the same port under `/api/v1`, with interactive docs at
`/api/docs`. The UI calls the services in-process as Python — it never calls
its own HTTP API — so the API is there for scripts, not for the UI.

### A first pass through the app

1. **Import** — register a delivery (an upload, or a path on this host), let it
   analyse, review the per-file report, select the files, and freeze them into a
   corpus. Nothing is repaired silently: every recovered or rejected row is
   reported with its key.
2. **Census** — read the populated rates. Sparse columns are the reason this
   project exists; pick features from what is actually populated.
3. **Codelists** — import `codes-2018.json`, then map corpus columns to code
   attributes so enum features can carry real labels.
4. **Features** — define what to extract, then create a feature set. **A set is
   frozen the moment it is created**; to change it, clone it.
5. **Prompts** — write the template around the feature descriptions. Saving
   never edits an existing version: it writes the next one and leaves the old
   text byte-identical, because the runs citing it must keep resolving to
   exactly what they used.
6. **Evaluation** — pin a corpus, a frozen feature set and a template, choose
   models and decoding settings, and launch. Runs execute one model at a time.

---

## Local LLMs

RA2 talks to **Ollama** through the OpenAI-compatible `/v1` surface, using the
`openai` SDK. Because it is the OpenAI surface, pointing at vLLM, LM Studio or
llama.cpp instead is a `base_url` change rather than a rewrite — but the
loopback rule below still applies.

### Setup

1. Install Ollama: https://ollama.com
2. Pull one or more models. **These are examples, not a supported list** —
   nothing has yet been measured against a real endpoint, so treat model choice
   as an open question this tool exists to answer:
   ```bash
   ollama pull llama3.1:8b-instruct-q8_0
   ollama pull qwen2.5:14b-instruct-q6_K
   ollama pull mistral-nemo:12b-instruct-2407-q8_0
   ```
3. Make sure Ollama is listening (it defaults to `127.0.0.1:11434`).
4. Open **Evaluation**. The Models card lists what the endpoint actually has,
   with each model's digest and size, and the endpoint's reachability is shown
   beneath it.

### The loopback rule — read this before changing `RA2_LLM_BASE_URL`

`RA2_LLM_BASE_URL` must point at **loopback** (`127.0.0.1`, `::1` or
`localhost`). The client checks this **when the application starts** and
refuses to run otherwise.

**There is deliberately no setting to turn this off.** An opt-out is how "no
data leaves the host" quietly becomes "no data leaves the host by default", and
these narratives are not anonymised. A typo or a copied `.env` pointing at a LAN
address would ship accident text off the machine; the guard is what makes that
impossible rather than merely discouraged.

**The guard covers the URL; the client covers the environment. Both are
needed.** A proxy is chosen by the HTTP transport, not by the URL, so on a
machine where `HTTP_PROXY` or `ALL_PROXY` is set and `NO_PROXY` does not cover
localhost — the default on most managed workstations — a request for
`127.0.0.1` would otherwise be handed to the proxy host with the guard
satisfied. RA2 therefore builds its own HTTP client with `trust_env=False`, so
no proxy variable, `.netrc` or `SSLKEYLOGFILE` is read, and with
`follow_redirects=False`, so the endpoint cannot redirect the request (and its
body) somewhere the guard never saw. Neither is configurable, for the same
reason the loopback rule is not.

### VRAM and model fit

RA2 reads your GPU's name and total VRAM through NVML's library bindings
(`nvidia-ml-py`) — never by shelling out to `nvidia-smi` — and uses it to mark
models that cannot fit. If there is no NVIDIA GPU, the answer is an honest
**unknown**: every model stays selectable and no fit judgement is made. On a
non-NVIDIA host you can declare the figure yourself with `RA2_GPU_VRAM_GB` and
`RA2_GPU_NAME`.

### If the endpoint is unreachable

The Models card empties, the reason appears next to the endpoint line, and
**Launch is disabled**. This is a state, not an error — there is no toast and
no failed request. Start Ollama, then press *refresh* in the settings dialog
behind the gear button.

---

## Data formats

**Nothing is ever read from a filename.** Canton, language and which table a
file holds all come from the data itself — the header decides the table, the
`unfall` rows decide the canton, and the narrative decides the language.

### A delivery

One delivery is **N cantonal sets of three structured files, plus one text file
covering all cantons**, imported into **one** corpus. A delivery is a single
format throughout — never mixed.

Two structured formats are recognised, decided per file from its header alone:

| | **RADIS** | **Astrana** |
|---|---|---|
| Delimiter | `\|` | `,` |
| Quoting | selective, type-inconsistent | RFC4180, every field quoted |
| Headers | mixed case (`UnfallUid`) | German labels (`Unfall-UID`, `Kanton Kürzel`) |
| `person` table | `person` | `Mitfahrende` |
| Key position | column 0 | anywhere (`unfall`'s key is column 2) |
| Canton column | `KantonAusw` | `Kanton Kürzel` |
| Columns | 67 / 77 / 18 | 67 / 76 / 21 |

The two are **not** a renaming of one another — Astrana is a different, narrower
export with its own values for coded fields.

**The text file is the same contract either way**: one file for all cantons,
`;`-delimited, RFC4180-quoted with `"` doubled, keyed on `UNFALLUID`.

Because that single text file is the join target for every cantonal set, key
uniqueness is verified **across the whole delivery**, not per file — a collision
between two cantons would otherwise attach one canton's narrative to another
canton's record.

### Relationships

`person` links to `objekt`, not to `unfall`. Person→accident is a two-hop join,
and a pedestrian still has an object row.

### Values

- Dates: `YYYYMMDD` (RADIS) or `DD.MM.YY` (Astrana)
- Times: `"HH:MM"`
- Decimals: `.`, optionally apostrophe-grouped (`1'127'946.61`)
- **An empty string means "no value provided"** — not "not applicable". Records
  with an empty column are excluded from that feature's denominator entirely.

### Encoding

Delimiter, quote character and encoding are **per-file settings**, detected on
import and overridable in the UI. Every file is opened with an explicit
encoding; nothing is decoded leniently.

One corpus-level check runs at import: a count of characters from the
Windows-1252-only set. **Zero, in a corpus containing French, proves the text
went through a lossy conversion that deleted characters.** It is reported on the
corpus to justify asking upstream for a UTF-8 re-export — not used to correct
anything.

### Codelists

Code tables are imported as JSON (`codes-2018.json`) and are **read-only in the
app** — there is no UI path that edits a label. A correction or a successor file
is a new import that adds rows; existing mappings keep pointing at the old
generation until an analyst re-points them.

### Real data never enters the repository

The deliveries are classified sensitive: the structured records are not
anonymised and the joined pair is personally identifying. `data/` is
gitignored, and a pre-commit hook (`scripts/check_no_real_data.py`) blocks
delivery-shaped files anywhere in the tree. Test fixtures synthesise the real
hazards byte-exactly instead.

---

## Configuration

Every setting is an environment variable prefixed `RA2_`, readable from a
`.env` file. Defaults are what you get with none set.

| Variable | Default | What it does |
|---|---|---|
| `RA2_DATA_DIR` | `./var` | The database, uploads and exports all live here. |
| `RA2_DB_PATH` | `{data_dir}/ra2.sqlite` | The SQLite file. |
| `RA2_HOST` / `RA2_PORT` | `127.0.0.1` / `8080` | Where the app listens. Loopback by default. |
| `RA2_LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | The LLM endpoint. **Must be loopback.** |
| `RA2_LLM_TIMEOUT_S` | `120` | Per-call timeout. |
| `RA2_LLM_MAX_RETRIES` | `2` | Retries per call — bounded, counted, and shown in the progress card. |
| `RA2_RUN_CONCURRENCY` | `1` | Models run one at a time. Raising it is not implemented. |
| `RA2_GPU_VRAM_GB` / `RA2_GPU_NAME` | unset | Declare the GPU instead of probing it. |
| `RA2_DEV_RECORD_MAX` | `50` | At or below this, a run is a dev-sized smoke test. |
| `RA2_EVAL_RECORD_MIN` | `200` | Below this, a run is marked *dev* and every view says "smoke test, not a result". |
| `RA2_MIN_CELL_COUNT` | `20` | Result cells below this are suppressed (used once scoring exists). |
| `RA2_MAX_UPLOAD_MB` | `512` | Upload ceiling. |
| `RA2_STORAGE_SECRET` | a fixed string | NiceGUI session storage. **Not** a security boundary: the app has no login. |

---

## Developing

### The command surface

Everything goes through `just`. Never bare `pip`, never `python -m venv`.

| Command | What it does |
|---|---|
| `just dev` | Run the app on 8080 against `./var`. |
| `just dev-agent` | Run it on a random port against a throwaway data dir. |
| `just test` | The commit gate: unit + backend + UI, with coverage. |
| `just e2e` | The PR gate: the Playwright journeys. |
| `just lint` | ruff format check, ruff, mypy strict, and the layer contracts. |
| `just fmt` | Apply the formatter and autofixes. |
| `just migrate` | Bring the database to head. |
| `just reset [yes]` | Show what a wipe of `RA2_DATA_DIR` would remove; `yes` carries it out. |
| `just reset-seed yes` | Wipe, then seed a delivery, a corpus, a feature set and a prompt. |
| `just revision "msg"` | Create a migration. **One author per phase** — see below. |
| `just census-export <corpus> <out>` | Export a corpus's census as CSV. |
| `just setup-e2e` | Install the Chromium the E2E layer drives. |
| `just eval` | The eval suite against a real Ollama (needs a GPU). |

### Architecture

Six packages with an enforced dependency rule. A violation **fails the build**;
it is not a review comment.

| Package | May import |
|---|---|
| `ra2/domain/` | stdlib, `pydantic`. **Nothing else in `ra2/`.** |
| `ra2/persistence/` | `domain`, SQLAlchemy, Alembic |
| `ra2/services/` | `domain`, `persistence`, `infra` protocols |
| `ra2/api/` | `services`, `domain` |
| `ra2/ui/` | `services`, `domain` |
| `ra2/infra/` | `domain` |

`ra2/main.py` is the composition root and sees everything — it contains wiring
only. Every adapter arrives there as a defaulted keyword argument, which is how
tests substitute a fake LLM client, a frozen clock or a static GPU probe
**without a single test-mode branch in production code**.

### The rules that have teeth

`CLAUDE.md` carries the full list; these are the ones most likely to catch you:

- **Never mutate an `extraction`, `record` or `corpus` row.** A re-run adds rows.
- **Never edit an applied migration.** Add a new one.
- **Never open a file without an explicit `encoding=`.**
- **Never read canton, language or table kind from a filename.**
- **Never silently repair or drop a row** — every one produces a finding
  carrying its key.
- **Never put business logic in `ui/`**, and never let `ui/` touch a session or
  an ORM object.
- **Never fetch anything over the network from the UI** — no CDN, no fonts. The
  fonts are vendored in `ra2/ui/static/fonts/`.
- **Never import `openai` or `ollama`** outside `ra2/infra/ollama_client.py`.

### Migrations

One migration author per phase, so there are never two heads. Use
`just revision "message"`, check what autogenerate produced against
`models.py`, and never edit a revision that has been applied.

### Findings, not prose

Error and outcome codes are stable identifiers. Assert on the code, never on
message text — wording lives in one rendering table in `ui/` and is free to
change.

---

## Running the tests

```bash
just test     # unit + backend + UI — the commit gate
just lint     # ruff + mypy strict + the layer contracts
just e2e      # the Playwright journeys — run `just setup-e2e` once first
```

All three must pass. Coverage is gated at 85% over `ra2/domain` and
`ra2/services`.

### The layers

| Layer | Path | What it is |
|---|---|---|
| Unit | `tests/unit` | Pure domain. No database, no network, no server. |
| Backend | `tests/backend` | Services, repositories and the API on a temp-file SQLite. |
| UI | `tests/ui` | NiceGUI's `User` fixture, in-process and headless. |
| E2E | `tests/e2e` | Playwright against a real server on a random port. |
| Eval | `tests/eval` | A real local model. Excluded from `just test` and from CI. |

Select a layer with its marker, e.g. `uv run pytest -m unit`.

**Nothing in layers 1–4 touches a socket or a real GPU.** The test fixtures
substitute a fake LLM client, a static model catalogue and a static GPU probe
through the composition root, so the whole suite passes on a laptop with no GPU
and nothing listening on 11434. Only `just eval` needs a real endpoint, and it
is deliberately outside both gates — a gate that needs a GPU is a gate that
fails on every machine without one.

### Fixtures contain the real hazards

Test fixtures are not clean. They carry mixed encodings, a stray delimiter, an
embedded newline, an orphan key, a key duplicated across two cantonal sets, an
all-empty column, and French that is already lossy. Real data is gitignored and
must never reach a test, so the hazards are synthesised byte-exactly and
committed. A clean fixture proves nothing about this input.

---

## Not built yet

Specified, and deliberately not implemented:

- **Scoring, Results and Mismatches.** Runs produce extraction rows and stop
  there — nothing scores them yet. Those nav entries route to a placeholder.
- **The first eval run.** `tests/eval` and `evals/baseline.json` need a real GPU
  and a real Ollama, so they are seeded on the target machine rather than here.
- **Docker packaging and an installer.** Planned; no Dockerfile exists today.
- **Concurrency above one model at a time**, and streaming progress. The UI
  polls; `RA2_RUN_CONCURRENCY` above 1 raises rather than silently running
  serially.
- **Auto-resume at startup.** A run interrupted by a restart is left
  `interrupted` and the Evaluation view offers **Resume**. It is restart-*safe*
  and resumable, deliberately not automatic — a run that restarts itself on
  every app start burns GPU hours on work you may have abandoned.
- **Per-language result breakdowns** and cross-evaluation views.

---

## Documentation map

In authority order — on a *what* question `mvp-spec.md` wins, on a *how*
question `sw-design.md` wins:

| Document | What it is for |
|---|---|
| [`vision.md`](vision.md) | Why this project exists, and what was found in the data. |
| [`ra2.md`](ra2.md) | The original stack and process recommendation. Kept for its rationale; superseded on specifics. |
| [`mvp-spec.md`](mvp-spec.md) | **What** is built — the input contract, the data model, the acceptance criteria. |
| [`sw-design.md`](sw-design.md) | **How** it is built — architecture, seams, invariants. |
| [`CLAUDE.md`](CLAUDE.md) | The Do-NOT list, the layer rule, the ownership rule. |
| [`CONTRACTS.md`](CONTRACTS.md) | What is frozen, and every documented deviation with its reason. |
| `plan-phase-*.md` | Who built what, wave by wave. |
| `design/*/README.md` | The UI handoff packages. Layout and copy are load-bearing. |

---

## Licence

See [`LICENSE`](LICENSE).

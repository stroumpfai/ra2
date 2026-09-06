# Recommendation — Local-LLM Text Structuring App

Stack and process recommendation for a new app that processes unstructured text
through different local LLMs and stores the structured result in SQLite.

Constraints taken as given: simple Python front-end *and* back-end, runs locally,
Docker packaging possible, development handed over to non-technical staff assisted
by Claude, process and testing ensured throughout.

Conventions below lean on the existing pi-planner setup (FastAPI, SQLAlchemy 2.0 +
Alembic, pytest, ruff/mypy, single-container Docker) so the handover audience isn't
learning two different worlds.

---

## Recommended stack

| Layer | Pick | Why |
|---|---|---|
| Runtime | Python 3.14, **uv** for deps/lockfile | One tool for venv + lock + run. `uv sync --frozen` makes "works on my machine" go away — critical for non-technical staff |
| Front-end | **NiceGUI** mounted on the FastAPI app | Pure Python, real component/state model, *same process and port* as the API. Has an in-process `User` test fixture — headless UI tests, no browser |
| Back-end | **FastAPI** | Already known here; NiceGUI is FastAPI underneath, so it's one app |
| LLM access | **Ollama**, called through the **`openai` SDK** pointed at `/v1` | Ollama gives painless multi-model management + pull/swap. Using the OpenAI-compatible surface means vLLM, LM Studio, llama.cpp or a cloud model is a `base_url` change, not a rewrite |
| Structured output | **Pydantic model → JSON Schema → Ollama `format:`** (constrained decoding), wrapped by **PydanticAI** | The schema *is* the contract. Constrained decoding means the model can't emit invalid JSON — no repair code. PydanticAI adds retries, and `TestModel`/`FunctionModel` for tests |
| Storage | **SQLite (WAL) + SQLAlchemy 2.0 async + Alembic** | Same as pi-planner. Alembic matters more here than usual — see handover below |
| Jobs | **SQLite `runs` table + in-process asyncio worker** | Local LLM calls take seconds to minutes; you need async. But no Redis/Celery — one container, restart-safe, and a queue Claude can reason about in one file |
| Quality gates | ruff, mypy, pytest, pytest-cov, pre-commit, GitHub Actions | Same as today |
| Packaging | Multi-stage Dockerfile + compose (`app` + `ollama`) | Mirrors the existing setup |

### Alternates worth knowing

- **Streamlit** instead of NiceGUI *if* the UI really is only "paste text → run →
  review table" (simpler, more training data behind it, `AppTest` for headless
  tests). Its whole-script-rerun model fights you the moment background jobs
  appear — which they do here.
- **LiteLLM** instead of the raw `openai` SDK *if* routing ends up spanning
  genuinely different backends rather than just different Ollama models.

---

## Shape of the app

```
Input text ──> ingest (docs table, raw text preserved verbatim)
                 │
                 ├─> job enqueued in `runs` (pending)
                 │
   asyncio worker ──> ExtractionEngine
                        ├─ prompt template (versioned, on disk)
                        ├─ Pydantic schema ──> JSON Schema ──> Ollama
                        └─ validated model instance
                 │
                 └─> extractions table (+ full provenance)
                        │
   NiceGUI ───────────> review / correct / re-run / compare models
   FastAPI /api/v1 ───> same data as JSON, for scripts and MCP later
```

---

## The three decisions that actually matter

### 1. One `LLMClient` seam, and everything crosses it

Define a narrow protocol — `async def extract(text: str, schema: type[T], model: str) -> Extraction[T]`
— and let *nothing else* in the codebase import `openai` or `ollama`.

This is the single most valuable line to draw: it makes the whole app testable
without a GPU, makes swapping models a config change, and gives Claude an obvious
place to work when the staff say "try a different model."

### 2. Store provenance, not just results

Every extraction row should carry:

- source doc id
- model name **and digest**
- prompt template version
- temperature / seed
- the raw JSON string the model emitted
- validation outcome
- token counts, latency

Without this you cannot answer *"did the output change because of the prompt or the
model?"* — which is **the** question non-technical staff will ask, repeatedly. It
also lets you re-run the same corpus across models and diff the results, which is
the app's real superpower.

### 3. Never overwrite an extraction

New run → new row, with `runs.id` as the discriminator. Immutable extraction
history costs one column and buys comparison, audit and rollback for free.

---

## Testing — five layers, and one that's unusual

The first four are conventional and should gate every commit:

1. **Unit** — schema validation, chunking, prompt rendering. Milliseconds.
2. **Fake-LLM integration** — the full pipeline against a `FakeLLMClient` returning
   canned payloads (including malformed ones, to prove the failure path). No Ollama
   needed, runs in CI.
3. **Cassettes** — real Ollama responses recorded once to JSON fixtures, replayed
   forever. Catches "does our parsing survive what this model actually emits."
4. **UI** — NiceGUI `User` fixture drives the real UI in-process, asserting on
   rendered elements. Headless, fast, no browser.

The fifth is the one that keeps quality from silently rotting under non-technical
maintenance:

5. **Eval suite.** A `tests/eval/` corpus of 30–100 hand-labelled documents with
   expected field values, behind `@pytest.mark.eval`, run against real Ollama. It
   reports per-field precision/recall per model and **fails if accuracy drops more
   than N% below the committed baseline** (`evals/baseline.json`, checked in).
   Excluded from the default `pytest` run; wired into a nightly CI job and a
   `just eval` command.

**Why this matters:** a well-meaning prompt tweak that improves one document and
quietly breaks fifteen is invisible to unit tests. The eval gate is what makes it
safe for someone who can't read the code to change the prompt — Claude proposes the
edit, the eval either backs it or blocks it.

---

## Making the handover survivable

- **`just` as the entire interface.** `just dev`, `just test`, `just eval`,
  `just fmt`, `just migrate`, `just docker`. Six commands is a learnable surface;
  `uv run alembic upgrade head` is not.
- **CLAUDE.md with a hard "Do NOT" list**, exactly like the current one. The
  invariants here: never bypass `LLMClient`; never mutate an extraction row; never
  edit an existing migration; never widen a schema without a migration *and* an
  eval re-baseline.
- **ADRs in `docs/adr/`** for the load-bearing choices (why Ollama, why constrained
  decoding, why extractions are immutable). Future-Claude reads these instead of
  re-deriving them wrongly.
- **Claude Code hooks**: a `PostToolUse` hook running `ruff check --fix` + `mypy` on
  edited files, and a `Stop` hook running the fast test suite. The staff get
  correctness feedback without knowing what mypy is.
- **Devcontainer + committed `uv.lock`** so setup is one click and byte-identical
  everywhere.
- **Branch protection**: green CI required. Non-negotiable, and it's the thing that
  actually holds the line.

---

## Docker notes

Multi-stage: `uv sync --frozen --no-dev` in a builder, copy the venv into a slim
runtime, non-root user, `/data` volume for `db.sqlite`. Compose runs `app` +
`ollama` with a named volume for model weights.

⚠️ **GPU passthrough to a container works on Linux (nvidia-container-toolkit) but
not on macOS.** On a Mac, Ollama must run on the host and the container talks to it
via `host.docker.internal:11434`. Make the Ollama base URL an env var from day one
and this is a config line rather than a crisis.

---

## Model choice

For schema-constrained extraction, a 7–14B instruct model at Q4_K_M is usually
enough — the Qwen3 and Mistral Small families are the strong candidates, with
Gemma 3 as a lighter option.

Don't guess: pick three, run the eval suite, keep the cheapest one that clears the
accuracy bar. That comparison is exactly what the provenance columns are for.

---

## What to build first

1. Skeleton: uv + FastAPI + NiceGUI in one process, SQLite + first migration,
   `just` recipes, CI green on an empty test suite.
2. `LLMClient` protocol + Ollama implementation + `FakeLLMClient`, with tests for
   both.
3. One real extraction schema end-to-end, immutable results with full provenance.
4. NiceGUI screens: upload/paste, run, review table, per-run detail.
5. Eval harness + first baseline.
6. Docker + compose.
7. CLAUDE.md, ADRs, and a handover runbook — written last, when the invariants are
   real.

Steps 1–3 are where the architecture is decided; everything after is filling in.

---

## Open questions

- **Input format** — genuinely plain text, or does it include PDFs/DOCX? If the
  latter, add `docling` at the ingest boundary. That's a meaningful extra layer,
  not a library swap.
- **Deployment shape** — single-user local, or multi-user on a shared box? The
  latter pulls in auth and pushes SQLite harder, though WAL handles it fine at this
  scale.

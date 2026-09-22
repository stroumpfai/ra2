# plan-evaluation-view-improvements.md — five changes to the Evaluation screen

**Status.** Written 2026-09-22 against `c41b860`, from five requests made
directly against the running screen rather than from a reproduced defect.
Authority as always: `mvp-spec.md` on *what*, `sw-design.md` on *how*
(CLAUDE.md). Four of the five are presentation; the fifth is a pinned input
and therefore costs **one Alembic revision** and **four frozen files**, under
[`contracts/amendments/feat-evaluation-view-improvements.md`](contracts/amendments/feat-evaluation-view-improvements.md).
Branch `feat/evaluation-view-improvements`; no wave is running, so the
amendment is applied in the same commits (the standing practice since
`fix-b1-census-value-samples`).

---

## 1. What was asked, and what was settled

| # | Asked | Settled as |
|---|---|---|
| a | Latency in seconds, max two digits | Seconds to **two decimal places**, everywhere latency is rendered — not only on this screen |
| b | Drop the prompt-template explainer under the reproducibility card | Deleted: constant, element, `__all__` entry, and both tests flipped to assert its absence |
| c | Local time everywhere | Every rendered timestamp converts to the **host's** zone at the render site. Stored, exported and API values stay UTC |
| d | A reasoning on/off parameter in the front end | The **four-level ladder** (`none · low · medium · high`), as a per-evaluation pinned input in step 5, beside temperature and seed |
| e | Drop the "already frozen" note under step 2 | Deleted, the same four places as (b) |

Two of these were decided rather than implied, and the decision is the
interesting part of each.

**(c) is host-local, not analyst-local.** RA2 is a loopback-only desktop
application (N1): the browser and the server are the same machine, so
`datetime.astimezone()` with no argument — the process's own zone — is the
analyst's zone, and no timezone setting, no browser round trip and no
`Settings` field is needed to get there. The moment that stops being true is
the moment this app has a network listener, which mvp-spec.md §19.10 forbids.

**(d) belongs to the evaluation, not to the process.** `RA2_LLM_REASONING_EFFORT`
was pinned on the `run` row three commits ago (`090e7fdc12c5`) precisely
because "two runs that asked different questions must not record identical
provenance" (§19.8). Its own docstring then names the workflow it cannot
support: *"set `high` and launch a second evaluation to compare"* — which
today means editing the environment and restarting the app between two
evaluations that are supposed to be comparable. A pinned input that decides
the answer as much as temperature does, and that the analyst is expected to
vary *between evaluations*, is a column on `evaluation` and a control in step
5. That is the whole of (d); everything below is the cost of saying it.

The ladder rather than a checkbox: `REASONING_EFFORTS` is already
`none | low | medium | high` — what Ollama maps — and `run.llm_reasoning_effort`
already stores the word. A checkbox would store `high`, render `on`, and then
disagree with provenance about what was asked.

---

## 2. Latency in seconds (a)

Three call sites render a latency, all of them in `ui/`:

| Site | Before | After |
|---|---|---|
| `ui/components/progress_card.py` `_metrics_line` | `median latency 812 ms` | `median latency 0.81 s` |
| `ui/views/results/ranking_tab.py` | `104 ms` | `0.10 s` |
| `ui/components/ollama_settings.py` `PROBE_WORDS[OK]` | `Reachable — 3 models, 12 ms.` | `Reachable — 3 models, 0.01 s.` |

One formatter, `primitives.format_latency_ms`, so the three cannot drift:

```python
def format_latency_ms(ms: int) -> str:
    """`812` -> `"0.81 s"`. Two decimals, always."""
```

**Why seconds are right here and `_format_duration_ms` is not.** The progress
card already has a duration formatter — `1 min 40 s` — and it is deliberately
not reused: it is for *spans a person waits out* (elapsed, ETA), where minutes
are the unit, and it renders a sub-second value as `0 s`. A latency is a
**measurement being compared between models**, which is what the Ranking
column exists for, and a comparison needs a fixed unit and fixed precision.
Two decimals is that: on the reporting host the interesting range is 6 s
against 190 s, and on a GPU host it is 0.4 s against 2 s — one format spans
both without a unit switch that would make a column of numbers
incommensurable.

**The one sharp edge, named.** A connection probe answers in single-digit
milliseconds, and `0.003 s` rounds to `0.00 s`, which reads as *zero* rather
than as *instant*. Anything greater than zero that rounds to `0.00` renders
`< 0.01 s` instead. This is the same rule `SuppressedCell` follows one layer
up — never print a number that says something the datum does not.

`design/prompt-evaluation/README.md` §2 and `design/results/README.md` §4
quote `812 ms` and `104px, right` in their copy examples and are **left
alone**. The design READMEs are the handoff record of what was drawn, not a
live spec — nothing in the repo edits them, and `SD3` (vendored fonts against
the README's Google Fonts) is the standing precedent for how a deviation from
them is recorded. It goes in `sw-design.md` §13 instead, as `SD37`, which is
where anyone asking "why does this not match the mock" is sent.

---

## 3. Two explanatory paragraphs removed (b, e)

`FEATURE_SET_NOTE` (step 2) and `PROVENANCE_EXPLAINER` (under the
reproducibility card) are deleted outright — constant, `__all__` entry,
rendered element, `data-testid`, and every assertion on them.

Both were written to correct or expand something. `FEATURE_SET_NOTE` replaced
the design's stale "Freezes when the first run executes" (plan-phase-3.md
C5/R6); `PROVENANCE_EXPLAINER` explained *why* a prompt template is versioned
separately. Neither statement stops being true — they stop being **new** on
the twentieth viewing, and the setup column is six steps deep in a 430px
column where every line of explanation pushes the Launch button further down.
The facts survive where they are load-bearing: step 2 still offers only frozen
sets (the service refuses an unfrozen one at launch, `EVAL_ERROR_CONFIG_NOT_FROZEN`),
and the reproducibility card still *renders* the template version and
fingerprint on its provenance line.

The module docstring's "Three places this file departs from the drawn board"
section keeps its entry for the step-2 copy, rewritten: the departure is now
that the note is **not rendered at all**, and the reason the design's own
sentence was wrong is still worth recording — it is the argument that stops
the next agent reinstating it from the mock.

`tests/ui/test_evaluation_view.py` and `tests/e2e/test_j10_evaluation.py`
keep their assertions rather than dropping them: both flip to
`to_have_count(0)` / `not _find(...)`. A deleted element with no test is an
element that comes back.

---

## 4. Local time everywhere (c)

Every stored timestamp is **aware UTC** — `UtcDateTime` guarantees it at the
persistence boundary, for the reason its docstring gives — and every read
model therefore hands `ui/` an aware value. So this is a one-line change at
each render site, and the only risk is missing one:

| Site | Renders |
|---|---|
| `ui/views/evaluation_view.py` `_timestamp` | runs table, launched / finished |
| `ui/views/results/__init__.py` `_launched_text` | the results header |
| `ui/views/import_view.py` | delivery `imported_at` |
| `ui/views/prompts_view.py` | template `created_at` |
| `ui/views/mismatches_view.py` (×2) | run `finished_at`, analyst tag stamp |
| `ui/components/feature_sets_table.py` (×2) | set `created_at`, date and time |

All eight go through one helper, `primitives.format_local`, which takes the
value and the format string and does the conversion:

```python
def format_local(value: datetime, fmt: str) -> str:
    """The host's own zone (`astimezone()` with no argument), then `strftime`.
    A naive value is read as UTC — the one thing `UtcDateTime` guarantees."""
```

The naive branch is not defensive padding: `ui/` also renders values that
never went through the ORM (a fresh `Clock.now()` is aware, but a test double
or a future read model need not be), and reading a naive value as *local*
would silently shift it by the host's offset. Reading it as UTC is the
assumption the whole codebase already makes.

**Not changed, deliberately:** the API's ISO-8601 responses, the CSV exports
and the log records. Exports are the artefact a result is reproduced from, and
a UTC instant is the only value two hosts agree on — which is the reason
`Clock.now()` is UTC in the first place (`infra/clock.py`). Local time is a
property of *reading a screen*, and it stops at the screen.

---

## 5. Reasoning effort as a per-evaluation input (d)

### 5.1 The column

```
evaluation(… , prompt_language, temperature, seed, reasoning_effort, size, …)
          -- one of none|low|medium|high; NOT NULL, default 'none'
          -- editable while launched_at IS NULL; immutable after (SD13)
```

`NOT NULL` with a default, unlike `run.llm_reasoning_effort` which is
nullable. The two nullabilities say different things and both are right: a
`run` row written before `090e7fdc12c5` genuinely does not know what effort it
used, and guessing would be inventing provenance; an `evaluation` row, by
contrast, is a *setup*, and every existing one ran under the process default —
`none`, which is `Settings`' default and what the backfill therefore writes.

Migration: one revision, `add_reasoning_effort_to_evaluation`, `batch_alter_table`
(SQLite), `server_default='none'` on add so existing rows backfill in the same
statement, then the default dropped is **not** attempted — SQLite batch-rebuild
makes that a second table copy for no gain, and a server default that matches
the model default is not a hazard.

### 5.2 The route from the column to the call

Seven files, in the order the value travels:

1. `persistence/models.py` — the column (frozen, amendment §1).
2. `services/readmodels.py` — `EvaluationDraftView.reasoning_effort`, and
   `_draft_view` reads it (frozen, amendment §2).
3. `services/evaluation_service.py` — `update_draft(reasoning_effort=…)`,
   validated against `REASONING_EFFORTS`, and `_new_run` writes it onto the
   run row beside `temperature` and `seed`. **Validated in the service, not in
   the view**: the view may not import `infra`, and "which efforts exist" is
   not a fact `ui/` is allowed to hold (Do-NOT #7). The vocabulary itself
   moves from `infra/config.py` to `domain/llm.py`, where `domain` can own it
   and `services`, `infra` and `api` can all read it — the same move
   `is_loopback_url` made, for the same reason.
4. `api/schemas.py` + `api/v1/evaluations.py` — the field on the update
   request and on both draft responses (frozen, amendment §3).
5. `domain/llm.py` — `LLMClient.extract` gains `reasoning_effort: str | None = None`
   (frozen, amendment §4).
6. `infra/ollama_client.py` — the per-call value when given, the constructed
   one when `None`. The constructor argument **stays**: it is the process
   default a run created before this change still needs, and it is what
   `main.py` wires from `Settings`.
7. `services/run_service.py` — `_RunPlan.reasoning_effort`, read from the
   **run** row (not the evaluation's — the run's copy is the provenance it is
   reproducible against, exactly as temperature and seed are), passed to
   `extract`. `_start`'s existing fallback to `Settings` stays for rows queued
   before the migration.

### 5.3 The control

Step 5 becomes three fields — Temperature, Seed, Reasoning — in the row that
currently holds two. A `_select` over the four values, disabled by
`self._locked` like every other control in the column, saved through
`_update(reasoning_effort=…)` on change, exactly as temperature is (the view's
"every step persists as it is chosen" rule, module docstring).

`DETERMINISM_NOTE` gains one clause: what `none` buys. The measurement is
already recorded in `Settings.llm_reasoning_effort`'s docstring — 190 s against
6 s on the same record — and an analyst choosing `high` from a three-item
dropdown with no warning is choosing a thirty-fold cost blind. The note says
it in one sentence; it does not repeat the table.

The provenance line already renders `reasoning <effort>` and needs no change,
which is the sign the column landed in the right place.

---

## 6. Frozen files, and the amendment

Four, all listed in `CONTRACTS.md`:

| File | Change |
|---|---|
| `ra2/persistence/models.py` | `evaluation.reasoning_effort` |
| `ra2/services/readmodels.py` | `EvaluationDraftView.reasoning_effort` |
| `ra2/api/schemas.py` | the field on `UpdateEvaluationRequest`, `EvaluationDraftResponse` |
| `ra2/domain/llm.py` | `extract(…, reasoning_effort=None)`; `REASONING_EFFORTS` moves here |

`ra2/infra/config.py` is frozen too but does not change shape:
`llm_reasoning_effort` stays exactly as it is, as the process default, and its
validator re-imports the vocabulary from `domain`.

Both authority documents are corrected **in the same commit**, which is the
CLAUDE.md rule for a document that has gone stale:

- `sw-design.md` §15.2 (the schema block), §15.5 (the `extract` signature,
  which that section asserted was "unchanged since phase 1" and now is not),
  and two new §13 entries — **`SD36`** for the pinned input and the protocol
  keyword, **`SD37`** for §2's latency unit, §4's local time and §3's two
  deleted paragraphs.
- `mvp-spec.md` §3's protocol snippet, §5's `evaluation` table, and §5's
  `run` table plus §19.8's provenance list — both of which still omitted
  `llm_reasoning_effort` from `090e7fdc12c5`, which this change makes
  central.

---

## 7. Tests

Per layer, in the layer that owns the fact (sw-design.md §11):

| Layer | Test |
|---|---|
| `tests/ui/test_components.py` | `format_latency_ms` at 812 / 104 / 12 / 3 / 0 ms; the metrics line reading `median latency 0.81 s`; `probe_sentence` in seconds |
| `tests/ui/test_components.py` | `format_local` on an aware UTC value equals the same instant `.astimezone()`'d — **computed, not hard-coded**, so the assertion holds in any CI zone; and on a naive value, read as UTC |
| `tests/ui/test_evaluation_view.py` | both notes gone; the reasoning select renders the draft's value, changing it persists, and it is disabled once launched |
| `tests/ui/test_results_view.py` | the Ranking latency cell in seconds |
| `tests/backend/services/evaluation/…` | `update_draft(reasoning_effort=…)` persists; an unmappable value is refused; `launch` copies the evaluation's effort onto every run it creates |
| `tests/backend/services/run/…` | the value reaches `FakeLLMClient.extract` as the run's own, not as `Settings`' |
| `tests/backend/api/evaluations/…` | the field round-trips through `PUT` and both responses |
| `tests/backend/infra/test_ollama_client.py` | the per-call effort is what is sent; `None` falls back to the constructed one |
| `tests/e2e/test_j10_evaluation.py` | the two notes absent; the reasoning select present, and locked after launch |

`tests/fixtures/fake_llm.py` records the effort on `calls` — the double's
tuple grows a field, which is the only reason any existing run test changes.

## 8. What this plan does not do

- **No timezone setting.** §4 says why. A setting here would be a second
  source of truth for something the OS already answers.
- **No per-run effort.** The ladder is pinned at the evaluation, and every run
  in one evaluation asks the same question — which is the definition of the
  evaluation ("only the model varies", the toolbar's own line).
- **No change to `RA2_LLM_REASONING_EFFORT`.** It stays as the default a new
  draft is created with, so an analyst who has set it keeps getting it.

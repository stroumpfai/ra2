# plan-settings-with-no-reader.md — a setting that implies a control nobody implemented

**Status.** Written 2026-09-27 against `8adf7d0`, out of the parameter
inventory in `plan-settings-in-the-app.md` §11 — which is **paused** until this
lands. Nothing here is built yet. Authority as always: `mvp-spec.md` on *what*,
`sw-design.md` on *how* (CLAUDE.md). **No migration** — every column this plan
needs already exists. One amendment file, named in §6.

---

## 1. The pattern was already named

`docs/risk-assesment.md` G3, verbatim:

> *A pattern worth naming once.* `Settings.host`, `Settings.port`, the deleted
> `Settings.exports_dir` (§8.6) and `scripts/dev_agent.py`'s `RA2_PORT` — set in
> the environment, read by nothing — are four instances of **a setting that
> implies a control nobody implemented**. §8.6 called this shape out for
> `exports_dir`; it is a category, not an instance. **One contract test would
> close it: every `Settings` field has a reader in `ra2/`, or it does not
> exist.**

That sentence is this plan. `exports_dir` was closed by deletion (`SD30`); the
rest are open, and the inventory found a fifth the report had not:
`Settings.min_cell_count`, which is worse than the others because the
capability it implies is one `mvp-spec.md` promises by name.

**Why it is worth a slice rather than a cleanup commit.** Each of these is a
line in `sw-design.md` §10 and a row in the README's configuration table. An
analyst — or a reviewer, or the next agent — reads those tables and believes
them. A knob that does nothing is not a cosmetic defect; it is documentation
that lies, and in `host`'s case it is documentation that lies **about the
deployment posture** (A4).

## 2. The instances

| # | Setting | Documented as | Actually | Evidence |
|---|---|---|---|---|
| 1 | `Settings.host` | "bind to loopback by default (N1)" | **no reader in `ra2/`**; the bind is the `justfile`'s `--host 127.0.0.1` | A4, G3, re-verified at `12268ed` and again here |
| 2 | `Settings.port` | the same | **no reader in `ra2/`**; the bind is `--port 8080` | same |
| 3 | `Settings.min_cell_count` | §10: "D3, unused until scoring"; `models.py:716`: the column is "defaulted from `config.min_cell_count` when the draft is created" | **no reader anywhere.** No code defaults the column from it, and there is no control, so `evaluation.min_cell_count` is `20` for every evaluation on every host | §4.3 |
| 4 | `scripts/dev_agent.py`'s `RA2_PORT` | the isolated port | set in the child environment **and ignored** — the same line passes `--port` on the command line | `scripts/dev_agent.py:37` vs `:80` |

Instance 4 is not a separate defect. It is instance 2 seen from the other side:
`dev_agent.py` sets the variable the app *ought* to read, then works around the
app not reading it. Fixing 2 fixes 4 by deletion.

### 2.1 What is **not** an instance

**`Settings.run_concurrency` is fine and this plan does not touch it.** The
inventory in `plan-settings-in-the-app.md` §11.1 and §11.5 called it "a
constant behind a guard" and recommended deleting it. That was wrong on the
evidence:

- it **has** a reader — `run_service._execute_serially`, at `run_service:375`;
- the refusal is **tested** — `test_run_concurrency_above_one_is_refused_not_silently_ignored`;
- and `sw-design.md` §15 F7 states the intent: the setting exists so that
  lifting the limit "is a config line rather than a rewrite".

A forward-declared setting with a reader, a refusal and a test is the opposite
of this pattern — it is `RA2_LLM_BASE_URL` in phase 1 (N2: "present from commit
1, unused in phase 1"), which is an established and deliberate shape here. The
two rows in the paused plan are corrected in the same commit as Stage 1.

## 3. The decisions

**D1. The rule is G3's sentence, and the gate is one contract test.** *Every
`Settings` field has a reader in `ra2/`, or it does not exist.* Stated as
`SD42`, enforced by `tests/test_settings_have_readers.py` (§4.1). The test is
the deliverable; the three fixes below are what it takes to make it green.

**D2. `host` and `port` get a reader, rather than being deleted.** A4 weighs
both and says which: *"Either make the server read `Settings.host` (and refuse
a non-loopback bind the way the LLM client refuses a non-loopback endpoint), or
delete the two settings so they stop implying a control that is not there.
**The first is better: it makes the deployment posture testable.**"*

Deleting is cheaper and would close the pattern just as well, and it is the
wrong trade here for a reason the deletion cannot reach: today **nothing
refuses `--host 0.0.0.0`** — not code, not a test, not a contract. Deleting the
settings leaves that true and removes the last place in the codebase where
anyone would think to look. Wiring them makes N1's bind half enforceable by the
same mechanism as its egress half, which is the one thing the loopback rule was
missing.

**D3. The refusal lives in the launcher, because that is where the bind is
decided.** `ra2/cli.py` grows a `serve` subcommand — a composition root, wiring
only — that reads `Settings`, refuses a non-loopback `host` against
`domain.llm.LOOPBACK_HOSTS`, and calls `uvicorn.run`. `create_app()` cannot do
this: it does not know, and cannot know, what address the server it is handed
to will bind. **No opt-out setting**, for `require_loopback`'s reason: an
opt-out is how "no data leaves the host" becomes "no data leaves the host by
default".

**D4. `LOOPBACK_HOSTS` is reused, not re-derived.** It is already public in
`domain/llm.py` (`__all__`, line 30) and is "the **one** statement of the
rule". The launcher compares `settings.host.lower()` against it — no DNS, no
`getaddrinfo`, for `classify_endpoint`'s stated reason: a name that resolves to
loopback today resolves wherever its owner points it tomorrow. **This needs no
amendment to `domain/llm.py`.**

**D5. `min_cell_count` is repaired at both ends, and the ends are separable.**
The reader (`evaluation_service` seeds the draft from `Settings`, which is what
`models.py:716` has always claimed) is Stage 2 and closes the pattern. The
control on step 5 — `mvp-spec.md` §11.4's "configurable **per evaluation**" —
is Stage 5 and closes the spec. Stage 5 can be dropped at the gate without
reopening Stage 2.

**D6. No column, no migration, no schema change.** `evaluation.min_cell_count`
has existed since `e5145f27bf8c` and is read by `results_service`,
`ranking_service` and three tabs. Nothing about this plan is a database change,
which is why it is small.

**D7. `dev_record_max` and `eval_record_min` are left alone.** They have
readers, so the pattern does not reach them; the inventory's separate point —
that a host which quietly lowered `eval_record_min` would publish dev-sized
numbers as results — is a policy question for `mvp-spec.md` §9, not a wiring
defect. §9.

---

## 4. The design, in detail

### 4.1 The gate: `tests/test_settings_have_readers.py`

For every field on `Settings`, the test requires **one** of:

1. a **direct reader** — the token `.<field>` appears in `ra2/` outside
   `infra/config.py`; or
2. a **named property** on `Settings` whose body reads the field, where that
   property itself has a direct reader.

Case 2 is not an escape hatch with a free-text reason — it is a second lookup
that must also pass. It exists because three fields are genuinely consumed
through a property and would otherwise need a fake reader to satisfy the test:

| Field | Consumed through |
|---|---|
| `db_path` | `database_path` → `database_url` |
| `data_dir` | `deliveries_dir`, `codelists_dir` (**and** directly, in `main.py`) |
| `max_upload_mb` | `max_upload_bytes` |

The failure message names the field and quotes `SD42`, because the next person
to hit this will be adding a setting, and the useful sentence is *"give it a
reader or do not add it"*.

**It is a text scan, and that is deliberate.** An import-graph or runtime check
would miss a field read once at startup and prove nothing about a field read
nowhere; the defect being closed is literally *"the name appears in no source
file"*. `scripts/check_no_real_data.py` and `test_p5_contract.py`'s chain walk
set the precedent for a contract test that reads the tree.

### 4.2 The bind

```
just dev        →  uv run python -m ra2.cli serve
just dev-agent  →  scripts/dev_agent.py  →  RA2_HOST/RA2_PORT  →  ra2.cli serve
```

`serve` is **wiring only** (CLAUDE.md: `cli.py` is a composition root): build
`Settings`, refuse a non-loopback host, `uvicorn.run(create_app, ...)`. The
`--host`/`--port` flags leave the `justfile`; the three recipes that carry them
(`dev`, `dev-reload`, and `dev_agent.py`'s argv) read the settings instead, so
the documented default and the actual bind become the same fact.

`dev_agent.py` keeps `_free_port()` and keeps setting `RA2_PORT` — it stops
passing `--port`, and the variable it has always set starts being the one that
decides.

**`tests/e2e/conftest.py` does not change and must not.** It builds
`create_app(...)` with substituted adapters and drives
`uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=_free_port()))`
in-process. A test harness choosing its own port is not a deployment, the
refusal is not being bypassed, and adding a launcher to the E2E path would only
put a second way to start the app under test.

### 4.3 `min_cell_count`, both ends

**The reader (Stage 2).** `evaluation_service`'s draft creation passes
`min_cell_count=self._settings.min_cell_count` where it already passes
`temperature=_DEFAULT_TEMPERATURE` and `seed=_DEFAULT_SEED`. One line. The
column's own `default=20` stays as the database's answer for a row written
around the service.

**The control (Stage 5).** A number input on step 5, beside temperature, seed
and effort — the three it most resembles: a pinned input, set before launch,
recorded in provenance. It is **undesigned** (`design/prompt-evaluation/README.md`
draws three decoding controls, not four), so it is built to this plan's own
design on `P3-D19`'s precedent, which settled the same question for the
settings dialog.

Two things make it cheap and one makes it careful:

- Cheap: suppression is applied at **read** time from stored `n` (`SD19`), so
  the floor never re-scores anything, and the whole read path already honours
  the column.
- Cheap: `results_service`, `ranking_service` and the three tabs already render
  from `evaluation.min_cell_count`, so a changed value is visible with no
  further work.
- Careful: step 5's layout is asserted in E2E at the drawn width (sw-design
  §8.2). §8 carries the risk.

---

## 5. The stages

Each is a commit; each leaves `just lint` and `just test` green.

### Stage 1 — the rule, before the code

- `sw-design.md`: **`SD42`** — *every `Settings` field has a reader in `ra2/`,
  or it does not exist* — plus §10's table gaining the `min_cell_count` row's
  correction and losing "unused until scoring".
- `docs/risk-assesment.md`: A4 and G3 record what is being built against them.
- `plan-settings-in-the-app.md` §11.1 and §11.5: the two `run_concurrency` rows
  corrected (§2.1), and its `SD42` renumbered to **`SD43`**, since this slice
  ships first.
- `contracts/amendments/fix-settings-with-no-reader.md`, and this plan's
  `CONTRACTS.md` section.

**Exit:** no code changed; no document claims a knob that does nothing.

### Stage 2 — `min_cell_count` gets its reader

- `evaluation_service`: the draft seeds the column from `Settings`.
- `README.md` and §10 stop describing it as unused.

**Exit:** `RA2_MIN_CELL_COUNT=30` produces a draft whose floor is 30 and whose
Results tabs suppress at 30. Backend tests per §7.

### Stage 3 — `host` and `port` get their reader

- `ra2/cli.py`: `serve`, with the loopback refusal (D3, D4).
- `justfile`: `dev` and `dev-reload` call it; the `--host`/`--port` flags go.
- `scripts/dev_agent.py`: drops `--port`, keeps `RA2_PORT`.

**Exit:** `RA2_PORT=9001 just dev` binds 9001; `RA2_HOST=0.0.0.0` is refused
before a socket is opened, and the refusal names N1. Backend and script tests
per §7.

### Stage 4 — the gate

- `tests/test_settings_have_readers.py` (§4.1), green because Stages 2 and 3
  landed.

**Exit:** G3's category is closed mechanically, not by review. Adding a
`Settings` field with no reader now fails the build.

### Stage 5 — the spec's "configurable per evaluation", and seen working

- The step-5 control (§4.3), its UI test and its E2E.
- `just dev-agent` in a **throwaway `RA2_DATA_DIR`** (never the real one,
  Do-NOT #13): set the floor to 3 on one evaluation and 20 on another over the
  same seeded corpus, and read the two Results tabs against each other.
- `README.md`'s configuration table and `docs/risk-assesment.md` A4/G3 close.

**Exit:** `mvp-spec.md` §11.4 is reachable from the product.

---

## 6. Frozen files, and the amendment

One amendment file, `contracts/amendments/fix-settings-with-no-reader.md`,
applied in the stage whose code needs it.

| File | Change | Stage |
|---|---|---|
| `ra2/infra/config.py` | **docstring only** — `min_cell_count` is the draft default, `host`/`port` are the bind. No field, default or validator changes | 1 |
| `ra2/cli.py` | + the `serve` subcommand and its loopback refusal — wiring only, it is a composition root | 3 |
| `justfile` | `dev` and `dev-reload` call `ra2.cli serve`; the two flags go. "Final" has been amended four times; it means *by amendment only* | 3 |
| `ra2/services/readmodels.py` | + `EvaluationDraftView.min_cell_count`, defaulted — the draft view is how step 5 learns the floor | 5 |
| `ra2/api/schemas.py` | `min_cell_count` on the draft update request and the draft response. `evaluations.py:279` does update drafts, so the API gets the field the view gets | 5 |

Not frozen, and changed: `ra2/services/evaluation_service.py` (its header:
"Not frozen."), `scripts/dev_agent.py`, `ra2/ui/views/evaluation_view.py`,
`sw-design.md`, `README.md`, `docs/risk-assesment.md`,
`plan-settings-in-the-app.md`.

*Corrected in Stage 1:* this table first listed `evaluation_service.py` as
frozen and `cli.py` as not — backwards on both, by their own first lines — and
missed `readmodels.py`, which Stage 5 needs because `EvaluationDraftView` has
no floor to show.

**Not changed, deliberately:** `ra2/domain/llm.py` (D4 reuses the public
`LOOPBACK_HOSTS`), `ra2/persistence/models.py` (D6, no schema change),
`tests/conftest.py` (§7.1), `tests/e2e/conftest.py` (§4.2).

---

## 7. Tests

### 7.1 Existing tests, and what happens to them

| Test | Change | Why |
|---|---|---|
| `tests/conftest.py`'s `settings` fixture | **none** | It clears `RA2_HOST`, `RA2_PORT` and `RA2_MIN_CELL_COUNT` from the ambient environment. All three remain fields, so the list is still right — and it matters *more* after Stage 2, because a developer's own `RA2_MIN_CELL_COUNT` would now reach a draft. The frozen file needs no amendment |
| `tests/e2e/conftest.py` | **none** | §4.2 — it constructs the app and its own server; the launcher is not on its path |
| `tests/backend/services/run/test_guards.py` | **none** | §2.1 — `run_concurrency` keeps its reader, its refusal and this test |
| `tests/ui/test_results_view.py`, `tests/fixtures/scored_corpus.py` | **none** | They pass `min_cell_count=20` explicitly, which is what a fixture should do; Stage 2 changes the *default*, not the argument |
| `tests/backend/services/evaluation/…` draft assertions | **updated** | Any that assert a draft's floor now assert it against the settings value rather than a literal `20` |
| `tests/e2e/…` step-5 layout | **updated** | Stage 5 adds a fourth control to a card whose geometry is asserted (§8) |

### 7.2 New tests

| Test | Layer | What it pins | Stage |
|---|---|---|---|
| `test_every_settings_field_has_a_reader` | contract | `SD42` — G3's sentence, mechanically. **The test this plan exists for** | 4 |
| `test_a_field_read_only_through_a_property_passes_through_that_property` | contract | §4.1 case 2 is a second lookup, not a free-text allowlist — the exemption cannot be widened by writing a reason | 4 |
| `test_a_settings_field_with_no_reader_fails_the_contract` | contract | The gate actually fails: a synthetic field with no reader is detected, so the test cannot rot into a tautology | 4 |
| `test_the_draft_floor_comes_from_the_settings` | backend | Stage 2's reader, at the value `models.py:716` always claimed | 2 |
| `test_a_later_settings_change_does_not_move_an_existing_draft` | backend | The seed is read **once**, at `save_draft` — a changed environment moves the next draft, never this one | 2 |

*Changed in Stage 2:* two rows planned here were dropped. "A raised floor
suppresses a cell the default would show" is already pinned from the row
onwards by `test_extraction_tab.py:71` and `test_ranking_tab.py:266`, which set
the column and assert the suppression; the only new link is Settings → row, and
that is the test above. "Pinned at launch" became the once-at-creation test,
because `update_draft` already refuses after launch and that has its own test.
| `test_serve_binds_the_configured_host_and_port` | backend | Stage 3's reader, against a stub `uvicorn.run` | 3 |
| `test_serve_with_nothing_set_binds_what_section_10_documents` | backend | `127.0.0.1:8080` still — `just dev`'s bind did not move, it changed owner | 3 |
| `test_serve_reload_watches_ra2_alone` | backend | `dev-reload`'s `--reload-dir ra2`, kept | 3 |
| `test_serve_accepts_every_loopback_form` | backend | `127.0.0.1`, `localhost`, `LOCALHOST`, `::1` | 3 |
| `test_serve_refuses_a_non_loopback_host_before_binding` | backend | D2–D4 in one parametrized test: `0.0.0.0`, `::`, a LAN address, `127.0.0.1.nip.io` (resolves to loopback, refused because it is compared literally), `127.0.0.2`. **`uvicorn.run` is never reached** | 3 |
| `test_dev_agent_passes_the_bind_in_the_environment_and_not_on_argv` | backend/scripts | Instance 4 closed — and `RA2_HOST` pinned to `127.0.0.1` even when the developer's own environment says `0.0.0.0` | 3 |
| `test_the_floor_control_writes_the_evaluation` | ui | Stage 5's control | 5 |
| `test_step_5_renders_four_pinned_controls_at_the_drawn_width` | e2e | §8's risk, asserted rather than hoped | 5 |

### 7.3 The one test that would have prevented all of this

`test_every_settings_field_has_a_reader` is the whole point, and it is worth
being explicit that it is **cheap and total**: it costs one file, it needs no
fixture, it runs in milliseconds, and it closes a category that has produced
four instances across five phases — one of which (`exports_dir`) was already
found and fixed once without the category being closed behind it.

---

## 8. Risks

| Risk | Why it is small | Cover |
|---|---|---|
| Stage 5's fourth control breaks step 5's asserted geometry | The card is a vertical stack of labelled fields, not a fixed grid; the three it joins are the same shape | `test_step_5_renders_four_pinned_controls_at_the_drawn_width` |
| A text-scanning contract test produces a false positive | The two-case rule (§4.1) is exactly the two ways a field is legitimately consumed, and the third new test proves the gate still fails when it should | §4.1, `test_a_settings_field_with_no_reader_fails_the_contract` |
| Moving the bind into `cli.py` breaks a developer's muscle memory | `just dev` and `just dev-agent` are unchanged at the command line; only what they execute moves | Stage 3 |
| The loopback refusal blocks a legitimate need to bind elsewhere | There is no such legitimate need under N1, and A4 is the record of what happens when one is assumed | D3 — no opt-out, `require_loopback`'s reasoning |
| `RA2_MIN_CELL_COUNT` in a developer's own environment starts reaching drafts | The frozen `settings` fixture already clears it, which is why §7.1 leaves that file alone | §7.1 |

---

## 9. Deliberately not in this plan

- **`plan-settings-in-the-app.md`.** Paused, and renumbered to `SD43`. It moves
  `llm_base_url` and `llm_timeout_s` into a stored, UI-writable table; nothing
  here depends on it and nothing here blocks it.
- **`run_concurrency`.** §2.1 — not an instance, and the paused plan's two rows
  about it are corrected in Stage 1.
- **`dev_record_max` / `eval_record_min` as policy rather than settings** (D7).
  They have readers, so `SD42` is satisfied; whether a host should be able to
  lower the threshold at which numbers stop being called a smoke test is a
  `mvp-spec.md` §9 question and belongs to whoever reopens §9.
- **A4's other two recommendations** — `RA2_IMPORT_ROOT` constraining
  `root_path`, and bounding the host-path walk. Both are real, both are G3's
  other half, and neither is this pattern. Their own slice (§11).
- **Every other setting that should exist and does not.** `SD42` is
  symmetrical, and the candidates are collected in **§11** with a home each —
  one of them is Stage 5, one turns out not to be a setting at all, and one is
  recommended against.
- **Deleting `host`/`port` instead of wiring them.** Considered and rejected on
  A4's own reasoning (D2). It stays the cheaper answer if Stage 3 turns out to
  cost more than it looks.

---

## 10. For the lead, before Stage 1

| # | Question | This plan's answer |
|---|---|---|
| Q1 | Wire `host`/`port` (D2), or delete them? | **Wire, with the refusal.** A4 weighs both and prefers the first because it makes the posture testable — and today nothing anywhere refuses `--host 0.0.0.0` |
| Q2 | Does `min_cell_count` need the step-5 control, or is the host default enough? | **Both, and Stage 5 is separable.** The reader closes `SD42`; only the control makes `mvp-spec.md` §11.4's "configurable per evaluation" true |
| Q3 | Is a text-scanning contract test acceptable as a gate? | **Yes**, and it is the only kind that can see this defect: the failure mode is a name that appears in no source file |
| Q4 | `SD42` here and `SD43` for the paused plan, or the reverse? | **This one first.** It is smaller, it has no migration, and it makes the paused plan's new field satisfy a rule that already exists rather than one added alongside it |
| Q5 | `temperature` and `seed` are hardcoded draft defaults while their sibling `reasoning_effort` is an env setting. Promote the two, or leave the asymmetry? | **Leave it, and document it** (§11.3). The effort's variable has a second job the other two do not have; promoting them would let a host seed drafts off the reproducibility baseline, which provenance would record correctly and therefore never flag |

---

## 11. The other half — settings that should exist and do not

`SD42` is symmetrical. A field with no reader is one defect; a capability with
no field is the other, and the inventory turned up six candidates. They are
collected here so the list lives in the active plan rather than in the paused
one, with each assigned a home. **Only the first is in this plan's scope**;
naming the rest is the point, not building them.

| # | Candidate | Class (§11 of the paused plan) | Home |
|---|---|---|---|
| 1 | A control for `evaluation.min_cell_count` | Experiment | **This plan, Stage 5** |
| 2 | The parallel-calls gate, rendered beside the model | — (a read, not a setting) | Its own slice, and cheaper than it looks — §11.2 |
| 3 | `llm_parallel_calls` as a stored per-model value | Operator | `plan-settings-in-the-app.md` — needs the store |
| 4 | `log_level`, changeable from the app | Operator | `plan-settings-in-the-app.md` — needs the store |
| 5 | `RA2_IMPORT_ROOT` | Host | A4/G3's own slice — a **security control**, not settings hygiene |
| 6 | Draft defaults for `temperature` and `seed` | Experiment | **Recommended against** — §11.3 |

### 11.1 Why most of them are not here

Three of the six (#3, #4, and the useful half of #1) want the same thing: a
setting an analyst can change **from the product**. That mechanism is
`plan-settings-in-the-app.md`, which is paused, and pulling any one of them
forward would drag the whole store, the rebind seam and its migration into a
slice that currently has none. The one exception is #1, and only because
`evaluation.min_cell_count` needs no store at all — the column and its read
path already exist, so the control is the last missing piece rather than the
first.

#5 is a different animal. It is a real missing setting and A4 asks for it by
name, but it exists to constrain an unbounded host-path read, not to correct a
parameter's location. Filing it here would let a security control ride in on a
hygiene slice, which is how a control gets reviewed as a footnote.

### 11.2 The one that turns out not to be a setting at all

`llm_parallel_calls`'s real defect is not that it lives in the environment. It
is that **its evidence and its value sit in different places**: the gate is a
row in `model_qualification` (`SD40`), written by `just qualify-model`, while
the value is a line in a text file — and when the launch pins 1 instead of 4,
it says why in a **log line**, which is the one place an analyst is not
looking.

Rendering the gate beside the model on the Models card — *"4 calls · qualified
2026-09-25"*, or *"serial · no gate on record"* — needs **no new setting, no
store and no migration**. It is a read model reaching a table that already
holds the answer. That makes it strictly cheaper than #3 and worth doing
first; #3 then becomes "and you can change it here", against a card that
already shows what the change would be judged by.

### 11.3 The one to refuse

**`_DEFAULT_TEMPERATURE` (0.0) and `_DEFAULT_SEED` (42) should stay private
constants in `evaluation_service`.**

The symmetry argument for promoting them is real and worth stating, because it
will be raised: `llm_reasoning_effort` is the third member of that trio, it
seeds the same draft from the same call, and it *is* an environment setting. So
two of three sibling defaults are hardcoded and one is configurable.

Resolve the asymmetry by **documenting it, not by widening it**. The effort's
env var is a leftover with a second job: `main.py` still passes it as the
client's default (`SD36` left it there deliberately, so a run queued before the
column existed still asks what `Settings` says). Temperature and seed have no
such second job.

And the cost of promoting them is specific: `0.0` and `42` are the
reproducibility baseline every evaluation starts from. A host that quietly
seeded drafts at `0.7` would produce evaluations that look identical in the UI
to another host's and are not comparable — the failure `mvp-spec.md` §19.8
exists to prevent, arriving through the one door provenance does not watch,
because the *pinned* value would be recorded correctly and only the default
behind it would differ. Stage 1 adds the sentence to `Settings.llm_reasoning_effort`'s
docstring saying which of its two jobs is which, and nothing else changes.

### 11.4 The rule that keeps this list short

Every candidate above arrives, if it arrives, under `SD42`: **a new `Settings`
field ships with its reader, or it does not ship.** That is what makes the
gate worth more than the three repairs under it — this section is a list of
things that may be built later, and the contract test is what stops any of
them being built halfway.

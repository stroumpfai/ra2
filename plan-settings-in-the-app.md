# plan-settings-in-the-app.md — the settings dialog saves

**Status.** Written 2026-09-26 against `8adf7d0`, out of the question *"the
settings are set through a `.env` file; that is not intuitive for an analyst —
should the configuration move to a `config.json` the frontend can edit?"*
Nothing here is built yet. Authority as always: `mvp-spec.md` on *what*,
`sw-design.md` on *how* (CLAUDE.md). One revision, one amendment file, named
in §6.

**Paused 2026-09-27, revisited after `4307b61`.** It waited for
`plan-settings-with-no-reader.md`, now merged, which took `SD42` — *every
`Settings` field has a reader in `ra2/`, or it does not exist*, enforced by
`tests/test_settings_have_readers.py` — and fixed the three dead settings the
§11 inventory found. What that changes here: §11 is updated to the merged
state; §6 is corrected (it had `evaluation_service.py` and `run_service.py` as
frozen, and both say "Not frozen."); D4 now records why the gate stays green;
§4.3 and §7 carry two lessons the floor's control taught; and Stage 5's check
is re-planned, because `just dev-agent` cannot show a value surviving a
restart. **The design itself is unchanged**, and D4's five call sites were
re-verified against `4307b61` — `evaluation_service` ×3, `run_service` ×2.

**Stage 1 done on 2026-09-27** on `feat/settings-in-the-app`: `SD43` with §3's
bootstrap-value paragraph and §10's **Stored** column, E3's *being built*
note, `contracts/amendments/feat-settings-in-the-app.md` and this slice's
`CONTRACTS.md` section. No code changed. Two things moved stage, both so that
no document claims what is not yet true: `config.py`'s docstrings go to Stage
3, and E3's control status to Stage 5 (§5, §6).

**Stage 2 done on 2026-09-27**: `domain/settings.py`, revision `ccbae1b96d1b`
(`app_setting`), `SettingsRepository`, `SettingsService`, `ConnectionSettings`,
`Services.settings`, and the five reads moved off `Settings`. Four decisions
the plan left open are settled in D6, D7 and §4.1: `RunActiveError` is
reused, the refusal is a code, a refused stored row is ignored rather than
fatal, and an unknown key is a log line rather than a `Finding`. `errors.py`
joins the amendment (§5). **`main.py` builds the service but does not load
stored rows yet** — that is Stage 3, beside the rebind, so the Models card
never shows a stored endpoint the client is not using.

**Stage 3 done on 2026-09-27**: `infra/connection.py`'s `OllamaConnection`
wired where the client and catalogue were; `SettingsService` rebinds it on a
save and on a startup load that found stored rows, through a new
`ConnectionRebinder` protocol (amendment §3 — the plan never said how the
service reaches the client, and `one-llm-seam` rules out an import);
`lifespan` loads the stored values before `reclaim_orphans`; `config.py`'s
"this is the seed" docstrings. Proven without Ollama and without a private
attribute: a loopback listener stands in for the stored endpoint, and the
real catalogue connects to it after startup — and does not when the startup
load is removed.

**Stage 4 done on 2026-09-28**: Save saves. The view's handler stores through
`settings_service`, answers a refusal with the dialog's words for its code,
and reloads; nothing on screen tells an analyst to edit a file. **D1 was
wrong that the UI kit needed no amendment** (amendment §6): the dialog called
`on_save` synchronously and closed whatever happened, so an async save would
have been a coroutine nobody awaited, and no save could keep the dialog open
on a refusal. `on_save` is now awaited and answers `None` or a sentence, as
`on_test` already did; the dialog shows the sentence under Save and stays
open.

---

## 1. What is wrong

`ra2/ui/views/evaluation_view.py`, `_save_settings`:

```python
def _save_settings(endpoint: str, timeout_s: int) -> None:
    ui.notify(f"Set RA2_LLM_BASE_URL={endpoint} and RA2_LLM_TIMEOUT_S={timeout_s}, then restart.")
```

Save does not save. The dialog is honest about it — the docstring says so, and
"reports where the change has to be made rather than accepting the edit and
silently dropping it" was the right call for phase 3, which had no service that
could write a setting. It is still the wrong thing to leave in the product:

| Document | Says |
|---|---|
| `vision.md` | analysts who never touch a command line |
| `docs/risk-assesment.md` E3 | "changing the LLM endpoint means editing `.env` and restarting … every such gap routes an analyst back to a developer, and the developer works on the machine holding real data" |
| `SD36` | a setting "the analyst is expected to vary … is a column and a control", said of the reasoning effort, which left the environment for `evaluation.reasoning_effort` for exactly this reason |

E3's cost is not the typing. It is that the one person who can change the
endpoint is the one person who should not be sitting at that machine.

## 2. Why `config.json` is not the answer

The question names the file format, and the format is the smallest of the three
problems:

1. **Nothing in the app can write a setting.** No service, no seam, and `ui/`
   may not reach `infra/`.
2. **`Settings` is constructed once in `create_app()` and injected**, so a
   change needs a restart whatever holds it.
3. The file is a dotfile in the working directory, hidden by Explorer and saved
   as `.env.txt` by Notepad.

A `config.json` fixes (3), partly — a hand-edited JSON file on Windows has the
same discoverability problem and, unlike the `.env`, cannot carry a comment
saying what a key does. It does have one real virtue: a program can safely
round-trip it, where a `.env` cannot be rewritten without losing comments and
order. That virtue is an argument for **a writable store**, not for JSON.

And the codebase has already chosen its writable store twice. `3b7c1d5a92e4`
moved `reasoning_effort` out of the environment into a column; `7d084d5a7dc6`
put this host's model measurements in a table rather than a docstring. The
repository layer, the migrations and the append-only discipline all exist. A
second configuration mechanism beside the environment would add a precedence
rule an analyst has to learn; a table adds none, because the environment stops
being the analyst's business at all.

**So: the store is the database, the surface is the dialog that already exists,
and `.env` keeps exactly the job it is good at** — bootstrap, set by whoever
starts the process.

## 3. The decisions

**D1. The scope is the two settings the dialog already draws** — the endpoint
and the timeout. Not a settings screen. `ollama_settings_dialog`'s frozen
signature is `on_save: Callable[[str, int], None]`, which is already these two
and nothing else, so the UI kit needs no amendment and the analyst gets the
control they were already shown. Everything else is §9.

*Corrected in Stage 4:* the two values fit, but the dialog called `on_save`
synchronously and closed regardless, which cannot carry an async save or a
refusal. `on_save` became awaitable, answering `None` or a sentence
(amendment §6).

**D2. The store is `app_setting`, and it is append-only.** Key, JSON value,
`changed_at`; the newest row per key wins. An `UPDATE` would be the one mutable
row in a schema whose rule is that a re-run adds rows (Do-NOT #2), and the
history is not overhead here: "the endpoint changed on Tuesday" is the first
question asked when a week of runs points at the wrong Ollama.

**D3. A stored value beats the environment; the environment is the seed and the
fallback.** The alternative — env wins — reintroduces the defect being fixed:
on a host where `RA2_LLM_BASE_URL` is set, Save would be accepted and silently
ignored, which is worse than today's refusal to accept it. The fallback keeps
every existing deployment's behaviour on first start, and **isolation survives
by construction**: `just dev-agent` gets a throwaway `RA2_DATA_DIR`, so a
throwaway database, so no stored rows, so its environment applies.

**D4. `Settings` is not mutated, and there is no global settings object.** It
stays the frozen, once-constructed bootstrap value (`sw-design.md` §3). The
five call sites that read a *connection* setting move to a `ConnectionSettings`
provider — `EvaluationService.connection_status`, its `test_connection`
default, and `RunService`'s timeout and its `run.llm_endpoint` pin — satisfied
structurally by `SettingsService`, exactly as `ScoreSubmitter` and
`PromptResolver` are satisfied today.

**`SD42` stays green through this, and it is worth knowing why.** Moving the
five reads off `Settings` does not leave `llm_base_url` and `llm_timeout_s`
without a reader: `main.py` still reads both to construct the client and the
catalogue, and after D3 it reads them as the seed. If a later change moves the
seed read somewhere `Settings` is not named, `test_every_settings_field_has_a_reader`
fails and says which field — that is the gate working, not a false positive.

**D5. The live client is rebound on save, not rebuilt per run.** `SD36`
rejected a client per run and its reasons stand: a second loopback guard and a
second connection pool inside the record loop. A save is a rare, human,
out-of-band event, so the rebind happens there. `infra/connection.py` holds one
object satisfying both `LLMClient` and `ModelCatalog` by delegating to the
adapters `main.py` constructs today; `rebind()` builds a new pair and drops the
old. `main.py` wires that one object where it wires two now.
`import-linter`'s `one-llm-seam` is untouched: the file that constructs
`OllamaLLMClient` is still the only one that knows the name.

**D6. A save is refused while a run is in flight.** A rebind under a running
worker would move the endpoint between two records of one run, and `run` pins
one `llm_endpoint` for the whole of it — the provenance would be a lie about
half the records. **A queued run counts too**: it executes against whichever
client exists when it starts.

*Settled in Stage 2:* the refusal is the existing `RunActiveError(run_id,
status)` — "a queued or running run is in the way" is exactly what it already
means for discard (G1), over `lifecycle_service.ACTIVE_STATUSES`. A second
error for the same two statuses would be a second meaning of "active".

**D7. The loopback rule is refused at the save as well as at construction.**
Today there are two enforcement points and no opt-out (`mvp-spec.md` §19.10).
This adds a third — a stored row is a value the next startup will read, so it
is refused on the way in *and* still refused on the way out. The dialog already
disables Save on `is_loopback_url`; that stays a courtesy, and the service
refusal is the rule.

*Settled in Stage 2:* the save's refusal is a **code** —
`domain.settings.SettingRefusal`, carried by `SettingRefusedError` (frozen
`errors.py`, amendment §5) — built on `classify_endpoint`, so the save cannot
disagree with the other three callers about what loopback is. **"Refused on
the way out" means ignored, not fatal**: a stored row that fails the rule at
startup is logged (the code, never the value) and the seed stays in force. An
app that cannot start is one only a shell can fix — the cost E3 is about — and
N1 holds either way, because the value never reaches a client.

**D8. Nothing is removed from `.env`.** Both variables keep working as the
seed, `README.md`'s table keeps every row, and a host with no stored rows
behaves today's way exactly.

---

## 4. The design, in detail

### 4.1 The table

```
app_setting   id · key · value_json · changed_at
```

Keys are a closed set in `domain/settings.py` (`SettingKey.LLM_BASE_URL`,
`SettingKey.LLM_TIMEOUT_S`) — `domain` because the vocabulary is needed by the
service *and* by the refusal the dialog renders, and `ui/` may not import
`infra/`: the move `is_loopback_url` and `REASONING_EFFORTS` already made. An
unknown key in the table is ignored with a log line, never a crash — a
database written by a newer build must still open. *(A log line, not the
`Finding` this first said: `FindingCode` is frozen and names things wrong with
a delivery's rows, not with the app's own table.)*

### 4.2 Resolution, once per process and once per save

```
Settings (env / .env / defaults)   →  seed
app_setting, newest row per key    →  override      }  ConnectionSettings
```

Read at startup, after the engine exists and before `reclaim_orphans`; read
again after each accepted save. Nowhere else — no database read on the record
loop's path.

### 4.3 What the dialog becomes

| Control | Today | After |
|---|---|---|
| Endpoint, Timeout | editable, discarded | editable, **stored** |
| Save | `ui.notify("… then restart.")` | writes, rebinds, closes, reloads the view |
| Save, run in flight | — | refused, D6's sentence |
| Save, non-loopback | disabled inline | disabled inline **and** refused in the service |
| Test connection, Refresh | unchanged | unchanged |

The endpoint line under the Models card already renders the effective value, so
a successful save is visible in the place the analyst was already looking.

**The refusal has to arrive as words the analyst can act on.** The floor's control
(`plan-settings-with-no-reader.md` §4.3) found that `EvaluationView._update`
had been rendering `str(FeatureValidationError)` — "1 feature validation
error(s)" — for every refusal `SD36` made a sentence, and nothing noticed
because no control could send a refused value until then. D6 and D7 add two
refusals the dialog *can* trigger. They arrive as codes (D6, D7), so the new
`_save_settings` handler renders each through `ui/`'s one rendering table —
never `str(exc)` — and §7's UI test asserts the rendered words reach the
screen, not merely that a notification appeared.

---

## 5. The stages

Each is a commit; each leaves `just lint` and `just test` green.

### Stage 1 — the contract, before the code

- `sw-design.md`: **`SD43`** — *a setting the analyst is expected to change is a
  stored row and a control; `.env` is the seed* — plus the §10 table gaining a
  **Stored?** column (two rows say yes) and §3's injection rule gaining what D4
  makes precise.
- `docs/risk-assesment.md` E3: a *being built* note. **Its control status moves
  in Stage 5, when the change ships** — moving it on a documents-only commit
  would record a control that does not exist yet.
- `contracts/amendments/feat-settings-in-the-app.md`, and this plan's
  `CONTRACTS.md` section.

**Exit:** no code changed; the documents agree with what Stage 2 will build.

### Stage 2 — the store and the service

- `domain/settings.py`: `SettingKey` and the per-key validation (loopback for
  the endpoint, a positive bound for the timeout) — pure, stdlib and `pydantic`
  only.
- Revision `…_store_the_settings_an_analyst_changes.py`: `app_setting`,
  append-only, referenced by nothing, no existing row touched. Registered in
  `tests/test_p5_contract.py`'s `POST_PHASE_5_REVISIONS`. **One author, this
  branch's implementer**; no parallel head.
- `services/settings_service.py`: `connection()` (D3's resolution) and
  `save_connection(endpoint, timeout_s)` (D6, D7, then the append).
- `services/protocols.py`: `ConnectionSettings`; `services/container.py`:
  `Services.settings`.
- `EvaluationService` and `RunService` take the provider and stop reading
  `Settings` for those five values.

**Exit:** the API and the UI are unchanged and behave identically; a row written
straight into `app_setting` changes what `connection_status()` reports. Backend
tests per §7.

### Stage 3 — the rebind seam

- `infra/connection.py`: the delegating connection object (D5) and its
  `rebind`, with the loopback refusal at construction it already has.
- `main.py`: one object wired where two are wired today; the startup read of
  the stored override, before `reclaim_orphans`.
- `infra/config.py` (frozen, amendment §1): `llm_base_url` and
  `llm_timeout_s` say they are the seed. Here, not in Stage 1, because this is
  the stage that makes it true.

**Exit:** a stored endpoint is the one the next run calls, with no restart and
no second seam. `tests/backend/infra` per §7.

### Stage 4 — Save saves

- `_save_settings` becomes a real handler: service call, refusal rendering,
  close-and-reload on success. The `… then restart.` notification is deleted.
- The refusal codes — the three `SettingRefusal`s and `RunActiveError` — join
  `ui/`'s rendering table (CLAUDE.md: findings, not prose); the tests assert on
  the code, and one asserts the rendered words reach the screen.

**Exit:** UI tests and the E2E of §7. No screen tells an analyst to edit a file.

### Stage 5 — seen working, and the documents closed

- A **throwaway `RA2_DATA_DIR`** (never the real one, Do-NOT #13), seeded with
  `just reset-seed yes` — synthetic only, which on a native-Windows machine an
  agent runs on is the only data there may be (CLAUDE.md) — and served with
  `RA2_DATA_DIR=<that dir> RA2_PORT=<free port> uv run python -m ra2.cli
  serve`. **Not `just dev-agent`**: it mints a fresh, empty data dir on every
  start, so "restart and confirm it survives" would restart into a database
  that never held the value. Then: change the endpoint to a wrong port and see
  the line go unreachable; change it back, launch a real run against this
  host's Ollama and confirm `run.llm_endpoint` pins the *stored* value; stop
  and re-serve the same dir and confirm it survives; try a save mid-run and see
  D6. Remove the dir afterwards.
- `README.md` §Configuration: the two rows gain "changeable in the app; the
  variable seeds it", and §2 step 4 says so where an analyst reads it.
- `docs/risk-assesment.md` E3: the control status moves, to the extent this
  closes it — the endpoint half.

**Exit:** the runbook's list of tasks that still need a shell is two shorter.

---

## 6. Frozen files, and the amendment

One amendment file, `contracts/amendments/feat-settings-in-the-app.md`, applied
in the stage whose code needs it.

| File | Change | Stage |
|---|---|---|
| `ra2/infra/config.py` | **docstring only** — `llm_base_url` and `llm_timeout_s` say they are seeds. No field, default or validator changes. **Stage 3**, not 1 as first planned: the sentence becomes true when the override is read at startup | 3 |
| `ra2/persistence/models.py` | + `AppSetting`, append-only, referenced by nothing | 2 |
| `ra2/services/protocols.py` | + `ConnectionSettings` | 2 |
| `ra2/services/container.py` | + `Services.settings` | 2 |
| `ra2/services/errors.py` | + `SettingRefusedError` (a `SettingRefusal` code); a note that `RunActiveError` also refuses a settings save. Added in Stage 2 — the plan first missed that the refusal needs an error class | 2 |

Not frozen, and changed: `ra2/services/evaluation_service.py` (+ the provider
keyword; three reads move off `Settings`) and `ra2/services/run_service.py`
(the same; two reads) — both headers say "Not frozen.", and this table first
listed them as frozen, the mistake `plan-settings-with-no-reader.md` §6 made
about the same file. Also `ra2/domain/settings.py` *(new)*,
`ra2/services/settings_service.py` *(new)*, `ra2/infra/connection.py` *(new)*,
`ra2/main.py`, `ra2/ui/views/evaluation_view.py`, `sw-design.md`, `README.md`,
`docs/risk-assesment.md`, `tests/test_p5_contract.py`.

`ra2/api/schemas.py` and `tests/api/openapi_snapshot.json` are **unchanged** —
no route is added (§9).

---

## 7. Tests

| Test | Layer | What it pins | Stage |
|---|---|---|---|
| `test_an_empty_store_reports_the_environment` | backend | D3's fallback — every existing deployment's behaviour on first start | 2 |
| `test_a_stored_endpoint_beats_the_environment` | backend | D3 — at values that differ from the seed, or "read the row" and "fell back" look alike | 2 |
| `test_a_row_written_into_the_table_changes_what_connection_status_reports` | backend | Stage 2's exit, through the service the Models card reads | 2 |
| `test_a_save_is_current_at_once_and_survives_a_restart` | backend | Held in memory after the save; read back by a fresh service | 2 |
| `test_a_save_appends_and_never_updates` | backend | D2: two saves leave four rows (two keys each) and the newest wins | 2 |
| `test_a_refused_value_stores_nothing_and_changes_nothing` | backend | D7 — off loopback, malformed, a zero timeout; asserted on the `SettingRefusal` code; no row, no change | 2 |
| `test_a_save_is_refused_while_a_run_is_active` | backend | D6, for `queued` and `running` alike — `RunActiveError` | 2 |
| `test_a_stored_non_loopback_row_is_refused_at_startup` | backend | D7's other half: ignored, seed kept; the log names the code and never the value | 2 |
| `test_a_key_this_build_does_not_know_is_ignored` | backend | A newer build's database still opens | 2 |
| `test_the_service_is_a_connection_settings_provider` | backend | Structural — the two services never import it | 2 |
| `test_the_run_pins_the_current_endpoint_not_the_seed` | backend | `run.llm_endpoint` follows the provider, at a value unlike the seed | 2 |
| `tests/unit/settings/test_setting_refusals.py` | unit | `endpoint_refusal` agrees with `classify_endpoint` on every input; the timeout bound; the two keys | 2 |
| `test_after_a_rebind_every_call_reaches_the_new_pair` | backend/infra | D5 — extract and the catalogue both go to the adapters built on the new values | 3 |
| `test_a_refused_url_swaps_nothing` | backend/infra | Both built before either is swapped; the real adapters' guard, no opt-out | 3 |
| `test_a_rebind_keeps_what_is_not_an_analysts_setting` | backend/infra | Retries and the effort default carried over | 3 |
| `test_after_startup_the_live_client_dials_the_stored_endpoint` | backend | The wiring: `create_app` + `lifespan` + the real `OllamaConnection`, against a loopback listener. Fails without the startup load | 3 |
| rebind assertions in `test_settings_service.py` | backend | Rebound once after a save or a stored-row load; never after a refusal, an active run, an empty store or an ignored row | 3 |
| `test_the_settings_dialog_save_stores_the_endpoint` | ui | Through the real service: stored, rebound, and the endpoint line redrawn from the provider; no "RA2_LLM_BASE_URL" on screen | 4 |
| `test_a_refused_save_is_worded_in_the_dialog` | ui | A zero timeout: `SAVE_REFUSAL_WORDS[TIMEOUT_NOT_POSITIVE]` on screen, dialog open, nothing stored | 4 |
| `test_a_save_during_a_run_is_refused_in_words` | ui | D6 on screen: `SAVE_REFUSED_RUN_ACTIVE` | 4 |
| `test_a_refused_save_keeps_the_dialog_open_and_says_why`, `test_changing_a_field_clears_a_stale_refusal` | ui | The dialog alone (amendment §6); the five existing save tests now await `on_save` | 4 |
| `test_the_endpoint_line_shows_a_saved_endpoint_without_a_restart` | e2e | The whole point, in the browser | 5 |

`tests/test_m0_contract.py` and `tests/test_p5_contract.py` take the amended
frozen files and the new revision. `tests/test_settings_have_readers.py`
(`SD42`) needs no change and must stay green (D4).

**The E2E test waits on the redraw, not the value.** Save closes the dialog and
reloads the view, and the view rebuilds the setup column *after* the call
returns. J10 was reading layout and clicking controls on the discarded column
under a loaded run until `_redrawn` (`tests/e2e/test_j10_evaluation.py`) —
mark the element, act, wait for the selector to resolve to an unmarked one.
Reuse it here; a check that polls for the new endpoint text alone will pass on
the old line's last frame.

---

## 8. Risks

| Risk | Why it is small | Cover |
|---|---|---|
| A stored row makes the endpoint unreachable and the UI is the only way back | The dialog is reachable with the endpoint down — it is where "Test connection" lives — and `just reset` clears the store with the database | D3, Stage 5 |
| Two configuration mechanisms confuse a reader | One wins, always, and the loser is documented as the seed in the same table | D3, D8, Stage 5's README row |
| The rebind races a run | Refused, not serialised | D6 |
| N1 is weakened by a UI-writable endpoint | The enforcement points go from two to three and none of them is optional | D7 |
| The append-only table grows | One row per human decision; `model_qualification` has the same shape | D2 |

---

## 9. Deliberately not in this plan

- **The rest of the §10 table.** `llm_max_retries` and `log_level` are the two
  plausible next rows and each needs its own answer about when it takes effect.
  `llm_reasoning_effort` is already a column (`SD36`) and does not come back.
  `llm_parallel_calls` is gated on a qualification (`SD40`) and is a
  measurement, not a preference — it belongs in the app only behind that gate.
- **`RA2_MIN_CELL_COUNT`.** Not a candidate for this store: it is not a host
  setting, and it is already a column. It was unwired at both ends (§11.4) and
  is **fixed as of `4307b61`** — the draft seeds from it, and step 6's
  "Minimum n per cell" sets it per evaluation.
- **`data_dir`, `db_path`, `host`, `port`, `storage_secret`.** Bootstrap: they
  decide where the store *is*, so they cannot live in it, and they belong to
  whoever starts the process — which for `host` and `port` is now literally
  true: `ra2 serve` reads them and refuses a non-loopback bind (`SD42`).
- **A `config.json`.** §2. If a second non-database mechanism is ever wanted it
  is `pydantic-settings`' `JsonConfigSettingsSource` slotted below the
  environment, and it is a separate decision from this one.
- **An API route for settings.** The UI calls services in-process; no client
  has asked.
- **A settings screen in the nav.** Two settings do not make a screen.

---

## 10. For the lead, before Stage 1

| # | Question | This plan's answer |
|---|---|---|
| Q1 | A database table, or the `config.json` the question asked about? | **The table.** The store has to be writable by the app, and the app has one; a file adds a precedence rule and cannot hold a comment |
| Q2 | Does a stored value beat the environment, or the other way round? | **Stored wins, env seeds.** Env-wins means Save is accepted and ignored on exactly the hosts that were configured deliberately |
| Q3 | Two settings, or the whole §10 table? | **Two.** They are the two the dialog already draws, which is why the frozen UI signature fits unchanged |
| Q4 | Rebind live (D5), or store and still require a restart? | **Rebind.** A stored setting that needs a restart fixes the typing and leaves E3's actual cost — the developer at the machine — in place |

---

## 11. Appendix — every parameter, and where it sits

Written because §2's argument is only as good as the inventory under it.
**Taken 2026-09-26 against `8adf7d0`; brought up to date with `4307b61`**, which
merged `plan-settings-with-no-reader.md` — the rows it changed say so. Four
classes, and the test for each:

| Class | Test | Home |
|---|---|---|
| **Host** | Decided once by whoever installs RA2. Wrong value and nothing starts. | `.env` — the bind included, since `ra2 serve` reads it (`SD42`) |
| **Operator** | Depends on *this machine* — its endpoint, its GPU, its patience. Does not vary between two evaluations. | `.env` today; `app_setting` for the two this plan moves |
| **Experiment** | The analyst is expected to **vary it between two evaluations that are then compared** (`SD36`). | a column on `evaluation` (or `feature`), and a control |
| **Method** | A property of how RA2 measures, not a preference. Make it configurable and two installs stop being comparable. | a `Final` in `domain/` — deliberately not a setting |

### 11.1 `Settings` — the `RA2_` environment (`infra/config.py`)

| Setting | Read by | Class | Sitting correctly? |
|---|---|---|---|
| `data_dir` | `main`, both file stores, alembic | Host | **Yes.** It decides where the store *is*, so it can never live in it |
| `db_path` | `main`, `migrations/env.py` | Host | **Yes** |
| `storage_secret` | `main` (NiceGUI) | Host | **Yes.** Not a security boundary; the app has no login |
| `max_upload_mb` | `main` (both upload stores) | Host | **Yes.** A disk fact, not an analyst's choice |
| `gpu_vram_gb` / `gpu_name` | `main` (`probe_for`) | Host | **Yes.** A declaration that beats a probe on a non-NVIDIA host |
| `log_level` | `main` (`configure_logging`) | Operator | **Yes for now.** §11.5 argues it is the best *next* candidate after this slice |
| `llm_max_retries` | `main` (client construction) only | Operator | **Yes.** Nothing above `main` reads it; nobody has needed to change it mid-session |
| `llm_base_url` | `main`, `evaluation_service`, `run_service` | Operator | **No — this plan.** It is the one setting an analyst *must* be able to change, and the only surface for it is a text editor |
| `llm_timeout_s` | `main`, `evaluation_service` ×2, `run_service` | Operator | **No — this plan.** Same dialog, same save |
| `llm_parallel_calls` | `evaluation_service` (the launch pin, gated by `SD40`) | Operator | **Defensible, and the next thing to move.** It is a per-model *measurement* whose gate already lives in `model_qualification`; the setting and its evidence sit in two different places (§11.5) |
| `llm_reasoning_effort` | `main` (client default), `evaluation_service` (draft default) | Experiment → **already moved** | **Yes, in its reduced role.** `SD36` made it `evaluation.reasoning_effort`; what is left in the environment is the *default for a new draft*, which is a legitimate remaining job |
| `dev_record_max` / `eval_record_min` | `evaluation_service`, `run_service` | Method | **Yes, but they are not really settings.** `mvp-spec.md` §9 defines what "smoke test, not a result" means; a host that quietly lowered `eval_record_min` would publish dev-sized numbers as results. Worth stating as policy rather than leaving as a knob |
| `run_concurrency` | `run_service:375`, which **refuses** anything but 1 | Operator, forward-declared | **Yes.** It has a reader, a refusal and a test (`test_run_concurrency_above_one_is_refused_not_silently_ignored`), and `sw-design.md` §15 F7 states the intent: the setting exists so lifting the limit "is a config line rather than a rewrite". The same shape as `llm_base_url` in phase 1 (N2) |
| `host` / `port` | `cli.serve` | Host | **Yes, since `4307b61`.** Read by nothing before it — the `justfile`'s `--host`/`--port` bound, and nothing refused `0.0.0.0` (A4, G3). `plan-settings-with-no-reader.md` **wired** them rather than deleting them: `ra2 serve` binds what they say and refuses a host outside `LOOPBACK_HOSTS` before a socket opens |
| `min_cell_count` | `evaluation_service.save_draft` | Experiment | **Yes, since `4307b61`** — in its right role, the seed for a new draft's floor. The floor itself is the `evaluation` column (§11.2). Read by nothing before (§11.4) |

### 11.2 `evaluation` — the per-experiment row, and its controls

The place `SD36` established, and the place most analyst-facing parameters
already are:

| Column | Control? | Note |
|---|---|---|
| `prompt_template_id`, `feature_config_id`, `corpus_id` | yes | The three frozen inputs |
| `prompt_language` | yes (`features_view`) | §15 F10's real home |
| `temperature` | yes — the `TEMPERATURE_CHOICES` ladder | Default `0.0` |
| `seed` | yes — number input | Default `42` |
| `reasoning_effort` | yes — select | `SD36`, the migration that set the pattern |
| `selected_models_json` | yes — the Models card | Gated on VRAM and reachability |
| `size` / `is_dev` | yes | Against `dev_record_max` |
| `min_cell_count` | yes — step 6, "Minimum n per cell" (since `4307b61`) | Seeded from `RA2_MIN_CELL_COUNT`; refused below 1. Step 6 (Size), not beside temperature and seed: it decides how much data a number needs, nothing about the answer |

Per **feature**, one layer down: `matching_rule` carries its own parameters
(the tolerance in minutes, its step), set in `features_view`. Correct place —
a matching tolerance is a property of the feature being scored, not of the
host.

### 11.3 Parameters that are deliberately not settings

Changing any of these changes what a number *means*, so they are `Final`
constants in `domain/`, where the layer rule keeps them away from
configuration:

`census.TOP_VALUES_STORED` (20) · `census.LONG_TAIL_MIN_DISTINCT` /
`LONG_TAIL_MAX_TOP_SHARE` · `parsing.headers.HEADER_MATCH_THRESHOLD` (0.6) ·
`parsing.dialect._SNIFF_LINES` (10) · `language.DEFAULT_MIN_CONFIDENCE` (0.5) ·
`feature.EXPLORATORY_FEATURE_CAP` (20) · `qualification.MIN_SPEEDUP` (1.3),
`NOISE_FLOOR_RECORDS` / `NOISE_FLOOR_OF` · `stats.WILSON_Z_95` ·
`infra/config.MAX_PARALLEL_CALLS` (8, the ceiling on the setting above).

Service and UI constants are the same answer for a different reason —
`run_service._MAX_CONSECUTIVE_ENDPOINT_ERRORS` (3),
`export_service._EXPORT_PAGE_SIZE` (1000), every view's `PAGE_SIZE`,
`POLL_FAST_S` / `POLL_SETTLED_S` — they are mechanism, and no analyst has a
reason to hold an opinion about them.

**The recommendation is to keep all of these where they are.** Two RA2 installs
that disagree about `HEADER_MATCH_THRESHOLD` produce ingest reports that cannot
be compared, and the product exists to make comparisons.

### 11.4 The one live defect this inventory found — fixed in `4307b61`

*Kept as found, because the finding is the reason `SD42` exists.* Both ends
are wired now: `save_draft` seeds the floor from `Settings`, and step 6 sets
it per evaluation. Measured against this host's Ollama: two evaluations
identical but for the floor (3 and 20) had the same `n` in every cell and
differed only where the floors did (`plan-settings-with-no-reader.md`
Stage 5).

**`min_cell_count` was unwired at both ends.**

- `mvp-spec.md` §11.4: "Default **20**, configurable **per evaluation**."
- `evaluation.min_cell_count` exists (`SD19`, revision `e5145f27bf8c`) and is
  read by `results_service`, `ranking_service` and three tabs.
- `Settings.min_cell_count` is read by **nothing**. `models.py` says the column
  is "defaulted from `config.min_cell_count` when the draft is created"; no
  code does that. The column's own `default=20` is what every row gets.
- There is **no control** for it on step 5.

So the value is 20 for every evaluation on every host, by two accidents that
cancel out. Nothing renders wrongly today — 20 is the specified default — which
is why it survived: the defect is that the spec's "configurable per evaluation"
is unreachable, not that a number is wrong. It is the same shape as
`vram_bytes=0` (`plan-ranking-vram.md` §2.1): a plan named a wiring that was
never built, and no test asked.

**It was not this plan's to fix** — a column and a control, not a host setting
— and it went first, in its own slice, because it was cheap: suppression is
applied at **read** time from stored `n` (`SD19`), so changing the floor never
re-scores anything.

### 11.5 What should become a setting next, and what should stop being one

Ranked by value over cost, after this plan lands. The first item on the
original list — a control for `evaluation.min_cell_count` — is **done**
(`4307b61`, step 6).

1. **The parallel-calls gate, rendered beside the model — a read, not a
   setting.** `plan-settings-with-no-reader.md` §11.2: the real defect is that
   the value lives in a text file while its evidence lives in
   `model_qualification`, and a launch pinned to 1 explains itself in a log
   line. "4 calls · qualified 2026-09-25" on the Models card needs no store
   and no migration, so it goes before item 2.
2. **`llm_parallel_calls` as a stored, per-model row.** It is already gated on
   `model_qualification` (`SD40`), so the evidence is in the database while the
   setting is in a text file — and the one place an analyst would look for both
   is the Models card. Moving it makes the gate legible: "4 calls, qualified on
   2026-09-25" beside the tick, rather than a refusal in a log line.
3. **`log_level`, from the app.** A run is tens of minutes; the moment anyone
   wants `DEBUG` is the moment a run is misbehaving, which is the worst moment
   to need a restart. `data-handling.md` §5.1 already bounds the *content* at
   every level, so this is safe by construction.
4. **Draft defaults** — the effort, temperature and seed a new evaluation starts
   at. Low value: the defaults are measured (`none`, `0.0`, `42`), and an
   analyst who wants different ones is running a comparison, which is exactly
   what the per-evaluation controls are for.

And two that were **documented knobs doing nothing** — the same class of defect
as a Save button that does not save. Both were fixed by
`plan-settings-with-no-reader.md`, merged as `4307b61`, and `SD42`'s gate now
fails the build on the next one:

- **`RA2_HOST` / `RA2_PORT`** — read by nothing; the `justfile` binds. A setting
  that describes an intent it cannot enforce is worse than no setting, because
  a reader of §10 believes it. That plan **wired** them, with a loopback
  refusal in the launcher, rather than deleting them: A4 weighs both and
  prefers wiring because it makes the deployment posture testable.
- **`RA2_MIN_CELL_COUNT`** — dead, and repaired at both ends there (the reader
  it always claimed, and the step-6 control).

**`RA2_RUN_CONCURRENCY` is not one of them**, and an earlier draft of this
appendix was wrong to say so: it has a reader, a refusal and a test, and §15 F7
states why it exists ahead of its use.

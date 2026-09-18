# Risk Assessment — RA2

**External review of the use cases and the implementation.**
Point-in-time, at commit `616bf2b` (2026-09-16), with phase 4 (scoring and
results) in progress and phase 5 (mismatch review) not started.

Reviewer: external, independent of the implementation. This document is not
legal advice and not a penetration test — see *Method and limits*.

---

## 1. Executive summary

RA2 processes **real, non-anonymised police accident records** — narratives
plus a structured record that `vision.md` itself describes as personally
identifying (birth date, postcode, LV95 coordinates, vehicle and insurer). The
project's answer to that is a single strong architectural decision — *local
models, nothing leaves the host* — backed by an unusually disciplined set of
invariants, and it holds up well under inspection.

**The fundamental choice is sound and the code implements it seriously.** The
loopback rule has no opt-out, is enforced before any socket exists, is stated
once and reused by all three callers, and has an `import-linter` contract plus
unit, backend and E2E tests behind it. Records, extractions and corpora are
append-only. Nothing is logged. The parser refuses to guess. That is a better
starting posture than most systems handling this class of data.

**The residual risk is therefore not in the decision — it is around it.** Three
patterns account for almost everything found:

1. **The guarantee is scoped to one process, and the data is not.** RA2 refuses
   to *name* an off-host endpoint, but it does not control what sits behind
   `127.0.0.1` (A2), what the environment does to its outbound socket (**A1 —
   verified defect**), what the separate Ollama process does (A3), or what a
   human does with an export (B1, B2).
2. **Deliverables carry the data out.** The census CSV, the per-record lists,
   the mismatch list with evidence spans and the evaluation report are all
   *meant* to be shared, and all of them can carry verbatim or identifying
   content (**B1 — verified**). N1 governs the app; nothing yet governs the
   outputs.
3. **The project's product is a number, and a wrong number is invisible.** The
   PoC's deliverable is a model ranking. Several mechanisms can silently
   degrade it — prompt truncation (D1), parse failures scored as misses (D2),
   reproducibility claimed more strongly than local inference supports (D3).
   None of them crash; they just lower a score and look like a model weakness.

**Top five actions**, in order:

**Status** is maintained as findings close: `open` until there is a
remediation entry in §8, then `✓ §8.n` pointing at it. **`◑`** means the code
is done and a decision for the project is not — the entry says which. It is
the only part of this document that is kept current; the register in §4 stays
as written at `616bf2b`.

| # | Status | Action | Effort | Risk |
|---|---|---|---|---|
| 1 | **✓ §8.1** | Build the adapter's HTTP client with `trust_env=False` (a proxy env var currently redirects loopback traffic off-host — reproduced) | ~1 h | **A1** |
| 2 | open | Write the data-handling rules the app cannot enforce: outputs, retention, destruction, named owner, incident path | ~1 day, no code | **F1, B2, B3** |
| 3 | **◑ §8.4** | Suppress or gate verbatim value samples in the census export; screen every export before it leaves the machine | ~½ day | **B1** |
| 4 | **◑ §8.2** | Make the real-data commit guard content-shaped and run it in CI; reconsider the repository being public | ~½ day | **C1** |
| 5 | open | Measure and bound the prompt against the model's context window before the evaluation corpus is cut | ~1 day | **D1** |

Nothing found here calls the architecture into question. Items 1, 3 and 4 are
small fixes to controls that already exist; item 2 is the gap that no amount of
code will close.

---

## 2. Method and limits

**What was examined.** `vision.md`, `ra2.md`, `mvp-spec.md`, `sw-design.md`,
`CLAUDE.md`, `CONTRACTS.md`, the four phase plans, `README.md`; the
implementation under `ra2/` (~36 kLOC, 128 modules); `justfile`,
`.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `.gitignore`,
`.importlinter`, `scripts/`; the test tree's shape (140 test modules across
five layers).

**What was executed.** Three checks were run rather than read, and are marked
**verified** where they appear:

- the HTTP client the adapter actually builds, against a proxy environment
  variable (A1);
- the census tables of the working database at `var/ra2.sqlite`, by aggregate
  query only — no narrative or personal value was printed or copied (B1);
- the real-data pre-commit guard's patterns against the Astrana delivery's own
  filenames (C1).

**What was not examined.** The target machine, the GPU, the real delivery
files, the Ollama deployment, the network the machine sits on, the NDAs, and
any organisational documentation that exists outside this repository. Where a
control may exist but is not written down here, the finding says so — "not
recorded" rather than "absent".

**Not in scope.** Legal assessment under Swiss federal or cantonal data
protection law. Several findings (F1 in particular) are the kind of thing a
data protection officer would normally own; they are raised as project risks,
not as legal conclusions.

**Severity** is the reviewer's judgement of likelihood × impact *in this
context* — a one-month PoC, one machine, one small group of analysts, real
data. It is not a CVSS score.

---

## 3. What is already strong

Recorded deliberately, because these controls are cheap to trade away later
under schedule pressure and expensive to rebuild.

| Control | Where | Why it matters |
|---|---|---|
| **Loopback rule with no opt-out**, enforced at construction, before any client exists | `ra2/domain/llm.py:303` (`classify_endpoint`), `ra2/infra/ollama_client.py:269` | One rule, three faces (raise / ask / report); a literal host list, no DNS; the reasoning for *why there is no setting* is written down where the next person will look |
| **One LLM seam**, enforced mechanically | `.importlinter` `one-llm-seam`, `tests/test_p3_contract.py:211` | A second provider client cannot be added by accident |
| **Append-only data** — extractions, records, corpora, prompt templates | `mvp-spec.md` §5, Do-NOT #2 | A re-run cannot destroy evidence; `mismatch` is the single documented exception, with a preservation test |
| **No logging of any kind** in the application | verified by grep over `ra2/` | The commonest way narrative text escapes a local app simply does not exist here |
| **Strict parsing, loud failure** — no `errors="replace"`, no silent repair, every recovered or rejected row reported with its key | `ra2/infra/files.py`, `mvp-spec.md` §4.2 | Corrupted labels are the failure mode that surfaces months later as wrong metrics |
| **Real data cannot reach the test suite** — hazards are synthesised byte-exactly; the one real-data test reads header lines only and skips when absent | `tests/unit/parsing/test_headers_realdata.py` | The discipline is real, not aspirational |
| **Agent isolation already practised** — `just dev-agent` on a random port and a throwaway data dir | `justfile`, `scripts/dev_agent.py` | The precedent needed for C2 exists already |
| **Honest metrics design** — presence has no gold label and says so; `hallucinated` is a tag, not a rate; suppression below *n*; ties rendered as ties; exploratory attributes excluded from ranking | `mvp-spec.md` §11, `sw-design.md` §16 | Most of the ways an evaluation lies to its reader have been anticipated |
| **Documented acceptance of the re-identification risk**, written down rather than assumed | `vision.md` → *Real data* | The right instinct; F1 is about finishing that sentence |

---

## 4. Risk register

Scenarios are grouped by what actually goes wrong, not by which component is
involved. **Control status**: *in place* · *partial* · *absent*.

### Group A — Data leaves the host

The scenario N1 exists to prevent: narrative or record content crosses the
machine boundary.

---

**A1 · A proxy environment variable redirects "loopback" traffic off-host**
· Severity: **High** · Control status: **absent** · **Verified**

> **Remediated 2026-09-17 — see §8.1.** The finding below is left as written:
> this document is a point-in-time review at `616bf2b`, and rewriting it would
> lose the reasoning that found the defect. Control status at the time of
> writing was *absent*; it is now *in place*.

*Scenario.* RA2 is installed on a managed workstation where `HTTP_PROXY` (or
`ALL_PROXY`) is set machine-wide, as it is on most corporate and government
Windows estates, and `NO_PROXY` does not cover localhost. The endpoint passes
the loopback guard — the URL genuinely is `http://127.0.0.1:11434/v1`. The
request carrying the accident narrative is nevertheless sent to the proxy host.

*Evidence.* `_build_client()` (`ra2/infra/ollama_client.py:197`) passes
`http_client=None` in production, so the `openai` SDK constructs its own
`httpx2.AsyncClient` with `trust_env=True` (the default). Reproduced with the
project's pinned versions:

```
$ HTTP_PROXY=http://proxy.corp.example:3128 uv run python -c "…AsyncOpenAI(base_url='http://127.0.0.1:11434/v1'…)"
trust_env: True
proxy: URL(scheme=b'http', host=b'proxy.corp.example', port=3128, target=b'/')
```

The transport chosen for a `127.0.0.1` URL is the proxy pool. Nothing in the
repository mentions proxies: `grep -r proxy` over the codebase, docs and
`pyproject.toml` returns one unrelated line.

*Why the existing control does not catch it.* `classify_endpoint` reasons about
the **URL**. The proxy decision is made later, by the transport, from the
environment. The guard is correct and complete for what it inspects.

*Impact.* Narrative text — the sensitive payload — is sent to a host that is
not this machine, most likely one that logs URLs and possibly bodies. The
README's claim that the guard makes off-host traffic "impossible rather than
merely discouraged" is, in this configuration, not true.

*Recommendation.*
1. Build the production client explicitly: `httpx2.AsyncClient(trust_env=False)`
   (or `mounts={"all://": None}`) in `_build_client`, for the LLM client, the
   catalogue **and** the prober.
2. Add a test that sets `HTTP_PROXY` in the environment and asserts the chosen
   transport has no proxy URL. This is the kind of regression that returns
   silently.
3. Say so in the README beside the loopback rule: the guard covers the URL, the
   client covers the environment, and both are needed.

---

**A2 · The guard cannot see what sits behind `127.0.0.1`**
· Severity: **Medium** · Control status: **partial (by design)**

*Scenario.* The GPU turns out to be too small for the interesting models —
`vision.md` lists this as a known risk and `mvp-spec.md` B2 still has VRAM
unconfirmed. Someone helpful forwards a port: `ssh -L 11434:gpu-server:11434`,
or runs a small reverse proxy, or points Ollama's own configuration elsewhere.
RA2 sees `127.0.0.1:11434`, accepts it, and ships every narrative to another
machine. Nothing in the app can detect this, and nothing in the app is at
fault.

*Why it is plausible rather than theoretical.* The pressure is structural: weak
hardware produces weak results, the month is short, and a tunnel is one line.
The person who types it will not think of themselves as exporting data.

*Existing controls.* The run record stores `llm_endpoint`, `host_platform`,
`gpu_name` and the model digest — so a run served from elsewhere leaves traces
(a GPU name that does not match the machine, a model digest never pulled
locally), but nobody is currently asked to look.

*Recommendation.*
- State the rule in the runbook in the plainest possible terms: *any tunnel,
  proxy or forwarder between RA2 and a model server is a data breach, whatever
  the URL says.* The technical control cannot express this; a sentence can.
- At M34, check the run provenance of the first real evaluation against the
  machine it claims to have run on. Once, deliberately, as an acceptance step.
- Close **B2/B3** (VRAM, air-gap status) before the evaluation corpus is cut.
  The temptation A2 describes is strongest when the hardware answer arrives
  late.

---

**A3 · The guarantees stop at RA2's process boundary**
· Severity: **Medium** · Control status: **absent (out of the app's scope,
not out of the project's)**

*Scenario.* Ollama is a separate process with its own configuration, and every
narrative passes through it.

- `OLLAMA_HOST=0.0.0.0` makes the model server reachable from the LAN — a
  second, unauthenticated way to reach the machine that RA2's loopback posture
  says nothing about.
- Debug logging (`OLLAMA_DEBUG`) causes prompt content to be written to the
  server's log, outside `RA2_DATA_DIR`, outside the retention rules, and into
  whatever log collection the workstation has.
- `ollama pull` fetches weights over the internet. That is egress *from the
  machine*, carrying no accident data, but it contradicts an air-gapped
  deployment (B3 is still open) and it is the step a runbook will get wrong.

*Recommendation.* One short "model server" section in the runbook, pinning
`OLLAMA_HOST=127.0.0.1`, forbidding debug logging while real data is loaded,
and stating how weights arrive (pull on a connected machine and side-load, or
pull in place) once B3 is answered. Record the Ollama version with each run —
see D3, which wants it for a different reason.

---

**A4 · Unauthenticated app + arbitrary host-path read, safe only while bound
to loopback** · Severity: **Medium** · Control status: **partial**

*Scenario.* `POST /api/v1/deliveries` with `source_kind=host_path` accepts an
arbitrary `root_path` and registers it (`ra2/api/v1/deliveries.py:105`,
`ra2/services/delivery_service.py:283`). Registration immediately walks the
directory recursively and reads **every file in full** to hash it
(`HostPathFileStore.list_files` → `_stat_file`, `ra2/infra/filestore.py:178`).
The app has no authentication anywhere, by design (`mvp-spec.md` §13).

While the server is bound to loopback on a single-user machine this is
equivalent to the analyst's own file access, and unremarkable. It stops being
unremarkable the moment the bind address changes.

*The bind address is weaker than it looks.* `Settings.host` and
`Settings.port` exist and are documented as "bind to loopback by default (N1)"
(`ra2/infra/config.py:69`), but **nothing in `ra2/` reads them**. The actual
bind comes from the `uvicorn` command line in the `justfile`. A future runbook
or an operator who wants a colleague to see a result will write
`--host 0.0.0.0`, and no code, test or contract will object.

*Secondary effect.* Pointing a registration at a large tree (`/`, a home
directory, a network share) reads and hashes every file into memory. Not an
attack, just an unbounded operation with a plausible user error behind it.

*Recommendation.*
- Constrain `root_path` to a configured allowed root (`RA2_IMPORT_ROOT`,
  defaulting to `{data_dir}/import`), rejecting anything outside it with a
  `Finding`. The traversal guard `_resolve` already does this *within* a root;
  this extends the same idea to the root itself.
- Either make the server read `Settings.host` (and refuse a non-loopback bind
  the way the LLM client refuses a non-loopback endpoint), or delete the two
  settings so they stop implying a control that is not there. The first is
  better: it makes the deployment posture testable.
- Bound the walk: file count and total bytes, with a `Finding` rather than an
  exception.

---

### Group B — Data stays on the host but spreads

The scenario nobody's invariant covers: the data is handled correctly by the
app and then carried out by a person doing their job.

---

**B1 · The census export contains verbatim identifying values**
· Severity: **High** · Control status: **absent** · **Verified**

> **Remediated 2026-09-17 — see §8.4.** Samples are withheld for every column
> the delivery does not mark as coded, and every export carries a
> classification line. **Screening an export before it is shared is still
> open** — that is a runbook sentence, not a predicate.

*Scenario.* The column-population census is the week-one deliverable, explicitly
intended to be reported on its own ("a finding about the data worth reporting")
and exported as CSV. It stores, for **every** column, the top 20 raw values
with counts (`ra2/domain/census.py:185`) and exports them in a `top_values`
column (`ra2/services/export_service.py:46`). No column is exempt.

*Evidence.* Aggregate query against the working database at `var/ra2.sqlite`
(2 695 real records, one corpus; values not printed):

| column | stored top values | of which occur exactly once |
|---|---|---|
| `unfall.Koordinate X` / `Y` / `E` / `N` | 20 each | 16–18 each |
| `unfall.Unfall-UID`, `objekt.Objekt-UID`, `person.Person-UID` | 20 each | 20 each |

A coordinate that occurs once is one accident, at metre precision. A UID is the
record key. Both are exported, and both are in a file whose entire purpose is to
be shown to other people. A RADIS delivery (77/18 columns against Astrana's
narrower export) will expose more of this kind, not less.

*Impact.* The most shareable artefact of the project is the one most likely to
carry identifying content out of the machine, and nothing marks it.

*Recommendation.*
- Do not store or export value samples for columns that are not plainly coded.
  A cheap, defensible rule: suppress `top_values` where `distinct_count` is
  high relative to `populated_count`, or where the top value's count is 1 —
  those are exactly the columns where a sample is least informative about
  population anyway. Keep counts, rates, distinct counts and type hints, which
  is what feature selection actually needs.
- Mark every export with a classification header line (the writer already emits
  a corpus/version comment line — one more line costs nothing).
- State in the runbook that a census export is sensitive until someone has
  looked at it.

---

**B2 · Exports and the evaluation report are the real exfiltration path**
· Severity: **High** · Control status: **absent**

*Scenario.* The intended deliverables include a mismatch list with **evidence
spans** — verbatim fragments of the narrative, mandatory by design — plus
per-record presence lists and an evaluation report. Exports are streamed to the
browser and land in the analyst's Downloads folder, outside `RA2_DATA_DIR` and
outside every rule the app enforces. From there they are attached to an email
like any other CSV.

This is not a defect. It is the consequence of building outputs people can act
on, and the design is right to mandate evidence spans. But **N1 constrains the
application, and every meaningful risk in this group is downstream of it.**

*Additional exposure.* Goal 3's review is performed by "the expert who proposed
the attribute" (`vision.md` → Metrics). That expert reads evidence samples, i.e.
narrative text, and is not obviously covered by the analysts' NDA that the
re-identification acceptance rests on.

*Recommendation.*
- One page of output-handling rules, owned by the project, not by the code:
  where exports may be saved, that they are not to be emailed outside the named
  group, who may read evidence spans, and that the evaluation report is screened
  for verbatim narrative before circulation.
- Make the report's own example rows synthetic. The temptation to paste a real
  mismatch into the report as an illustration is high and the cost is real.
- Extend the NDA (or an equivalent instruction) to the reviewing domain expert
  before Goal 3's review, not after.

---

**B3 · No retention limit, no deletion path, no end-of-PoC destruction**
· Severity: **High** · Control status: **absent**

*Scenario.* The PoC ends. The data stays.

*Evidence.*
- There is **no delete for a delivery** — only `DELETE /deliveries/{id}/files/{file_id}`
  for a single file. Uploaded delivery files persist under
  `{data_dir}/deliveries/{delivery_id}/` indefinitely.
- `CorpusService.delete` (`ra2/services/corpus_service.py:284`) removes database
  rows and is correctly refused while an evaluation cites the corpus — but it
  does **not** remove the raw delivery files those records came from.
- SQLite does not return freed pages to the OS and nothing runs `VACUUM`, so
  deleted narratives remain readable in the file's free space until overwritten.
- No document states a retention period, a destruction date, or who performs
  destruction. `vision.md` accepts the re-identification risk; it does not bound
  it in time.

*Recommendation.*
- Decide and write down: how long the corpus may live on the machine, what
  happens to it at the end of the PoC, and who signs that it happened.
- Add a delivery-level delete that removes the stored files, and run `VACUUM`
  after a corpus delete. Small work, and it is what makes "we deleted it"
  truthful.
- If the machine is ever repurposed, the disk — not the database — is the unit
  of destruction.

---

**B4 · Encryption at rest and machine custody are not recorded**
· Severity: **Medium** · Control status: **unknown — not recorded**

*Scenario.* The whole corpus sits in one unencrypted SQLite file plus the raw
delivery files beside it. On this development machine that file is 281 MB and
holds 2 695 real records (verified by row count). A laptop is lost, a disk is
returned to a lease, a backup is copied to a share.

Full-disk encryption may well be in place — it is not the reviewer's to
observe, and nothing in the repository states it either way.

*Recommendation.* Record the deployment conditions as explicit prerequisites,
in the runbook, at the same level of seriousness as the loopback rule: full-disk
encryption on, one named machine, one OS account per analyst, screen lock, no
remote-desktop sharing of the session, no synchronisation of `RA2_DATA_DIR` to
any cloud folder (OneDrive on a managed Windows profile is the specific hazard —
`./var` under a redirected home directory would be synchronised silently).

---

**B5 · The anonymisation marking does not assert what its label implies**
· Severity: **Medium** · Control status: **partial**

*Scenario.* `mvp-spec.md` §13 requires the per-record anonymisation marking
"everywhere text is shown", and the UI renders a chip reading *anonymised*. In
the implementation, that flag is **provenance, not a privacy statement**: it is
`True` only when the narrative came from the `UnfHergangTextAnonym` fallback
column because the shared text file had no row for that record
(`ra2/services/corpus_service.py:558`). For every normally imported record —
i.e. nearly all of them — the flag is `False`.

An analyst reading "not anonymised" will draw a conclusion about the content of
the text. That conclusion may be right, wrong, or unknowable: the exact
semantics of `UnfHergangTextAnonym` ("an anonymised text exists" vs "this text
has been anonymised") is still an **open question** in `mvp-spec.md` §18, and
the delivered text file's own status is not recorded anywhere.

The code is not wrong — it is careful, documented, and deliberately conservative
about a column whose meaning is unknown. The risk is in the label.

*Recommendation.*
- Close the open question with the data supplier before the evaluation corpus is
  cut. It is one email and it decides what the marking means.
- Until it is closed, render three states, not two: *anonymised* / *not
  anonymised* / **unknown**, with unknown as the default for a delivered
  narrative. A marking that overstates certainty about personal data is worse
  than one that admits it.

---

### Group C — Development, tooling and supply chain

---

**C1 · The barrier against committing real data is name-shaped, opt-in, and
not in CI — and the repository is public** · Severity: **High** ·
Control status: **partial** · **Verified**

> **Partly remediated 2026-09-17 — see §8.2.** The guard is content-shaped and
> runs in CI; **public visibility is still open**, and it is a decision rather
> than a diff.

*Scenario.* A real delivery file is copied into the working tree while
debugging an import — the single most natural thing to do when a parser fails
on real data — and is committed.

*Evidence.* Three defences exist and each has a gap:

1. `.gitignore` covers `data/`, `vum_*.txt`, `AstranaExport*`, `*.xlsx`,
   `*.xls`, `*.zip`. **The Astrana delivery's real filenames are `Unfall.csv`,
   `Objekt.csv` and `Mitfahrende.csv`** (`mvp-spec.md` §4.1) and match none of
   these patterns outside `data/`.
2. `scripts/check_no_real_data.py` repeats the same patterns, so it inherits the
   same gap. It also runs only as a **pre-commit hook**, which is installed by
   hand once per clone (`uv run pre-commit install`) and bypassed by
   `git commit --no-verify`.
3. **CI does not run it.** The `lint` job runs ruff, mypy and `lint-imports`
   only.
4. The repository is **public** (`github.com/stroumpfai/ra2`, confirmed
   `"private": false` via the GitHub API). A private repository gives a window
   to force-push a mistake away; a public one does not — the content should be
   assumed mirrored the moment it is pushed.

*Recommendation.*
- Make the guard **content-shaped**, not name-shaped: refuse any staged file
  whose first data line begins with a 32-hex key followed by `|`, `;` or `,`,
  or whose header matches a canonical delivery column set. The canonical sets
  already exist in `ra2/domain/parsing/headers.py`; the check is a dozen lines
  and it catches the file whatever it is called.
- Run that check in CI over the pull request's changed files, so it is a gate
  and not a local convenience.
- Reconsider public visibility for the duration. There is no data in the
  repository today and the documentation is exemplary, but a public repository
  makes the one mistake in this class unrecoverable.

---

**C2 · AI-assisted development on the machine that holds the real corpus**
· Severity: **Medium–High** · Control status: **partial**

> **Partly remediated 2026-09-17 — see §8.3.** Do-NOT #13 and the deny rules
> exist and are verified live. **Keeping real data off the development
> checkout entirely is still open**, and it is the recommendation that would
> make the rule unnecessary rather than merely stated.

*Scenario.* The project is built with an AI coding assistant by explicit design
(`vision.md` → Environment). The assistant runs on the same machine as
`data/` (real samples) and `var/ra2.sqlite` (2 695 real records). Agent
transcripts are, by construction, processed off the host. An agent debugging an
import, a census or a language-detection bug has every reason to read a real
file or query the real database, and no rule tells it not to.

*Existing controls.* Good instincts are already present: `just dev-agent`
isolates port and data directory precisely because a previous collision caused
harm, the real-data test reads header lines only, and Do-NOT #11 forbids
committing real data. But **Do-NOT #11 is about committing, not about
reading**, and `.claude/` holds no permission configuration.

*Recommendation.*
- Add a thirteenth Do-NOT, in the same voice as the rest: *never open, query,
  print or paste the contents of `data/` or `RA2_DATA_DIR`. Reproduce the hazard
  in a fixture instead.* Back it with a deny rule in the assistant's permission
  configuration for `data/**` and `var/**`.
- Better still, keep real data off the development checkout entirely: real
  delivery files and the real corpus on the target machine, synthetic hazards
  everywhere else. The fixture discipline already in place makes this
  affordable — it is mostly a matter of stating it.
- The same applies to Playwright traces and screenshots if the E2E suite is ever
  pointed at a real corpus on the target machine.

---

**C3 · Dependency supply chain and the offline-install question**
· Severity: **Low–Medium** · Control status: **partial**

`uv sync --frozen` against a committed lock file is the right posture, and
`pyproject.toml` being deliberately unchanged in phase 4 shows the discipline is
maintained. Two residuals:

- Every dependency still originates from PyPI, and CI runs on GitHub-hosted
  runners. Neither handles data; both are trust relationships worth naming once.
- **B3 (air-gap status) is still open.** If the target machine is air-gapped,
  neither `uv sync` nor `ollama pull` works there, and no offline install path
  exists — no Dockerfile, no wheel bundle, no runbook (`README.md` → *Not built
  yet*). This is a schedule risk as much as a security one.

*Recommendation.* Answer B3 now; if air-gapped, produce a wheel bundle
(`uv export` + `uv pip download`) and a side-loaded model bundle, and test the
install on a disconnected machine **before** handover week.

---

### Group D — Wrong conclusions from a working system

The PoC's product is a defensible answer about models. These risks do not break
anything; they make the answer wrong while everything looks fine.

---

**D1 · Nothing bounds the prompt against the model's context window**
· Severity: **High** · Control status: **absent**

*Scenario.* One call per record carries the full narrative plus every feature's
description plus, for enums, the **full code→label list** plus the JSON schema.
Model servers apply their own context limit and, when the input exceeds it,
**truncate rather than refuse**. The model then answers about text it never saw.
Every affected feature scores `missing`, recall falls, and the result is
indistinguishable from a model that reads badly — including in the ranking,
which is the deliverable.

Long narratives are exactly the records where extraction matters most, and
richly-coded feature sets are exactly the configurations an analyst will build
after the census.

*Evidence.* `grep` over `ra2/` finds no `num_ctx`, no `max_tokens`, no length
check. `domain/prompt.py:361`'s `estimate_tokens` exists and is used only to
render "≈ N" in the prompt preview (`ra2/services/prompt_service.py:202`).
Nothing compares it to anything, and no context option is sent — the
OpenAI-compatible surface does not carry one, so the server's default applies
unless it is set on the model itself.

*Recommendation.*
1. Record the resolved prompt's token estimate on every extraction (one integer
   column) and the configured context size on every run.
2. Validate at evaluation setup: estimate the prompt for the corpus's longest
   narrative and refuse to launch — or warn loudly — above a configured budget.
3. Decide how the context size is set for real runs (a Modelfile per model, or
   the native API's options) and record the decision with the run. This is a
   `sw-design.md` §15 question, not an implementation detail.
4. At M34, verify against the real server version that a long record is not
   silently truncated. One record, once, deliberately.

---

**D2 · Unreadable model output scores as "missing" on every feature, and the
parse-failure rate does not reach the results** · Severity: **Medium** ·
Control status: **partial**

*Scenario.* A model that cannot hold the JSON schema produces
`parse_ok=False`, no `extraction_value` rows, and therefore — through
`_model_answers` (`ra2/services/scoring_service.py:373`) — a `missing` outcome
for every labelled feature of that record. Recall drops; precision does not.
Arguably correct, but it conflates *"cannot follow a schema"* with *"cannot read
the text"*, and those are different answers to the question the PoC asks.

The rate **is** measured and shown on the run progress card
(`ra2/ui/components/progress_card.py:84`), which is good. It does not appear
anywhere on Results or Ranking, so the person reading the ranking three days
later has no reason to suspect it.

*Recommendation.* Carry the parse-failure rate onto the Results header and into
the ranking's reported-never-scored group, beside latency and VRAM — where
`mvp-spec.md` §11.5 already puts exactly this kind of figure. Same argument as
the dev-sized marker: the number that qualifies a result must travel with it.

---

**D3 · Reproducibility is claimed more strongly than local inference supports**
· Severity: **Medium** · Control status: **partial**

`vision.md` requires every run to be reproducible "from its record alone", and
the record is genuinely rich: model name and digest, prompt template id and
fingerprint, temperature, seed, feature fingerprints, corpus version, host
platform, GPU name, endpoint.

Two gaps remain:

- **Same seed does not guarantee same output.** Batching, KV-cache reuse,
  driver and runtime version, and non-associative floating-point accumulation
  all move results on GPU inference. The provenance is necessary but not
  sufficient, and no document says so.
- **The server's own version and decoding options are not recorded.** The model
  digest pins the weights; it does not pin the runtime or the context size (D1).

*Recommendation.* Record the model server version (and, once D1 is decided, the
context size and any decoding options) on the `run` row, and state the
determinism caveat once, plainly, in the evaluation report template. An honest
caveat costs nothing; a reproducibility claim that fails in front of a
stakeholder costs the project's credibility.

---

**D4 · Ground truth may be too thin to answer the question**
· Severity: **Medium** · Control status: **in place**

The project's own biggest technical risk, already well handled: the single
examined record had every human-coded field empty, the census exists precisely
to measure this before feature selection, empty cells are excluded from
denominators rather than scored as absent, and every metric carries its
labelled-case count.

*Residual.* The outcome may be that the PoC cannot answer its question on this
data. That is a legitimate and valuable finding — **provided it is reported as
one**. The risk is presentational: a report full of suppressed cells and thin
denominators reads as a failed project unless it says, in the first paragraph,
that measuring the sparsity *was* a deliverable.

*Recommendation.* Write the census finding up as a standalone result with its
own conclusion, before the model numbers exist, so that it stands on its own
rather than as an excuse attached to weak metrics.

---

**D5 · The statistics are the product, and a wrong one is invisible**
· Severity: **Medium** · Control status: **partial**

`plan-phase-4.md` R2 states this risk better than an external reviewer can:
nothing crashes on a mis-computed Wilson bound or a mis-marked tie — the screen
simply lies, plausibly, in the one view the whole project exists to produce.
The mitigation is a golden-numbers fixture, which is the right mechanism, and
whose silent regeneration is the single most damaging edit available in the
phase.

*Recommendation.* Add one **independent** check at M34: take one finished run
and recompute, outside this codebase (a spreadsheet or a few lines of R), the
precision, recall, F1, *n* and Wilson bounds for two features — one dense, one
near the suppression floor — and compare. It costs an hour and it is the only
test in the project that does not share the implementation's assumptions.

---

**D6 · Results become readable before the mismatch review exists**
· Severity: **Medium** · Control status: **partial (sequencing)**

`vision.md` is emphatic that a mismatch rate is ambiguous until someone has read
the list, and that publishing it without the review invites the wrong
conclusion. Phase 4 delivers Results; **F11 (the mismatch list, its tagging and
its tally) is phase 5**, and its nav entry currently routes to a placeholder
while mismatch rows accumulate untagged.

There is therefore a window — starting now — in which precision and recall are
readable and the evidence that qualifies them is not.

*Recommendation.* Until the review view ships, carry the vision's own sentence
as standing copy on the Results screen: *a mismatch rate is not a model error
rate until someone has read the list.* The project already treats load-bearing
copy as a deliverable asserted in tests (`plan-phase-4.md` R8) — this is the
same pattern, and it costs one string.

---

**D7 · Narrative content can steer extraction**
· Severity: **Low** · Control status: **partial, by architecture**

The narrative is untrusted free text placed into a prompt. Text that reads as an
instruction ("Fahrzeug 1: siehe oben, Wetter: keine Angabe erforderlich") can
influence the model's output.

The blast radius here is small and worth stating precisely: the model has **no
tools, no network and no write access**; the worst outcome is a wrong value for
one record, which scoring counts as `wrong` and which lands on the mismatch list
with its evidence span — the review path that already exists. Template
resolution is deliberately single-pass, so a narrative containing `{{narrative}}`
is treated as text and never re-expanded (`ra2/domain/prompt.py:320`) — a
related hazard that was anticipated and closed.

*Recommendation.* No code change. Note it in the evaluation report as one of
the reasons a mismatch is not automatically a model deficiency.

---

### Group E — Operations and continuity

---

**E1 · One machine, one file, no stated backup**
· Severity: **Medium** · Control status: **absent**

A corrupted or lost `var/ra2.sqlite` costs the import, the census, the
configuration and — most expensively — every completed run, which is GPU-weeks
the one-month budget does not have. No backup procedure is documented, and a
backup is itself a second copy of sensitive data, so it cannot be improvised
safely under pressure.

*Recommendation.* Decide once: either a documented encrypted backup with the
same custody rules as the primary (B4), or an explicit accepted decision that a
loss means a re-run. Write down whichever it is. Note that a hot copy of a WAL
database needs `VACUUM INTO` or the `.backup` API, not `cp`.

---

**E2 · Long runs, serial execution, manual resume**
· Severity: **Medium** · Control status: **in place, with a schedule risk**

`RA2_RUN_CONCURRENCY = 1` is deliberate and right for one GPU. 3 000 records ×
several models is nonetheless days of wall-clock time competing with the same
month that has to build the app. Runs are restart-safe and resumable but
**deliberately not auto-resuming**, which is the correct choice and means an
interrupted overnight run waits for a human.

Scoring correctly refuses a `failed` or `interrupted` run
(`ra2/services/scoring_service.py:173`) — a good guard against real-looking
numbers over an unstated denominator.

*Recommendation.* Plan the evaluation calendar explicitly, in days, against the
remaining budget; decide in advance whether an interrupted run is resumed or
discarded; and make sure the machine's power and update policy will not reboot
it mid-run (a managed Windows workstation will, if allowed to).

---

**E3 · Handover is not built, and the gap pulls a developer back onto the
machine** · Severity: **Medium** · Control status: **absent (deferred by
design)**

The installer and runbook are explicitly deferred (`mvp-spec.md` §16), which is
a defensible cut. The operational consequence is worth seeing: `vision.md`
promises analysts who never touch a command line, while today changing the LLM
endpoint means editing `.env` and restarting — the settings dialog says so
honestly in a notification (`ra2/ui/views/evaluation_view.py:1550`) rather than
pretending to save. Every such gap routes an analyst back to a developer, and
the developer works on the machine holding real data. Informal access spreads
that way, quietly, and nobody records it.

*Recommendation.* When the runbook is written, treat the handful of tasks that
still need a shell as a numbered list with exact commands, and name who is
allowed to run them. If a developer must work on the machine, that is a
decision to record once, not a habit to fall into.

---

### Group F — Organisation, people and governance

---

**F1 · The acceptance of the risk is recorded; the accountability around it is
not** · Severity: **High** · Control status: **absent**

`vision.md` states the position well: the joined record is identifying, the risk
is "understood and accepted", the basis is that the app runs locally, no data
leaves the host, and analysts are under NDA. That is more than most projects
write down.

What is missing is everything that turns an accepted risk into a managed one:

- **who** accepted it (a named role, not the document);
- the **legal basis and the data owner** on the supplier's side;
- a **retention period and a destruction date** (B3);
- **what happens if it goes wrong** — who is told, within what time, by whom.
  There is no incident path. Combined with the deliberate absence of logging
  and audit, a suspected incident would be difficult to investigate at all.
- whether a **DPIA / Bearbeitungsreglement** is required for this processing
  and, if so, whether it exists outside this repository.

*Recommendation.* One page, owned by the project lead and agreed with the data
supplier, covering: owner, basis, scope, retention, destruction, permitted
outputs (B2), incident contact and response time. It is a day's work and it is
the single highest-value item in this report after A1. The technical posture is
already strong enough to make that page easy to write.

---

**F2 · "No auth, no roles, no audit" is right for the assumed deployment, and
the assumption is not written as a condition** · Severity: **Medium** ·
Control status: **partial**

The decision (`vision.md` → Non-goals) is well reasoned for one analyst on one
machine. It silently depends on conditions nobody has stated: the machine is
not shared, the session is not remote-desktopped, the server is bound to
loopback (A4), the OS account is the access control. If any of those changes,
the app has no second line of defence and no record of who did what.

*Recommendation.* Promote the assumption to a stated deployment condition in the
runbook, and re-open the decision if the machine is ever shared. The design note
"nothing should be designed that makes adding [access control] impossible" is
already honoured; this is about noticing when the day arrives.

---

**F3 · Scope drift — a PoC that works gets used**
· Severity: **Medium** · Control status: **partial**

Non-goals are explicit (not production, no write-back, no integration). Nothing
technical prevents a successful PoC from being handed a larger corpus and
operated as a standing service — the code is good enough that this is a
*likely* outcome, not a cynical one. At that point every deferred control (auth,
audit, retention, backup, multi-user) is missing simultaneously, and the
original risk acceptance — which rested on one machine and a small named group —
no longer describes reality.

*Recommendation.* Write the decommission condition down with the PoC's end date,
and attach a short "what would have to be true to operate this for real" list:
authentication, audit, retention and deletion, backup, a DPIA, and a named
operator. Producing that list while the reasoning is fresh costs an hour and
makes the next conversation an engineering one rather than an argument.

---

**F4 · Key-person concentration**
· Severity: **Medium** · Control status: **partial**

The system is built by one developer with AI agents, at high speed, with
exceptional written architecture (`sw-design.md`, `CONTRACTS.md`, the phase
plans) — which is the strongest possible mitigation and genuinely reduces this
risk. What is *not* written down is the operational knowledge: GPU and driver
setup, Ollama configuration, model choice, how the evaluation corpus was cut,
what went wrong and how it was fixed.

*Recommendation.* Keep a plain operations log alongside the runbook from the
first real run — endpoint, model, dates, incidents, decisions. It is also the
provenance record the evaluation report will need.

---

**F5 · External dependencies still open, and they gate the month**
· Severity: **Medium** · Control status: **tracked, not closed**

`mvp-spec.md` §18 lists them: codelists (B1), GPU and VRAM (B2), air-gap status
(B3), real delivery files (B4). Several of this report's findings depend on the
same answers — A2 on B2, A3/C3 on B3, B5 on the `UnfHergangTextAnonym`
question, D1 on the real corpus's longest narrative.

*Recommendation.* Chase them as a single list with named owners and dates. They
are other people's decisions, they have the longest lead times of anything in
the project, and four of this report's recommendations unblock the moment they
land.

---

## 5. Consolidated recommendations

**Status** is maintained as findings close: `open` until there is a
remediation entry in §8, then `✓ §8.n` pointing at it. **`◑`** means the code
is done and a decision for the project is not — the entry says which. It is
the only part of this document that is kept current; the register in §4 stays
as written at `616bf2b`.

**Now — before the next real import** (small, mostly code)

| # | Status | Action | Risk | Effort |
|---|---|---|---|---|
| 1 | **✓ §8.1** | `trust_env=False` on every HTTP client the adapter builds, plus a proxy-environment test | A1 | 1 h |
| 2 | **✓ §8.2** | Content-shaped real-data guard, wired into CI as well as pre-commit | C1 | ½ d |
| 3 | **✓ §8.3** | Add Do-NOT #13 (agents never read `data/` or `RA2_DATA_DIR`) and a matching permission deny rule | C2 | 1 h |
| 4 | **✓ §8.4** | Suppress verbatim value samples for non-coded columns; classification header on every export | B1 | ½ d |
| 5 | open | Render the anonymisation marking as three states until its semantics are confirmed | B5 | 2 h |

**Before the evaluation corpus is cut** (validity of the answer)

| # | Status | Action | Risk | Effort |
|---|---|---|---|---|
| 6 | open | Record prompt token estimate per extraction; validate against a context budget at setup; decide how context size is set | D1 | 1 d |
| 7 | open | Carry the parse-failure rate onto Results and Ranking | D2 | 2 h |
| 8 | open | Record model-server version and decoding options on the run; state the determinism caveat in the report template | D3 | 3 h |
| 9 | open | Constrain `root_path` to an allowed root; make the server honour `Settings.host` or drop it | A4 | ½ d |
| 10 | open | Standing copy on Results: a mismatch rate is not a model error rate until the list is read | D6 | 1 h |

**Organisational — no code, highest leverage**

| # | Status | Action | Risk | Effort |
|---|---|---|---|---|
| 11 | open | The governance page: owner, basis, retention, destruction, permitted outputs, incident path | F1, B2, B3 | 1 d |
| 12 | open | Deployment conditions in the runbook: disk encryption, custody, no cloud-synced data dir, loopback bind, model-server pinning, no tunnels | B4, A2, A3, F2 | ½ d |
| 13 | open | Extend the NDA or equivalent to the reviewing domain expert before Goal 3's review | B2 | — |
| 14 | open | Delivery delete + `VACUUM`; decide and document backup vs. accepted re-run | B3, E1 | ½ d |
| 15 | open | Close B1–B4 with named owners and dates; write the decommission condition and the "to operate for real" list | F5, F3 | ½ d |

**At the acceptance pass (M34)**

| # | Status | Action | Risk |
|---|---|---|---|
| 16 | open | Independent recomputation of one run's statistics outside this codebase | D5 |
| 17 | open | Verify a long record is not silently truncated by the real server | D1 |
| 18 | open | Check one run's provenance against the machine it claims to have run on | A2 |

---

## 6. Open questions for the data owner and the project

1. Who is the named owner of this processing, and what is its legal basis?
   (F1)
2. How long may the corpus remain on the machine, and what evidence of
   destruction is required? (B3)
3. What may leave the machine — census export, per-record lists, mismatch lists
   with evidence spans, the evaluation report — and who may receive each? (B1,
   B2)
4. Is the target machine air-gapped? (B3 in `mvp-spec.md`; drives C3 and A3)
5. What is the exact semantics of `UnfHergangTextAnonym`, and is the delivered
   text file anonymised at all? (B5)
6. Is the workstation's disk encrypted, is the data directory excluded from any
   cloud synchronisation, and is the machine single-user? (B4, F2)
7. Is the domain expert who will review Goal 3 evidence covered by the same NDA
   as the analysts? (B2)
8. Is there an existing incident-reporting route for this data, and what is its
   time bound? (F1)

---

## 7. Appendix — how the verified findings were checked

| Finding | Check | Result |
|---|---|---|
| A1 | `HTTP_PROXY=… uv run python -c "openai.AsyncOpenAI(base_url='http://127.0.0.1:11434/v1', …)"`, then inspect the transport chosen for the loopback URL | `trust_env: True`; transport is the proxy pool for `proxy.corp.example:3128` |
| B1 | Aggregate SQL over `census_column` / `census_value` in `var/ra2.sqlite` (read-only, immutable), counting stored top values whose count is 1. No values printed | Coordinates 16–18 singletons of 20 per column; all three UID columns 20 of 20 |
| C1 | Astrana filenames from `mvp-spec.md` §4.1 against `FORBIDDEN_PATTERNS` in `scripts/check_no_real_data.py` and `.gitignore` | `Unfall.csv`, `Objekt.csv`, `Mitfahrende.csv` match no pattern outside `data/`; CI does not run the guard |
| C1 | `GET https://api.github.com/repos/stroumpfai/ra2` | `"private": false`, `"visibility": "public"` |
| A4 | Read of `ra2/api/v1/deliveries.py`, `ra2/services/delivery_service.py`, `ra2/infra/filestore.py`; grep for readers of `Settings.host` | Arbitrary `root_path` accepted; whole files read to hash; no module reads `Settings.host` |
| D1 | grep over `ra2/` for `num_ctx`, `max_tokens`, `context`, `truncat`, and for callers of `estimate_tokens` | No context option sent, no length validation; `estimate_tokens` used only in the prompt preview |
| D2 | Read of `ra2/services/scoring_service.py:373` and `ra2/ui/components/progress_card.py:84` | No `extraction_value` rows → `missing`; rate shown on the progress card only |

---

## 8. Remediation log

Appended after the review, one entry per finding closed. The register above is
**not** edited: it says what was true at `616bf2b`, and an entry here says what
changed since and where to verify it. A finding with no entry is still open.

### 8.1 A1 — the proxy environment variable · closed 2026-09-17 · `39c72e0`

**Status: in place.** Severity was **High**; the residual is the part no code
reaches — see *What this does not close*.

**What changed.**

| Where | Change |
|---|---|
| `ra2/infra/ollama_client.py` | `_build_client` now builds the transport itself, `openai.DefaultAsyncHttpx2Client(trust_env=False, follow_redirects=False)`, instead of letting the SDK construct one with `trust_env=True`. All three classes — `OllamaLLMClient`, `OllamaModelCatalog`, `OllamaEndpointProber` — route through it, so one change covers every client the adapter builds |
| `ra2/infra/ollama_client.py` | `_reject_environment_reading_client` refuses an **injected** `http_client` carrying either flag. The `http_client` seam exists so the tests can drive a `MockTransport` (Do-NOT #12); a seam that accepted a looser client than production builds would make the guarantee true only of the path nobody runs |
| `tests/backend/infra/test_ollama_client.py` | A section of eleven tests, *The environment cannot move the socket*. The proxy ones set `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` and a `NO_PROXY` that deliberately does **not** cover localhost, then assert on the transport `_transport_for_url` actually selects for the loopback URL — not on the flag, because the transport is what the defect was. They exercise the **production** path, with no `http_client` injected, which is the one path the rest of the file never touched and the only one that had the defect |
| `sw-design.md` §13, §15.5 | **SD27**, and the paragraph *The guard is half the rule; the transport is the other half* |
| `README.md` | *The loopback rule* now says both halves. The claim that the guard makes off-host traffic "impossible rather than merely discouraged" is true again |
| `CLAUDE.md` | The *Loopback only* agreement names the transport half |

**`follow_redirects=False` was not in the recommendation** and is added here as
a second finding of the same shape, found while fixing the first: the SDK's
default is `True`, and a `307`/`308` preserves the method and the body, so
whatever answers on `127.0.0.1:11434` can hand the narrative to an off-host URL
that the guard never saw. Same hole, read the other direction.

**How it was verified.**

| Check | Result |
|---|---|
| The reviewer's own reproduction, re-run on the pinned versions before the change | `trust_env: True`; transport for the loopback URL is `httpcore2.AsyncHTTPProxy` with `_proxy_url` `proxy.corp.example:3128` — the finding confirmed on `main` |
| The same inspection after the change | `trust_env False`, `_mounts {}`, pool `AsyncConnectionPool`, no proxy URL |
| The new tests against the **unfixed** adapter (`git stash` of the one module) | 9 of them fail — the regression gate is real, not tautological |
| `test_the_proxy_check_can_tell_the_difference` | A positive control: under the same environment, a client built with `trust_env=True` **is** seen to dial through the proxy. Every other assertion in the section is a negative one, and a negative assertion that cannot fail is worse than none. The reviewer's `_proxy` / `_proxy_url` distinction is exactly how this would have gone quiet |
| `just lint`, `just test` | Green |

**What this does not close.** **A2 is untouched and unchanged.** This makes the
environment unable to move the socket; it still cannot see what is listening on
the other end of it. A tunnel, a forwarder or an Ollama configured to relay
remains invisible to every control in this codebase, and the answer to it is
still the runbook sentence A2 asks for and the M34 provenance check.


### 8.2 C1 — the real-data commit guard · code closed 2026-09-17 · `2e401bc` · visibility open

**Status: in place for the guard, open for the repository's visibility.** Two
of the three recommendations are done; the third is a project decision.

**What changed.**

| Where | Change |
|---|---|
| `scripts/check_no_real_data.py` | Rewritten. The `.gitignore` name patterns stay as defence one; the new content check decides what a file **is**, through `ra2.domain.parsing.headers.classify_header` — the importer's own classifier, so there is no second copy of the column vocabulary. Two copies of one pattern list, both wrong in the same way, is what C1 found; the fix keeps one copy and it is not this script's |
| `scripts/check_no_real_data.py` | A delivery-shaped file is refused unless it is under `tests/fixtures/deliveries/` **and** its keys were invented rather than delivered. `generate_hazards.uid()` yields three to five distinct characters out of thirty-two; a real 32-hex key yields about thirteen, so `MAX_INVENTED_DISTINCT_CHARS = 8` sits in empty space between two populations rather than on a guess |
| `.github/workflows/ci.yml` | A `no-real-data` job, **first and depending on nothing** — no `uv sync`, no cache, no `needs`. It runs `--all`: every tracked file, not the pull request's changed ones |
| `.pre-commit-config.yaml`, `justfile` | The hook says *name and content* and runs through `uv run python`; `just check-data` runs the same check over the tree |
| `tests/backend/scripts/test_check_no_real_data.py` | Twenty-four tests |
| `contracts/amendments/fix-c1-real-data-guard.md`, `CONTRACTS.md` | All four files are M0-frozen. Amended and applied in one commit, the way the reset-and-discard slice did |

**The second rule is the one no other control covered.** CLAUDE.md requires the
hazards to be synthesised byte-exactly and forbids real data reaching a test.
Until now that was prose. Lifting five real rows into a fixture because the
synthesised one did not reproduce the bug is the plausible, tempting mistake,
and it passed every check in this repository.

**How it was verified.**

| Check | Result |
|---|---|
| `Unfall.csv` — the reviewer's own example — generated with delivered-entropy keys, staged with `git add -f`, and the **real pre-commit hook** run against it | Refused: *"looks like a delivery file, and only tests/fixtures/deliveries/ may hold one"*. The old guard passed this file |
| The same content renamed `notes/scratch.bak`, and a headerless tail with no header line at all | Both refused |
| The fourteen committed hazard fixtures, which are delivery files by construction — real header, real delimiters, 32-hex keys | All pass. A guard that refused them would be switched off within a day |
| A fixture-directory file carrying delivered-entropy keys | Refused: *"fixtures are synthesised, never sampled"* |
| `--all` over every tracked file | Green — so, as of this commit, there is no real delivery content anywhere in the repository |
| `python -S -E scripts/check_no_real_data.py` (no `site`, no `site-packages`) | Exit 0, which is what lets CI's job run on a bare interpreter with no install step |
| `just lint`, `just test` | Green |

**What this does not close.** **The repository is public**
(`github.com/stroumpfai/ra2`, `"private": false`). C1's third recommendation is
to reconsider that for the duration, and it is a decision rather than a diff. A
private repository gives a window to force-push a mistake away; a public one
does not — content should be assumed mirrored the moment it is pushed. The
guard makes the mistake much harder to make; it cannot make it recoverable.
That is why C1's row is marked `◑` and not `✓`.

**A limit of the guard itself, recorded rather than hidden.** The headerless
detector keys on the *first* field, so a RADIS tail is caught and an Astrana
tail — whose key sits at column 2, after `Jahr` and `Datum` (§4.1) — is not.
Both are caught the moment the header line is present, which is how a delivery
arrives.


### 8.3 C2 — reading the real corpus while building · rule closed 2026-09-17 · `e8c5a45` · checkout separation open

**Status: in place for the rule and the deny list, open for the second
recommendation.** Do-NOT #11 forbade *committing* real data. Nothing forbade
*reading* it — and agent transcripts leave the host by construction, so an
agent that opens a real narrative to debug an import has exported that record
as surely as an upload would.

**What changed.**

| Where | Change |
|---|---|
| `sw-design.md` §12, `CLAUDE.md` | **Do-NOT #13** — *never open, query, print or paste the contents of `data/` or `RA2_DATA_DIR`. Reproduce the hazard in a fixture instead.* Worded as an act, not as a path: "do not access" reads as a filesystem rule, and the database is the easier mistake. The only invariant addressed to the people and agents building RA2 rather than to the code, and §12 says why |
| `.claude/settings.json` *(new, committed)* | `Read(./data/**)`, `Read(./var/**)`, `Bash(sqlite3 *)`, plus the matching `sandbox.filesystem.denyRead`. A `Read(...)` deny rule is merged into the sandbox's read denials, so it covers a sandboxed `cat` and `grep` as well as the Read tool |
| `.gitignore` | `.claude/` -> `.claude/*` + `!.claude/settings.json`. **The load-bearing half**: a deny rule in an ignored directory protects the one machine it was written on, and C2 is about the development practice, not one workstation |
| `tests/test_m0_contract.py` | The Do-NOT count is now compared against `sw-design.md` §12 instead of the literal `12`, so adding an invariant to one document and not the other is a red test |
| `contracts/amendments/fix-c2-agent-data-access.md`, `CONTRACTS.md` | `sw-design.md`, `CLAUDE.md` and the contract test are amended. The amendment also **retroactively covers** `CLAUDE.md`'s loopback edit in `39c72e0`, which went in without one, and corrects its row in `CONTRACTS.md` |

**How it was verified.** The rules were exercised live in the session that
wrote them, not merely written:

| Probe | Result |
|---|---|
| `cat data/nonexistent-c2-probe.txt` — a path that does **not** exist | Denied. The block is on the path, before the file is resolved, which is the property worth having |
| A write and read under `var/` | Denied |
| `head -c 40 README.md` — the control | Allowed, exit 0. The denial is specific to `data/` and `var/`, not a blanket block that would be turned off within a day |
| Removing #13 from `CLAUDE.md` alone | `test_claude_md_carries_the_do_not_list` fails |
| `just lint`, `just test` | Green |

**What this does not close.**

**C2's second recommendation — keep real data off the development checkout
entirely.** Real delivery files and the real corpus on the target machine,
synthetic hazards everywhere else. `data/` and `var/ra2.sqlite` are on this
machine today. That is the control that would make #13 unnecessary rather than
merely stated, and it is a project decision. The fixture discipline that makes
it affordable is already in place.

**And the honest limit of a deny rule.** It guards one tool on one configured
path. `RA2_DATA_DIR` can point anywhere and a glob cannot cover a path it has
not been told about; a subprocess that opens a file itself is not intercepted;
`Bash(sqlite3 *)` is a speed bump that `python -c "import sqlite3"` walks
around; and a Playwright trace taken against a real corpus would land in
`test-results/`, which is deliberately **not** denied, because E2E runs on
synthetic data today and denying it would block debugging a hazard that does
not yet exist. **#13 is the control. The deny list is what catches the lapse.**


### 8.4 B1 — verbatim values in the census export · closed 2026-09-17 · `72f311b` · screening open

**Status: in place for the suppression and the marking, open for the human
step.** The census CSV is the week-one deliverable and the artefact most
*meant* to be shown to other people, and it carried the top 20 raw values of
every column — including four `Koordinate` columns at metre precision and three
UID columns, 16 to 20 of each column's 20 stored values occurring exactly once.
A value that occurs once is one accident.

**What changed.**

| Where | Change |
|---|---|
| `ra2/domain/census.py` | `SHAREABLE_TYPE_HINTS` / `sample_is_shareable` — the one statement of which columns' values may leave the corpus, true only for `ENUM`. In `domain` because `census_service` and `export_service` both need the same answer; a rule stated twice is a rule that drifts, and the half that drifts is the half nobody looks at |
| `ra2/services/census_service.py` | Applied in `_to_view`, so the Census view, the API and the CSV get one answer. **Read time, never write time**: a corpus is immutable, so a write-time filter would leave every corpus frozen before today still carrying its values into every export. This covers those and needs no migration — the `SD19` shape |
| `ra2/services/readmodels.py`, `ra2/api/schemas.py`, the CSV header and the OpenAPI snapshot | `top_values_withheld`. `top_values == ()` already meant *empty in every row* (hazard h08), which is the **opposite** conclusion for feature selection. Collapsing the two would hand a reader a finding the data does not support |
| `ra2/services/export_service.py` | `CLASSIFICATION_COMMENT`, written by `_write_csv` — the one place all **six** exports pass through, so the line is guaranteed rather than remembered, and written first because the first line is the one a reader sees before deciding what to do with the file |
| `ra2/ui/views/census_view.py` | The third bar state. The screen holds to the rule the export holds to, because the screen is the easier of the two places to copy a value out of by hand |
| `mvp-spec.md` §6, `sw-design.md` §7 + `SD28` | The *what* changed, so it landed in `mvp-spec.md` first (CLAUDE.md's document authority) |

**Only the raw values are withheld.** Populated count and rate, distinct count,
top-value share, long-tail flag and type hint all survive — those are what
feature selection actually reads (mvp-spec.md §6), and a rule that took them
too would have made the deliverable useless rather than safe.

**How it was verified.**

| Check | Result |
|---|---|
| The existing hand-computed census fixture, which already held all three states — `UnfallUid` (five values, each once), `WetterAusw` (coded), `StrasseName` (empty in every row) | Sample withheld, sample kept, sample absent-and-not-withheld. No new fixture was needed to show the finding |
| The census CSV, byte-exact, through the HTTP API | A coded column keeps `5:3\|3:1`; a `Koordinate` column exports `;;True` and the coordinate string appears nowhere in the row |
| The Census view, through the real renderer | The withheld row draws an empty track and the legend *values withheld · aggregates only* — never "no values", which an analyst would read as an empty column |
| The view handed the contradictory state (flagged withheld, still carrying values) | Nothing of them reaches the page. The branch is on the flag, so the property holds for any caller of the read model, not only the one that empties it |
| The same UI tests with the view's branch removed | Two fail. The branch is load-bearing, not decorative |
| `just lint`, `just test` | Green |

**The cost, chosen rather than discovered.** A code appearing in a single
record is still exported, because the line is drawn at the **header** — the
delivery's own `Ausw` / `` UAP`` marking — rather than at a frequency. The
mirror of it is that Astrana's `Kanton Kürzel`, a two-letter canton code by any
reading, loses its sample because that format does not use the suffix. A
frequency floor reusing `Settings.min_cell_count` (20) was the alternative and
would have caught the rare code and kept the canton; the header rule was
preferred because it is one sentence a reader can check against the data
dictionary, and it does not make the deliverable's contents depend on how large
the corpus happens to be.

**What this does not close.**

**Screening an export before it leaves the machine.** B1's third recommendation
is a runbook sentence — *a census export is sensitive until someone has looked
at it* — and this repository has no runbook (risk F1, recommendation 12). The
file now says what it is; a person still has to read it. That is why B1's §1 row
is `◑` and not `✓`.

**B2 is untouched and unchanged.** The mismatch list carries **evidence
spans** — verbatim narrative fragments, mandatory by design — and the
per-record lists and the evaluation report carry their own content. All of
them now leave with a line saying what they are, which is not the same as a
rule about what may be in them. B1 was a sample nobody had decided to include;
B2 is content the design requires, and it needs a decision rather than a
predicate.

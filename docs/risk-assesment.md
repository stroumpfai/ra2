# Risk Assessment — RA2

**External review of the use cases and the implementation.**

**Two passes, two baselines.**

| Pass | Commit | Date | State of the work |
|---|---|---|---|
| **First** | `616bf2b` | 2026-09-16 | Phase 4 (scoring and results) in progress, phase 5 (mismatch review) not started |
| **Second** | `12268ed` | 2026-09-23 | Phases 4 and 5 shipped; development winding down, first operational use imminent |

The first pass wrote §§1–8. The second wrote **§9**, and touched §§1, 3, 5, 6
and 7 where they had become factually wrong or where the maintained status
columns moved. **§4 is not edited by the second pass** — it says what was true
at `616bf2b`, and the findings the second pass adds are in **§9.2**, in the
same form and under the same group letters.

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
as written at `616bf2b`. A row may be `open` **and** name an entry: §8.5
closed a third of an action and left the rest, and saying so is more useful
than a symbol for it.

| # | Status | Action | Effort | Risk |
|---|---|---|---|---|
| 1 | **✓ §8.1** | Build the adapter's HTTP client with `trust_env=False` (a proxy env var currently redirects loopback traffic off-host — reproduced) | ~1 h | **A1** |
| 2 | **◑ §8.6** | Write the data-handling rules the app cannot enforce: outputs, retention, destruction, named owner, incident path | ~1 day, no code | **F1, B2, B3** |
| 3 | **◑ §8.4** | Suppress or gate verbatim value samples in the census export; screen every export before it leaves the machine | ~½ day | **B1** |
| 4 | **◑ §8.2** | Make the real-data commit guard content-shaped and run it in CI; reconsider the repository being public | ~½ day | **C1** |
| 5 | open | Measure and bound the prompt against the model's context window before the evaluation corpus is cut | ~1 day | **D1** |

Nothing found here calls the architecture into question. Items 1, 3 and 4 are
small fixes to controls that already exist; item 2 is the gap that no amount of
code will close.

### Second pass, 2026-09-23 — top five, recalibrated for handover

The first pass's five are above, with their statuses maintained. **§9** re-reads
the project at `12268ed`, with phases 4 and 5 shipped, development winding down
and operational use imminent. The architecture still holds; the finding is that
the register was graded for a project being *built* and the project is now being
*used*. The five that matter most from here:

| # | Status | Action | Effort | Risk |
|---|---|---|---|---|
| 21 | **✔ closed** | **`hide_parameters=True`** — a database error wrote the narrative and `unfall_uid` into `run.error` **and into the log** (reproduced). Fixed at the engine, with a provoked-`IntegrityError` test and a positive control (`contracts/amendments/fix-a5-bound-parameters.md`) | — | **A5** |
| 23·24 | open | An intake mojibake canary and the mixed-encoding fixture — a mixed-encoding delivery is silently corrupted today (reproduced), and real files meet the parser for the first time at handover | ~½ day | **G1, G4** |
| 11·15 | **◑ §8.6** | Fill in `data-handling.md` §7's ten decisions and close `mvp-spec.md` §18's B1–B4. **No longer pending — late**, and four of them gate work that cannot be done afterwards (§6) | ~1 day, no code | **F1, B3, C3** |
| 31 | open | **A stated support path** — what may be copied off the machine when something breaks. The developer is reachable rather than resident, and §9.1.1 is the chain that makes this the dominant technical residual. **Item 21 broke link 5 and did not break the chain**: a screenshot, a hand-typed description and the export all still carry content | ~2 h, no code | **C2, E3** |
| 26·32 | open | Correct and **gate** the README; start an operations log from the first real run. The handover document currently says the deliverable does not exist | ~½ day | **F6, E3, F4** |

**The headline of the second pass is not a defect.** Every technical control in
this report has improved since `616bf2b`, the gates are green, and A5 — the
second pass's lead defect — took one keyword argument and two tests. G1 is
similarly small. What has not moved at all is the organisational half: ten blank
decisions, four unanswered dependencies, no runbook, no rehearsed destruction,
no operations log. At the first pass that imbalance was tolerable because the
system was not in use. **It is now the larger share of the residual risk by a
clear margin**, and §9.1 is why the margin widened without anyone changing a
line of code.

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
| ~~**No logging of any kind** in the application~~ · **superseded 2026-09-22** | was: verified by grep over `ra2/`. Now `ra2/infra/logging.py` + `data-handling.md` §5.1 | **The strongest claim in this table, and it is no longer true.** An operational log to stderr now exists, bounded by a *content* rule with a test behind it (`test_run_log_carries_no_data.py`). The trade is defensible — absence was fragile and nearly broke on the first silent 26-minute run — but a tested rule is a control with a perimeter, where absence had none. **§9.2 A5 was the hole in that perimeter, and it was verified.** Closed by `fix-a5-bound-parameters`: the perimeter now has two halves, the call sites and the engine, and both are tested. |
| **Strict parsing, loud failure** — no `errors="replace"`, no silent repair, every recovered or rejected row reported with its key | `ra2/infra/files.py`, `mvp-spec.md` §4.2 | Corrupted labels are the failure mode that surfaces months later as wrong metrics |
| **Real data cannot reach the test suite** — hazards are synthesised byte-exactly; the one real-data test reads header lines only and skips when absent | `tests/unit/parsing/test_headers_realdata.py` | The discipline is real, not aspirational |
| **Agent isolation already practised** — `just dev-agent` on a random port and a throwaway data dir | `justfile`, `scripts/dev_agent.py` | The precedent needed for C2 exists already |
| **Honest metrics design** — presence has no gold label and says so; `hallucinated` is a tag, not a rate; suppression below *n*; ties rendered as ties; exploratory attributes excluded from ranking | `mvp-spec.md` §11, `sw-design.md` §16 | Most of the ways an evaluation lies to its reader have been anticipated |
| **Documented acceptance of the re-identification risk**, written down rather than assumed | `vision.md` → *Real data* | The right instinct; F1 is about finishing that sentence |

---

## 4. Risk register

Scenarios are grouped by what actually goes wrong, not by which component is
involved. **Control status**: *in place* · *partial* · *absent*.

> **This register is the first pass, at `616bf2b`, and is not edited.** The
> second pass adds **A5**, **B6**, **C4**, **D8**, **E4**, **F6** and a new
> **Group G — data input integrity**; they are in **§9.2**, written in the same
> form and under the same group letters. Where the second pass re-graded a
> severity below, the re-grade is in **§9.3** and the row here is left alone.

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

> **Re-checked 2026-09-18 against `af0150f` — see §8.5; remediated in part the
> same day — see §8.6.** The deletion path exists, and the finding below
> understated the gap it describes rather than overstating it. A discard now
> erases the bytes and not merely the rows, and `data-handling.md` carries the
> destruction procedure — but **the retention period, the destruction date and
> the named signer are still blank**, and they are the larger half. Left as
> written, like every other entry here.

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
as written at `616bf2b`. A row may be `open` **and** name an entry: §8.5
closed a third of an action and left the rest, and saying so is more useful
than a symbol for it.

> **Re-sequenced by the second pass, 2026-09-23.** Row numbers and statuses
> are unchanged — §8's entries cite them — but the buckets are not. The first
> pass sequenced by *kind of work*; with development winding down and
> operational use imminent, the binding constraint is no longer what a task is
> but **when it stops being possible**. The four buckets below are therefore
> gates, in date order, and rows 21–30 are the second pass's additions.
>
> Nothing here is accepted. Every open row is a live recommendation.

### Gate 1 — before the code freeze

*These become impossible afterwards. Roughly three days in total, and they are
the last three days in which any of them can be done.*

| # | Status | Action | Risk | Effort |
|---|---|---|---|---|
| **21** | **✔ closed** | **`hide_parameters=True` on `create_async_engine`**, plus a provoked-`IntegrityError` test with a positive control, and §5.1 of `data-handling.md` stating that the list is enforced at the engine as well as at the call sites. `SD39`; `contracts/amendments/fix-a5-bound-parameters.md` | **A5** | **done** |
| **22** | open | Refuse UTF-16/32 BOMs and NUL bytes in `detect_encoding`, each with its own `FindingCode` | **G2** | 1 h |
| **23** | open | An intake mojibake canary — the mirror of `CP1252_CANARY_ZERO`; one `FindingCode`, no schema change | **G1** | ½ d |
| **24** | open | `h15_mixed_encoding` — the hazard `CLAUDE.md` has required by name since month one | **G4** | 1 h |
| **25** | open | `reset_data.py` prints records and corpora, not bytes, and refuses a non-dev corpus without a second token | **E4** | 2 h |
| **26** | open | Correct the README, and gate it: a test that no shipped nav item appears under *Not built yet* | **F6, E3** | 2 h |
| **27** | open | A synthetic-corpus marker, rendered beside the dev chip and refused by the ranking — **needs a migration, so its deadline is earlier: before real data is in the database** | **D8** | ½ d + migration |
| 6 | open | Record the context length on the run (`/api/show`); **flag any extraction whose returned `prompt_tokens` sits at or near the limit** — the per-extraction counts already exist (§9.4) | D1 | ½–1 d |
| 7 | open | Carry the parse-failure rate onto Results and Ranking | D2 | 2 h |
| 8 | open | Record model-server version and decoding options on the run; state the determinism caveat in the report template | D3 | 3 h |
| 5 | open | Render the anonymisation marking as three states until its semantics are confirmed | B5 | 2 h |
| 10 | open | Standing copy on Results: a mismatch rate is not a model error rate until the list is read — D6 closed by delivery, the string is still worth it | D6 | 1 h |
| 9 | open | Constrain `root_path` to an allowed root; bound the walk; make the server honour `Settings.host` or drop it | A4, G3 | ½ d |
| **28** | open | A contract test: every `Settings` field has a reader in `ra2/`, or it does not exist | G3 | 2 h |
| **29** | open | Helper copy under the mismatch note field, in `EXPORT_LEAVES_RA2`'s voice | B6 | 1 h |

### Gate 2 — before real data lands on the machine

| # | Status | Action | Risk | Effort |
|---|---|---|---|---|
| 20 | **◑ §8.6** | **Rehearse the destruction procedure end to end** on `reset-seed` data. Written, never executed | B3, F1, E4 | 2 h |
| **30** | open | **Decide host-path intake: upload-only for real deliveries.** Deletes destruction step 5 and makes `just reset yes` complete | G3, A4, B3 | decision |
| 15 | open | Confirm **B2 (VRAM)** and **B3 (air-gap)**. If air-gapped, build *and test* the wheel bundle and side-loaded weights **while the developer is still here** | F5, C3 | ½ d + lead time |
| 12 | **◑ §8.6** | Deployment conditions confirmed, not merely written: disk encryption, custody, single-user, no cloud-synced data dir, loopback bind, `OLLAMA_HOST=127.0.0.1`, `OLLAMA_DEBUG` off, no tunnels | B4, A2, A3, F2 | ½ d |
| 11 | **◑ §8.6** | The governance page — **fill in `data-handling.md` §7's ten decisions** | F1, B2, B3 | 1 d |
| 14 | **◑ §8.6** | Decide backup vs. accepted re-run. E4 adds a second way to lose the corpus | B3, E1 | ½ d |
| 13 | open · §8.6 | Extend the NDA or equivalent to the reviewing domain expert before Goal 3's review | B2 | — |
| 3 | **✓ §8.3** | **Move real data off the development checkout** — C2's second recommendation, now near-free (§9.4). Closes C2 and C4 together | C2, C4 | ½ d |

### Gate 3 — at the acceptance pass (M34), once, deliberately

*Unchanged from the first pass except that these now have a date: they are the
go-live gate, and M34 is still unscheduled.*

| # | Status | Action | Risk |
|---|---|---|---|
| 16 | open | Independent recomputation of one run's statistics outside this codebase | D5 |
| 17 | open | Verify a long record is not silently truncated by the real server | D1 |
| 18 | open | Check one run's provenance against the machine it claims to have run on | A2 |

### Gate 4 — standing, during operation

| # | Status | Action | Risk |
|---|---|---|---|
| **31** | open | **A stated support path**: what may be copied off the machine when something breaks, and to where. With item 21 closed this is **the** remaining break in §9.1.1's chain, and the one that does not depend on a control being correct | C2, B2, F6 |
| **32** | open | **An operations log from the first real run** — endpoint, model, dates, incidents, decisions. With the developer reachable rather than resident, this is the only knowledge-transfer mechanism there is | F4 |
| 4 | **✓ §8.4** | Screen every export before it leaves the machine. The classification line is a label; this is the rule | B1, B2 |
| 15 | open | The decommission condition, with a date, and the "to operate for real" list | F3 |

### Closed, or settled as decisions

| # | Status | Action | Risk |
|---|---|---|---|
| 1 | **✓ §8.1** | `trust_env=False` on every HTTP client the adapter builds, plus a proxy-environment test | A1 |
| 2 | **✓ §8.2** | Content-shaped real-data guard, wired into CI as well as pre-commit | C1 |
| — | **decided** | **The repository stays public.** No longer a recommendation; see §9.4 for the two residuals that belong beside the acceptance | C1 |
| 19 | **✓ §8.6** | ~~Write exports to `settings.exports_dir`~~ — **deleted instead**, and the two documents that claimed exports live under the data directory are corrected (`SD30`) | B3, B2 |

---

## 6. Open questions for the data owner and the project

**Questions 1-4 and 6-8 are now carried as the decision table in
[`data-handling.md`](../data-handling.md) §7**, with owner and date columns to
fill in. They are repeated here as the review left them.

> **Second pass, 2026-09-23 — these are no longer pending, they are late.**
> All ten rows of `data-handling.md` §7 are still blank, and `mvp-spec.md`
> §18's B1–B4 are all still open, seven days after the page was written and
> with operational use imminent. Four of them now gate work that cannot be
> done afterwards:
>
> | Question | What it gates | Why the deadline is real |
> |---|---|---|
> | **4 · air-gap status** (B3) | The offline install path — a wheel bundle and side-loaded weights | There is no Dockerfile and no installer (F6). If the answer is *air-gapped*, this must be built **and tested** while the developer is still resident. Longest lead time of anything in the project |
> | **B2 · GPU and VRAM** | Which models are testable at all | Unanswered hardware is what makes A2's tunnel tempting, and A2 is now **High** |
> | **6 · disk encryption, single-user, no cloud sync** | Whether every deletion in `data-handling.md` §4 means anything | The machine goes into use. B4 is now **High**, and "unknown — not recorded" stops being tolerable when the recording *is* the control |
> | **5 · `UnfHergangTextAnonym` semantics** | What the anonymisation marking may claim (B5) | One email, and it decides whether the chip is a privacy statement or provenance. It should be sent before the first real corpus is cut, not after |
>
> Questions 2, 3, 7 and 8 — retention, permitted outputs, NDA cover and the
> incident path — do not gate code, but they are the whole of F1, and F1 is
> **overdue** rather than open.

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

**Second pass, 2026-09-23, at `12268ed`.** All four executed checks use
synthetic bytes or synthetic rows in a throwaway temporary database. No project
data was opened, queried or printed (Do-NOT #13).

| Finding | Check | Result |
|---|---|---|
| **A5** | A duplicate-key insert forced through the project's own `create_engine`, on a temp database with two synthetic rows, then `f"{type(exc).__name__}: {exc}"` — exactly `_error_text` — inspected for the planted narrative and key | Both present. SQLAlchemy's `hide_parameters` defaults to `False` and `create_async_engine` is called without it (`session.py:97`). **Re-checked 2026-09-24 after the fix**: absent through `create_engine`, still present through a default-built engine, which is the control |
| **G1** | Six synthetic byte-layouts through `ra2.domain.parsing.encoding.detect_encoding`, including UTF-8 bytes followed by cp1252 bytes in one file | Whole-file fallback to cp1252; the UTF-8 portion returns as `GrÃ¼ezi`. No finding beyond `ENCODING_DETECTED` |
| **G2** | The same harness, with UTF-16LE with and without a BOM | With BOM → `cp1252`, text `'ÿþU\x00n\x00f…'`. Without BOM → `utf-8`, text `'U\x00n\x00f…'`. Neither is refused; only the UTF-8 BOM is recognised |
| **G4** | `ls tests/fixtures/deliveries/hazards/` against `CLAUDE.md`'s named hazard list | `h01`–`h14` present; no mixed-encoding fixture. `h01_cp1252` is whole-file, `h02_undecodable` fails the file |
| **C1** | Read of `scripts/check_no_real_data.py` and `.github/workflows/ci.yml`, since the guard is now a permanent rather than an interim control | Content-shaped via `classify_header`, headerless fallback on a 32-hex key plus delimiter, `_was_invented` excludes fixture keys, stdlib-only, runs first in CI with `--all` over every tracked file |
| **A4 / G3** | Re-grep for readers of `Settings.host` and `Settings.port` across `ra2/` and `scripts/` | Still none. `scripts/dev_agent.py:37` sets `RA2_PORT` in the environment, which nothing reads; the port it binds is passed on the uvicorn command line |
| **D1** | Re-grep for `num_ctx`, `max_tokens`, a context budget, and callers of `estimate_tokens`; read of `OllamaModelCatalog` | Still no context option, no budget check. `prompt_tokens`/`completion_tokens` **are** now recorded from the endpoint. The catalogue calls `/api/tags` only, never `/api/show` |
| **D2 / D3 / D6** | Greps over `ra2/services/results_service.py`, `ranking_service.py`, `ra2/ui/views/results/` | Parse-failure rate absent from Results and Ranking; no model-server version on `run`; no standing mismatch-rate copy. The Mismatches view itself exists, which is what closes D6 |
| **D8** | Read of `corpus_service.py:189` and every `is_dev` / `is_dev_sized` site | `is_dev_sized = record_count < dev_record_max`. A size threshold; no provenance marker anywhere |
| **F6** | Read of `README.md` → *At a glance* and *Not built yet*, against the shipped nav | "Scoring, Results and Mismatches … nothing scores them yet … route to a placeholder" — false on all three. "No Dockerfile exists today" — still true |
| — | `just test` | 2 521 passed, 1 skipped, 96.1 % coverage, 31 s |

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

### 8.5 B3 — the deletion path · re-checked 2026-09-18 against `af0150f` · one third closed

**Status: in place for the deletes, absent for erasure, open for retention.**
B3 named three things: no delivery delete, no `VACUUM`, no retention rule. The
first landed. The second is still absent and is now **verified** rather than
inferred. The third is untouched and is still the larger half.

**Chronology, because it changes what this entry is.** `af0150f` was committed
on the evening of 2026-09-16 — the day of this review's own baseline — and
implements `plan-reset-and-discard.md`, written before the review existed. It
is not an answer to B3 and its author had not read it. The overlap is real and
coincidental, and the parts of B3 that a feature plan had no reason to think
about are exactly the parts still open.

**What changed.**

| Where | Change |
|---|---|
| `ra2/services/lifecycle_service.py:197` | `discard_delivery` — the delete B3 said did not exist. Removes the `delivery` and `delivery_file` rows and, **for an upload**, the bytes, through the same `FileStore` seam intake used. Asserted in `tests/backend/services/lifecycle/test_discard_delivery.py:79`, which counts both |
| `ra2/services/lifecycle_service.py:154`, `:173` | `discard_run` and `discard_evaluation`. **This is the larger correction to B3's evidence**, and it runs the other way: at `616bf2b` the gap was not only the delivery. `run` and `evaluation` had no delete at all, and `corpus_service.delete` refuses a corpus any evaluation cites — so a corpus that had been evaluated once could not be removed by **any** route the app offered, and neither could the delivery under it. The finding said *no delete for a delivery*; the truth was that the whole chain below the delivery was immovable |
| the same commit | The chain now completes, in exactly one order: **discard the runs or the evaluation → delete the corpus** (its existing 409-when-cited guard) **→ discard the delivery** (`DeliveryCitedError`, because `corpus.delivery_id` is `SET NULL` and the database would otherwise null a provenance link rather than refuse) |
| `scripts/reset_data.py:59` | `just reset yes` — the whole data directory: the database **and its `-wal` and `-shm` sidecars**, `deliveries/`, `codelists/`, `exports/`, then `alembic upgrade head`. Naming the sidecars rather than globbing is what makes it a wipe instead of a wipe that comes back with rows in it, and it is the closest thing the project now has to an end-of-PoC destruction command |
| `sw-design.md` §18, `SD23` | The design is written down: whole objects only, two guards, and **no discard state is ever persisted** — no `deleted_at`, no tombstone, no export flag (§18.3). Deliberate, and it is why the slice needed no migration |

**What it does not close.**

**1 · Nothing reclaims or zeroes the freed pages — now verified, on synthetic
data.** B3 inferred this from SQLite's behaviour; it reproduces exactly. A
`DELETE` of 500 rows carrying a synthetic evidence span, followed by a WAL
checkpoint, leaves **572 readable occurrences** of that span in the file. This
is not a footnote any more: before `af0150f` the app could not delete a scored
run at all, so there was nothing to leave behind. The verb that closes a third
of B3 is the verb that creates this residue, and `mismatch.evidence_span` —
verbatim narrative — is among the rows it frees.

| Path | Occurrences of the deleted text still in the file |
|---|---|
| `DELETE` + checkpoint, `secure_delete` at its default | **572** |
| `DELETE` + `VACUUM` + checkpoint | 0, and the file shrinks |
| `DELETE` + checkpoint, `secure_delete=ON` at connect | 0, no `VACUUM` needed |

`PRAGMA secure_delete` reads back **`0`** on the SQLite this project's
interpreter bundles (3.50.4). It is a compile-time default, so it is not a
thing to assume in either direction — which is the argument for setting it
explicitly rather than for trusting it.

**Two details worth having before choosing.** In WAL mode a `VACUUM` alone
changes nothing observable: the rebuild lands in `-wal` and the main file is
untouched until a checkpoint, so *run `VACUUM` after a discard* is half an
instruction. And both routes are about the **database file**; the bytes the
filesystem already holds are B4's problem, and full-disk encryption is the only
control that reaches them.

**2 · A host-path delivery's files are never removed, by design.**
`discard_delivery` removes bytes only for `SourceKind.UPLOAD`
(`lifecycle_service.py:230`); `HostPathFileStore` registers the analyst's own
files in place and refuses to remove them, and the service relies on that
rather than working around it. That is the right call for a store seam and the
wrong shape for a destruction claim: if the real delivery is registered from a
host path — which A4 shows is unconstrained — then *deleting the delivery*
removes rows only, and the raw `Unfall.csv` sits where it always was, outside
`RA2_DATA_DIR` and outside `just reset`'s reach. The empty
`{data_dir}/deliveries/{id}/` directory is likewise left behind, documented at
`lifecycle_service.py:350`.

**3 · The one destructive verb hands out a copy on the way past.** `R-D2`
chose an exported file over an audit row, so the confirm dialog offers
**Export** beside **Discard**, and `run_mismatches_csv`
(`ra2/services/export_service.py:394`) writes `record_value`,
`extracted_value` and **`evidence_span`** — verbatim narrative fragments — per
row. The trade is defensible and the reasoning is sound. Its consequence for
this finding is not: **the deletion path manufactures precisely the artefact
B2 says nothing governs**, at the one moment the analyst has been told the data
is about to be gone. The file leaves with §8.4's `CLASSIFICATION_COMMENT` on
its first line, which is a label, not a rule. And since §18.3 keeps no export
bookkeeping — correctly, by the same posture that keeps no logs — **how many
copies exist and where they went is unknowable by construction**.

**4 · `settings.exports_dir` is written by nothing.** It is declared at
`ra2/infra/config.py:105` ("Where CSV exports are written"), and the only
readers in the repository are `reset_data.py` and its test. Exports stream to
the browser and land in Downloads. So `just reset` clears a directory the app
never fills, while the copies that actually matter are somewhere no RA2 verb
reaches. This is `Settings.host` from A4, the same shape: a setting that
implies a control nobody implemented. Here it is worth *building* rather than
deleting — a single directory the app writes to gives the runbook's screening
sentence (B1) somewhere to point, and gives `just reset` something true to do.

**5 · The delete with no way to reach it.** §18.6 records that delivery
discard ships as a route with no UI affordance, the reasoning being that the
Import view has no delivery list and a table would be a design amendment. That
is a sound answer to *where does the button go*. It leaves the analyst's only
route to removing a delivery as `just reset` — which removes **everything**,
including the corpus, the codelists and every run — or an HTTP call by hand. A
destruction step that needs a shell is E3's problem arriving early.

**6 · The half that no commit can close.** No retention period. No destruction
date. Nobody named to sign that it happened. `grep` over every document in the
repository finds the words nowhere. `af0150f` gave the project a verb; what is
missing is the sentence that says when to use it, and that is still
recommendation 11's governance page and F1's argument, unchanged.

**How it was re-checked.**

| Check | Result |
|---|---|
| The free-page reproduction above, on a temp database with synthetic rows — 500 inserts of one marker string, `DELETE`, `wal_checkpoint(TRUNCATE)`, then a byte search of the file and its `-wal` | 572 occurrences remain. `VACUUM`+checkpoint clears them; `secure_delete=ON` prevents them. No project data was touched (Do-NOT #13) |
| `PRAGMA secure_delete` on this interpreter's SQLite | `0`, version 3.50.4 |
| `grep -rn -i vacuum` over `ra2/`, `scripts/`, `justfile` and the docs | No occurrence outside `plan-reset-and-discard.md` §2.2 and `sw-design.md` §18.6, both deferring *snapshot/restore*, neither about erasure |
| `grep -rn -iE` for retention, destruction and destroy over every `.md` | Nothing about data retention anywhere; every hit is about destroying `analyst_tag` or a Vue component |
| Readers of `settings.exports_dir` and `settings.deliveries_dir` across the repository | `exports_dir`: `reset_data.py` and its test only. `deliveries_dir`: `main.py` wiring into `UploadFileStore`, as expected |
| `ra2/services/corpus_service.delete` | Unchanged — still removes rows only, still refused while an evaluation cites the corpus. What changed is that the evaluation can now be discarded first |
| `tests/backend/services/lifecycle/test_discard_delivery.py:139` | `test_a_host_path_delivery_keeps_the_analysts_own_files` — the behaviour of §2 above is asserted, deliberate and tested, not an oversight |

**Propositions**, cheapest first. The first is a one-line change in an existing
pattern; the last is the one that matters most.

**P1 · `PRAGMA secure_delete=ON` beside the other three connect-time pragmas**
(`ra2/persistence/session.py:57`), which already says the pragmas live there
and **nowhere else**. It zeroes pages as they are freed, needs no `VACUUM`, no
checkpoint dance and no decision about when to run it, and it costs write
throughput on a workload that is one row per record per run. Prefer it to
`VACUUM`-after-discard: a `VACUUM` is a second thing to remember, must be
followed by a checkpoint to mean anything in WAL, and cannot run inside the
transaction a discard already holds. Test it the way `foreign_keys=ON` is
tested — the real-file fixture, reading the pragma back — plus the byte search
above over a discarded run. *(Recommendation 14, reworded.)*

**P2 · Say in one place what "the data is deleted" covers.** The chain has an
order and each step refuses out of order, so today the order is discoverable
only by trying. A numbered procedure — discard evaluations, delete the corpus,
discard the delivery, `just reset yes`, then the host-path source files, then
the exports in Downloads, then the disk — belongs in the runbook, and should be
rehearsed once on synthetic data before handover, as an acceptance step beside
the three at M34. *(New recommendation 20.)*

**P3 · Make `exports_dir` true, or delete it.** Writing every export there and
serving the download from the file gives one screenable location, makes
`just reset` cover the copies, and gives B1's screening sentence an address.
The alternative — deleting the setting — is honest but throws away the only
cheap place to put a retention rule later. *(New recommendation 19.)*

**P4 · One sentence in the discard dialog, beside Export.** *This file leaves
RA2's control — it carries verbatim narrative and is not covered by anything
the app deletes.* One string, the pattern D6 already asks for on Results, at
the only moment in the product where a person is deliberately creating a copy
of sensitive data outside the machine's rules.

**P5 · Decide whether real deliveries may be registered from a host path at
all.** If intake for real data is upload-only, then discard removes the bytes,
`just reset` removes the tree, and a destruction claim is complete without
qualification. If host-path intake stays — and A4 wants it constrained to an
`RA2_IMPORT_ROOT` under `{data_dir}` anyway — then that root is inside the data
directory and `just reset` reaches it. **Either way A4's fix closes this one
too**, which is worth knowing before either is scheduled.

**P6 · The governance page still decides this finding.** A retention period, a
destruction date, and a named person who signs that destruction happened.
Everything above is plumbing for a decision nobody has taken. `af0150f` moved
B3 from *there is no way to delete this* to *there is a way, and no rule saying
when* — which is progress, and is the smaller half.

### 8.6 B3 — erasure, and the page that decides the rest · closed 2026-09-18 · `fix-b3-deletion-path` · retention open

**Status: in place for the erasure and the procedure, open for every decision
that needs a person.** §8.5 left six propositions. Five are done; the sixth was
never a diff.

**What changed.**

| Where | Change |
|---|---|
| `ra2/persistence/session.py` | **P1 — a fourth connect-time PRAGMA, `secure_delete=ON`.** One line, in the file §4.4 already says owns the pragmas and *nowhere else*. SQLite frees a deleted row's page with its bytes intact, so a discarded run's `mismatch.evidence_span` — verbatim narrative — stayed readable in the database file until an unrelated write reused that page. It is now zeroed as it is freed |
| `ra2/infra/config.py`, `scripts/reset_data.py` | **P3 — `Settings.exports_dir` is deleted**, along with the `exports/` reset target. See *the proposition that changed* below |
| `ra2/ui/components/discard_dialog.py` | **P4 — `EXPORT_LEAVES_RA2`**, beside the Export button: *the file carries verbatim narrative and leaves RA2's control — nothing the app deletes can reach it again.* The one place the product says *this cannot be undone* is the one place it offers to make a copy that nothing here can delete, and now it says both |
| `data-handling.md` *(new)* | **P2, P5 and P6.** Outputs (§3), the numbered destruction procedure (§4.1), what the software does and does not guarantee (§4.2), the rehearsal before handover (§4.3), backup (§4.4), the incident path (§5), the decommission condition (§6) — and §7, ten decisions with owner and date columns left **blank**. Recommendations 11, 14 and 20 |
| `sw-design.md` | `SD29`, `SD30`, §4.4, §10, and **§18.7 — *What a discard erases***. §18.1 said *whole objects*; nothing said what *removed* meant, and the difference is the whole of this finding |
| `README.md` | Two false claims removed: exports do **not** live under the data directory |

**The proposition that changed on contact with the code.** §8.5's P3 said to
*build* `exports_dir` rather than delete it. Reading the export path changed
the answer, and the reason is worth keeping: a server-side copy **does not
replace the downloaded one — it adds a second copy at rest**, unpruned, of the
artefact B2 says nothing governs. For a finding about data outliving its
purpose that is the wrong direction, and the five UI call sites and five API
routes it would have cost buy nothing B3 wanted. The setting is gone, the two
documents that repeated its claim are corrected, and where the copies actually
are is now a sentence in `data-handling.md` §3 instead of a directory that was
always empty. `SD30`.

**How it was verified.**

| Check | Result |
|---|---|
| `PRAGMA secure_delete` read back off the real engine (`test_secure_delete_pragma_is_on`) | `1` |
| The property, through the real service against the real temp-file database (`test_discard_erasure.py`): plant a synthetic span on a `mismatch`, discard the run, close every connection so the WAL is checkpointed and removed, then search the file | **0 occurrences.** A positive control asserts the same search finds the span *before* the discard, so the assertion cannot pass vacuously |
| The control, `secure_delete` at SQLite's own default (`test_the_search_can_tell_the_difference`) | The bytes survive the `DELETE`. This is both the defect and the proof that the gate is not tautological |
| The new tests against the **unfixed** module — the pragma line removed | **2 fail.** The gate is real |
| `test_a_reset_has_no_exports_target` | Both halves asserted: `Settings` has no `exports_dir`, and no reset target is named `exports`. Either one returning alone re-creates the same false reassurance |
| `test_the_export_offer_says_the_file_leaves_ra2`, and the absence asserted in the nothing-to-export state | The sentence is load-bearing copy, tested like `DISCARD_KEEPS` |
| `ruff format --check`, `ruff check`, `mypy`, `lint-imports` | Green |
| `pytest`, by layer | **2 340 passed, 9 skipped, nothing failed** — `tests/unit` + `tests/api` + the five contract modules 1 169, `tests/backend` 868, `tests/ui` 303. (`tests/e2e` needs a browser and is a separate gate; the discard journey's new assertion is not run here) |
| The six failures this work first ran into | **None of them were this change** — each was reproduced at `HEAD` with the work stashed, and all were Windows artefacts of the repository itself: four CRLF fixture comparisons and two path-separator assertions in `test_p3_contract.py`, both fixed under `contracts/amendments/fix-windows-paths-and-eol.md` |
| `tests/ui`, and whose fix it is | Most of the layer was failing because the data-dir chip pastes `RA2_DATA_DIR` into a NiceGUI prop string parsed with `ast.literal_eval`. That was already diagnosed and fixed **first**, independently, on branch `fix-ui-windows-data-dir` (`8665563`, `SD31`); this work reached the same fix, found theirs, and dropped its own rather than commit a second copy. **The 303 figure above was measured with that branch's fix applied** — on `main` alone, `tests/ui` stays red until it lands |

**What this does not close.**

**1 · Every decision in `data-handling.md` §7.** Ten of them, blank: the named
owner and legal basis, the machine and its custody, what may leave and to whom,
**the retention period**, **the destruction date and who signs it**, host-path
intake, backup, the incident contact and its time bound, NDA cover for the
reviewing expert, and the decommission condition. The page is a form; nobody
has filled it in. That is why B3 keeps a `◑` and not a `✓`, and why
recommendation 11 is not closed by a file existing.

**2 · The manual steps stay manual.** Destruction is complete at step 4 only if
no delivery was registered from a host path. Step 5 — deleting the analyst's
own source files — and step 6 — deleting the exports in Downloads — are
procedure, not code, and A4's `RA2_IMPORT_ROOT` is what would fold step 5 into
`just reset` (P5, `data-handling.md` §4.2).

**3 · Two of the three discard routes have no button.** §18.6 records this for
the delivery. Writing the procedure down surfaced that it is also true of the
**evaluation**: the row action in the Evaluation view discards *one run*
(`run-discard`), and an analyst clearing three inconclusive evaluations
discards each of their runs one at a time or calls the API. That is consistent
with `R-D5` — one object at a time, no bulk verb over a destructive
operation — and it is not what §18.6's text implies. Recorded in
`data-handling.md` §4.1 rather than fixed: adding the affordance is a design
change, and the destruction procedure needs to describe what exists.

**4 · The filesystem, and every earlier copy.** `secure_delete` reaches the
database file. It does not reach the blocks the filesystem freed, a backup, or
a disk image. **B4 carries this**, and `data-handling.md` §2 states full-disk
encryption as the deployment condition that makes every deletion above mean
something — still unconfirmed, still not the reviewer's to observe.

---

## 9. Second pass — the handover recalibration · 2026-09-23 · `12268ed`

Sixty-two commits, 187 files and roughly 37 000 lines after the first pass.
Phases 4 and 5 shipped; `just lint` and `just test` are green (2 521 passed,
1 skipped, 96.1 % coverage, 31 s).

**The code moved a long way. The decisions did not move at all.** All ten rows
of `data-handling.md` §7 are blank, and `mvp-spec.md` §18's B1–B4 are all still
open. At the first pass that was a governance finding. It is now a scheduling
one, because of what §9.1 describes.

### 9.1 Why the second pass re-grades rather than re-reviews

The first pass graded every severity "in this context — a one-month PoC, one
machine, one small group of analysts, real data". That context was
**construction**. The project is now crossing into **operation**: development is
winding down, analysts begin using the PoC, and the developer stays reachable
rather than resident.

The register has no entry for the crossing itself, and the crossing does not
move every finding the same way.

| | What the phase does to it |
|---|---|
| **Group C falls** — development, tooling, supply chain | Fewer commits, fewer branches, fewer agents. The exposure window closes on its own. **C2 is the exception and does not fall** — see §9.3. |
| **A2, A3, B3, B4, Group E, Group F rise** | Every one of them was deferred *because* it was an operations concern. Operations starts now. |
| **Group D's deadline arrives** | "Before the evaluation corpus is cut" was a future tense in September. It is now. |
| **Group G spikes** — data input | **Real delivery files meet the parser for the first time at handover.** B4 has never landed. G1 and G2 are exactly what first contact surfaces. |

The three acceptance checks the first pass parked "at M34" — an independent
recomputation of one run's statistics, a truncation check against the real
server, a provenance check of one run against the machine it claims to have run
on — **are the go-live gate**, and nobody has scheduled M34. §5 now carries
them as Gate 3.

### 9.1.1 The support path is the new egress path

This is the finding the second pass would lead with, and none of its parts are
new. The chain is.

While the system was being built, nobody operated it, so nothing broke in front
of a user. From now on it will, and when it does:

1. There is **no runbook** — E3, "deferred by design" (`mvp-spec.md` §16). The
   design is over.
2. The **README tells the incoming operator that the three screens the PoC
   exists to produce do not exist** — F6, verbatim, still in the file.
3. There is **no audit trail anywhere**, by deliberate and well-reasoned choice
   (F1; `data-handling.md` §5).
4. So the only diagnostic material is a log line, a screenshot or a traceback,
   and the natural act — with the developer *reachable rather than resident* —
   is to send it to them.
5. ~~**A5 means that log line can carry a narrative and an `unfall_uid`
   verbatim**, precisely when something has gone wrong.~~ **Broken, 2026-09-24**
   (`fix-a5-bound-parameters`): the engine hides bound parameters, so a driver
   error no longer publishes the row it failed on. **The chain is weakened,
   not cut.** Links 1, 2, 3 and 6 stand, and the diagnostic material a person
   sends is not only the log — a screenshot of the record view, a description
   typed out by hand, and the mismatch export (B2, `EXPORT_LEAVES_RA2`) all
   still carry content, and none of them is a control anybody can fix. Item 31
   is what closes this, and it is not code.
6. The destination is a **public repository** (now a settled decision, §9.4) or
   an **agent transcript**, which leaves the host by construction (Do-NOT #13).

Each link was assessed individually and accepted individually. The chain was
not, because it could not close while the thing was still being built. It
closes at handover.

**The developer being reachable rather than resident is what arms it.** A
resident developer debugs on the machine; a reachable one debugs from a
description, and a description of a data bug is made of data. Every
recommendation that breaks this chain is in Gate 1 or Gate 4 of §5.

---

### 9.2 Findings added by the second pass

Written in §4's form. Severities are second-pass severities, already graded for
the operational phase.

---

**A5 · A database error writes the narrative and the record key into
`run.error`, and from there into the log** · Severity: **High** · Control
status: ~~**absent**~~ → **present** · **Verified**, then **closed 2026-09-24**
(`contracts/amendments/fix-a5-bound-parameters.md`, `SD39`)

*Scenario.* Any exception raised beneath a run — a constraint violation, a
validation error, a driver fault — is stringified into `run.error`, which is
persisted, rendered in the runs table's log action, **and written to stderr**.
SQLAlchemy includes the bound parameters of the failing statement in that
string by default. For an insert over `record`, the bound parameters are the
narrative and `unfall_uid`.

*Evidence.* `create_engine` (`ra2/persistence/session.py:97`) calls
`create_async_engine(database_url, echo=echo, future=True)` — **without
`hide_parameters=True`**. `_error_text` (`ra2/services/run_service.py:1079`) is
`f"{type(exc).__name__}: {exc}"` for every exception that is not a
`FeatureValidationError`, and `run_service.py:808` logs it. Reproduced through
the project's own engine on synthetic rows:

```
IntegrityError: (sqlite3.IntegrityError) UNIQUE constraint failed: r.uid
[SQL: INSERT INTO r VALUES (?,?)]
[parameters: ('SYNTHETICUID0000000000000000abcd', 'SYNTHETIC-NARRATIVE Lenker A
 kollidierte mit Fussgaenger B am Fussgaengerstreifen.')]

narrative present : True
unfall_uid present: True
```

Both are on `data-handling.md` §5.1's **"may never appear"** list, by name.

*Why the existing control does not catch it.*
`test_run_log_carries_no_data.py` drives a **successful** run against a fixture
whose narrative and keys it knows. It never provokes a database error, so the
one channel that can carry content is the one channel the test cannot reach.
This is A1's shape exactly: the guard is correct and complete for what it
inspects, and the defect lives one layer below it.

*Impact.* `ra2/infra/logging.py`'s stated rationale is that the log is *safe
for an agent to paste into a bug report*. This path makes it unsafe at exactly
the moment an agent is asked to look, and it is link 5 of §9.1.1's chain.

*Recommendation.*
1. `hide_parameters=True` on `create_async_engine`. One line.
2. A test that provokes a real `IntegrityError` through the real engine and
   asserts the narrative and the key are absent from `str(exc)` — **with a
   positive control** proving the search can fail, in the idiom §8.1 and §8.6
   already established. A negative assertion that cannot fail is worse than
   none.
3. Say in `data-handling.md` §5.1 that the "may never appear" list is enforced
   by the engine's configuration as well as by the call sites, because a call
   site is not where this one came from.

*Resolution, 2026-09-24.* All three, in one commit. `create_engine` passes
`hide_parameters=True` (`session.py`, one keyword argument);
`tests/backend/persistence/test_engine_hides_parameters.py` provokes a real
`IntegrityError` over the real migrated `record` table and asserts the planted
narrative and key are absent from exactly `_error_text`'s expression, **with a
sibling that runs the same insert through a default-built engine and fails if
the narrative is not there**; and `data-handling.md` §5.1 now states the rule
in two halves — what a line is given, at the call sites, and what an exception
is allowed to say, at the engine.

Two things the fix turned up that the finding had not.

**The channel was wider than `record`.** The reproduction used an insert over
`record`, so it named `text_raw` and `unfall_uid`. Re-provoked through the real
service, the statement that actually fails first in a run is the insert over
**`extraction`**, and its bound parameters include `raw_output_text` — the
model's entire answer, which is on the same "may never appear" list. Logged at
`WARNING`, on a failed run, which is the only kind anybody reads.

**The false premise was written down.** The comment above the log call in
`run_service.py` read *"…and never the model's words, so it is safe to repeat
here"* — correct for every error that module **writes**, wrong for the ones it
**catches**. It has been corrected rather than deleted; an assumption stated
out loud is why this was findable at all.

`test_run_log_carries_no_data.py` gained the case it structurally could not
have: a `RAISE(ABORT)` trigger on `extraction` provokes a real driver error
inside a real run, and both the persisted `run.error` and the log are asserted
clean. Removing the keyword argument fails three tests across the two files.

---

**B6 · The mismatch note is an unconstrained free-text channel that exports
verbatim** · Severity: **Low–Medium** · Control status: **absent**

*Scenario.* Review writes three columns — `analyst_tag`, `tagged_at` and
`note`. The `note` is unconstrained free text and is exported verbatim in both
mismatch CSVs (`ra2/services/export_service.py:96`, `:115`). An analyst writing
*"the text says the driver braked, so the code is wrong"* is doing the job as
designed, and has just copied narrative into an export whose classification
line is a label rather than a rule (B2).

`data-handling.md` §3 lists the column. It does not name it as a hazard.

*Secondary, and worth stating as accepted rather than leaving implicit.*
`tagged_at` exists; **`tagged_by` does not**, and the tag is the single mutable
row in the schema with no history. A retag leaves no trace and the Goal 3 tally
is not reconstructible from the machine. That is correct for one analyst on one
machine and wrong the moment F3 happens — which is the argument for recording
it as an accepted decision rather than as an absence nobody noticed.

*Recommendation.* One line of helper copy under the note field, in the voice
`EXPORT_LEAVES_RA2` already uses. Record the `tagged_by` decision as accepted
in `data-handling.md`, so F3 re-opens it deliberately rather than by drift.

---

**C4 · The agent deny rules are relative paths, and agents work in worktrees**
· Severity: **Medium** · Control status: **partial**

*Scenario.* `.claude/settings.json` denies `Read(./data/**)`,
`Read(./var/**)` and `Bash(sqlite3 *)`. Three gaps, in rising order of how
likely each is to matter:

1. The paths are **relative**. Both the justfile and `.gitignore` document
   agents working in `.claude/worktrees/agent-*` — full copies of this project.
   A deny evaluated from a worktree root does not cover
   `<repo>/var/ra2.sqlite` reached by absolute path.
2. `Bash(sqlite3 *)` is denied; `uv run python -c "import sqlite3 …"` is not,
   and neither are `cat`, `head`, `strings` or `grep` against a path the deny
   list has not been told about.
3. `RA2_DATA_DIR` can point anywhere — which `CLAUDE.md` concedes in writing:
   *"no glob covers a path it has not been told about."*

*Recommendation.* Absolute paths in the deny list, plus patterns for the
database file by name and for the interpreter-shaped bypasses. But the
recommendation that makes all of it unnecessary is **C2's second one, still
open — keep real data off the development checkout entirely** — and see §9.3
for why it is now much cheaper than it was at `616bf2b`.

---

**D8 · Nothing distinguishes a synthetic corpus from a real one** · Severity:
**High during the transition** · Control status: **absent**

*Scenario.* `corpus.is_dev_sized` is
`record_count < settings.dev_record_max` (`ra2/services/corpus_service.py:189`)
— a **size** threshold, not a provenance marker. `just reset-seed yes --records
3000` produces a corpus above the floor, unmarked, whose Results screen is
indistinguishable from a real evaluation's.

*Why now and not before.* During the transition — and only during the
transition — a seeded corpus and the first real corpus exist on the same
machine at the same time. And the seed is *deliberately convincing*:
`scripts/seed_dev.py` documents having been rebuilt specifically so a run over
it would not produce a hollow Results screen, with realistic proportions of
`HIT`, `WRONG` and `MISSING`. That quality is the risk.

*Impact.* A screenshot or an exported ranking taken from seed data and carried
into a report. The PoC's deliverable is a number, and D5 already establishes
that a wrong one is invisible; this is a second way to produce one.

*Recommendation.* A `corpus.is_synthetic` flag, set on the seed path, rendered
as a chip beside the dev-sized one and refused by the ranking — the same
pattern the project already accepted for dev-sized results, and asserted the
same way. **It needs a migration, so its deadline is earlier than the code
freeze: before real data is in the database.** A migration against a database
holding real records is a different act from a migration against an empty one.
The migration-author rule applies (`CLAUDE.md`).

---

**E4 · The rehearsal tool and the destruction tool are the same command, and
after handover it points at real data** · Severity: **High** · Control status:
**partial**

*Scenario.* `data-handling.md` §4.3 instructs the operator to rehearse
destruction using `just reset-seed`. `just reset-seed yes` runs
`reset_data.py`, which wipes `RA2_DATA_DIR`, and then **seeds a convincing
synthetic corpus in its place**.

On a development machine that is a convenience. On the operational machine it
destroys the real corpus, the census, the codelists and every completed run —
GPU-weeks that the budget does not have — and replaces them with data that
looks plausible on every screen (D8).

*Existing controls, and why they are thin here.* There is a `yes` token, and
the script prints its plan before acting — both deliberate, and
`reset_data.py`'s own docstring gives the right reason: *"a destructive default
is how the wrong database gets deleted at the end of a long day."* But the plan
reports **bytes, not records**. The operator sees `ra2.sqlite 281.0 MB`, which
is a hint, not a statement, and nothing in the output distinguishes the machine
holding the real corpus from the one holding a seed.

*Impact.* Compounded by two things already in the register: E1 — there is no
backup and no decision about whether there should be — and E2, which is what
makes the loss GPU-weeks rather than minutes.

*Recommendation.*
- Count the corpora and records the plan is about to destroy, and **print
  them**. The plan should say what is being lost, not how many bytes it
  occupies.
- **Refuse outright** when the database holds a corpus that is not dev-sized,
  unless a second, different token is supplied. This extends the script's own
  stated principle one step, to match who is now holding it.
- Consider whether `reset-seed` should exist on the operational machine at all.

---

**F6 · The README is the handover document, and it is materially false** ·
Severity: **High** · Control status: **absent** · **Verified**

*Scenario.* Not drift in the abstract. Verbatim in `README.md` today, under
*Not built yet*:

> **Scoring, Results and Mismatches.** Runs produce extraction rows and stop
> there — nothing scores them yet. Those nav entries route to a placeholder.

All three shipped. Scoring is chained to run completion
(`tests/backend/services/run/test_scoring_is_chained.py`), Results is V1–V3,
Mismatches is M35–M40. The *At a glance* section repeats the claim.

The same section's *"Docker packaging and an installer. Planned; no Dockerfile
exists today"* is **still true**, which is E3 arriving on schedule with the
resident developer leaving.

*Impact.* The incoming operator's first document tells them the deliverable
does not exist, and is silent about the two things they will actually need. It
is link 2 of §9.1.1's chain: a reader who cannot trust the README has no route
to self-service and goes to the developer instead.

*Why it keeps happening.* §8.6 already had to remove two false README claims
about exports. This is the third and fourth. The diagnosis is this project's
own principle turned on itself: `FindingCode` values, load-bearing UI copy,
line endings, import layers and frozen contracts all have a test, a linter or a
gate. **The README has a habit.** It is the only document here with nothing
behind it, and it is the one a stranger reads first.

*Recommendation.* Correct it, and gate it: a test asserting that no nav item
`ra2/ui/shell.py:NAV_ITEMS` routes to a real view appears in the README's *Not
built yet* section. One test, in the idiom the project already uses for
load-bearing copy, and it retires the habit rather than the instance.

---

### Group G — Data input integrity

*New in the second pass.* The first pass had no input-integrity group; intake
concerns sat scattered under A4 and D4. The group exists now because **B4 —
real delivery files — has never landed, and the first real import happens at
handover.** Everything here is upstream of every number the PoC produces.

---

**G1 · A mixed-encoding file is silently mojibaked** · Severity: **High** ·
Control status: **absent** · **Verified**

*Scenario.* `detect_encoding` decides for the **whole file**: UTF-8 strictly,
else cp1252, else fail. One cp1252 byte anywhere in a 200 000-row file flips
the entire file to cp1252 — and every correctly-encoded UTF-8 row *before* it
becomes mojibake, with no finding raised.

*Evidence.* Synthetic bytes, through the project's own `detect_encoding`:

```
utf8 + cp1252 mix  ->  cp1252   text='Text\nGrüezi\nFussgänger\n'
                                           ^^^^^^^  was "Grüezi"
```

*Why the existing reasoning does not cover it.* `encoding.py`'s docstring
argues there is deliberately no third fallback because `latin-1` *"would decode
every byte string ever written and turn a detection failure into silent
mojibake"*. The argument is sound and the conclusion is right — but **cp1252
decodes 251 of 256 byte values**, so it is 98 % of the way to being latin-1.
The reasoning proves slightly less than it is asked to carry.

*Impact.* The D-group failure mode arriving at the head of the pipeline. The
model reads corrupted German, scores `wrong` or `missing`, and the result is
indistinguishable from a model that reads badly — in the ranking, which is the
deliverable. The analyst sees `ENCODING_DETECTED: cp1252`, severity
**REPORTED** rather than blocking, and has no reason to suspect anything.

*Recommendation.* **The project already owns the right pattern, pointing the
other way.** `CP1252_CANARY_ZERO` counts Windows-1252-only characters to prove
a lossy conversion happened *upstream*. Nothing counts the mirror signature —
`Ã`, `Â`, `â€`, `Ã¼` — which is what UTF-8-read-as-cp1252 looks like *at
intake*. Add that canary: one new `FindingCode`, one corpus-level count, no
schema change, symmetric with the one that exists and defensible for the same
reason.

---

**G2 · A UTF-16 file decodes "successfully" and lands as NUL-riddled text** ·
Severity: **High** · Control status: **absent** · **Verified**

*Scenario.* Only the UTF-8 BOM is recognised and stripped. A UTF-16 file — an
Excel "Unicode Text" re-export is the obvious way one arrives — decodes
cleanly, because UTF-8 accepts `U+0000` and cp1252 accepts almost everything.

*Evidence.*

```
utf16le with BOM   ->  cp1252   text='ÿþU\x00n\x00f\x00a\x00l\x00l\x00-\x00U\x00I\x00D…'
utf16le no BOM     ->  utf-8    text='U\x00n\x00f\x00a\x00l\x00l\x00-\x00U\x00I\x00D…'
```

*Impact, and the saving grace.* The file then fails downstream at header
classification, so this is **loud** rather than silent — which is why it is
graded below G1 on impact and level with it on urgency. But the finding names
the wrong cause: the analyst is told `UNKNOWN_HEADER` and sent to fix a header
that is fine. At handover, with a first real delivery and no runbook, a
misdiagnosed import is exactly the event that routes someone to the developer
(§9.1.1).

*Recommendation.* Three lines, both in the *refuse to guess* posture the parser
already applies everywhere else: refuse a UTF-16/32 BOM by name, and refuse
decoded text containing `\x00`, each with its own `FindingCode` so the finding
names the real cause.

---

**G3 · Host-path intake is unconstrained, unbounded, and now load-bearing for
the destruction claim** · Severity: **Medium** · Control status: **partial**

*This is A4's intake half, re-stated because its cost has risen rather than
because the code changed.* Re-verified at `12268ed`: `Settings.host` and
`Settings.port` still have **no reader anywhere in `ra2/`**;
`HostPathFileStore.list_files` still does `rglob("*")` with `_stat_file`
reading every file fully into memory to hash it; `root_path` is still
unconstrained.

*What changed.* `data-handling.md` §4.2 has promoted this unfixed code finding
into a **permanent manual step 5 of the destruction procedure**, and a
`DECISION REQUIRED (P5)`. An open code finding has become a standing operational
burden on the person least able to carry it.

*Recommendation.* **The cheapest resolution is not code.** Decide that real
deliveries are **upload-only**. That deletes destruction step 5, makes
`just reset yes` a complete destruction of everything RA2 has ever held, and
costs one validation. `RA2_IMPORT_ROOT` is the fallback if host-path intake
must stay. Separately, bound the walk — file count and total bytes, with a
`Finding` rather than an exception.

*A pattern worth naming once.* `Settings.host`, `Settings.port`, the deleted
`Settings.exports_dir` (§8.6) and `scripts/dev_agent.py`'s `RA2_PORT` — set in
the environment, read by nothing — are four instances of **a setting that
implies a control nobody implemented**. §8.6 called this shape out for
`exports_dir`; it is a category, not an instance. One contract test would close
it: every `Settings` field has a reader in `ra2/`, or it does not exist.

---

**G4 · The hazard corpus is missing the hazard `CLAUDE.md` requires by name** ·
Severity: **Medium** · Control status: **absent** · **Verified**

*Evidence.* `CLAUDE.md` → *Working agreements*: *"Fixtures must contain the
real hazards — **mixed encodings**, a stray `|`, an embedded newline, an orphan
key, a key duplicated across two cantonal sets, an all-empty column, French
already lossy."* The committed set is `h01`–`h14`. `h01_cp1252` is whole-file
cp1252; `h02_undecodable` fails the file. **There is no mixed-encoding
fixture.**

*Impact.* G1 is precisely the defect that fixture was specified to catch, and
the specification predates the code. This is the one finding in the report that
costs nothing to close and would have prevented another.

*Recommendation.* `h15_mixed_encoding`, generated byte-exactly by
`tests/fixtures/deliveries/generate_hazards.py` like the other fourteen.

---

### 9.3 Re-grades

The row in §4 is left as written. This table is the second pass's judgement at
`12268ed`, for the operational phase.

| Finding | First pass | Second pass | Why the phase moved it |
|---|---|---|---|
| **A2** tunnel behind `127.0.0.1` | Medium | **High** | B2 (VRAM) is still unconfirmed at the moment models are chosen. Weak hardware, a short month, and one line of `ssh -L`. |
| **A3** the Ollama process | Medium | **High** | Setup happens now. `OLLAMA_HOST`, `OLLAMA_DEBUG` and how weights arrive are go-live decisions, not future ones. |
| **A4** unauthenticated app, arbitrary host-path read | Medium | **Medium**, intake half re-stated as **G3** | Unchanged in code; re-verified. Its destruction consequence is what moved. |
| **B3** retention and destruction | High | **High, dated** | The rehearsal window (`data-handling.md` §4.3) is *before* real data lands. It is open now and closes at first import. |
| **B4** encryption and custody | Medium | **High** | The machine goes into use. "Unknown — not recorded" stops being tolerable when the recording is the control. |
| **C1** real-data commit guard | High | **Closed / accepted** | §9.4. |
| **C2** AI-assisted development on the corpus machine | Med–High | **Medium–High — unchanged, and its character changes** | The obvious read is that this falls with the build traffic. It does not. A *resident* developer debugs on the machine; a **reachable** one debugs from a description, and a description of a data bug is made of data. The residual moves from *an agent reading the corpus while building a feature* to *an agent reading it while diagnosing a live incident* — unplanned, urgent, and involving precisely the record that broke. Reactive debugging is when Do-NOT #13 gets broken, not scheduled work. |
| **C3** supply chain and offline install | Low–Med | **High if air-gapped** | If B3 answers "air-gapped", the wheel bundle and the side-loaded weights must be built **while the developer is still here**. There is no Dockerfile and no installer (F6). A schedule gate, not a security nicety. |
| **D1** context-window truncation | High | **High, dated** | "Before the corpus is cut" is now. Half of it arrived free — see §9.4. |
| **D2** parse-failure rate invisible on Results | Medium | **Medium** | Unchanged; re-verified absent from Results and Ranking. |
| **D3** reproducibility claimed too strongly | Medium | **Medium** | Unchanged; the model-server version is still not recorded. |
| **D6** Results readable before the review exists | Medium | **Closed by delivery** | §9.4. |
| **E1** one machine, one file, no backup | Medium | **High** | Runs become GPU-weeks of real work, and E4 adds a second way to lose them. |
| **E3** handover not built | Medium | **High** | No longer deferred. Due. It is what §9.1.1's chain hangs on. |
| **F1** accountability | High | **High, overdue** | Ten blank decisions. The status changes from pending to late. |
| **F2** deployment conditions unstated | Medium | **High** | The assumptions — single user, loopback bind, no remote-desktop sharing — become live operating conditions with nobody watching them. |
| **F3** scope drift | Medium | **High** | "A PoC that works gets used." This is the week it starts being used. |
| **F4** key-person concentration | Medium | **High, partly mitigated** | The developer staying reachable preserves the knowledge and is the right call. It does not *transfer* it, and reachability ends. The operations log recommendation moves from nice-to-have to the only transfer mechanism there is. |

### 9.4 What the second pass closes

**D6 — closed by delivery, not by remediation.** The finding was bounded:
*"until the review view ships"*. It shipped (M35–M40, `5a61ed3`). The window
closed itself. The underlying recommendation — standing copy on Results saying
*a mismatch rate is not a model error rate until someone has read the list* —
is still worth one string, and is carried in §5 Gate 1.

**C1 — the repository's visibility is now a settled decision, not an open
item.** The project has decided the repository stays public. The document
should stop carrying "reconsider public visibility" as a recommendation.

The guard that now permanently carries the whole weight is sound, and the
second pass checked it rather than assuming: `scripts/check_no_real_data.py` is
content-shaped, classifies through the importer's own `classify_header`, has a
headerless fallback keyed on a 32-hex key plus a delimiter, excludes invented
fixture keys via `_was_invented`, imports nothing outside the standard library,
and runs **first** in CI over **every tracked file** with `--all`. It is a good
permanent control.

Two residuals belong beside the acceptance, because *public, permanently*
changes what they mean:

- **A mistake is unrecoverable.** A force-push does not help. Content must be
  assumed mirrored the moment it is pushed.
- **The guard sees delivery-shaped files.** It does not see a narrative pasted
  into an issue, a commit message, a test failure, a screenshot or a Playwright
  trace. **§9.1.1 is the path it cannot cover**, and with the repository public
  that path now ends somewhere permanent.

**D1 — half of it arrived by another route, and the remaining half got
cheaper.** `Extraction.prompt_tokens` and `completion_tokens` are now recorded
**from the endpoint** on every extraction (`ra2/persistence/models.py:1128`),
which is recommendation 6's first half, reached by a different road. What is
still missing is only the comparison: no context size is configured, recorded
or checked; `OllamaModelCatalog` calls `/api/tags` only, never `/api/show`,
which is where Ollama exposes context length; and `estimate_tokens` still feeds
nothing but the prompt preview. **The cheapest useful check now needs no setup
at all** — flag any extraction whose returned `prompt_tokens` sits at or near
the model's limit, which is what truncation looks like from the client side,
using a number the database already holds.

**C2's second recommendation got much cheaper.** At `616bf2b` the reason
`var/ra2.sqlite` held 2 695 real records on the development machine was that
there was nothing else to develop against. **`just reset-seed` now produces a
genuinely usable corpus** — realistic scenarios, deliberate `HIT`/`WRONG`/
`MISSING` proportions, a runnable evaluation, documented in `docs/seed.md`. The
cost of *keep real data off the development checkout entirely* has fallen to
near zero, and the first pass could not have known that. It is the single
recommendation that closes C2 and C4 together, and it makes §9.1.1's link 6
much harder to reach.

### 9.5 Method and limits of the second pass

Same reviewer posture and the same limits as §2, which are unchanged. In
addition:

**What was executed.** Four checks were run rather than read, all on synthetic
bytes or synthetic rows. **No project data was opened, queried or printed**
(Do-NOT #13) — the engine probe used a throwaway temporary database built for
the purpose.

**What was not examined**, beyond §2's list: the E2E suite was not run; the
repository's visibility was not re-queried (the project states it and it is now
a decision rather than a finding); `data/` and `var/` were not touched.

**What is deliberately not re-derived.** §4's register was not re-audited
finding by finding. Where the second pass says *unchanged*, that means the code
paths named in the original finding were re-read or re-grepped at `12268ed` and
still behave as described — not that the whole scenario was re-reasoned.

# Rules — RA2

**The rules for using and developing RA2, in one place.**

RA2 processes **real, non-anonymised police accident records**: narratives and
a structured record that together identify people (birth date, postcode,
metre-precise coordinates, vehicle, insurer). Almost every rule below exists
because of that one fact.

This page gathers rules that are stated with their reasons in other documents.
**It is not the authority for any of them.** Each section names its source, and
where this page and its source disagree, the source wins and this page is
corrected.

| Source | Authority for |
|---|---|
| [`sw-design.md`](../sw-design.md) §12 | The Do-NOT list — invariants with a test, a lint rule or a CI gate behind each |
| [`data-handling.md`](../data-handling.md) | What may leave the machine, retention, destruction, incidents — and the decisions still open |
| [`CLAUDE.md`](../CLAUDE.md) | How agents and developers work in this repository |
| [`risk-assesment.md`](risk-assesment.md) | Why each control exists, and what is still open |

**Who reads which part.** Everyone: §1 and §2. Analysts using the app: §3.
Developers: §4. Anyone working with an AI agent: §5. Anyone reporting a
problem: §6.

---

## 1. The three rules everything else follows from

1. **Real data stays on the machine it was given to.** Not in the repository,
   not in a transcript, not in a bug report, not in a slide, not in a cloud
   folder. Every copy is a copy nobody can later destroy.
2. **Nothing leaves the host except to a loopback model server.** The app
   refuses any other LLM endpoint, and there is no setting to change that.
3. **Nothing is repaired or dropped silently.** Every problem with a row is a
   finding carrying its key; nothing is edited in place.

---

## 2. Machines: which one may hold what

> Source: `risk-assesment.md` §8.7, C2; `data-handling.md` §2;
> `sw-design.md` §12 (*On #13*).

**No sandbox on Windows — use Linux, macOS or WSL2. Therefore no real data on a
Windows machine where an AI agent runs.**

AI agents' transcripts leave the machine by design, so an agent that reads a
real record has exported it. On Linux, macOS and WSL2, Claude Code's sandbox
confines the agent's shell commands to what `.claude/settings.json` allows. **On
native Windows the sandbox does not run**: the settings are accepted and do
nothing, and an agent's `cat`, `find` or Python script can read every file the
user account can. That has happened (`risk-assesment.md` §8.7). On such a
machine the only control that works is that there is no real data to find.

| Machine | OS | May hold real data? | AI agents? |
|---|---|---|---|
| **The operational machine** — where analysts run RA2 on deliveries | Windows, Linux or macOS | **Yes** — it is the one named machine of `data-handling.md` §2, under the conditions there | **Never** |
| **A development machine, Linux / macOS / WSL2** | Linux, macOS, or Windows + WSL2 | **No, by default.** Synthetic data only. See the note below | Yes, inside the sandbox |
| **A development machine, native Windows** | Windows | **Never** — no delivery, no copy of one, no database built from one, nowhere on the disk | Yes, but only with synthetic data present |

**Synthetic data** means the committed fixtures and what `just reset-seed`
builds. Both contain the real hazards (encodings, stray delimiters, orphan
keys, lossy French) without containing a real record.

**WSL2 counts as Linux only if Windows is out of reach.** Keep the checkout on
the Linux filesystem, not under `/mnt/c`, and turn off the Windows drive mounts
in `/etc/wsl.conf`:

```ini
[automount]
enabled = false
```

Otherwise `/mnt/c` puts every Windows folder back in the agent's reach. And if
real data sits on the Windows side of a machine, agents on that machine run in
WSL2 only — never in a native-Windows session on the same box.

**If a development machine must hold real data** — to reproduce a parser
problem that no fixture captures yet — it must be Linux, macOS or WSL2 with the
sandbox on, the data must be outside the checkout and outside every path the
sandbox allows, and it leaves the machine again when the fixture exists. The
preferred route is always to synthesise the hazard into a fixture instead
(§4.4).

---

## 3. Using the tool

> Source: `data-handling.md`; `README.md` → *Running the application*,
> *The loopback rule*, *Configuration*.

### 3.1 Before real data arrives

- The machine is the **one named machine**, with **full-disk encryption on**
  (`data-handling.md` §2). Encryption is what makes every deletion mean
  anything.
- `RA2_DATA_DIR` is **not** under OneDrive, Dropbox or any synced or redirected
  folder. A synced data directory is a silent second copy of the whole corpus.
- The model server listens on loopback only (`OLLAMA_HOST=127.0.0.1`) and
  **`OLLAMA_DEBUG` is off** — it writes prompt content to its own log.
- **No AI agent runs on this machine** (§2).
- No tunnel, proxy, port forward or remote-desktop session between RA2, the
  model server and anyone else. A tunnel behind `127.0.0.1` is a data breach
  whatever the URL says.

### 3.2 While using it

- **The LLM endpoint must be loopback** (`127.0.0.1`, `::1`, `localhost`). The
  app refuses anything else at startup, and the settings dialog refuses to
  save it. Do not look for a way around it; there is deliberately none.
- **Code tables are imported, never edited in the app.** A wrong label is fixed
  in the source and re-imported as a new generation
  (`scripts/build_codes_json.py` builds the file from ASTRA's
  `UAP_Referenzen.csv`, keeping only codes valid today).
- **Feature sets and prompt versions are frozen.** To change one, clone it or
  save a new version; old runs keep citing exactly what they used.
- **A run below the evaluation threshold is a smoke test, not a result**, and
  every view says so. Do not quote its numbers.
- **A mismatch rate is not a model error rate** until someone has read the
  mismatch list.

### 3.3 What may leave the machine

Every CSV export starts with
`# SENSITIVE — derived from non-anonymised police accident records.`
That line is a label; these are the rules (`data-handling.md` §3):

1. **An export is sensitive until a person has read it.** Screen it before it
   leaves the machine.
2. **Nothing containing an evidence span leaves the named group.** The mismatch
   exports carry verbatim narrative.
3. **Illustrations are synthetic, always.** A real mismatch pasted into a
   report or a slide is a narrative in a slide deck.
4. **An export you no longer need is deleted** — from Downloads and from
   everywhere it was copied. The app does not know where exports went and
   cannot delete them for you.

Which exports may go to whom is still a **DECISION REQUIRED** in
`data-handling.md` §3; until it is made, the rules above are the whole
permission.

### 3.4 Ending the processing

Destruction follows `data-handling.md` §4.1, in order: discard runs and
evaluations, delete corpora, discard deliveries, `just reset yes`, then by hand
the host-path source files, every export, and — if the machine is repurposed —
the disk. **Rehearse it once on seeded data before real data arrives**
(`data-handling.md` §4.3).

---

## 4. Developing

> Source: `CLAUDE.md`; `sw-design.md`; `README.md` → *Developing*;
> `docs/testing.md`.

### 4.1 Where and how

- **Platform:** Linux, macOS or WSL2 (§2). Windows remains a product target,
  and CI keeps a Windows leg for test layers 1–3.
- **Toolchain:** `uv` for everything Python (`uv sync --frozen`, `uv run …`),
  `just` for every command. Never bare `pip`, never `python -m venv`.
- **Running the app while developing:** `just dev` uses port 8080 and `./var`.
  **Agents and automated checks use `just dev-agent`** — a random port and a
  throwaway data directory, so they never touch a developer's live database.
- **Done means:** your tests are green, and `just lint` and `just test` pass.

### 4.2 The Do-NOT list

The thirteen invariants of `sw-design.md` §12, reproduced verbatim in
`CLAUDE.md`. They are not preferences; each has a test, a lint rule or a CI gate
behind it. In short:

| # | Never… |
|---|---|
| 1 | import `openai` or `ollama` outside the `LLMClient` implementation |
| 2 | mutate an `extraction`, `record` or `corpus` row — a re-run adds rows |
| 3 | edit an applied Alembic migration — add a new one |
| 4 | open a file without an explicit `encoding=`, or with `errors="replace"` |
| 5 | read canton, language or table kind from a filename |
| 6 | silently repair or drop a row — every one produces a `Finding` with its key |
| 7 | put business logic in `ui/`, or let `ui/` touch a session or an ORM object |
| 8 | hold UI state in module globals — use `app.storage.client` |
| 9 | fetch anything over the network from the UI — no CDN, fonts, telemetry |
| 10 | use `metadata.create_all()`, in the app or in tests |
| 11 | commit anything matching the real-data patterns in `.gitignore` |
| 12 | add a branch to production code that exists only for tests |
| 13 | open, query, print or paste the contents of `data/` or `RA2_DATA_DIR` |

### 4.3 Structure

- **The layer rule** (`CLAUDE.md`, enforced by `import-linter`): `domain`
  imports nothing else in `ra2/`; `ui` never imports `api` or `persistence`;
  `main.py` and `cli.py` are wiring only. A violation fails the build.
- **Frozen files** are listed in `CONTRACTS.md`. To change one, write
  `contracts/amendments/<branch>.md` with the file, the reason and the diff.
- **One migration author per phase**, so there is never a second Alembic head.
- **Findings, not prose:** assert on `FindingCode`, never on message text.
- **Document authority:** `vision.md` (why) → `ra2.md` → `mvp-spec.md` (what)
  → `sw-design.md` (how). Where a document is wrong, fix it in the same change.

### 4.4 Test data

- **Fixtures contain the real hazards** — mixed encodings, a stray `|`, an
  embedded newline, an orphan key, a duplicated key, an all-empty column,
  French already lossy. Clean fixtures are not acceptable.
- **Real data never reaches a test.** A hazard seen in real data is reproduced
  byte-exactly in a generated fixture and committed; the real file is not.
- **The real-data guard** (`just check-data`, pre-commit and CI) refuses
  delivery-shaped files anywhere in the tree by name *and* by content. Do not
  bypass it; if it blocks a synthetic fixture, the fixture belongs under
  `tests/fixtures/deliveries/` with invented keys.

### 4.5 Logging

A log line may carry ids, counts, statuses, model tags and durations. **It may
never carry** narrative, a resolved prompt, model output, a column value, a code
label, a delivery file name, or `unfall_uid` — at any log level
(`data-handling.md` §5.1). There is no log file; stderr only.

---

## 5. Working with an AI agent

> Source: `CLAUDE.md` (Do-NOT #13 and *Working agreements*);
> `risk-assesment.md` §8.3, §8.7.

The agent's transcript leaves the machine. Everything it reads, prints or
pastes has left the host with it.

1. **Only on a machine that fits §2.** On native Windows: synthetic data only,
   and the agent stays inside the checkout.
2. **The agent works inside the checkout.** It does not search the home
   directory, sibling folders, Downloads or network drives. If it needs a file
   from elsewhere, it asks, and the human decides whether to copy it in.
3. **Never `data/`, `var/` or `RA2_DATA_DIR`** — not opened, queried, printed or
   pasted, whatever the reason. Reproduce the hazard in a fixture instead.
4. **If an agent meets something that looks like real data**, it stops and
   says so. It does not read further to check.
5. **Attachments count.** Pasting a file into the conversation sends it; a
   reference table is fine, a delivery excerpt is not.
6. **Permission modes matter.** In auto mode an agent's commands run without a
   prompt, and its subagents inherit that. On a machine without a working
   sandbox, that means nothing stands between the agent and the disk.
7. **The deny list in `.claude/settings.json` is a backstop, not the rule.** It
   names paths inside the repository; it cannot name the places nobody knows
   about. The rule is the sentence in #13, and on Windows the absence of real
   data.

---

## 6. When something breaks

> Source: `data-handling.md` §5; `risk-assesment.md` §9.1.1, item 31 (open).

A description of a data bug is easily made of data. Until a support path is
agreed (`risk-assesment.md` item 31), these rules hold:

- **What may be sent to a developer or an agent:** run and record *ids*,
  counts, statuses, `FindingCode` values, endpoint status codes, model tags,
  versions, and the log (which by §4.5 carries none of the forbidden content).
- **What may not:** narrative text, a screenshot showing narrative or a record,
  an export, a `unfall_uid`, a delivery file or any part of one.
- **A parser problem** is reproduced by describing its *shape* — encoding,
  delimiter, which column, what kind of value — so a developer can synthesise
  it into a fixture. The fixture is the bug report.
- **A suspected incident** — real data somewhere it should not be — is reported
  to the contacts in `data-handling.md` §5 (**DECISION REQUIRED** until they
  are named). RA2 keeps no audit trail, so say early what you know.

---

## 7. Changing these rules

A rule changes in its source first (the table at the top), then here, in the
same change. A rule that restricts what the code may do also gets a test, a
lint rule or a CI gate — that is what separates a Do-NOT from advice.

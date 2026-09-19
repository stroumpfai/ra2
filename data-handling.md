# Data Handling — RA2

**What may leave this machine, how long the data stays, and how it is
destroyed.**

RA2 processes real, non-anonymised police accident records. `vision.md` records
that the joined record is personally identifying and that the risk is
*understood and accepted*; `sw-design.md` and `CLAUDE.md` record everything the
code enforces. This page is the part neither of them can enforce — the rules
that live with people, and the procedure for ending the processing.

> **This page is a draft with holes in it, and the holes are deliberate.**
> Everything marked **DECISION REQUIRED** needs a named human, not an
> implementing agent, and nothing here should be read as agreed until someone
> has filled those in and signed §7. The rest — the procedures, and the
> statements about what the software does — is verified against the code and
> is true today.
>
> Raised by `risk-assesment.md` **F1** (accountability), **B2** (outputs) and
> **B3** (retention and destruction); this page is recommendations 11, 14 and
> 20 of that report.

**Last reviewed:** 2026-09-18 · against commit `af0150f` and the B3 remediation.

---

## 1. What the data is

| | |
|---|---|
| **Structured records** | `Unfall` / `Objekt` / `Mitfahrende` rows: birth date, postcode, LV95 coordinates at metre precision, vehicle and insurer. Not anonymised. |
| **Narratives** | Free German and French accident descriptions (`UnfHergangText`). Whether the delivered text is anonymised at all is an **open question with the supplier** (`mvp-spec.md` §18; `risk-assesment.md` B5). |
| **Derived** | Extractions, scores, and **mismatches carrying `evidence_span`** — verbatim fragments of the narrative, mandatory by design so a reviewer can judge the model. |
| **Aggregates** | The census: column population counts, distinct counts, type hints. Value samples are withheld for every column the delivery does not mark as coded (`SD28`). |

Treat all four as the same class. The census is the only one where the software
itself removes identifying content, and it does so on a rule about the column
header, not about what a value happens to contain.

---

## 2. Where it is allowed to be

| | |
|---|---|
| **One named machine** | **DECISION REQUIRED** — which machine, and who has an account on it. |
| **Full-disk encryption** | Required. It is what makes every deletion below mean anything: the application can clear its own file, not the blocks the filesystem freed (`sw-design.md` §18.7). **DECISION REQUIRED** — confirm it is on. |
| **No cloud-synced data directory** | `RA2_DATA_DIR` must not sit under OneDrive, Dropbox or a redirected home directory. A synchronised `./var` is a silent second copy of the whole corpus. |
| **No remote-desktop sharing** of a session showing narrative text. |
| **Loopback only** | The app binds `127.0.0.1`; the model server must too (`OLLAMA_HOST=127.0.0.1`). **Any tunnel, proxy or forwarder between RA2 and a model server is a data breach, whatever the URL says** (`risk-assesment.md` A2). |
| **No debug logging on the model server** while real data is loaded (`OLLAMA_DEBUG` writes prompt content to its own log, outside all of this). |

---

## 3. What may leave the machine

The application produces six CSV exports. Every one is built in memory and
streamed to the browser — **nothing is written to the data directory** (`SD30`),
so every export exists exactly where the browser saved it, usually Downloads,
and `just reset` cannot reach it.

Every export's first line is
`# SENSITIVE — derived from non-anonymised police accident records.`
That line is a label. This section is the rule.

| Export | Carries | May be shared? |
|---|---|---|
| **Census** | Aggregates; value samples only for coded columns | **DECISION REQUIRED** — this is the week-one deliverable and the one most likely to be circulated |
| **File findings** | Row keys and parse detail | **DECISION REQUIRED** |
| **Presence / per-record lists** | Record keys and per-feature outcomes | **DECISION REQUIRED** |
| **Run scores** | Aggregated metrics per feature | **DECISION REQUIRED** |
| **Run mismatches** (discard dialog) | `record_value`, `extracted_value`, **`evidence_span`**, `analyst_tag` | **Verbatim narrative.** Named recipients only |
| **Mismatch review list** | The same, plus the anonymisation marking | **Verbatim narrative.** Named recipients only |

**Standing rules, pending those decisions:**

1. **An export is sensitive until a person has read it.** Screen it before it
   leaves the machine — that is the step the software cannot take for you.
2. **Nothing containing an evidence span leaves the named group.** The
   evaluation report's example rows are **synthetic**, always. The temptation
   to paste a real mismatch in as an illustration is exactly how a narrative
   ends up in a slide deck.
3. **The domain expert who reviews Goal 3 evidence reads narrative text.**
   Confirm they are covered by the same NDA as the analysts *before* that
   review, not after (**DECISION REQUIRED**).
4. **An export you no longer need is deleted**, from Downloads and from
   wherever you copied it. §4 step 6 is the end-of-PoC version of the same
   sentence.

---

## 4. Retention and destruction

**Retention period: DECISION REQUIRED.** How long may the corpus remain on the
machine after the PoC's deliverable is accepted?

**Destruction date: DECISION REQUIRED.** A date, not "when we get to it".

**Who performs and signs it: DECISION REQUIRED.**

### 4.1 The procedure

Steps 1–3 remove *part* of the data and are the analyst's everyday tools. For
end-of-PoC destruction, **4 through 7 are the ones that matter** — 1–3 are
unnecessary if the whole data directory is going.

Each step refuses if the one before it has not been done, so the order is not
advisory. **Only step 1a has a button.** Discarding an evaluation or a delivery
is an HTTP call — deliberate (`sw-design.md` §18.6 for the delivery; the nav
and the Import view are fixed designs), and worth knowing before you plan a
destruction session around the screen.

| # | Step | How | Refuses when |
|---|---|---|---|
| 1a | **Discard each run** | Evaluation view → the run's **discard** row action → confirm | The run is `queued` or `running` (G1 — let it finish, or interrupt it). Tagged mismatches require pressing through the warning, which names the count |
| 1b | **Discard the evaluation** | `DELETE /api/v1/evaluations/{id}` — **there is no button for this either**; the row action in 1a discards one run | Any of its runs is active. Tagged mismatches across its runs need `?force=true` |
| 2 | **Delete the corpus** | Census / corpus view | Any evaluation still cites it — so step 1b first |
| 3 | **Discard the delivery** | `DELETE /api/v1/deliveries/{id}` — **there is no button for this** (`sw-design.md` §18.6) | Any corpus still cites it — so step 2 first |
| 4 | **Wipe the data directory** | `just reset yes` | Nothing. It prints what it will remove and does nothing without the token |
| 5 | **Delete host-path source files** | By hand, wherever the delivery was registered from | Nothing — **the app never touches these.** See §4.2 |
| 6 | **Delete every export** | By hand: Downloads, and anywhere they were copied, attached or shared | Nothing — the app has never known where they are |
| 7 | **The disk** | If the machine is repurposed or returned, the disk is the unit of destruction | — |

### 4.2 What the software guarantees, and what it does not

**It does guarantee** that a discard removes the *bytes*, not merely the rows:
`secure_delete=ON` zeroes each freed page as it is freed, so a discarded run's
evidence spans are not left readable in the SQLite file
(`sw-design.md` §4.4, §18.7, `SD29`; asserted in
`tests/backend/services/lifecycle/test_discard_erasure.py`). `just reset`
removes the database **and its `-wal` and `-shm` sidecars**, which is where
committed rows also live.

**It does not guarantee:**

- **Host-path deliveries.** A delivery registered from a path on disk is
  registered *in place*; discarding it removes the database rows and leaves the
  files exactly where they were, outside `RA2_DATA_DIR` and outside
  `just reset`. This is deliberate — they are the analyst's own files and the
  app will not delete them — and it is why step 5 exists.

  > **DECISION REQUIRED (P5).** Decide whether real deliveries may be
  > registered from a host path at all. If intake for real data is
  > **upload-only**, step 5 disappears and destruction is complete at step 4.
  > If host-path intake stays, constraining it to a root under the data
  > directory (`risk-assesment.md` A4) achieves the same thing. Until one of
  > those happens, step 5 is a manual step that a runbook will eventually get
  > wrong.

- **Exports.** See §3. The app produces them and then has no further
  relationship with them.
- **The blocks the filesystem freed**, and any earlier backup or copy of the
  database. Only full-disk encryption (§2) and step 7 reach those.
- **That anything was exported before it was discarded.** No discard is
  recorded anywhere — no `deleted_at`, no tombstone, no export flag
  (`sw-design.md` §18.3). That is a deliberate choice, and its consequence is
  that *how many copies exist* is not answerable from the machine.

### 4.3 Rehearse it once

Run steps 1–4 end to end on synthetic data — `just reset-seed` gives you a
delivery, a corpus and a prompt version to destroy — **before** the machine
holds anything that matters. An acceptance step, once, deliberately, beside the
three already planned for M34. Destruction procedures that have never been
executed are the ones that fail on the day.

### 4.4 Backup

**DECISION REQUIRED.** Either a documented encrypted backup under the same
custody rules as the primary, or an explicit accepted decision that a lost
database means a re-run (GPU-weeks, `risk-assesment.md` E1). A backup is a
second copy of sensitive data and cannot be improvised safely under pressure,
so this is decided now or it is decided badly later.

*If backups are taken:* a hot copy of a WAL database needs `VACUUM INTO` or the
`.backup` API — never `cp`. And a backup taken before `secure_delete` was set
may contain narrative that has since been discarded from the live database.

---

## 5. If something goes wrong

**DECISION REQUIRED** — all of it:

| | |
|---|---|
| **Who is told** | A named person on the supplier's side, and one here |
| **Within what time** | A number of hours, agreed in advance |
| **By whom** | The person who notices, or a single named owner |

Note the constraint this project has deliberately accepted: **there is no
logging and no audit trail anywhere in RA2** (`mvp-spec.md` §13). It is the
right choice for keeping narrative text out of log files, and it means a
suspected incident cannot be investigated from the application. The evidence
available is the run provenance (`llm_endpoint`, `host_platform`, `gpu_name`,
model digest) and whatever the operating system records.

---

## 6. When the PoC ends

Non-goals are explicit — not production, no write-back, no integration — but
nothing technical stops a PoC that works from being handed a bigger corpus and
quietly operated as a service. At that point every deferred control is missing
at once, and the risk acceptance in `vision.md`, which rests on one machine and
a small named group, no longer describes reality.

**Decommission condition: DECISION REQUIRED** — the date or the event at which
this deployment stops.

**Before it could be operated for real**, all of these would have to exist:
authentication, an audit trail, retention and deletion policy in force, a
tested backup, a DPIA or `Bearbeitungsreglement` if the processing requires one,
and a named operator. Writing that list while the reasoning is fresh makes the
next conversation an engineering one instead of an argument.

---

## 7. The decisions, and who owes them

Nothing above is agreed until this table is filled in.

| # | Decision | Section | Owner | Date | Status |
|---|---|---|---|---|---|
| 1 | Named owner of this processing, and its legal basis | §7 | | | **open** |
| 2 | The named machine, its custody, and disk encryption confirmed | §2 | | | **open** |
| 3 | What may leave the machine, and to whom | §3 | | | **open** |
| 4 | Retention period | §4 | | | **open** |
| 5 | Destruction date, and who signs that it happened | §4 | | | **open** |
| 6 | Host-path intake: permitted for real deliveries, or upload-only | §4.2 | | | **open** |
| 7 | Backup, or accepted re-run | §4.4 | | | **open** |
| 8 | Incident contact and response time | §5 | | | **open** |
| 9 | NDA cover for the reviewing domain expert | §3 | | | **open** |
| 10 | Decommission condition | §6 | | | **open** |

**Signed:** ____________________  **Role:** ____________________  **Date:** __________

---

## 8. Related

| Where | What it covers |
|---|---|
| [`vision.md`](vision.md) | Why the data is here, and the recorded acceptance of the re-identification risk |
| [`sw-design.md`](sw-design.md) §18 | Discard: what it removes, what it erases, what it deliberately does not record |
| [`sw-design.md`](sw-design.md) §15.5 | The loopback rule, and why it has no opt-out |
| [`CLAUDE.md`](CLAUDE.md) | Do-NOT #13 — agents never read `data/` or `RA2_DATA_DIR` |
| [`risk-assesment.md`](risk-assesment.md) | The external review. B2, B3, F1 and the remediation log in §8 |

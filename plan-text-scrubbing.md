# Plan — Narrative Scrubbing

Replaces personal data in the accident narratives with numbered placeholders
(`<Lastname_1>`, `<LicensePlate_2>`) when a corpus is frozen, using regular
expressions and name lists only. **No LLM is involved at any step.** The rules
are visible to the analyst, and every replacement is counted in the import
report.

**Authority order**, as everywhere else: `mvp-spec.md` (what) → `sw-design.md`
(how) → this file (who builds what, and what they may touch). Where this file
and `sw-design.md` disagree, `sw-design.md` wins and this file is corrected in
the same commit.

**Status: decided and built, 2026-10-18, on `feat/text-scrubbing`.** §11
records the decisions taken. The mandatory patterns in §4 are **provisional**:
the implementer wrote them to the §4 contract, and they are replaced by the
supplied ones when those arrive. Each supplied pattern must still pass the
same examples.

---

## 1. The problem

The narratives are not anonymised (`data-handling.md` §2, risk B5). Whether
the supplier scrubbed anything is an open question, and the samples show the
parties replaced by role codes (`B1`, `G1`, `P`), while phone numbers, plates
and names of witnesses or relatives can still appear in free text.

Three readers see that text, and each is a reason to remove it before it is
stored:

1. **The screen.** Results, Mismatches, the prompt preview and the Import
   screen's raw file preview all show narrative text to whoever sits at the
   workstation.
2. **Future features.** Anything built later on `record.text_raw` or on the
   `UnfHergangTextAnonym` cell inherits whatever is stored there.
3. **A possible non-local LLM.** N1 and the loopback rule stand today. If they
   are ever relaxed, the text sent must already be scrubbed. Scrubbing it
   in the prompt adapter would be too late, because every other reader would
   still hold the original.

**So the stored corpus holds only the scrubbed text.** The original stays where
it already is, in the delivery files on disk. It is never written to the
database.

---

## 2. Scope

### 2.1 In

- A pure scrubber in `ra2/domain/scrub.py`: regex rules plus name lists,
  matching names without regard to case or accents, a whitelist, and
  numbering per record.
- **One new dependency, `regex`** (§3.6), for its matching timeout. Only
  `ra2/domain/scrub.py` may import it.
- **Mandatory rules, compiled into the code and always applied:** licence
  plates, phone numbers, email addresses. They cannot be disabled or
  overridden by an import.
- **Rules the analyst imports:** extra regexes (IBAN, AHV number, dates, and
  whatever else is supplied), a first-name list, a last-name list, and a
  whitelist. They are imported through the app, versioned in the database,
  **and never committed to the repository**.
- Scrubbing at `CorpusService.freeze`, applied to the narrative from the text
  file **and** to the `UnfHergangTextAnonym` cell. Only scrubbed text is
  persisted.
- Counts per rule (hits, records affected), stored on the corpus as
  REPORTED `Finding`s and shown before the freeze (dry run) and after it.
- The Import screen's 20-row raw preview is shown scrubbed with the active
  rule set.
- A new **Scrubbing** screen that lists every rule, every list and every
  version, and has a box for testing a sentence.
- One paragraph added to the seed prompt template that explains the
  placeholders.

### 2.2 Out

- **Addresses, street names and towns.** Explicitly not attempted. A last name
  inside a compound word (`Müllerstrasse`) is not matched, by design, because
  matching is on whole tokens.
- **Structured columns** (`Unfall` / `Objekt` / `Mitfahrende` cells other than
  `UnfHergangTextAnonym`). The structured record stays identifying
  (`vision.md`, *Real data*). Scrubbing it is a different project.
- **Re-scrubbing an existing corpus.** Do-NOT #2. A new rule set means a new
  freeze, which already produces a new corpus version.
- **Changing N1 or the loopback rule.** Scrubbing is a precondition for ever
  relaxing them, not a reason to.
- **Any claim of anonymity.** See §8.

---

## 3. How the scrubber works

All of it is pure domain code: `regex` (§3.6) and stdlib `unicodedata`, with
no I/O.

### 3.1 Two kinds of rule

| Kind | Source | Matches on | Tag |
|---|---|---|---|
| Regex rule | mandatory (code) or imported (TOML) | the original text, via `regex.finditer(…, timeout=)` | the rule's `tag` |
| Name list | imported (UTF-8 text, one entry per line) | normalised tokens (§3.3) | `Firstname` or `Lastname` |

A regex rule as imported:

```toml
[[rule]]
id      = "iban-ch"            # unique; may not reuse a mandatory id
tag     = "IBAN"               # ^[A-Z][A-Za-z]{1,31}$; Firstname, Lastname, Name reserved
pattern = 'CH\d{2}(?:\s?[0-9A-Z]{4}){4}\s?[0-9A-Z]'
must_match     = ["CH93 0076 2011 6238 5295 7", "CH9300762011623852957"]
must_not_match = ["CH93", "Km 123.4"]

# Optional, once per file: strings the WHOLE scrubber must leave untouched,
# on top of the built-in protected strings (§3.5).
protected = ["Rega 1414", "Tempo 80"]
```

### 3.2 One pass, deterministic

1. Collect **every** candidate span from every regex rule (mandatory first,
   then imported, each in declared order) and every name list, all against
   the original text.
2. Resolve overlaps: **regex beats name**. Within a kind, the earliest start
   wins, then the longest span, then the rule declared first.
3. Number the surviving spans (§3.4) and replace them in a single
   right-to-left pass.

Consequences, each one a test (§9): output is deterministic, a placeholder is
never re-matched, `scrub(scrub(t)) == scrub(t)`, and text outside the replaced
spans is byte-identical. Nothing else in the narrative is normalised.

### 3.3 Name matching: case- and accent-insensitive

- **Tokens.** `[^\W\d_]+`, letters only. `'`, `’`, `-` and whitespace are the
  only separators allowed *inside* a multi-token entry.
- **Normalisation, applied to every token and every list entry, in two
  forms:**
  - *stripped*: `casefold()`, NFKD, drop combining marks (`Mn`);
  - *transliterated*: `casefold()`, then `ä→ae`, `ö→oe`, `ü→ue`, then as
    *stripped*.

  An entry is indexed under both forms, and a text n-gram matches if either
  of its forms is indexed. So `René` = `rene` = `RENE`; `Müller`, `Mueller`
  and `Muller` all match a list holding any one of them; and an NFD
  `Mu\u0308ller` matches like an NFC one (Q3). The stored text is not
  normalised. Only the comparison is.
- **Multi-token entries** (`von Allmen`, `De la Cruz`, `D'Alessandro`) are
  tokenised the same way and matched as n-grams, longest first, using a set
  lookup per n-gram length. Cost is O(tokens × max n), independent of list
  size. No giant alternation regex.
- **Whitelist.** An n-gram in the whitelist is never replaced by a name rule,
  **unless an honorific immediately precedes it** (Q2): `Herr`, `Frau`,
  `Hr.`, `Fr.`, `M.`, `Mme`, `Mlle`, `Monsieur`, `Madame`, `Signor`,
  `Signora`, `Sig.`, `Sig.ra`, a constant in `scrub.py`. So `ein Fuchs querte`
  keeps its fox and `Herr Fuchs` loses his name. The honorific only lifts the
  whitelist. It never makes a word that is on no list into a name. The
  whitelist does not shield text from regex rules.
- **Too short to trust.** An entry that normalises to fewer than 3 letters is
  skipped *and reported* at import (`Le`, `Da`, `Li` would erase French
  articles). `MIN_ENTRY_LETTERS = 3`, a constant (Q10).
- **Both lists.** A token found in both lists (`Martin`, `Simon`, `Werner`)
  is tagged `Firstname` when the next token is on the last-name list,
  `Lastname` when the previous token was tagged `Firstname`, and otherwise
  `<Name_n>` (Q1).

Known misses, written into the risk register rather than worked around:
genitive and inflected forms (`Meiers`), names whose letters were deleted upstream (h09, so
`Lœwe` arrives as `Lwe`), mojibake (`MÃ¼ller`; the canary already flags the
corpus), nicknames and typos.

### 3.4 Numbering

Per record, restarting at 1. Each tag has its own counter. The key is
`(tag, normalised value)`:

- names: the transliterated form of the matched list entry, so
  `Herr Müller … müller … Mueller` → `<Lastname_1>` all three times;
- regex rules: casefolded, with whitespace and `- . / ( )` removed, so
  `079 123 45 67` and `0791234567` → the same `<Phone_1>`.

`Hans Müller sprach mit Anna Müller` →
`<Firstname_1> <Lastname_1> sprach mit <Firstname_2> <Lastname_1>`. That is
correct: one surname, two people. The numbers keep references within a
narrative consistent, the same job `B1` / `G1` already do. They mean nothing
across records.

The `UnfHergangTextAnonym` cell is scrubbed with its own numbering. When it is
also the record's narrative (the fallback in `_text_for`), it is the same text
and produces the same result.

### 3.5 What gets checked when rules are imported or compiled

Refused (BLOCKING), with a stable `ScrubImportError` code, following the
pattern of `codes.py`'s `CodeImportError`:

- the TOML does not parse, a field is missing, an id is duplicated, or an id
  collides with a mandatory rule;
- a tag is malformed or reserved;
- a pattern does not compile, or **can match the empty string**;
- a `must_match` example is not matched *in full* by its own rule;
- a `must_not_match` example is matched anywhere by **its own rule**. The
  examples are local: the phone rule's counter-example `756.1234.5678.97` is
  exactly what the AHV rule exists to replace, so asking the whole scrubber to
  leave it alone would refuse a correct rule set;
- a **protected string** is altered by **the whole effective scrubber**
  (mandatory + imported + lists). This is the cross-rule check: it catches a
  date rule eating `um 07.45 Uhr`. The protected strings are the built-in
  constant `PROTECTED_STRINGS` in `scrub.py`, plus the TOML's optional
  `protected` list. The built-in ones are role codes `B1` `G1` `P`, `80 km/h`,
  `um 14.30 Uhr`, `um 07.45 Uhr`, `A1`, `N1`, `Hauptstrasse 12`, `Km 12.5`,
  `Rega 1414`, `Notruf 117` / `144`, `im Kanton ZH 2 Verletzte`. Features
  depend on them;
- a name list that is not valid UTF-8 (Do-NOT #4: explicit `encoding=`, no
  `errors="replace"`).

Reported, but the import still succeeds: a BOM, CRLF line endings, blank
lines, duplicate entries, entries that are too short, and entries also present
in the whitelist. Each is a count, never a silent drop (Do-NOT #6).

**ReDoS.** Every match runs under `regex`'s `timeout=` (§3.6). At import,
each pattern is also run against three synthetic 20 kB adversarial strings
(digits, spaces, mixed) under the tighter `IMPORT_TIMEOUT_S`. A pattern that
times out is refused (`pattern_too_slow`), so a runaway pattern is an input
error, not a hung task.

### 3.6 The `regex` package

The engine is [`regex`](https://pypi.org/project/regex/) (mrab-regex), not
stdlib `re`. It was chosen for one feature: **`timeout=` on `search`,
`finditer` and `sub`**, which raises `TimeoutError` *during* matching. Stdlib
`re` has no equivalent, and analysts import the rules through the UI, so a
bad pattern has to fail like every other bad input: cleanly, with a code.

| Fact | Value, checked on PyPI 2026-10-18 |
|---|---|
| Version pinned | `regex>=2026.9.29` |
| Runtime dependencies | **none** (`requires_dist` is empty) |
| Licence | Apache-2.0 AND CNRI-Python |
| Wheels | cp314 for win_amd64/arm64, manylinux and musllinux x86_64/aarch64, macOS arm64/x86_64. Nothing compiles at install |
| Network | **none**. A C matcher with its Unicode tables compiled in: no download, no telemetry, no socket. Irrelevant to N1 |
| Supply chain | the same as every wheel: `uv.lock` pins the file hashes, and `uv sync --frozen` refuses anything else |

Rules that come with it:

- **Only `ra2/domain/scrub.py` imports `regex`.** It is a new import-linter
  `forbidden` contract, `regex-only-in-the-scrubber`, so the package cannot
  spread. `sw-design.md` §1.1 and CLAUDE.md's layer table name it beside
  `pydantic` as the domain's one other allowed third-party import.
- **One engine for every rule**, the mandatory ones included, so each rule's
  examples are tested against the engine that runs them. Patterns compile in
  `regex`'s `VERSION0` mode, the `re`-compatible one.
- **A timeout at freeze fails closed.** A narrative that could not be
  scrubbed is a narrative that would be stored unscrubbed. So the freeze
  raises `BlockingFindingsError` carrying `FindingCode.TEXT_SCRUB_TIMEOUT`
  (BLOCKING, with the record's `UnfallUid` and the rule id), and nothing is
  written (Do-NOT #6). The record is never skipped, and never stored
  verbatim.
- **Features deliberately not used:** fuzzy matching (`{e<=1}`) and named
  lists (`\L<names>`). The first would hit ordinary words constantly on
  case-insensitive lists; the second cannot fold accents the way §3.3
  requires, so the token-set lookup stays.

---

## 4. The mandatory rules

They live in `ra2/domain/scrub_mandatory.py` as a Python literal: committed,
visible, versioned by git, and tested in CI. The domain layer may not read
files, so they cannot be a TOML file. **The patterns themselves will be
supplied.** Until then, the implementer's provisional patterns ship, written
to this contract. A supplied pattern replaces a provisional one only if it
passes the same examples. This plan fixes the contract each one must meet, as
`must_match` / `must_not_match` examples that become tests:

| Tag | Must match (at least) | Must **not** alter |
|---|---|---|
| `LicensePlate` | `BE 123456`, `ZH 1234`, `VD-123 456`, `AG 12 345`, `TI123456` | `B1`, `G1`, `A1`, `N1`, `Kanton BE`, `Hauptstrasse 12`, `Km 12.5`; **`im Kanton ZH 2 Verletzte`** (Q4: a canton code after `Kanton` / `canton` / `Kt.` is never a plate) |
| `Phone` | `079 123 45 67`, `+41 79 123 45 67`, `0041 79 123 45 67`, `044 123 45 67`, `+41 (0)44 123 45 67`, `0791234567` | `117`, `144`, `1414` (emergency numbers are information); `um 14.30 Uhr`, `12.03.2024`, `80 km/h`, `756.1234.5678.97` (an AHV number is the AHV rule's to claim) |
| `Email` | `a.b@example.ch`, `x+y@sub.example.org` | `B1@` fragments, `@` alone |

Tags stay in English, whatever the narrative's language. The number of the
mandatory rule set's version, and the full rule set itself, are copied onto
every corpus frozen with them (§5), so a corpus shows which mandatory rules it
got even after the code changes.

Expected **imported** rules: `IBAN`, `AHV` (`756.1234.5678.97`), `Date`
(`12.03.2024`, `12.3.24`, `12. März 2024`, `1er mars 2024`). The date rule
needs `um 07.45 Uhr` in its `must_not_match`. `12.03` on its own is ambiguous
between a date and a time (§11, Q5).

**Existing fixtures.** The mandatory rules now run on every freeze, including
the hazard fixtures, the seed and `scored_corpus.py`. Before anything merges,
S1 runs them over every committed fixture narrative and reports what changes.
The expected answer is nothing. Any golden file that does change is
regenerated in its own commit, with the reason.

---

## 5. Storage

**One migration, and one author: S2.** Nobody else runs `alembic revision`.

```
scrub_list(id, kind, filename, sha256, imported_at, entry_count,
           content_text, import_report_json)
    -- kind: regex | firstname | lastname | whitelist
    -- IMMUTABLE. UNIQUE(kind, sha256): re-importing the same file reuses the row

scrub_ruleset(id, version UNIQUE, created_at, fingerprint,
              regex_list_id NULL, firstname_list_id NULL,
              lastname_list_id NULL, whitelist_id NULL)
    -- IMMUTABLE. Importing one file creates version n+1 = version n with
    -- that one component swapped. The highest version is the active one.

corpus + scrub_ruleset_id NULL     -- FK; NULL = mandatory rules only
       + scrub_fingerprint NULL    -- the effective set (mandatory + imported);
                                   -- NULL = frozen before this feature existed
       + scrub_mandatory_json NULL -- snapshot of the mandatory rules applied
```

- **The counts go in `corpus.import_report_json`**, as one REPORTED `Finding`
  per rule, `FindingCode.TEXT_SCRUBBED`, with detail
  `{rule_id, tag, source: mandatory|imported|list, hits, records}`. A rule
  with zero hits is still reported, so the report always lists every rule
  that ran.
- **Per-record counts are not stored.** They can be derived by counting
  `<Tag_n>` in the stored text, which the drill-down can do if it is ever
  wanted.
- **`record.text_raw` keeps its name and changes its meaning**: "the
  narrative as delivered, after the corpus's scrub rule set". Renaming the
  column would touch every consumer for nothing. The same applies to the
  `UnfHergangTextAnonym` row's `value_raw`.
- **Language detection and the cp1252 canary run on the original text, in
  memory, before scrubbing.** The canary counts characters the scrubber
  removes (accented names), so counting afterwards would understate the
  loss.
- Do-NOT #2 gets extended in `sw-design.md` to `scrub_list` and
  `scrub_ruleset`.

---

## 6. Where scrubbing happens in the pipeline

| Step | Change | Owner |
|---|---|---|
| Rule import | `ScrubService.import_list(kind, filename, content)` → validate (§3.5) → new `scrub_list` (or reuse one) → new `scrub_ruleset` version | S3 |
| Dry run | `CorpusService.scrub_preview(delivery_id)`, a direct call like `freeze`: it walks the selected files with the freeze's own code (`_selected`, `_unfall_rows`, `_scrub_record`), so the counts are the freeze's. Returns per-rule counts and the rule-set id it used. Nothing is written. *Changed during the build*: first planned as a `ScrubService` task, which would have meant a second walk to keep equal to the first | S3 |
| Freeze | `freeze(…, scrub_ruleset_id=None)`. The new keyword is the ruleset the preview showed; `None` means the active one. A preview of v4 followed by a freeze under v5 would otherwise go unnoticed. The service compiles the scrubber once, scrubs in `_build_records`, writes the §5 columns and the `TEXT_SCRUBBED` findings. The counts must equal the dry run's (a test). A `regex` timeout raises `BlockingFindingsError` with `TEXT_SCRUB_TIMEOUT`, and nothing is written (§3.6) | S3 |
| Raw preview | `DeliveryService.preview` scrubs every returned line with the active effective scrubber. Line-level, all file kinds | S3 |
| Prompt | Nothing in code. `{{narrative}}` already resolves to `text_raw`. The seed template gains a paragraph (§7.4) | S5 |
| Exports, Results, Mismatches | Nothing: they read `text_raw` | — |

**A layer note.** `scrub.py` decodes uploaded bytes with
`bytes.decode("utf-8")`. That is not filesystem access, and `codes.py`
already does the same for `codes-2018.json`.

---

## 7. UI — proposals (no design exists yet)

All four follow the existing tokens and primitives (`theme.py`,
`components/primitives.py`, `data_table.py`). Each still needs a design pass
before E2E asserts pixel sizes (`sw-design.md` §8.2).

### 7.1 A new **Scrubbing** screen (nav: Data → after Codelists)

Recommended. It is a concept of its own, and the analyst has to find it
without being told where to look.

```
┌ Scrubbing ─────────────────────────────────────────────────────────────┐
│ RULES v4 · active · since 2026-10-17 14:02 · fp 3f9a…    [Import ▾]   │
│                                       (Regex · Firstnames · Lastnames · Whitelist)
├────────────────────────────────────────────────────────────────────────┤
│ REGEX RULES                                                            │
│  🔒 license-plate  <LicensePlate>  (?:AG|AI|…)[\s-]?\d{1,6}   ✓5 ✗8   │
│  🔒 phone-ch       <Phone>       (?:\+41|0041|0)…            ✓6 ✗7   │
│  🔒 email          <Email>         […]@[…]                     ✓2 ✗2   │
│     iban-ch        <IBAN>          CH\d{2}…        regex.toml  ✓2 ✗3   │
│     ahv            <AHV>           756\.\d{4}…     regex.toml  ✓1 ✗2   │
│  (row expands: full pattern, mono, wrapped; every example as a chip)   │
├────────────────────────────────────────────────────────────────────────┤
│ NAME LISTS   [Firstnames 18 204] [Lastnames 41 877] [Whitelist 312]    │
│  vornamen-2025.txt · sha 9c1e… · 2026-10-17 · 14 duplicates, 22 short │
│  ┌ search ───────────┐                                                 │
│  │ müll              │   müller · müller-lüdenscheidt · müllhaupt …    │
│  └───────────────────┘   paged, 50 per page, normalised form in grey   │
├────────────────────────────────────────────────────────────────────────┤
│ TRY A SENTENCE                                                         │
│  [Herr Müller (079 123 45 67) fuhr mit BE 12345 …                  ]   │
│  → <Lastname_1> (<Phone_1>) fuhr mit <LicensePlate_1> …               │
│  nothing is stored; uses the active rules                              │
├────────────────────────────────────────────────────────────────────────┤
│ VERSIONS  v4 lastnames swapped · v3 whitelist · v2 regex · v1 …        │
│           each with the corpora frozen under it                        │
└────────────────────────────────────────────────────────────────────────┘
```

The cost: the nav goes from eight items to nine. That is a design amendment
to `design/nav-import-census/README.md`, and the E2E nav assertion changes
with it.

**Alternative:** a *Scrubbing* tab inside Codelists, renamed *Reference
data*. No nav change, but it hides a privacy control inside a coding tool.

### 7.2 Import screen: the freeze card gets a dry run

```
┌ Freeze ───────────────────────────────────────────────────────────────┐
│ Name [Bern 2025-Q3        ]                                           │
│ SCRUBBING with rules v4                         [Preview scrubbing]   │
│   <LicensePlate>   312 hits · 280 records   🔒                         │
│   <Phone>         41 hits ·  39 records   🔒                         │
│   <Email>            0                      🔒                         │
│   <Lastname>     1 204 hits · 903 records                              │
│   <Firstname>      988 hits · 811 records                              │
│   MOST-HIT LIST ENTRIES (≥ 10 hits) — whitelist candidates             │
│   weiss 233 · koch 61 · fuchs 18 …                    → Scrubbing      │
│                                                     [Freeze corpus]   │
└───────────────────────────────────────────────────────────────────────┘
```

The *most-hit entries* table shows **list entries** (public data), never
record text, and only entries with at least *k* hits. A low count could
disclose that a rare name occurs in the corpus, so *k* acts as a floor
(§11, Q6). It is the fastest way to find whitelist candidates: `weiss` is a
car colour long before it is a person.

The file report modal's raw preview gets a caption: *scrubbed with rules v4*.

### 7.3 Corpora table and Results header

- A `SCRUBBED v4` chip next to `SYNTHETIC` / dev-sized. The row expands to
  show the §7.2 counts table, read from the import report.
- **Corpora frozen before this feature**: a `NOT SCRUBBED` chip in
  `--danger`, with a tooltip suggesting a re-freeze. They cannot be changed
  (Do-NOT #2).
- The Results header repeats the corpus chip, so a screenshot of a result
  says what it was computed on.
- The per-record SD50 marking stays as it is. It describes where the text
  came from, which is a separate fact from whether it was scrubbed.

Placeholders render as plain text through `ui.label`. Styling them (a mono
inline chip) would mean splitting the text into separate labels, never
`ui.html` (SD31, provenance). That is deferred.

### 7.4 The prompt

Appended to the seed template in `scripts/seed_dev.py`, which becomes a new
template version the next time the seed runs:

> Text in angle brackets, such as `<Lastname_1>` or `<Phone_2>`, is a
> placeholder for personal data that was removed. The same placeholder means
> the same value within this narrative; different numbers mean different
> values. Never return a placeholder as a feature value. Quoting one inside an
> evidence span is correct.

`sw-design.md` §15.1 records the paragraph as **recommended** template content.
The template stays analyst-authored. A `{{placeholders}}` slot generated from
the rule set's tags was considered and deferred, because the slot catalogue is
frozen and the paragraph above is generic enough.

---

## 8. Honesty: what the labels may claim (SD50, extended)

- The app says **scrubbed**, never **anonymised**. Name lists miss whatever
  is not on them; §3.3 lists the known misses.
- `data-handling.md` §2 *Narratives* row: "scrubbed at freeze with the rule
  set recorded on the corpus; names not on the lists, and addresses, remain."
- `docs/risk-assesment.md` gets a new entry (B-series): *residual personal
  data after scrubbing*. The scenario is a reader trusting the chip. The
  mitigations are the chip wording, the most-hit table and the sentence
  tester.
- `docs/rules.md`: the name lists are public data but **are not committed**.
  `.gitignore` gains `**/scrub-lists/` and `*.names.txt` as a guard. The
  invented fixtures stay outside those patterns, and a test says so.

---

## 9. Tests

Fixtures use **invented** names and numbers only, never the supplied lists.
`tests/fixtures/scrub/generate_scrub_fixtures.py` writes them byte-exactly to
`tests/fixtures/scrub/hazards/`: `s01_firstnames.txt` (an NFD entry),
`s02_lastnames.txt` (BOM, CRLF, one name spelt three ways, entries too short),
`s03_whitelist.txt`, `s04_rules.toml` (IBAN, AHV, dates), and two that must be
refused, `s05_lastnames_cp1252.txt` and `s06_slow_rule.toml`.
New delivery hazard: **`h18_names_in_narrative`**, generated byte-exactly by
`generate_hazards.py` like h01–h17.

### `tests/unit/scrub/` (S1)

- **Each mandatory rule's examples**, parametrised. The supplied patterns
  arrive with their examples, and the table in §4 is the minimum.
- **Overlap resolution:** regex beats name; earliest, then longest, then
  declared first; AHV beats Phone; IBAN is not split.
- **Invariants:** deterministic output, `scrub(scrub(t)) == scrub(t)`, text
  outside the spans byte-identical, protected strings untouched, `None` and
  `""` handled.
- **Name hazards:**
  - word boundaries: `Müllerstrasse`, `Weberei`;
  - normalisation: NFC vs NFD, upper/lower case, `René` / `Rene`;
  - the h09 lossy-French token;
  - a name split by an embedded newline (h04-style);
  - whitelist: `Herr Fuchs` vs `ein Fuchs querte`;
  - multi-token entries: `von Allmen`, `Müller-Lüdenscheidt`, `D'Alessandro`;
  - known miss: genitive `Meiers` stays untouched, and is asserted as such;
  - a name on both lists → §3.3's rule.
- **Numbering:** the same value gets the same number, numbers are contiguous
  from 1 per tag, `079 123 45 67` and `0791234567` share a number, and
  numbering restarts per record.
- **Import validation (§3.5):** one test per `ScrubImportError` code,
  including an empty-match pattern, a cross-rule `must_not_match` failure, a
  protected-string failure, a mandatory-id collision, a cp1252 name list,
  and a catastrophic-backtracking pattern refused as `pattern_too_slow`.
  It is `(a|aa)+$`: `regex` optimises the textbook `(a+)+$` away, measured.
- **Timeout:** `scrub()` raises `ScrubTimeout` naming the rule when matching
  exceeds its budget. Neither partial text nor an unscrubbed original is ever
  returned.
- **Engine confinement:** `regex` is imported by `ra2/domain/scrub.py` and
  nothing else (the import-linter contract, plus a test that greps `ra2/`).
- **Hypothesis properties:**
  - Generate text from a vocabulary and plant fixture names: no planted name
    survives as a whole token.
  - The sequence of untouched tokens is preserved.
  - Placeholders are well formed.

### `tests/backend/` (S2, S3, S4)

- **Migration:** upgrade and downgrade on temp SQLite (`tests/fixtures/
  migrations.py`). A pre-existing corpus has `scrub_fingerprint IS NULL`.
- **Repositories:** `scrub_list` reuse by `(kind, sha256)`; version n+1
  inherits n's components; nothing ever UPDATEs a row.
- **Freeze with h18:**
  - `text_raw` and the `UnfHergangTextAnonym` cell are scrubbed;
  - `TEXT_SCRUBBED` findings exist for every rule, zero-hit rules included;
  - the counts equal `preview_counts`;
  - language and canary results equal the values computed from the
    unscrubbed fixture;
  - freezing twice gives identical text.
- **The leak test.** After freezing h18, read every `TEXT` column of every
  table through `sqlite_master` and assert that **none** of the planted
  values appears, normalised. The same assertion runs over every CSV export,
  the prompt preview and `DeliveryService.preview`.
- **Freeze race:** a preview under v4, then an import of v5, then a freeze
  with `scrub_ruleset_id=v4` scrubs with v4.
- **No imported rule set:** only the mandatory rules apply, and
  `scrub_ruleset_id IS NULL`.
- **Fail closed:** a scrubber whose budget is exceeded during freeze raises
  `BlockingFindingsError` with `TEXT_SCRUB_TIMEOUT`, carrying the
  `UnfallUid`, and leaves zero `corpus`, `record` and `census_*` rows.
- **API:** import (201, and a 422 carrying the `ScrubImportError` code),
  list, versions, entries search (paged), try-a-sentence, preview task.
  OpenAPI snapshot regenerated: additions only.

### `tests/ui/` and `tests/e2e/` (S5)

- **UI (`User` fixture):**
  - the Scrubbing screen lists mandatory rules with a lock and imported rules
    with their source;
  - the name-list search pages;
  - the sentence tester shows the placeholders;
  - the freeze card shows counts and the ruleset version;
  - `NOT SCRUBBED` / `SCRUBBED vN` chips;
  - `<Lastname_1>` renders literally, not as HTML, in Results and in the
    prompt preview.
- **E2E journey:** import the fixture lists, register h18, preview, freeze,
  open Results, and see placeholders and no planted name in the page
  (J6 still watches that the browser makes no outbound call). The lead
  assigns the journey number.

### Performance (S3)

A 50 000-entry list and 20 000 synthetic records of 600 characters each must
scrub within a budget recorded in `docs/performance.md`. Marked like the
existing performance tests.

### The sweep (S1, before merge)

Run the mandatory rules over every committed fixture narrative, the seed
scenarios and `scored_corpus.py`, and report what changes (§4).

---

## 10. Ownership and frozen files

**One branch, one implementer.** The slice is built on `feat/text-scrubbing`
by a single implementer, in the order below, so nobody's paths overlap and
the S-labels are steps, not agents. The ownership rule still holds: the
integration check is the branch's changed-file list against `main`, compared
with the union of the rows below. **One amendment file**,
`contracts/amendments/feat-text-scrubbing.md`, names every frozen file
touched. **The migration author is this branch's implementer**: one
revision, one head.

**Step 0, before any code** (`CLAUDE.md`: `sw-design.md` first, in the same
commit as the code that needs it):

- `sw-design.md`:
  - §1.1 and CLAUDE.md's layer table: `regex`, for `domain/scrub.py` only;
  - a new **§19 *Narrative scrubbing***;
  - **SD62**: only scrubbed text is stored, and the scrub happens at freeze;
  - **SD63**: mandatory rules are code, imported rules are data;
  - **SD64**: placeholders are numbered per record;
  - **SD65**: the label says *scrubbed*, never *anonymised*;
  - **SD66**: `regex` with a timeout, failing closed.
- `ra2.md`: the stack gains `regex`.
- `mvp-spec.md` §5 (`text_raw`'s meaning) and §13 (the corpus-level chip).
- `data-handling.md`, `docs/risk-assesment.md`, `docs/rules.md` (§8 of this
  plan).

| Step | Label | Owns |
|---|---|---|
| 1 | **S1** domain | `ra2/domain/scrub.py`, `ra2/domain/scrub_mandatory.py` (new), `ra2/domain/ids.py` (`ScrubListId`, `ScrubRulesetId`), `ra2/domain/findings.py` (`TEXT_SCRUBBED`, `TEXT_SCRUB_TIMEOUT`), `pyproject.toml` + `uv.lock`, `.importlinter`, `tests/unit/scrub/`, `tests/fixtures/scrub/`, h18 in `tests/fixtures/deliveries/generate_hazards.py`, the §9 sweep |
| 2 | **S2** persistence | `ra2/persistence/models.py` (the §5 additions), **the one migration**, `ra2/persistence/repositories/scrub_repo.py` (new), `tests/backend/persistence/` scrub tests, the contract-test registries (`POST_PHASE_5_REVISIONS`) |
| 3 | **S3** services | `ra2/services/scrub_service.py` (new), `corpus_service.py` (body plus the defaulted keyword), `delivery_service.preview` body, `readmodels.py`, `errors.py`, `container.py` + `main.py` wiring, `tests/backend/services/scrub/`, the performance test |
| 4 | **S4** API | `ra2/api/v1/scrub.py` (new), `router.py`, `schemas.py`, `deps.py`, the OpenAPI snapshot, `tests/backend/api/scrub/` |
| 5 | **S5** UI | `ra2/ui/views/scrubbing_view.py` (new), the nav item in `shell.py`, the freeze card in `import_view.py`, the preview caption in `file_report_modal.py`, the chips in the Corpora table and `results/chrome.py`, the `TEXT_SCRUBBED` rendering row, `scripts/seed_dev.py` (prompt paragraph; imports the fixture lists), `docs/seed.md`, the design README amendment, `tests/ui/`, the E2E journey |

Frozen files needing an amendment, all in the one amendment file:

| File | What |
|---|---|
| `ra2/domain/ids.py` | `ScrubListId`, `ScrubRulesetId` |
| `ra2/domain/findings.py` | `FindingCode.TEXT_SCRUBBED` (REPORTED), `FindingCode.TEXT_SCRUB_TIMEOUT` (BLOCKING) |
| `ra2/persistence/models.py` | `ScrubList`, `ScrubRuleset`, the three `corpus` columns |
| `ra2/services/corpus_service.py` | `freeze(…, scrub_ruleset_id: ScrubRulesetId \| None = None)`, defaulted, so existing callers keep working |
| `ra2/services/delivery_service.py` | body of `preview` only |
| `ra2/services/readmodels.py` | `ScrubRulesetView`, `ScrubRuleView`, `ScrubListView`, `ScrubCountsView`; `CorpusView` + `scrub_version: int \| None`, `scrubbed: bool` |
| `ra2/services/container.py`, `ra2/main.py` | `Services.scrub` |
| `ra2/services/errors.py` | `ScrubImportRefusedError` (→ 422, carrying the codes) |
| `ra2/api/schemas.py`, `ra2/api/deps.py` | the response models and `ScrubServiceDep` |
| `ra2/ui/shell.py` (`NAV_ITEMS`) | the ninth item (Q9) |
| `pyproject.toml`, `.importlinter` | `regex`; the `regex-only-in-the-scrubber` contract |
| `tests/test_p3_contract.py`, `test_p4_contract.py`, `test_p5_contract.py` | the eight-item nav, the pinned dependency list and the pinned contract count each become "phase 5's set plus a named post-phase set", the `POST_PHASE_5_*` pattern those files already use |
| `.gitignore` | the §8 patterns |

---

## 11. Decisions taken

Asked on 2026-10-17. The proposed defaults were accepted on 2026-10-18,
except Q8, which was revised after the `regex` package was checked (§3.6).

| # | Question | Decision |
|---|---|---|
| Q1 | A token on both name lists, with no neighbour that settles it | `<Name_n>` |
| Q2 | Should an honorific override the whitelist? | Yes. A fixed honorific list in the code, lifting the whitelist only (§3.3) |
| Q3 | Should `Müller` match `Mueller`? | Yes. Both forms are indexed and looked up (§3.3) |
| Q4 | `im Kanton ZH 2 Verletzte` looks like a plate | A canton code after `Kanton` / `canton` / `Kt.` is never a plate. The provisional pattern does this; a supplied one must pass the same example |
| Q5 | `12.03` alone: date or time? | Not a date unless a year or a month name is present. It goes in the date rule's `must_not_match` |
| Q6 | The *k* floor for the most-hit list entries | 10, a constant (`MOST_HIT_FLOOR`) |
| Q7 | Highest version active, or an explicit *Activate*? | The highest is active; rolling back means re-importing the older file |
| Q8 | Stdlib `re` or the `regex` package? | **`regex`**, with a timeout, failing closed (§3.6) |
| Q9 | Nav item or Codelists tab? | Nav item, *Scrubbing*, in Data after Codelists |
| Q10 | Minimum entry length | 3 letters (`MIN_ENTRY_LETTERS`) |

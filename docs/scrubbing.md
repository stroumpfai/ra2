# Scrubbing — RA2

**How RA2 replaces personal data in the accident narratives with placeholders,
what you can configure, how to write the files it imports, and what it will
always miss.**

This page is for an analyst preparing or importing scrub rules and name lists,
and for anyone reading a scrubbed corpus. It assumes no knowledge of the
codebase. Where to find each control is in §2; the file formats are in §4.

**This page is not authority.** `mvp-spec.md` decides *what* the product must
do, `sw-design.md` §19 decides *how* scrubbing is built, and where either
disagrees with this page, this page is wrong. Every example below is checked
by a test (§6 says which), so an example that stops being true fails the
build rather than misleading you.

**Last reviewed:** 2026-10-18 · mandatory rules v1 (**provisional**, see §2.1).

---

## 1. Scrubbing is not anonymisation

**Scrubbing** replaces the spans a rule recognises with a placeholder such as
`<Lastname_1>` or `<Phone_2>`. It is mechanical: a regular expression or a name
list either matches a span or it does not. **No LLM is involved at any step**,
and nothing guesses.

**Anonymisation** is a claim about the result: that no person can be
identified from it. Scrubbing cannot make that claim, and RA2 never does. The
screens say *scrubbed*, never *anonymised*.

| | Scrubbing (what RA2 does) | Anonymisation (what RA2 does not claim) |
|---|---|---|
| What it is | Replace what the rules recognise | Remove everything that identifies a person |
| How it decides | Patterns and lists you can read on the Scrubbing screen | Judgement about context, combinations, rarity |
| What it misses | Anything not on a list or not matched by a pattern | By definition, nothing |
| What the label says | `scrubbed · rules v3` | — |

**What survives scrubbing, by construction:**

- names that are on no list: rare or foreign surnames, nicknames, typos;
- inflected forms: `Meiers Auto` keeps `Meiers`, because the list holds `Meier`;
- names whose letters were lost upstream: a French `Lœwe` that arrived as
  `Lwe` matches nothing (the canary on the Import screen warns about this
  kind of damage);
- whitelisted words used as names without an honorific: `Fuchs sagte` keeps
  `Fuchs` (§3.4);
- addresses, streets and towns, which are **not attempted at all**;
- descriptions: *the driver's 82-year-old mother* names nobody and identifies
  somebody;
- **everything in the structured record**: birth date, postcode, coordinates,
  vehicle and insurer are not touched by scrubbing, and the joined record stays
  identifying.

**So treat a scrubbed corpus exactly like an unscrubbed one.** Everything in
`data-handling.md` and [`rules.md`](rules.md) still applies, including to the
mismatch export, whose evidence spans are quoted from the scrubbed narrative.

**Two different markers, two different facts.** The per-record *anonymisation
marking* (*anonymised column*, *anonymisation unknown*, …) says where a
narrative came from, and what the supplier has said about it. The *scrub
marker* (`scrubbed · rules v3`, or `NOT SCRUBBED`) says what RA2 did to it at
freeze. A record can carry both.

---

## 2. What you can configure

| Where | What | Notes |
|---|---|---|
| **Scrubbing** screen, *Rule set* card | Import or remove the four files: a rule file, first names, last names, a whitelist | Each import or removal makes a new version (§3.1) |
| *Regex rules* card | Read every rule that runs: mandatory first, then yours, with patterns and examples | Read-only |
| *Name lists* card | Search the active lists the way the scrubber compares (`müll` finds `Müller` and `Mueller`) | Read-only |
| *Protected strings* card | Read the strings no rule may change | Extendable from the rule file (§4.1), never reducible |
| *Try a sentence* card | Scrub one sentence with the active rules | Stored nowhere, logged nowhere |
| *Versions* card | Every version, its files, and how many corpora it scrubbed | Read-only |
| **Import** screen, *Preview scrubbing* | What a freeze of the selected files would replace, per rule, before anything is written | Its *Create corpus with these rules* freezes with exactly the version shown |
| **Import** screen, *Corpora* table | `scrubbed · rules v3` or `NOT SCRUBBED` under each corpus; hover for the counts | |
| **Import** screen, file report | The 20-line raw preview, shown scrubbed with the active rules | So the screen shows no name the corpus would not |
| **Results** and **Mismatches** | The scrub marker beside the run's other pills | Required on every result |

### 2.1 The mandatory rules

Three rules run on **every** freeze, whether or not anything was imported.
They are part of the code, not data: you cannot remove them, change them, or
reuse their ids.

| Rule id | Placeholder | Matches | Never matches |
|---|---|---|---|
| `license-plate` | `<LicensePlate_n>` | a canton code in capitals, optionally a space or hyphen, then one to six digits not starting with 0, optionally grouped `123 456` or `123'456`: `BE 123456`, `ZH 1234`, `VD-123 456`, `AG 12 345`, `SG 12'345` | a canton named in a sentence (`im Kanton ZH 2 Verletzte`, `le canton VD 3 blessés`, `Kt. BE 4`), lower-case words (`il ne 12 pas`), `B1`, `A1`, `Km 12.5` |
| `phone` | `<Phone_n>` | `0` and a two-digit code, then seven digits with optional single separators (space, `.`, `-`, `/`), or `+41` / `0041` with an optional `(0)`: `079 123 45 67`, `+41 (0)44 123 45 67`, `0791234567`, `044/123 45 67` | short numbers, which are information rather than personal data (`117`, `144`, `1414`); times; dates; AHV numbers |
| `email` | `<Email_n>` | `local@domain.tld`, with a top-level part of at least two letters | `B1@`, a lone `@`, `a@b` |

**These patterns are provisional.** They were written to the contract in
`plan-text-scrubbing.md` §4 and are to be replaced by the patterns the project
owner supplies. A supplied pattern goes in only if it passes the same examples
(`tests/unit/scrub/test_mandatory.py`).

### 2.2 What you cannot configure

These are fixed in the code, so every corpus is scrubbed by the same algorithm.
They are part of the fingerprint every corpus records:

| Setting | Value | Why |
|---|---|---|
| Minimum letters in a list entry | 3 | `Le`, `Da` and `Li` are surnames and French articles |
| Honorifics that lift the whitelist | `Herr`, `Frau`, `Hr.`, `Fr.`, `M.`, `Mme`, `Mlle`, `Monsieur`, `Madame`, `Signor`, `Signora`, `Sig.`, `Sig.ra` | §3.4 |
| Built-in protected strings | `B1`, `G1`, `P`, `B1 kollidierte mit G1`, `80 km/h`, `um 14.30 Uhr`, `um 07.45 Uhr`, `A1`, `N1`, `Hauptstrasse 12`, `Km 12.5`, `Rega 1414`, `Notruf 117`, `Notruf 144`, `im Kanton ZH 2 Verletzte` | The role codes, speeds, times, roads and numbers extraction depends on |
| Time budget per rule per narrative, at freeze | 2 s | §3.6 |
| Time budget per rule at import | 0.25 s over each of four 4 096-character test strings | §3.6 |
| Floor of the most-hit table | 10 hits | A rarer entry is not named, so the table cannot reveal that a rare name occurs |

---

## 3. How it works

### 3.1 Importing builds a version

A **rule set** has up to four files: one rule file, one first-name list, one
last-name list and one whitelist.

1. You import one file, of one kind, on the Scrubbing screen.
2. RA2 reads it (§4), then **checks it together with** the mandatory rules and
   the other files of the active rule set. A file that is fine on its own can
   still be refused in combination: a surname list containing `Rega` turns the
   protected `Rega 1414` into a person.
3. Refused: a dialog lists every reason (§4.4), and **nothing changes**.
4. Accepted: a new version is made, equal to the active one with this kind of
   file swapped in. **The highest version is the active one.**

Removing a file makes a version without it, checked the same way: removing the
whitelist that resolves a collision is refused. Importing the file that is
already active for its kind changes nothing. A version is never edited, so to
go back, import the older file again.

### 3.2 Freezing scrubs, once

When a corpus is frozen (*Create corpus*, or *Create corpus with these rules*
from the preview), for every record:

1. The narrative is chosen as before: the text file's, or the
   `UnfHergangTextAnonym` column when the text file has none.
2. **Language detection and the cp1252 canary read the original**, in memory.
   A scrubbed name takes letters with it, and the canary exists to count lost
   characters.
3. The narrative is scrubbed, and so is the `UnfHergangTextAnonym` cell. When
   that cell *is* the narrative, it is scrubbed once and counted once.
4. **Only the scrubbed text is stored.** The original stays in the delivery
   files on disk and nowhere else.

The corpus records the rule-set version, a fingerprint of everything that ran,
and a copy of the mandatory rules as they were. The import report gets one line
per rule (`TEXT_SCRUBBED`), zero-hit rules included: placeholder, how many
spans were replaced, and in how many records. It never contains a matched text.

**An existing corpus is never re-scrubbed.** A new rule set applies to the next
freeze; to scrub a corpus with it, freeze its delivery again, which makes a new
corpus version. A corpus frozen before scrubbing existed is marked
`NOT SCRUBBED`.

### 3.3 One pass over the narrative

1. Every rule looks at the **original** narrative: the mandatory rules, then
   your rules in file order, then the name lists.
2. When two matches overlap, **a regex beats a name**. Between regex matches,
   the one that starts first wins, then the longer one, then the rule listed
   first.
3. The winners are numbered (§3.5) and replaced in one go.

So the same narrative and rules always give the same result, a placeholder is
never matched again by a later rule, scrubbing a scrubbed text changes nothing,
and every character outside a replaced span is exactly as delivered.

### 3.4 How names match

- **Whole words only.** `Müllerstrasse` and `Weberei` are never touched.
- **Any case, any accents.** `Müller`, `MÜLLER`, `Muller` and `Mueller` match an
  entry spelt any one of those ways, and so does a `Müller` written with a
  combining accent.
- **Several words.** `von Allmen`, `D'Alessandro` and `Marie-Claire` match as
  one name, also when a line break falls between the words. A double name of two
  listed names, `Meier-Müller`, becomes two placeholders.
- **The whitelist** holds words that are names but also ordinary words: `Fuchs`
  (fox), `Weiss` (white), `Koch`, `Bach`. A whitelisted word is never replaced
  as a name, **unless an honorific stands right before it** (§2.2): `Herr Fuchs`
  loses his name, `ein Fuchs querte` keeps its fox. An honorific never makes a
  word that is on no list into a name.
- **On both lists** (`Martin`, `Simon`): a first name when a surname follows, a
  surname when a first name precedes it, otherwise whatever the same name was
  earlier in the narrative, and only failing all three `<Name_n>`.

### 3.5 Numbering

Numbers count per placeholder, per narrative, in order of first appearance.
**The same value gets the same number**, so the narrative keeps its internal
references the way `B1` and `G1` do:

- a name is the same value however it is spelt (`Müller` … `MUELLER`);
- a regex match is the same value without its spaces and `- . / ( )`, so
  `079 123 45 67` and `0791234567` are one `<Phone_1>`.

Numbers start again at 1 in every narrative and mean nothing across records.

### 3.6 When a rule takes too long

A badly written pattern can take minutes on the wrong input. RA2 guards against
it twice:

- **At import**, every pattern is timed on four 4 096-character test strings;
  one that takes longer than 0.25 s on any of them is refused
  (`pattern_too_slow`).
- **At freeze**, every rule gets 2 s per narrative. A rule that runs over
  **stops the freeze, and nothing is written** (`TEXT_SCRUB_TIMEOUT`, naming the
  rule and the record's key). RA2 never skips the narrative or stores it
  unscrubbed. *Preview scrubbing* names the rule in advance instead of failing.

### 3.7 Performance

About 0.3 ms per narrative with a 50 000-entry surname list, so roughly 15 s
added to the freeze of a 50 000-record corpus, and the same for its preview. A
longer list compiles longer but scrubs at the same speed
([`performance.md`](performance.md) §8).

---

## 4. File formats

All files are **UTF-8**. Anything else is refused (`not_utf8`), never guessed.
A byte-order mark and Windows line endings are accepted and reported.

**Never commit a list to the repository.** The name lists are public data, but
they are the analyst's working copy: keep them outside the checkout, or in a
folder named `scrub-lists/`, which git ignores, as it ignores `*.names.txt`.

### 4.1 The rule file (TOML)

```toml
# Optional, once per file: strings the WHOLE rule set must leave untouched,
# on top of the built-in protected strings (§2.2).
protected = ["Tempo 80", "am Vortag"]

[[rule]]
id = "iban-ch"                       # required
tag = "IBAN"                         # required, becomes <IBAN_1>, <IBAN_2>, ...
description = "Swiss IBAN, grouped or not."               # optional
pattern = '(?<![0-9A-Z])CH\d{2}(?: ?[0-9A-Z]{4}){4} ?[0-9A-Z](?![0-9A-Z])'
must_match = ["CH93 0076 2011 6238 5295 7", "CH9300762011623852957"]
must_not_match = ["CH93", "Km 123.4"]                     # optional
```

| Field | Required | Rule |
|---|---|---|
| `id` | yes | Lower-case letters, digits and hyphens, starting with a letter or digit, at most 64 characters. Unique, and not a mandatory rule's (`license-plate`, `phone`, `email`) or a name list's (`firstnames`, `lastnames`, `both-lists`) |
| `tag` | yes | One capital letter, then 1 to 31 letters: `IBAN`, `AHV`, `Date`. Not `Firstname`, `Lastname` or `Name`, which belong to the name lists |
| `pattern` | yes | A regular expression (§4.2) |
| `must_match` | yes, at least one | Each example must be matched **whole** by this rule |
| `must_not_match` | no | Each example must not be matched **anywhere** by this rule |
| `description` | no | Shown on the Scrubbing screen. Changes nothing |
| `protected` (top level) | no | Added to the protected strings for the whole rule set |

**No other field is accepted.** A misspelt `must_not_macth` is refused rather
than ignored, so it cannot quietly drop the examples it was meant to carry.

**Examples are local, protected strings are global.** `must_not_match` asks only
*this* rule to leave a string alone: the phone rule's counter-example
`756.1234.5678.97` is exactly what the AHV rule exists to replace. A protected
string must survive the **whole** rule set, which is what catches a date rule
that eats `um 07.45 Uhr`.

**Use single quotes** for patterns: in a TOML literal string a backslash is a
backslash, so `\d` stays `\d`. In double quotes it would need to be `\\d`.

### 4.2 Writing patterns

- The engine is the Python package `regex`, in its `re`-compatible mode. If a
  pattern works in Python's `re`, it works here.
- Unicode classes are available: `\p{L}` is any letter, `\p{M}` any combining
  mark.
- **Case matters** unless the pattern says otherwise: start it with `(?i)` to
  ignore case.
- **Fence your matches.** Without `(?<!\d)` and `(?!\d)` around a number, a
  pattern for a 4-digit postcode also matches inside a phone number.
- A pattern that can match nothing at all (`\d*`, `x?`, a bare lookahead) is
  refused (`pattern_empty_match`).
- Avoid nested repetition of overlapping alternatives, such as `(a|aa)+$`: it is
  what makes a pattern slow (§3.6).
- Before importing, try the pattern on real-looking sentences with *Try a
  sentence*, and on a delivery with *Preview scrubbing*.

### 4.3 Name lists and the whitelist

Plain text, one entry per line:

```text
# Nachnamen, Stand 2026-10
Müller
Meier
von Allmen
D'Alessandro
Brunner
```

| What | Treated as | Reported as |
|---|---|---|
| A line starting with `#` | A comment, skipped | `comment_lines` |
| An empty line | Skipped | `blank_lines` |
| Spaces around an entry | Ignored | — |
| An entry with several words (`von Allmen`) | One name, matched as a whole | — |
| A second spelling of an entry already listed (`Müller`, then `MÜLLER` or `Mueller`) | Skipped: it is the same name to the scrubber | `duplicates` |
| An entry with fewer than 3 letters (`Li`, `Le`) | Skipped | `too_short` |
| An entry with no letters (`123`) | Skipped | `no_letters` |
| A byte-order mark, Windows line endings | Accepted | `bom`, `crlf` |
| A list with no usable entry left | **Refused** | `list_empty` |

Every skip is counted and shown on the Scrubbing screen under the file, with up
to five of the entries affected. Nothing is dropped silently.

The whitelist has the same format. Its entries never become placeholders as
names (§3.4).

### 4.4 Why an import is refused

| Code | Meaning |
|---|---|
| `not_utf8` | The file is not UTF-8 |
| `toml_invalid` | The rule file is not valid TOML |
| `unknown_field` | A field a rule file may not have (often a typo) |
| `field_missing` | `id`, `tag`, `pattern` or `must_match` is missing |
| `field_invalid` | A field has the wrong type: a number for a string, a string for a list |
| `id_malformed` | The id is not lower-case letters, digits and hyphens |
| `duplicate_id` | Two rules share an id |
| `id_reserved` | The id belongs to a mandatory rule or a name list |
| `tag_malformed` | The tag is not one capitalised word of letters |
| `tag_reserved` | `Firstname`, `Lastname` and `Name` are the name lists' |
| `pattern_invalid` | The pattern does not compile |
| `pattern_empty_match` | The pattern can match nothing at all |
| `pattern_too_slow` | The pattern takes too long on hard input (§3.6) |
| `no_must_match` | A rule has no `must_match` example |
| `must_match_failed` | An example is not matched whole by its rule |
| `must_not_match_hit` | A counter-example is matched by its rule |
| `protected_altered` | The rule set would change a protected string; the dialog names the string and what it would become |
| `list_empty` | A name list has no usable entry |

A `protected_altered` caused by a name list is resolved with the whitelist:
add the word there, then import the list again.

---

## 5. Examples

### 5.1 A sentence, before and after

With the mandatory rules, the rule file of §4.1 extended by an AHV and a date
rule, and the lists `Hans`, `Anna`, `Jörg`, `Martin`, `Simon` (first names),
`Müller`, `Meier`, `Fuchs`, `Martin`, `Simon`, `von Allmen` (last names) and
`Fuchs`, `Weiss` (whitelist). `Martin` and `Simon` are on both name lists:

| Before | After |
|---|---|
| `Am 12.03.2024 rief Jörg Müller (079 123 45 67, hans@example.ch, AHV 756.1234.5678.97, IBAN CH93 0076 2011 6238 5295 7) wegen BE 123456 an.` | `Am <Date_1> rief <Firstname_1> <Lastname_1> (<Phone_1>, <Email_1>, AHV <AHV_1>, IBAN <IBAN_1>) wegen <LicensePlate_1> an.` |
| `Hans Müller sprach mit Anna Müller.` | `<Firstname_1> <Lastname_1> sprach mit <Firstname_2> <Lastname_1>.` |
| `Er rief 079 123 45 67 an, dann nochmals 0791234567.` | `Er rief <Phone_1> an, dann nochmals <Phone_1>.` |
| `Herr Müller, später MUELLER.` | `Herr <Lastname_1>, später <Lastname_1>.` |
| `Ein Fuchs querte die Fahrbahn.` | unchanged: whitelisted, no honorific |
| `Herr Fuchs bremste.` | `Herr <Lastname_1> bremste.` |
| `Martin Simon kam. Martin rief.` | `<Firstname_1> <Lastname_1> kam. <Firstname_1> rief.` |
| `Martin kam zu spät.` | `<Name_1> kam zu spät.` |
| `Frau von Allmen bremste.` | `Frau <Lastname_1> bremste.` |
| `ZH 079 123 45 67` | `ZH <Phone_1>`: no plate starts with 0 |
| `Im Kanton ZH 2 Verletzte, im canton VD 3 blessés.` | unchanged: a canton named in a sentence |
| `Notruf 117 alarmiert, die Rega 1414 flog. B1 fuhr auf G1 auf.` | unchanged: short numbers and role codes |
| `Unfall an der Müllerstrasse.` | unchanged: whole words only |
| `Meiers Auto` | unchanged: **a known miss** (§1) |

### 5.2 A date rule, and why to think twice

```toml
[[rule]]
id = "date"
tag = "Date"
description = "A date with a year, or with a German or French month name."
pattern = '(?<!\d)(?:0?[1-9]|[12]\d|3[01])\.(?:0?[1-9]|1[0-2])\.(?:\d{4}|\d{2})(?!\d)'
must_match = ["12.03.2024", "12.3.24"]
must_not_match = ["um 07.45 Uhr", "12.03", "Km 12.5"]
```

`12.03` on its own is left alone on purpose: it is as likely a time as a date.

**A date rule replaces every date in a narrative, including the accident's.**
An evaluation that extracts a date from the text (`UnfDatumFeld`, for example)
then gives the model `<Date_1>` to read, and the model can only answer null.
Decide which dates you mean to scrub (a birth date, say) and write the pattern
for those, or evaluate date features on a corpus frozen with a rule set that
has no date rule. The development seed imports no rule file for exactly this
reason ([`seed.md`](seed.md)).

### 5.3 What the preview shows

*Preview scrubbing* on a three-record delivery, with the rule set above:

| Placeholder | Rule | Replaced | Records |
|---|---|---|---|
| `<LicensePlate_n>` | license-plate · mandatory | 3 | 2 |
| `<Phone_n>` | phone · mandatory | 3 | 2 |
| `<Email_n>` | email · mandatory | 1 | 1 |
| `<IBAN_n>` | iban-ch · imported | 0 | 0 |
| `<AHV_n>` | ahv · imported | 0 | 0 |
| `<Date_n>` | date · imported | 0 | 0 |
| `<Firstname_n>` | firstnames · list | 1 | 1 |
| `<Lastname_n>` | lastnames · list | 5 | 3 |
| `<Name_n>` | both-lists · list | 0 | 0 |

followed by *3 of 3 records would have something replaced*, and the **most-hit
list entries**. On a real delivery that table is the fastest way to find
whitelist candidates: `weiss 233 · koch 61` is a colour and a profession long
before it is two people. Add them to the whitelist, import it, and preview
again.

### 5.4 A refusal

Importing a rule that treats every `dd.dd` as a time:

```toml
[[rule]]
id = "time"
tag = "Time"
pattern = '\d{2}\.\d{2}'
must_match = ["14.30"]
```

is refused with `protected_altered` twice: the rule set would turn the
protected `um 14.30 Uhr` into `um <Time_1> Uhr`, and `um 07.45 Uhr` likewise.
Times are what extraction reads.

---

## 6. Where to look next

- **The design**: `sw-design.md` §19 and decisions `SD62`–`SD66`; the plan it was
  built from, with every decision taken: `plan-text-scrubbing.md`.
- **The risk**: `docs/risk-assesment.md` B7, *personal data survives scrubbing*.
- **The examples above are tests**: `tests/unit/scrub/test_scrubber.py`,
  `test_mandatory.py` and `test_check_rules.py`; the fixture files they use are
  in `tests/fixtures/scrub/hazards/`, invented and safe to read.
- **The API**, for scripts: `GET /api/v1/scrub/active`,
  `POST /api/v1/scrub/lists/{kind}`, `DELETE /api/v1/scrub/lists/{kind}`,
  `GET /api/v1/scrub/lists/{kind}/entries`, `POST /api/v1/scrub/try`,
  `GET /api/v1/scrub/preview?delivery_id=…`, `GET /api/v1/scrub/versions`.

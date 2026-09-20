# The Development Seed — RA2

**What `just reset-seed` puts in the database, and what a run over it should
produce.**

`scripts/seed_dev.py` builds a small, deliberately imperfect corpus and the
configuration needed to evaluate it. This page is reference material for
reading the result: it records what the corpus contains, which hazards are in
it on purpose, and the score a *perfect reader* could reach — so that a
surprising number can be attributed to the model, the prompt or the pipeline
rather than guessed at.

**This page is not authority.** `mvp-spec.md` decides *what*, `sw-design.md`
decides *how*, and where either disagrees with this page, this page is wrong.
Everything below is derived from the script, not remembered: regenerate it by
running the seed rather than by editing the numbers here.

**Last reviewed:** 2026-09-20 · against commit `00e0f55`.

---

## 1. Running it

```
just reset-seed yes                    # 48 records, the default
just reset-seed yes --records 200      # a corpus a launch will not call a smoke test
```

`reset-seed` **wipes `RA2_DATA_DIR`** and migrates it back before seeding. The
seed stops at the prompt template: picking models and pressing Launch stays a
deliberate act, and nothing in the script contacts the LLM endpoint.

Every byte is synthetic. Only the *column names* come from
`ra2.domain.parsing.headers`; every value is invented in the script. Real data
is gitignored and never reaches the seed (Do-NOT #11).

Nothing is random. The language plan and the case plan are fixed cycles of
co-prime length, so a given `--records` always produces identical bytes, and
re-running the seed is a check rather than a new sample.

### Size and the three thresholds

| Setting | Default | What it decides |
|---|---|---|
| `RA2_DEV_RECORD_MAX` | 50 | at or above, the corpus stops being marked dev-sized |
| `RA2_EVAL_RECORD_MIN` | 200 | below, a launch is marked "smoke test, not a result" |
| `RA2_MIN_CELL_COUNT` | 20 | below, a Results cell renders as "insufficient data" |

`--records` defaults to **48**: under `RA2_DEV_RECORD_MAX`, so the dev-sized
banner still shows, and large enough that at the default floor a feature's
all-languages row and its `de` row clear it while `fr`, `it`, `mixed` and `und`
do not. Both states on one screen is worth more than either alone.

The minimum is **15**, derived from the case plan rather than written down: the
three tail records and the orphan-code record overwrite four plan slots, so a
shorter corpus silently omits whichever cases fall at the end of the cycle.
`--records 14` is refused with exit code 2.

---

## 2. The delivery

Four files, written UTF-8 with CRLF line endings, `|` delimited except the
text file, which uses `;`.

| File | Kind | Columns | Rows at `--records 48` |
|---|---|---|---|
| `unfall.txt` | `unfall` | 67 | 48 |
| `objekt.txt` | `objekt` | 77 | 111 |
| `person.txt` | `person` | 18 | 48 |
| `text.csv` | `text` | 2 | 47 |

`person` hangs off `objekt`, never off `unfall` (mvp-spec.md §4.1), and the
person rows are spread across their accident's objects rather than pinned to
the first one. `text.csv` is one row short of the record count because one
accident deliberately has no narrative.

Column values a feature does not read are shaped, not meaningful: `*Ausw` looks
like a code, `*Datum*` like `YYYYMMDD`, `*Feld` like a number. The census infers
its type hints from the shape, and the content is nonsense on purpose.

### Distribution at 48 records

| | |
|---|---|
| objects per accident | 1 × 4 · 2 × 31 · 3 × 7 · 4 × 6 |
| persons per accident | 0 × 16 · 1 × 16 · 2 × 16 |
| `PersSchaAusw` | `1` (unhurt) × 24 · `2` (light) × 16 · `3` (serious) × 8 |
| `UnfTypAusw` | `01` × 11 · `02` × 12 · `03` × 12 · `04` × 12 · `09` × 1 |
| driver on the phone | 16 |

The accident type and the vehicle count cycle at co-prime lengths (4 and 7) so
they are **not** correlated — otherwise a model could score the enum feature by
counting vehicles instead of by reading.

---

## 3. Languages

Planned 6 : 3 : 1, which is roughly the shape of the real corpus and
deliberately not an even split.

| | plan | detected by `lingua` |
|---|---|---|
| `de` | 29 | 28 |
| `fr` | 14 | 13 |
| `it` | 5 | 5 |
| `mixed` | — | 1 |
| `und` | — | 1 |

The two differences are the point: one record carries too little text to call
and lands on `mixed` rather than being forced to a winner (mvp-spec.md §4.5),
and one `unfall` row has no text row at all and lands on `und`. Detection
agrees with the plan on every other record.

### French arrives already damaged

The French narratives are written with `œ` and `’` intact and then run through
`_as_delivered`, which deletes exactly the character set `domain/canary.py`
counts. The result carries **zero** cp1252-only characters with accents fully
intact — the asymmetry that proves the upstream cp1252 → Latin-1 conversion
happened (mvp-spec.md §4.4). `manœuvre` arrives as `manuvre`, `l’arrière` as
`larrière`, while `é` and `è` survive.

The corpus's canary count is therefore **0**, and because the corpus contains
French, that zero is evidence rather than noise.

---

## 4. How a record is built

Every accident is told twice, from one `Scenario`: once as the structured
columns (`record_*` — the ground truth scoring compares against) and once as
the world the narrative describes (`told_*`). A narrative is rendered from the
`told_*` half, so text and columns cannot drift apart by accident — only where
a `Case` says they should.

```
de  Am 14. Januar 2025 um 07:45 kam es zu einer Auffahrkollision. Beteiligt
    waren zwei Fahrzeuge. Niemand wurde verletzt. Der Lenker war zum
    Zeitpunkt des Unfalls am Telefon.

fr  Le 14 janvier 2025 à 14:55, il y a eu une collision par larrière. Deux
    véhicules ont été impliqués. Personne na été blessé. Le conducteur
    téléphonait au moment de laccident.

it  Il 22 settembre 2025 alle 14:55, si è verificato uno scontro frontale.
    Sono coinvolti due veicoli. Nessuno è rimasto ferito.
```

The accident-type clause is **count-neutral** — "kam es zu einer
Auffahrkollision", not "two vehicles collided" — so the vehicle sentence is the
only place a count is stated and the only place a model should read one from.

Times are written `HH:MM` in all three languages rather than `07h45` or
`ore 7.45`: `matching._normalise_time` parses `HH:MM` and nothing else, so an
idiomatic French rendering would score a correctly-read time as `wrong` and the
seed would be teaching a bug that is not there.

### The cases

| Case | 48 | What it exists to produce |
|---|---|---|
| `AGREES` | 22 | narrative and record say the same thing — `HIT` |
| `CONTRADICTS` | 7 | narrative disagrees about one fact — `WRONG`, plus a mismatch row |
| `TIME_WITHIN_TOLERANCE` | 4 | narrative is 3 minutes out — a `HIT` the ±5 rule earns |
| `TIME_OUTSIDE_TOLERANCE` | 4 | narrative is 8 minutes out — `WRONG` |
| `SILENT` | 4 | narrative mentions no time and no type — `MISSING` |
| `EMPTY_SOURCE` | 4 | the column is blank: **not a labelled case** (§8.6), out of `n` |
| `ORPHAN_CODE` | 1 | the record's enum code is in no code table |
| `SHORT_NARRATIVE` | 1 | too little text to call — `language = mixed` |
| `NO_NARRATIVE` | 1 | an `unfall` row with no text row — `language = und` |

A `CONTRADICTS` record disagrees about **one** thing, rotating between the
vehicle count and type, the date, and the injury flag. A record contradicting
every column at once would be easy to spot and unlike anything in the delivery;
the rotation is what gives each labelled feature mismatches of its own.

The rotation is driven by a counter, not by `index % 3`. The case plan places
`CONTRADICTS` at a fixed residue, so any modular rotation off the index aliases
against it and every contradicting record disagrees about the same fact.

Worked example — `TIME_OUTSIDE_TOLERANCE` at index 6:

```
record UnfZeitFeld = 19:40
narrative           Am 14. Januar 2025 um 19:48 kam es zu einem Unfall beim
                    Abbiegen. Beteiligt waren zwei Fahrzeuge. …
```

A model that reads the narrative correctly answers `19:48`, which is 8 minutes
from the record and outside the ±5 tolerance. **The correct behaviour here is a
`wrong`**, and the mismatch row is the deliverable.

---

## 5. Import hazards

These are in the corpus on purpose. A clean fixture is not acceptable
(mvp-spec.md §15).

| Hazard | Where | Expected |
|---|---|---|
| declared-count mismatch | index `count - 3`: `AnzObjFeld` = 2, one `objekt` row | reported, non-blocking (§4.3) |
| all-empty column | `Witter0Ausw`, empty in every row | census 0 %, no denominator for any feature over it (§8.6) |
| French already lossy | every `fr` narrative | canary 0 with accents intact (§4.4) |
| unfall row with no text | index `count - 1` | `language = und` |
| undetectable language | index `count - 2` | `language = mixed`, confidence stored verbatim |
| orphan enum code | index 4: `UnfTypAusw` = `09` | §7's finding, carrying column, value and record key |
| enum label gap | code `04` has no `it` label | `PARTIAL` coverage, not an error, no fallback to another language |

The count-mismatch record is the most interesting one, because two labelled
features read it differently: `AnzObjFeld` says two and `objects_involved`
counts one. One scores `wrong` while the other scores `hit`, on the same record
from the same narrative.

---

## 6. The code table

`data/Codes/codes-2018.json` wins when it is present. On a clone without it —
`data/` is gitignored — the seed imports a code table it synthesises itself, so
an `enum` feature works everywhere:

| Attribute | Chapter | Codes |
|---|---|---|
| `UnfTypAusw` | `seed.1` | `01` Auffahren · `02` Frontalkollision · `03` Abbiegeunfall · `04` Schleudern |
| `PersSchaAusw` | `seed.2` | `1` unverletzt · `2` leicht verletzt · `3` schwer verletzt |

Both columns are mapped to their attribute. Code `04` carries `de` and `fr`
labels and no `it` one, which is `PARTIAL` coverage on the Codelists screen;
the attribute still has Italian labels overall, so an Italian-prompt evaluation
still launches.

---

## 7. The feature set

Seven features, frozen. Between them they cover five of the seven value types,
both matching-rule kinds that have ground truth, both scalar grains, and two of
the seven derivations.

| Key | Kind | Grain | Type | Rule | Source |
|---|---|---|---|---|---|
| `UnfZeitFeld` | labelled | accident | `time` | within ±5 min | `UnfZeitFeld` |
| `UnfDatumFeld` | labelled | accident | `date` | exact | `UnfDatumFeld` |
| `AnzObjFeld` | labelled | accident | `integer` | exact | `AnzObjFeld` |
| `UnfTypAusw` | labelled | accident | `enum` | exact | `UnfTypAusw` |
| `objects_involved` | labelled | derived | `integer` | exact | `count_objects()` |
| `anyone_injured` | labelled | derived | `boolean` | exact | `any_person_matches(PersSchaAusw in 2,3)` |
| `phone_use` | exploratory | accident | `free_text` | none | — |

`decimal` is the one scored type left out: the only decimal columns in the
vocabulary are blood-alcohol readings on `objekt`, and an `OBJECT`-grain
feature is captured, never scored (§8.2).

### The prompt carries a format contract

`render_feature_block` gives a labelled feature exactly one line,
`"{key} — {value_type}"`, and a labelled feature's `description` is **not
rendered into the prompt at all** (§10.2). The template is therefore the only
place that can say what a `date` looks like, and the seeded template says it:

```
  date      YYYYMMDD, digits only. 14 January 2025 is 20250114.
  time      HH:MM, 24-hour, the time by itself and never the date.
  integer   digits only.
  enum      one of the codes listed above, copied character for
            character and keeping any leading zero. …
  boolean   true or false.
```

**Do not remove these lines** without expecting the numbers to collapse.
Without them the models answer `14. Januar 2025` against a `20250114` record
and `14. Januar 2025 um 07:45` against an `07:45` one; `domain/matching.py`
parses `YYYYMMDD` and `HH:MM` and nothing else, so every one of those scores
`wrong` even though the narrative was read correctly. Measured on this corpus:
`UnfDatumFeld` scored 4 % and 16 % across two models that had read every date
right, and one model scored **0 %** on `UnfZeitFeld` having read every time
right.

---

## 8. Expected results

### The ceiling

A *perfect reader* — a model answering exactly what each narrative states and
nothing more — cannot score 100 %, because the seeded contradictions and silent
narratives are unrecoverable by design. Running the real `classify` and
`aggregate_goal1` over the scenarios gives the ceiling at `--records 48`:

| Feature | n | hit | wrong | missing | P | R | F1 |
|---|---|---|---|---|---|---|---|
| `UnfDatumFeld` | 48 | 44 | 2 | 2 | 95.7 % | 91.7 % | **93.6 %** |
| `anyone_injured` | 48 | 44 | 2 | 2 | 95.7 % | 91.7 % | **93.6 %** |
| `objects_involved` | 48 | 43 | 3 | 2 | 93.5 % | 89.6 % | **91.5 %** |
| `AnzObjFeld` | 48 | 42 | 4 | 2 | 91.3 % | 87.5 % | **89.4 %** |
| `UnfTypAusw` | 48 | 39 | 3 | 6 | 92.9 % | 81.2 % | **86.7 %** |
| `UnfZeitFeld` | 44 | 34 | 4 | 6 | 89.5 % | 77.3 % | **82.9 %** |

**macro-F1 ceiling: 89.6 %.** `UnfZeitFeld`'s n is 44 rather than 48 because
the four `EMPTY_SOURCE` records have no ground truth and leave the denominator
entirely (§8.6) — they are *not* counted as `MISSING`.

A run that beats these numbers is a bug. A run far below them is either the
model or the prompt, and §9 is how to tell which.

### Suppression

At `--records 48` with the floor at 20:

| Row | n | Rendered? |
|---|---|---|
| all languages (`*`) | 44–48 | yes |
| `de` | 25–28 | yes |
| `fr` | 12–13 | suppressed |
| `it` | 5 | suppressed |
| `mixed`, `und` | 1 each | suppressed |

At `--records 200`, `fr` clears the floor too (54–59) and `it` sits exactly on
it (18–20), which makes the boundary itself visible.

### A worked run

Two local models over the 48-record corpus, `full` size, serial. 96/96 records,
**zero parse failures, zero retries**; median latency 18.8 s and 66.9 s; about
78 minutes wall clock.

| Feature | ceiling | `qwen3.5:2b` | `qwen3.5:latest` |
|---|---|---|---|
| `UnfDatumFeld` | 93.6 % | 88.6 % | 79.5 % |
| `anyone_injured` | 93.6 % | 92.5 % | 86.4 % |
| `objects_involved` | 91.5 % | 90.3 % | 88.6 % |
| `AnzObjFeld` | 89.4 % | 88.2 % | 86.4 % |
| `UnfTypAusw` | 86.7 % | 42.2 % | 69.3 % |
| `UnfZeitFeld` | 82.9 % | 43.9 % | 73.7 % |
| **macro-F1** | **89.6 %** | 74.3 % | 80.6 % |

The verdict was a **tie**: the macro intervals [67.7–76.5] and [73.4–82.4]
overlap, so §11.5's rule fires and the ranking renders a tie rather than an
order, with one separating feature (`UnfZeitFeld`, Δ 0.298).

These are two particular models on one host and will not reproduce exactly.
The *shape* should: a corpus that separates on one or two features, ties on the
rest, and leaves both models several points below the ceiling.

### What the mismatch list should contain

The larger model produced **12 mismatch rows in total**, and they were exactly
the seeded perturbations — its four `UnfZeitFeld` rows were precisely the four
`TIME_OUTSIDE_TOLERANCE` records, each with the right evidence span, while the
four `+3 min` records were absent because the tolerance earned them:

```
record='19:40'  model='19:48'   evidence='um 19:48'
record='22:05'  model='22:13'   evidence='à 22:13'
record='07:45'  model='07:53'   evidence='um 07:53'
record='06:20'  model='06:28'   evidence='à 06:28'
```

**That is what a healthy run looks like**: every mismatch traceable to a case
the seed planted. The smaller model produced 53, of which 43 were format
confusion — answering `170317` or `202509221455` where `HH:MM` was asked for —
which is a finding about that model, not about the corpus.

---

## 9. Reading a surprising number

| Symptom | Most likely cause |
|---|---|
| every cell suppressed | `--records` too small for `RA2_MIN_CELL_COUNT` |
| one feature near 0 % across **all** models | a format the prompt does not specify; check the mismatch list's `model=` column against `domain/matching.py` |
| scores above the ceiling in §8 | a bug — the ground truth and the narrative have drifted |
| `n` smaller than the record count | correct for `UnfZeitFeld` (the `EMPTY_SOURCE` records); suspicious anywhere else |
| mismatches in features the seed never perturbs | the model, or the prompt |
| a feature missing from the Results table entirely | it was never scoreable — no `score` rows at all (§8.6) |
| high `parse_failures` | the answer schema, not the corpus |

The first question to ask of a low score is always **what did the model
actually answer** — the mismatch list carries the record value, the model value
and the evidence span side by side, and it distinguishes "read it wrong" from
"read it right and formatted it differently" immediately.

---

## 10. Extending it

- **Cycle lengths must stay co-prime.** The language plan is 10, the case plan
  11, the type codes 4, the object counts 7, times 7, dates 6. Two cycles of
  equal or multiple length lock together and correlate two things that should
  be independent.
- **`MIN_RECORDS` is derived** from the case plan length. Adding a case changes
  it automatically; hard-coding it would make it wrong.
- **A new hazard needs a row in §5 here and a line in the script's docstring.**
  A hazard nobody can name is indistinguishable from a defect.
- **Regenerate the numbers in §8** after any change to the scenarios, the
  features or the matching rules. They are computed, not authored, and a stale
  ceiling is worse than no ceiling.

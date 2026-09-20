#!/usr/bin/env python
"""`just reset-seed` — land on a *runnable evaluation*, not an empty database.

`reset_data.py` leaves a migrated, empty database, which is a state nobody can
do anything with: every screen in the app needs a corpus, and getting one means
six clicks and a delivery you have to find. This seeds one.

**It drives the services** — not raw SQL and not the ORM (§5). That is the
point of the script rather than an implementation detail:

- the seed cannot drift from the schema, because it goes through the same
  `DeliveryService.analyse` / `CorpusService.freeze` path the Import view does;
- it doubles as a smoke test of that path, on the real machine, with no test
  harness — a seed that fails is a defect in the import pipeline, and it says
  which step it failed on;
- nothing here is a second implementation of anything. `create_app(mount_ui=
  False)` builds the very same `Services` bundle the app serves from.

**Every byte it writes is synthetic.** The column *names* come from
`ra2.domain.parsing.headers` (as `tests/fixtures/deliveries/generate_hazards.py`
does, and for the same reason — a 67-column file stays 67 columns without
anyone counting); every value is invented here. Real data is gitignored, must
stay on the host, and must never be what a developer's seed leans on
(Do-NOT #11).

---

## The delivery is not clean, and neither is the *evaluation*

An earlier version of this script seeded a corpus whose narratives were three
fixed sentences repeated, whose one labelled column held the same constant on
every row, and which no narrative mentioned. A run over it produced twelve
`MISSING`s and a Results screen with every cell suppressed — a working import
and a hollow evaluation.

So the narratives are **generated from the same scenario the structured
columns are written from**, and then a fixed slice of records is perturbed on
purpose. `Case` is that slice, and `build_scenarios` is where the proportions
live. What each case exists to produce, once the model has read the narrative:

| Case | What scoring should make of it |
|---|---|
| `AGREES` | narrative and record say the same thing — `HIT` |
| `TIME_WITHIN_TOLERANCE` | narrative is 3 minutes out — a `HIT` the ±5 rule earns |
| `TIME_OUTSIDE_TOLERANCE` | narrative is 8 minutes out — `WRONG`, and a mismatch row |
| `CONTRADICTS` | narrative disagrees about one fact, rotating which — `WRONG` |
| `SILENT` | narrative mentions no time and no type — `MISSING` |
| `EMPTY_SOURCE` | the column is blank: **not a labelled case** (§8.6), out of `n` |
| `ORPHAN_CODE` | the record's enum code is in no code table (the §7 finding) |
| `SHORT_NARRATIVE` | too little text to call — aims at `language = mixed` (§4.5) |
| `NO_NARRATIVE` | an `unfall` row with no text row — `language = und` |

plus the two import hazards the seed has always carried: one record declaring
two objects and shipping one (a count mismatch, reported and non-blocking,
mvp-spec.md §4.3) and French written **as the delivery really arrives** — the
upstream cp1252 -> Latin-1 conversion has deleted `œ` and the curly apostrophe
while leaving `é` and `è` intact, which is the whole of §4.4.

A corpus that produced none of this would hide the things this app exists to
surface (mvp-spec.md §15).

## Size

`--records` defaults to 48: under `RA2_DEV_RECORD_MAX` (50), so the corpus is
still marked dev-sized and every screen still says "smoke test, not a result"
(mvp-spec.md §9) — and large enough that, at the default
`RA2_MIN_CELL_COUNT` of 20, a feature's all-languages row and its `de` row
clear the floor while `fr`, `it`, `mixed` and `und` stay suppressed. **Both
states visible** is worth more than either alone: a Results screen that is
entirely suppressed and one that is entirely populated each teach half of
§11.4.

`just reset-seed yes --records 200` reaches `RA2_EVAL_RECORD_MIN`, which is
the point a launch stops being marked a smoke test.

Nothing here is random — the language plan and the case plan are fixed
cycles of co-prime length, so a given `--records` always produces the same
bytes, and re-running the seed is a check rather than a new sample.

## What it does not do

It stops at the prompt template. Picking models and pressing Launch stays a
deliberate act: the seed never contacts the LLM endpoint.

Run after a reset: `just reset-seed yes`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from ra2.domain.canary import CP1252_ONLY_CHARS
from ra2.domain.delivery import FileKind, SourceKind
from ra2.domain.feature import (
    AnyPersonMatches,
    CountObjects,
    Filter,
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    Operator,
    ValueType,
)
from ra2.domain.ids import CorpusId, DeliveryId
from ra2.domain.parsing.headers import (
    CANONICAL_COLUMN_SETS,
    OBJEKT_KEY_COLUMN,
    PERSON_KEY_COLUMN,
    TEXT_KEY_COLUMN,
    TEXT_NARRATIVE_COLUMN,
    UNFALL_KEY_COLUMN,
)
from ra2.infra.config import Settings
from ra2.infra.idgen import Uuid7Factory
from ra2.infra.tasks import InlineTaskRunner
from ra2.main import create_app
from ra2.services.container import Services
from ra2.services.errors import ServiceError

#: `scripts/seed_dev.py` -> the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: The RADIS column vocabulary — index 0 of each kind's `ColumnSet`.
_RADIS: Final = {kind: sets[0] for kind, sets in CANONICAL_COLUMN_SETS.items()}

_CRLF: Final = "\r\n"
_STRUCTURED_DELIMITER: Final = "|"
_TEXT_DELIMITER: Final = ";"

#: How many accidents the seeded corpus holds, unless `--records` says
#: otherwise. See the module docstring: 48 is the largest round number still
#: under `RA2_DEV_RECORD_MAX`.
DEFAULT_RECORDS: Final = 48

#: At most this many `objekt` rows hang off one accident. Fixes the key
#: arithmetic in `delivery_files` and nothing else.
_MAX_OBJECTS: Final = 4


# ===========================================================================
# The scenario generator
#
# One `Scenario` is one accident, told twice: once as the structured columns
# (`record_*` — the ground truth scoring compares against) and once as the
# world the narrative describes (`told_*` — what a model reading the text can
# possibly know). `Case` is how far apart the two are allowed to drift.
# ===========================================================================


class Case(StrEnum):
    """The perturbation applied to one record. Values are stable identifiers,
    printed in the run summary so a developer can tell a bad model from a bad
    pipeline."""

    AGREES = "agrees"
    TIME_WITHIN_TOLERANCE = "time_within_tolerance"
    TIME_OUTSIDE_TOLERANCE = "time_outside_tolerance"
    CONTRADICTS = "contradicts"
    SILENT = "silent"
    EMPTY_SOURCE = "empty_source"
    ORPHAN_CODE = "orphan_code"
    SHORT_NARRATIVE = "short_narrative"
    NO_NARRATIVE = "no_narrative"


@dataclass(frozen=True, slots=True)
class Scenario:
    """One accident. `record_*` goes into the delivery's structured files;
    `told_*` is what the narrative is rendered from."""

    index: int
    case: Case
    language: str

    #: `None` writes an **empty** cell — `EMPTY_SOURCE`, and §8.6's exclusion.
    record_time: str | None
    record_date: str
    #: `AnzObjFeld`. Equal to `objekt_count` except on the count-mismatch
    #: record, which is the point of that record.
    declared_objects: int
    objekt_count: int
    record_type: str
    #: One `PersSchaAusw` code per person row, spread across the objects.
    person_severities: tuple[str, ...]

    #: `None` means the narrative does not mention it at all.
    told_time: str | None
    #: Always stated — every narrative carries a date. Equal to `record_date`
    #: unless this record is the one contradicting it.
    told_date: str
    told_objects: int | None
    told_type: str | None
    told_injured: bool | None
    told_phone: bool


#: 6 `de` : 3 `fr` : 1 `it`, roughly the shape of the real corpus, and
#: deliberately **not** an even split — per-language rows that all clear the
#: floor together teach nothing about §11.4's suppression.
_LANGUAGE_PLAN: Final = ("de", "de", "fr", "de", "de", "it", "de", "fr", "de", "fr")

#: Length 11 against the language plan's 10 — co-prime, so cases and
#: languages do not lock into the same pairing every cycle and `it` is not
#: always the same case.
#:
#: Five records in eleven agree outright. The rest are the reason the seed
#: exists: a corpus where everything agrees produces a Results screen of
#: 100 % and an empty mismatch list, and neither is a screen anyone can learn
#: to read.
_CASE_PLAN: Final = (
    Case.AGREES,
    Case.AGREES,
    Case.TIME_WITHIN_TOLERANCE,
    Case.AGREES,
    Case.CONTRADICTS,
    Case.AGREES,
    Case.TIME_OUTSIDE_TOLERANCE,
    Case.CONTRADICTS,
    Case.AGREES,
    Case.SILENT,
    Case.EMPTY_SOURCE,
)

#: How many facts a `CONTRADICTS` record may disagree about — one each, taken
#: in turn. See `_scenario`.
_CONTRADICTION_KINDS: Final = 3

#: The smallest corpus in which every `Case` actually occurs.
#:
#: The three tail records (the count mismatch and the two language edges)
#: overwrite the last three plan slots, and the orphan-code record overwrites
#: one more, so a corpus shorter than this silently omits whichever cases fall
#: at the end of the cycle: below this, `EMPTY_SOURCE` sits past the last
#: plan slot a short corpus reaches, and nothing exercises §8.6's exclusion.
#: Derived rather than written down, so editing `_CASE_PLAN` cannot make it
#: wrong.
MIN_RECORDS: Final = len(_CASE_PLAN) + 4

#: Invented times and dates, cycled. The two lengths are co-prime with each
#: other and with the plans above, so "the 07:45 record" is not also always
#: "the January record".
_TIMES: Final = ("07:45", "12:10", "17:30", "22:05", "06:20", "14:55", "19:40")
_DATES: Final = ("20250114", "20250203", "20250317", "20250628", "20251105", "20250922")

#: The accident-type codes the synthetic code table names.
_TYPE_CODES: Final = ("01", "02", "03", "04")

#: How many `objekt` rows an accident has, cycled. Length 7 against
#: `_TYPE_CODES`' 4 **on purpose**: with both cycling at the same length the
#: type and the vehicle count were perfectly correlated, and a model could
#: have scored `UnfTypAusw` by counting vehicles instead of by reading.
_OBJECT_COUNTS: Final = (2, 1, 3, 2, 4, 2, 1)

#: The types that need more than one vehicle to make sense. A rear-end
#: collision involving one car is not a hard case, it is a broken fixture.
_MULTI_VEHICLE_TYPES: Final = ("01", "02", "03")

#: `PersSchaAusw` codes, cycled — all three of them. A code the synthetic
#: table declares and no record uses would make the Codelists screen's usage
#: count wrong about its own corpus.
_SEVERITY_CYCLE: Final = ("1", "2", "1", "3", "2", "1")

#: A code **no** code table carries. mvp-spec.md §7's finding — "the column,
#: the value and the record key" — and, once an evaluation snapshots the code
#: table, a value outside the snapshot for scoring to be wrong about.
_ORPHAN_TYPE_CODE: Final = "09"

#: The `PersSchaAusw` codes that mean somebody was hurt. `"1"` — unhurt — is
#: deliberately **not** here: `any_person_matches` over these two is the
#: ground truth for `anyone_injured`, and it has to be a fact the narrative
#: states and a model can read back.
_INJURED_CODES: Final = ("2", "3")


def build_scenarios(count: int) -> tuple[Scenario, ...]:
    """`count` accidents, deterministically.

    Four records are placed by position rather than by the cycles, because
    each is a hazard there should be exactly *one* of:

    - index 4: the orphan enum code;
    - `count - 3`: the declared-count mismatch;
    - `count - 2`: too little text to detect a language;
    - `count - 1`: no narrative at all.

    Everything else follows `_CASE_PLAN` and `_LANGUAGE_PLAN`.
    """
    if count < MIN_RECORDS:
        raise ValueError(f"--records must be at least {MIN_RECORDS}, got {count}")
    orphan_index = 4
    mismatch_index = count - 3
    short_index = count - 2
    silent_index = count - 1

    scenarios: list[Scenario] = []
    contradictions = 0
    for index in range(count):
        if index == orphan_index:
            case = Case.ORPHAN_CODE
        elif index == short_index:
            case = Case.SHORT_NARRATIVE
        elif index == silent_index:
            case = Case.NO_NARRATIVE
        else:
            case = _CASE_PLAN[index % len(_CASE_PLAN)]
        # Counted, not derived from `index % 3`. The case plan places
        # `CONTRADICTS` at a fixed residue, so any modular rotation off the
        # index aliases against it and every contradicting record disagrees
        # about the same fact — which is how the first version of this shipped
        # a corpus whose date feature had no mismatches at all.
        contradiction = contradictions % _CONTRADICTION_KINDS
        if case is Case.CONTRADICTS:
            contradictions += 1
        scenarios.append(
            _scenario(
                index,
                case,
                declared_mismatch=index == mismatch_index,
                contradiction=contradiction,
            )
        )
    return tuple(scenarios)


def _scenario(index: int, case: Case, *, declared_mismatch: bool, contradiction: int) -> Scenario:
    """One accident's two halves, before and after the perturbation.

    :param contradiction: which fact a `CONTRADICTS` record disagrees about.
        Ignored by every other case.
    """
    language = _LANGUAGE_PLAN[index % len(_LANGUAGE_PLAN)]
    time = _TIMES[index % len(_TIMES)]
    date = _DATES[index % len(_DATES)]
    # Decided **before** the vehicle count, because the count depends on it.
    # Swapping the type inside the `match` below left the orphan-code record
    # describing four cars colliding with a deer.
    accident_type = (
        _ORPHAN_TYPE_CODE if case is Case.ORPHAN_CODE else _TYPE_CODES[index % len(_TYPE_CODES)]
    )
    objekt_count = _OBJECT_COUNTS[index % len(_OBJECT_COUNTS)]
    if accident_type in _MULTI_VEHICLE_TYPES:
        objekt_count = max(objekt_count, 2)
    elif accident_type == _ORPHAN_TYPE_CODE:
        # A collision with an animal involves one vehicle. The orphan-code
        # record is meant to be hard because its code is in no table, not
        # because its narrative describes four cars hitting a deer.
        objekt_count = 1
    severities = _severities(index)
    injured = any(code in _INJURED_CODES for code in severities)
    # Every third record has the driver on the phone. Nothing scores it —
    # `phone_use` is exploratory — but Goal 2's presence flag needs a feature
    # the narrative sometimes supports and sometimes does not.
    phone = index % 3 == 0

    record_time: str | None = time
    told_time: str | None = time
    told_date: str = date
    told_objects: int | None = objekt_count
    told_type: str | None = accident_type
    told_injured: bool | None = injured

    match case:
        case Case.TIME_WITHIN_TOLERANCE:
            told_time = _shift(time, 3)
        case Case.TIME_OUTSIDE_TOLERANCE:
            told_time = _shift(time, 8)
        case Case.CONTRADICTS:
            # The narrative disagrees with the record about **one** thing,
            # rotating which. A record that contradicted every column at once
            # would be easy to spot and unlike anything in the delivery; the
            # rotation is what gives each labelled feature a `wrong` of its
            # own, and so the mismatch list rows from more than one feature.
            match contradiction:
                case 0:
                    told_objects = objekt_count % _MAX_OBJECTS + 1
                    told_type = _TYPE_CODES[(index + 1) % len(_TYPE_CODES)]
                case 1:
                    told_date = _DATES[(index + 1) % len(_DATES)]
                case _:
                    told_injured = not injured
        case Case.SILENT:
            told_time = None
            told_type = None
        case Case.EMPTY_SOURCE:
            # The narrative still states the time. The *record* does not have
            # one, so there is no question to be right or wrong about and the
            # record leaves this feature's denominator entirely (§8.6).
            record_time = None
        case Case.SHORT_NARRATIVE | Case.NO_NARRATIVE:
            told_time = None
            told_objects = None
            told_type = None
        case Case.AGREES | Case.ORPHAN_CODE:
            # `ORPHAN_CODE` perturbs nothing: its narrative describes exactly
            # the accident the record holds. What makes it hard is that the
            # code the record holds is in no code table.
            pass

    return Scenario(
        index=index,
        case=case,
        language=language,
        record_time=record_time,
        record_date=date,
        declared_objects=objekt_count + 1 if declared_mismatch else objekt_count,
        objekt_count=objekt_count,
        record_type=accident_type,
        person_severities=severities,
        told_time=told_time,
        told_date=told_date,
        told_objects=told_objects,
        told_type=told_type,
        told_injured=None if case in (Case.SHORT_NARRATIVE, Case.NO_NARRATIVE) else told_injured,
        told_phone=phone and case not in (Case.SHORT_NARRATIVE, Case.NO_NARRATIVE),
    )


def _severities(index: int) -> tuple[str, ...]:
    """0, 1 or 2 person rows. **Zero is a value, not a gap**: a record with no
    person rows makes `any_person_matches` `false` and `count_persons` `"0"`,
    and both stay in the denominator (`domain/derivation.py`)."""
    count = index % 3
    return tuple(
        _SEVERITY_CYCLE[(index + offset) % len(_SEVERITY_CYCLE)] for offset in range(count)
    )


def _shift(time: str, minutes: int) -> str:
    """`HH:MM` plus `minutes`, wrapping at midnight."""
    hours, mins = (int(part) for part in time.split(":"))
    total = (hours * 60 + mins + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


# ===========================================================================
# Narratives
#
# Rendered from the `told_*` half of a scenario, so the text and the columns
# cannot drift apart by accident — only where a `Case` says they should.
# ===========================================================================

#: Times are written `HH:MM` in all three languages rather than `07h45` /
#: `ore 7.45`. `matching._normalise_time` parses `HH:MM` and nothing else, so
#: an idiomatic French rendering would score a correctly-read time as `wrong`
#: and the seed would be teaching a bug that is not there. Swiss official
#: prose writes `07:45` in French too.
_MONTHS: Final = {
    "de": (
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ),
    "fr": (
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ),
    "it": (
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ),
}  # fmt: skip

#: **Count-neutral on purpose.** An earlier version said "two vehicles
#: collided head-on" and then a second sentence gave the real count, so a
#: narrative could state three vehicles and imply two. The type clause says
#: *what* happened; the vehicle sentence is the only place that says *how
#: many*, and it is the only place the model should read one from.
_TYPE_CLAUSES: Final = {
    "de": {
        "01": "kam es zu einer Auffahrkollision",
        "02": "kam es zu einer Frontalkollision",
        "03": "kam es zu einem Unfall beim Abbiegen",
        "04": "kam es auf nasser Fahrbahn zu einem Schleuderunfall",
        _ORPHAN_TYPE_CODE: "kam es zu einer Kollision mit einem Reh",
    },
    "fr": {
        "01": "il y a eu une collision par l’arrière",
        "02": "il y a eu une collision frontale",
        "03": "un accident s’est produit lors d’une manœuvre de changement de direction",
        "04": "un dérapage s’est produit sur une chaussée mouillée",
        _ORPHAN_TYPE_CODE: "il y a eu une collision avec un chevreuil",
    },
    "it": {
        "01": "si è verificato un tamponamento",
        "02": "si è verificato uno scontro frontale",
        "03": "si è verificato un incidente in svolta",
        "04": "si è verificato uno sbandamento sulla carreggiata bagnata",
        _ORPHAN_TYPE_CODE: "si è verificata una collisione con un capriolo",
    },
}

_VEHICLE_WORDS: Final = {
    "de": {1: "ein Fahrzeug", 2: "zwei Fahrzeuge", 3: "drei Fahrzeuge", 4: "vier Fahrzeuge"},
    "fr": {1: "un véhicule", 2: "deux véhicules", 3: "trois véhicules", 4: "quatre véhicules"},
    "it": {1: "un veicolo", 2: "due veicoli", 3: "tre veicoli", 4: "quattro veicoli"},
}

_INJURY_SENTENCES: Final = {
    "de": {True: "Es gab Verletzte.", False: "Niemand wurde verletzt."},
    "fr": {True: "Il y a eu des blessés.", False: "Personne n’a été blessé."},
    "it": {True: "Ci sono stati feriti.", False: "Nessuno è rimasto ferito."},
}

_PHONE_SENTENCES: Final = {
    "de": "Der Lenker war zum Zeitpunkt des Unfalls am Telefon.",
    "fr": "Le conducteur téléphonait au moment de l’accident.",
    "it": "Il conducente stava telefonando al momento dell'incidente.",
}

#: The `SHORT_NARRATIVE` record. One word per language and nothing else —
#: aiming at `Language.MIXED`, which mvp-spec.md §4.5 stores rather than
#: forcing to a winner. The detector decides; the point of the record is that
#: the pipeline has *something* to be unsure about.
_AMBIGUOUS_NARRATIVE: Final = "Unfall / accident / incidente."

#: The Windows-1252-only characters the upstream conversion to Latin-1 deletes
#: (mvp-spec.md §4.4), taken from `domain.canary` rather than written out
#: again: the set the seed damages French *with* has to be the set the canary
#: counts, or the seeded corpus would carry a canary figure its own text does
#: not justify.
#:
#: The French clauses above are written with `œ` and `’` **intact**;
#: `_as_delivered` removes them on the way into the file, so the seeded corpus
#: carries French damaged exactly the way the real delivery is — accents
#: present, cp1252-only characters gone, canary zero.
_CP1252_ONLY: Final = str.maketrans("", "", "".join(sorted(CP1252_ONLY_CHARS)))


def narrative(scenario: Scenario) -> str | None:
    """The text row for one accident, or `None` for no text row at all."""
    if scenario.case is Case.NO_NARRATIVE:
        return None
    if scenario.case is Case.SHORT_NARRATIVE:
        return _AMBIGUOUS_NARRATIVE
    language = scenario.language
    sentences = [_opening(scenario), _vehicles(scenario)]
    if scenario.told_injured is not None:
        sentences.append(_INJURY_SENTENCES[language][scenario.told_injured])
    if scenario.told_phone:
        sentences.append(_PHONE_SENTENCES[language])
    text = " ".join(sentence for sentence in sentences if sentence)
    return _as_delivered(text) if language == "fr" else text


def _opening(scenario: Scenario) -> str:
    """When it happened and what happened — the two clauses `SILENT` drops."""
    language = scenario.language
    when = _when(language, scenario.told_date, scenario.told_time)
    if scenario.told_type is None:
        # `SILENT`: no time, no type. Deliberately still a real sentence, so
        # the model has a narrative to read and returns `null` because the
        # answer is absent rather than because the prompt looks broken.
        return {
            "de": "Zum Hergang liegen keine näheren Angaben vor.",
            "fr": "Aucune précision n’est disponible sur le déroulement.",
            "it": "Non sono disponibili dettagli sulla dinamica.",
        }[language]
    clause = _TYPE_CLAUSES[language][scenario.told_type]
    if language == "de":
        return f"{when} {clause}."
    return f"{when}, {clause}."


def _when(language: str, date: str, time: str | None) -> str:
    """`Am 14. Januar 2025 um 07:45` and its two translations. A `None` time
    drops the clause rather than inventing one."""
    year, month, day = int(date[:4]), int(date[4:6]), int(date[6:])
    month_name = _MONTHS[language][month - 1]
    if language == "de":
        head = f"Am {day}. {month_name} {year}"
        return head if time is None else f"{head} um {time}"
    if language == "fr":
        head = f"Le {day} {month_name} {year}"
        return head if time is None else f"{head} à {time}"
    head = f"Il {day} {month_name} {year}"
    return head if time is None else f"{head} alle {time}"


def _vehicles(scenario: Scenario) -> str:
    """How many vehicles the narrative says were involved."""
    if scenario.told_objects is None:
        return ""
    count = scenario.told_objects
    word = _VEHICLE_WORDS[scenario.language][count]
    if scenario.language == "de":
        return f"Beteiligt {'war' if count == 1 else 'waren'} {word}."
    if scenario.language == "fr":
        verb = "a" if count == 1 else "ont"
        plural = "" if count == 1 else "s"
        return f"{word[0].upper()}{word[1:]} {verb} été impliqué{plural}."
    return f"{'È' if count == 1 else 'Sono'} coinvolt{'o' if count == 1 else 'i'} {word}."


def _as_delivered(text: str) -> str:
    """French, as it arrives: cp1252-only characters deleted, accents intact.

    `manœuvre` becomes `manuvre` and `l’arrière` becomes `larrière`, while `é`
    and `è` survive — the asymmetry that proves the conversion happened
    (mvp-spec.md §4.4). A French corpus with accents intact and **zero**
    cp1252-only characters is the signature; this is where the seed produces
    it instead of hard-coding one damaged sentence.
    """
    return text.translate(_CP1252_ONLY)


# ===========================================================================
# The delivery files
# ===========================================================================


def _uid(tag: str, number: int) -> str:
    """A 32-hex key — the shape the key-anchored recovery rule keys on."""
    return f"{tag}{number:0{32 - len(tag)}d}"


def _synthetic(column: str, index: int) -> str:
    """An invented value with the right *shape*.

    Shape matters because the census infers type hints from it (`Ausw` is a
    codelist, `Datum` is `YYYYMMDD`, `UnfZeitFeld` is `HH:MM`); content does
    not, and is nonsense on purpose. Every column a *feature* reads is
    overridden by the scenario before this value ever reaches the file.
    """
    if column.endswith("Uid"):
        return _uid("dd", index)
    if "Datum" in column or column.endswith("PruefungFeld") or column == "FahrzLetztePruefung":
        return "20250114"
    if column == "UnfZeitFeld":
        return "07:45"
    if column.endswith("Ausw"):
        return str(index % 9 + 1)
    if column.endswith("Feld"):
        return str(100 + index)
    if column.startswith("Ist"):
        return "0"
    return f"seed-{index}"


def _row(kind: FileKind, index: int, overrides: dict[str, str]) -> str:
    columns = _RADIS[kind].columns
    values = {c: _synthetic(c, index) for c in columns}
    values.update(overrides)
    return _STRUCTURED_DELIMITER.join(values[c] for c in columns)


def _table(kind: FileKind, rows: list[str]) -> str:
    header = _STRUCTURED_DELIMITER.join(_RADIS[kind].columns)
    return _CRLF.join([header, *rows]) + _CRLF


def delivery_files(scenarios: tuple[Scenario, ...]) -> dict[str, str]:
    """The four files of one small, deliberately imperfect delivery.

    `person` hangs off `objekt`, never off `unfall` (mvp-spec.md §4.1), so the
    person rows are spread across their accident's objects rather than pinned
    to the first one — otherwise `count_persons` and `any_person_matches`
    would be exercised over a tree the real delivery never has.
    """
    unfall_rows: list[str] = []
    objekt_rows: list[str] = []
    person_rows: list[str] = []
    text_rows: list[tuple[str, str]] = []

    for scenario in scenarios:
        index = scenario.index
        unfall_key = _uid("a1", index)
        injured = [code for code in scenario.person_severities if code in _INJURED_CODES]
        unfall_rows.append(
            _row(
                FileKind.UNFALL,
                index,
                {
                    UNFALL_KEY_COLUMN: unfall_key,
                    "KantonAusw": "380" if index % 2 else "381",
                    "AnzObjFeld": str(scenario.declared_objects),
                    "UnfTypAusw": scenario.record_type,
                    "UnfDatumFeld": scenario.record_date,
                    "UnfZeitFeld": scenario.record_time or "",
                    "BeteiligtePersTotalFeld": str(len(scenario.person_severities)),
                    "BeteiligtePersLeichtVerletztFeld": str(injured.count("2")),
                    "BeteiligtePersSchwVerletztFeld": str(injured.count("3")),
                    # An all-empty column: 0 % populated in the census, and no
                    # denominator for any feature over it (§8.6).
                    "Witter0Ausw": "",
                },
            )
        )
        for ordinal in range(scenario.objekt_count):
            objekt_index = index * _MAX_OBJECTS + ordinal
            objekt_key = _uid("b2", objekt_index)
            on_this_object = [
                code
                for position, code in enumerate(scenario.person_severities)
                if position % scenario.objekt_count == ordinal
            ]
            objekt_rows.append(
                _row(
                    FileKind.OBJEKT,
                    objekt_index,
                    {
                        OBJEKT_KEY_COLUMN: objekt_key,
                        UNFALL_KEY_COLUMN: unfall_key,
                        "ObjNrFeld": str(ordinal + 1),
                        "AnzPerFeld": str(len(on_this_object)),
                    },
                )
            )
            for position, code in enumerate(on_this_object):
                person_index = objekt_index * _MAX_OBJECTS + position
                person_rows.append(
                    _row(
                        FileKind.PERSON,
                        person_index,
                        {
                            PERSON_KEY_COLUMN: _uid("c3", person_index),
                            OBJEKT_KEY_COLUMN: objekt_key,
                            "PersNrFeld": str(position + 1),
                            "PersSchaAusw": code,
                        },
                    )
                )
        text = narrative(scenario)
        if text is not None:
            text_rows.append((unfall_key, text))

    header = _TEXT_DELIMITER.join((TEXT_KEY_COLUMN, TEXT_NARRATIVE_COLUMN))
    text_file = _CRLF.join([header, *(f"{k}{_TEXT_DELIMITER}{v}" for k, v in text_rows)]) + _CRLF
    return {
        "unfall.txt": _table(FileKind.UNFALL, unfall_rows),
        "objekt.txt": _table(FileKind.OBJEKT, objekt_rows),
        "person.txt": _table(FileKind.PERSON, person_rows),
        "text.csv": text_file,
    }


def write_delivery(root: Path, scenarios: tuple[Scenario, ...]) -> Path:
    """Write the files and return the directory they are in.

    `write_bytes` after an explicit `.encode("utf-8")`, not `write_text`:
    `.gitattributes` is `* -text` repository-wide (`SD33`), so whatever is
    written is what is stored, and text mode translates line endings on some
    platforms whatever `newline=` says. The delimiters above are explicit
    CRLF, and encoding at the call site keeps N4's "never without an explicit
    encoding" true of this path too.

    UTF-8 rather than cp1252 so the seeded corpus's canary count is the honest
    one for text that never went through the conversion — the French damage is
    in the *characters* (`_as_delivered`), not in the file's encoding.
    """
    root.mkdir(parents=True, exist_ok=True)
    for name, content in delivery_files(scenarios).items():
        (root / name).write_bytes(content.encode("utf-8"))
    return root


# ===========================================================================
# The synthetic code table
# ===========================================================================

#: A code table invented here, so an `enum` feature works on a clone that has
#: no `data/`. Two hazards on purpose, mirroring the `c0*` codelist fixtures:
#:
#: - `04` has **no `it` label**. One code short of complete is `PARTIAL`
#:   coverage on the Codelists screen, not an error, and not a fallback to
#:   another language (mvp-spec.md §7). The *attribute* still has Italian
#:   labels, so an Italian-prompt evaluation still launches.
#: - the corpus uses `09`, which is in no attribute at all — §7's finding,
#:   carrying the column, the value and the record key.
SYNTHETIC_CODELIST: Final = {
    "UnfTypAusw": {
        "chapter": "seed.1",
        "name": {"de": "Unfalltyp", "fr": "Type d'accident", "it": "Tipo di incidente"},
        "codes": {
            "01": {"de": "Auffahren", "fr": "Collision par l'arrière", "it": "Tamponamento"},
            "02": {"de": "Frontalkollision", "fr": "Collision frontale", "it": "Scontro frontale"},
            "03": {
                "de": "Abbiegeunfall",
                "fr": "Accident en tournant",
                "it": "Incidente in svolta",
            },
            "04": {"de": "Schleudern", "fr": "Dérapage"},
        },
    },
    "PersSchaAusw": {
        "chapter": "seed.2",
        "name": {"de": "Personenschaden", "fr": "Dommage corporel", "it": "Danno alle persone"},
        "codes": {
            "1": {"de": "unverletzt", "fr": "indemne", "it": "illeso"},
            "2": {"de": "leicht verletzt", "fr": "blessé léger", "it": "ferito lieve"},
            "3": {"de": "schwer verletzt", "fr": "blessé grave", "it": "ferito grave"},
        },
    },
}

#: The columns the seed maps to the attributes above. Both are `Ausw` columns,
#: so the census hints them `enum` and `map_column` finds a census row.
_MAPPED_COLUMNS: Final = ("UnfTypAusw", "PersSchaAusw")


# ===========================================================================
# Driving the services, in the order the app drives them
# ===========================================================================


async def seed(services: Services, *, delivery_root: Path, scenarios: tuple[Scenario, ...]) -> None:
    """Register, analyse, freeze, then configure. Each step prints what it
    produced, so a failure names the step rather than the script."""
    delivery_id = await services.delivery.register(
        "seed delivery", source_kind=SourceKind.HOST_PATH, root_path=delivery_root
    )
    print(f"  delivery {delivery_id} registered from {delivery_root}")

    await services.delivery.analyse(delivery_id)
    view = await services.delivery.get(delivery_id)
    for file in view.files:
        print(f"    {file.filename}: {file.file_kind} · {file.encoding} · {file.row_count} rows")

    corpus_id = await _freeze(services, delivery_id)
    if corpus_id is None:
        return
    corpus = await services.corpus.get(corpus_id)
    print(
        f"  corpus {corpus_id} · {corpus.record_count} records · "
        f"dev-sized={corpus.is_dev_sized} · cp1252 canary={corpus.cp1252_canary_count}"
    )

    await _import_codelists(services, corpus_id)
    await _seed_features(services, corpus_id)
    await _seed_prompt(services)
    _print_plan(scenarios)


async def _freeze(services: Services, delivery_id: DeliveryId) -> CorpusId | None:
    try:
        corpus_id = await services.corpus.freeze(delivery_id, name="seed corpus")
    except ServiceError as exc:
        # A blocked freeze is a **finding about the seed**, printed and not
        # swallowed: if this ever fails, the import pipeline changed and this
        # script is the cheapest place to have learned it (Do-NOT #6's spirit).
        print(f"  freeze refused: {exc}")
        return None
    return corpus_id


async def _import_codelists(services: Services, corpus_id: CorpusId) -> None:
    """Import a code table and map the two `Ausw` columns the features need.

    Real codelists win when `data/` has them — a developer with the real code
    tables should see the real labels. Without them the seed imports
    `SYNTHETIC_CODELIST` instead, because an `enum` feature that only exists
    on one machine is a feature the seed cannot claim to exercise.
    """
    source = REPO_ROOT / "data" / "Codes" / "codes-2018.json"
    if source.is_file():
        result = await services.codelist.import_file(source.name, source.read_bytes())
        print(f"  codelists imported from data/: {result.attribute_count} attributes")
    else:
        payload = json.dumps(SYNTHETIC_CODELIST, ensure_ascii=False, indent=2).encode("utf-8")
        result = await services.codelist.import_file("seed-codes.json", payload)
        print(f"  synthetic codelist imported: {result.attribute_count} attributes")

    by_key = {attribute.key: attribute for attribute in await services.codelist.list_attributes()}
    for column in _MAPPED_COLUMNS:
        attribute = by_key.get(column)
        if attribute is None:
            print(f"  {column} left unmapped: no attribute named it in the imported table")
            continue
        try:
            await services.codelist.map_column(corpus_id, column, attribute.code_attribute_id)
        except ServiceError as exc:
            print(f"  {column} left unmapped: {exc}")
            continue
        print(f"  {column} mapped to {attribute.key} · {attribute.code_count} codes")


async def _seed_features(services: Services, corpus_id: CorpusId) -> None:
    """Six labelled features and one exploratory one.

    Between them they cover five of the seven value types, both matching rule
    kinds that have ground truth, both scalar grains, and two of the seven
    derivations. `DECIMAL` is the one scored type left out: the only decimal
    columns in the vocabulary are blood-alcohol readings on `objekt`, and an
    `OBJECT`-grain feature is captured, never scored (mvp-spec.md §8.2).

    `AnzObjFeld` and `objects_involved` are deliberately **both** here. They
    agree on every record but the count-mismatch one, where the column says
    two and the objects say one — one labelled feature scoring `wrong` while
    another scores `hit` on the same record, from the same narrative.
    """
    config = await services.feature.create_draft(name="seed features")
    config_id = config.feature_config_id

    await services.feature.add_feature(
        config_id,
        key="UnfZeitFeld",
        kind=Kind.LABELLED,
        description="The time of the accident, as the narrative states it.",
        grain=Grain.ACCIDENT,
        source_column="UnfZeitFeld",
        derivation=None,
        value_type=ValueType.TIME,
        matching_rule=MatchingRule(kind=MatchingRuleKind.WITHIN_TOLERANCE, tolerance_minutes=5),
        validate_against=corpus_id,
    )
    await services.feature.add_feature(
        config_id,
        key="UnfDatumFeld",
        kind=Kind.LABELLED,
        description="The date of the accident, as the narrative states it.",
        grain=Grain.ACCIDENT,
        source_column="UnfDatumFeld",
        derivation=None,
        value_type=ValueType.DATE,
        matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
        validate_against=corpus_id,
    )
    await services.feature.add_feature(
        config_id,
        key="AnzObjFeld",
        kind=Kind.LABELLED,
        description="How many vehicles the narrative says were involved.",
        grain=Grain.ACCIDENT,
        source_column="AnzObjFeld",
        derivation=None,
        value_type=ValueType.INTEGER,
        matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
        validate_against=corpus_id,
    )
    await services.feature.add_feature(
        config_id,
        key="UnfTypAusw",
        kind=Kind.LABELLED,
        description="The kind of accident, as one of the codes offered.",
        grain=Grain.ACCIDENT,
        source_column="UnfTypAusw",
        derivation=None,
        value_type=ValueType.ENUM,
        matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
        validate_against=corpus_id,
    )
    await services.feature.add_feature(
        config_id,
        key="objects_involved",
        kind=Kind.LABELLED,
        description="How many vehicles were involved, counted from the narrative.",
        grain=Grain.DERIVED,
        source_column=None,
        derivation=CountObjects(),
        value_type=ValueType.INTEGER,
        matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
        validate_against=corpus_id,
    )
    await services.feature.add_feature(
        config_id,
        key="anyone_injured",
        kind=Kind.LABELLED,
        description="Whether the narrative says anybody was injured.",
        grain=Grain.DERIVED,
        source_column=None,
        derivation=AnyPersonMatches(
            filter=Filter(column="PersSchaAusw", operator=Operator.IN, value=_INJURED_CODES)
        ),
        value_type=ValueType.BOOLEAN,
        matching_rule=MatchingRule(kind=MatchingRuleKind.EXACT),
        validate_against=corpus_id,
    )
    await services.feature.add_feature(
        config_id,
        key="phone_use",
        kind=Kind.EXPLORATORY,
        description="An explicit mention that a driver was using a phone.",
        grain=Grain.ACCIDENT,
        source_column=None,
        derivation=None,
        value_type=ValueType.FREE_TEXT,
        matching_rule=MatchingRule(kind=MatchingRuleKind.NONE),
        validate_against=corpus_id,
    )

    try:
        frozen = await services.feature.freeze(config_id, validate_against=corpus_id)
    except ServiceError as exc:
        print(f"  feature set left as a draft: {exc}")
        return
    print(f"  feature set {frozen.feature_config_id} frozen · {len(frozen.features)} features")


async def _seed_prompt(services: Services) -> None:
    """The active template, and it **carries a format contract**.

    `render_feature_block` gives a labelled feature exactly one line,
    `"{key} — {value_type}"`, and a labelled feature's `description` is never
    rendered at all (mvp-spec.md §10.2). The template is therefore the only
    place that can say what a `date` *looks* like — and without it the models
    answer `"14. Januar 2025"` against a `YYYYMMDD` record, and
    `"14. Januar 2025 um 07:45"` against an `HH:MM` one. Both have read the
    narrative correctly; both score `wrong`, because `domain/matching.py`
    parses `YYYYMMDD` and `HH:MM` and nothing else.

    Measured on this corpus before the contract existed: `UnfDatumFeld`
    scored 4 % and 16 % across two models that had in fact read every date
    right, and `qwen3.5:2b` scored **0 %** on `UnfZeitFeld` having read every
    time right. A seed whose numbers blame the model for the prompt's
    omission teaches the opposite of what this app is for.
    """
    source = (
        "You extract structured facts from Swiss accident reports.\n\n"
        "Language: {{language}}\n\n"
        "Read the narrative below. For each feature, emit only the value the\n"
        "narrative supports, and quote the span it came from.\n\n"
        "{{feature_block}}\n\n"
        "Answer each feature in exactly the form its type takes, or null:\n\n"
        "  date      YYYYMMDD, digits only. 14 January 2025 is 20250114.\n"
        "  time      HH:MM, 24-hour, the time by itself and never the date.\n"
        "  integer   digits only.\n"
        "  enum      one of the codes listed above, copied character for\n"
        "            character and keeping any leading zero. Never the label,\n"
        "            never its position in the list.\n"
        "  boolean   true or false.\n\n"
        "A value the narrative does not state is null, never a guess.\n\n"
        "Answer as JSON only, one key per feature, no prose.\n\n"
        "--- narrative ---\n"
        "{{narrative}}\n"
    )
    template = await services.prompt.save_as_next_version(source)
    await services.prompt.activate(template.prompt_template_id)
    print(f"  prompt template v{template.version} saved and activated")


def _print_plan(scenarios: tuple[Scenario, ...]) -> None:
    """What the corpus is made of, so a surprising score can be read against
    what the seed meant to build. A run that scores worse than this table
    allows is the model; a run that cannot reach it is the pipeline."""
    by_case: dict[str, int] = {}
    by_language: dict[str, int] = {}
    for scenario in scenarios:
        by_case[scenario.case.value] = by_case.get(scenario.case.value, 0) + 1
        by_language[scenario.language] = by_language.get(scenario.language, 0) + 1
    print("  the plan this corpus was built to:")
    for case, count in sorted(by_case.items()):
        print(f"    {case:<24} {count:>4}")
    print("    " + " · ".join(f"{lang} {count}" for lang, count in sorted(by_language.items())))
    print("    (language counts are the plan, not the detector's answer)")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--records",
        type=int,
        default=DEFAULT_RECORDS,
        metavar="N",
        help=(
            f"how many accidents to seed (default {DEFAULT_RECORDS}, minimum {MIN_RECORDS}). "
            "Above RA2_DEV_RECORD_MAX the corpus stops being marked dev-sized."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        scenarios = build_scenarios(args.records)
    except ValueError as exc:
        print(f"seed refused: {exc}")
        return 2

    settings = Settings()
    # `InlineTaskRunner` rather than the app's `AsyncioTaskRunner`: analysis
    # runs through the `TaskRunner` seam, and a script has no UI to poll
    # `GET /api/v1/tasks/{id}` from. Inline is the same work on the same seam,
    # finished before `submit()` returns — a composition-root choice, not a
    # branch inside anything (Do-NOT #12).
    app = create_app(
        settings=settings, task_runner=InlineTaskRunner(Uuid7Factory()), mount_ui=False
    )
    services: Services = app.state.services

    print(f"RA2_DATA_DIR: {settings.data_dir}")
    delivery_root = write_delivery(settings.data_dir / "seed", scenarios)
    asyncio.run(seed(services, delivery_root=delivery_root, scenarios=scenarios))
    print("Seeded. Start the app with `just dev`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

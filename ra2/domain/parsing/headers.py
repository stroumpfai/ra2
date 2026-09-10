# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""The canonical column sets, and the header match that decides `FileKind`.

**The header is the only thing that decides what a file is** (SD5,
sw-design.md §12.5). Matching is case-insensitive and whitespace-trimmed
(mvp-spec.md §4.1).

Two structured-file vocabularies are recognised per `FileKind` — RADIS
(pipe-delimited, system-field-code names) and Astrana (comma/RFC4180,
German business-label names) — bundled as a `ColumnSet` each. The RADIS
sets (67 `unfall` / 77 `objekt` / 18 `person` columns) and the shared
two-column text header are taken from the headers of `data/RADIS-Export/
samples/*` as plan-m0-m5.md §5 (A1) directs; the Astrana sets (67 `unfall`
/ 76 `objekt` / 21 `person` columns) are taken from `data/ASTRANA-Export/
samples/*`. No data row, no value, and nothing derived from one, appears
here or in any committed fixture — `tests/unit/parsing/
test_headers_realdata.py` re-checks these names against the samples when
they are present on the host, and skips when they are not.

A delivery is a single format, never mixed (confirmed product decision) —
so `column_set` need not be persisted anywhere; it is resolved fresh from
each file's own header, same as `kind` is, and carried only as long as the
file is in memory during analysis/validation/freeze.

Two rules the matcher must never break:

1. An **empty** canonical set means "not yet known", not "no columns". Matching
   against one is refused, so a placeholder can never produce a false match.
2. The filename is never consulted. There is no parameter for it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from ra2.domain.delivery import FileKind

__all__ = [
    "CANONICAL_COLUMN_SETS",
    "HEADER_MATCH_THRESHOLD",
    "OBJEKT_KEY_COLUMN",
    "PERSON_KEY_COLUMN",
    "TEXT_KEY_COLUMN",
    "TEXT_NARRATIVE_COLUMN",
    "UNFALL_KEY_COLUMN",
    "ColumnSet",
    "HeaderMatch",
    "classify_header",
    "column_index",
    "match_header",
    "normalise_header",
]

#: `UnfallUid` in the RADIS structured files; the text file's header is
#: upper-case regardless of structured-file format (the narrative file is
#: shared/unchanged across formats).
UNFALL_KEY_COLUMN: Final = "UnfallUid"
TEXT_KEY_COLUMN: Final = "UNFALLUID"

#: The remaining RADIS primary keys, still used directly at a couple of call
#: sites (e.g. the never-varying text file).
OBJEKT_KEY_COLUMN: Final = "ObjektUid"
PERSON_KEY_COLUMN: Final = "PersonUid"
TEXT_NARRATIVE_COLUMN: Final = "HERGANG"

#: How much of a canonical set a header must cover before the file is called
#: that kind with a `HEADER_MISMATCH` rather than left `UNKNOWN`. Below this a
#: header is genuinely unrecognisable (h12) and the file is `UNKNOWN`.
HEADER_MATCH_THRESHOLD: Final = 0.6


@dataclass(frozen=True, slots=True)
class ColumnSet:
    """One known column vocabulary for a `FileKind` — RADIS or Astrana.

    The landmark fields are `None` where a format has no equivalent concept
    (e.g. neither format's `person`/`Mitfahrende` table has a canton or
    count column of its own — those only exist on `unfall`)."""

    columns: tuple[str, ...]
    key_column: str
    #: `unfall` only — where canton comes from (mvp-spec.md §4.1, SD §12.5).
    canton_column: str | None = None
    #: `unfall` only — cross-checked against the child `objekt`/`person` counts.
    obj_count_column: str | None = None
    pers_count_column: str | None = None
    #: `objekt`/`person` only — the delivered within-parent ordinal.
    ordinal_column: str | None = None
    #: `text` only.
    narrative_column: str | None = None


#: Column **names only**, from the sample headers. Order is the delivered
#: order, which is what `header_ok` compares against. Every `FileKind` maps
#: to a tuple of known `ColumnSet`s — RADIS first, then Astrana — so a
#: header is classified by kind *and* format in one pass.
CANONICAL_COLUMN_SETS: Final[dict[FileKind, tuple[ColumnSet, ...]]] = {
    FileKind.UNFALL: (
        ColumnSet(  # RADIS — 67 columns
            columns=(
                "UnfallUid",
                "GeoRefUid",
                "MandantNr",
                "UnfallStatus",
                "UnfallUnterStatus",
                "BfsGemNrNeuAusw",
                "AxisIdFeld",
                "AxisSegIdFeld",
                "AxisSegVersionIdFeld",
                "RbbsDateFeld",
                "DaQuAusw",
                "UnfNrFeld",
                "AnzObjFeld",
                "UnfTypAusw",
                "UnfDatumFeld",
                "UnfZeitFeld",
                "UnfTagAusw",
                "BetragFeld",
                "HauptUrsaAusw",
                "DienststelleFeld",
                "BeteiligtePersTotalFeld",
                "BeteiligtePersErheblichVerletztFeld",
                "BeteiligtePersLebensbVerletztFeld",
                "BeteiligtePersSchwVerletztFeld",
                "BeteiligtePersLeichtVerletztFeld",
                "BeteiligtePersTotFeld",
                "KantonAusw",
                "OrtschaftPlzFeld",
                "BfsGemNrAusw",
                "AutobBezFeld",
                "AutobKmFeld",
                "AutobRichtungFeld",
                "Koordinaten1Feld",
                "KoordinatenEFeld",
                "Koordinaten2Feld",
                "KoordinatenNFeld",
                "InnerAusserortsAusw",
                "EigentuemerFeld",
                "NameFeld",
                "BezPunktFeld",
                "DistFeld",
                "AbstFeld",
                "VssOhne",
                "VssOhneBegruendung",
                "OrtschaftFeld",
                "StrFeld",
                "HausNrFeld",
                "StrAbsFeld",
                "AzimutFeld",
                "StrArtAusw",
                "StrArt2Ausw",
                "VerBedAusw",
                "ZonSignAusw",
                "HoechstGeschwKmHFeld",
                "HoechstGeschwSignAusw",
                "HoechstGeschwWeitereFeld",
                "UnfStelle0Ausw",
                "UnfStelle1Ausw",
                "StrZu0Ausw",
                "Witter0Ausw",
                "Witter1Ausw",
                "VortrittAusw",
                "VortrittRegelZus",
                "LichtVerhAusw",
                "StrBelAusw",
                "UnfHergangTextAnonym",
                "UnfSkizzeAnonym",
            ),
            key_column="UnfallUid",
            canton_column="KantonAusw",
            obj_count_column="AnzObjFeld",
            pers_count_column="BeteiligtePersTotalFeld",
        ),
        ColumnSet(  # Astrana — 67 columns (data/ASTRANA-Export/samples/Unfall.csv)
            columns=(
                "Jahr",
                "Datum",
                "Unfall-UID",
                "Unfall-Nr",
                "Monat-Nr",
                "Wochentag-Nr",
                "Wochentag Kürzel",
                "Tages-Nr",
                "Stunde-Nr",
                "Unfallzeit",
                "Total Objekte",
                "Total Personen",
                "unverletzte Personen",
                "Getötete",
                "Schwerverletzte",
                "lebensbedrohlich Verletzte",
                "erheblich Verletzte",
                "Leichtverletzte",
                "Unfalltyp UAP",
                "Unfalltyp",
                "Unfalltyp Gruppenreferenz",
                "Unfalltyp Gruppe",
                "Hauptursache UAP",
                "Hauptursache",
                "Hauptursache Untergruppenreferenz",
                "Hauptursache Untergruppe",
                "Hauptursache Gruppenreferenz",
                "Hauptursache Gruppe",
                "Kanton Kürzel",
                "Aktuelle BFS Gemeinde-Nr",
                "Aktuelle Gemeinde",
                "Innerorts / Ausserorts",
                "Koordinate X",
                "Koordinate Y",
                "Koordinate E",
                "Koordinate N",
                "Strassenart UAP",
                "Strassenart",
                "Strassenart Zusatz UAP",
                "Strassenart Zusatz",
                "Verkehrsaufkommen UAP",
                "Verkehrsaufkommen",
                "Zonensignalisation UAP",
                "Zonensignalisation",
                "Vortrittsregelung UAP",
                "Vortrittsregelung",
                "Vortrittsregelung Zusatz UAP",
                "Vortrittsregelung Zusatz",
                "Unfallstelle UAP",
                "Unfallstelle",
                "Unfallstelle Zusatz UAP",
                "Unfallstelle Zusatz",
                "Strassenkategorie",
                "Strassenbeleuchtung UAP",
                "Strassenbeleuchtung",
                "Strassenzustand UAP",
                "Strassenzustand",
                "Witterung UAP",
                "Witterung",
                "Witterung Zusatz UAP",
                "Witterung Zusatz",
                "Höchstgeschwindigkeit",
                "Höchstgeschwindigkeit Zusatz UAP",
                "Höchstgeschwindigkeit Zusatz",
                "Lichtverhältnis UAP",
                "Lichtverhältnis",
                "aktualisiert am",
            ),
            key_column="Unfall-UID",
            canton_column="Kanton Kürzel",
            obj_count_column="Total Objekte",
            pers_count_column="Total Personen",
        ),
    ),
    FileKind.OBJEKT: (
        ColumnSet(  # RADIS — 77 columns
            columns=(
                "ObjektUid",
                "UnfallUid",
                "ObjektArt",
                "ObjNrFeld",
                "ObjInternalNrFeld",
                "ObjKatAusw",
                "ObjMeldePflichtAusw",
                "AnzPerFeld",
                "HauptVerursaFeld",
                "ResAtemAlkoholMglFeld",
                "AtemAlkoholProbe",
                "AtemAlkoholProbeZus",
                "AlkBlutpAusw",
                "AlkBlutpFeld",
                "AlkBlutpZuAusw",
                "BlutUrinMediProbe",
                "BlutUrinMediProbeZus",
                "BlutUrinMediProbeErgebnis",
                "BlutUrinBetProbe",
                "BlutUrinBetProbeZus",
                "BlutUrinBetProbeErgebnis",
                "KennzStaatAusw",
                "KennzKantonAusw",
                "KennzNrZuFeld",
                "Ursa1Ausw",
                "Ursa2Ausw",
                "Ursa3Ausw",
                "Anh1ArtFeld",
                "Anh1TypFeld",
                "Anh1FahrgNrFeld",
                "Anh1StammNrFeld",
                "Anh2ArtFeld",
                "Anh2TypFeld",
                "Anh2FahrgNrFeld",
                "Anh2StammNrFeld",
                "FahrzMarkeFeld",
                "FahrzMarkencodeFeld",
                "FahrzTypFeld",
                "FahrzFarbeFeld",
                "FahrzStamNrFeld",
                "FahrzFahrGestllNrFeld",
                "FahrzTypengenehmigungsNr",
                "FzHubraum",
                "FzLeistungKw",
                "FzSitzplaetzeTotal",
                "FahrzGesamtGewichtFeld",
                "FahrzLeerGewichtFeld",
                "AnhAuflAusw",
                "KennzArt0Ausw",
                "FahrzInvDatumFeld",
                "FahrzVersichFeld",
                "FahrzLetztePruefung",
                "FahrzAnzahlKilometer",
                "FahrzArtTreibstoff",
                "FahrzArtAntrieb",
                "FahrzArtGetriebe",
                "FhzArtAusw",
                "FAZAusw",
                "FhzArtWeitereFeld",
                "FhzArtZuAusw",
                "FhzKarosserieform",
                "FahrzwAusw",
                "Anprall1Ausw",
                "FhzHalterGeschlecht",
                "PinFeld",
                "FuehAuswSeitDatumFeld",
                "FuehAuswStaatAusw",
                "FuehAuswKatAusw",
                "AngZuFueh0Ausw",
                "AngZuFueh1Ausw",
                "IstPinPseudonymisiert",
                "IstFahrzStamNrPseudonymisiert",
                "IstFahrzFahrGestllNrFeldPseudonymisiert",
                "IstAnh1StammNrPseudonymisiert",
                "IstAnh1FahrgNrFeldPseudonymisiert",
                "IstAnh2StammNrPseudonymisiert",
                "IstAnh2FahrgNrFeldPseudonymisiert",
            ),
            key_column="ObjektUid",
            ordinal_column="ObjNrFeld",
        ),
        ColumnSet(  # Astrana — 76 columns (data/ASTRANA-Export/samples/Objekt.csv)
            columns=(
                "Jahr",
                "Datum",
                "Unfall-UID",
                "Objekt-UID",
                "Objekt-Nr. (intern)",
                "Total Personen",
                "unverletzte Personen",
                "Getötete",
                "Schwerverletzte",
                "lebensbedrohlich Verletzte",
                "erheblich Verletzte",
                "Leichtverletzte",
                "Objekt-Kategorie UAP",
                "Objekt-Kategorie",
                "Meldepflicht UAP",
                "Meldepflicht",
                "Kontrollschild Land UAP",
                "Kontrollschild Land",
                "Kontrollschild Kanton",
                "Hauptverursacher UAP",
                "Hauptverursacher",
                "Ursache 1 UAP",
                "Ursache 1",
                "Ursache 2 UAP",
                "Ursache 2",
                "Ursache 3 UAP",
                "Ursache 3",
                "Fahrzeugart UAP",
                "Fahrzeugart",
                "Fahrzeugart Zusatz UAP",
                "Fahrzeugart Zusatz",
                "FAZ",
                "Kontrollschildart (Farbe) UAP",
                "Kontrollschildart (Farbe)",
                "Hubraum",
                "Leistung in KW",
                "Sitzplätze",
                "Gesamtgewicht",
                "Fahrzeug 1.Inverkehrsetzung",
                "Anhänger (mitgeführt) UAP",
                "Anhänger (mitgeführt)",
                "Angabe Führerausweis UAP",
                "Angabe Führerausweis",
                "Angabe Führerausweis Zusatz UAP",
                "Angabe Führerausweis Zusatz",
                "Führerausweis seit",
                "Führerausweis Land UAP",
                "Führerausweis Land",
                "Führerausweis Kategorie",
                "Fahr- / Gehzweck UAP",
                "Fahr- / Gehzweck",
                "Anprall UAP",
                "Anprall",
                "Atemalkoholprobe UAP",
                "Atemalkoholprobe",
                "Atemalkoholprobe Zusatz UAP",
                "Atemalkoholprobe Zusatz",
                "Atemalkoholkonzentration (mg/l)",
                "Blutprobe auf Alkohol Zusatz UAP",
                "Blutprobe Alkohol angeordnet Zusatz",
                "Blutprobe auf Alkohol UAP",
                "Blutprobe auf Alkohol",
                "Blutalkoholkonzentration (‰)",
                "Blut-/Urinprobe auf Arzneimittel UAP",
                "Blut-/Urinprobe auf Arzneimittel",
                "Blut-/Urinprobe auf Arzneimittel Zusatz UAP",
                "Blut-/Urinprobe auf Arzneimittel Zusatz",
                "Ergebnis Blut-/Urinprobe auf Arzneimittel UAP",
                "Ergebnis Blut-/Urinprobe auf Arzneimittel",
                "Blut-/Urinprobe auf Betäubungsmittel UAP",
                "Blut-/Urinprobe auf Betäubungsmittel",
                "Blut-/Urinprobe auf Betäubungsmittel Zusatz UAP",
                "Blut-/Urinprobe auf Betäubungsmittel Zusatz",
                "Ergebnis Blut-/Urinprobe auf Betäubungsmittel UAP",
                "Ergebnis Blut-/Urinprobe auf Betäubungsmittel",
                "aktualisiert am",
            ),
            key_column="Objekt-UID",
            ordinal_column="Objekt-Nr. (intern)",
        ),
    ),
    FileKind.PERSON: (
        ColumnSet(  # RADIS — 18 columns
            columns=(
                "PersonUid",
                "ObjektUid",
                "GebDatumFeld",
                "PersNrFeld",
                "PersArtAusw",
                "PersSchaAusw",
                "PersArt1Ausw",
                "PersGeschAusw",
                "NacaScoreAusw",
                "SchutzsysAusw",
                "Schutzsys1Ausw",
                "NatAusw",
                "BerufFeld",
                "PlzFeld",
                "WohnortFeld",
                "LandAusw",
                "ErwPersDatumTodFeld",
                "ErwPersVerlFeld",
            ),
            key_column="PersonUid",
            ordinal_column="PersNrFeld",
        ),
        ColumnSet(  # Astrana `Mitfahrende` — 21 columns
            columns=(
                "Jahr",
                "Datum",
                "Unfall-UID",
                "Objekt-UID",
                "Objekt-Nr. (intern)",
                "Person-UID",
                "Person-Nr",
                "Geschlecht UAP",
                "Geschlecht",
                "Alter num",
                "Führerausweisalter",
                "Personenart UAP",
                "Personenart",
                "Unfallfolgen UAP",
                "Unfallfolgen",
                "NACA",
                "Schutzsystem UAP",
                "Schutzsystem",
                "Schutzsystem Zusatz UAP",
                "Schutzsystem Zusatz",
                "aktualisiert am",
            ),
            key_column="Person-UID",
            ordinal_column="Person-Nr",
        ),
    ),
    FileKind.TEXT: (  # shared/unchanged across formats
        ColumnSet(
            columns=("UNFALLUID", "HERGANG"),
            key_column="UNFALLUID",
            narrative_column="HERGANG",
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class HeaderMatch:
    """What the header said this file is, and how well it fitted.

    `ok` is exact: same columns, same order, no duplicates. Anything less is a
    `HEADER_MISMATCH` (blocking, mvp-spec.md §4.3) or, below
    `HEADER_MATCH_THRESHOLD`, `FileKind.UNKNOWN`.
    """

    kind: FileKind
    ok: bool
    #: The vocabulary that matched — `None` only for `FileKind.UNKNOWN`. The
    #: single extension point every downstream caller (canton/key/count
    #: column resolution, the census column universe) reads instead of a
    #: fixed RADIS-only constant.
    column_set: ColumnSet | None = None
    #: Canonical columns the header does not have, in canonical order.
    missing: tuple[str, ...] = ()
    #: Header columns the canonical set does not have, in header order.
    extra: tuple[str, ...] = ()
    #: Columns appearing more than once in the header.
    duplicated: tuple[str, ...] = ()


def normalise_header(header: Sequence[str]) -> tuple[str, ...]:
    """Whitespace-trim and case-fold for comparison.

    Original case is kept on `FileAnalysis.header`; this is only the comparison
    key (mvp-spec.md §4.1). A UTF-8 BOM on the very first column is stripped —
    it is a byte-order mark, not part of a column name.
    """
    normalised = [column.strip().casefold() for column in header]
    if normalised:
        normalised[0] = normalised[0].lstrip("﻿")
    return tuple(normalised)


def column_index(header: Sequence[str], column: str) -> int | None:
    """Index of `column` in `header`, matched the same way headers are.

    Returns `None` when the header does not carry it. Callers use this rather
    than a hard-coded position, because a real delivery's column order is only
    *usually* the canonical one.
    """
    wanted = column.strip().casefold()
    for index, name in enumerate(normalise_header(header)):
        if name == wanted:
            return index
    return None


def classify_header(header: Sequence[str]) -> HeaderMatch:
    """Decide the file's kind *and* format from its header alone. No filename
    is consulted.

    Every `(kind, column_set)` pair across `CANONICAL_COLUMN_SETS` is scored
    the same way a single canonical set used to be; the best-scoring pair
    wins, with ties broken by iteration order (RADIS before Astrana within a
    kind, `UNFALL`/`OBJEKT`/`PERSON`/`TEXT` order otherwise) — unchanged
    behaviour for any header that only ever matched one vocabulary. An empty
    `columns` tuple is a placeholder, never a candidate: a file with no
    columns must not silently "match" a kind nobody has filled in yet.
    """
    observed = normalise_header(header)
    if not observed:
        return HeaderMatch(FileKind.UNKNOWN, ok=False)

    observed_set = set(observed)
    # A repeated column is a property of the header alone, so it is found once
    # rather than per candidate kind. It makes `ok` false wherever it lands: two
    # columns of the same name make every value under them positional guesswork.
    duplicated = tuple(
        original
        for index, original in enumerate(header)
        if observed.count(observed[index]) > 1 and observed.index(observed[index]) == index
    )

    best: HeaderMatch | None = None
    best_score = 0.0

    for kind, column_sets in CANONICAL_COLUMN_SETS.items():
        for column_set in column_sets:
            if not column_set.columns:  # placeholder — never a match
                continue
            expected = normalise_header(column_set.columns)
            expected_set = set(expected)
            score = len(observed_set & expected_set) / len(expected_set)
            if score <= best_score:
                continue
            best_score = score
            best = HeaderMatch(
                kind=kind,
                ok=observed == expected and not duplicated,
                column_set=column_set,
                missing=tuple(
                    c for c in column_set.columns if c.strip().casefold() not in observed_set
                ),
                extra=tuple(
                    original
                    for index, original in enumerate(header)
                    if observed[index] not in expected_set
                ),
                duplicated=duplicated,
            )

    if best is None or best_score < HEADER_MATCH_THRESHOLD:
        return HeaderMatch(FileKind.UNKNOWN, ok=False, extra=tuple(header), duplicated=duplicated)
    return best


def match_header(header: Sequence[str]) -> FileKind:
    """Decide the file's kind from its header alone. No filename is consulted."""
    return classify_header(header).kind

# STUB — bodies owned by A1 (feat/m1-parsing). Not frozen.
"""The canonical column sets, and the header match that decides `FileKind`.

**The header is the only thing that decides what a file is** (SD5,
sw-design.md §12.5). Matching is case-insensitive and whitespace-trimmed
(mvp-spec.md §4.1).

The three canonical sets (67 `unfall` / 77 `objekt` / 18 `person` columns) and
the two-column text header below are the **column names only**, taken from the
headers of `data/data/samples/*` as plan-m0-m5.md §5 (A1) directs. No data row,
no value, and nothing derived from one, appears here or in any committed
fixture — `tests/unit/parsing/test_headers_realdata.py` re-checks these names
against the samples when they are present on the host, and skips when they are
not.

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
    "CANONICAL_HEADERS",
    "HEADER_MATCH_THRESHOLD",
    "KEY_COLUMNS",
    "OBJEKT_KEY_COLUMN",
    "PERSON_KEY_COLUMN",
    "TEXT_KEY_COLUMN",
    "TEXT_NARRATIVE_COLUMN",
    "UNFALL_CANTON_COLUMN",
    "UNFALL_KEY_COLUMN",
    "UNFALL_OBJ_COUNT_COLUMN",
    "UNFALL_PERS_COUNT_COLUMN",
    "HeaderMatch",
    "canonical_field_count",
    "classify_header",
    "column_index",
    "match_header",
    "normalise_header",
]

#: `UnfallUid` in the structured files; the text file's header is upper-case.
UNFALL_KEY_COLUMN: Final = "UnfallUid"
TEXT_KEY_COLUMN: Final = "UNFALLUID"

#: The remaining primary keys, and the columns cross-file validation reads.
#: They are named here, once, so `validation.py` never spells a column inline.
OBJEKT_KEY_COLUMN: Final = "ObjektUid"
PERSON_KEY_COLUMN: Final = "PersonUid"
TEXT_NARRATIVE_COLUMN: Final = "HERGANG"
#: Canton comes from the **data** — this column — never from a filename
#: (mvp-spec.md §4.1, sw-design.md §12.5).
UNFALL_CANTON_COLUMN: Final = "KantonAusw"
UNFALL_OBJ_COUNT_COLUMN: Final = "AnzObjFeld"
UNFALL_PERS_COUNT_COLUMN: Final = "BeteiligtePersTotalFeld"

#: The primary key of each structured kind, for the duplicate check that runs
#: across the **whole delivery** (mvp-spec.md §4.3).
KEY_COLUMNS: Final[dict[FileKind, str]] = {
    FileKind.UNFALL: UNFALL_KEY_COLUMN,
    FileKind.OBJEKT: OBJEKT_KEY_COLUMN,
    FileKind.PERSON: PERSON_KEY_COLUMN,
    FileKind.TEXT: TEXT_KEY_COLUMN,
}

#: How much of a canonical set a header must cover before the file is called
#: that kind with a `HEADER_MISMATCH` rather than left `UNKNOWN`. Below this a
#: header is genuinely unrecognisable (h12) and the file is `UNKNOWN`.
HEADER_MATCH_THRESHOLD: Final = 0.6

#: Column **names only**, from the sample headers. Order is the delivered
#: order, which is what `header_ok` compares against.
CANONICAL_HEADERS: Final[dict[FileKind, tuple[str, ...]]] = {
    FileKind.UNFALL: (  # 67 columns
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
    FileKind.OBJEKT: (  # 77 columns
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
    FileKind.PERSON: (  # 18 columns
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
    FileKind.TEXT: (  # 2 columns
        "UNFALLUID",
        "HERGANG",
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
        normalised[0] = normalised[0].lstrip("\ufeff")
    return tuple(normalised)


def canonical_field_count(kind: FileKind) -> int | None:
    """How many fields a row of `kind` has, or `None` when unknown."""
    columns = CANONICAL_HEADERS.get(kind, ())
    return len(columns) or None


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
    """Decide the file's kind from its header alone. No filename is consulted.

    An empty canonical set is a placeholder, never a candidate: a file with no
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

    for kind, canonical in CANONICAL_HEADERS.items():
        if not canonical:  # placeholder — never a match (see module docstring)
            continue
        expected = normalise_header(canonical)
        expected_set = set(expected)
        score = len(observed_set & expected_set) / len(expected_set)
        if score <= best_score:
            continue
        best_score = score
        best = HeaderMatch(
            kind=kind,
            ok=observed == expected and not duplicated,
            missing=tuple(c for c in canonical if c.strip().casefold() not in observed_set),
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

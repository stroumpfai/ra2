"""Regenerate the twelve hazard fixtures (sw-design.md §11.4).

mvp-spec.md §15 is explicit that clean fixtures are not acceptable. The real
delivery is classified and gitignored and must never reach a test (§12.11), so
every hazard is **synthesised byte-exactly** here and the result is committed.

Two properties this file has to keep:

1. **Deterministic.** No clock, no randomness, no dict ordering luck. Running
   it twice produces identical bytes, and `test_generator_matches_fixtures`
   fails the build if the committed files and this generator ever disagree.
2. **Synthetic to the last cell.** The only thing taken from the real delivery
   is the *column names*, imported from `ra2.domain.parsing.headers` — which
   plan-m0-m5.md §5 (A1) sanctions, and which keeps a 67-column fixture at 67
   columns without anyone counting. Every value below was invented here. No
   UID, narrative, coordinate, date or canton code comes from a real record.

Run it with `uv run python tests/fixtures/deliveries/generate_hazards.py`;
`--check` reports drift without writing.

The hazards, and what each one exists to prove:

| Fixture                  | Hazard                              | Expected                        |
|--------------------------|-------------------------------------|---------------------------------|
| `h01_cp1252`             | Windows-1252 bytes                  | detected, decoded, reported     |
| `h02_undecodable`        | bytes valid in neither encoding     | file fails, never `U+FFFD`      |
| `h03_stray_delimiter`    | extra `\\|` in a wide `unfall` row   | row rejected, key in report     |
| `h04_embedded_newline`   | newline inside a quoted narrative   | recovered, counted              |
| `h05_unquoted_newline`   | newline in an unquoted field        | recovered by the key anchor     |
| `h06_orphan_objekt`      | `objekt.UnfallUid` with no parent   | blocking                        |
| `h07_dup_uid_cross_canton` | one `UnfallUid` in the AG and BE sets | blocking                    |
| `h08_all_empty_column`   | a column empty in every row         | census 0 %, in no denominator   |
| `h09_fr_lossy`           | French with `oe`/quotes deleted     | contributes 0 to the canary     |
| `h10_count_mismatch`     | `AnzObjFeld` != child count         | reported, non-blocking          |
| `h11_unmatched_text_key` | text row with no `unfall` row       | reported, non-blocking          |
| `h12_unknown_header`     | header matching no table            | kind `unknown`, blocking if selected |
"""

import sys
from pathlib import Path

from ra2.domain.delivery import FileKind
from ra2.domain.parsing.headers import (
    CANONICAL_HEADERS,
    OBJEKT_KEY_COLUMN,
    PERSON_KEY_COLUMN,
    TEXT_KEY_COLUMN,
    TEXT_NARRATIVE_COLUMN,
    UNFALL_CANTON_COLUMN,
    UNFALL_KEY_COLUMN,
    UNFALL_OBJ_COUNT_COLUMN,
    UNFALL_PERS_COUNT_COLUMN,
)

HAZARDS_DIR = Path(__file__).parent / "hazards"

#: The delivered files use CRLF. Fixtures do too, so the reader is exercised on
#: the line ending it will actually meet.
CRLF = "\r\n"
STRUCTURED_DELIMITER = "|"
TEXT_DELIMITER = ";"

#: The one column left empty in every row of h08. Chosen because it is a free
#: text field, so "empty" is plausible rather than contrived.
ALL_EMPTY_COLUMN = "VssOhneBegruendung"


# --------------------------------------------------------------------------
# Synthetic values
# --------------------------------------------------------------------------


def uid(tag: str, number: int) -> str:
    """A 32-hex-character key — the shape the recovery anchor keys on.

    `tag` is a short hex prefix so a fixture's keys are readable at a glance:
    `aa…` is the AG set, `bb…` the BE set, `ff…` a deliberate orphan.
    """
    if len(tag) >= 32 or any(c not in "0123456789abcdef" for c in tag):
        raise ValueError(f"tag must be short lowercase hex: {tag!r}")
    return f"{tag}{number:0{32 - len(tag)}d}"


def _synthetic(column: str, index: int, key: str) -> str:
    """An obviously-invented value that still has the right *shape*.

    Shape matters — `Ausw` columns are enums, `Datum` columns are `YYYYMMDD`,
    time columns are `HH:MM` (mvp-spec.md §4.1) — because A2's type-hint rules
    read shapes. Content does not, and is deliberately nonsense.
    """
    if column.endswith("Uid"):
        return uid("cc", index)
    if "Datum" in column or column.endswith("PruefungFeld") or column == "FahrzLetztePruefung":
        return "20250101"
    if column == "UnfZeitFeld":
        return "07:45"
    if column.endswith("Ausw"):
        return str(index % 9 + 1)
    if column.endswith("Feld"):
        return str(100 + index)
    if column.startswith("Ist"):
        return "0"
    return f"synthetic-{index}"


def _row(kind: FileKind, key: str, overrides: dict[str, str]) -> list[str]:
    columns = CANONICAL_HEADERS[kind]
    values = {c: _synthetic(c, i, key) for i, c in enumerate(columns)}
    values.update(overrides)
    return [values[c] for c in columns]


def unfall_row(
    key: str,
    *,
    canton: str,
    objekt_count: int = 0,
    person_count: int = 0,
    narrative: str = "Fahrzeug A bremste, Fahrzeug B fuhr auf.",
    **overrides: str,
) -> list[str]:
    return _row(
        FileKind.UNFALL,
        key,
        {
            UNFALL_KEY_COLUMN: key,
            UNFALL_CANTON_COLUMN: canton,
            UNFALL_OBJ_COUNT_COLUMN: str(objekt_count),
            UNFALL_PERS_COUNT_COLUMN: str(person_count),
            "UnfHergangTextAnonym": narrative,
            **overrides,
        },
    )


def objekt_row(key: str, *, unfall_key: str, **overrides: str) -> list[str]:
    return _row(
        FileKind.OBJEKT,
        key,
        {OBJEKT_KEY_COLUMN: key, UNFALL_KEY_COLUMN: unfall_key, **overrides},
    )


def person_row(key: str, *, objekt_key: str, **overrides: str) -> list[str]:
    return _row(
        FileKind.PERSON,
        key,
        {PERSON_KEY_COLUMN: key, OBJEKT_KEY_COLUMN: objekt_key, **overrides},
    )


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def structured(kind: FileKind, rows: list[list[str]]) -> str:
    """A `|`-delimited table, header first, unquoted — the delivered shape."""
    lines = [STRUCTURED_DELIMITER.join(CANONICAL_HEADERS[kind])]
    lines += [STRUCTURED_DELIMITER.join(row) for row in rows]
    return CRLF.join(lines) + CRLF


def _quote(value: str) -> str:
    if any(c in value for c in (TEXT_DELIMITER, '"', "\r", "\n")):
        escaped = value.replace('"', '""')
        return f'"{escaped}"'
    return value


def text_file(rows: list[tuple[str, str]], *, quote: bool = True) -> str:
    """The two-column `;` file: RFC4180 with `"` doubled (mvp-spec.md §4.1).

    `quote=False` writes the narrative raw, which is what h05 needs: an
    embedded newline with no quoting for the RFC4180 reader to lean on, so the
    key anchor is the only thing that can put the record back together.
    """
    header = TEXT_DELIMITER.join((TEXT_KEY_COLUMN, TEXT_NARRATIVE_COLUMN))
    lines = [header]
    for key, narrative in rows:
        body = _quote(narrative) if quote else narrative
        lines.append(f"{key}{TEXT_DELIMITER}{body}")
    return CRLF.join(lines) + CRLF


# --------------------------------------------------------------------------
# The twelve hazards
# --------------------------------------------------------------------------

AG = "AG"
BE = "BE"


def _h01_cp1252() -> dict[str, bytes]:
    """Windows-1252 bytes: a narrative full of umlauts and accents.

    `0xE4` (`ä`) followed by ASCII is a UTF-8 lead byte with no continuation
    bytes, so this file cannot decode as UTF-8 and the fallback is genuinely
    exercised rather than being a code path nobody reaches.
    """
    text = structured(
        FileKind.UNFALL,
        [
            unfall_row(
                uid("aa", 1),
                canton=AG,
                narrative="Der Fahrzeuglenker naeherte sich der Kreuzung. Straße glatt, Nässe.",
            ),
            unfall_row(
                uid("aa", 2),
                canton=AG,
                narrative="Fußgänger überquerte die Fahrbahn beim Übergang, Sicht behindert.",
            ),
        ],
    )
    return {"unfall.txt": text.encode("cp1252")}


def _h02_undecodable() -> dict[str, bytes]:
    """Bytes valid in neither encoding.

    `0x9d` is undefined in Windows-1252 and is a bare UTF-8 continuation byte,
    so strict decoding fails both ways and the file must fail — never
    `errors="replace"`, never `U+FFFD` (§12.4).
    """
    text = structured(
        FileKind.UNFALL,
        [unfall_row(uid("aa", 1), canton=AG, narrative="Kollision im Kreisel PLACEHOLDER Ende.")],
    )
    return {"unfall.txt": text.encode("ascii").replace(b"PLACEHOLDER", b"\x9d\x9d")}


def _h03_stray_delimiter() -> dict[str, bytes]:
    """An extra `|` in a wide row: 68 fields where the header has 67.

    The row still starts with a 32-hex key and a delimiter, so it is a record,
    not a continuation. It is **detected and rejected** with its key — a
    67-column row cannot be repaired, because the stray delimiter could have
    landed in any of 67 fields (mvp-spec.md §4.2.3).
    """
    good_a = unfall_row(uid("aa", 1), canton=AG)
    bad = unfall_row(uid("aa", 2), canton=AG, narrative="Auffahrunfall|mit Sachschaden")
    good_b = unfall_row(uid("aa", 3), canton=AG)
    return {"unfall.txt": structured(FileKind.UNFALL, [good_a, bad, good_b]).encode("utf-8")}


def _h04_embedded_newline() -> dict[str, bytes]:
    """A newline inside a *quoted* narrative.

    The RFC4180 reader glues this one back together itself. It is still a
    recovery and still reported: the record spans two physical lines, and an
    analyst comparing "lines in the file" with "rows imported" needs that
    difference explained rather than left as an unaccountable gap.
    """
    rows = [
        (uid("aa", 1), "Der Lenker bremste stark.\r\nAnschliessend kam es zur Kollision."),
        (uid("aa", 2), "Einfacher Fall ohne Zeilenumbruch."),
    ]
    return {"text.csv": text_file(rows).encode("utf-8")}


def _h05_unquoted_newline() -> dict[str, bytes]:
    """A newline in an *unquoted* field: only the key anchor can repair it.

    Written by hand rather than through `text_file`, because the whole point is
    that no quoting is present for the reader to use.
    """
    header = TEXT_DELIMITER.join((TEXT_KEY_COLUMN, TEXT_NARRATIVE_COLUMN))
    lines = [
        header,
        f"{uid('aa', 1)}{TEXT_DELIMITER}Der Lenker bremste stark.",
        "Anschliessend kam es zur Kollision.",
        "Der Sachschaden war erheblich.",
        f"{uid('aa', 2)}{TEXT_DELIMITER}Einfacher Fall ohne Zeilenumbruch.",
    ]
    return {"text.csv": (CRLF.join(lines) + CRLF).encode("utf-8")}


def _h06_orphan_objekt() -> dict[str, bytes]:
    """An `objekt` row whose `UnfallUid` reaches no `unfall` row: blocking."""
    parent = uid("aa", 1)
    orphan_parent = uid("ff", 999)
    unfall = structured(
        FileKind.UNFALL, [unfall_row(parent, canton=AG, objekt_count=1, person_count=0)]
    )
    objekt = structured(
        FileKind.OBJEKT,
        [
            objekt_row(uid("aa", 11), unfall_key=parent),
            objekt_row(uid("aa", 12), unfall_key=orphan_parent),
        ],
    )
    return {"unfall.txt": unfall.encode("utf-8"), "objekt.txt": objekt.encode("utf-8")}


def _h07_dup_uid_cross_canton() -> dict[str, bytes]:
    """One `UnfallUid` in two cantonal sets — the collision §4.1 exists to catch.

    Each file is internally unique. Only checking across the **whole delivery**
    finds this, and if it is missed the shared text file attaches AG's narrative
    to BE's record.
    """
    shared = uid("aa", 1)
    ag = structured(
        FileKind.UNFALL,
        [unfall_row(shared, canton=AG), unfall_row(uid("aa", 2), canton=AG)],
    )
    be = structured(
        FileKind.UNFALL,
        [unfall_row(uid("bb", 1), canton=BE), unfall_row(shared, canton=BE)],
    )
    return {"ag_unfall.txt": ag.encode("utf-8"), "be_unfall.txt": be.encode("utf-8")}


def _h08_all_empty_column() -> dict[str, bytes]:
    """A column empty in every row.

    It must appear in the census at 0 % and leave every denominator — which is
    only possible if the canonical header, not the observed cells, decides which
    columns exist (M0-D9).
    """
    rows = [
        unfall_row(uid("aa", n), canton=AG, **{ALL_EMPTY_COLUMN: ""}) for n in range(1, 4)
    ]
    return {"unfall.txt": structured(FileKind.UNFALL, rows).encode("utf-8")}


def _h09_fr_lossy() -> dict[str, bytes]:
    """French whose cp1252-only characters were already deleted upstream.

    Ordinary accented letters survive a cp1252 -> Latin-1 conversion; `oe`,
    typographic quotes, dashes and the ellipsis do not — they are *deleted*,
    not substituted, so the text still reads and nothing in it is malformed.
    Zero canary characters in a French corpus is what proves it happened.
    """
    rows = [
        (uid("aa", 1), "Le conducteur a perdu le controle et a heurte la glissiere de securite."),
        (uid("aa", 2), "La voiture a derape sur la chaussee mouillee, pres du carrefour."),
        (uid("aa", 3), "Le pieton traversait hors du passage protege, a la tombee de la nuit."),
    ]
    return {"text.csv": text_file(rows).encode("utf-8")}


def _h10_count_mismatch() -> dict[str, bytes]:
    """`AnzObjFeld` says 3, two `objekt` rows exist. Reported, not blocking.

    `BeteiligtePersTotalFeld` is set to the true person count, so the fixture
    isolates one finding instead of firing two.
    """
    parent = uid("aa", 1)
    objekt_a, objekt_b = uid("aa", 11), uid("aa", 12)
    unfall = structured(
        FileKind.UNFALL,
        [unfall_row(parent, canton=AG, objekt_count=3, person_count=2)],
    )
    objekt = structured(
        FileKind.OBJEKT,
        [objekt_row(objekt_a, unfall_key=parent), objekt_row(objekt_b, unfall_key=parent)],
    )
    person = structured(
        FileKind.PERSON,
        [
            person_row(uid("aa", 21), objekt_key=objekt_a),
            person_row(uid("aa", 22), objekt_key=objekt_b),
        ],
    )
    return {
        "unfall.txt": unfall.encode("utf-8"),
        "objekt.txt": objekt.encode("utf-8"),
        "person.txt": person.encode("utf-8"),
    }


def _h11_unmatched_text_key() -> dict[str, bytes]:
    """A narrative whose `UNFALLUID` matches no `unfall` row. Reported."""
    present = uid("aa", 1)
    missing = uid("ff", 998)
    unfall = structured(FileKind.UNFALL, [unfall_row(present, canton=AG)])
    text = text_file(
        [
            (present, "Auffahrunfall auf der Hauptstrasse."),
            (missing, "Narrative fuer einen Unfall, der in keiner Tabelle steht."),
        ]
    )
    return {"unfall.txt": unfall.encode("utf-8"), "text.csv": text.encode("utf-8")}


def _h12_unknown_header() -> dict[str, bytes]:
    """A header matching no table at all.

    Nothing about the *filename* may rescue it: kind is `unknown`, and blocking
    the moment the analyst selects it (SD5, sw-design.md §6.2.2).
    """
    lines = [
        "REPORT_ID;SUBMITTED_ON;OFFICER_REMARKS",
        "R-0001;20250101;Bericht ohne passende Tabelle.",
        "R-0002;20250102;Zweiter Bericht.",
    ]
    return {"unknown.csv": (CRLF.join(lines) + CRLF).encode("utf-8")}


#: Ordered, so a regenerated tree is byte-identical every time.
HAZARDS = (
    ("h01_cp1252", _h01_cp1252),
    ("h02_undecodable", _h02_undecodable),
    ("h03_stray_delimiter", _h03_stray_delimiter),
    ("h04_embedded_newline", _h04_embedded_newline),
    ("h05_unquoted_newline", _h05_unquoted_newline),
    ("h06_orphan_objekt", _h06_orphan_objekt),
    ("h07_dup_uid_cross_canton", _h07_dup_uid_cross_canton),
    ("h08_all_empty_column", _h08_all_empty_column),
    ("h09_fr_lossy", _h09_fr_lossy),
    ("h10_count_mismatch", _h10_count_mismatch),
    ("h11_unmatched_text_key", _h11_unmatched_text_key),
    ("h12_unknown_header", _h12_unknown_header),
)


def build() -> dict[str, bytes]:
    """Every fixture as `"<hazard>/<filename>" -> bytes`. Pure; writes nothing."""
    out: dict[str, bytes] = {}
    for name, builder in HAZARDS:
        for filename, payload in builder().items():
            out[f"{name}/{filename}"] = payload
    return out


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    drift: list[str] = []
    for relative, payload in build().items():
        path = HAZARDS_DIR / relative
        current = path.read_bytes() if path.is_file() else None
        if current == payload:
            continue
        drift.append(relative)
        if check_only:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    if check_only and drift:
        print("Committed fixtures differ from the generator:")
        for relative in drift:
            print(f"  {relative}")
        return 1
    print(f"{'drift' if check_only else 'wrote'}: {len(drift)} file(s) of {len(build())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

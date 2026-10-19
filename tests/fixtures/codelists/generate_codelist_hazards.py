"""Regenerate the six codelist hazard fixtures (sw-design.md §14.1/§14.2).

`codes-2018.json` (the real file `ra2.domain.codes.validate_import` parses in
production) lives under gitignored `data/Codes/` and must never reach a test
(CLAUDE.md Do-NOT #11) — it may not even exist on a given checkout. These six
fixtures stand in for it: small, synthetic, byte-exact, committed, so tests
never depend on the real upload.

Two properties this file has to keep, same as
`tests/fixtures/deliveries/generate_hazards.py`:

1. **Deterministic.** No clock, no randomness, no dict ordering luck — `json`
   is asked to sort keys, and every dict below is written out by hand in a
   fixed order. Running this twice byte-for-byte matches.
2. **Synthetic to the last label.** No attribute key, code or label comes from
   the real ASTRA/OFROU annexes. `main_cause`'s real de/fr-only gap
   (mvp-spec.md §7) is the one piece of *shape* borrowed here — c02 mirrors it
   deliberately — but the key, codes and label text are all invented.

Run it with `uv run python tests/fixtures/codelists/generate_codelist_hazards.py`;
`--check` reports drift without writing.

The hazards, and what each one exists to prove:

| Fixture | Hazard                                    | Expected                          |
|---------|--------------------------------------------|-----------------------------------|
| c01     | minimal valid import, two attributes, all langs | `validate_import` succeeds  |
| c02     | one code missing a language's label        | `PARTIAL` once mapped, that lang  |
| c03     | an attribute with zero codes               | `MISSING` once mapped to it       |
| c04     | one attribute missing its `codes` key      | the whole import fails, `list[…]` |
| c05     | valid codelist + a corpus value it lacks   | coverage's orphan/danger row      |
| c06     | automap: padded vs bare, nested code sets, | copied / overlap / unresolved     |
|         | a next generation that drops a key         | suggestions                       |
"""

import json
import sys
from pathlib import Path
from typing import Any

HAZARDS_DIR = Path(__file__).parent / "hazards"

#: c05's corpus-only value: never a key of any attribute's `codes` map below,
#: by construction — the test asserting `in_codelist=False` imports this
#: directly rather than re-typing a "value that happens not to be a code".
ORPHAN_VALUE = "97"

#: c02 mirrors the real, named gap (mvp-spec.md §7): `main_cause` and its two
#: siblings have `de`/`fr` but no `it`. Only the *shape* is borrowed — key,
#: codes and label text below are all invented.
PARTIAL_LANGUAGE = "it"


def _entry(**labels: str) -> dict[str, str]:
    """One `{de, fr, it}`-shaped label map, only the given languages set."""
    return dict(labels)


def _dump(document: dict[str, Any]) -> bytes:
    """Stable, readable JSON: sorted keys, 2-space indent, trailing newline."""
    return (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


# --------------------------------------------------------------------------
# The six hazards
# --------------------------------------------------------------------------


def _c01_minimal_valid() -> dict[str, bytes]:
    """Two attributes, `de`/`fr`/`it` all present on every code and every name."""
    document = {
        "accident_type": {
            "chapter": "4.1.1",
            "name": _entry(de="Unfallart", fr="Type d'accident", it="Tipo di incidente"),
            "codes": {
                "01": _entry(de="Auffahren", fr="Collision par l'arrière", it="Tamponamento"),
                "02": _entry(de="Frontalkollision", fr="Collision frontale", it="Scontro frontale"),
            },
        },
        "road_type": {
            "chapter": "4.1.2",
            "name": _entry(de="Strassenart", fr="Type de route", it="Tipo di strada"),
            "codes": {
                "01": _entry(de="Autobahn", fr="Autoroute", it="Autostrada"),
                "02": _entry(de="Hauptstrasse", fr="Route principale", it="Strada principale"),
            },
        },
    }
    return {"codelist.json": _dump(document)}


def _c02_missing_language_label() -> dict[str, bytes]:
    """`main_cause`-shaped: code `02` has `de`/`fr` but no `it` (real gap, invented text)."""
    document = {
        "main_cause": {
            "name": _entry(de="Hauptursache", fr="Cause principale", it="Causa principale"),
            "codes": {
                "01": _entry(de="Missachten Vortritt", fr="Non-respect priorité", it="Precedenza"),
                "02": _entry(de="Unangepasste Geschwindigkeit", fr="Vitesse inadaptée"),
            },
        }
    }
    return {"codelist.json": _dump(document)}


def _c03_attribute_with_zero_codes() -> dict[str, bytes]:
    """`codes: {}` is structurally valid — zero rows, not a validation error."""
    document = {
        "light_condition": {
            "name": _entry(
                de="Lichtverhältnis", fr="Conditions de lumière", it="Condizioni di luce"
            ),
            "codes": {},
        }
    }
    return {"codelist.json": _dump(document)}


def _c04_missing_codes_key() -> dict[str, bytes]:
    """One attribute (`weather`) has no `codes` key at all: the whole import fails.

    `road_type` is present and well-formed alongside it, proving the failure
    is not "every attribute happened to be bad" but "one bad attribute fails
    the lot" (Do-NOT list #6 — no partial import, no best-effort skipping).
    """
    document: dict[str, Any] = {
        "road_type": {
            "name": _entry(de="Strassenart", fr="Type de route", it="Tipo di strada"),
            "codes": {"01": _entry(de="Autobahn", fr="Autoroute", it="Autostrada")},
        },
        "weather": {
            "name": _entry(de="Wetter", fr="Météo", it="Meteo"),
            # deliberately no "codes" key
        },
    }
    return {"codelist.json": _dump(document)}


def _c05_orphan_corpus_value() -> dict[str, bytes]:
    """A valid, minimal codelist. `ORPHAN_VALUE` (above) matches none of its codes.

    The codelist itself is unremarkable — c01-shaped, one attribute. What
    makes this c05 is the test pairing it with a corpus cell whose value is
    `ORPHAN_VALUE`: no code in this file, in any language, is `"97"`.
    """
    document = {
        "weather": {
            "name": _entry(de="Wetter", fr="Météo", it="Meteo"),
            "codes": {
                "1": _entry(de="Klar", fr="Clair", it="Sereno"),
                "2": _entry(de="Regen", fr="Pluie", it="Pioggia"),
                "6": _entry(de="Starker Wind", fr="Vent fort", it="Vento forte"),
            },
        }
    }
    return {"codelist.json": _dump(document)}


def _numbered(codes: list[str], *, de: str, fr: str, it: str) -> dict[str, dict[str, str]]:
    """`{code: {de, fr, it}}`, each label the word plus its code — invented."""
    return {code: _entry(de=f"{de} {code}", fr=f"{fr} {code}", it=f"{it} {code}") for code in codes}


def _c06_automap() -> dict[str, bytes]:
    """Automap's hazards (plan-codelists-usability.md §4.1).

    - `accident_type`'s codes are **padded** (`01`…`04`): a corpus whose
      leading zeros were lost (`1`, `2`) must not overlap it.
    - `injury_severity` ⊂ `light_condition` ⊂ `weather` over bare integers:
      every small-integer column sits inside several attributes at once, and
      only the tightest fit (Jaccard) may be proposed.
    - `codelist_next.json` is the next generation, **without**
      `light_condition`: a mapping copied from a corpus mapped against the
      first one has a key the current import no longer has.
    """
    first = {
        "accident_type": {
            "chapter": "6.1",
            "name": _entry(de="Unfalltyp", fr="Type d'accident", it="Tipo di incidente"),
            "codes": _numbered(["01", "02", "03", "04"], de="Typ", fr="Type", it="Tipo"),
        },
        "injury_severity": {
            "chapter": "6.2",
            "name": _entry(de="Verletzungsgrad", fr="Gravité", it="Gravità"),
            "codes": _numbered(["1", "2", "3"], de="Grad", fr="Degré", it="Grado"),
        },
        "light_condition": {
            "chapter": "6.3",
            "name": _entry(de="Lichtverhältnis", fr="Lumière", it="Luce"),
            "codes": _numbered(["1", "2", "3", "4", "5"], de="Licht", fr="Lumière", it="Luce"),
        },
        "weather": {
            "chapter": "6.4",
            "name": _entry(de="Witterung", fr="Météo", it="Meteo"),
            "codes": _numbered([str(n) for n in range(1, 10)], de="Wetter", fr="Temps", it="Tempo"),
        },
    }
    second = {key: value for key, value in first.items() if key != "light_condition"}
    return {"codelist.json": _dump(first), "codelist_next.json": _dump(second)}


#: Ordered, so a regenerated tree is byte-identical every time.
HAZARDS = (
    ("c01_minimal_valid", _c01_minimal_valid),
    ("c02_missing_language_label", _c02_missing_language_label),
    ("c03_attribute_with_zero_codes", _c03_attribute_with_zero_codes),
    ("c04_missing_codes_key", _c04_missing_codes_key),
    ("c05_orphan_corpus_value", _c05_orphan_corpus_value),
    ("c06_automap", _c06_automap),
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

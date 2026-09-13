"""Regenerate the seven prompt-domain hazard fixtures (sw-design.md §15.1).

A real prompt template is authored by an analyst in the Prompts view and
lives in `prompt_template.source` — there is no on-disk file to gitignore the
way `codes-2018.json` or a VUM delivery is (CLAUDE.md Do-NOT #11 does not
apply here for that reason). These seven fixtures exist anyway, for the same
reason `tests/fixtures/deliveries/hazards/` and
`tests/fixtures/codelists/hazards/` do: **clean fixtures are not acceptable**
(mvp-spec.md §15) and a hand-typed literal in each test module drifts the
moment two tests need the same hazard.

Two properties this file has to keep, same as
`tests/fixtures/deliveries/generate_hazards.py` and
`tests/fixtures/codelists/generate_codelist_hazards.py`:

1. **Deterministic.** No clock, no randomness — running this twice
   byte-for-byte matches.
2. **Small and synthetic to the last word.** No real accident narrative, no
   real feature wording — every string here is invented for the test.

Run it with `uv run python tests/fixtures/prompts/generate_prompt_hazards.py`;
`--check` reports drift without writing.

The hazards, and what each one exists to prove (plan-phase-3.md §7, H1):

| Fixture | Hazard                                          | Expected                       |
|---------|--------------------------------------------------|-------------------------------|
| p01     | valid template, all three slots, none duplicated  | `validate_template` -> `()`   |
| p02     | `{{feature_block}}` present, `{{narrative}}` gone  | `MISSING_REQUIRED_SLOT`       |
| p03     | an unknown `{{corpus}}` alongside both required   | `UNKNOWN_SLOT`                 |
| p04     | `{{feature_block}}` twice, `{{narrative}}` once   | `validate_template` -> `()`   |
| p05     | `{{narrative}` — a half-brace, never silent text  | `MALFORMED_SLOT`               |
| p06     | one enum code has no label in the requested lang  | visible fallback, never empty |
| p07     | narrative text containing a literal `{{`          | single-pass: never re-expanded|
"""

import json
import sys
from pathlib import Path
from typing import Any

HAZARDS_DIR = Path(__file__).parent / "hazards"


def _text(content: str) -> bytes:
    """UTF-8, LF line endings, exactly one trailing newline — no surprises
    when this is read back with `encoding="utf-8"` (Do-NOT list #4)."""
    return (content.rstrip("\n") + "\n").encode("utf-8")


def _json_doc(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _p01_valid_all_slots() -> dict[str, bytes]:
    return {
        "p01_valid_all_slots/template.txt": _text(
            "You extract structured facts from Swiss accident reports.\n"
            "\n"
            "Language: {{language}}\n"
            "\n"
            "Read the narrative below. For each feature, emit the value the\n"
            "narrative supports — nothing inferred, nothing assumed.\n"
            "\n"
            "{{feature_block}}\n"
            "\n"
            "Answer as JSON only, one key per feature, no prose.\n"
            "\n"
            "--- narrative ---\n"
            "{{narrative}}"
        )
    }


def _p02_missing_narrative() -> dict[str, bytes]:
    return {
        "p02_missing_narrative/template.txt": _text(
            "You extract structured facts from Swiss accident reports.\n"
            "\n"
            "{{feature_block}}\n"
            "\n"
            "Answer as JSON only, one key per feature, no prose."
        )
    }


def _p03_unknown_slot() -> dict[str, bytes]:
    return {
        "p03_unknown_slot/template.txt": _text(
            "You extract structured facts from Swiss accident reports.\n"
            "\n"
            "Corpus: {{corpus}}\n"
            "\n"
            "{{feature_block}}\n"
            "\n"
            "--- narrative ---\n"
            "{{narrative}}"
        )
    }


def _p04_duplicate_feature_block() -> dict[str, bytes]:
    return {
        "p04_duplicate_feature_block/template.txt": _text(
            "{{feature_block}}\n"
            "\n"
            "Reminder — the same feature list again, for emphasis:\n"
            "\n"
            "{{feature_block}}\n"
            "\n"
            "--- narrative ---\n"
            "{{narrative}}"
        )
    }


def _p05_half_brace() -> dict[str, bytes]:
    return {
        "p05_half_brace/template.txt": _text(
            "You extract structured facts from Swiss accident reports.\n"
            "\n"
            "{{feature_block}}\n"
            "\n"
            "--- narrative ---\n"
            "{{narrative}"
        )
    }


#: p06's requested rendering language — chosen so at least one code below
#: (`02`) is deliberately missing exactly that language's label.
P06_LANGUAGE = "fr"


def _p06_enum_missing_label() -> dict[str, bytes]:
    document = {
        "language": P06_LANGUAGE,
        "features": [
            {
                "key": "weather",
                "kind": "labelled",
                "grain": "accident",
                "value_type": "enum",
                "description": "Weather condition at the time of the accident",
                "matching_rule": {
                    "kind": "exact",
                    "tolerance_minutes": None,
                    "decimal_precision": None,
                },
                "enum_codelist": [
                    {"code": "01", "label": {"de": "Klar", "fr": "Clair", "it": "Chiaro"}},
                    # "02" has de/it but no fr — the hazard.
                    {"code": "02", "label": {"de": "Regen", "it": "Pioggia"}},
                ],
            },
            {
                "key": "road_notes",
                "kind": "exploratory",
                "grain": "accident",
                "value_type": "free_text",
                "description": "Anything unusual about the road surface, verbatim from the expert.",
                "matching_rule": {
                    "kind": "none",
                    "tolerance_minutes": None,
                    "decimal_precision": None,
                },
                "enum_codelist": None,
            },
        ],
    }
    return {"p06_enum_missing_label/features.json": _json_doc(document)}


def _p07_narrative_literal_braces() -> dict[str, bytes]:
    return {
        "p07_narrative_literal_braces/template.txt": _text(
            "{{feature_block}}\n\n--- narrative ---\n{{narrative}}"
        ),
        # Record text can and does contain a literal "{{" — anonymisation
        # markers, a quoted radio message, anything. Resolution must place
        # this verbatim and never re-scan it for slots.
        "p07_narrative_literal_braces/narrative.txt": _text(
            "The driver reported the dashcam overlay read "
            '"{{narrative}}" in the corner of the frame just before impact.'
        ),
    }


def build() -> dict[str, bytes]:
    """Every hazard's files, keyed by path relative to `hazards/`."""
    out: dict[str, bytes] = {}
    for fn in (
        _p01_valid_all_slots,
        _p02_missing_narrative,
        _p03_unknown_slot,
        _p04_duplicate_feature_block,
        _p05_half_brace,
        _p06_enum_missing_label,
        _p07_narrative_literal_braces,
    ):
        out.update(fn())
    return out


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    built = build()

    if not check_only:
        for relative, content in built.items():
            path = HAZARDS_DIR / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        print(f"wrote {len(built)} file(s) under {HAZARDS_DIR}")
        return 0

    drift = []
    for relative, expected in built.items():
        path = HAZARDS_DIR / relative
        if not path.is_file() or path.read_bytes() != expected:
            drift.append(relative)
    if drift:
        print("drift detected in:", *drift, sep="\n  ")
        return 1
    print("no drift")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

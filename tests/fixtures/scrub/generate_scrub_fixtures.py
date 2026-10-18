"""Regenerate the scrub fixtures (sw-design.md §19, plan-text-scrubbing.md §9).

The name lists RA2 runs on are public, but they are **not committed**
(`docs/rules.md`, `.gitignore`'s `**/scrub-lists/` and `*.names.txt`), and a
test must never depend on them. These stand in for them: small, invented,
byte-exact, committed. The names are ordinary first and last names; no entry
was taken from a delivery or from any real person's record.

Two properties this file has to keep, as the other generators do:

1. **Deterministic.** Every byte is written out below in a fixed order.
   Running this twice produces identical files, and
   `tests/unit/scrub/test_generated_scrub_fixtures.py` fails the build if the
   committed files and this generator ever disagree.
2. **Hazards in the bytes, not described.** A list with a BOM and CRLF line
   endings, an NFD entry, one name spelt three ways, entries too short to
   trust, an entry with no letters, comments and blank lines, and a list that
   is not UTF-8 at all. Clean fixtures are not acceptable (mvp-spec.md §15).

Run it with `uv run python tests/fixtures/scrub/generate_scrub_fixtures.py`;
`--check` reports drift without writing.

| Fixture         | Hazard                                  | Expected               |
|-----------------|-----------------------------------------|------------------------|
| s01_firstnames  | LF, an NFD `Jörg`, a hyphen, a comment  | NFD matches NFC text   |
| s02_lastnames   | BOM, CRLF, `Müller` spelt three ways,   | parses; every notice   |
|                 | `Li`, `Le`, `123`, blank lines          | is counted             |
| s03_whitelist   | surnames that are also nouns            | whitelist wins, unless |
|                 |                                         | an honorific precedes  |
| s04_rules       | IBAN, AHV, date rules, `protected`      | `check_rules` passes   |
| s05_lastnames…  | Windows-1252 bytes                      | refused `not_utf8`     |
| s06_slow_rule   | catastrophic backtracking               | `pattern_too_slow`     |
"""

import sys
from pathlib import Path

HAZARDS_DIR = Path(__file__).parent / "hazards"

#: s01: plain LF. `Jo\u0308rg` is Jörg in NFD, decomposed on purpose: a list
#: exported from a Mac arrives that way, and it must match the NFC `Jörg` a
#: narrative carries.
FIRSTNAMES = (
    "# Vornamen, erfunden für die Tests\n"
    "Hans\n"
    "Anna\n"
    "Martin\n"
    "Simon\n"
    "René\n"
    "Jo\u0308rg\n"
    "Céline\n"
    "Marie-Claire\n"
    "Luca\n"
).encode()

#: s02: a BOM, CRLF line endings, and every reported case. `Müller`,
#: `MÜLLER` and `Mueller` are one entry key (`mueller`), so the last two are
#: duplicates. `Li` and `Le` are too short (and `Le` is a French article),
#: `123` has no letters.
LASTNAMES = "\ufeff" + "\r\n".join(
    (
        "# Nachnamen, erfunden für die Tests",
        "Müller",
        "Meier",
        "Fuchs",
        "Weiss",
        "Martin",
        "Simon",
        "von Allmen",
        "D'Alessandro",
        "Brunner",
        "Dupont",
        "Rossi",
        "",
        "MÜLLER",
        "Mueller",
        "Li",
        "Le",
        "123",
        "",
    )
)

#: s03: last names that are also nouns or adjectives in a narrative: a fox
#: crossing, a white car. `Pierre` is a first name and French for stone.
WHITELIST = "Fuchs\nWeiss\nWolf\nKoch\nBach\nPierre\n"

#: s04's date rule, in three alternatives: numeric with a year, a German
#: month name with an optional year, a French month name with a year. A bare
#: `12.03` is not a date (Q5): it is as likely a time.
_DAY = r"(?:0?[1-9]|[12]\d|3[01])"
DATE_PATTERN = "|".join(
    (
        rf"(?<!\d){_DAY}\.(?:0?[1-9]|1[0-2])\.(?:\d{{4}}|\d{{2}})(?!\d)",
        rf"(?<!\d){_DAY}\. ?(?:Januar|Februar|März|April|Mai|Juni|Juli|August"
        r"|September|Oktober|November|Dezember)(?: \d{4})?",
        r"(?<!\d)(?:1er|0?[1-9]|[12]\d|3[01]) (?:janvier|février|mars|avril|mai|juin"
        r"|juillet|août|septembre|octobre|novembre|décembre) \d{4}",
    )
)

#: s04: the imported rules a real set is expected to carry (plan §4): IBAN,
#: AHV, dates. Numbers are invented; `756` is the AHV prefix every number has.
RULES_TEMPLATE = """\
# Erfundene Testregeln (plan-text-scrubbing.md §4).

protected = ["Tempo 80", "am Vortag"]

[[rule]]
id = "iban-ch"
tag = "IBAN"
description = "Swiss IBAN, grouped or not."
pattern = '(?<![0-9A-Z])CH\\d{2}(?: ?[0-9A-Z]{4}){4} ?[0-9A-Z](?![0-9A-Z])'
must_match = ["CH93 0076 2011 6238 5295 7", "CH9300762011623852957"]
must_not_match = ["CH93", "Km 123.4"]

[[rule]]
id = "ahv"
tag = "AHV"
description = "AHV number: 756, then ten digits, dotted or not."
pattern = '(?<!\\d)756[. ]?\\d{4}[. ]?\\d{4}[. ]?\\d{2}(?!\\d)'
must_match = ["756.1234.5678.97", "7561234567897"]
must_not_match = ["756", "Tempo 75"]

[[rule]]
id = "date"
tag = "Date"
description = "A date with a year, or with a German or French month name."
pattern = '{DATE}'
must_match = ["12.03.2024", "12.3.24", "12. März 2024", "1er mars 2024", "3. Mai"]
must_not_match = ["um 07.45 Uhr", "12.03", "Km 12.5", "um 14.30 Uhr"]
"""
RULES = RULES_TEMPLATE.replace("{DATE}", DATE_PATTERN).encode()

#: s05: `Müller` and `Jörg` in Windows-1252. `0xFC` and `0xF6` are not UTF-8.
LASTNAMES_CP1252 = "Müller\nJörg\n".encode("cp1252")

#: s06: `regex` optimises the textbook `(a+)+$` away (measured); `(a|aa)+$`
#: still backtracks exponentially on a run of `a` ending in a non-match.
SLOW_RULE = b"""\
[[rule]]
id = "slow"
tag = "Slow"
pattern = '(a|aa)+$'
must_match = ["aaa"]
"""


def build() -> dict[str, bytes]:
    """Every fixture, by path relative to `hazards/`."""
    return {
        "s01_firstnames.txt": FIRSTNAMES,
        "s02_lastnames.txt": LASTNAMES.encode(),
        "s03_whitelist.txt": WHITELIST.encode(),
        "s04_rules.toml": RULES,
        "s05_lastnames_cp1252.txt": LASTNAMES_CP1252,
        "s06_slow_rule.toml": SLOW_RULE,
    }


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

# NEW — feat/text-scrubbing. Not frozen; a change bumps MANDATORY_RULES_VERSION.
"""The rules every freeze applies, whatever was imported (sw-design.md §19, `SD63`).

Licence plates, phone numbers and email addresses. They are **code**, not
data: committed, reviewed and tested in CI, and an import cannot disable,
override or reuse their ids. Each corpus frozen with them copies them, so a
corpus still says which mandatory rules it got after this file changes.

**These are the agreed patterns**, confirmed by the project owner. They meet
the contract in `plan-text-scrubbing.md` §4, and any change to one must still
pass the same examples: `tests/unit/scrub/test_mandatory.py` is where that is
checked. Bump `MANDATORY_RULES_VERSION` with any change here.

Patterns compile in `regex`'s `VERSION0` mode (the `re`-compatible one) and
are case-sensitive unless they say otherwise inline.
"""

from typing import Final

from ra2.domain.scrub import RegexRule, RuleSource

__all__ = ["MANDATORY_RULES", "MANDATORY_RULES_VERSION"]

#: Stored on every corpus beside the rules themselves (`scrub_mandatory_json`).
MANDATORY_RULES_VERSION: Final = 1

_CANTONS: Final = "AG|AI|AR|BE|BL|BS|FR|GE|GL|GR|JU|LU|NE|NW|OW|SG|SH|SO|SZ|TG|TI|UR|VD|VS|ZG|ZH"

#: A Swiss plate: a canton code, an optional space or hyphen, then one to six
#: digits, optionally grouped `123 456` or `123'456`. Upper case only, so
#: French `ne` and German `so` are never plates. A canton code right after
#: `Kanton`, `canton` or `Kt.` names the canton, not a vehicle (Q4). **The
#: first digit is never 0**: no plate starts with one, and without the rule
#: `ZH 079 123 45 67` was claimed as the plate `ZH 079 123`, which starts
#: before the phone number and so wins the overlap (found by the property
#: tests).
LICENSE_PLATE: Final = RegexRule(
    rule_id="license-plate",
    tag="LicensePlate",
    pattern=(
        r"(?<![\p{L}\p{M}\d])(?<!Kanton\s)(?<!canton\s)(?<!Kt\.\s)"
        rf"(?:{_CANTONS})[ \-]?[1-9]\d{{0,2}}(?:[ ']?\d{{3}})?(?![\d\p{{L}}])"
    ),
    must_match=("BE 123456", "ZH 1234", "VD-123 456", "AG 12 345", "TI123456", "SG 12'345"),
    must_not_match=(
        "B1",
        "G1",
        "A1",
        "N1",
        "Kanton BE",
        "Hauptstrasse 12",
        "Km 12.5",
        "im Kanton ZH 2 Verletzte",
        "le canton VD 3 blessés",
        "ZH 079 123 45 67",
    ),
    source=RuleSource.MANDATORY,
    description="Swiss licence plate: canton code and up to six digits.",
)

#: A Swiss phone number: `0` and a two-digit area or mobile code, or `+41` /
#: `0041` with an optional `(0)`, then seven digits with optional single
#: separators. Short numbers (`117`, `144`, `1414`) are information, not
#: personal data, and have no leading zero, so they are never matched.
PHONE: Final = RegexRule(
    rule_id="phone",
    tag="Phone",
    pattern=(
        r"(?<![\d+])(?:(?:\+|00)41[ .\-]?(?:\(0\)[ .\-]?)?|0)"
        r"[1-9]\d(?:[ .\-/]?\d){7}(?!\d)"
    ),
    must_match=(
        "079 123 45 67",
        "+41 79 123 45 67",
        "0041 79 123 45 67",
        "044 123 45 67",
        "+41 (0)44 123 45 67",
        "0791234567",
        "044/123 45 67",
    ),
    must_not_match=(
        "117",
        "144",
        "1414",
        "um 14.30 Uhr",
        "12.03.2024",
        "80 km/h",
        "756.1234.5678.97",
        "Km 12.5",
    ),
    source=RuleSource.MANDATORY,
    description="Swiss phone number, national or international form.",
)

#: An email address: a local part, `@`, a domain with at least one dot and a
#: top-level part of two letters or more.
EMAIL: Final = RegexRule(
    rule_id="email",
    tag="Email",
    pattern=(
        r"(?<![\p{L}\p{M}\d._%+\-])[\p{L}\p{M}\d._%+\-]+@"
        r"[\p{L}\p{M}\d\-]+(?:\.[\p{L}\p{M}\d\-]+)*\.\p{L}{2,}(?![\p{L}\p{M}\d\-])"
    ),
    must_match=("a.b@example.ch", "x+y@sub.example.org", "Hans.Muster@bluewin.ch"),
    must_not_match=("B1@", "@", "a@b", "B1 @ G1"),
    source=RuleSource.MANDATORY,
    description="Email address.",
)

#: In this order: plates, phones, emails. The order breaks ties between
#: overlapping matches of equal start and length (§19.2).
MANDATORY_RULES: Final[tuple[RegexRule, ...]] = (LICENSE_PLATE, PHONE, EMAIL)

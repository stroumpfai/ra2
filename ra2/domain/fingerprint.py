# FROZEN (types and signature) — see CONTRACTS.md
"""The fingerprint (mvp-spec.md §8.5) — one function, two callers.

Built now (plan-phase-2.md Q3) so the Features draft can show the "· preview"
badge before an Evaluation exists to compute the real one. Evaluation-creation
code (phase 3) becomes this function's second caller, unchanged — the two
differ only in what `enum_codelist_json` snapshot they pass in, never in how
the hash is taken.

**M9 freezes `FingerprintInput` and the signature. D2 writes the body.**
"""

from dataclasses import dataclass

from ra2.domain.feature import Grain, Kind, ValueType

__all__ = ["FingerprintInput", "compute_fingerprint"]


@dataclass(frozen=True, slots=True)
class FingerprintInput:
    """The eight inputs, in mvp-spec.md §8.5's exact order.

    `derivation_json`, `matching_rule_json` and `enum_codelist_json` are
    already-canonical JSON strings — assembling that canonical form (stable
    key order, so the hash is stable) is the caller's job; this module only
    hashes what it is given.
    """

    kind: Kind
    grain: Grain
    #: `None` for a derived-aggregate or exploratory feature.
    source_column: str | None
    #: `None` unless `grain` is `DERIVED`.
    derivation_json: str | None
    value_type: ValueType
    matching_rule_json: str
    #: `None` unless `value_type` is `ENUM`. **Includes label text** — two
    #: runs against different code tables with the same codes and different
    #: labels asked the model different questions (mvp-spec.md §7).
    enum_codelist_json: str | None
    description: str


def compute_fingerprint(input: FingerprintInput) -> str:
    """`sha256` over a canonical JSON serialisation of the eight fields, in
    order (mvp-spec.md §8.5).

    Stable: the same input hashes the same way twice. Sensitive: changing any
    one of the eight fields changes the hash — the property that makes "two
    runs asked the model different questions" true.
    """
    raise NotImplementedError

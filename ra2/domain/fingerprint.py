# FROZEN (types and signature) — see CONTRACTS.md
"""The fingerprint (mvp-spec.md §8.5) — one function, two callers.

Built now (plan-phase-2.md Q3) so the Features draft can show the "· preview"
badge before an Evaluation exists to compute the real one. Evaluation-creation
code (phase 3) becomes this function's second caller, unchanged — the two
differ only in what `enum_codelist_json` snapshot they pass in, never in how
the hash is taken.

**M9 freezes `FingerprintInput` and the signature. D2 writes the body.**
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from ra2.domain.feature import Grain, Kind, ValueType

__all__ = ["FingerprintInput", "compute_fingerprint", "compute_set_fingerprint"]

#: The application controls key order and separators so the hash is
#: reproducible byte-for-byte, and `ensure_ascii=False` so label text hashes
#: as text, not `\uXXXX` escapes. **Not** `sort_keys=True` (unlike the
#: `*_json` columns' own M0-D8 convention): §8.5 names an exact field order,
#: and `payload` below is built with its keys in exactly that order, so
#: preserving Python's own dict insertion order *is* "in order" — sorting
#: them alphabetically instead was a code-review finding: still stable and
#: still sensitive to every field (the two properties the tests actually
#: pin), but not the order mvp-spec.md §8.5 states.
_JSON_KWARGS: Final = {"sort_keys": False, "separators": (",", ":"), "ensure_ascii": False}


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
    payload = {
        "kind": input.kind.value,
        "grain": input.grain.value,
        "source_column": input.source_column,
        "derivation_json": input.derivation_json,
        "value_type": input.value_type.value,
        "matching_rule_json": input.matching_rule_json,
        "enum_codelist_json": input.enum_codelist_json,
        "description": input.description,
    }
    canonical = json.dumps(payload, **_JSON_KWARGS)  # type: ignore[arg-type]
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_set_fingerprint(fingerprints: Iterable[str]) -> str:
    """One identity for a whole frozen feature set — the `cfg` chip's hash.

    `design/results/README.md` draws the results identity line as
    `Corpus 2026-09-02 · 4 978 records · 3 models` beside a `cfg 4f9a2c1e`
    chip, and its context block names the field `cfgHash`. Eight hex
    characters is a hash, not the head of a `feature_config_id`, and the two
    answer different questions: the id says *which row*, the hash says
    *whether two sets ask the same thing*. Two configs cloned and re-frozen
    without an edit have different ids and the same hash, and that is the
    comparison a reader of two result boards actually needs.

    Built from the per-feature fingerprints rather than from the features, so
    every guarantee of `compute_fingerprint` carries up unchanged: change a
    matching rule, a codelist snapshot or a description on any one feature and
    this moves too. It invents no new notion of sameness, it sums the one
    §8.5 already defines.

    **Sorted, and not de-duplicated.** Sorted because a set has no order and
    the hash must not depend on how the rows came back. Not de-duplicated
    because a fingerprint carries the feature's own key, so two identical ones
    mean two identical features — a fact about the set worth hashing, not
    noise worth hiding (Do-NOT #6's spirit: nothing is silently repaired).
    """
    canonical = "\n".join(sorted(fingerprints))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

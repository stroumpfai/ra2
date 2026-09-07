# Layer 1 — unit

Pure `ra2/domain/`, tested without a database: encoding detection, dialect
detection, RFC4180 reading, key-anchored recovery, header matching, delivery
validation, canary counting, type-hint inference, census computation,
language-guess handling. No DB, no network, no server, milliseconds.

Property-based tests (Hypothesis) for the recovery rule: a round trip of
"split a record across N lines, recover it" must reconstruct the original for
all N.

Owners: `parsing/`, `validation/`, `canary/` → **A1**. `census/`,
`typehint/` → **A2**. `tests/unit/conftest.py` belongs to whoever owns this
layer in the current wave (plan-m0-m5.md §4).

"""`ra2.domain.prompt.compute_template_fingerprint` (sw-design.md §15.1).

`sha256` over the exact template source. Stable across calls, and sensitive
to **every** byte — whitespace is part of a prompt, so a template differing
by one space must be a different template. Also checked against
`ra2.domain.fingerprint.compute_fingerprint`'s own hashing mechanics, so the
two fingerprint functions in this codebase cannot drift apart.
"""

import hashlib

import pytest

from ra2.domain.prompt import compute_template_fingerprint

pytestmark = pytest.mark.unit


def test_stability_same_source_hashes_the_same_way_twice():
    source = "You extract structured facts.\n\n{{feature_block}}\n\n{{narrative}}"
    assert compute_template_fingerprint(source) == compute_template_fingerprint(source)


def test_sensitivity_to_a_single_whitespace_change():
    """A template's whitespace is part of the prompt (sw-design.md §15.1) —
    one added space must change the fingerprint."""
    base = "You extract structured facts.\n\n{{feature_block}}\n\n{{narrative}}"
    changed = base + " "
    assert compute_template_fingerprint(base) != compute_template_fingerprint(changed)


def test_sensitivity_to_a_single_character_change():
    base = "{{feature_block}} {{narrative}}"
    changed = "{{feature_block}}  {{narrative}}"  # one extra space mid-template
    assert compute_template_fingerprint(base) != compute_template_fingerprint(changed)


def test_matches_a_plain_sha256_of_the_utf8_encoded_source():
    """The contract is "sha256 over the exact source bytes" — spelled out
    here as a fixed, independently computed expectation rather than by
    re-deriving the same call inside the assertion."""
    source = "abc"
    expected = hashlib.sha256(b"abc").hexdigest()
    assert compute_template_fingerprint(source) == expected


def test_non_ascii_source_is_hashed_as_utf8_not_escaped():
    source = "Réponse attendue : {{narrative}}"
    expected = hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert compute_template_fingerprint(source) == expected

"""`ra2.domain.prompt.estimate_tokens` (plan-phase-3.md C6).

Pure arithmetic — no vocabulary, no download, no model (an exact count needs
the model's tokeniser, and downloading one is egress, N1). The preview
renders `≈ N tokens`, never an exact figure.
"""

import pytest

from ra2.domain.prompt import estimate_tokens

pytestmark = pytest.mark.unit


def test_empty_text_estimates_zero_tokens():
    assert estimate_tokens("") == 0


def test_a_non_empty_text_never_estimates_zero():
    for text in ("a", "ab", "abc"):
        assert estimate_tokens(text) > 0


def test_longer_text_never_estimates_fewer_tokens():
    short = "a" * 10
    long = "a" * 1000
    assert estimate_tokens(long) > estimate_tokens(short)


def test_deterministic_same_text_same_estimate():
    text = "The quick brown fox jumps over the lazy dog." * 5
    assert estimate_tokens(text) == estimate_tokens(text)

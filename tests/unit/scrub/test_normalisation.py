"""The ASCII shortcut in the token normalisers (sw-design.md §19.3).

An ASCII token skips Unicode normalisation and the cache, because for ASCII
both normalisers are `lower()`. If that ever stopped being true, a list
entry and a narrative token could normalise differently and a name would
slip through, so it is held here for every ASCII token, not argued.
"""

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ra2.domain.scrub import (
    _stripped,
    _stripped_unicode,
    _transliterated,
    _transliterated_unicode,
)

pytestmark = pytest.mark.unit

_ASCII_TOKENS = st.text(alphabet=string.ascii_letters, min_size=1, max_size=24)


@given(_ASCII_TOKENS)
def test_an_ascii_token_normalises_as_the_unicode_path_would(token: str) -> None:
    assert _stripped(token) == _stripped_unicode(token)
    assert _transliterated(token) == _transliterated_unicode(token)


@pytest.mark.parametrize(
    ("token", "stripped", "transliterated"),
    [
        ("Müller", "muller", "mueller"),
        ("René", "rene", "rene"),
        ("Strauß", "strauss", "strauss"),
        ("MEIER", "meier", "meier"),
    ],
)
def test_a_non_ascii_token_still_takes_the_unicode_path(
    token: str, stripped: str, transliterated: str
) -> None:
    assert (_stripped(token), _transliterated(token)) == (stripped, transliterated)

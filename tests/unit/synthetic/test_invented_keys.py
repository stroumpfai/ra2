"""Whether a key was invented here or delivered (risk D8, `SD45`).

Errs towards *delivered*: a false "invented" would withhold a real ranking's
verdict, so every negative case below is a key that must stay real.
"""

import pytest

from ra2.domain.synthetic import all_invented, is_invented_key


def _uid(tag: str, number: int) -> str:
    """`generate_hazards.uid` and `seed_dev._uid`, restated."""
    return f"{tag}{number:0{32 - len(tag)}d}"


@pytest.mark.parametrize(
    "key",
    [
        _uid("aa", 1),
        _uid("ff", 999),
        _uid("a1", 48),
        _uid("c3", 3000),
        _uid("dd", 1_234_567),
        _uid("AA", 1),
    ],
)
def test_the_projects_own_keys_are_invented(key):
    assert is_invented_key(key)


@pytest.mark.parametrize(
    "key",
    [
        # Random-looking hex, made up for this test: the delivered shape.
        "7c3e9a51d2f84b06e1a9c5d3b7f20e84",
        "0000000a0000000000000000000000ff",  # zeros, but a hex tail
        "abcde00000000000000000000000001",  # 31 characters
        "abcde000000000000000000000000001",  # five-character tag
        "U" + "0" * 31,  # the scored-corpus fixture's shape is not hex
        "",
    ],
)
def test_other_keys_are_not(key):
    assert not is_invented_key(key)


def test_a_corpus_is_invented_only_if_every_key_is():
    invented = [_uid("aa", n) for n in range(1, 50)]
    assert all_invented(invented)
    assert not all_invented([*invented, "7c3e9a51d2f84b06e1a9c5d3b7f20e84"])


def test_an_empty_corpus_proves_nothing():
    assert not all_invented([])

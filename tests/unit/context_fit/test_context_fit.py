"""Will the longest prompt fit the model's context? (`SD53`, risk D1)."""

import pytest

from ra2.domain.context_fit import (
    ANSWER_RESERVE_TOKENS,
    LAUNCH_CONTEXT_SHARE,
    ContextFit,
    ContextSource,
    modelfile_context,
)


def _fit(prompt: int | None, context: int | None) -> ContextFit:
    source = None if context is None else ContextSource.MODELFILE
    return ContextFit(prompt_tokens=prompt, context_length=context, source=source)


def test_the_answer_reserve_and_the_share_are_the_agreed_ones() -> None:
    assert ANSWER_RESERVE_TOKENS == 1024
    assert LAUNCH_CONTEXT_SHARE == 0.90


@pytest.mark.parametrize(
    ("prompt", "context", "fits"),
    [
        # 90 % of 8192 is 7372.8, so 6348 + 1024 = 7372 fits and 7373 does not.
        (6348, 8192, True),
        (6349, 8192, False),
        (1000, 4096, True),
        (3000, 4096, False),  # the prompt alone fits; with the answer it does not
    ],
)
def test_prompt_plus_answer_must_stay_within_ninety_percent(
    prompt: int, context: int, fits: bool
) -> None:
    assert _fit(prompt, context).fits is fits


@pytest.mark.parametrize(("prompt", "context"), [(None, 8192), (1000, None), (1000, 0)])
def test_an_unknown_side_is_cannot_check_never_a_refusal(
    prompt: int | None, context: int | None
) -> None:
    assert _fit(prompt, context).fits is None


def test_needed_tokens_carries_the_reserve() -> None:
    assert _fit(1000, 8192).needed_tokens == 1000 + ANSWER_RESERVE_TOKENS
    assert _fit(None, 8192).needed_tokens is None


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        ({"num_ctx": ("8192",)}, 8192),
        ({"num_ctx": ("2048", "16384")}, 16384),  # the last one wins, as in a Modelfile
        ({"num_ctx": ('"4096"',)}, 4096),
        ({"temperature": ("0.6",)}, None),
        ({"num_ctx": ("lots",)}, None),
        ({"num_ctx": ("0",)}, None),
        ({}, None),
        (None, None),
    ],
)
def test_modelfile_context_reads_num_ctx_or_nothing(
    parameters: dict[str, tuple[str, ...]] | None, expected: int | None
) -> None:
    assert modelfile_context(parameters) == expected

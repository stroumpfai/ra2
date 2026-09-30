"""When a prompt counts as at the context limit (`SD48`, risk D1).

Ollama truncates rather than refuses, and the `prompt_tokens` it reports are
capped at the window, so a prompt at 95 % of it either was truncated or is one
feature description away. An extraction is flagged on evidence, never on the
absence of a number.
"""

import pytest

from ra2.domain.llm import CONTEXT_LIMIT_SHARE, at_context_limit


def test_the_share_is_ninety_five_percent() -> None:
    assert CONTEXT_LIMIT_SHARE == 0.95


@pytest.mark.parametrize(
    ("prompt_tokens", "context_length", "expected"),
    [
        (4096, 4096, True),  # truncated to exactly the window
        (3892, 4096, True),  # 95.02 %
        (3891, 4096, False),  # 94.99 %
        (1200, 4096, False),
        (8191, 8192, True),
    ],
)
def test_a_prompt_at_or_above_the_share_is_at_the_limit(
    prompt_tokens: int, context_length: int, expected: bool
) -> None:
    assert at_context_limit(prompt_tokens, context_length) is expected


@pytest.mark.parametrize(
    ("prompt_tokens", "context_length"),
    [(None, 4096), (4096, None), (None, None), (4096, 0)],
)
def test_an_unknown_is_never_flagged(prompt_tokens: int | None, context_length: int | None) -> None:
    assert at_context_limit(prompt_tokens, context_length) is False

# NEW — fix-d1-launch-context-check. Not frozen.
"""Will the longest prompt fit the model's context? (`SD53`, risk D1).

Ollama truncates a prompt that exceeds the context rather than refusing it,
and the model then answers about text it never saw: every feature of that
record scores `missing`, which is indistinguishable from a model that reads
badly. `SD48` flags that *after* a run. This decides it *before* one, so the
GPU-hours are not spent producing a wrong ranking.

The prompt side is an estimate (`domain.prompt.estimate_tokens`, about four
characters per token), and the context must also hold the model's answer.
So a model fits when the estimated prompt plus an answer reserve stays within
`LAUNCH_CONTEXT_SHARE` of its context: room for the estimate to be low (German
tokenises worse than four characters per token), and below the 95 % that the
after-the-fact flag uses, so a launch that passes here is unlikely to be
flagged there.

The context side is only ever a number someone **measured or configured**:
what an earlier run of this model and digest was actually loaded with on this
host, or the Modelfile's `num_ctx`. Never the model's trained maximum: the
server's default context is usually far smaller, and comparing with the
maximum would pass exactly the prompts that get truncated. With neither,
the answer is `None`, *cannot check*, and nothing is refused on a guess.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "ANSWER_RESERVE_TOKENS",
    "LAUNCH_CONTEXT_SHARE",
    "ContextFit",
    "ContextSource",
    "modelfile_context",
]

#: Room left for the model's answer: the JSON for every feature, with a
#: margin. The answer shares the context with the prompt.
ANSWER_RESERVE_TOKENS: Final = 1024

#: The share of the context the prompt and the answer reserve may use.
LAUNCH_CONTEXT_SHARE: Final = 0.90


class ContextSource(StrEnum):
    """Where the context number came from. Stable identifiers; wording is `ui/`'s."""

    #: An earlier run of this model and digest on this host was loaded with it
    #: (`run.context_length`, `SD48`). The strongest evidence there is.
    MEASURED = "measured"
    #: The model's Modelfile sets `PARAMETER num_ctx` (`/api/show`).
    MODELFILE = "modelfile"


@dataclass(frozen=True, slots=True)
class ContextFit:
    """The check for one model: the estimate, the context, and where it came from."""

    #: The estimated prompt for the longest record in the run's scope, or
    #: `None` when no prompt can be resolved yet (no template, no records).
    prompt_tokens: int | None
    context_length: int | None
    source: ContextSource | None

    @property
    def needed_tokens(self) -> int | None:
        """The estimated prompt plus the answer reserve."""
        if self.prompt_tokens is None:
            return None
        return self.prompt_tokens + ANSWER_RESERVE_TOKENS

    @property
    def fits(self) -> bool | None:
        """`True` / `False` when both sides are known; `None`: cannot check.

        Only `False` refuses a model. `None` never does.
        """
        needed = self.needed_tokens
        if needed is None or self.context_length is None or self.context_length <= 0:
            return None
        return needed <= LAUNCH_CONTEXT_SHARE * self.context_length


def modelfile_context(parameters: Mapping[str, tuple[str, ...]] | None) -> int | None:
    """`num_ctx` from a model's `/api/show` parameters, or `None`.

    The last value wins, as it does in a Modelfile. A value that is not a
    positive integer is not a context.
    """
    if not parameters:
        return None
    values = parameters.get("num_ctx")
    if not values:
        return None
    try:
        context = int(values[-1].strip().strip('"'))
    except ValueError:
        return None
    return context if context > 0 else None

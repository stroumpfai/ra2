"""`Settings` guards that fail at construction rather than at the first call.

There is one other setting in this file's spirit — `RA2_LLM_BASE_URL`, which
`OllamaLLMClient` refuses before any socket exists, "so a misconfigured host
fails at start, not at the first narrative". `RA2_LLM_REASONING_EFFORT` is the
second, and the arithmetic is what makes it worth a guard rather than a
docstring: an effort Ollama cannot map is rejected **per record**, one
`RA2_LLM_TIMEOUT_S` apart — 600 s each since the bound was measured against a
reasoning model — after the analyst has launched and walked away.
"""

from pathlib import Path

import pytest
from sqlalchemy import String

from ra2.infra.config import REASONING_EFFORTS, Settings

pytestmark = pytest.mark.backend


@pytest.mark.parametrize("effort", sorted(REASONING_EFFORTS))
def test_every_effort_ollama_maps_is_accepted(effort: str, tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, llm_reasoning_effort=effort, _env_file=None)
    assert settings.llm_reasoning_effort == effort


@pytest.mark.parametrize("effort", ["minimal", "xhigh", "max", "", "NONE", "off"])
def test_anything_ollama_cannot_map_is_refused_at_construction(effort: str, tmp_path: Path) -> None:
    """Deliberately narrower than the OpenAI SDK's literal.

    `minimal`, `xhigh` and `max` are real values in `openai`'s
    `ReasoningEffort` and are *not* values this endpoint understands — and the
    endpoint is the only one N1 permits the app to talk to, so its vocabulary
    is the real one. `NONE` is in the list because a case-insensitive guard
    would be a repair, and Do-NOT #6's spirit is that nothing is silently
    repaired.
    """
    with pytest.raises(ValueError, match="RA2_LLM_REASONING_EFFORT"):
        Settings(data_dir=tmp_path, llm_reasoning_effort=effort, _env_file=None)


def test_the_default_is_the_one_that_finishes_a_run(tmp_path: Path) -> None:
    """`none`, from a measurement rather than a preference.

    On the reporting host, one record with two features and one sentence of
    narrative against `qwen3.5:latest` (9.7 B Q4_K_M, CPU-bound), through the
    adapter's own call shape: 190 s at the model's own default against 6 s at
    `none`, both answering correctly. A default that cannot complete this
    product's own 12-record development seed inside `RA2_LLM_TIMEOUT_S` is not
    a default.
    """
    assert Settings(data_dir=tmp_path, _env_file=None).llm_reasoning_effort == "none"


def test_the_effort_is_pinned_on_the_run_and_not_only_in_the_environment() -> None:
    """The reason this is a setting and not a constant is that the comparison
    it enables has to survive the run.

    Asserted on the ORM column rather than through a run, because the claim is
    structural: without somewhere durable to record it, two evaluations that
    asked the model to think and not to think would be indistinguishable
    afterwards — and telling those apart is the product's subject, not an
    implementation detail (mvp-spec.md §19.8).
    """
    from ra2.persistence.models import Run

    column = Run.__table__.columns["llm_reasoning_effort"]
    assert column.nullable, "rows written before the column existed recorded no effort"
    assert isinstance(column.type, String)
    assert column.type.length == 16

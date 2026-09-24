"""`RA2_LLM_PARALLEL_CALLS` — records in flight per model (sw-design.md SD38).

Refused at construction for `RA2_LLM_REASONING_EFFORT`'s reason: a map the run
can't use should stop the app at start, not one `RA2_LLM_TIMEOUT_S` into a
run the analyst has walked away from.
"""

from pathlib import Path

import pytest

from ra2.infra.config import MAX_PARALLEL_CALLS, Settings

pytestmark = pytest.mark.backend


def test_the_default_runs_every_model_serially(tmp_path: Path) -> None:
    """`{}` is the behaviour from before the setting existed."""
    assert Settings(data_dir=tmp_path, _env_file=None).llm_parallel_calls == {}


@pytest.mark.parametrize("calls", [0, -1, MAX_PARALLEL_CALLS + 1, 64])
def test_settings_refuse_parallel_calls_outside_1_to_8(calls: int, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="RA2_LLM_PARALLEL_CALLS"):
        Settings(data_dir=tmp_path, llm_parallel_calls={"qwen3:8b": calls}, _env_file=None)


@pytest.mark.parametrize("calls", [1, MAX_PARALLEL_CALLS])
def test_the_bounds_themselves_are_accepted(calls: int, tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, llm_parallel_calls={"qwen3:8b": calls}, _env_file=None)
    assert settings.llm_parallel_calls == {"qwen3:8b": calls}


@pytest.mark.parametrize("tag", ["", "   "])
def test_settings_refuse_an_empty_model_tag(tag: str, tmp_path: Path) -> None:
    """An empty tag matches no model, so the entry would silently do nothing."""
    with pytest.raises(ValueError, match="empty model tag"):
        Settings(data_dir=tmp_path, llm_parallel_calls={tag: 4}, _env_file=None)


def test_the_environment_variable_is_read_as_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The form an operator actually writes."""
    monkeypatch.setenv("RA2_LLM_PARALLEL_CALLS", '{"qwen3:8b": 4, "granite4.1:8b": 1}')
    settings = Settings(data_dir=tmp_path, _env_file=None)
    assert settings.llm_parallel_calls == {"qwen3:8b": 4, "granite4.1:8b": 1}

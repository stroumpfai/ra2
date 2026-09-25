"""`just qualify-model`, driven through its real wiring against fake endpoints
(sw-design.md SD40, `plan-model-choice.md` Stage 3).

The script seeds a throwaway data dir, runs ordinary evaluations there through
`create_app`, and records one `model_qualification` row in the target database.
These tests hand it fake adapters through the same factories production uses,
so everything between the argument parser and the database is the code that
ships.

The fake answers are the §10.3 envelope with every seeded feature declared.
Per test, they're scripted per record and per pass, which is how a gate's
differ counts are made to come out at a known number.
"""

import hashlib
import importlib.util
import json
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tests.fixtures.fake_llm import DEFAULT_OLLAMA_VERSION, StaticModelCatalog
from tests.fixtures.migrations import upgrade_to_head

from ra2.domain.llm import Extraction, LLMClient, ModelCatalog, ModelInfo
from ra2.domain.qualification import GateVerdict
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuInfo, StaticGpuProbe

pytestmark = pytest.mark.backend

REPO_ROOT = Path(__file__).resolve().parents[3]
TAG = "qwen3:8b"
DIGEST = "500a1f067a9f"
ONE_SLOT = "http://127.0.0.1:11434/v1"
N_SLOT = "http://127.0.0.1:11435/v1"
#: Small enough to keep the file quick, large enough for the seed's case plan.
SMALL = ["--records", "40", "--gate-records", "20"]

#: The seed's seven feature keys (`scripts/seed_dev.py::_seed_features`).
FEATURE_KEYS = (
    "UnfZeitFeld",
    "UnfDatumFeld",
    "AnzObjFeld",
    "UnfTypAusw",
    "objects_involved",
    "anyone_injured",
    "phone_use",
)

#: Planted in every fake answer. It must never reach the terminal or a log.
CANARY = "CANARY-7f3a-answer-text"


def _answer(*, flipped: bool = False, entities: bool = False) -> str:
    features: dict[str, Any] = {
        key: {"value": None, "present": False, "evidence": None} for key in FEATURE_KEYS
    }
    features["anyone_injured"] = {
        "value": flipped,
        "present": True,
        "evidence": CANARY,
    }
    return json.dumps(
        {
            "features": features,
            "entities": [{"kind": "vehicle", "ref": "B1"}] if entities else [],
        }
    )


def _flips(text: str) -> bool:
    """A fixed, content-derived fifth of the records."""
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % 5 == 0


class ScriptedPass:
    """An `LLMClient` for one pass. `flip` decides whether this pass answers
    the flipping records differently, so a test knows exactly how many records
    two passes disagree on."""

    def __init__(self, *, flip: bool, entities_every: int = 0) -> None:
        self._flip = flip
        self._entities_every = entities_every
        self.prompts: list[str] = []

    async def extract[T](
        self,
        text: str,
        schema: type[T],
        model: str,
        *,
        temperature: float,
        seed: int,
        reasoning_effort: str | None = None,
    ) -> Extraction[T]:
        index = len(self.prompts)
        self.prompts.append(text)
        entities = bool(self._entities_every) and index % self._entities_every == 0
        raw = _answer(flipped=self._flip and _flips(text), entities=entities)
        return Extraction[T](
            value=None,
            raw_output_text=raw,
            parse_ok=True,
            latency_ms=10,
            prompt_tokens=len(text) // 4,
            completion_tokens=len(raw) // 4,
        )


class Endpoints:
    """The factories `main` takes. Records every client it hands out, per URL
    and in order, so a test can ask what each pass was sent."""

    def __init__(
        self,
        *,
        flip_on: Callable[[str, int], bool] = lambda url, parallel: False,
        catalogs: dict[str, StaticModelCatalog] | None = None,
        entities_every: int = 0,
    ) -> None:
        self._flip_on = flip_on
        self._entities_every = entities_every
        self.catalogs = catalogs or {
            url: StaticModelCatalog([ModelInfo(tag=TAG, digest=DIGEST, size_bytes=5_200_000_000)])
            for url in (ONE_SLOT, N_SLOT)
        }
        self.clients: list[tuple[str, int, ScriptedPass]] = []

    def catalog_for(self, url: str, settings: Settings) -> ModelCatalog:
        return self.catalogs[url]

    def client_for(self, url: str, settings: Settings) -> LLMClient:
        parallel = settings.llm_parallel_calls.get(TAG, 1)
        client = ScriptedPass(
            flip=self._flip_on(url, parallel), entities_every=self._entities_every
        )
        self.clients.append((url, parallel, client))
        return client

    @property
    def calls(self) -> int:
        return sum(len(client.prompts) for _, _, client in self.clients)


@pytest.fixture
def qualify_model() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ra2_qualify_model", REPO_ROOT / "scripts" / "qualify_model.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def target(tmp_path: Path) -> Settings:
    """The analyst's data dir, migrated and otherwise empty."""
    settings = Settings(
        data_dir=tmp_path / "target",
        db_path=tmp_path / "target" / "ra2.sqlite",
        _env_file=None,
    )
    upgrade_to_head(settings)
    return settings


@pytest.fixture
def workdirs(qualify_model: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every throwaway dir the script creates, so a test can check it's gone."""
    created: list[Path] = []
    real = qualify_model.tempfile.mkdtemp

    def recording_mkdtemp(*args: Any, **kwargs: Any) -> str:
        path: str = real(*args, **kwargs)
        created.append(Path(path))
        return path

    monkeypatch.setattr(qualify_model.tempfile, "mkdtemp", recording_mkdtemp)
    return created


def _row_counts(settings: Settings) -> dict[str, int]:
    with closing(sqlite3.connect(settings.database_path)) as conn:
        tables = [
            name
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def _recorded(settings: Settings) -> list[tuple[str, str, str, str]]:
    with closing(sqlite3.connect(settings.database_path)) as conn:
        return conn.execute(
            "SELECT model_tag, model_digest, quality_json, gate_json FROM model_qualification"
        ).fetchall()


def _run(
    qualify_model: ModuleType,
    target: Settings,
    endpoints: Endpoints,
    argv: list[str],
    lines: list[str] | None = None,
) -> int:
    code: int = qualify_model.main(
        argv,
        target=target,
        catalog_for=endpoints.catalog_for,
        client_for=endpoints.client_for,
        gpu_probe=StaticGpuProbe(GpuInfo(name="Test GPU", total_vram_bytes=16 * 1024**3)),
        out=(lines if lines is not None else []).append,
    )
    return code


# ===========================================================================
# What reaches the target database
# ===========================================================================


def test_the_qualifier_never_touches_the_target_data_dir_except_to_record(
    qualify_model: ModuleType, target: Settings
) -> None:
    before = _row_counts(target)

    assert _run(qualify_model, target, Endpoints(), [TAG, *SMALL]) == 0

    after = _row_counts(target)
    assert after.pop("model_qualification") == before.pop("model_qualification") + 1
    assert after == before


def test_summarise_derives_quality_from_an_ordinary_run(
    qualify_model: ModuleType, target: Settings
) -> None:
    """Every record answered, one in four with an entity, none failing to
    parse: the figures come back as that."""
    endpoints = Endpoints(entities_every=4)

    assert _run(qualify_model, target, endpoints, [TAG, *SMALL]) == 0

    [(tag, digest, quality_json, gate_json)] = _recorded(target)
    quality = json.loads(quality_json)
    assert (tag, digest, gate_json) == (TAG, DIGEST, "[]")
    assert quality["records"] == 40
    assert quality["parse_failures"] == 0
    assert quality["entity_fill"] == 0.25
    assert quality["reasoning_effort"] == target.llm_reasoning_effort
    assert quality["median_latency_ms"] == 10
    # The ranking's own figures, copied. Not asserted to bracket the point:
    # `stats.macro_interval` (P4-D1) centres on the mean of the Wilson
    # centres, which near 0 sits above the point estimate.
    assert 0.0 <= quality["macro_f1_low"] <= quality["macro_f1_high"] <= 1.0
    assert 0.0 <= quality["macro_f1"] <= 1.0


# ===========================================================================
# The gate
# ===========================================================================


def test_summarise_counts_differing_answers_between_cloned_passes(
    qualify_model: ModuleType, target: Settings
) -> None:
    """Only the parallel pass answers a fifth of the records differently. The
    recorded gate says exactly how many, and that the serial passes agree."""
    endpoints = Endpoints(flip_on=lambda url, parallel: parallel > 1)

    assert (
        _run(qualify_model, target, endpoints, [TAG, *SMALL, "--gate", "4", "--n-slot", N_SLOT])
        == 0
    )

    parallel_pass = [c for url, n, c in endpoints.clients if url == N_SLOT and n == 4]
    assert len(parallel_pass) == 1
    flipped = sum(1 for prompt in parallel_pass[0].prompts if _flips(prompt))
    assert flipped > 0, "the fixture must actually flip something"

    [(_, _, _, gate_json)] = _recorded(target)
    [gate] = json.loads(gate_json)
    assert gate["n"] == 4
    assert gate["records"] == 20
    assert gate["serial_on_n_slot_differ"] == 0
    assert gate["parallel_differ"] == flipped
    assert gate["noise_band"] == 1
    assert gate["verdict"] == (
        GateVerdict.PASSES.value if flipped <= 1 else GateVerdict.FAILS_PARALLEL.value
    )


def test_the_gate_runs_three_baseline_passes_then_two_per_n(
    qualify_model: ModuleType, target: Settings
) -> None:
    endpoints = Endpoints()

    assert (
        _run(qualify_model, target, endpoints, [TAG, *SMALL, "--gate", "2,4", "--n-slot", N_SLOT])
        == 0
    )

    passes = [(url, n) for url, n, client in endpoints.clients if client.prompts]
    assert passes == [
        (ONE_SLOT, 1),  # quality, 40 records
        (ONE_SLOT, 1),
        (ONE_SLOT, 1),
        (ONE_SLOT, 1),  # the baseline
        (N_SLOT, 1),
        (N_SLOT, 2),
        (N_SLOT, 1),
        (N_SLOT, 4),
    ]


def test_gate_without_an_n_slot_endpoint_is_refused_before_any_call(
    qualify_model: ModuleType, target: Settings
) -> None:
    endpoints = Endpoints()
    lines: list[str] = []

    assert _run(qualify_model, target, endpoints, [TAG, *SMALL, "--gate", "4"], lines) == 2

    assert endpoints.calls == 0
    assert "--n-slot" in lines[-1]
    assert _recorded(target) == []


def test_the_two_servers_must_agree_on_digest_and_version(
    qualify_model: ModuleType, target: Settings
) -> None:
    catalogs = {
        ONE_SLOT: StaticModelCatalog([ModelInfo(tag=TAG, digest=DIGEST, size_bytes=1)]),
        N_SLOT: StaticModelCatalog(
            [ModelInfo(tag=TAG, digest=DIGEST, size_bytes=1)], version="0.35.0"
        ),
    }
    endpoints = Endpoints(catalogs=catalogs)
    lines: list[str] = []

    code = _run(
        qualify_model, target, endpoints, [TAG, *SMALL, "--gate", "4", "--n-slot", N_SLOT], lines
    )

    assert code == 2
    assert endpoints.calls == 0
    assert DEFAULT_OLLAMA_VERSION in lines[-1] and "0.35.0" in lines[-1]


# ===========================================================================
# Refusals
# ===========================================================================


def test_a_non_loopback_endpoint_is_refused(qualify_model: ModuleType, target: Settings) -> None:
    """Through `OllamaModelCatalog`'s own guard: the script has no second
    check to drift from the first, and the refusal comes before a socket."""
    lines: list[str] = []

    code = qualify_model.main(
        [TAG, *SMALL, "--one-slot", "http://10.0.0.5:11434/v1"],
        target=target,
        out=lines.append,
    )

    assert code == 2
    assert "10.0.0.5" in lines[-1]
    assert _recorded(target) == []


def test_a_tag_the_endpoint_does_not_offer_is_refused(
    qualify_model: ModuleType, target: Settings
) -> None:
    endpoints = Endpoints()
    lines: list[str] = []

    assert _run(qualify_model, target, endpoints, ["never:pulled", *SMALL], lines) == 2

    assert endpoints.calls == 0
    assert "ollama pull" in lines[-1]


def test_another_loaded_model_refuses_the_pass(qualify_model: ModuleType, target: Settings) -> None:
    """A resident model squeezes the measured one out of VRAM and the timings
    lie (`plan-parallel-calls.md` §1.1 point 3)."""
    endpoints = Endpoints()
    endpoints.catalogs[ONE_SLOT].loaded_tags = ("gemma4:12b", TAG)
    lines: list[str] = []

    assert _run(qualify_model, target, endpoints, [TAG, *SMALL], lines) == 2

    assert endpoints.calls == 0
    assert "gemma4:12b" in lines[-1]
    assert _recorded(target) == []


@pytest.mark.parametrize("gate", ["1", "x", "4,0"])
def test_a_gate_value_below_two_is_refused(
    qualify_model: ModuleType, target: Settings, gate: str
) -> None:
    lines: list[str] = []

    code = _run(
        qualify_model, target, Endpoints(), [TAG, "--gate", gate, "--n-slot", N_SLOT], lines
    )

    assert code == 2
    assert "--gate" in lines[-1]


# ===========================================================================
# What is left behind, and what is said
# ===========================================================================


@pytest.mark.parametrize("fails", [False, True], ids=["success", "refusal"])
def test_the_qualifier_deletes_its_throwaway_dir(
    qualify_model: ModuleType, target: Settings, workdirs: list[Path], fails: bool
) -> None:
    endpoints = Endpoints()
    if fails:
        endpoints.catalogs[ONE_SLOT].loaded_tags = ("gemma4:12b",)

    _run(qualify_model, target, endpoints, [TAG, *SMALL])

    assert len(workdirs) == 1
    assert not workdirs[0].exists()
    assert not workdirs[0].is_relative_to(target.data_dir)


def test_the_qualifier_prints_no_answer_text(
    qualify_model: ModuleType,
    target: Settings,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    lines: list[str] = []
    endpoints = Endpoints(flip_on=lambda url, parallel: parallel > 1)

    code = _run(
        qualify_model, target, endpoints, [TAG, *SMALL, "--gate", "4", "--n-slot", N_SLOT], lines
    )

    assert code == 0
    captured = capsys.readouterr()
    for channel in ("\n".join(lines), captured.out, captured.err, caplog.text):
        assert CANARY not in channel
    with closing(sqlite3.connect(target.database_path)) as conn:
        stored = "".join(
            str(v) for row in conn.execute("SELECT * FROM model_qualification") for v in row
        )
    assert CANARY not in stored

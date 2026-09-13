"""The GPU probe (sw-design.md §15.6, SD15, plan-phase-3.md R2).

NVML is stubbed **present and absent**, because the suite has to pass on the
target machine *and* on a laptop with no NVIDIA card — and because "absent" is
the branch that has to answer `None` rather than raise (plan-phase-3.md §11).

Nothing here runs `nvidia-smi`, and `test_nvml_is_named_only_by_this_module`
is the local gate that keeps it that way while
`contracts/amendments/feat-p3-llm-adapter.md` is open.
"""

import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from ra2.infra.gpu import GpuInfo, GpuProbe, NvmlGpuProbe, StaticGpuProbe, probe_for

pytestmark = pytest.mark.backend

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The design's host: "gpu RTX 4090 24 GB".
FIXTURE_NAME = "NVIDIA GeForce RTX 4090"
FIXTURE_VRAM = 25_757_220_864


class FakeNvml(ModuleType):
    """A stand-in for `pynvml`, built the way the real binding behaves.

    `nvidia-ml-py` is a `ctypes` wrapper: `nvmlDeviceGetName` returns `str` on
    current versions and `bytes` on older ones, and every call can raise
    `NVMLError`. Both shapes are exercised. The method names are NVML's own
    camelCase, deliberately — a double that renames them proves nothing.
    """

    def __init__(
        self,
        *,
        name: str | bytes = FIXTURE_NAME,
        total: int = FIXTURE_VRAM,
        device_count: int = 1,
        init_error: BaseException | None = None,
        device_error: BaseException | None = None,
        shutdown_error: BaseException | None = None,
        missing_memory_info: bool = False,
    ) -> None:
        super().__init__("pynvml")
        self._name = name
        self._total = total
        self._device_count = device_count
        self._init_error = init_error
        self._device_error = device_error
        self._shutdown_error = shutdown_error
        self._missing_memory_info = missing_memory_info
        self.init_calls = 0
        self.shutdown_calls = 0
        self.handles: list[int] = []

    def nvmlInit(self) -> None:
        self.init_calls += 1
        if self._init_error is not None:
            raise self._init_error

    def nvmlShutdown(self) -> None:
        self.shutdown_calls += 1
        if self._shutdown_error is not None:
            raise self._shutdown_error

    def nvmlDeviceGetCount(self) -> int:
        return self._device_count

    def nvmlDeviceGetHandleByIndex(self, index: int) -> int:
        if self._device_error is not None:
            raise self._device_error
        self.handles.append(index)
        return index

    def nvmlDeviceGetName(self, handle: int) -> str | bytes:
        return self._name

    def nvmlDeviceGetMemoryInfo(self, handle: int) -> Any:
        if self._missing_memory_info:
            # What a driver/binding mismatch looks like: the symbol is not bound.
            raise AttributeError("nvmlDeviceGetMemoryInfo")
        return SimpleNamespace(total=self._total, free=0, used=self._total)


class NvmlError(Exception):
    """`pynvml.NVMLError`'s stand-in — it is a plain `Exception` subclass."""


@pytest.fixture
def nvml(monkeypatch: pytest.MonkeyPatch) -> FakeNvml:
    """NVML **present**, reporting the design's GPU."""
    module = FakeNvml()
    monkeypatch.setitem(sys.modules, "pynvml", module)
    return module


@pytest.fixture
def no_nvml(monkeypatch: pytest.MonkeyPatch) -> None:
    """NVML **absent**. `None` in `sys.modules` is what the interpreter uses
    to mean "this import fails", so no real library is needed to prove the
    branch — the suite runs identically on the target host and on a laptop."""
    monkeypatch.setitem(sys.modules, "pynvml", None)


def install(monkeypatch: pytest.MonkeyPatch, module: FakeNvml) -> FakeNvml:
    monkeypatch.setitem(sys.modules, "pynvml", module)
    return module


# ===========================================================================
# NVML present
# ===========================================================================


def test_the_probe_reads_name_and_total_vram_from_nvml(nvml: FakeNvml) -> None:
    info = NvmlGpuProbe().describe()

    assert info == GpuInfo(name=FIXTURE_NAME, total_vram_bytes=FIXTURE_VRAM)


def test_the_probe_reports_decimal_gb_so_the_two_numbers_compare(nvml: FakeNvml) -> None:
    """The design renders "24 GB" beside a model's size, and Ollama reports
    sizes in decimal."""
    info = NvmlGpuProbe().describe()

    assert info is not None
    assert round(info.total_vram_gb) == 26


def test_the_probe_reads_device_zero_only(nvml: FakeNvml) -> None:
    """A multi-GPU host is out of scope: Ollama loads one model on one
    device, and the design shows one VRAM figure."""
    NvmlGpuProbe().describe()

    assert nvml.handles == [0]


def test_an_older_binding_returning_bytes_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeNvml(name=FIXTURE_NAME.encode("utf-8")))

    info = NvmlGpuProbe().describe()

    assert info is not None
    assert info.name == FIXTURE_NAME


def test_nvml_is_shut_down_after_a_successful_probe(nvml: FakeNvml) -> None:
    NvmlGpuProbe().describe()

    assert nvml.init_calls == 1
    assert nvml.shutdown_calls == 1


def test_a_failing_shutdown_does_not_lose_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeNvml(shutdown_error=NvmlError("uninitialised")))

    info = NvmlGpuProbe().describe()

    assert info == GpuInfo(name=FIXTURE_NAME, total_vram_bytes=FIXTURE_VRAM)


def test_the_probe_can_be_asked_twice(nvml: FakeNvml) -> None:
    """Nothing is cached, so a second ask re-initialises rather than reusing a
    handle from a shut-down session."""
    first = NvmlGpuProbe().describe()
    second = NvmlGpuProbe().describe()

    assert first == second
    assert nvml.init_calls == 2
    assert nvml.shutdown_calls == 2


# ===========================================================================
# NVML absent, or honest about having nothing to say
# ===========================================================================


def test_the_probe_is_none_when_nvml_is_absent(no_nvml: None) -> None:
    """`None` is **not an error** (sw-design.md §15.6): no NVIDIA GPU means no
    `fits_vram` judgement and every model selectable."""
    assert NvmlGpuProbe().describe() is None


def test_the_probe_is_none_when_nvml_will_not_initialise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The library is installed but the driver is not — the everyday state of
    a CI runner with `nvidia-ml-py` in its lockfile."""
    module = install(monkeypatch, FakeNvml(init_error=NvmlError("driver not loaded")))

    assert NvmlGpuProbe().describe() is None
    assert module.shutdown_calls == 0


def test_the_probe_is_none_when_there_are_no_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    module = install(monkeypatch, FakeNvml(device_count=0))

    assert NvmlGpuProbe().describe() is None
    assert module.shutdown_calls == 1


def test_the_probe_is_none_when_a_device_call_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeNvml(device_error=NvmlError("gpu is lost")))

    assert NvmlGpuProbe().describe() is None


def test_a_symbol_missing_from_an_old_binding_is_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A driver/binding mismatch leaves a symbol unbound. That is still "no
    honest answer", not an exception out of `create_app()`."""
    install(monkeypatch, FakeNvml(missing_memory_info=True))

    assert NvmlGpuProbe().describe() is None


def test_a_name_that_does_not_decode_is_not_a_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """N4: the encoding is stated and `errors="replace"` is never used, so an
    undecodable name yields `None` rather than a row of replacement
    characters in a run's provenance."""
    install(monkeypatch, FakeNvml(name=b"\xff\xfe not utf-8"))

    assert NvmlGpuProbe().describe() is None


def test_a_zero_vram_report_is_not_a_judgement(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeNvml(total=0))

    assert NvmlGpuProbe().describe() is None


def test_the_probe_satisfies_the_frozen_protocol() -> None:
    assert isinstance(NvmlGpuProbe(), GpuProbe)


# ===========================================================================
# probe_for — the override wins, else NVML (P3-D9)
# ===========================================================================


def test_probe_for_prefers_a_declared_capability(nvml: FakeNvml) -> None:
    """A configured `RA2_GPU_VRAM_GB` beats a probed one, and is the only way
    a host with an AMD or Intel GPU gets a `fits_vram` judgement at all (R2)."""
    probe = probe_for(name="Radeon RX 7900 XTX", vram_gb=24.0)

    assert isinstance(probe, StaticGpuProbe)
    assert probe.describe() == GpuInfo(name="Radeon RX 7900 XTX", total_vram_bytes=24_000_000_000)
    assert nvml.init_calls == 0


def test_probe_for_asks_nvml_when_nothing_is_configured(nvml: FakeNvml) -> None:
    probe = probe_for(name=None, vram_gb=None)

    assert isinstance(probe, NvmlGpuProbe)
    assert probe.describe() == GpuInfo(name=FIXTURE_NAME, total_vram_bytes=FIXTURE_VRAM)


def test_probe_for_answers_unknown_on_a_host_with_no_nvml(no_nvml: None) -> None:
    """The laptop case, and the one that has to keep the whole suite
    runnable."""
    assert probe_for(name=None, vram_gb=None).describe() is None


# ===========================================================================
# N3 — no shell-outs, and NVML stays in one module
# ===========================================================================


def test_nvml_is_named_only_by_this_module() -> None:
    """The local gate that stands in for `.importlinter` while
    `contracts/amendments/feat-p3-llm-adapter.md` is open.

    `ra2/infra/gpu.py` loads NVML through `importlib.import_module` rather
    than a static `import pynvml`, because the frozen `one-llm-seam` contract
    does not set `allow_indirect_imports` and the sanctioned
    `services -> infra.gpu` protocol import therefore reads a static edge as a
    violation. `import-linter` cannot see a dynamic load — so this test does,
    and it is **stricter** than the AST import scan in `test_p3_contract.py`:
    it catches `import pynvml`, `importlib.import_module("pynvml")` and
    `__import__("pynvml")` alike.
    """
    offenders = set()
    for path in sorted(REPO_ROOT.joinpath("ra2").rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            ast.get_docstring(node, clean=False)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        }
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Call):
                names = [
                    argument.value
                    for argument in node.args
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                ]
            if any(name.split(".")[0] == "pynvml" and name not in docstrings for name in names):
                offenders.add(relative)

    assert offenders == {"ra2/infra/gpu.py"}


def test_the_probe_never_shells_out() -> None:
    """N3, and plan-phase-3.md R2's named failure mode. `test_p3_contract.py`
    gates the whole package; this one is on the module that has the obvious
    temptation, so a reader of the probe's tests sees the rule."""
    source = REPO_ROOT.joinpath("ra2/infra/gpu.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "subprocess" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "subprocess"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "nvidia-smi" not in node.value or node.value in docstrings

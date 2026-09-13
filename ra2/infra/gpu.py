# FROZEN (protocol and StaticGpuProbe) — see CONTRACTS.md
"""The GPU probe (sw-design.md §15.6, SD15).

The design disables a model that "exceeds 24 GB VRAM". Ollama reports tag,
digest and size; it does **not** report the host's VRAM. So VRAM is probed,
behind a protocol like every other host fact.

**Never `nvidia-smi`, never any subprocess.** N3 forbids shell-outs;
`NvmlGpuProbe` reads GPU name and total VRAM through the NVML *library*
bindings (`nvidia-ml-py` — a `ctypes` load of `libnvidia-ml`, present wherever
the GPU is, on Windows and Linux alike), and a library load is not a shell-out.
Read this rule as written: the next reader reaching for `nvidia-smi` because
"it is only a probe" is the failure mode this paragraph exists to prevent.

`None` is **not an error**. No NVIDIA GPU means no `fits_vram` judgement, every
model selectable, and the design's disabled row simply does not occur.
Declared capability beats guessed capability, and "unknown" beats either when
it is the truth.

**M17 freezes `GpuInfo`, `GpuProbe` and `StaticGpuProbe`. H4 writes
`NvmlGpuProbe`'s body** — it is the only class here that may import `pynvml`,
and `.importlinter`'s `one-llm-seam` contract keeps that import out of every
package above `ra2/infra/`.
"""

from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["GpuInfo", "GpuProbe", "NvmlGpuProbe", "StaticGpuProbe", "probe_for"]


@dataclass(frozen=True, slots=True)
class GpuInfo:
    """One GPU's name and total memory.

    `name` is the design's "RTX 4090" and lands verbatim in every run's
    provenance (mvp-spec.md §19.8). `total_vram_bytes` is what a model's
    `size_bytes` is compared against to decide `fits_vram`.
    """

    name: str
    total_vram_bytes: int

    @property
    def total_vram_gb(self) -> float:
        """The design renders "24 GB". Decimal GB, matching how Ollama reports
        model sizes, so the two numbers on one row are comparable."""
        return self.total_vram_bytes / 1_000_000_000


@runtime_checkable
class GpuProbe(Protocol):
    """`None` = no NVIDIA GPU, or NVML not present. Not an error (Q3)."""

    def describe(self) -> GpuInfo | None:
        """The host's GPU, or `None` when there is nothing honest to say.

        Synchronous and cheap: a library call, not I/O worth awaiting.
        """
        ...


class StaticGpuProbe:
    """A fixed answer — the `RA2_GPU_VRAM_GB` / `RA2_GPU_NAME` overrides, and
    the tests' substitute (sw-design.md §15.6).

    Construct with no arguments for the honest "unknown" state, which is what
    a laptop with no NVIDIA GPU gets and what keeps the whole suite runnable
    there.
    """

    def __init__(self, info: GpuInfo | None = None) -> None:
        self._info = info

    @classmethod
    def from_overrides(cls, *, name: str | None, vram_gb: float | None) -> StaticGpuProbe:
        """Build from `Settings.gpu_name` / `Settings.gpu_vram_gb`.

        Both unset -> the unknown probe. A VRAM figure with no name still
        counts: the number is what gates a model, the name is provenance.
        """
        if vram_gb is None:
            return cls(None)
        return cls(GpuInfo(name=name or "unknown", total_vram_bytes=int(vram_gb * 1_000_000_000)))

    def describe(self) -> GpuInfo | None:
        return self._info


class NvmlGpuProbe:
    """NVML through `nvidia-ml-py` — a `ctypes` load, **no subprocess** (N3).

    **Body owned by H4 (`feat/p3-llm-adapter`).** The import of
    `pynvml` belongs inside `describe()`, not at module scope: this module is
    imported by `ra2.main` on every start, including on hosts where NVML is
    absent, and an import-time failure there would turn "no GPU" into "the app
    does not boot". `describe()` must swallow NVML's own errors and return
    `None` — absence is the honest answer, not an exception.

    Device 0 only. A multi-GPU host is out of scope for the MVP: Ollama loads
    one model on one device, and the design shows one VRAM figure.
    """

    def describe(self) -> GpuInfo | None:
        # The load is deliberately here and not at module scope: `ra2.main`
        # imports this module on every start, including on hosts where
        # `libnvidia-ml` is absent, and an import-time failure there would turn
        # "no GPU" into "the app does not boot".
        try:
            import pynvml  # type: ignore[import-untyped]  # noqa: PLC0415
        except ImportError:
            return None

        # Everything below is a `ctypes` call into `libnvidia-ml`. It fails in
        # more ways than `NVMLError` covers — the library may be missing
        # (`OSError`), a driver mismatch may leave a symbol unbound
        # (`AttributeError`), an old binding may not expose a call at all — and
        # every one of them means the same thing: there is nothing honest to
        # say about this host's GPU. `None` is that answer, and it is not an
        # error (sw-design.md §15.6).
        initialised = False
        try:
            pynvml.nvmlInit()
            initialised = True
            if pynvml.nvmlDeviceGetCount() < 1:
                return None
            # Device 0 only: Ollama loads one model on one device and the
            # design shows one VRAM figure. A multi-GPU host is out of scope.
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            raw_name = pynvml.nvmlDeviceGetName(handle)
            total_vram_bytes = int(pynvml.nvmlDeviceGetMemoryInfo(handle).total)
        except Exception:
            return None
        finally:
            if initialised:
                # A failed shutdown is not news, and not worth losing the
                # answer over.
                with suppress(Exception):
                    pynvml.nvmlShutdown()

        # Older bindings hand back a C string; newer ones decode for us. N4
        # applies to the decode too: the encoding is stated, and never
        # `errors="replace"` — a name we cannot decode is not a name.
        if isinstance(raw_name, bytes | bytearray):
            try:
                name = bytes(raw_name).decode("utf-8")
            except UnicodeDecodeError:
                return None
        else:
            name = str(raw_name)
        if not name or total_vram_bytes <= 0:
            return None
        return GpuInfo(name=name, total_vram_bytes=total_vram_bytes)


def probe_for(*, name: str | None, vram_gb: float | None) -> GpuProbe:
    """The probe `create_app()` uses: **the override wins, else NVML**.

    A configured `RA2_GPU_VRAM_GB` is a declared capability and beats a
    guessed one — it is also the only way a host with an AMD or Intel GPU gets
    a `fits_vram` judgement at all (R2). With nothing configured, ask NVML;
    with no NVML, `NvmlGpuProbe` answers `None` and the UI says so.

    Lives here rather than in `create_app()` so the composition root stays
    wiring and this one rule has one home.
    """
    if vram_gb is not None:
        return StaticGpuProbe.from_overrides(name=name, vram_gb=vram_gb)
    return NvmlGpuProbe()

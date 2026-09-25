#!/usr/bin/env python
"""`just qualify-model <tag>` — measure one model on this host (sw-design.md SD40).

```
just qualify-model qwen3:8b
just qualify-model qwen3:8b --gate 2,4 --n-slot http://127.0.0.1:11435/v1
```

**What it measures.** One serial pass over the 200-record synthetic seed,
scored exactly as an evaluation is: macro-F1 and its interval, per-language
F1, time per record, output length and how often the model fills `entities`.
With `--gate`, it also runs `plan-parallel-calls.md` §4.1's gate over the
seed's first 48 records: three serial passes on the one-slot server for the
noise band, then for each N a serial and an N-call pass on the N-slot server.

**Where.** Every pass runs in a **throwaway data dir** in the system temp
directory, seeded through `seed_dev`'s own functions, and removed at the end,
on failure too. The configured `RA2_DATA_DIR` receives exactly one thing: the
`model_qualification` row. No corpus of the target database is ever opened,
so no delivery content can reach a measurement.

**Whose servers.** RA2 can't read `OLLAMA_NUM_PARALLEL`, so the operator
names the two servers: `--one-slot` (default `RA2_LLM_BASE_URL`) and
`--n-slot`, which `--gate` requires. Both go through the real adapter, so both
must be loopback, with no opt-out (§15.5). This script **never starts or
stops Ollama**. `docs/performance.md` §5.4 says how to run a private N-slot
server beside the system one.

**What it prints.** Counts, times, scores and the verdict. Never an answer:
the gate compares answers by fingerprint (`QualificationService`), and
nothing here holds model text (data-handling.md §5).

It is wiring, like `seed_dev.py`. The comparisons are
`ra2.domain.qualification`'s, and the figures are `QualificationService`'s.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.metadata
import importlib.util
import io
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Final

from sqlalchemy.ext.asyncio import AsyncEngine

from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    FeatureConfigId,
    QualificationId,
    RecordId,
    RunId,
)
from ra2.domain.llm import LLMClient, LlmEndpointError, ModelCatalog
from ra2.domain.qualification import (
    GateResult,
    Qualification,
    QualitySummary,
    gate_result,
)
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuProbe, probe_for
from ra2.infra.idgen import Uuid7Factory
from ra2.infra.ollama_client import OllamaLLMClient, OllamaModelCatalog
from ra2.infra.tasks import InlineTaskRunner
from ra2.main import create_app
from ra2.services.container import Services

SCRIPTS: Final = Path(__file__).resolve().parent

#: `docs/choosing-models.md` §3 was measured on 200 records, and the gate on
#: 48 (`plan-parallel-calls.md` §1.2). The defaults reproduce both.
DEFAULT_RECORDS: Final = 200
DEFAULT_GATE_RECORDS: Final = 48
#: Three one-slot serial passes: the 2nd and 3rd against the 1st give the
#: noise band (plan-model-choice.md D5).
BASELINE_PASSES: Final = 3
#: How long an unload may take to show in `/api/ps`, and how often to look.
RELEASE_WAIT_S: Final = 30.0
RELEASE_POLL_S: Final = 0.2

#: Builds the adapter for one endpoint. Injected so the tests can drive fakes
#: through the same wiring. Production passes nothing (Do-NOT #12).
CatalogFor = Callable[[str, Settings], ModelCatalog]
ClientFor = Callable[[str, Settings], LLMClient]


class QualifyRefused(Exception):
    """A precondition failed before or between passes. The message is the
    whole explanation and names what to do; the exit code is 2."""


def _sibling(name: str) -> ModuleType:
    """`scripts/<name>.py`, loaded by path. `scripts/` isn't a package, and
    this way the tests can load this file the same way."""
    module_name = f"ra2_script_{name}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _ollama_catalog(url: str, settings: Settings) -> ModelCatalog:
    return OllamaModelCatalog(base_url=url, timeout_s=settings.llm_timeout_s)


def _ollama_client(url: str, settings: Settings) -> LLMClient:
    return OllamaLLMClient(
        base_url=url,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
        reasoning_effort=settings.llm_reasoning_effort,
    )


@dataclass(frozen=True, slots=True)
class Plan:
    tag: str
    records: int
    gate_records: int
    gates: tuple[int, ...]
    one_slot: str
    n_slot: str | None


@dataclass(frozen=True, slots=True)
class _Seeded:
    corpus_id: CorpusId
    feature_config_id: FeatureConfigId


def throwaway_settings(
    plan: Plan, *, target: Settings, workdir: Path, url: str, parallel: int = 1
) -> Settings:
    """The throwaway app's settings. **Built field by field**, never copied
    from the target: a copied `Settings` would carry the target's resolved
    `db_path`, and the passes would write into the analyst's database.
    `db_path` is named explicitly so no environment variable can move it
    either."""
    return Settings(
        data_dir=workdir,
        db_path=workdir / "ra2.sqlite",
        llm_base_url=url,
        llm_timeout_s=target.llm_timeout_s,
        llm_max_retries=target.llm_max_retries,
        llm_reasoning_effort=target.llm_reasoning_effort,
        llm_parallel_calls={} if parallel == 1 else {plan.tag: parallel},
        dev_record_max=plan.gate_records,
        _env_file=None,
    )


class _Qualifier:
    """One qualification: the throwaway dir, its apps, and the passes."""

    def __init__(
        self,
        plan: Plan,
        *,
        target: Settings,
        workdir: Path,
        catalog_for: CatalogFor,
        client_for: ClientFor,
        out: Callable[[str], None],
    ) -> None:
        self._plan = plan
        self._target = target
        self._workdir = workdir
        self._catalog_for = catalog_for
        self._client_for = client_for
        self._out = out
        self._pass_count = 0
        #: Every app's engine, disposed before the event loop ends. An engine
        #: left open outlives its loop and leaks its connections.
        self._engines: list[AsyncEngine] = []

    def _settings(self, url: str, *, parallel: int = 1) -> Settings:
        return throwaway_settings(
            self._plan, target=self._target, workdir=self._workdir, url=url, parallel=parallel
        )

    def _services(self, url: str, *, parallel: int = 1) -> Services:
        settings = self._settings(url, parallel=parallel)
        app = create_app(
            settings=settings,
            task_runner=InlineTaskRunner(Uuid7Factory()),
            llm_client=self._client_for(url, settings),
            model_catalog=self._catalog_for(url, settings),
            mount_ui=False,
        )
        self._engines.append(app.state.engine)
        services: Services = app.state.services
        return services

    async def close(self) -> None:
        for engine in self._engines:
            await engine.dispose()
        self._engines.clear()

    async def digest_and_version(self, url: str) -> tuple[str, str | None]:
        catalog = self._catalog_for(url, self._target)
        offered = {model.tag: model.digest for model in await catalog.models()}
        if self._plan.tag not in offered:
            raise QualifyRefused(
                f"{url} doesn't offer {self._plan.tag}. Pull it there first (`ollama pull`)."
            )
        return offered[self._plan.tag], await catalog.version()

    async def _nothing_else_loaded(self, url: str) -> None:
        """A model left resident squeezes the one being measured out of VRAM,
        and the speedup vanishes (`plan-parallel-calls.md` §1.1 point 3).

        **Both servers share one GPU**, so both are checked. The model being
        measured is released from the server this pass *doesn't* use: its
        copy there would otherwise sit out Ollama's keep-alive beside the
        copy being loaded here. Any *other* model, on either server, is the
        operator's, so it's refused rather than unloaded.
        """
        endpoints = [self._plan.one_slot] + ([self._plan.n_slot] if self._plan.n_slot else [])
        for endpoint in dict.fromkeys(endpoints):
            catalog = self._catalog_for(endpoint, self._target)
            if endpoint != url:
                await self._release(catalog)
            others = sorted(tag for tag in await catalog.loaded() if tag != self._plan.tag)
            if others:
                raise QualifyRefused(
                    f"{endpoint} has other models loaded ({', '.join(others)}). Unload them "
                    "(`ollama stop <tag>`) and run this again: a resident model distorts "
                    "every timing this measures."
                )

    async def _release(self, catalog: ModelCatalog) -> None:
        """Unload the measured model from `catalog` and wait until it's gone.
        Ollama answers the unload before the memory is free, so `loaded()` is
        polled; after `RELEASE_WAIT_S` it's refused rather than measured."""
        if self._plan.tag not in await catalog.loaded():
            return
        await catalog.release(self._plan.tag)
        for _ in range(int(RELEASE_WAIT_S / RELEASE_POLL_S)):
            if self._plan.tag not in await catalog.loaded():
                return
            await asyncio.sleep(RELEASE_POLL_S)
        raise QualifyRefused(
            f"{self._plan.tag} stayed loaded after an unload request; the other server "
            "would be measured short of VRAM"
        )

    async def seed(self) -> _Seeded:
        seed_dev = _sibling("seed_dev")
        scenarios = seed_dev.build_scenarios(self._plan.records)
        services = self._services(self._plan.one_slot)
        root = seed_dev.write_delivery(self._workdir / "seed", scenarios)
        # The seed narrates each step. That's useful from `just reset-seed`
        # and noise here, where the only output is the measurement.
        with contextlib.redirect_stdout(io.StringIO()):
            await seed_dev.seed(services, delivery_root=root, scenarios=scenarios)
        corpora = await services.corpus.list_corpora()
        configs = [c for c in await services.feature.list_configs() if c.frozen_at is not None]
        if len(corpora.items) != 1 or len(configs) != 1:
            raise QualifyRefused("the synthetic seed didn't produce one corpus and one frozen set")
        return _Seeded(corpora.items[0].corpus_id, configs[0].feature_config_id)

    async def _pass(
        self, seeded: _Seeded, url: str, size: EvaluationSize, *, parallel: int = 1
    ) -> tuple[EvaluationId, RunId, Services]:
        """One ordinary evaluation of this one model, launched and run to the
        end. A new evaluation per pass, so no two passes share a run."""
        await self._nothing_else_loaded(url)
        services = self._services(url, parallel=parallel)
        self._pass_count += 1
        draft = await services.evaluation.save_draft(
            name=f"qualify {self._plan.tag} pass {self._pass_count}",
            corpus_id=seeded.corpus_id,
            feature_config_id=seeded.feature_config_id,
        )
        evaluation_id = draft.evaluation_id
        await services.evaluation.update_draft(
            evaluation_id, selected_models=(self._plan.tag,), size=size
        )
        # A measurement, not an evaluation: the gate this pass is part of
        # can't be on record yet, so the map applies as asked (SD40).
        await services.evaluation.launch(evaluation_id, measuring=True)
        await services.run.launch_runs(evaluation_id)
        runs = await services.run.list_runs(evaluation_id)
        run = runs.items[0]
        if run.status is not RunStatus.DONE:
            raise QualifyRefused(
                f"pass {self._pass_count} on {url} ended {run.status.value}, not done"
                + (f": {run.error}" if run.error else "")
            )
        return evaluation_id, run.run_id, services

    async def quality(self, seeded: _Seeded) -> QualitySummary:
        evaluation_id, _, services = await self._pass(
            seeded, self._plan.one_slot, EvaluationSize.FULL
        )
        return await services.qualification.quality(evaluation_id)

    async def _answers(
        self, seeded: _Seeded, url: str, *, parallel: int = 1
    ) -> tuple[dict[RecordId, str], int]:
        _, run_id, services = await self._pass(seeded, url, EvaluationSize.DEV, parallel=parallel)
        return (
            await services.qualification.answer_fingerprints(run_id),
            await services.qualification.pass_wall_ms(run_id),
        )

    async def gates(self, seeded: _Seeded) -> tuple[GateResult, ...]:
        if not self._plan.gates:
            return ()
        assert self._plan.n_slot is not None, "checked before any pass"
        baseline = [
            (await self._answers(seeded, self._plan.one_slot))[0] for _ in range(BASELINE_PASSES)
        ]
        results: list[GateResult] = []
        for n in self._plan.gates:
            serial, serial_ms = await self._answers(seeded, self._plan.n_slot)
            parallel, parallel_ms = await self._answers(seeded, self._plan.n_slot, parallel=n)
            result = gate_result(
                n=n,
                baseline=baseline,
                serial_on_n_slot=serial,
                parallel=parallel,
                serial_on_n_slot_ms=serial_ms,
                parallel_ms=parallel_ms,
            )
            self._out(
                f"  gate ×{n}: {result.verdict.value} · band {result.noise_band} · "
                f"serial on {n} slots differs on {result.serial_on_n_slot_differ} · "
                f"parallel differs on {result.parallel_differ} of {result.records} · "
                f"{result.speedup:.2f}×"
            )
            results.append(result)
        return tuple(results)


async def qualify(
    plan: Plan,
    *,
    target: Settings,
    workdir: Path,
    catalog_for: CatalogFor = _ollama_catalog,
    client_for: ClientFor = _ollama_client,
    gpu_probe: GpuProbe | None = None,
    out: Callable[[str], None] = print,
) -> Qualification:
    """Measure, then return the qualification. Recording is `main`'s."""
    qualifier = _Qualifier(
        plan,
        target=target,
        workdir=workdir,
        catalog_for=catalog_for,
        client_for=client_for,
        out=out,
    )
    try:
        return await _measure(qualifier, plan, target=target, gpu_probe=gpu_probe, out=out)
    finally:
        await qualifier.close()


async def _measure(
    qualifier: _Qualifier,
    plan: Plan,
    *,
    target: Settings,
    gpu_probe: GpuProbe | None,
    out: Callable[[str], None],
) -> Qualification:
    digest, version = await qualifier.digest_and_version(plan.one_slot)
    if plan.gates:
        assert plan.n_slot is not None, "checked by _plan"
        n_digest, n_version = await qualifier.digest_and_version(plan.n_slot)
        if (n_digest, n_version) != (digest, version):
            raise QualifyRefused(
                f"the two servers disagree: {plan.one_slot} has {plan.tag} {digest} on Ollama "
                f"{version}, {plan.n_slot} has {n_digest} on {n_version}. A gate compares one "
                "model on one Ollama build."
            )
    out(f"{plan.tag} · digest {digest} · Ollama {version or 'unknown'}")

    seeded = await qualifier.seed()
    quality = await qualifier.quality(seeded)
    out(
        f"  quality: macro-F1 {quality.macro_f1:.3f} "
        f"({quality.macro_f1_low:.3f}–{quality.macro_f1_high:.3f}) · "
        f"{quality.ms_per_record / 1000:.2f} s/record · entities in "
        f"{quality.entity_fill:.0%} of records · {quality.parse_failures} parse failures"
    )
    gates = await qualifier.gates(seeded)

    probe = gpu_probe or probe_for(name=target.gpu_name, vram_gb=target.gpu_vram_gb)
    gpu = probe.describe()
    return Qualification(
        model_tag=plan.tag,
        model_digest=digest,
        ollama_version=version,
        gpu_name=None if gpu is None else gpu.name,
        ra2_version=_ra2_version(),
        measured_at=datetime.now(UTC),
        seed_records=plan.records,
        quality=quality,
        gates=gates,
    )


async def _record(target: Settings, qualification: Qualification) -> QualificationId:
    """The one write to the target database."""
    app = create_app(settings=target, mount_ui=False)
    services: Services = app.state.services
    try:
        return await services.qualification.record(qualification)
    finally:
        await app.state.engine.dispose()


def _ra2_version() -> str | None:
    """The installed package's version. Not a commit: that would need a `git`
    shell-out, and an installed copy has no `.git` (N3)."""
    try:
        return importlib.metadata.version("ra2")
    except importlib.metadata.PackageNotFoundError:
        return None


def _parse_args(argv: Sequence[str] | None, target: Settings) -> Plan:
    parser = argparse.ArgumentParser(
        prog="just qualify-model",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("tag", help="the model tag, as Ollama lists it")
    parser.add_argument(
        "--records",
        type=int,
        default=DEFAULT_RECORDS,
        help=f"seed size for the quality pass (default {DEFAULT_RECORDS})",
    )
    parser.add_argument(
        "--gate",
        default="",
        metavar="N[,N…]",
        help="also run the parallel-calls gate at these call counts, e.g. 2,4",
    )
    parser.add_argument(
        "--gate-records",
        type=int,
        default=DEFAULT_GATE_RECORDS,
        help=f"records per gate pass (default {DEFAULT_GATE_RECORDS})",
    )
    parser.add_argument(
        "--one-slot",
        default=target.llm_base_url,
        metavar="URL",
        help="an Ollama serving one request at a time (default RA2_LLM_BASE_URL)",
    )
    parser.add_argument(
        "--n-slot",
        default=None,
        metavar="URL",
        help="an Ollama started with OLLAMA_NUM_PARALLEL ≥ the largest --gate value",
    )
    args = parser.parse_args(argv)
    try:
        gates = tuple(sorted({int(n) for n in args.gate.split(",") if n.strip()}))
    except ValueError:
        raise QualifyRefused(f"--gate takes call counts like 2,4; got {args.gate!r}") from None
    if any(n < 2 for n in gates):
        raise QualifyRefused("--gate values are call counts of 2 or more; 1 is the baseline")
    if gates and args.n_slot is None:
        raise QualifyRefused(
            "--gate needs --n-slot URL: an Ollama started with OLLAMA_NUM_PARALLEL at least "
            f"{max(gates)}. RA2 can't read that setting, so it can't use the one-slot server "
            "for this. docs/performance.md §5.4 shows how to run one beside the system server."
        )
    if not 1 <= args.gate_records <= args.records:
        raise QualifyRefused(f"--gate-records must be 1..{args.records}")
    return Plan(
        tag=args.tag,
        records=args.records,
        gate_records=args.gate_records,
        gates=gates,
        one_slot=args.one_slot,
        n_slot=args.n_slot,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    target: Settings | None = None,
    catalog_for: CatalogFor = _ollama_catalog,
    client_for: ClientFor = _ollama_client,
    gpu_probe: GpuProbe | None = None,
    out: Callable[[str], None] = print,
) -> int:
    target = target or Settings()
    workdir = Path(tempfile.mkdtemp(prefix="ra2-qualify-"))
    try:
        plan = _parse_args(argv, target)
        # Before the event loop, not inside it: alembic's `env.py` runs its
        # own `asyncio.run`.
        _sibling("reset_data").upgrade_head(
            throwaway_settings(plan, target=target, workdir=workdir, url=plan.one_slot)
        )
        qualification = asyncio.run(
            qualify(
                plan,
                target=target,
                workdir=workdir,
                catalog_for=catalog_for,
                client_for=client_for,
                gpu_probe=gpu_probe,
                out=out,
            )
        )
        qualification_id = asyncio.run(_record(target, qualification))
    except QualifyRefused as exc:
        out(f"qualify-model refused: {exc}")
        return 2
    except LlmEndpointError as exc:
        # The loopback guard, and an endpoint that stopped answering mid-pass.
        out(f"qualify-model refused: {exc}")
        return 2
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    out(f"Recorded as {qualification_id} in {target.database_path}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

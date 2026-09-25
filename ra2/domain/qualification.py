"""What this host has measured about one model (sw-design.md SD40).

A **qualification** is one model (tag, digest) run over the synthetic seed in
a throwaway data dir by `just qualify-model`, reduced to numbers: how well it
reads (`QualitySummary`), and optionally whether it survives parallel calls
(`GateResult`, one per N). The rows are append-only, and the newest per
(tag, digest) wins.

Two rules live here and nowhere else:

- `gate_verdict` — `plan-parallel-calls.md` §4.1's gate, which was prose
  until SD40. A model passes at N when its answers move no more than serial
  noise already moves them, both in parallel and serially on an N-slot
  server, and parallel calls actually buy at least `MIN_SPEEDUP`.
- `parallel_decision` — whether the launch honours an
  `RA2_LLM_PARALLEL_CALLS` entry. The entry applies only with a matching
  passing gate. Anything else pins **1**, never a lower non-1 value nobody
  configured (plan-model-choice.md Q5).

"Differ" counts records whose **canonical** answers differ
(`canonical_answer`), which is how every number in `docs/choosing-models.md`
§5 was measured.

Pure: stdlib and pydantic, no session, no config, no network. The caller
passes in every fact, including the Ollama version it asked the endpoint for.
"""

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

from ra2.domain.ids import RecordId

__all__ = [
    "MIN_SPEEDUP",
    "NOISE_FLOOR_OF",
    "NOISE_FLOOR_RECORDS",
    "UNPARSED_PREFIX",
    "GateResult",
    "GateVerdict",
    "ParallelDecision",
    "ParallelReason",
    "Qualification",
    "QualificationState",
    "QualitySummary",
    "canonical_answer",
    "differ_count",
    "gate_result",
    "gate_verdict",
    "noise_band",
    "noise_floor",
    "parallel_decision",
]

#: Condition 3 (`plan-parallel-calls.md` §4.1). Below it the gain doesn't pay
#: for the provenance and the display that parallel runs cost. Measured
#: gains were 1.6–2.7× where Ollama batches and 1.0× where it refuses.
MIN_SPEEDUP: Final = 1.3

#: The noise band's floor: 2 differing records of 48, scaled to the seed size
#: (plan-model-choice.md Q2). Three baseline passes is too small a sample: a
#: 0-0 baseline would fail `qwen3:8b` on a single flipped token, and 2 of 48 is
#: the difference `docs/performance.md` §6 already calls noise between two
#: ordinary runs. **A constant, not a setting**, so the gate cannot be
#: loosened until a model passes.
NOISE_FLOOR_RECORDS: Final = 2
NOISE_FLOOR_OF: Final = 48

#: Marks an answer that did not parse. No canonical JSON starts with `!`, so
#: a broken answer never equals a parsed one.
UNPARSED_PREFIX: Final = "!unparsed:"

_FROZEN: Final = ConfigDict(frozen=True, extra="forbid")


class GateVerdict(StrEnum):
    """What the gate found at one N.

    `FAILS_SERVER` and `FAILS_BOTH` are the dangerous two. The model's
    *serial* answers move on an N-slot server, so raising
    `OLLAMA_NUM_PARALLEL` for anything changes this model's runs, even
    though it never runs in parallel itself (the `ministral-3:8b` case).
    """

    PASSES = "passes"
    FAILS_PARALLEL = "fails_parallel"
    FAILS_SERVER = "fails_server"
    FAILS_BOTH = "fails_both"


class QualificationState(StrEnum):
    """The Models card's third line (SD40, design README §2 step 4).

    "Not measured" isn't a value here. It's the absence of a qualification,
    so it can't be constructed with numbers attached.
    """

    QUALIFIED = "qualified"
    STALE_DIGEST = "stale-digest"
    SERVER_SENSITIVE = "server-sensitive"


class ParallelReason(StrEnum):
    """Why `parallel_decision` pinned what it pinned. Logged as `gate=<value>`
    beside `parallel=N`: a code, never a sentence (data-handling.md §5.1)."""

    GATED = "gated"
    #: The qualifier's own gate passes: the measurement a gate is made of,
    #: so there is no gate to ask yet (SD40).
    MEASURING = "measuring"
    NOT_MAPPED = "not_mapped"
    NO_GATE = "missing"
    DIGEST = "digest"
    OLLAMA_VERSION = "ollama_version"
    FAILED = "failed"


class QualitySummary(BaseModel):
    """One serial pass over the seed, as the Results screens would score it.

    `ms_per_record` is the serial pass's mean latency: SD38's time per record
    with N = 1. `entity_fill` is the share of records whose answer carried at
    least one entity. Entities aren't scored, and no screen shows them, so this
    is the only place the difference between the leaders is visible
    (`docs/choosing-models.md` §4).
    """

    model_config = _FROZEN

    records: int
    #: The effort the pass asked with (SD36). It moves time per record by
    #: 30× on a thinking model, so a number without it isn't comparable.
    reasoning_effort: str
    macro_f1: float
    macro_f1_low: float
    macro_f1_high: float
    f1_by_language: dict[str, float]
    median_latency_ms: int
    ms_per_record: float
    median_completion_tokens: int | None
    entity_fill: float
    parse_failures: int


class GateResult(BaseModel):
    """`plan-parallel-calls.md` §4.1 at one N, with the counts behind it.

    Every differ count is against the **first one-slot serial pass**, which
    is the comparison production makes: a run from before the server changed
    against a run after it.
    """

    model_config = _FROZEN

    n: int
    records: int
    noise_band: int
    serial_on_n_slot_differ: int
    parallel_differ: int
    speedup: float
    verdict: GateVerdict


class Qualification(BaseModel):
    """One `model_qualification` row, as the domain sees it.

    `gpu_name` is recorded, **not** compared (plan-model-choice.md Q4): it's
    often unknown, and it misses the driver and CUDA versions that matter
    more.
    """

    model_config = _FROZEN

    model_tag: str
    model_digest: str
    ollama_version: str | None
    gpu_name: str | None
    ra2_version: str | None
    measured_at: datetime
    seed_records: int
    quality: QualitySummary
    gates: tuple[GateResult, ...] = ()

    @property
    def passing_n(self) -> int:
        """The largest N the gate passed at, or 1 when it passed nowhere.

        One is the floor because serial always "passes": a model that runs
        one record at a time is exactly what a qualification without a gate
        describes.
        """
        return max((g.n for g in self.gates if g.verdict is GateVerdict.PASSES), default=1)

    @property
    def server_sensitive(self) -> bool:
        """Its serial answers moved on an N-slot server, at any N measured."""
        return any(
            g.verdict in {GateVerdict.FAILS_SERVER, GateVerdict.FAILS_BOTH} for g in self.gates
        )


@dataclass(frozen=True, slots=True)
class ParallelDecision:
    """What the launch pins on the run, and why."""

    n: int
    reason: ParallelReason


def canonical_answer(raw: str) -> str:
    """One model answer, in the form two passes are compared in.

    Sorted keys and compact separators, so key order and whitespace don't
    count as a difference. An answer that doesn't parse is **its own
    answer**: two different broken texts differ, the same broken text
    doesn't, and neither equals any parsed answer (`UNPARSED_PREFIX`).
    """
    try:
        parsed = json.loads(raw)
    except ValueError:
        return UNPARSED_PREFIX + raw
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def differ_count(first: Mapping[RecordId, str], second: Mapping[RecordId, str]) -> int:
    """How many records two passes answered differently.

    Both maps hold `canonical_answer`s by record. **Refuses** two passes over
    different records rather than counting a missing one as a difference: a
    pass with holes is an interrupted pass, not a result.
    """
    if first.keys() != second.keys():
        raise ValueError(
            f"passes cover different records: {len(first.keys() - second.keys())} only in the "
            f"first, {len(second.keys() - first.keys())} only in the second"
        )
    return sum(1 for record_id, answer in first.items() if second[record_id] != answer)


def noise_floor(records: int) -> int:
    """`NOISE_FLOOR_RECORDS` of `NOISE_FLOOR_OF`, scaled up to `records`, so a
    larger gate seed doesn't make the floor relatively tighter."""
    if records < 1:
        raise ValueError(f"a gate needs at least one record; got {records}")
    return math.ceil(records * NOISE_FLOOR_RECORDS / NOISE_FLOOR_OF)


def noise_band(baseline_differs: Sequence[int], records: int) -> int:
    """The most records two serial one-slot passes are allowed to differ on.

    `baseline_differs` are the 2nd, 3rd, … one-slot passes against the 1st.
    The band is the largest of them, but never below `noise_floor`. There
    has to be at least one, because a gate without a baseline has nothing to
    compare against.
    """
    if not baseline_differs:
        raise ValueError("a noise band needs at least two serial passes to compare")
    return max(max(baseline_differs), noise_floor(records))


def gate_verdict(
    *, band: int, serial_on_n_slot_differ: int, parallel_differ: int, speedup: float
) -> GateVerdict:
    """`plan-parallel-calls.md` §4.1, as one function.

    1. Parallel calls on the N-slot server move no more answers than the band.
    2. **Serial** calls on the N-slot server move no more answers than the
       band. This is the server-wide side effect.
    3. Parallel calls are at least `MIN_SPEEDUP` faster than serial on the
       same server. An architecture Ollama refuses to batch fails here,
       at 1.0×.

    1 and 3 decide whether the model may run in parallel, and 2 decides
    whether the *server* setting is safe for it.
    """
    parallel_ok = parallel_differ <= band and speedup >= MIN_SPEEDUP
    server_ok = serial_on_n_slot_differ <= band
    if parallel_ok and server_ok:
        return GateVerdict.PASSES
    if server_ok:
        return GateVerdict.FAILS_PARALLEL
    if parallel_ok:
        return GateVerdict.FAILS_SERVER
    return GateVerdict.FAILS_BOTH


def gate_result(
    *,
    n: int,
    baseline: Sequence[Mapping[RecordId, str]],
    serial_on_n_slot: Mapping[RecordId, str],
    parallel: Mapping[RecordId, str],
    serial_on_n_slot_ms: int,
    parallel_ms: int,
) -> GateResult:
    """One N's gate, from the passes themselves.

    `baseline` is the one-slot serial passes, the first being the reference
    every other pass is compared with. The speedup compares the two passes on
    the **same** N-slot server, so a difference between the servers can't
    pose as a gain. Every map is record -> an answer's fingerprint, so a
    caller never has to hand model text across a layer.
    """
    if len(baseline) < 2:
        raise ValueError("a gate needs at least two one-slot serial passes")
    if parallel_ms <= 0 or serial_on_n_slot_ms <= 0:
        raise ValueError("a pass that took no time was not measured")
    reference = baseline[0]
    band = noise_band([differ_count(reference, other) for other in baseline[1:]], len(reference))
    serial_differ = differ_count(reference, serial_on_n_slot)
    parallel_differ = differ_count(reference, parallel)
    speedup = serial_on_n_slot_ms / parallel_ms
    return GateResult(
        n=n,
        records=len(reference),
        noise_band=band,
        serial_on_n_slot_differ=serial_differ,
        parallel_differ=parallel_differ,
        speedup=round(speedup, 2),
        verdict=gate_verdict(
            band=band,
            serial_on_n_slot_differ=serial_differ,
            parallel_differ=parallel_differ,
            speedup=speedup,
        ),
    )


def parallel_decision(
    *,
    mapped: int | None,
    qualification: Qualification | None,
    digest: str,
    ollama_version: str | None,
    measuring: bool = False,
) -> ParallelDecision:
    """What the launch pins for one model (SD40). The only place this rule
    exists: the launch and the Models card both call it.

    `mapped` is the model's `RA2_LLM_PARALLEL_CALLS` entry, `None` when it has
    none. `qualification` is the newest **gated** one for the tag. It's the
    one for the current digest when there is one, otherwise the newest for
    any digest, so that a stale digest gets its own reason instead of looking
    like "never measured". `ollama_version` is what the endpoint reports now,
    and `None` matches nothing.

    Every refusal pins **1**. A map entry above the gated N isn't lowered to
    the gated N, because that would run at a value nobody configured
    (plan-model-choice.md Q5).

    `measuring` is the one exception, and it's here rather than in the launch
    so the rule stays in one place. `just qualify-model` runs the passes a
    gate is *made of*, in a throwaway database that can't hold a gate yet, so
    it pins the map's value as asked. No adapter passes it: the API and the
    UI launch the analyst's evaluations, which are never measurements.
    """
    if mapped is None or mapped <= 1:
        return ParallelDecision(1, ParallelReason.NOT_MAPPED)
    if measuring:
        return ParallelDecision(mapped, ParallelReason.MEASURING)
    if qualification is None or not qualification.gates:
        return ParallelDecision(1, ParallelReason.NO_GATE)
    if qualification.model_digest != digest:
        return ParallelDecision(1, ParallelReason.DIGEST)
    if ollama_version is None or qualification.ollama_version != ollama_version:
        return ParallelDecision(1, ParallelReason.OLLAMA_VERSION)
    if mapped > qualification.passing_n:
        return ParallelDecision(1, ParallelReason.FAILED)
    return ParallelDecision(mapped, ParallelReason.GATED)

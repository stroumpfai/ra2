# STUB — signature only at M17, body owned by L3 (feat/p3-evaluation-components).
"""The per-model progress card (design/prompt-evaluation/README.md §2).

Declared at M17 (plan-phase-3.md §3.1) so L2 (the Evaluation view) and L3
(this component) build in Wave 4 in parallel: L2 places it and passes a
`RunProgressView`; L2 never reaches inside it.

**No service call inside the component** (Do-NOT #7). It renders all four
states — `queued`, `running`, `done`, `failed` — from the read model alone,
and a `queued` card has a 0 % bar and **no metrics line**, because there is
nothing honest to put in one yet.

The status line and metrics line are assembled from `RunProgressView`'s own
fields (`percent`, `has_metrics`, `done`, `total`, `parse_failures`,
`retries`, `median_latency_ms`, `prompt_tokens`, `elapsed_ms`, `eta_ms`) —
this never fetches or recomputes anything the read model does not already
carry; the arithmetic here (a duration from milliseconds, a rate from two
counts) is presentation formatting of exactly that kind, the same category
as `bar()`'s own clamp or `pagination_row`'s `first`/`last`.

`FAILED` is not in the design mock (only `queued` / `running` / `done` are
shown there); its status and metrics lines follow the same formatting rules
as `done`, coloured `--danger` instead of `--ink3` — this component's own
reasonable extension of an undrawn state, not something the design specifies.
"""

from nicegui import ui
from nicegui.element import Element

from ra2.domain.extraction import RunStatus
from ra2.services.readmodels import RunProgressView
from ra2.ui.components.primitives import bar, card, format_count

__all__ = ["progress_card"]

#: Milliseconds thresholds for `_format_duration_ms`.
_MS_PER_SECOND = 1_000
_MS_PER_MINUTE = 60_000
_MS_PER_HOUR = 3_600_000


def _format_duration_ms(ms: int) -> str:
    """`72 * 60_000` -> `"1 h 12 m"`; `38 * 60_000` -> `"38 m"`; anything
    under a minute -> `"N s"` — the design's own two examples plus the
    obvious short case."""
    if ms < _MS_PER_MINUTE:
        return f"{round(ms / _MS_PER_SECOND)} s"
    if ms < _MS_PER_HOUR:
        return f"{round(ms / _MS_PER_MINUTE)} m"
    hours, remainder_ms = divmod(ms, _MS_PER_HOUR)
    return f"{hours} h {round(remainder_ms / _MS_PER_MINUTE)} m"


def _format_tokens(count: int) -> str:
    """`2_100_000` -> `"2.1 M"`; anything smaller uses `format_count`'s own
    thousands separator (design: "2.1 M prompt tok")."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f} M"
    return format_count(count)


def _status_text(progress: RunProgressView) -> str:
    if progress.status is RunStatus.QUEUED:
        return "queued"
    counts = f"{format_count(progress.done)} / {format_count(progress.total)}"
    if progress.status is RunStatus.RUNNING:
        text = f"{counts} · running"
        # Elapsed **before** the ETA, and shown whether or not there is one.
        # `_eta_ms` is `None` until a record has committed, and on a model that
        # takes minutes per record that is most of the first quarter of an
        # hour — during which this line read `0 / 12 · running` over a bar at
        # zero and did not change. There was nothing on the screen separating a
        # worker that was extracting from one whose process had died, which is
        # what mvp-spec.md N6's "progress is visible" has to mean when the
        # first record is still in flight. The number was in the read model the
        # whole time; only the `done`/`failed` branch below ever rendered it.
        if progress.elapsed_ms is not None:
            text += f" · {_format_duration_ms(progress.elapsed_ms)}"
        if progress.eta_ms is not None:
            text += f" · ETA {_format_duration_ms(progress.eta_ms)}"
        return text
    # DONE, FAILED, INTERRUPTED — a finished-or-stopped run reports what it
    # got through and how long that took.
    text = f"{counts} · {progress.status.value}"
    if progress.elapsed_ms is not None:
        text += f" · {_format_duration_ms(progress.elapsed_ms)}"
    return text


def _metrics_line(progress: RunProgressView) -> str:
    """ "parse failures 14 (0.3 %) · median latency 812 ms · 2.1 M prompt
    tok" (design). Segments are included only when the field behind them is
    known/nonzero — this reports what `RunProgressView` carries, in one
    fixed order, never a per-state hand-picked subset."""
    segments = [f"parse failures {format_count(progress.parse_failures)}"]
    if progress.done > 0:
        rate = 100 * progress.parse_failures / progress.done
        segments[0] += f" ({rate:.1f} %)"
    if progress.retries > 0:
        segments.append(f"retries {format_count(progress.retries)} (bounded, counted)")
    if progress.median_latency_ms is not None:
        segments.append(f"median latency {format_count(progress.median_latency_ms)} ms")
    if progress.prompt_tokens > 0:
        segments.append(f"{_format_tokens(progress.prompt_tokens)} prompt tok")
    return " · ".join(segments)


def progress_card(*, progress: RunProgressView) -> Element:
    """Model tag, a right-aligned status line, a 6px `.bar` at the completion
    percentage, and — for active and finished runs only — the metrics line
    ("parse failures 14 (0.3 %) · median latency 812 ms · 2.1 M prompt tok")."""
    is_queued = progress.status is RunStatus.QUEUED
    is_failed = progress.status is RunStatus.FAILED
    element = (
        card(extra="padding:14px;gap:14px;")
        .props('data-testid="progress-card"')
        .mark("progress-card")
    )
    with element:
        with ui.element("div").style(
            "display:flex;justify-content:space-between;align-items:baseline;gap:10px;"
        ):
            ui.label(progress.model_tag).classes("mono").props(
                'data-testid="progress-card-model"'
            ).mark("progress-card-model").style(
                f"font-size:12.5px;color:var(--{'ink2' if is_queued else 'ink'});"
            )
            ui.label(_status_text(progress)).classes("mono nowrap").props(
                'data-testid="progress-card-status"'
            ).mark("progress-card-status").style(
                f"font-size:11.5px;color:var(--{'danger' if is_failed else 'ink3'});"
            )
        bar(fill_pct=0.0 if is_queued else progress.percent).style("width:100%;")
        if progress.has_metrics:
            ui.label(_metrics_line(progress)).classes("mono").props(
                'data-testid="progress-card-metrics"'
            ).mark("progress-card-metrics").style("font-size:10.5px;color:var(--ink3);")
    return element

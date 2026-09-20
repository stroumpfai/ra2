# FROZEN — see CONTRACTS.md
"""Configuration (sw-design.md §10).

pydantic-settings, `RA2_` prefix, `.env` supported. The table below is
sw-design.md §10 verbatim; nothing else is configurable in phase 1.

`Settings` is constructed once in `create_app()` and injected. **No module
reaches for a global settings object** (sw-design.md §3).
"""

from pathlib import Path
from typing import Final, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["REASONING_EFFORTS", "Settings"]

#: The `reasoning_effort` values Ollama maps onto its own `think` levels.
#: Deliberately narrower than the OpenAI SDK's literal, which also carries
#: `minimal`, `xhigh` and `max` — this endpoint is the only one N1 allows the
#: app to talk to, so its vocabulary is the real one.
REASONING_EFFORTS: Final[frozenset[str]] = frozenset({"none", "low", "medium", "high"})


class Settings(BaseSettings):
    """Every RA2 setting. Defaults are sw-design.md §10's."""

    model_config = SettingsConfigDict(
        env_prefix="RA2_",
        env_file=".env",
        env_file_encoding="utf-8",  # N4: never rely on the platform default
        extra="ignore",
    )

    #: N7 — the database, uploads and codelists all live under one
    #: configurable dir. **Exports do not**: every one of the six is built in
    #: memory and streamed to the browser, so it exists once, in the
    #: analyst's Downloads folder, and never as a second copy at rest here
    #: (risk-assesment.md B3 §8.6, `SD30`).
    data_dir: Path = Path("./var")

    #: Defaults to `{data_dir}/ra2.sqlite`; see `_default_db_path` below.
    db_path: Path | None = None

    #: N2 — present from commit 1, first caller in phase 3
    #: (`infra/ollama_client.py`). The default is the design's own endpoint
    #: line, written as `127.0.0.1` rather than `localhost` so the loopback
    #: guard has one fewer name to resolve (sw-design.md §15.5).
    #:
    #: **The host must be loopback.** `OllamaLLMClient` refuses anything else
    #: at construction, and there is deliberately no opt-out setting: an
    #: opt-out is how "no data leaves the host" (N1) becomes "no data leaves
    #: the host by default" (mvp-spec.md §19.10, §15 F4).
    llm_base_url: str = "http://127.0.0.1:11434/v1"

    #: Per-call timeout. Belongs to client construction, not to a per-call
    #: argument — which is why `LLMClient.extract` never took one.
    #:
    #: **600, raised from 120 against a measurement.** 120 was never checked
    #: against a reasoning model: on the reporting host a 9.7 B thinking model
    #: answered *two* features over one sentence of narrative in 136 s cold and
    #: 126 s warm, almost all of it inside the response's `reasoning` field. At
    #: 120 every call on that host timed out, always, and — because the bound
    #: is per call and the model is the slow part — no amount of waiting ever
    #: produced a row. A bound that the ordinary case cannot meet is not a
    #: bound, it is an outage with a timer.
    #:
    #: Still a bound, and the cost of raising it is bounded too: a timeout is
    #: no longer retried (`ollama_client._is_retryable`), and `run_service`
    #: stops asking after `_MAX_CONSECUTIVE_ENDPOINT_ERRORS` records, so a
    #: genuinely dead endpoint costs that many intervals — not one per record,
    #: and no longer three attempts apiece.
    llm_timeout_s: int = 600

    #: mvp-spec.md §10.4 — retries are **bounded and counted**, never a
    #: retry-until-quiet loop. The count is carried back on the `Extraction`
    #: and rendered in the progress card's metrics line.
    llm_max_retries: int = 2

    #: How hard the model is asked to think before it answers. Pinned on the
    #: `run` row beside the model digest, the temperature and the seed, so two
    #: runs cannot ask different questions and look identical in provenance.
    #:
    #: **`none` is the default because the measured cost is not marginal.** On
    #: the reporting host, one record with two features and one sentence of
    #: narrative, against `qwen3.5:latest` (9.7 B Q4_K_M, CPU-bound), through
    #: the adapter's own call shape:
    #:
    #: | `reasoning_effort` | elapsed | completion tokens | reasoning |
    #: |---|---|---|---|
    #: | unset (the model's own default) | **190 s** | 977 | 3 259 chars |
    #: | `none` | **6 s** | 38 | none |
    #:
    #: Both answered correctly. The first never finished a 12-record run
    #: inside `llm_timeout_s`; the second finishes one in about a minute. A
    #: default that cannot complete the product's own development seed is not
    #: a default.
    #:
    #: **It is a setting and not a constant** because whether a thinking model
    #: extracts these features *better* is exactly the question RA2 exists to
    #: answer, and foreclosing it in the adapter would be the tool deciding
    #: its own subject. Set `high` and launch a second evaluation to compare —
    #: the value rides on both runs' provenance, so the comparison is legible
    #: afterwards.
    #:
    #: Restricted to what Ollama maps (`none`, `low`, `medium`, `high`). The
    #: OpenAI SDK's literal is wider; sending it `xhigh` would fail per record,
    #: at the endpoint, after the run had started. Refused at construction
    #: instead — `OllamaLLMClient`'s loopback check, same reasoning.
    llm_reasoning_effort: str = "none"

    #: sw-design.md §15.4 — runs execute serially, one model at a time: the
    #: GPU is the bottleneck and two models sharing 24 GB is slower than two
    #: in sequence. Phase 3 never raises this; it exists so lifting the limit
    #: is a config line rather than a rewrite (§15 F7).
    run_concurrency: int = 1

    #: sw-design.md §15.6 — declared capability beats a probed one. Unset
    #: (the default) means "ask NVML"; NVML absent means an honest "unknown",
    #: not an error. Set these on a host whose GPU is not NVIDIA.
    gpu_vram_gb: float | None = None
    gpu_name: str | None = None

    #: Bind to loopback by default. No egress, no external listener (N1).
    host: str = "127.0.0.1"
    port: int = 8080

    max_upload_mb: int = 512

    #: mvp-spec.md §9. Below `dev_record_max` a corpus is marked dev-sized and
    #: every view showing its numbers carries "smoke test, not a result".
    dev_record_max: int = 50
    eval_record_min: int = 200

    #: D3 — cells below this render as "insufficient data". Unused until scoring.
    min_cell_count: int = 20

    #: NiceGUI needs a secret to enable `app.storage`. Not a security boundary:
    #: the app has no login and no auth (mvp-spec.md §13).
    storage_secret: str = Field(default="ra2-local-storage-secret")

    #: The level of the `ra2` stderr logger (`infra/logging.py`). `INFO` is the
    #: default because the thing it makes visible — a run's per-record
    #: progress — is the one thing a half-hour job needs and had nowhere to
    #: say. `WARNING` quiets that to the failures alone.
    #:
    #: **Not a switch on what may be logged.** `data-handling.md` §5 bounds the
    #: *content*: ids, counts, statuses, model tags and durations, never
    #: anything out of a delivery. `DEBUG` is the same rule, louder — there is
    #: deliberately no level at which narrative reaches a log record, which is
    #: why this is a level and not a `log_prompts` flag.
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_reasoning_effort(self) -> Self:
        """Refuse an effort Ollama cannot map, **at construction**.

        The alternative is a value the endpoint rejects on every record, one
        `RA2_LLM_TIMEOUT_S` apart, after the analyst has launched and walked
        away. Same reasoning as the loopback refusal in `OllamaLLMClient`: a
        misconfiguration that can be caught before the first call should be.
        """
        if self.llm_reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(
                f"RA2_LLM_REASONING_EFFORT must be one of "
                f"{', '.join(sorted(REASONING_EFFORTS))}; got "
                f"{self.llm_reasoning_effort!r}"
            )
        return self

    @model_validator(mode="after")
    def _default_db_path(self) -> Self:
        """`RA2_DB_PATH` defaults to `{data_dir}/ra2.sqlite` (sw-design.md §10)."""
        if self.db_path is None:
            object.__setattr__(self, "db_path", self.data_dir / "ra2.sqlite")
        return self

    @property
    def database_path(self) -> Path:
        """The resolved SQLite file. Never `None` after validation."""
        assert self.db_path is not None
        return self.db_path

    @property
    def deliveries_dir(self) -> Path:
        """Where `UploadedFileStore` streams uploads (sw-design.md §6.1)."""
        return self.data_dir / "deliveries"

    @property
    def codelists_dir(self) -> Path:
        """Where `codelist_service` stores uploads: `{data_dir}/codelists/
        {code_table_import_id}/` (sw-design.md §14.1) — the same `FileStore`
        seam as delivery intake, a different root."""
        return self.data_dir / "codelists"

    @property
    def database_url(self) -> str:
        """The async SQLAlchemy URL. `pathlib` only — no POSIX-only paths (N3)."""
        return f"sqlite+aiosqlite:///{self.database_path.as_posix()}"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

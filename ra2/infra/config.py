# FROZEN — see CONTRACTS.md
"""Configuration (sw-design.md §10).

pydantic-settings, `RA2_` prefix, `.env` supported. The table below is
sw-design.md §10 verbatim; nothing else is configurable in phase 1.

`Settings` is constructed once in `create_app()` and injected. **No module
reaches for a global settings object** (sw-design.md §3).
"""

from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings"]


class Settings(BaseSettings):
    """Every RA2 setting. Defaults are sw-design.md §10's."""

    model_config = SettingsConfigDict(
        env_prefix="RA2_",
        env_file=".env",
        env_file_encoding="utf-8",  # N4: never rely on the platform default
        extra="ignore",
    )

    #: N7 — the DB, uploads and exports all live under one configurable dir.
    data_dir: Path = Path("./var")

    #: Defaults to `{data_dir}/ra2.sqlite`; see `_default_db_path` below.
    db_path: Path | None = None

    #: N2 — present from commit 1, no caller in phase 1.
    llm_base_url: str = "http://localhost:11434/v1"

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
    def exports_dir(self) -> Path:
        """Where CSV exports are written."""
        return self.data_dir / "exports"

    @property
    def database_url(self) -> str:
        """The async SQLAlchemy URL. `pathlib` only — no POSIX-only paths (N3)."""
        return f"sqlite+aiosqlite:///{self.database_path.as_posix()}"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

# FROZEN — see CONTRACTS.md
"""The `just census-export` and `just dev` entry points.

Composition-root adjacent, like `main.py`: it builds the app to get the same
wired services and calls one of them. Building the app rather than hand-wiring
means the CLI and the UI can never drift into two different compositions.

`serve` is where the **bind** is decided, so it is where the bind is checked
(`SD42`). `RA2_HOST` and `RA2_PORT` were documented as "bind to loopback by
default (N1)" and read by nothing — the `justfile`'s `--host`/`--port` bound,
and nothing anywhere would have refused `--host 0.0.0.0` (`docs/
risk-assesment.md` A4). `create_app()` cannot hold this check: it is handed to
a server it never sees.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Final

from ra2.domain.ids import CorpusId
from ra2.domain.llm import LOOPBACK_HOSTS
from ra2.infra.config import Settings
from ra2.services.readmodels import SortDir

__all__ = ["BIND_REFUSED", "main"]

#: `serve`'s refusal. **No opt-out**, for `require_loopback`'s reason: an
#: opt-out is how "no data leaves the host" (N1) becomes "no data leaves the
#: host by default". Compared against `LOOPBACK_HOSTS` literally — the same set
#: the LLM endpoint is checked against, so the bind half of N1 and its egress
#: half cannot drift apart.
BIND_REFUSED: Final = (
    "RA2_HOST={host!r} is not a loopback address. RA2 binds to 127.0.0.1, ::1 or "
    "localhost only (N1, sw-design.md SD42), and there is no setting that allows another."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ra2", description="RA2 command-line tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("census-export", help="Export a corpus's census as CSV.")
    export.add_argument("--corpus-id", required=True)
    export.add_argument("--out", required=True, type=Path)
    export.add_argument("--table", default=None, help="unfall | objekt | person")
    export.add_argument("--min-populated-rate", default=None, type=float)
    export.add_argument("--sort-key", default="populated_rate")
    export.add_argument(
        "--sort-dir", default=SortDir.DESC.value, choices=[d.value for d in SortDir]
    )

    serve = sub.add_parser("serve", help="Run the app on RA2_HOST:RA2_PORT, loopback only.")
    serve.add_argument(
        "--reload",
        action="store_true",
        help="Restart on a change under ra2/. Never with a run executing.",
    )
    return parser


async def _census_export(args: argparse.Namespace) -> None:
    from ra2.main import create_app  # noqa: PLC0415 - keeps import time off `--help`

    app = create_app(mount_ui=False)
    try:
        data = await app.state.services.export.census_csv(
            CorpusId(args.corpus_id),
            table_name=args.table,
            min_populated_rate=args.min_populated_rate,
            sort_key=args.sort_key,
            sort_dir=SortDir(args.sort_dir),
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # UTF-8 with BOM and the header comment line are the export service's
        # business; the CLI only writes the bytes it is given.
        args.out.write_bytes(data)
    finally:
        await app.state.engine.dispose()


def _serve(args: argparse.Namespace) -> int:
    """Refuse a non-loopback `RA2_HOST`, then hand `create_app` to uvicorn.

    Refused **before** `uvicorn.run`, so no socket is ever opened on the wrong
    address. `create_app` goes in as an import string with `factory=True`,
    which is what `--reload` needs and what `just dev` always ran.
    """
    import uvicorn  # noqa: PLC0415 - keeps import time off `--help`

    settings = Settings()
    if settings.host.lower() not in LOOPBACK_HOSTS:
        print(BIND_REFUSED.format(host=settings.host), file=sys.stderr)
        return 1
    uvicorn.run(
        "ra2.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        # `ra2/` alone — `dev-reload`'s `--reload-dir ra2`. An unscoped watcher
        # on a tree that holds copies of itself under `.claude/worktrees/`
        # restarts on a test file, a script, or another agent's edit.
        reload_dirs=["ra2"] if args.reload else None,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "census-export":
        asyncio.run(_census_export(args))
        return 0
    if args.command == "serve":
        return _serve(args)
    return 2  # pragma: no cover - argparse rejects anything else first


if __name__ == "__main__":
    sys.exit(main())

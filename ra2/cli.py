# FROZEN — see CONTRACTS.md
"""The `just census-export` entry point.

Composition-root adjacent, like `main.py`: it builds the app to get the same
wired services and calls one of them. Building the app rather than hand-wiring
means the CLI and the UI can never drift into two different compositions.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from ra2.domain.ids import CorpusId
from ra2.services.readmodels import SortDir

__all__ = ["main"]


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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "census-export":
        asyncio.run(_census_export(args))
        return 0
    return 2  # pragma: no cover - argparse rejects anything else first


if __name__ == "__main__":
    sys.exit(main())

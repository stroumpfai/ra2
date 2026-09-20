#!/usr/bin/env python
"""Run RA2 for an agent's own manual verification, isolated from `just dev`.

`just dev` binds 127.0.0.1:8080 and `RA2_DATA_DIR` defaults to `./var` — the
same port and the same real database a developer's own manual testing session
uses. An agent starting the app to eyeball a change must never share either:
doing so has clobbered a developer's live test data before. This picks a free
port the same way `tests/e2e/conftest.py`'s `_free_port()` does, and a fresh
temp `RA2_DATA_DIR` per run, then hands off to the same `create_app()` that
`just dev` uses.

`uvicorn` is invoked as a subprocess, so this needs no change to `ra2/` and no
test-mode branch in production code (sw-design.md §12.12).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="ra2-dev-agent-"))
    port = _free_port()
    env = dict(os.environ)
    env["RA2_DATA_DIR"] = str(data_dir)
    env["RA2_PORT"] = str(port)

    print(f"RA2 (agent instance): http://127.0.0.1:{port}", flush=True)
    print(f"RA2_DATA_DIR: {data_dir}", flush=True)

    # **Migrate first.** `session.py` states the rule — "the schema comes from
    # `alembic upgrade head`, always" — and this is the one launcher that
    # starts against a directory that has never existed before, so it is the
    # one that has to apply it. `just dev` and `just dev-agent` are not
    # symmetrical here: `dev` points at a `./var` a developer migrated long
    # ago, and nothing made the difference visible until the app began reading
    # the `run` table at startup (`RunService.reclaim_orphans`) and an
    # unmigrated instance stopped booting rather than merely 500-ing on the
    # first page.
    #
    # Empty **but migrated** is the state the README promises here: "it mints
    # a fresh temporary data directory on every run, by design".
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        check=False,
    )
    if migrated.returncode != 0:
        print("migration failed; not starting the server", flush=True)
        return migrated.returncode

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "ra2.main:create_app",
            "--factory",
            # **No `--reload`**, for `just dev`'s reason and one more. The
            # reloader watches the whole working directory for `*.py`, and an
            # agent is by definition writing `*.py` in it — including in the
            # `.claude/worktrees/agent-*` copies of this project that sit
            # under it. An agent eyeballing a run it just launched would be
            # killing that run with its own next edit, and the app would
            # report "the process died while this run was executing" without
            # being able to say who did it.
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

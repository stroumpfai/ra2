"""`reclaim_orphans` is called from the composition root and from nowhere else.

The same shape as `test_p3_contract.py`'s `openai` and `pynvml` seam gates, and
for the same reason: the property is a *location*, and a location is not
something a behavioural test can assert.

**Why it needs a gate at all.** `RunService.reclaim_orphans` relabels every
`running` row `interrupted` **unconditionally** — no claim to check, no set to
consult. That is correct precisely once per process, at startup, when this
process is executing nothing. Called from anywhere else it is a loaded gun: from
a read path it declares live runs dead, which is the defect this replaced, and
the Evaluation view reaches the read paths twice a tick for the length of a run.

So the safety of the whole arrangement rests on one call site, and "there is
only one" is the thing to assert. Reading it out of the source is what makes it
a gate rather than a comment — a second caller added in good faith six months
from now fails here, with the reason attached, instead of silently reinstating
the race.

`.as_posix()`, never `str()`: the comparison target is a POSIX literal and
`str()` on a `Path` is `ra2\\main.py` on Windows. That failed *closed* in the
two gates this copies, but a gate that cannot pass on a platform CI runs it on
is a gate nobody reads (`SD33`).
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The composition root — the one module allowed to see every layer, because
#: wiring is its whole job (`.importlinter`'s own note on `ra2.main`).
THE_ONE_CALLER = "ra2/main.py"

METHOD = "reclaim_orphans"


def _callers_in(root: Path) -> list[str]:
    found = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == METHOD
            ):
                found.append(path.relative_to(REPO_ROOT).as_posix())
    return found


def test_reclaim_orphans_is_called_in_exactly_one_module():
    """`ra2/` holds one call, in the composition root's lifespan."""
    assert _callers_in(REPO_ROOT / "ra2") == [THE_ONE_CALLER], (
        f"{METHOD}() relabels every running run with no guard, which is only "
        f"true at process start. It belongs in {THE_ONE_CALLER}'s lifespan and "
        f"nowhere else."
    )


def test_the_caller_is_the_lifespan_and_not_the_request_path():
    """Being in `main.py` is not enough: it has to run *before* work can be
    submitted. A call made anywhere else in `create_app` would run at import of
    the app object, which the E2E fixture and every UI test do more than once
    per process."""
    tree = ast.parse((REPO_ROOT / THE_ONE_CALLER).read_text(encoding="utf-8"))
    holders = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == METHOD
            for call in ast.walk(node)
        )
    ]
    assert holders == ["lifespan"], holders


def test_no_read_path_in_the_run_service_can_write_a_status():
    """The negative half, read out of the service itself.

    `progress`, `get` and `list_runs` are what the Evaluation view polls. The
    behavioural proof is `tests/backend/services/run/test_reclaim.py`; this
    pins the structural reason — the relabelling code exists in exactly one
    method, and it is not one of theirs.
    """
    source = (REPO_ROOT / "ra2/services/run_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    service = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "RunService"
    )
    writers = [
        node.name
        for node in service.body
        if isinstance(node, ast.AsyncFunctionDef)
        and "_ERROR_INTERRUPTED_BY_RESTART" in ast.unparse(node)
    ]
    assert writers == [METHOD], writers

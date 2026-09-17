"""`scripts/check_no_real_data.py` — the guard that stops real data being
committed (risk C1, sw-design.md §12.11).

The guard it replaces was **name-shaped**: it refused `vum_*.txt` and
`AstranaExport*`, and the Astrana delivery's real filenames are `Unfall.csv`,
`Objekt.csv` and `Mitfahrende.csv`. Those match nothing outside `data/`, so the
one scenario the guard exists for — a delivery file copied into the tree while
debugging an import on real data — walked straight past it.

So the tests that matter here are the ones that would have passed before and
must fail now, and they are built the only honest way: by asking
`generate_hazards` for a **genuine** delivery file and then putting *delivered*
keys in it. A guard tested against a file that only resembles a delivery is a
guard tested against the author's idea of one.

**No real value appears here either.** `DELIVERED_KEYS` are invented UUIDs with
the *entropy* of delivered ones — which is the only property the guard reads.

`scripts/` is not a package, so the module is loaded by path, the same way a
script is actually run.
"""

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from ra2.domain.delivery import FileKind

pytestmark = pytest.mark.backend

#: `tests/backend/scripts/` -> the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_no_real_data.py"
GENERATOR = REPO_ROOT / "tests" / "fixtures" / "deliveries" / "generate_hazards.py"


def _load(name: str, path: Path) -> ModuleType:
    """Import a module by location.

    Neither `scripts/` nor `tests/fixtures/` is a package, and adding an
    `__init__.py` to either would change how pytest names every module beneath
    it. `tests/unit/parsing/test_generated_fixtures.py` reaches the generator
    the same way.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load("ra2_generate_hazards", GENERATOR)

#: Keys with the shape and the **entropy** of delivered ones. Invented here —
#: nothing in this file comes from a delivery — but a real 32-hex key is what
#: they are indistinguishable from, which is the whole of what the guard reads.
DELIVERED_KEYS = (
    "3f8a1c27b94e5d0a6172e8f3c5b40d91",
    "c72e04b8af13569d2e8b7a40f16c395d",
    "91b3e7d5c08a426fb1ed93504c7a28fe",
)

#: What `generate_hazards.uid()` produces: a short hex tag and a zero-padded
#: counter. Three distinct characters out of thirty-two.
INVENTED_KEYS: tuple[str, ...] = tuple(cast("str", gen.uid("aa", n)) for n in (1, 2, 3))

FIXTURE_ROOT = "tests/fixtures/deliveries/"


@pytest.fixture
def guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The script, rooted at a throwaway tree.

    `REPO_ROOT` is repointed so a test can place a file at
    `tests/fixtures/deliveries/…` — the guard's one allowed location — without
    writing into the real repository to do it.
    """
    module = _load("ra2_check_no_real_data", SCRIPT)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    return module


def place(root: Path, relative: str, content: bytes) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return relative


def radis_unfall(keys: tuple[str, ...]) -> bytes:
    """A real RADIS `unfall` file: 67 columns, `|`-delimited, header first."""
    rows = [gen.unfall_row(key, canton="AG") for key in keys]
    return cast("str", gen.structured(FileKind.UNFALL, rows)).encode("utf-8")


def astrana_unfall(keys: tuple[str, ...]) -> bytes:
    """`Unfall.csv` — the filename the old guard had no pattern for."""
    rows = [gen.astrana_unfall_row(key, canton="AG") for key in keys]
    return cast("bytes", gen.astrana_csv(FileKind.UNFALL, rows))


def text_narratives(keys: tuple[str, ...]) -> bytes:
    """The `;`-delimited narrative file — the sensitive payload itself."""
    rows = [(key, "Auffahrunfall auf der Hauptstrasse.") for key in keys]
    return cast("str", gen.text_file(rows)).encode("utf-8")


# ===========================================================================
# The C1 scenario: a delivery file in the tree, correctly named
# ===========================================================================


@pytest.mark.parametrize(
    ("relative", "build"),
    [
        pytest.param("Unfall.csv", astrana_unfall, id="astrana-at-the-root"),
        pytest.param("debug/Objekt.csv", astrana_unfall, id="astrana-in-a-subdir"),
        pytest.param("unfall.txt", radis_unfall, id="radis"),
        pytest.param("scratch/text.csv", text_narratives, id="narratives"),
    ],
)
def test_a_delivery_file_anywhere_in_the_tree_is_refused(
    guard: ModuleType,
    tmp_path: Path,
    relative: str,
    build: Callable[[tuple[str, ...]], bytes],
) -> None:
    """The finding itself. Every one of these passed the name-shaped guard:
    none of `Unfall.csv`, `Objekt.csv`, `unfall.txt` or `text.csv` matches a
    `.gitignore` delivery pattern outside `data/`."""
    path = place(tmp_path, relative, build(DELIVERED_KEYS))

    assert guard.inspect(path) is not None


def test_the_old_name_patterns_would_have_let_it_through(guard: ModuleType) -> None:
    """Stated as a test so the gap cannot quietly reopen: if someone adds
    `Unfall.csv` to `FORBIDDEN_PATTERNS`, the test above stops proving that the
    **content** check is what caught it."""
    for name in ("Unfall.csv", "Objekt.csv", "Mitfahrende.csv", "unfall.txt"):
        assert guard.is_forbidden(name) is False


def test_the_guard_reads_the_content_not_the_extension(guard: ModuleType, tmp_path: Path) -> None:
    """Renaming it does not help. `.gitignore` is a name check by nature; this
    one is not, and that is the entire point of the change."""
    path = place(tmp_path, "notes/scratch.bak", radis_unfall(DELIVERED_KEYS))

    assert guard.inspect(path) is not None


def test_a_headerless_tail_of_a_delivery_is_refused(guard: ModuleType, tmp_path: Path) -> None:
    """A few rows pasted out of a delivery carry no header. They still start
    with a 32-hex key and a delimiter, which is what makes them records."""
    whole = radis_unfall(DELIVERED_KEYS).decode("utf-8").splitlines()
    path = place(tmp_path, "rows.txt", "\r\n".join(whole[1:]).encode("utf-8"))

    assert guard.inspect(path) is not None


# ===========================================================================
# The fixtures the repository commits on purpose stay committable
# ===========================================================================


def test_every_committed_fixture_passes(guard: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fourteen hazards are delivery files by construction — the real
    header, the real delimiters, 32-hex keys. A guard that refused them would
    be turned off within a day, which is the failure mode worth testing for."""
    monkeypatch.setattr(guard, "REPO_ROOT", REPO_ROOT)
    fixtures = sorted((REPO_ROOT / FIXTURE_ROOT).rglob("*"))
    committed = [f for f in fixtures if f.is_file() and f.suffix != ".py"]

    assert committed, "the hazard fixtures went missing"
    assert [f for f in committed if guard.inspect(str(f.relative_to(REPO_ROOT))) is not None] == []


def test_the_whole_repository_is_clean(guard: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--all`, the mode CI runs. Every tracked file, not only the changed
    ones: the question in CI is not "what did this branch add" but "is any of
    this in here at all"."""
    monkeypatch.setattr(guard, "REPO_ROOT", REPO_ROOT)

    assert guard.main(["--all"]) == 0


# ===========================================================================
# Invented keys or delivered ones — the rule no other control covers
# ===========================================================================


def test_delivered_keys_are_refused_even_in_the_fixtures_directory(
    guard: ModuleType, tmp_path: Path
) -> None:
    """The subtler mistake, and the tempting one: five real rows lifted into a
    fixture because a synthesised one did not reproduce the bug.

    CLAUDE.md requires hazards to be synthesised byte-exactly and forbids real
    data reaching a test. Until this, that was prose.
    """
    path = place(tmp_path, f"{FIXTURE_ROOT}hazards/h99/unfall.txt", radis_unfall(DELIVERED_KEYS))

    reason = guard.inspect(path)

    assert reason is not None
    assert "synthesised, never sampled" in reason


def test_invented_keys_in_the_fixtures_directory_are_allowed(
    guard: ModuleType, tmp_path: Path
) -> None:
    path = place(tmp_path, f"{FIXTURE_ROOT}hazards/h99/unfall.txt", radis_unfall(INVENTED_KEYS))

    assert guard.inspect(path) is None


def test_invented_keys_outside_the_fixtures_directory_are_still_refused(
    guard: ModuleType, tmp_path: Path
) -> None:
    """The two conditions are independent. A synthesised delivery file at the
    repository root is not real data, but it is not something that belongs
    there either, and the guard cannot tell a convincing synthetic from a
    delivery without reading values — which it will not do."""
    path = place(tmp_path, "unfall.txt", radis_unfall(INVENTED_KEYS))

    assert guard.inspect(path) is not None


def test_the_two_key_populations_do_not_overlap(guard: ModuleType) -> None:
    """The threshold is a gap, not a guess. `uid()` yields three to five
    distinct characters; a 32-hex key drawn from sixteen symbols yields about
    thirteen. `MAX_INVENTED_DISTINCT_CHARS` sits in the empty space between."""
    invented = [len(set(key)) for key in INVENTED_KEYS]
    delivered = [len(set(key)) for key in DELIVERED_KEYS]

    assert max(invented) <= guard.MAX_INVENTED_DISTINCT_CHARS < min(delivered)
    assert all(guard._was_invented(key) for key in INVENTED_KEYS)
    assert not any(guard._was_invented(key) for key in DELIVERED_KEYS)


# ===========================================================================
# What must keep working
# ===========================================================================


@pytest.mark.parametrize(
    "relative",
    [
        pytest.param("README.md", id="prose"),
        pytest.param("ra2/main.py", id="source"),
        pytest.param("notes/codes.csv", id="an-ordinary-csv"),
    ],
)
def test_ordinary_files_are_not_refused(guard: ModuleType, tmp_path: Path, relative: str) -> None:
    content = b"code,label\r\n1,Kollision\r\n2,Auffahrunfall\r\n"
    path = place(tmp_path, relative, content)

    assert guard.inspect(path) is None


def test_a_binary_file_is_not_read_as_a_table(guard: ModuleType, tmp_path: Path) -> None:
    """The vendored fonts and the Playwright artefacts are binary. Decoding
    them as text would be slow and would find nothing."""
    path = place(tmp_path, "ra2/ui/static/fonts/plex.woff2", b"wOF2\x00\x00\x00\x01" * 64)

    assert guard.inspect(path) is None


def test_the_name_patterns_still_stand(guard: ModuleType, tmp_path: Path) -> None:
    """Defence one is kept. It is cheap, it is what `.gitignore` says, and it
    catches a `.zip` whose contents this guard cannot see into."""
    path = place(tmp_path, "AstranaExport-2026.zip", b"PK\x03\x04not-really")

    assert guard.inspect(path) is not None


def test_the_guard_needs_no_third_party_package(tmp_path: Path) -> None:
    """`-S` runs without `site`, so nothing in `site-packages` is importable.

    CI's `no-real-data` job runs this on a bare Python with **no `uv sync` at
    all**, which is what lets the one gate whose failure cannot be undone by a
    later commit run first and depend on nothing. A third-party import creeping
    in would break that job, and a guard that fails open is worse than none.

    It holds because the guard imports `ra2.domain.parsing.headers` rather than
    keeping its own copy of the column vocabulary, and that module is pure
    domain: the stdlib and this repository, nothing else.
    """
    sample = tmp_path / "ordinary.txt"
    sample.write_text("nothing to see\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "-S", "-E", str(SCRIPT), str(sample)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr

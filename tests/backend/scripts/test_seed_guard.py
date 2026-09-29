"""`scripts/seed_dev.py` refuses to seed beside a real corpus (risk D8, `SD46`).

`reset_data.py --for-seed` already refuses real data under `just reset-seed`,
but the seed can be run on its own. A seed beside a delivered corpus is the
transition hazard D8 describes, so the seed checks for itself.

`scripts/` is not a package, so the module is loaded by path, as
`test_reset_data.py` does.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from tests.fixtures.factories import make_corpus_view

from ra2.services.readmodels import Page, SortDir

pytestmark = pytest.mark.backend

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def seed_dev() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ra2_seed_dev", REPO_ROOT / "scripts" / "seed_dev.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Corpora:
    def __init__(self, *synthetic: bool) -> None:
        self._views = tuple(
            make_corpus_view(f"c{i}", is_synthetic=flag) for i, flag in enumerate(synthetic)
        )

    async def list_corpora(self, **_: object) -> Page[object]:
        return Page(
            items=self._views,
            total=len(self._views),
            page=1,
            page_size=len(self._views) or 1,
            sort_key="imported_at",
            sort_dir=SortDir.DESC,
        )


@pytest.mark.parametrize(
    ("corpora", "real"),
    [((), 0), ((True, True), 0), ((True, False), 1), ((False, False), 2)],
)
async def test_the_seed_counts_the_corpora_that_are_not_synthetic(
    seed_dev: ModuleType, corpora: tuple[bool, ...], real: int
) -> None:
    services = SimpleNamespace(corpus=_Corpora(*corpora))
    assert await seed_dev.real_corpus_count(services) == real

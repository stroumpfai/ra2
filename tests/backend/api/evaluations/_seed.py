"""Shared fixtures for `/api/v1/{evaluations,runs,models}` backend tests
(K2, Wave 3): a real app over a real migrated temp-file SQLite database,
driven through `httpx.ASGITransport` — no network (sw-design.md §11.2).

`tests/backend/api/{evaluations,runs,models}/**` are all K2's own paths
(CONTRACTS.md), so this one module is not a cross-agent conflict. It is not a
`conftest.py` itself — pytest only auto-discovers fixtures from a module named
`conftest.py`, so each of the three directories' own `conftest.py` re-exports
what it needs from here with an explicit `as` alias (`import X as X`), the
form mypy strict's `no_implicit_reexport` requires. `tests/` carries no
`__init__.py`, but the absolute dotted path (`tests.backend.api.evaluations
._seed`) still resolves — namespace packages need none (confirmed against
this repo's own `tests.backend.api.census.conftest`-style imports).

**No live endpoint anywhere in this file.** `FakeLLMClient`, `StaticModel
Catalog` and `StaticGpuProbe` (`tests/fixtures/fake_llm.py`, `ra2/infra/
gpu.py`) are threaded through `create_app()`'s keyword arguments explicitly,
so nothing here constructs the real `OllamaLLMClient` / `OllamaModelCatalog`
that `create_app()` would default to — those touch a socket at call time
(§15.5), and this suite must pass on a machine with no GPU and nothing
listening on 11434.

`InlineTaskRunner` makes `POST .../launch` run its run(s) to completion
**synchronously** before the response comes back (same idiom as `tests/
backend/api/codelists/conftest.py`'s use of it for `.../analyse`) — a test
asserting on a run's final state needs no polling loop, and `GET /api/v1/
tasks/{id}` is C2's endpoint, not exercised here.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.conftest import FrozenClock, SeededFactory
from tests.fixtures.fake_llm import DEFAULT_MODELS, FakeLLMClient, StaticModelCatalog

from ra2.domain.ids import CorpusId, PromptTemplateId, RecordId
from ra2.infra.config import Settings
from ra2.infra.gpu import GpuInfo, StaticGpuProbe
from ra2.infra.tasks import InlineTaskRunner
from ra2.main import create_app
from ra2.persistence.models import Corpus, PromptTemplate, Record

__all__ = [
    "FITTING_MODEL",
    "FIXTURE_GPU",
    "NOW",
    "OVERSIZED_MODEL",
    "api_client",
    "api_gpu_probe",
    "api_ids",
    "api_llm_client",
    "api_model_catalog",
    "create_feature_config",
    "seed_corpus",
    "seed_ready",
    "seed_template",
]

#: A fixed instant. Only used for rows written directly (bypassing the
#: `frozen_clock`-driven service layer), so it need not match `FrozenClock`'s
#: own default — nothing here asserts elapsed time against it.
NOW = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)

#: The design's host: "gpu RTX 4090 24 GB" — same fixture the evaluation and
#: run service suites use, so a `fits_vram` verdict is the same number here.
FIXTURE_GPU = GpuInfo(name="RTX 4090", total_vram_bytes=24_000_000_000)

#: `DEFAULT_MODELS` by role, named rather than indexed at each call site.
FITTING_MODEL = DEFAULT_MODELS[0].tag
#: 42.5 GB against the fixture host's 24 GB — the design's disabled row.
OVERSIZED_MODEL = DEFAULT_MODELS[2].tag


@pytest.fixture
def api_ids() -> SeededFactory:
    return SeededFactory(prefix="api-eval")


@pytest.fixture
def api_llm_client() -> FakeLLMClient:
    """The default response is `"{}"` and never fails — enough for a launch
    to run every record to `done` with nothing to script. A test that needs
    scripted failures constructs its own `FakeLLMClient` and passes it through
    `api_client`'s `llm_client` override point... this fixture *is* that
    override point, so a test overrides it with its own fixture of the same
    name in a local `@pytest.fixture` when it needs different behaviour.
    """
    return FakeLLMClient()


@pytest.fixture
def api_model_catalog() -> StaticModelCatalog:
    """A reachable endpoint with the design's fixture models. A test
    exercising the unreachable-endpoint path calls
    `api_model_catalog.set_status(EndpointStatus.UNREACHABLE)` before its
    request — the same mutable-double idiom `evaluation`/`run` service tests
    already use, rather than a second app fixture.
    """
    return StaticModelCatalog()


@pytest.fixture
def api_gpu_probe() -> StaticGpuProbe:
    return StaticGpuProbe(FIXTURE_GPU)


@pytest_asyncio.fixture
async def api_client(
    run_upgrade_head: Settings,
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: FrozenClock,
    api_ids: SeededFactory,
    api_llm_client: FakeLLMClient,
    api_model_catalog: StaticModelCatalog,
    api_gpu_probe: StaticGpuProbe,
) -> AsyncIterator[AsyncClient]:
    """An `AsyncClient` over the real composition root, real migrated DB,
    `mount_ui=False` — no NiceGUI, no network (J6)."""
    app = create_app(
        settings=run_upgrade_head,
        session_factory=db_session_factory,
        clock=frozen_clock,
        ids=api_ids,
        task_runner=InlineTaskRunner(api_ids),
        llm_client=api_llm_client,
        model_catalog=api_model_catalog,
        gpu_probe=api_gpu_probe,
        mount_ui=False,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def seed_corpus(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[str]]:
    """A corpus and `record_count` records, written directly — there is no
    delivery-import round trip in this router's own tests, that pipeline is
    C1's (`tests/backend/api/deliveries/**`, `corpora/**`)."""

    async def _seed(
        *, corpus_id: str = "corpus-1", record_count: int = 2, name: str = "Zurich 2024"
    ) -> str:
        async with db_session_factory() as session:
            session.add(
                Corpus(
                    id=CorpusId(corpus_id),
                    name=name,
                    imported_at=NOW,
                    source_file_manifest_json="[]",
                    import_report_json="[]",
                    record_count=record_count,
                )
            )
            await session.flush()
            for n in range(record_count):
                session.add(
                    Record(
                        id=RecordId(f"{corpus_id}-rec-{n:03d}"),
                        corpus_id=CorpusId(corpus_id),
                        unfall_uid=f"UID{n:05d}",
                        language="de",
                        language_confidence=0.99,
                        text_raw=f"Narrative {n}",
                    )
                )
            await session.commit()
        return corpus_id

    return _seed


@pytest.fixture
def seed_template(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[..., Awaitable[str]]:
    """One `prompt_template` version, active by default — the version
    `EvaluationService.save_draft` picks up (§15.1)."""

    async def _seed(*, template_id: str = "pt-1", version: int = 1, active: bool = True) -> str:
        async with db_session_factory() as session:
            session.add(
                PromptTemplate(
                    id=PromptTemplateId(template_id),
                    version=version,
                    source="{{feature_block}}\n{{narrative}}",
                    created_at=NOW,
                    activated_at=NOW if active else None,
                    fingerprint=f"fp-template-{version}",
                )
            )
            await session.commit()
        return template_id

    return _seed


@pytest.fixture
def create_feature_config(
    api_client: AsyncClient,
) -> Callable[..., Awaitable[str]]:
    """A feature config through the real `/feature-configs` API (F2, phase 2)
    — one `exploratory` `free_text` feature, so a launch built on it never
    needs a codelist snapshot: `EvaluationService._snapshots` skips
    `Kind.EXPLORATORY` unconditionally (sw-design.md §15.2). The two
    mvp-spec.md §7 codelist launch-refusal gates are `EvaluationService`'s own
    test suite's job (I2), not this router's — this fixture exists to reach a
    launchable state with the least setup, not to re-prove that gate.
    """

    async def _create(*, name: str = "Notes", frozen: bool = True) -> str:
        resp = await api_client.post("/api/v1/feature-configs", json={"name": name})
        assert resp.status_code == 201, resp.text
        config_id: str = resp.json()["feature_config_id"]
        resp = await api_client.post(
            f"/api/v1/feature-configs/{config_id}/features",
            json={
                "key": "note",
                "kind": "exploratory",
                "description": "A free-text note.",
                "grain": "accident",
                "source_column": "Bemerkung",
                "value_type": "free_text",
                "matching_rule": {"kind": "none"},
            },
        )
        assert resp.status_code == 200, resp.text
        if not frozen:
            return config_id
        resp = await api_client.post(f"/api/v1/feature-configs/{config_id}/freeze")
        assert resp.status_code == 200, resp.text
        return config_id

    return _create


@pytest.fixture
def seed_ready(
    api_client: AsyncClient,
    seed_corpus: Callable[..., Awaitable[str]],
    seed_template: Callable[..., Awaitable[str]],
    create_feature_config: Callable[..., Awaitable[str]],
) -> Callable[..., Awaitable[dict[str, str]]]:
    """Everything a launch needs, wired through the real API: a corpus, an
    active template, a feature config (frozen by default), a saved draft
    citing both, and — when `models` is given — that selection saved too.

    Returns `{"corpus_id", "feature_config_id", "evaluation_id"}`.
    """

    async def _build(
        *,
        template: bool = True,
        frozen: bool = True,
        models: Sequence[str] = (),
        record_count: int = 2,
    ) -> dict[str, str]:
        corpus_id = await seed_corpus(record_count=record_count)
        if template:
            await seed_template()
        config_id = await create_feature_config(frozen=frozen)
        resp = await api_client.post(
            "/api/v1/evaluations",
            json={"name": "Weather eval", "corpus_id": corpus_id, "feature_config_id": config_id},
        )
        assert resp.status_code == 201, resp.text
        evaluation_id: str = resp.json()["evaluation_id"]
        if models:
            resp = await api_client.put(
                f"/api/v1/evaluations/{evaluation_id}",
                json={"selected_models": list(models)},
            )
            assert resp.status_code == 200, resp.text
        return {
            "corpus_id": corpus_id,
            "feature_config_id": config_id,
            "evaluation_id": evaluation_id,
        }

    return _build

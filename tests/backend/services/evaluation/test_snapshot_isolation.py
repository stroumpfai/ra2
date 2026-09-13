"""R5's test: the snapshot is independent of later `column_mapping` edits.

`plan-phase-3.md` §14 R5 — *`evaluation_feature` is a table this plan invents
... if it is wrong the fingerprints are wrong.* This module is the reason it
exists, seen from the evaluation's side:

- `mvp-spec.md` §19.3 — re-pointing a mapping **changes** the affected
  features' fingerprints, for an evaluation created afterwards;
- `mvp-spec.md` §8.5 — the snapshot is "a copy, not a live reference, so a
  later `code_table_import` never moves the fingerprint of an
  already-created evaluation";
- `mvp-spec.md` §19.8 — and therefore an already-launched run stays
  reproducible.

The first two pull in opposite directions, and only the launch-time snapshot
satisfies both. That is what is asserted here.
"""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ra2.domain.ids import CodeAttributeId, CorpusId, EvaluationId
from ra2.persistence.models import EvaluationFeature
from ra2.services.evaluation_service import EvaluationService, snapshot_from_json
from ra2.services.readmodels import FeatureConfigView

pytestmark = pytest.mark.backend


async def _snapshot(
    session_factory: async_sessionmaker[AsyncSession], evaluation_id: str
) -> tuple[str | None, str]:
    """`(enum_codelist_json, fingerprint)` of the one enum feature's row."""
    async with session_factory() as session:
        row = await session.scalar(
            select(EvaluationFeature).where(EvaluationFeature.evaluation_id == evaluation_id)
        )
    assert row is not None
    return row.enum_codelist_json, row.fingerprint


async def test_repointing_a_mapping_after_launch_leaves_the_snapshot_untouched(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    map_column: Callable[..., Awaitable[None]],
    seed_codelists: Callable[..., Awaitable[dict[str, CodeAttributeId]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    attribute_keys: dict[str, str],
) -> None:
    """**The** exit-criterion test. Launch, then re-point the corpus's
    `column_mapping` at a different imported attribute, and assert the stored
    `enum_codelist_json` — and the fingerprint over it — have not moved."""
    corpus_id, _, evaluation_id = await launchable()
    await evaluation_service.launch(EvaluationId(evaluation_id))
    before_json, before_fingerprint = await _snapshot(db_session_factory, evaluation_id)
    assert before_json is not None
    assert "Klar" in before_json

    # The analyst re-points the column at a completely different code table —
    # mvp-spec.md §7's "freely re-editable".
    attributes = await seed_codelists()
    await map_column(corpus_id, attributes[attribute_keys["road"]])

    after_json, after_fingerprint = await _snapshot(db_session_factory, evaluation_id)

    assert after_json == before_json
    assert after_fingerprint == before_fingerprint
    # And the copy still says what it said: not one label of the new table.
    assert "Autobahn" not in (after_json or "")
    labels = {value.code: value.label["de"] for value in snapshot_from_json(after_json or "")}
    assert labels == {"01": "Klar", "02": "Regen"}


async def test_an_evaluation_launched_after_the_repoint_gets_the_new_table(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    map_column: Callable[..., Awaitable[None]],
    seed_codelists: Callable[..., Awaitable[dict[str, CodeAttributeId]]],
    db_session_factory: async_sessionmaker[AsyncSession],
    attribute_keys: dict[str, str],
    fitting_model: str,
) -> None:
    """The other half of mvp-spec.md §19.3: re-pointing a mapping **does**
    change the affected features' fingerprints — for an evaluation created
    after it. A snapshot that never moved for anybody would satisfy the test
    above by being broken."""
    corpus_id, config, first_id = await launchable()
    await evaluation_service.launch(EvaluationId(first_id))
    first_json, first_fingerprint = await _snapshot(db_session_factory, first_id)

    attributes = await seed_codelists()
    await map_column(corpus_id, attributes[attribute_keys["road"]])

    second = await evaluation_service.save_draft(
        name="After the re-point",
        corpus_id=corpus_id,
        feature_config_id=config.feature_config_id,
    )
    await evaluation_service.update_draft(second.evaluation_id, selected_models=(fitting_model,))
    await evaluation_service.launch(second.evaluation_id)
    second_json, second_fingerprint = await _snapshot(db_session_factory, second.evaluation_id)

    assert second_json != first_json
    assert second_fingerprint != first_fingerprint
    assert "Autobahn" in (second_json or "")
    # The first evaluation is untouched by the second's launch.
    assert await _snapshot(db_session_factory, first_id) == (first_json, first_fingerprint)


async def test_the_same_frozen_config_against_two_corpora_gets_two_snapshots(
    evaluation_service: EvaluationService,
    launchable: Callable[..., Awaitable[tuple[CorpusId, FeatureConfigView, str]]],
    seed_corpus: Callable[..., Awaitable[CorpusId]],
    seed_codelists: Callable[..., Awaitable[dict[str, CodeAttributeId]]],
    map_column: Callable[..., Awaitable[None]],
    db_session_factory: async_sessionmaker[AsyncSession],
    attribute_keys: dict[str, str],
    fitting_model: str,
) -> None:
    """§15 F2's whole reason for inventing this table: a frozen
    `feature_config` is corpus-**independent**, so the same one cited against
    two corpora resolves to two different codelist generations and therefore
    two different fingerprints. Putting the snapshot on `feature` could not
    express that."""
    _, config, first_id = await launchable()
    await evaluation_service.launch(EvaluationId(first_id))
    first_json, first_fingerprint = await _snapshot(db_session_factory, first_id)

    other_corpus = await seed_corpus(corpus_id="corpus-2", name="Bern 2024")
    attributes = await seed_codelists()
    await map_column(other_corpus, attributes[attribute_keys["road"]], mapping_id="cm-corpus-2")
    second = await evaluation_service.save_draft(
        name="Bern eval", corpus_id=other_corpus, feature_config_id=config.feature_config_id
    )
    await evaluation_service.update_draft(second.evaluation_id, selected_models=(fitting_model,))
    await evaluation_service.launch(second.evaluation_id)
    second_json, second_fingerprint = await _snapshot(db_session_factory, second.evaluation_id)

    assert first_json != second_json
    assert first_fingerprint != second_fingerprint

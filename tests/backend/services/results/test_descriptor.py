"""The identity line every board carries — `RunDescriptorView`.

`design/results/README.md` §2 draws it as `Corpus 2026-09-02 · 4 978 records ·
3 models` beside a `cfg 4f9a2c1e` chip, and states the rule: **every tab must
carry it**. `readmodels.RunDescriptorView` puts it as *"a score without its
config is not a result"*.

It was placeholder data. Three services each held a byte-identical private
builder returning `record_count=0`, the corpus **id** where the label goes and
the feature config **id** where the design asks for a hash — so every Results,
Ranking and Mismatches board read `Corpus 01a0bebb-… · 0 records`, over
numbers computed from thousands of them.

**Asserted through all three services, not against `build_descriptor`.** The
triplication is why the stub survived four phases: a unit test on one builder
would have been green while the other two lied. These call the boards, which
is the only way the claim "every tab carries it" can be a claim at all. Nothing
here asserts `record_count == 0` is *wrong* in the abstract — it asserts the
number matches the corpus the board is about, which is the only version of the
assertion a future stub cannot satisfy.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.scored_corpus import ScoredCorpus

from ra2.persistence.models import Corpus
from ra2.services.mismatch_service import MismatchService
from ra2.services.ranking_service import RankingService
from ra2.services.results_service import ResultsService

pytestmark = pytest.mark.backend

#: `seed_scored_corpus(records=40)`. Named rather than inlined so the three
#: assertions below read as "the corpus's own count" rather than as a literal
#: that happens to match.
SEEDED_RECORDS = 40


async def test_the_extraction_board_names_the_corpus_and_counts_its_records(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    view = await results_service.extraction_tab(scored.evaluation_id)

    assert view.descriptor.record_count == SEEDED_RECORDS
    assert view.descriptor.corpus_label.startswith("scored corpus")
    assert view.descriptor.model_count == len(scored.run_ids)


async def test_the_presence_board_carries_the_same_line(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    view = await results_service.presence_tab(scored.evaluation_id)

    assert view.descriptor.record_count == SEEDED_RECORDS
    assert view.descriptor.corpus_label.startswith("scored corpus")


async def test_the_ranking_board_carries_the_same_line(
    ranking_service: RankingService, scored: ScoredCorpus
) -> None:
    view = await ranking_service.ranking_tab(scored.evaluation_id)

    assert view.descriptor.record_count == SEEDED_RECORDS
    assert view.descriptor.corpus_label.startswith("scored corpus")


async def test_the_mismatch_board_carries_the_same_line(
    db_session_factory: async_sessionmaker[AsyncSession],
    frozen_clock: object,
    scored: ScoredCorpus,
) -> None:
    """Mismatches is the fourth surface and had the third copy of the stub."""
    service = MismatchService(session_factory=db_session_factory, clock=frozen_clock)  # type: ignore[arg-type]

    view = await service.list_mismatches(scored.evaluation_id, run_id=scored.run_ids[0])

    assert view.descriptor.record_count == SEEDED_RECORDS
    assert view.descriptor.corpus_label.startswith("scored corpus")


async def test_the_cfg_chip_is_a_hash_and_not_the_config_id(
    results_service: ResultsService, scored: ScoredCorpus
) -> None:
    """`design/results/README.md`'s context block names the field `cfgHash`,
    and the chip it draws — `cfg 4f9a2c1e` — is eight hex characters.

    The id and the hash answer different questions: the id says *which row*,
    the hash says *whether two sets ask the same thing*. A config cloned and
    re-frozen without an edit gets a new id and keeps its hash, which is the
    comparison a reader of two boards needs — and the reason showing the id
    here was not merely untidy.
    """
    fingerprint = (await results_service.extraction_tab(scored.evaluation_id)).descriptor

    assert fingerprint.config_fingerprint != scored.feature_config_id
    assert len(fingerprint.config_fingerprint) == 64
    assert set(fingerprint.config_fingerprint) <= set("0123456789abcdef")


async def test_the_corpus_cannot_be_removed_out_from_under_a_board(
    scored: ScoredCorpus,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Why the descriptor's "(corpus removed)" branch is defensive, not live.

    `Evaluation.corpus_id` is `ondelete=RESTRICT`, so the database refuses to
    remove a corpus an evaluation still cites — which is exactly the guarantee
    that lets the boards name their corpus without checking first. Asserted
    here rather than assumed, because the day that FK is relaxed the branch
    stops being unreachable and somebody should find out from a test.

    (`Record.corpus_id` is `CASCADE` by contrast: records are the corpus, an
    evaluation only points at it.)
    """
    async with db_session_factory() as session:
        corpus = await session.get(Corpus, scored.corpus_id)
        assert corpus is not None
        await session.delete(corpus)
        with pytest.raises(IntegrityError):
            await session.commit()

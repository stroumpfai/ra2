"""`get`, `list_corpora` (sort + page as parameters) and the delete guard."""

import pytest
from sqlalchemy import func, select

from ra2.domain.ids import CorpusId
from ra2.persistence.models import Corpus, Record
from ra2.services.errors import CorpusLockedError, NotFoundError
from ra2.services.readmodels import SortDir

pytestmark = pytest.mark.backend


@pytest.fixture
def three_corpora(corpus_service, analysed_golden_delivery, clock):
    """Three frozen corpora, each a minute apart, in a known order."""

    async def _freeze() -> list[CorpusId]:
        delivery_id = await analysed_golden_delivery()
        ids: list[CorpusId] = []
        for name in ("charlie", "alpha", "bravo"):
            ids.append(await corpus_service.freeze(delivery_id, name=name))
            clock.advance(seconds=60)
        return ids

    return _freeze


async def test_get_raises_not_found_for_an_unknown_corpus(corpus_service):
    with pytest.raises(NotFoundError) as missing:
        await corpus_service.get(CorpusId("no-such-corpus"))
    assert missing.value.kind == "corpus"


async def test_list_corpora_is_newest_first_by_default(corpus_service, three_corpora):
    charlie, alpha, bravo = await three_corpora()

    page = await corpus_service.list_corpora()

    assert page.sort_key == "imported_at"
    assert page.sort_dir is SortDir.DESC
    assert page.total == 3
    assert [c.corpus_id for c in page.items] == [bravo, alpha, charlie]


async def test_sort_and_page_are_service_call_parameters(corpus_service, three_corpora):
    await three_corpora()

    first = await corpus_service.list_corpora(
        sort_key="name", sort_dir=SortDir.ASC, page=1, page_size=2
    )
    second = await corpus_service.list_corpora(
        sort_key="name", sort_dir=SortDir.ASC, page=2, page_size=2
    )

    assert [c.name for c in first.items] == ["alpha", "bravo"]
    assert [c.name for c in second.items] == ["charlie"]
    # The design's "1-25 of 162" needs both numbers.
    assert (first.total, first.page, first.page_size) == (3, 1, 2)


async def test_an_unknown_sort_key_falls_back_to_the_default(corpus_service, three_corpora):
    await three_corpora()
    page = await corpus_service.list_corpora(sort_key="favourite_colour")
    assert page.sort_key == "imported_at"


async def test_delete_removes_the_corpus_and_everything_below_it(
    corpus_service, analysed_golden_delivery, db_session_factory
):
    delivery_id = await analysed_golden_delivery()
    corpus_id = await corpus_service.freeze(delivery_id, name="throwaway")

    await corpus_service.delete(corpus_id)

    async with db_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Corpus)) == 0
        assert await session.scalar(select(func.count()).select_from(Record)) == 0


async def test_delete_is_refused_while_an_evaluation_cites_the_corpus(
    corpus_service, analysed_golden_delivery, seed_evaluation, db_session_factory
):
    delivery_id = await analysed_golden_delivery()
    corpus_id = await corpus_service.freeze(delivery_id, name="cited")
    await seed_evaluation(corpus_id)

    with pytest.raises(CorpusLockedError) as locked:
        await corpus_service.delete(corpus_id)

    assert locked.value.corpus_id == corpus_id
    assert locked.value.evaluation_count == 1
    # The runs that cite it would stop being reproducible, so it is still here.
    async with db_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Corpus)) == 1
    # And the pill the UI renders comes off the same number (J3).
    assert (await corpus_service.get(corpus_id)).is_locked is True
    assert (await corpus_service.get(corpus_id)).locked_by_evaluations == 1


async def test_delete_of_an_unknown_corpus_raises_not_found(corpus_service):
    with pytest.raises(NotFoundError):
        await corpus_service.delete(CorpusId("no-such-corpus"))

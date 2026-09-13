"""`activate()` and `delete()` (sw-design.md §15.1).

Exit criteria covered: exactly one row is active at a time, asserted after an
activate-twice sequence; deleting a cited version raises and deletes nothing.
"""

import pytest

from ra2.domain.ids import PromptTemplateId
from ra2.services.errors import NotFoundError, PromptTemplateCitedError

pytestmark = pytest.mark.backend


async def test_activating_a_version_marks_it_active(prompt_service, seed_template):
    await seed_template("pt-1", version=1)

    activated = await prompt_service.activate(PromptTemplateId("pt-1"))

    assert activated.is_active is True


async def test_activate_twice_leaves_exactly_one_row_active(prompt_service, seed_template):
    await seed_template("pt-1", version=1)
    await seed_template("pt-2", version=2)

    await prompt_service.activate(PromptTemplateId("pt-1"))
    await prompt_service.activate(PromptTemplateId("pt-2"))

    versions = await prompt_service.list_versions()
    active = [v for v in versions if v.is_active]
    assert len(active) == 1
    assert active[0].prompt_template_id == "pt-2"

    first = await prompt_service.get(PromptTemplateId("pt-1"))
    assert first.is_active is False


async def test_activate_raises_not_found_for_an_unknown_id(prompt_service):
    with pytest.raises(NotFoundError):
        await prompt_service.activate(PromptTemplateId("does-not-exist"))


async def test_delete_removes_an_uncited_version(prompt_service, seed_template):
    await seed_template("pt-1", version=1)

    await prompt_service.delete(PromptTemplateId("pt-1"))

    with pytest.raises(NotFoundError):
        await prompt_service.get(PromptTemplateId("pt-1"))


async def test_delete_raises_not_found_for_an_unknown_id(prompt_service):
    with pytest.raises(NotFoundError):
        await prompt_service.delete(PromptTemplateId("does-not-exist"))


async def test_deleting_a_cited_version_raises_and_deletes_nothing(
    prompt_service, seed_template, seed_minimal_feature_config, seed_evaluation_with_snapshot
):
    await seed_template("pt-1", version=1)
    config_id = await seed_minimal_feature_config("fc-1")
    await seed_evaluation_with_snapshot(
        "eval-1",
        corpus_id="corpus-1",
        feature_config_id=config_id,
        prompt_template_id="pt-1",
        weather_feature_id="fc-1-weather",
        injured_feature_id="fc-1-injured",
        notes_feature_id="fc-1-notes",
        run_ids=("run-1",),
    )

    with pytest.raises(PromptTemplateCitedError) as excinfo:
        await prompt_service.delete(PromptTemplateId("pt-1"))

    assert excinfo.value.run_count == 1

    # Nothing was deleted.
    still_there = await prompt_service.get(PromptTemplateId("pt-1"))
    assert still_there.prompt_template_id == "pt-1"

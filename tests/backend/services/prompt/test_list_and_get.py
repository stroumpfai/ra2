"""`list_versions()`, `get()` and `slots()` (sw-design.md §15.1)."""

import pytest

from ra2.domain.ids import PromptTemplateId
from ra2.domain.prompt import REQUIRED_SLOTS, SlotName
from ra2.services.errors import NotFoundError

pytestmark = pytest.mark.backend


async def test_list_versions_is_empty_before_anything_is_saved(prompt_service):
    assert await prompt_service.list_versions() == []


async def test_list_versions_orders_newest_first_with_citation_counts(
    prompt_service, seed_template, seed_evaluation_with_snapshot, seed_minimal_feature_config
):
    await seed_template("pt-1", version=1, source="v1 {{narrative}} {{feature_block}}")
    await seed_template("pt-2", version=2, source="v2 {{narrative}} {{feature_block}}")
    config_id = await seed_minimal_feature_config("fc-1")
    await seed_evaluation_with_snapshot(
        "eval-1",
        corpus_id="corpus-1",
        feature_config_id=config_id,
        prompt_template_id="pt-1",
        weather_feature_id="fc-1-weather",
        injured_feature_id="fc-1-injured",
        notes_feature_id="fc-1-notes",
        run_ids=("run-1", "run-2"),
    )

    versions = await prompt_service.list_versions()

    assert [v.version for v in versions] == [2, 1]
    by_version = {v.version: v for v in versions}
    assert by_version[1].cited_by_run_count == 2
    assert by_version[1].deletable is False
    assert by_version[2].cited_by_run_count == 0
    assert by_version[2].deletable is True


async def test_get_returns_the_view_for_a_known_id(prompt_service, seed_template):
    await seed_template("pt-1", version=1, source="hello {{narrative}} {{feature_block}}")

    view = await prompt_service.get(PromptTemplateId("pt-1"))

    assert view.prompt_template_id == "pt-1"
    assert view.version == 1
    assert view.source == "hello {{narrative}} {{feature_block}}"
    assert view.is_active is False
    assert view.cited_by_run_count == 0


async def test_get_raises_not_found_for_an_unknown_id(prompt_service):
    with pytest.raises(NotFoundError):
        await prompt_service.get(PromptTemplateId("does-not-exist"))


async def test_slots_is_the_closed_catalogue(prompt_service):
    slots = await prompt_service.slots()

    assert [slot.name for slot in slots] == [
        SlotName.FEATURE_BLOCK,
        SlotName.NARRATIVE,
        SlotName.LANGUAGE,
    ]
    assert [slot.token for slot in slots] == [
        "{{feature_block}}",
        "{{narrative}}",
        "{{language}}",
    ]
    required = {slot.name for slot in slots if slot.required}
    assert required == set(REQUIRED_SLOTS)
    # never assembled in the view: the description travels verbatim.
    assert all(slot.resolves_to for slot in slots)

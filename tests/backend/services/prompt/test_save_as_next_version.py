"""`save_as_next_version()` — copy-on-write (sw-design.md §15.1).

The exit criterion that matters most here: saving over a **cited** version
creates a new row and leaves the old row's `source` byte-identical — asserted
on the raw bytes, not on equality of some parsed form, because the runs
citing the old version must keep resolving to exactly the text they used.
"""

import pytest

from ra2.domain.ids import PromptTemplateId
from ra2.domain.prompt import PromptValidationCode
from ra2.services.errors import PromptTemplateInvalidError

pytestmark = pytest.mark.backend

VALID_SOURCE = "Narrative: {{narrative}}\n\nFeatures:\n{{feature_block}}"


async def test_save_as_next_version_starts_the_lineage_at_v1(prompt_service):
    view = await prompt_service.save_as_next_version(VALID_SOURCE)

    assert view.version == 1
    assert view.source == VALID_SOURCE
    assert view.is_active is False
    assert view.cited_by_run_count == 0
    assert view.fingerprint  # sha256 hex digest, non-empty


async def test_save_as_next_version_is_monotonic(prompt_service):
    await prompt_service.save_as_next_version(VALID_SOURCE)
    second = await prompt_service.save_as_next_version(VALID_SOURCE + " v2")

    assert second.version == 2


async def test_saving_over_a_cited_version_creates_a_new_row_and_leaves_the_old_byte_identical(
    prompt_service, seed_evaluation_with_snapshot, seed_minimal_feature_config
):
    original_source = "Original: {{narrative}}\n{{feature_block}}"
    v1 = await prompt_service.save_as_next_version(original_source)

    config_id = await seed_minimal_feature_config("fc-1")
    await seed_evaluation_with_snapshot(
        "eval-1",
        corpus_id="corpus-1",
        feature_config_id=config_id,
        prompt_template_id=v1.prompt_template_id,
        weather_feature_id="fc-1-weather",
        injured_feature_id="fc-1-injured",
        notes_feature_id="fc-1-notes",
        run_ids=("run-1",),
    )

    edited_source = "Edited, byte-for-byte different: {{narrative}}\n{{feature_block}}"
    v2 = await prompt_service.save_as_next_version(edited_source)

    assert v2.version == 2
    assert v2.source == edited_source
    assert v2.prompt_template_id != v1.prompt_template_id

    # The cited row is untouched — re-fetched and compared byte-for-byte,
    # not merely "equal" through some parsed/normalised form.
    reloaded_v1 = await prompt_service.get(PromptTemplateId(v1.prompt_template_id))
    assert reloaded_v1.source.encode("utf-8") == original_source.encode("utf-8")
    assert reloaded_v1.version == 1
    assert reloaded_v1.cited_by_run_count == 1
    assert reloaded_v1.deletable is False


async def test_a_template_missing_a_required_slot_writes_nothing(prompt_service):
    with pytest.raises(PromptTemplateInvalidError) as excinfo:
        await prompt_service.save_as_next_version("no slots here at all")

    codes = {e.code for e in excinfo.value.validation_errors}
    assert PromptValidationCode.MISSING_REQUIRED_SLOT in codes
    assert await prompt_service.list_versions() == []


async def test_a_template_with_an_unknown_slot_writes_nothing(prompt_service):
    with pytest.raises(PromptTemplateInvalidError) as excinfo:
        await prompt_service.save_as_next_version("{{narrative}} {{feature_block}} {{bogus_slot}}")

    codes = {e.code for e in excinfo.value.validation_errors}
    assert PromptValidationCode.UNKNOWN_SLOT in codes
    assert await prompt_service.list_versions() == []


async def test_an_empty_template_writes_nothing(prompt_service):
    with pytest.raises(PromptTemplateInvalidError) as excinfo:
        await prompt_service.save_as_next_version("   ")

    codes = {e.code for e in excinfo.value.validation_errors}
    assert PromptValidationCode.EMPTY_SOURCE in codes
    assert await prompt_service.list_versions() == []


async def test_an_invalid_save_does_not_advance_the_version_counter(prompt_service):
    await prompt_service.save_as_next_version(VALID_SOURCE)

    with pytest.raises(PromptTemplateInvalidError):
        await prompt_service.save_as_next_version("not valid")

    third = await prompt_service.save_as_next_version(VALID_SOURCE + " again")
    assert third.version == 2  # not 3 — the failed save never touched the counter

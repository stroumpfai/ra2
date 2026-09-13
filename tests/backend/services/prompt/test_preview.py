"""`preview()` — resolve against a feature set and one record, no model call
(sw-design.md §15.1, plan-phase-3.md C4)."""

import pytest

from ra2.domain.ids import FeatureConfigId, PromptTemplateId, RecordId
from ra2.domain.prompt import SlotName
from ra2.services.errors import NotFoundError

pytestmark = pytest.mark.backend

TEMPLATE_SOURCE = "Language: {{language}}\nNarrative: {{narrative}}\nFeatures:\n{{feature_block}}"


async def test_preview_resolves_the_feature_block_and_narrative(
    prompt_service,
    seed_template,
    seed_minimal_feature_config,
    seed_mapped_enum_column,
    seed_record,
):
    template_id = await seed_template("pt-1", version=1, source=TEMPLATE_SOURCE)
    config_id = await seed_minimal_feature_config("fc-1", source_column="WitterungAusw")
    record_id = await seed_record(
        "rec-1",
        corpus_id="corpus-1",
        unfall_uid="uid-0001",
        text_raw="Es regnete stark.",
    )
    await seed_mapped_enum_column(
        corpus_id="corpus-1",
        source_column="WitterungAusw",
        import_id="import-1",
        attribute_id="attr-1",
    )

    view = await prompt_service.preview(
        template_id, FeatureConfigId(config_id), record_id, language="de"
    )

    assert "Es regnete stark." in view.text
    assert "weather" in view.text
    # The enum's full code -> label list, in the mapped language.
    assert "01 — Klar" in view.text
    assert "02 — Regen" in view.text
    # The exploratory attribute's description, verbatim, no type line.
    assert "notes: Anything else worth flagging." in view.text
    assert "Language: de" in view.text
    assert view.record_key == "uid-0001"
    assert view.feature_count == 3
    assert view.token_estimate > 0
    assert set(view.slots_used) == {SlotName.LANGUAGE, SlotName.NARRATIVE, SlotName.FEATURE_BLOCK}
    assert view.validation_errors == ()


async def test_preview_falls_back_visibly_for_a_code_with_no_label_in_the_requested_language(
    prompt_service,
    seed_template,
    seed_minimal_feature_config,
    seed_mapped_enum_column,
    seed_record,
):
    template_id = await seed_template("pt-1", source=TEMPLATE_SOURCE)
    config_id = await seed_minimal_feature_config("fc-1", source_column="WitterungAusw")
    record_id = await seed_record("rec-1", corpus_id="corpus-1")
    await seed_mapped_enum_column(
        corpus_id="corpus-1",
        source_column="WitterungAusw",
        import_id="import-1",
        attribute_id="attr-1",
    )

    view = await prompt_service.preview(
        template_id, FeatureConfigId(config_id), record_id, language="it"
    )

    assert "[no it label]" in view.text


async def test_preview_with_an_unmapped_enum_column_omits_the_code_list_but_still_resolves(
    prompt_service, seed_template, seed_minimal_feature_config, seed_record
):
    """No `column_mapping` at all — `preview()` must not raise; the feature
    block simply carries no per-code lines for that feature (mirrors
    `render_feature_block`'s own tolerance for `enum_codelist=None`)."""
    template_id = await seed_template("pt-1", source=TEMPLATE_SOURCE)
    config_id = await seed_minimal_feature_config("fc-1", source_column="WitterungAusw")
    record_id = await seed_record("rec-1", corpus_id="corpus-1")

    view = await prompt_service.preview(
        template_id, FeatureConfigId(config_id), record_id, language="de"
    )

    assert "weather" in view.text
    assert "01 —" not in view.text


async def test_preview_raises_not_found_for_an_unknown_template(
    prompt_service, seed_minimal_feature_config, seed_record
):
    config_id = await seed_minimal_feature_config("fc-1")
    record_id = await seed_record("rec-1", corpus_id="corpus-1")

    with pytest.raises(NotFoundError):
        await prompt_service.preview(
            PromptTemplateId("does-not-exist"), FeatureConfigId(config_id), record_id, language="de"
        )


async def test_preview_raises_not_found_for_an_unknown_feature_config(
    prompt_service, seed_template, seed_record
):
    template_id = await seed_template("pt-1", source=TEMPLATE_SOURCE)
    record_id = await seed_record("rec-1", corpus_id="corpus-1")

    with pytest.raises(NotFoundError):
        await prompt_service.preview(
            template_id, FeatureConfigId("does-not-exist"), record_id, language="de"
        )


async def test_preview_raises_not_found_for_an_unknown_record(
    prompt_service, seed_template, seed_minimal_feature_config
):
    template_id = await seed_template("pt-1", source=TEMPLATE_SOURCE)
    config_id = await seed_minimal_feature_config("fc-1")

    with pytest.raises(NotFoundError):
        await prompt_service.preview(
            template_id, FeatureConfigId(config_id), RecordId("does-not-exist"), language="de"
        )

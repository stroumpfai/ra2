"""A corpus shaped like the ones scoring gets wrong (plan-phase-4.md §7, S4).

This phase's `tests/fixtures/fake_llm.py`: six later agents build on it, so it
seeds a whole scoreable world in one call — corpus, records with their EAV
rows, a frozen feature config, an evaluation, a run, and extractions.

**Clean fixtures are not acceptable** (mvp-spec.md §15, CLAUDE.md). The
`h01`-`h14` delivery hazards, the `c01`-`c05` codelist hazards and the
`p01`-`p07` prompt hazards each encode the ways their input is really broken;
these are the ways a *scored* corpus is:

| | Hazard | What it is for |
|---|---|---|
| `s01` | a feature at **n = 17** | below the floor: suppressed, out of the macro |
| `s02` | two models whose intervals **overlap** | a tie, rendered as a tie |
| `s03` | two models whose intervals **do not** | a separating feature |
| `s04` | an **all-empty** source column | leaves the denominator entirely (§8.6) |
| `s05` | a **French, cp1252-damaged** record | the standing encoding caveat, in data |
| `s06` | an enum **outside the snapshot** | a `wrong` the codelist explains |
| `s07` | `present = false`, value matched | the flag-inconsistency / "114" case |
| `s08` | a `null` value, **non-null span** | evidence for a value never given |
| `s09` | a **derived** feature, zero objects | `"0"` is a value; the record stays in |

Every hazard is synthesised here, in code, and committed. Real data is
gitignored and must never reach a test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from ra2.domain.extraction import EvaluationSize, RunStatus
from ra2.domain.feature import (
    CountObjects,
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    ValueType,
    derivation_to_json,
)
from ra2.domain.ids import (
    CorpusId,
    EvaluationId,
    ExtractionId,
    FeatureConfigId,
    FeatureId,
    ObjektRowId,
    PersonRowId,
    PromptTemplateId,
    RecordId,
    RunId,
)
from ra2.persistence.models import (
    Corpus,
    Evaluation,
    Extraction,
    ExtractionValue,
    Feature,
    FeatureConfig,
    ObjektCell,
    ObjektRow,
    PersonCell,
    PersonRow,
    PromptTemplate,
    Record,
    Run,
    UnfallRow,
)
from ra2.services.feature_service import matching_rule_json

NOW: Final = datetime(2026, 9, 2, 9, 30, tzinfo=UTC)

#: `s05` — French text after the upstream cp1252 conversion has eaten the
#: accents. Byte-exact, committed, and never corrected for: the loss "is real
#: but **cannot be quantified**" (mvp-spec.md §4.4, design README §2c).
FRENCH_LOSSY: Final = "Le v hicule a d rap  sur la chauss e mouill e."

#: The feature keys this fixture seeds. Names are the real delivery's
#: (sw-design.md §13: the design's `WitterungAusw` does not exist).
WEATHER: Final = "Witter0Ausw"
LIGHT: Final = "LichtVerhAusw"
RIGHT_OF_WAY: Final = "VortrittAusw"
ALL_EMPTY: Final = "NieGefuelltFeld"


@dataclass(frozen=True, slots=True)
class ScoredCorpus:
    """What `seed_scored_corpus` built, by the name a test wants it under."""

    corpus_id: CorpusId
    evaluation_id: EvaluationId
    feature_config_id: FeatureConfigId
    run_ids: tuple[RunId, ...]
    #: `feature key -> id`, so a test names a hazard rather than an opaque id.
    feature_ids: dict[str, FeatureId]
    record_ids: tuple[RecordId, ...]


async def seed_scored_corpus(
    session: AsyncSession,
    *,
    suffix: str = "s",
    records: int = 40,
    models: tuple[str, ...] = ("qwen3:14b", "mistral-small:24b"),
) -> ScoredCorpus:
    """Seed one scoreable corpus carrying every hazard above.

    `records` is the corpus size; `s01`'s feature is deliberately populated on
    only 17 of them whatever that number is, because 17 is the hazard.
    """
    corpus_id = CorpusId(f"corpus-{suffix}")
    config_id = FeatureConfigId(f"config-{suffix}")
    evaluation_id = EvaluationId(f"eval-{suffix}")
    template_id = PromptTemplateId(f"template-{suffix}")

    session.add(
        Corpus(
            id=corpus_id,
            name=f"scored corpus {suffix}",
            imported_at=NOW,
            version=1,
            source_file_manifest_json="[]",
            import_report_json="[]",
            record_count=records,
            is_dev_sized=False,
            cp1252_canary_count=3,
        )
    )
    session.add(
        FeatureConfig(
            id=config_id, name=f"features {suffix}", version=1, created_at=NOW, frozen_at=NOW
        )
    )
    session.add(
        PromptTemplate(
            id=template_id,
            version=1,
            source="{{feature_block}}{{narrative}}",
            created_at=NOW,
            activated_at=NOW,
            fingerprint="f" * 64,
        )
    )
    await session.flush()

    feature_ids = await _seed_features(session, suffix, config_id)
    record_ids = await _seed_records(session, suffix, corpus_id, records)

    session.add(
        Evaluation(
            id=evaluation_id,
            name=f"evaluation {suffix}",
            corpus_id=corpus_id,
            feature_config_id=config_id,
            prompt_template_id=template_id,
            prompt_language="de",
            temperature=0.0,
            seed=42,
            size=EvaluationSize.FULL,
            selected_models_json="[]",
            min_cell_count=20,
            created_at=NOW,
            launched_at=NOW,
            is_dev=False,
        )
    )
    run_ids = tuple(RunId(f"run-{suffix}-{index}") for index, _ in enumerate(models))
    for run_id, model in zip(run_ids, models, strict=True):
        session.add(
            Run(
                id=run_id,
                evaluation_id=evaluation_id,
                model_name=model,
                model_digest=f"{model}-digest",
                prompt_template_version=1,
                prompt_template_id=template_id,
                prompt_template_fingerprint="f" * 64,
                temperature=0.0,
                seed=42,
                started_at=NOW,
                finished_at=NOW,
                status=RunStatus.DONE,
                host_platform="linux",
                gpu_name="none",
                llm_endpoint="http://127.0.0.1:11434/v1",
            )
        )
    await session.flush()

    await _seed_extractions(session, suffix, run_ids, record_ids, feature_ids)
    await session.flush()

    return ScoredCorpus(
        corpus_id=corpus_id,
        evaluation_id=evaluation_id,
        feature_config_id=config_id,
        run_ids=run_ids,
        feature_ids=feature_ids,
        record_ids=record_ids,
    )


async def _seed_features(
    session: AsyncSession, suffix: str, config_id: FeatureConfigId
) -> dict[str, FeatureId]:
    # `feature.matching_rule` holds serialised JSON (M0-D8), not the
    # dataclass — the same codec `feature_service` writes with.
    exact = matching_rule_json(MatchingRule(kind=MatchingRuleKind.EXACT))
    specs: list[tuple[str, dict[str, object]]] = [
        # s02/s03: two ordinary enum features, well populated.
        (WEATHER, {"source_column": WEATHER, "value_type": ValueType.ENUM}),
        (LIGHT, {"source_column": LIGHT, "value_type": ValueType.ENUM}),
        # s01: populated on 17 records only — below the floor of 20.
        (RIGHT_OF_WAY, {"source_column": RIGHT_OF_WAY, "value_type": ValueType.ENUM}),
        # s04: the column exists in the config and in no record.
        (ALL_EMPTY, {"source_column": ALL_EMPTY, "value_type": ValueType.ENUM}),
    ]
    feature_ids: dict[str, FeatureId] = {}
    for ordinal, (key, extra) in enumerate(specs):
        feature_id = FeatureId(f"feature-{suffix}-{key}")
        feature_ids[key] = feature_id
        session.add(
            Feature(
                id=feature_id,
                feature_config_id=config_id,
                ordinal=ordinal,
                key=key,
                kind=Kind.LABELLED,
                description=f"{key} for scoring tests",
                grain=Grain.ACCIDENT,
                matching_rule=exact,
                fingerprint=f"{ordinal:064d}",
                **extra,
            )
        )
    # s09: a derived feature. `count_objects` over a record with no objects is
    # `"0"` — a value, so the record stays in the denominator (§16.2).
    derived_id = FeatureId(f"feature-{suffix}-vehicles")
    feature_ids["vehicles"] = derived_id
    session.add(
        Feature(
            id=derived_id,
            feature_config_id=config_id,
            ordinal=len(specs),
            key="vehicles",
            kind=Kind.LABELLED,
            description="vehicles involved",
            grain=Grain.DERIVED,
            derivation_json=derivation_to_json(CountObjects()),
            value_type=ValueType.INTEGER,
            matching_rule=exact,
            fingerprint=f"{len(specs):064d}",
        )
    )
    await session.flush()
    return feature_ids


async def _seed_records(
    session: AsyncSession, suffix: str, corpus_id: CorpusId, count: int
) -> tuple[RecordId, ...]:
    record_ids: list[RecordId] = []
    for index in range(count):
        record_id = RecordId(f"rec-{suffix}-{index:03d}")
        record_ids.append(record_id)
        # s05: every third record is French, and its text is already lossy.
        french = index % 3 == 0
        session.add(
            Record(
                id=record_id,
                corpus_id=corpus_id,
                unfall_uid=f"U{suffix}{index:030d}",
                language="fr" if french else "de",
                language_confidence=0.41 if french else 0.98,
                text_raw=FRENCH_LOSSY if french else "Schneefall, Strasse nass.",
                text_anonymised_flag=True,
            )
        )
        session.add(
            UnfallRow(record_id=record_id, column_name=WEATHER, value_raw=str(index % 4 + 1))
        )
        session.add(UnfallRow(record_id=record_id, column_name=LIGHT, value_raw=str(index % 3 + 1)))
        # s01: only the first 17 records carry this column at all.
        if index < 17:
            session.add(UnfallRow(record_id=record_id, column_name=RIGHT_OF_WAY, value_raw="2"))
        # s04: `ALL_EMPTY` is written for nobody — the column is configured and
        # never populated, so its feature has n = 0 and produces no rows.

        # s09: every other record has two objekt rows; the rest have none, so
        # `count_objects` is "2" or "0" and both are labelled cases.
        if index % 2 == 0:
            for obj_index in range(2):
                objekt_id = ObjektRowId(f"obj-{suffix}-{index:03d}-{obj_index}")
                session.add(
                    ObjektRow(
                        id=objekt_id,
                        record_id=record_id,
                        objekt_uid=f"O{suffix}{index:03d}{obj_index}",
                        obj_nr=obj_index + 1,
                    )
                )
                session.add(
                    ObjektCell(objekt_row_id=objekt_id, column_name="ObjArtAusw", value_raw="01")
                )
                person_id = PersonRowId(f"per-{suffix}-{index:03d}-{obj_index}")
                session.add(
                    PersonRow(
                        id=person_id,
                        objekt_row_id=objekt_id,
                        person_uid=f"P{suffix}{index:03d}{obj_index}",
                        pers_nr=1,
                    )
                )
                session.add(
                    PersonCell(person_row_id=person_id, column_name="VerlAusw", value_raw="2")
                )
    await session.flush()
    return tuple(record_ids)


async def _seed_extractions(
    session: AsyncSession,
    suffix: str,
    run_ids: tuple[RunId, ...],
    record_ids: tuple[RecordId, ...],
    feature_ids: dict[str, FeatureId],
) -> None:
    """One extraction per (run, record), with the value hazards on top."""
    for run_index, run_id in enumerate(run_ids):
        for index, record_id in enumerate(record_ids):
            extraction_id = ExtractionId(f"ext-{suffix}-{run_index}-{index:03d}")
            session.add(
                Extraction(
                    id=extraction_id,
                    run_id=run_id,
                    record_id=record_id,
                    raw_output_text="{}",
                    parse_ok=True,
                    latency_ms=900 + index,
                    prompt_tokens=1200,
                    completion_tokens=40,
                    retry_count=0,
                )
            )
            # The second model is deliberately worse on `WEATHER`, so the two
            # separate there (s03) and overlap on `LIGHT` (s02).
            weather_wrong = (index % 4 == 0) if run_index else (index % 9 == 0)
            weather_value = str((index % 4 + 2) if weather_wrong else (index % 4 + 1))
            session.add(
                ExtractionValue(
                    extraction_id=extraction_id,
                    feature_id=feature_ids[WEATHER],
                    value_raw=weather_value,
                    value_normalised=weather_value,
                    # s07: on one record the model says the text does NOT
                    # contain the feature and extracts the right value anyway.
                    present_flag=index != 5,
                    evidence_span="Schneefall",
                )
            )
            light_value = str(index % 3 + 1)
            session.add(
                ExtractionValue(
                    extraction_id=extraction_id,
                    feature_id=feature_ids[LIGHT],
                    # s06: one extracted code is outside the codelist snapshot.
                    value_raw="99" if index == 7 else light_value,
                    value_normalised="99" if index == 7 else light_value,
                    present_flag=True,
                    evidence_span="Dunkelheit",
                )
            )
            # s08: a null value that still carries an evidence span.
            session.add(
                ExtractionValue(
                    extraction_id=extraction_id,
                    feature_id=feature_ids["vehicles"],
                    value_raw=None if index == 9 else ("2" if index % 2 == 0 else "0"),
                    value_normalised=None if index == 9 else ("2" if index % 2 == 0 else "0"),
                    present_flag=True,
                    evidence_span="zwei Fahrzeuge",
                )
            )

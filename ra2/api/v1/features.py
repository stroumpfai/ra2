# STUB — bodies owned by F2 (feat/p2-api-features). Not frozen.
"""`/api/v1/feature-configs` — list, create draft, add/edit/delete feature,
freeze, clone (mvp-spec.md §8, plan-phase-2.md §9).

Freezing a config with a blocking error returns 422 and creates nothing; a
frozen config's edit endpoints return 409.

`validate_against` (Wave 2's `FeatureService.add_feature`/`edit_feature`/
`freeze` keyword, feature_service.py's module docstring) is a per-call
validation context, never persisted — there is no field for it on the frozen
request schemas, so it is a plain optional query parameter here.
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ra2.api.deps import FeatureServiceDep
from ra2.api.schemas import (
    CloneFeatureConfigRequest,
    CreateFeatureConfigRequest,
    DerivationFilterSchema,
    DerivationSpecSchema,
    ErrorResponse,
    FeatureConfigResponse,
    FeatureConfigSummaryResponse,
    FeatureRequest,
    FeatureResponse,
    FeatureValidationErrorResponse,
    MatchingRuleSchema,
)
from ra2.domain.feature import (
    AnyObjectMatches,
    AnyPersonMatches,
    CountObjects,
    CountPersons,
    DerivationSpec,
    DerivationType,
    DistinctCount,
    Filter,
    Grain,
    Kind,
    MatchingRule,
    MatchingRuleKind,
    MaxOrdinal,
    MinOrdinal,
    Operator,
    ValueType,
)
from ra2.domain.ids import CorpusId, FeatureConfigId, FeatureId
from ra2.services.errors import (
    FeatureConfigFrozenError,
    FeatureValidationError,
    NotFoundError,
)
from ra2.services.readmodels import FeatureConfigView, FeatureSetSummary, FeatureView

__all__ = ["router"]

router = APIRouter(prefix="/feature-configs", tags=["feature-configs"])


# ---------------------------------------------------------------------------
# wire schema -> domain
# ---------------------------------------------------------------------------


def _filter_from_schema(schema: DerivationFilterSchema) -> Filter:
    value: str | tuple[str, ...] | None
    if isinstance(schema.value, list):
        value = tuple(schema.value)
    else:
        value = schema.value
    return Filter(column=schema.column, operator=Operator(schema.operator), value=value)


def _derivation_from_schema(schema: DerivationSpecSchema | None) -> DerivationSpec | None:
    """The mirror of `derivation_to_json`'s discriminated shape, one layer up
    the stack: a wire `DerivationSpecSchema` in, one of the seven closed-
    catalogue dataclasses out (mvp-spec.md §8.3). Raises `ValueError` /
    `KeyError` on a malformed envelope — the route turns that into a 422."""
    if schema is None:
        return None
    derivation_type = DerivationType(schema.type)
    if derivation_type is DerivationType.COUNT_OBJECTS:
        return CountObjects(filter=_filter_from_schema(schema.filter) if schema.filter else None)
    if derivation_type is DerivationType.COUNT_PERSONS:
        return CountPersons(filter=_filter_from_schema(schema.filter) if schema.filter else None)
    if derivation_type is DerivationType.ANY_OBJECT_MATCHES:
        if schema.filter is None:
            raise ValueError("any_object_matches requires a filter")
        return AnyObjectMatches(filter=_filter_from_schema(schema.filter))
    if derivation_type is DerivationType.ANY_PERSON_MATCHES:
        if schema.filter is None:
            raise ValueError("any_person_matches requires a filter")
        return AnyPersonMatches(filter=_filter_from_schema(schema.filter))
    if derivation_type is DerivationType.MAX_ORDINAL:
        if schema.table is None or schema.column is None or schema.ordered_codes is None:
            raise ValueError("max_ordinal requires table, column and ordered_codes")
        return MaxOrdinal(
            table=schema.table, column=schema.column, ordered_codes=tuple(schema.ordered_codes)
        )
    if derivation_type is DerivationType.MIN_ORDINAL:
        if schema.table is None or schema.column is None or schema.ordered_codes is None:
            raise ValueError("min_ordinal requires table, column and ordered_codes")
        return MinOrdinal(
            table=schema.table, column=schema.column, ordered_codes=tuple(schema.ordered_codes)
        )
    if derivation_type is DerivationType.DISTINCT_COUNT:
        if schema.table is None or schema.column is None:
            raise ValueError("distinct_count requires table and column")
        return DistinctCount(table=schema.table, column=schema.column)
    raise ValueError(f"Unknown derivation type: {schema.type!r}")  # pragma: no cover - closed enum


def _matching_rule_from_schema(schema: MatchingRuleSchema) -> MatchingRule:
    return MatchingRule(
        kind=MatchingRuleKind(schema.kind),
        tolerance_minutes=schema.tolerance_minutes,
        decimal_precision=schema.decimal_precision,
    )


def _feature_kwargs(body: FeatureRequest) -> dict[str, object]:
    """`FeatureRequest` -> `FeatureService.add_feature`/`edit_feature`
    keyword arguments. A malformed literal (an unknown `kind`, `grain`,
    `value_type`, matching-rule `kind`, or derivation shape) raises a plain
    `ValueError`/`KeyError` here, which becomes a 422 — the frozen request
    schemas declare these fields as bare `str`, so this is the boundary that
    actually enforces membership in the domain enums."""
    try:
        return {
            "key": body.key,
            "kind": Kind(body.kind),
            "description": body.description,
            "grain": Grain(body.grain),
            "source_column": body.source_column,
            "derivation": _derivation_from_schema(body.derivation),
            "value_type": ValueType(body.value_type),
            "matching_rule": _matching_rule_from_schema(body.matching_rule),
        }
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# domain -> wire schema
# ---------------------------------------------------------------------------


def _filter_to_schema(filter_: Filter) -> DerivationFilterSchema:
    value: list[str] | str | None
    if isinstance(filter_.value, tuple):
        value = list(filter_.value)
    else:
        value = filter_.value
    return DerivationFilterSchema(
        column=filter_.column, operator=filter_.operator.value, value=value
    )


def _derivation_to_schema(derivation: DerivationSpec | None) -> DerivationSpecSchema | None:
    if derivation is None:
        return None
    if isinstance(derivation, CountObjects):
        return DerivationSpecSchema(
            type=DerivationType.COUNT_OBJECTS.value,
            filter=_filter_to_schema(derivation.filter) if derivation.filter is not None else None,
        )
    if isinstance(derivation, CountPersons):
        return DerivationSpecSchema(
            type=DerivationType.COUNT_PERSONS.value,
            filter=_filter_to_schema(derivation.filter) if derivation.filter is not None else None,
        )
    if isinstance(derivation, AnyObjectMatches):
        return DerivationSpecSchema(
            type=DerivationType.ANY_OBJECT_MATCHES.value,
            filter=_filter_to_schema(derivation.filter),
        )
    if isinstance(derivation, AnyPersonMatches):
        return DerivationSpecSchema(
            type=DerivationType.ANY_PERSON_MATCHES.value,
            filter=_filter_to_schema(derivation.filter),
        )
    if isinstance(derivation, MaxOrdinal):
        return DerivationSpecSchema(
            type=DerivationType.MAX_ORDINAL.value,
            table=derivation.table,
            column=derivation.column,
            ordered_codes=list(derivation.ordered_codes),
        )
    if isinstance(derivation, MinOrdinal):
        return DerivationSpecSchema(
            type=DerivationType.MIN_ORDINAL.value,
            table=derivation.table,
            column=derivation.column,
            ordered_codes=list(derivation.ordered_codes),
        )
    if isinstance(derivation, DistinctCount):
        return DerivationSpecSchema(
            type=DerivationType.DISTINCT_COUNT.value,
            table=derivation.table,
            column=derivation.column,
        )
    raise TypeError(f"Not a DerivationSpec: {derivation!r}")  # pragma: no cover - closed union


def _matching_rule_to_schema(rule: MatchingRule) -> MatchingRuleSchema:
    return MatchingRuleSchema(
        kind=rule.kind.value,
        tolerance_minutes=rule.tolerance_minutes,
        decimal_precision=rule.decimal_precision,
    )


def _feature_response(view: FeatureView) -> FeatureResponse:
    return FeatureResponse(
        feature_id=view.feature_id,
        feature_config_id=view.feature_config_id,
        ordinal=view.ordinal,
        key=view.key,
        kind=view.kind.value,
        description=view.description,
        grain=view.grain.value,
        source_column=view.source_column,
        derivation=_derivation_to_schema(view.derivation),
        value_type=view.value_type.value,
        matching_rule=_matching_rule_to_schema(view.matching_rule),
        fingerprint=view.fingerprint,
        fingerprint_preview=view.fingerprint_preview,
        validation_errors=list(view.validation_errors),
    )


def _config_response(view: FeatureConfigView) -> FeatureConfigResponse:
    return FeatureConfigResponse(
        feature_config_id=view.feature_config_id,
        name=view.name,
        version=view.version,
        description=view.description,
        created_at=view.created_at,
        frozen_at=view.frozen_at,
        locked_by_evaluations=view.locked_by_evaluations,
        features=[_feature_response(f) for f in view.features],
    )


def _summary_response(view: FeatureSetSummary) -> FeatureConfigSummaryResponse:
    return FeatureConfigSummaryResponse(
        feature_config_id=view.feature_config_id,
        name=view.name,
        version=view.version,
        description=view.description,
        created_at=view.created_at,
        feature_count=view.feature_count,
        frozen_at=view.frozen_at,
        locked_by_evaluations=view.locked_by_evaluations,
    )


# ---------------------------------------------------------------------------
# error builders
# ---------------------------------------------------------------------------


def _not_found(exc: NotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: FeatureConfigFrozenError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _validation_error_response(exc: FeatureValidationError) -> JSONResponse:
    """422, body **is** `FeatureValidationErrorResponse` — nothing was frozen
    (or cloned). Same top-level-fields contract as `corpora.py`'s
    `_blocking_findings_response`: a plain `HTTPException` would nest this
    under `"detail"`, which is not what the schema promises."""
    body = FeatureValidationErrorResponse(validation_errors=list(exc.validation_errors))
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=jsonable_encoder(body)
    )


def _validate_against(value: str | None) -> CorpusId | None:
    return None if value is None else CorpusId(value)


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[FeatureConfigSummaryResponse])
async def list_feature_configs(
    service: FeatureServiceDep,
) -> list[FeatureConfigSummaryResponse]:
    summaries = await service.list_configs()
    return [_summary_response(s) for s in summaries]


@router.post("", response_model=FeatureConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_feature_config(
    body: CreateFeatureConfigRequest, service: FeatureServiceDep
) -> FeatureConfigResponse:
    view = await service.create_draft(name=body.name, description=body.description)
    return _config_response(view)


@router.get("/{feature_config_id}", response_model=FeatureConfigResponse)
async def get_feature_config(
    feature_config_id: str, service: FeatureServiceDep
) -> FeatureConfigResponse:
    try:
        view = await service.get(FeatureConfigId(feature_config_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _config_response(view)


@router.delete(
    "/{feature_config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
)
async def delete_feature_config(feature_config_id: str, service: FeatureServiceDep) -> None:
    """409 when the set is frozen."""
    try:
        await service.delete(FeatureConfigId(feature_config_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except FeatureConfigFrozenError as exc:
        raise _conflict(exc) from exc


@router.post(
    "/{feature_config_id}/features",
    response_model=FeatureConfigResponse,
    responses={409: {"model": ErrorResponse}},
)
async def add_feature(
    feature_config_id: str,
    body: FeatureRequest,
    service: FeatureServiceDep,
    validate_against: str | None = None,
) -> FeatureConfigResponse:
    """Validation problems surface as error rows on the response; only
    `freeze` blocks on them (mvp-spec.md §7/§8.2)."""
    kwargs = _feature_kwargs(body)
    try:
        view = await service.add_feature(
            FeatureConfigId(feature_config_id),
            validate_against=_validate_against(validate_against),
            **kwargs,  # type: ignore[arg-type]
        )
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except FeatureConfigFrozenError as exc:
        raise _conflict(exc) from exc
    return _config_response(view)


@router.put(
    "/{feature_config_id}/features/{feature_id}",
    response_model=FeatureConfigResponse,
    responses={409: {"model": ErrorResponse}},
)
async def edit_feature(
    feature_config_id: str,
    feature_id: str,
    body: FeatureRequest,
    service: FeatureServiceDep,
    validate_against: str | None = None,
) -> FeatureConfigResponse:
    kwargs = _feature_kwargs(body)
    try:
        view = await service.edit_feature(
            FeatureConfigId(feature_config_id),
            FeatureId(feature_id),
            validate_against=_validate_against(validate_against),
            **kwargs,  # type: ignore[arg-type]
        )
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except FeatureConfigFrozenError as exc:
        raise _conflict(exc) from exc
    return _config_response(view)


@router.delete(
    "/{feature_config_id}/features/{feature_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
)
async def delete_feature(
    feature_config_id: str, feature_id: str, service: FeatureServiceDep
) -> None:
    try:
        await service.delete_feature(FeatureConfigId(feature_config_id), FeatureId(feature_id))
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except FeatureConfigFrozenError as exc:
        raise _conflict(exc) from exc


@router.post(
    "/{feature_config_id}/freeze",
    response_model=FeatureConfigResponse,
    responses={
        422: {"model": FeatureValidationErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def freeze_feature_config(
    feature_config_id: str,
    service: FeatureServiceDep,
    validate_against: str | None = None,
) -> FeatureConfigResponse | JSONResponse:
    """422 with every blocking error and creates nothing (mirrors J2's
    corpus-freeze contract). 409 when the set is already frozen."""
    try:
        view = await service.freeze(
            FeatureConfigId(feature_config_id),
            validate_against=_validate_against(validate_against),
        )
    except FeatureValidationError as exc:
        return _validation_error_response(exc)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    except FeatureConfigFrozenError as exc:
        raise _conflict(exc) from exc
    return _config_response(view)


@router.post(
    "/{feature_config_id}/clone",
    response_model=FeatureConfigResponse,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": FeatureValidationErrorResponse}},
)
async def clone_feature_config(
    feature_config_id: str, body: CloneFeatureConfigRequest, service: FeatureServiceDep
) -> FeatureConfigResponse | JSONResponse:
    """A frozen set only — the design's "Clone to new evaluation." 422 (same
    `FeatureValidationErrorResponse` shape as `freeze`) when the source is
    still a draft (`FEATURE_ERROR_CLONE_OF_DRAFT`)."""
    try:
        view = await service.clone(FeatureConfigId(feature_config_id), name=body.name)
    except FeatureValidationError as exc:
        return _validation_error_response(exc)
    except NotFoundError as exc:
        raise _not_found(exc) from exc
    return _config_response(view)

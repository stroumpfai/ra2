# STUB — bodies owned by F2 (feat/p2-api-features). Not frozen.
"""`/api/v1/feature-configs` — list, create draft, add/edit/delete feature,
freeze, clone (mvp-spec.md §8, plan-phase-2.md §9).

Freezing a config with a blocking error returns 422 and creates nothing; a
frozen config's edit endpoints return 409.
"""

from fastapi import APIRouter, HTTPException, status

from ra2.api.deps import FeatureServiceDep
from ra2.api.schemas import (
    CloneFeatureConfigRequest,
    CreateFeatureConfigRequest,
    ErrorResponse,
    FeatureConfigResponse,
    FeatureConfigSummaryResponse,
    FeatureRequest,
    FeatureValidationErrorResponse,
)

__all__ = ["router"]

router = APIRouter(prefix="/feature-configs", tags=["feature-configs"])

_NOT_BUILT = "not implemented until Wave 3 (F2)"


def _todo() -> HTTPException:
    return HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=_NOT_BUILT)


@router.get("", response_model=list[FeatureConfigSummaryResponse])
async def list_feature_configs(
    service: FeatureServiceDep,
) -> list[FeatureConfigSummaryResponse]:
    raise _todo()


@router.post("", response_model=FeatureConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_feature_config(
    body: CreateFeatureConfigRequest, service: FeatureServiceDep
) -> FeatureConfigResponse:
    raise _todo()


@router.get("/{feature_config_id}", response_model=FeatureConfigResponse)
async def get_feature_config(
    feature_config_id: str, service: FeatureServiceDep
) -> FeatureConfigResponse:
    raise _todo()


@router.delete(
    "/{feature_config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
)
async def delete_feature_config(feature_config_id: str, service: FeatureServiceDep) -> None:
    """409 when the set is frozen."""
    raise _todo()


@router.post(
    "/{feature_config_id}/features",
    response_model=FeatureConfigResponse,
    responses={409: {"model": ErrorResponse}},
)
async def add_feature(
    feature_config_id: str, body: FeatureRequest, service: FeatureServiceDep
) -> FeatureConfigResponse:
    """Validation problems surface as error rows on the response; only
    `freeze` blocks on them (mvp-spec.md §7/§8.2)."""
    raise _todo()


@router.put(
    "/{feature_config_id}/features/{feature_id}",
    response_model=FeatureConfigResponse,
    responses={409: {"model": ErrorResponse}},
)
async def edit_feature(
    feature_config_id: str, feature_id: str, body: FeatureRequest, service: FeatureServiceDep
) -> FeatureConfigResponse:
    raise _todo()


@router.delete(
    "/{feature_config_id}/features/{feature_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorResponse}},
)
async def delete_feature(
    feature_config_id: str, feature_id: str, service: FeatureServiceDep
) -> None:
    raise _todo()


@router.post(
    "/{feature_config_id}/freeze",
    response_model=FeatureConfigResponse,
    responses={422: {"model": FeatureValidationErrorResponse}},
)
async def freeze_feature_config(
    feature_config_id: str, service: FeatureServiceDep
) -> FeatureConfigResponse:
    """422 with every blocking error and creates nothing (mirrors J2's
    corpus-freeze contract)."""
    raise _todo()


@router.post(
    "/{feature_config_id}/clone",
    response_model=FeatureConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone_feature_config(
    feature_config_id: str, body: CloneFeatureConfigRequest, service: FeatureServiceDep
) -> FeatureConfigResponse:
    """A frozen set only — the design's "Clone to new evaluation."""
    raise _todo()

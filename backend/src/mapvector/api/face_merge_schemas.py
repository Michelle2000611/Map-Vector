"""Public merge preview contract shared with generated frontend types."""
from typing import Literal

from pydantic import BaseModel, JsonValue

from mapvector.api.schemas import PolygonGeometry, MultiPolygonGeometry

FaceGeometry = PolygonGeometry | MultiPolygonGeometry
FaceMergeMode = Literal['single', 'multipart', 'gap_single']


class FaceMergeReviewEvidence(BaseModel):
    evidence_id: str
    reason_code: str
    feature_ids: list[str]
    gap_candidate_ids: list[str]


class FaceMergeCapabilityResponse(BaseModel):
    eligible: bool
    blocked_reasons: list[str]
    review_required: bool
    review_reason_codes: list[str]
    review_evidence_ids: list[str]
    review_evidence: list[FaceMergeReviewEvidence]
    result_geometry: FaceGeometry | None
    output_geometry_type: Literal['Polygon', 'MultiPolygon'] | None
    output_component_count: int
    hole_count: int
    preserved_hole_geometries: list[PolygonGeometry]
    added_empty_geometry: FaceGeometry | None
    transferred_geometry: FaceGeometry | None


class FaceMergeCapabilities(BaseModel):
    single: FaceMergeCapabilityResponse
    multipart: FaceMergeCapabilityResponse
    gap_single: FaceMergeCapabilityResponse


class FaceMergeOwnershipTransfer(BaseModel):
    feature_id: str
    geometry: FaceGeometry
    remaining_geometry: FaceGeometry | None
    area_px2: float
    blocked_reasons: list[str]
    raster_evidence: dict[str, JsonValue]


class FaceMergeGapCandidateResponse(BaseModel):
    candidate_id: str
    geometry: FaceGeometry
    feature_ids: list[str]
    component_ids: list[str]
    width_px: float
    area_px2: float
    local_length_px: float
    contact_length_px: float
    occupying_feature_ids: list[str]
    owner_feature_ids: list[str]
    ownership_transfers: list[FaceMergeOwnershipTransfer]
    transferred_area_px2: float
    blocked_reasons: list[str]
    review_reason_codes: list[str]
    raster_evidence: dict[str, JsonValue]
    review_required: bool
    risk_level: Literal['blocked', 'review']
    recommended: bool
    metrics: dict[str, float]


class FaceMergeAffectedFeature(BaseModel):
    feature_id: str
    role: Literal['attribute_source', 'merge_source', 'ownership_transfer']
    modes: list[FaceMergeMode]
    before_geometry: FaceGeometry
    after_lifecycle_status: Literal['active', 'superseded'] | None = None
    after_geometry_by_mode: dict[FaceMergeMode, FaceGeometry | None] | None = None
    after_geometry: FaceGeometry | None = None
    transferred_geometry: FaceGeometry | None = None


class FaceMergeParameterSnapshot(BaseModel):
    max_gap_px: float
    max_added_area_px2: float
    scale_source: Literal['explicit', 'local_line_median', 'fallback']
    max_candidates: int
    raster_window_size_px: int
    raster_max_windows: int
    context_feature_limit: int


class FaceMergePreviewResponse(BaseModel):
    preview_id: str
    project_id: str
    asset_id: str
    base_revision: int
    expires_at: str
    algorithm_revision: str
    parameter_snapshot: FaceMergeParameterSnapshot
    input_sha256: str
    result_sha256: str
    feature_ids: list[str]
    attribute_source_feature_id: str
    capabilities: FaceMergeCapabilities
    input_component_count: int
    hole_count_before: int
    gap_candidates: list[FaceMergeGapCandidateResponse]
    selected_gap_candidate_ids: list[str]
    ownership_transfer_feature_ids: list[str]
    affected_features: list[FaceMergeAffectedFeature]
    source_raster_evidence: list[dict[str, JsonValue]]
    boundary_raster_evidence: list[dict[str, JsonValue]]
    truncated: bool

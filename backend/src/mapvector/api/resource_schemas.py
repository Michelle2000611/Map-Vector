"""Resource responses share the Pydantic/OpenAPI source with frontend models."""
from typing import Generic,TypeVar,Literal
from pydantic import BaseModel,ConfigDict,Field
from mapvector.api.schemas import ProjectResponse,FaceResponse,LineResponse,TextResponse,LineGeometry

T=TypeVar('T')
class Envelope(BaseModel,Generic[T]):
    data:T
    request_id:str
    schema_revision:str='1.0'
class Page(BaseModel,Generic[T]):
    items:list[T]
    next_cursor:str|int|None=None
class Resource(BaseModel):
    model_config=ConfigDict(extra='allow')
class Source(Resource):
    source_id:str;project_id:str;source_file_name:str;source_rel_path:str;source_sha256:str;byte_size:int;page_count:int;created_at:str
    source_type:str|None=None
class Asset(Resource):
    asset_id:str;project_id:str;source_id:str;raster_rel_path:str;raster_sha256:str;width_px:int;height_px:int;page_index:int;coordinate_mode:Literal['pixel','georeferenced'];crs_wkt:str|None;pixel_to_map_affine:list[float]|None;normalization_config:dict[str,object];created_at:str
    is_current:bool|None=None
class Run(Resource):
    run_id:str;project_id:str|None=None;asset_id:str;input_raster_sha256:str;pipeline_id:str;run_status:str
    input_region_px:list[float]|None=None
    stage_name:str|None=None;progress_percent:float|None=None;created_at:str|None=None;started_at:str|None=None;finished_at:str|None=None;elapsed_ms:int=0;error_code:str|None=None;error_detail:object|None=None;stdout_rel_path:str|None=None;stderr_rel_path:str|None=None
class JobEvent(Resource):
    run_id:str;event_id:int;event_type:str;stage_name:str|None;event_data:dict[str,object];created_at:str
class Snapshot(Resource):
    snapshot_id:str;asset_id:str|None;working_revision:int;snapshot_status:str;snapshot_sequence:int;snapshot_rel_path:str
class Export(Resource):
    export_id:str;export_status:str;snapshot_id:str
    export_format:str|None=None;stage_name:str|None=None;elapsed_ms:int=0;created_at:str|None=None;started_at:str|None=None;finished_at:str|None=None;error_code:str|None=None;error_detail:object|None=None;readback_report:object|None=None;policy_snapshot:dict[str,object]|None=None
class Candidate(Resource):
    candidate_id:str;project_id:str;asset_id:str;run_id:str|None;text_feature_id:str|None;raw_text:str;suggested_text:str|None;score:float|None;detected_quad_px:list[list[float]]|None;engine_id:str;model_id:str|None;rule_suggestions:list[object];candidate_status:str;created_at:str
class Style(Resource):
    style_id:str;project_id:str;feature_type:Literal['face','line','text'];style_name:str;fill_color:str|None;stroke_color:str|None;stroke_width_px:float|None;line_pattern:str|None;dash_pattern_px:list[float];tooth_spacing_px:float|None;tooth_height_px:float|None;tooth_side:str|None;revision:int
    font_size_px:float|None=None
    text_color:str|None=None
    rotation_deg:float|None=None
class Layer(Resource):
    project_id:str;asset_id:str;layer_type:str;is_visible:bool;opacity:float;default_style_id:str|None
class Roi(Resource):
    roi_id:str;project_id:str;asset_id:str;geometry:dict[str,object];revision:int
    scope_mode:Literal['keep_crossing','clip']='clip'
class RoiResult(BaseModel):
    roi:Roi|None
class ReviewPage(Page[TextResponse]):
    status_counts:dict[str,int];policy_id:str
class TextLayerEvidence(BaseModel):
    feature_id:str
    feature_type:Literal['face','line']
    inside_share:float
    reason:str
    source_ink_share:float|None=None
class TextLayerAssessment(BaseModel):
    manually_confirmed_face_ids:list[str]=Field(default_factory=list)
    manually_confirmed_line_ids:list[str]=Field(default_factory=list)
    kept_face_ids:list[str]=Field(default_factory=list)
    kept_line_ids:list[str]=Field(default_factory=list)
    text_feature_id:str;candidate_id:str|None;text_value:str;ocr_score:float|None
    content_status:str;content_reasons:list[str];cleanup_status:str
    region_source:Literal['ocr_quad','display_bbox','missing'];region_px:list[float]
    suspected_face_ids:list[str];suspected_line_ids:list[str];protected_line_ids:list[str]
    protected_face_ids:list[str]=Field(default_factory=list)
    protected_face_reasons:dict[str,list[dict[str,object]]]=Field(default_factory=dict)
    reasons:list[str];evidence:list[TextLayerEvidence]
class TextLayerAssessmentReport(BaseModel):
    items:list[TextLayerAssessment]
    working_revision:int
    policy_revision:str
    summary:dict[str,int]
    read_only:bool
class SelectionResult(BaseModel):
    feature_ids:list[str];working_revision:int
class ResidueReviewGroup(BaseModel):
    group_id:str
    feature_ids:list[str]
    bounds_px:list[float]
    reason_codes:list[str]
    status:Literal['pending','kept','confirmed']
    can_confirm:bool
    requires_confirmation:bool=False
    evidence_sha256:str
class TextResidueDisplay(BaseModel):
    resolved_face_assignments:dict[str,str]=Field(default_factory=dict)
    unresolved_face_feature_ids:list[str]=Field(default_factory=list)
    manually_confirmed_face_feature_ids:list[str]=Field(default_factory=list)
    manually_confirmed_line_feature_ids:list[str]=Field(default_factory=list)
    protected_face_feature_ids:list[str]=Field(default_factory=list)
    protected_face_reasons:dict[str,list[dict[str,object]]]=Field(default_factory=dict)
    kept_face_feature_ids:list[str]=Field(default_factory=list)
    region_geometry:dict[str,object]|None=None
    region_source:str|None=None
    bounds_px:list[float]
    face_feature_ids:list[str]
    line_feature_ids:list[str]
    protected_line_feature_ids:list[str]
    assessment_only_face_ids:list[str]
    assessment_only_line_ids:list[str]
    preserves_existing_text:bool
    complete_region_available:bool=False
    cleanup_face_feature_ids:list[str]
    cleanup_line_feature_ids:list[str]
    complete_region:bool=False
    verification_pending_feature_ids:list[str]=[]
    verification_summary:dict[str,int]={}
    review_groups:list[ResidueReviewGroup]=Field(default_factory=list)
class ResidueCleanupPreview(BaseModel):
    features:list[FaceResponse|LineResponse|TextResponse]
    styles:list[Style]
    has_changes:bool
class Preview(Resource):
    cleanup_preview:ResidueCleanupPreview|None=None
    text_residue_display:TextResidueDisplay|None=None
    preview_id:str;base_revision:int;input_sha256:str;expires_at:str;preview_type:str;feature_ids:list[str];affected_feature_ids:list[str];legacy_report:dict[str,object];warnings:list[object]
class Operation(Resource):
    operation_id:str;result_revision:int;operation_type:str;operation_status:str;can_undo:bool;can_redo:bool;result_summary:dict[str,object]


class DeliveryIssue(BaseModel):
    issue_id:str
    code:Literal['INVALID_GEOMETRY','FACE_OVERLAP','FACE_BOUNDARY_MISMATCH']
    severity:Literal['error','review']
    feature_ids:list[str]
    bounds_px:tuple[float,float,float,float]|None
    message:str
    area_px2:float|None=None

class GeometryQualityReport(BaseModel):
    target:Literal['full_asset_pixel_extent']
    target_area_px2:float
    face_count:int
    geometry_count:int
    valid_geometry_count:int
    invalid_geometry_count:int
    coverage_is_valid:bool|None
    covered_area_px2:float
    uncovered_area_px2:float
    overlap_area_px2:float
    recognition_accuracy:float|None=None
    tolerance_px2:float
    area_statistics_complete:bool
    note:str

class DeliveryCheckResult(BaseModel):
    asset_id:str
    coordinate_space:Literal['pixel']='pixel'
    working_revision:int
    rule_version:Literal['delivery_checks_v1']='delivery_checks_v1'
    quality_report:GeometryQualityReport
    issues:list[DeliveryIssue]
    issue_count:int
    check_complete:bool=True
    issue_count_exact:bool=True
    checked_pair_count:int=0
    issues_truncated:bool

class RoiAuditCounts(BaseModel):
    inside:int
    crossing:int
    outside:int

class RoiAuditResult(BaseModel):
    asset_id:str
    coordinate_space:Literal['pixel']='pixel'
    working_revision:int
    rule_version:Literal['delivery_scope_v1']='delivery_scope_v1'
    roi_revision:int
    roi:Roi
    counts:dict[Literal['face','line','text'],RoiAuditCounts]

class MultiLineGeometry(BaseModel):
    type:Literal['MultiLineString']
    coordinates:list[list[tuple[float,float]]]

class PreviewLineResponse(LineResponse):
    geometry:LineGeometry|MultiLineGeometry

class RoiPreviewResult(BaseModel):
    asset_id:str
    coordinate_space:Literal['pixel']='pixel'
    working_revision:int
    rule_version:Literal['delivery_scope_v1']='delivery_scope_v1'
    roi_id:str
    roi_revision:int
    keep_crossing:list[FaceResponse|PreviewLineResponse|TextResponse]
    clip:list[FaceResponse|PreviewLineResponse|TextResponse]

class SnapshotScope(BaseModel):
    snapshot_id:str
    asset_id:str|None
    working_revision:int
    coordinate_space:Literal['pixel']='pixel'
    roi:Roi|None

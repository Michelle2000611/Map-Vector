"""Resource responses share the Pydantic/OpenAPI source with frontend models."""
from typing import Generic,TypeVar,Literal
from pydantic import BaseModel,ConfigDict,Field
from mapvector.api.schemas import ProjectResponse,FaceResponse,LineResponse,TextResponse

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
    style_id:str;project_id:str;feature_type:Literal['face','line'];style_name:str;fill_color:str|None;stroke_color:str|None;stroke_width_px:float|None;line_pattern:str|None;dash_pattern_px:list[float];tooth_spacing_px:float|None;tooth_height_px:float|None;tooth_side:str|None;revision:int
class Layer(Resource):
    project_id:str;asset_id:str;layer_type:str;is_visible:bool;opacity:float;default_style_id:str|None
class Roi(Resource):
    roi_id:str;project_id:str;asset_id:str;geometry:dict[str,object];revision:int
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
    text_feature_id:str;candidate_id:str|None;text_value:str;ocr_score:float|None
    content_status:str;content_reasons:list[str];cleanup_status:str
    region_source:Literal['ocr_quad','display_bbox','missing'];region_px:list[float]
    suspected_face_ids:list[str];suspected_line_ids:list[str];protected_line_ids:list[str]
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
    status:Literal['pending','kept']
    can_confirm:bool
    evidence_sha256:str
class TextResidueDisplay(BaseModel):
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
class Preview(Resource):
    text_residue_display:TextResidueDisplay|None=None
    preview_id:str;base_revision:int;input_sha256:str;expires_at:str;preview_type:str;feature_ids:list[str];affected_feature_ids:list[str];legacy_report:dict[str,object];warnings:list[object]
class Operation(Resource):
    operation_id:str;result_revision:int;operation_type:str;operation_status:str;can_undo:bool;can_redo:bool;result_summary:dict[str,object]

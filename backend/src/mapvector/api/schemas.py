from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from typing import Literal


class CreateProject(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    project_name: str = Field(min_length=1, max_length=120)


class ProjectResponse(BaseModel):
    project_id: str
    project_name: str
    working_revision: int
    created_at: str
    updated_at: str
    current_asset_id: str | None = None
    current_snapshot_id: str | None = None
    schema_revision:str='1.0'
    export_policy_id:str='baseline_compatible'
    workflow_stage: int = 0


class WorkflowStage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    stage: int = Field(ge=0, le=5, strict=True)


class ProjectEnvelope(BaseModel):
    data: ProjectResponse
    request_id: str
    schema_revision: str = '1.0'


class NormalizationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    dpi: float = Field(default=200, ge=36, le=600)


class CreateAsset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: UUID
    page_index: int = Field(default=0, ge=0, strict=True)
    normalization_config: NormalizationConfig = Field(default_factory=NormalizationConfig)


class CreateSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_revision: int = Field(ge=0, le=9007199254740990, strict=True)
    snapshot_note: str | None = Field(default=None, max_length=2000)


class RestoreSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_revision: int = Field(ge=0, le=9007199254740990, strict=True)


class CreateExport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot_id: UUID
    export_format: Literal['gpkg','shp','geojson','pixel_json']
    export_mode: Literal['draft','formal']
    layer_types: list[Literal['face','line','text_confirmed','text_unconfirmed','isolated_line']] = Field(min_length=1)
    scope_mode: Literal['full','keep_crossing','clip']
    roi_id: UUID | None
    policy_id: Literal['baseline_compatible','strict_review']


class RoiAudit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    asset_id:UUID
    roi_id:UUID|None=None


class Geometry(BaseModel):
    type:Literal['Point','LineString','Polygon','MultiPolygon','MultiLineString']
    coordinates:list

class PointGeometry(BaseModel):
    type:Literal['Point']
    coordinates:tuple[float,float]
class LineGeometry(BaseModel):
    type:Literal['LineString']
    coordinates:list[tuple[float,float]]
class PolygonGeometry(BaseModel):
    type:Literal['Polygon']
    coordinates:list[list[tuple[float,float]]]
class MultiPolygonGeometry(BaseModel):
    type:Literal['MultiPolygon']
    coordinates:list[list[list[tuple[float,float]]]]


class FeatureResponse(BaseModel):
    model_config=ConfigDict(extra='allow')
    feature_id:UUID
    project_id:UUID
    asset_id:UUID
    feature_type:Literal['face','line','text']
    lifecycle_status:Literal['active','isolated','deleted','superseded']
    geometry:Geometry
    revision:int
    origin_run_id:UUID|None
    source_type:Literal['algorithm','manual','legacy_import','unknown']
    geometry_type:Literal['Point','LineString','Polygon','MultiPolygon','MultiLineString']
    style_id:UUID|None
    bbox_min_x_px:float
    bbox_min_y_px:float
    bbox_max_x_px:float
    bbox_max_y_px:float
    created_at:str|None
    updated_at:str
    coordinate_space:Literal['pixel']='pixel'


class FaceResponse(FeatureResponse):
    feature_type:Literal['face']
    geometry:PolygonGeometry|MultiPolygonGeometry
    fill_color:str
    algorithm_label:str|None
    color_class_id:str|None
    area_px2:float
    observed_area_px2:float|None
    inferred_area_px2:float|None
    coverage_status:str


class LineResponse(FeatureResponse):
    feature_type:Literal['line']
    geometry:LineGeometry
    stroke_color:str
    stroke_width_px:float
    line_pattern:str
    line_role:str
    length_px:float
    draw_order:int
    isolation_reason:str|None
    associated_text_feature_id:UUID|None


class TextLayoutRun(BaseModel):
    text:str
    script:Literal['normal','subscript','superscript']
    font_size_px:float
    x_offset_px:float
    baseline_offset_px:float
    width_px:float
    source_index:int=0
    basis:str='source_ink'
    review_required:bool=False


class TextResponse(FeatureResponse):
    ocr_score:float|None=None
    ocr_engine_id:str|None=None
    feature_type:Literal['text']
    geometry:PointGeometry
    text_value:str
    original_text:str|None
    font_size_px:float
    rotation_deg:float
    text_color:str
    text_anchor:str
    text_content_revision:int
    review_status:str
    review_reason_codes:list[str]
    reviewed_content_revision:int|None
    reviewed_at:str|None
    reviewer_id:str|None
    cleanup_status:str
    display_bbox_px:list[float]|None
    primary_candidate_id:UUID|None
    font_family:str
    layout_width_px:float|None=None
    layout_height_px:float|None=None
    baseline_offset_px:float|None=None
    layout_basis:str='legacy_estimate'
    layout_runs:list[TextLayoutRun]=Field(default_factory=list)
    review_basis:str


class FeaturePage(BaseModel):
    items:list[FaceResponse|LineResponse|TextResponse]
    next_cursor:str|None
    working_revision:int
    coordinate_space:Literal['pixel']='pixel'
    asset_id:UUID


class FeatureEnvelope(BaseModel):
    data:FeaturePage
    request_id:str
    schema_revision:str='1.0'


class EditResult(BaseModel):
    model_config=ConfigDict(extra='allow')
    operation_id:UUID
    result_revision:int
    upserted_features:list[FaceResponse|LineResponse|TextResponse]
    current_asset_id:UUID|None=None
    roi_changed:bool=False
    removed_feature_ids:list[UUID]
    changed_groups:list[dict[str,object]]=Field(default_factory=list)
    changed_styles:list[dict[str,object]]=Field(default_factory=list)
    changed_layers:list[dict[str,object]]=Field(default_factory=list)
    roi:dict[str,object]|None=None
    review_summary:dict[str,object]=Field(default_factory=dict)
    warnings:list=Field(default_factory=list)


class EditEnvelope(BaseModel):
    data:EditResult
    request_id:str
    schema_revision:str='1.0'


class ErrorResponse(BaseModel):
    code:str
    message:str
    detail:dict
    recoverable:bool
    request_id:str

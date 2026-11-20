"""Text assessment resources shared by read reports and edit deltas."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel,Field


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
    region_source:Literal['ocr_quad','display_bbox','missing','source_uncertain'];region_px:list[float]
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
class ResidueUpdate(BaseModel):
    asset_id:UUID
    base_revision:int
    result_revision:int
    text_feature_ids:list[UUID]
    assessment:TextLayerAssessmentReport

from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from mapvector.domain.commands import UUIDString


class SelectionRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:str
    selection_type:Literal['pick','box','group','same_color','gesture','grow','shrink','text_pick']
    feature_type:Literal['face','line','text']='face'
    lifecycle_status:Literal['active','isolated']='active'
    feature_ids:list[str]=Field(default_factory=list)
    x:float=0
    y:float=0
    bounds_px:tuple[float,float,float,float]|None=None
    points:list[tuple[float,float]]=Field(default_factory=list)
    gesture_kind:Literal['brush','lasso','box']='lasso'
    radius_px:float=Field(default=4,ge=0)
    rule:Literal['touch','center','cover50']='touch'
    max_area_px2:float|None=Field(default=None,gt=0)
    color_distance:float=Field(default=15,ge=0)
    steps:int=Field(default=1,ge=1,le=100)
    selection_mode:Literal['replace','add','subtract']='replace'


class PreviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:str
    base_revision:int=Field(ge=0,le=9007199254740990,strict=True)
    preview_type:Literal['merge_faces','join_lines','heal_faces','split_faces','text_residue','merge_suggest','line_to_face']
    feature_ids:list[str]=Field(default_factory=list)
    complete_region:bool=False
    verified_line_feature_ids:list[UUIDString]=Field(default_factory=list)
    line_review_preview_id:UUIDString|None=None
    points:list[tuple[float,float]]=Field(default_factory=list)
    radius_px:float=Field(default=4,ge=0)
    max_area_px2:float=Field(default=12,gt=0)
    bounds_px:tuple[float,float,float,float]|None=None
    stroke_width_px:float|None=Field(default=None,ge=.25,le=50)
    fill_color:str|None=Field(default=None,pattern='^#[0-9a-fA-F]{6}$')

    @model_validator(mode='after')
    def validate_line_review(self):
        if len(self.verified_line_feature_ids)!=len(set(self.verified_line_feature_ids)):raise ValueError('Verified lines must be unique')
        if self.verified_line_feature_ids and (self.preview_type!='text_residue' or not self.complete_region or self.line_review_preview_id is None):raise ValueError('Verified lines require a complete text residue preview and source review')
        if self.line_review_preview_id and self.preview_type!='text_residue':raise ValueError('Line review is only supported for text residue')
        return self

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field,AfterValidator,model_validator
from uuid import UUID


def canonical_uuid(value:str):return str(UUID(value))
UUIDString=Annotated[str,AfterValidator(canonical_uuid)]


class CommandBase(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)
    asset_id: UUIDString
    base_revision: int = Field(ge=0,le=9007199254740990,strict=True)
    idempotency_key: str = Field(min_length=1, max_length=128)
    feature_ids: list[UUIDString] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_identities(self):
        self.asset_id=canonical_uuid(self.asset_id)
        self.feature_ids=[canonical_uuid(value) for value in self.feature_ids]
        if len(self.feature_ids)!=len(set(self.feature_ids)):raise ValueError('Feature identities must be unique')
        for name in ('target_operation_id','preview_id','candidate_id','style_id'):
            value=getattr(self,name,None)
            if value is not None:setattr(self,name,canonical_uuid(value))
        return self


class CreateText(CommandBase):
    operation_type: Literal['create_text']
    x: float
    y: float
    text_value: str = Field(min_length=1, max_length=200)
    font_size_px: float = Field(ge=1, le=200)
    rotation_deg: float = 0
    text_color: str = Field(default='#000000',pattern='^#[0-9a-fA-F]{6}$')


class UpdateText(CommandBase):
    operation_type: Literal['update_text']
    feature_ids: list[str] = Field(min_length=1, max_length=1)
    text_value: str | None = Field(default=None, min_length=1, max_length=200)
    x: float | None = None
    y: float | None = None
    font_size_px: float | None = Field(default=None, ge=1, le=200)
    rotation_deg: float | None = None
    text_color: str | None = Field(default=None,pattern='^#[0-9a-fA-F]{6}$')

    @model_validator(mode='after')
    def reject_null_patch(self):
        fields={'text_value','font_size_px','rotation_deg','text_color','x','y'}
        if any(getattr(self,name) is None for name in self.model_fields_set&fields):raise ValueError('Explicit null is not a text modification')
        if not self.model_fields_set&fields:raise ValueError('Text modification requires at least one changed property')
        return self


class ReviewText(CommandBase):
    operation_type: Literal['confirm_text', 'skip_text']
    feature_ids: list[str] = Field(min_length=1)


class HistoryCommand(CommandBase):
    operation_type: Literal['undo', 'redo']
    target_operation_id: str


class MergeFaces(CommandBase):
    operation_type:Literal['merge_adjacent_faces','merge_face_components']
    feature_ids:list[str]=Field(min_length=2)
    allow_mixed_algorithm_labels:bool=False
    preview_id:str|None=None


class CreateLine(CommandBase):
    operation_type:Literal['create_line']
    coordinates:list[tuple[float,float]]=Field(min_length=2)
    stroke_width_px:float=Field(default=2,ge=.25,le=50)
    stroke_color:str=Field(default='#000000',pattern='^#[0-9a-fA-F]{6}$')
    snap_px:float=Field(default=3,ge=0,le=100)


class SplitLine(CommandBase):
    operation_type:Literal['split_line']
    feature_ids:list[str]=Field(min_length=1,max_length=1)
    x:float
    y:float


class JoinLines(CommandBase):
    operation_type:Literal['join_lines']
    feature_ids:list[str]=Field(min_length=2)
    max_gap_px:float=Field(default=30,ge=0,le=1000)
    preview_id:str|None=None


class FeatureColor(CommandBase):
    operation_type:Literal['set_feature_color']
    feature_ids:list[str]=Field(min_length=1)
    feature_type:Literal['face','line']
    color:str=Field(pattern='^#[0-9a-fA-F]{6}$')


class SetFeatureProperties(CommandBase):
    operation_type:Literal['set_feature_properties']
    feature_ids:list[str]=Field(min_length=1)
    feature_type:Literal['face','line']
    color:str|None=Field(default=None,pattern='^#[0-9a-fA-F]{6}$')
    stroke_width_px:float|None=Field(default=None,ge=.25,le=50)
    line_role:Literal['unknown','cover','split']|None=None

    @model_validator(mode='after')
    def validate_patch(self):
        fields=self.model_fields_set&{'color','stroke_width_px','line_role'}
        if not fields or any(getattr(self,name) is None for name in fields):
            raise ValueError('Feature modification requires at least one non-null property')
        if self.feature_type=='face' and fields-{'color'}:
            raise ValueError('Face modification only accepts color')
        return self


class DeleteFaces(CommandBase):
    operation_type:Literal['delete_faces']
    feature_ids:list[str]=Field(min_length=1)


class LineWidth(CommandBase):
    operation_type:Literal['set_line_width']
    feature_ids:list[str]=Field(min_length=1)
    stroke_width_px:float=Field(ge=.25,le=50)


class LineRole(CommandBase):
    operation_type:Literal['set_line_role']
    feature_ids:list[str]=Field(min_length=1)
    line_role:Literal['unknown','cover','split']


class DeleteLines(CommandBase):
    operation_type:Literal['delete_lines']
    feature_ids:list[str]=Field(min_length=1)


class IsolateLines(CommandBase):
    operation_type:Literal['isolate_lines']
    feature_ids:list[str]=Field(min_length=1)
    isolation_reason:Literal['manual','misgrouped','text_residue']='manual'


class SetRoi(CommandBase):
    operation_type:Literal['set_roi']
    bounds_px:tuple[float,float,float,float] | None


class GroupFeatures(CommandBase):
    operation_type:Literal['group_features']
    feature_ids:list[str]=Field(min_length=1)
    group_name:str | None=Field(default=None,max_length=200)


class UngroupFeatures(CommandBase):
    operation_type:Literal['ungroup_features']
    feature_ids:list[str]=Field(min_length=1)


class AdoptOcrCandidate(CommandBase):
    operation_type:Literal['adopt_ocr_candidate']
    candidate_id:str
    text_value:str|None=None
    candidate_mode:Literal['create','update']='create'


class ApplyPreview(CommandBase):
    operation_type:Literal['heal_faces','split_faces','cleanup_text_residue']
    preview_id:str
    complete_region:bool=False
    verified_line_feature_ids:list[UUIDString]=Field(default_factory=list)
    feature_ids:list[str]=Field(default_factory=list)
    accept_uncertain_feature_ids:list[str]=Field(default_factory=list)
    allow_mixed_algorithm_labels:bool=False
    text_value:str|None=Field(default=None,min_length=1,max_length=200)
    font_size_px:float|None=Field(default=None,ge=1,le=200)
    rotation_deg:float=0
    text_color:str=Field(default='#000000',pattern='^#[0-9a-fA-F]{6}$')
    line_feature_ids:list[str]|None=None
    face_assignments:dict[str,UUIDString]=Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_verified_lines(self):
        if len(self.verified_line_feature_ids)!=len(set(self.verified_line_feature_ids)):raise ValueError('Verified lines must be unique')
        if self.verified_line_feature_ids and (self.operation_type!='cleanup_text_residue' or not self.complete_region):raise ValueError('Verified lines require complete text residue cleanup')
        return self


class LineToFace(CommandBase):
    operation_type:Literal['line_to_face']
    feature_ids:list[str]=Field(min_length=1)
    preview_id:str|None=None
    stroke_width_px:float|None=Field(default=None,ge=.25,le=50)
    fill_color:str|None=Field(default=None,pattern='^#[0-9a-fA-F]{6}$')


class RestoreLines(CommandBase):
    operation_type:Literal['restore_lines']
    feature_ids:list[str]=Field(min_length=1)


class DeleteText(CommandBase):
    operation_type:Literal['delete_text']
    feature_ids:list[str]=Field(min_length=1)


class SetStyle(CommandBase):
    operation_type:Literal['set_style']
    style_id:str|None=None
    feature_type:Literal['face','line']
    style_name:str=Field(min_length=1,max_length=200)
    fill_color:str|None=Field(default=None,pattern='^#[0-9a-fA-F]{6}$')
    stroke_color:str|None=Field(default=None,pattern='^#[0-9a-fA-F]{6}$')
    stroke_width_px:float|None=Field(default=None,ge=.25,le=50)
    line_pattern:Literal['solid','dashed','teeth']|None=None
    dash_pattern_px:list[float]=Field(default_factory=list)
    tooth_spacing_px:float|None=Field(default=None,ge=2,le=200)
    tooth_height_px:float|None=Field(default=None,ge=.5,le=50)
    tooth_side:Literal['left','right']|None=None


class BindStyle(CommandBase):
    operation_type:Literal['bind_style']
    style_id:str
    feature_ids:list[str]=Field(min_length=1)


class SetLayer(CommandBase):
    operation_type:Literal['set_layer']
    layer_type:Literal['face','line','text','isolated_line']
    is_visible:bool=True
    opacity:float=Field(default=1,ge=0,le=1)
    default_style_id:str|None=None


class RestoreOcrLayout(CommandBase):
    operation_type:Literal['restore_ocr_layout']
    all_assets:bool=False


class ClassifyReview(CommandBase):
    operation_type:Literal['classify_review']
    threshold:float=Field(default=.90,gt=0,le=1)
    candidate_only:bool=False


class RepairFace(CommandBase):
    operation_type:Literal['repair_face_geometry']
    feature_ids:list[UUIDString]=Field(min_length=1,max_length=1)
    preview_id:UUIDString
    # Exact stored preview membership bounds selections, including select-all.
    candidate_ids:list[str]=Field(min_length=1)
    assignments:dict[str,UUIDString]=Field(default_factory=dict)
    verified_protected_candidate_ids:list[str]=Field(default_factory=list)
    verified_review_candidate_ids:list[str]=Field(default_factory=list)
    merge_occupied_candidate_ids:list[str]=Field(default_factory=list)

    @model_validator(mode='after')
    def unique_candidates(self):
        if len(self.candidate_ids)!=len(set(self.candidate_ids)):raise ValueError('Repair candidates must be unique')
        if len(self.verified_protected_candidate_ids)!=len(set(self.verified_protected_candidate_ids)):raise ValueError('Protected candidate confirmations must be unique')
        if len(self.verified_review_candidate_ids)!=len(set(self.verified_review_candidate_ids)):raise ValueError('Review candidate confirmations must be unique')
        if not set(self.verified_review_candidate_ids).issubset(self.candidate_ids):raise ValueError('Review candidate confirmations must be selected')
        if len(self.merge_occupied_candidate_ids)!=len(set(self.merge_occupied_candidate_ids)):raise ValueError('Occupied hole confirmations must be unique')
        if not set(self.merge_occupied_candidate_ids).issubset(self.candidate_ids):raise ValueError('Occupied hole confirmations must be selected')
        return self


class ApplyLineCheck(CommandBase):
    operation_type:Literal['apply_line_check']
    feature_ids:list[UUIDString]=Field(default_factory=list,max_length=0)
    preview_id:UUIDString
    candidate_ids:list[str]=Field(min_length=1,max_length=2000)
    action:Literal['join','isolate','group']
    verified_candidate_ids:list[str]=Field(default_factory=list,max_length=2000)

    @model_validator(mode='after')
    def unique_candidates(self):
        if len(self.candidate_ids)!=len(set(self.candidate_ids)):raise ValueError('Line check candidates must be unique')
        if len(self.verified_candidate_ids)!=len(set(self.verified_candidate_ids)):raise ValueError('Line check confirmations must be unique')
        return self


GeometryCommand = MergeFaces | CreateLine | SplitLine | JoinLines | FeatureColor | SetFeatureProperties | DeleteFaces | LineWidth | LineRole | DeleteLines | IsolateLines | ApplyPreview | LineToFace | RestoreLines | DeleteText | RepairFace | ApplyLineCheck
EditCommand = Annotated[CreateText | UpdateText | ReviewText | HistoryCommand | GeometryCommand | SetRoi | GroupFeatures | UngroupFeatures | AdoptOcrCandidate | SetStyle | BindStyle | SetLayer | ClassifyReview | RestoreOcrLayout, Field(discriminator='operation_type')]

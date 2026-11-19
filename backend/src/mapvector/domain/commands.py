from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field,AfterValidator,model_validator
from uuid import UUID
import unicodedata


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


def text_format_glyph(char):
    """Decode Unicode script notation without normalizing unrelated typography."""
    name=unicodedata.name(char,'')
    script='subscript' if 'SUBSCRIPT' in name else 'superscript' if 'SUPERSCRIPT' in name or name.startswith(('MODIFIER LETTER SMALL','MODIFIER LETTER CAPITAL')) else 'normal'
    return (unicodedata.normalize('NFKC',char) if script!='normal' else char),script


class TextFormatRun(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,frozen=True)
    text:str=Field(min_length=1,max_length=200)
    script:Literal['normal','subscript','superscript']
    font_size_px:float=Field(gt=0,le=40000,strict=True)
    x_offset_px:float=Field(ge=-1000000,le=1000000,strict=True)
    baseline_offset_px:float=Field(ge=-1000000,le=1000000,strict=True)
    width_px:float=Field(ge=0,le=1000000,strict=True)
    ink_bbox_px:tuple[float,float,float,float]|None=None
    quality_reasons:tuple[Annotated[str,Field(min_length=1,max_length=100)],...]=Field(default_factory=tuple,max_length=30)

    @model_validator(mode='after')
    def validate_ink_bounds(self):
        if self.ink_bbox_px is not None:
            left,top,right,bottom=self.ink_bbox_px
            if any(abs(value)>1000000 for value in self.ink_bbox_px) or left>=right or top>=bottom:
                raise ValueError('Run ink bounds must be a finite, nonempty rectangle')
        return self


class TextFormatSample(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False,frozen=True)
    font_size_px:float=Field(ge=1,le=200,strict=True)
    text_color:str=Field(pattern='^#[0-9a-fA-F]{6}$')
    rotation_deg:float=Field(strict=True)
    text_value:str=Field(min_length=1,max_length=200)
    layout_runs:tuple[TextFormatRun,...]=Field(default_factory=tuple,max_length=200)
    layout_width_px:float|None=Field(default=None,gt=0,le=1000000,strict=True)
    layout_height_px:float|None=Field(default=None,gt=0,le=1000000,strict=True)
    baseline_offset_px:float|None=Field(default=None,ge=-1000000,le=1000000,strict=True)
    layout_basis:str|None=Field(default=None,max_length=100)

    @model_validator(mode='after')
    def validate_layout_text(self):
        if not self.text_value.strip():raise ValueError('Text snapshot requires nonempty text')
        if self.layout_runs:
            source=''.join(text_format_glyph(ch)[0] for ch in self.text_value)
            runs=''.join(text_format_glyph(ch)[0] for run in self.layout_runs for ch in run.text)
            # OCR ink and vertical layouts both omit whitespace glyph boxes.
            if (self.layout_basis or '').startswith('ocr_'):
                source=''.join(source.split());runs=''.join(runs.split())
            if source!=runs:raise ValueError('Layout run text must match snapshot text')
        return self


class ApplyTextFormat(CommandBase):
    operation_type:Literal['apply_text_format']
    feature_ids:list[UUIDString]=Field(min_length=1,max_length=2000)
    sample:TextFormatSample
    copy_size:bool=True
    copy_color:bool=True
    copy_rotation:bool=False
    copy_text:bool=False


class ReviewText(CommandBase):
    operation_type: Literal['confirm_text']
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
    scope_mode:Literal['keep_crossing','clip']='clip'


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
    feature_type:Literal['face','line','text']
    style_name:str=Field(min_length=1,max_length=200)
    fill_color:str|None=Field(default=None,pattern='^#[0-9a-fA-F]{6}$')
    stroke_color:str|None=Field(default=None,pattern='^#[0-9a-fA-F]{6}$')
    stroke_width_px:float|None=Field(default=None,ge=.25,le=50)
    line_pattern:Literal['solid','dashed','teeth']|None=None
    dash_pattern_px:list[float]=Field(default_factory=list)
    tooth_spacing_px:float|None=Field(default=None,ge=2,le=200)
    tooth_height_px:float|None=Field(default=None,ge=.5,le=50)
    tooth_side:Literal['left','right']|None=None
    font_size_px:float|None=Field(default=None,ge=1,le=200)
    text_color:str|None=Field(default=None,pattern='^#[0-9a-fA-F]{6}$')
    rotation_deg:float|None=None

    @model_validator(mode='after')
    def validate_text_style(self):
        text_fields={'font_size_px','text_color','rotation_deg'}
        if self.feature_type=='text':
            if not any(getattr(self,name) is not None for name in text_fields):raise ValueError('Text styles require at least one format property')
            if self.model_fields_set&{'fill_color','stroke_color','stroke_width_px','line_pattern','dash_pattern_px','tooth_spacing_px','tooth_height_px','tooth_side'}:raise ValueError('Text styles only accept text format properties')
        elif any(getattr(self,name) is not None for name in text_fields):raise ValueError('Text format properties require a text style')
        return self


class BindStyle(CommandBase):
    operation_type:Literal['bind_style']
    style_id:str
    feature_ids:list[str]=Field(min_length=1)
    text_fields:list[Literal['font_size_px','text_color','rotation_deg']]|None=None
    text_content:TextFormatSample|None=None


class DeleteStyle(CommandBase):
    operation_type:Literal['delete_style']
    style_id:str


class RebindStyle(CommandBase):
    operation_type:Literal['rebind_style']
    from_style_id:str
    to_style_id:str
    feature_type:Literal['face','line','text']


class ClearStyleOverride(CommandBase):
    operation_type:Literal['clear_style_override']
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
    expected_preview_sha256:str|None=Field(default=None,pattern='^[0-9a-f]{64}$')


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


class ApplyFaceMerge(CommandBase):
    operation_type:Literal['apply_face_merge']
    feature_ids:list[UUIDString]=Field(min_length=2,max_length=1000)
    preview_id:UUIDString
    mode:Literal['single','multipart','gap_single']
    verified_review_evidence_ids:list[str]=Field(default_factory=list,max_length=4000)
    confirmed_gap_candidate_ids:list[str]=Field(default_factory=list,max_length=2000)
    confirmed_ownership_transfer_feature_ids:list[UUIDString]=Field(default_factory=list,max_length=1000)

    @model_validator(mode='after')
    def unique_confirmations(self):
        for name in ('verified_review_evidence_ids','confirmed_gap_candidate_ids','confirmed_ownership_transfer_feature_ids'):
            values=getattr(self,name)
            if len(values)!=len(set(values)):raise ValueError('Face merge confirmations must be unique')
        if self.mode!='gap_single' and (self.confirmed_gap_candidate_ids or self.confirmed_ownership_transfer_feature_ids):
            raise ValueError('Only gap merging accepts gap or ownership confirmations')
        return self


class SplitSelectedFaces(CommandBase):
    operation_type:Literal['split_selected_faces']
    feature_ids:list[UUIDString]=Field(min_length=1,max_length=1000)
    preview_id:UUIDString
    confirmed_small_piece_ids:list[str]=Field(default_factory=list)

    @model_validator(mode='after')
    def unique_small_parts(self):
        if len(self.confirmed_small_piece_ids)!=len(set(self.confirmed_small_piece_ids)):raise ValueError('Small split pieces must be unique')
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


GeometryCommand = MergeFaces | CreateLine | SplitLine | JoinLines | FeatureColor | SetFeatureProperties | DeleteFaces | LineWidth | LineRole | DeleteLines | IsolateLines | ApplyPreview | LineToFace | RestoreLines | DeleteText | RepairFace | ApplyLineCheck | SplitSelectedFaces | ApplyFaceMerge
EditCommand = Annotated[CreateText | UpdateText | ApplyTextFormat | ReviewText | HistoryCommand | GeometryCommand | SetRoi | GroupFeatures | UngroupFeatures | AdoptOcrCandidate | SetStyle | BindStyle | SetLayer | ClassifyReview | RestoreOcrLayout | DeleteStyle | RebindStyle | ClearStyleOverride, Field(discriminator='operation_type')]

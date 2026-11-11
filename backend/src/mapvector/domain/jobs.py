from typing import Literal

from pydantic import BaseModel,ConfigDict,Field
from uuid import UUID


class StartRun(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    pipeline_id:Literal['legacy_b2c','legacy_b2c_rapid','ocr_rapid','legacy_b2c_paddle','ocr_paddle','ocr_combined','legacy_b2c_combined']
    pipeline_revision:str=Field(default='1.0',min_length=1,max_length=80)
    config_snapshot:dict=Field(default_factory=dict)
    input_region_px:tuple[float,float,float,float]|None=None
    retry_of_run_id:UUID|None=None


class AdoptRun(BaseModel):
    model_config=ConfigDict(extra='forbid')
    base_revision:int=Field(ge=0,le=9007199254740990,strict=True)
    adoption_mode:Literal['keep_current','replace','new_project']='keep_current'
    idempotency_key:str|None=Field(default=None,min_length=1,max_length=128)


class ReviewDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation_type:Literal['confirm_text','skip_text']
    asset_id:str
    base_revision:int=Field(ge=0,strict=True)
    idempotency_key:str=Field(min_length=1,max_length=128)
    feature_ids:list[str]=Field(min_length=1)

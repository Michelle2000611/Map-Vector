from dataclasses import dataclass


@dataclass(frozen=True)
class Project:
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

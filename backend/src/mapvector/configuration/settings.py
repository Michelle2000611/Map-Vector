import os
from dataclasses import dataclass,field
from pathlib import Path,PureWindowsPath


@dataclass(frozen=True)
class Settings:
    project_root:Path=field(default_factory=lambda:Path(os.environ.get('PROJECT_ROOT',Path(__file__).resolve().parents[4])))
    allowed_origins:tuple[str,...]=('http://127.0.0.1:8840','http://localhost:8840','http://127.0.0.1:5175','http://localhost:5175')
    workspace_override:Path|None=None
    api_port:int=field(default_factory=lambda:int(os.environ.get('MAPVECTOR_API_PORT','8840')))

    def __post_init__(self):
        object.__setattr__(self,'project_root',Path(self.project_root).resolve())
        if self.workspace_override:object.__setattr__(self,'workspace_override',Path(self.workspace_override).resolve())
        if not 1<=self.api_port<=65535:raise ValueError('API port must be between 1 and 65535')
        origins=tuple(dict.fromkeys((*self.allowed_origins,f'http://127.0.0.1:{self.api_port}',f'http://localhost:{self.api_port}')))
        object.__setattr__(self,'allowed_origins',origins)

    @property
    def workspace(self):return self.workspace_override or self.project_root/'workspaces/default'

    @staticmethod
    def resolve_project_path(project_dir:Path,relative:str):
        if not relative or Path(relative).is_absolute() or PureWindowsPath(relative).drive or chr(92) in relative or ':' in relative:raise ValueError('Project paths must be portable relative paths')
        root=project_dir.resolve();target=(root/relative).resolve()
        if not target.is_relative_to(root):raise ValueError('Project path escapes its root')
        return target

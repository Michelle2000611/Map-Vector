import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from mapvector.domain.project import Project
from mapvector.infrastructure.repositories.database import ProjectDatabase


class ProjectRepository:
    def __init__(self, workspace: Path):
        self.projects_dir = workspace / 'projects'
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def create(self, project_name: str) -> Project:
        now = datetime.now(timezone.utc).isoformat()
        project = Project(str(uuid4()), project_name, 0, now, now)
        directory = self.projects_dir / project.project_id
        (directory / 'state').mkdir(parents=True)
        ProjectDatabase(directory / 'state' / 'project.sqlite').initialize()
        manifest = directory / 'project.json'
        temporary = manifest.with_suffix('.tmp')
        temporary.write_text(json.dumps(asdict(project), ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            with ProjectDatabase(directory / 'state' / 'project.sqlite').transaction() as connection:
                connection.execute('INSERT INTO project (project_id,project_name,working_revision,created_at,updated_at) VALUES (?,?,?,?,?)', (project.project_id,project.project_name,project.working_revision,project.created_at,project.updated_at))
            temporary.replace(manifest)
        except BaseException:
            temporary.unlink(missing_ok=True)
            if not manifest.exists():
                import shutil
                shutil.rmtree(directory, ignore_errors=True)
            raise
        return project

    def get(self, project_id: str) -> Project:
        from uuid import UUID
        project_id = str(UUID(project_id))
        path = self.projects_dir / project_id / 'state' / 'project.sqlite'
        if not path.is_file():
            raise KeyError(project_id)
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
            row = connection.execute('SELECT project_id,project_name,working_revision,created_at,updated_at,current_asset_id,current_snapshot_id,schema_revision,export_policy_id,workflow_stage FROM project WHERE project_id=?', (project_id,)).fetchone()
        if row is None:
            raise KeyError(project_id)
        return Project(*row)

    def list(self) -> list[Project]:
        projects = []
        for manifest in sorted(self.projects_dir.glob('*/project.json')):
            projects.append(self.get(manifest.parent.name))
        return projects

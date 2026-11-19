from uuid import UUID

from fastapi import Request

from mapvector.api.resource_schemas import Envelope
from mapvector.application.face_colors import FaceColorRequest, FaceColorReport, search
from mapvector.infrastructure.repositories.database import ProjectDatabase


def register(app, project_directory, envelope):
    @app.post('/api/projects/{project_id}/face-color-searches', response_model=Envelope[FaceColorReport])
    def face_color_search(project_id: UUID, body: FaceColorRequest, request: Request):
        directory = project_directory(str(project_id))
        return envelope(request, search(ProjectDatabase(directory / 'state/project.sqlite'), str(project_id), body))

from uuid import UUID

from fastapi import Request

from mapvector.api.resource_schemas import Envelope
from mapvector.application.line_checks import (LineCheckRequest, LineCheckDecision, LineCheckReport,
                                               LineCheckDecisionResult, create_preview, decide)
from mapvector.infrastructure.repositories.database import ProjectDatabase


def register(app, project_directory, envelope):
    @app.post('/api/projects/{project_id}/line-check-previews',response_model=Envelope[LineCheckReport])
    def line_check_preview(project_id: UUID, body: LineCheckRequest, request: Request):
        directory=project_directory(str(project_id))
        return envelope(request,create_preview(ProjectDatabase(directory/'state/project.sqlite'),str(project_id),body))

    @app.post('/api/projects/{project_id}/line-check-decisions',response_model=Envelope[LineCheckDecisionResult])
    def line_check_decision(project_id: UUID, body: LineCheckDecision, request: Request):
        directory=project_directory(str(project_id))
        return envelope(request,decide(ProjectDatabase(directory/'state/project.sqlite'),str(project_id),body))

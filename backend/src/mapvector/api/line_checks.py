from uuid import UUID
from typing import Literal

from fastapi import Query, Request

from mapvector.api.resource_schemas import Envelope
from mapvector.application.line_checks import (LineCheckRequest, LineCheckDecision, LineCheckReport,
                                               LineCheckPage, LineCheckDecisionResult, create_preview, candidate_page, decide)
from mapvector.infrastructure.repositories.database import ProjectDatabase


def register(app, project_directory, envelope):
    @app.post('/api/projects/{project_id}/line-check-previews',response_model=Envelope[LineCheckReport])
    def line_check_preview(project_id: UUID, body: LineCheckRequest, request: Request):
        directory=project_directory(str(project_id))
        return envelope(request,create_preview(ProjectDatabase(directory/'state/project.sqlite'),str(project_id),body))

    @app.get('/api/projects/{project_id}/line-check-previews/{preview_id}/candidates',response_model=Envelope[LineCheckPage])
    def line_check_candidates(project_id: UUID, preview_id: UUID, request: Request, asset_id: UUID,
                              base_revision: int=Query(ge=0,le=9007199254740990),
                              kind: Literal['join_gap','text_stroke','dash_group']=Query(),
                              filter: Literal['pending','kept','applied','all']='pending',
                              offset: int=Query(default=0,ge=0), limit: int=Query(default=25,ge=1,le=200)):
        directory=project_directory(str(project_id))
        return envelope(request,candidate_page(ProjectDatabase(directory/'state/project.sqlite'),str(project_id),
                                               str(asset_id),base_revision,str(preview_id),kind,filter,offset,limit))

    @app.post('/api/projects/{project_id}/line-check-decisions',response_model=Envelope[LineCheckDecisionResult])
    def line_check_decision(project_id: UUID, body: LineCheckDecision, request: Request):
        directory=project_directory(str(project_id))
        return envelope(request,decide(ProjectDatabase(directory/'state/project.sqlite'),str(project_id),body))

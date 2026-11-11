from uuid import UUID
from fastapi import Request
from mapvector.api.resource_schemas import Envelope
from mapvector.application.text_residue_review import TextResidueDecision, TextResidueDecisionResult, decide
from mapvector.infrastructure.repositories.database import ProjectDatabase


def register(app, project_directory, envelope):
    @app.post('/api/projects/{project_id}/text-residue-decisions',response_model=Envelope[TextResidueDecisionResult])
    def text_residue_decision(project_id: UUID, body: TextResidueDecision, request: Request):
        directory=project_directory(str(project_id))
        return envelope(request,decide(ProjectDatabase(directory/'state/project.sqlite'),str(project_id),body))

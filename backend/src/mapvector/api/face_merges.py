from uuid import UUID
from fastapi import Request
from mapvector.application.face_merges import FaceMergeRequest, create_preview
from mapvector.application.ports import ProjectDatabase
from mapvector.domain.errors import CommandConflict
from mapvector.api.face_merge_schemas import FaceMergePreviewResponse
from mapvector.api.resource_schemas import Envelope


def register(app, project_directory, envelope, error):
    @app.post('/api/projects/{project_id}/face-merge-previews',response_model=Envelope[FaceMergePreviewResponse],response_model_exclude_unset=True)
    def preview(project_id: UUID, body: FaceMergeRequest, request: Request):
        directory=project_directory(str(project_id))
        try:
            with ProjectDatabase(directory/'state/project.sqlite').transaction() as connection:
                result=create_preview(connection,str(project_id),body,directory)
            return envelope(request,result)
        except CommandConflict as exc:
            return error(request,409 if exc.code in ('REVISION_CONFLICT','PREVIEW_STALE') else 422,exc.code,'面合并检查未完成',exc.detail)

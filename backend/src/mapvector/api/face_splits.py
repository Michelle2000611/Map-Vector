from uuid import UUID
from fastapi import Request
from mapvector.application.face_splits import FaceSplitRequest,create_preview
from mapvector.application.ports import ProjectDatabase
from mapvector.domain.errors import CommandConflict


def register(app,project_directory,envelope,error):
    @app.post('/api/projects/{project_id}/face-split-previews')
    def preview(project_id:UUID,body:FaceSplitRequest,request:Request):
        directory=project_directory(str(project_id))
        try:
            with ProjectDatabase(directory/'state/project.sqlite').transaction() as connection:result=create_preview(connection,str(project_id),body,directory)
            return envelope(request,result)
        except CommandConflict as exc:return error(request,409 if exc.code in ('REVISION_CONFLICT','PREVIEW_STALE') else 422,exc.code,'面分割检查未完成',exc.detail)

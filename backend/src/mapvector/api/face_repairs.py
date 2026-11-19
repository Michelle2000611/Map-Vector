from uuid import UUID

from fastapi import Request, Query

from mapvector.application.face_repairs import FaceRepairRequest, HealResidueDecision, confirm_heal_candidates, create_preview, repair_history, scan_asset
from mapvector.domain.errors import CommandConflict
from mapvector.infrastructure.repositories.database import ProjectDatabase


def register(app, project_directory, envelope, error):
    @app.post('/api/projects/{project_id}/heal-residue-decisions')
    def heal_residue_decision(project_id:UUID,body:HealResidueDecision,request:Request):
        directory=project_directory(str(project_id))
        try:
            result=confirm_heal_candidates(ProjectDatabase(directory/'state/project.sqlite'),str(project_id),body)
            return envelope(request,result)
        except CommandConflict as exc:
            return error(request,409,exc.code,'残留核对未保存',exc.detail)

    @app.get('/api/projects/{project_id}/face-repair-scan')
    def face_repair_scan(project_id:UUID,asset_id:UUID,request:Request,cursor:UUID|None=None,base_revision:int|None=Query(default=None,ge=0)):
        directory=project_directory(str(project_id))
        try:
            with ProjectDatabase(directory/'state/project.sqlite').read() as connection:
                connection.execute('BEGIN')
                result=scan_asset(connection,str(project_id),str(asset_id),directory,cursor=str(cursor) if cursor else None,base_revision=base_revision)
            return envelope(request,result)
        except CommandConflict as exc:
            return error(request,409 if exc.code in ('REVISION_CONFLICT','ASSET_RESULT_MISMATCH') else 422,exc.code,'面检查未完成',exc.detail)

    @app.get('/api/projects/{project_id}/face-repair-history')
    def face_repair_history(project_id:UUID,asset_id:UUID,feature_id:UUID,request:Request):
        directory=project_directory(str(project_id))
        with ProjectDatabase(directory/'state/project.sqlite').read() as connection:
            if connection.execute('SELECT 1 FROM asset WHERE project_id=? AND asset_id=?',(str(project_id),str(asset_id))).fetchone() is None:raise KeyError(str(asset_id))
            if connection.execute("SELECT 1 FROM feature WHERE project_id=? AND asset_id=? AND feature_id=? AND feature_type='face'",(str(project_id),str(asset_id),str(feature_id))).fetchone() is None:raise KeyError(str(feature_id))
            result=repair_history(connection,str(project_id),str(asset_id),str(feature_id))
        return envelope(request,result)

    @app.post('/api/projects/{project_id}/face-repair-previews')
    def face_repair_preview(project_id:UUID, body:FaceRepairRequest, request:Request):
        directory=project_directory(str(project_id))
        try:
            with ProjectDatabase(directory/'state/project.sqlite').transaction() as connection:
                result=create_preview(connection,str(project_id),body,directory)
            return envelope(request,result)
        except CommandConflict as exc:
            return error(request,409 if exc.code in ('REVISION_CONFLICT','ASSET_RESULT_MISMATCH') else 422,exc.code,'面修复预览未生成',exc.detail)

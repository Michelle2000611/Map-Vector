import logging
import math
import hashlib
import json
import re
import threading
from starlette.exceptions import HTTPException as StarletteHTTPException
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import asdict
from uuid import UUID, uuid4

from fastapi import FastAPI, Request, UploadFile, File, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mapvector.api.schemas import CreateProject, ProjectEnvelope, CreateAsset, CreateSnapshot, CreateExport, RestoreSnapshot,RoiAudit,FeatureEnvelope,EditEnvelope,ErrorResponse
from mapvector.configuration.settings import Settings
from mapvector.infrastructure.repositories.project import ProjectRepository
from mapvector.infrastructure.repositories.database import ProjectDatabase
from mapvector.domain.commands import EditCommand
from mapvector.application.commands import CommandService, CommandConflict
from mapvector.application.snapshots import SnapshotService
from mapvector.application.exports import ExportService
from mapvector.application.assets import AssetService
from mapvector.application.jobs import JobService
from mapvector.application.export_jobs import ExportJobService
from mapvector.domain.jobs import StartRun,AdoptRun
from mapvector.api.resource_schemas import Envelope,Page,Source,Asset,Run,JobEvent,Snapshot,Export,Candidate,Style,Layer,RoiResult,ReviewPage,SelectionResult,Preview,Operation,ProjectResponse
from mapvector.infrastructure.storage.raster import MAX_BYTES
from mapvector.domain.errors import CommandConflict
from PIL import Image, UnidentifiedImageError
from mapvector.api.schemas import WorkflowStage
from mapvector.api.resource_schemas import TextLayerAssessmentReport


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    repository = ProjectRepository(settings.workspace)
    app = FastAPI(title='Map-Vector', version='0.1.0',responses={status:{'model':ErrorResponse} for status in (400,403,404,409,422,500,503,504)})
    app.state.settings = settings
    # Existing project stores need explicit forward migration before newly added routes can read them.
    for database_path in settings.workspace.glob('projects/*/state/project.sqlite'):
        ProjectDatabase(database_path).initialize()
        SnapshotService(database_path.parents[1]).recover()
    job_services={}
    export_services={}
    job_lock=threading.Lock()

    def job_service(project_id):
        with job_lock:
            if project_id not in job_services:
                job_services[project_id]=JobService(project_directory(project_id),settings.project_root)
            return job_services[project_id]

    def export_service(project_id):
        with job_lock:
            if project_id not in export_services:export_services[project_id]=ExportJobService(project_directory(project_id))
            return export_services[project_id]

    def error(request, status, code, message, detail=None):
        return JSONResponse(status_code=status, content=dict(code=code, message=message, detail=detail or {}, recoverable=status < 500, request_id=request.state.request_id))

    def envelope(request, data):
        return dict(data=data, request_id=request.state.request_id, schema_revision='1.0')

    def decode_record(row):
        value=dict(row)
        for key in ('config_snapshot','plugin_manifest','input_region_px','local_to_asset_affine','event_data','policy_snapshot','readback_report','layer_types','result_summary','payload_snapshot','error_detail'):
            if key in value and isinstance(value[key],str):value[key]=json.loads(value[key])
        if 'is_visible' in value:value['is_visible']=bool(value['is_visible'])
        return value

    def project_directory(project_id):
        path = settings.workspace / 'projects' / project_id
        if not path.is_dir():
            raise KeyError(project_id)
        return path

    def relative_file(project_id, relative):
        return settings.resolve_project_path(project_directory(project_id), relative)

    @app.middleware('http')
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('origin') not in (None, *settings.allowed_origins):
            return error(request, 403, 'ORIGIN_FORBIDDEN', '请求来源不受允许')
        if request.headers.get('X-Contract-Revision') not in (None,'1.0'):
            return error(request,409,'CONTRACT_REVISION_UNSUPPORTED','不支持所请求的契约修订')
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [{'loc': list(item['loc']), 'type': item['type'], 'message': item['msg']} for item in exc.errors()]
        return error(request, 422, 'VALIDATION_ERROR', '请求参数无效', {'errors': errors})

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return error(request, 404, 'RESOURCE_NOT_FOUND', '资源不存在')

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request,exc):
        return error(request,exc.status_code,'RESOURCE_NOT_FOUND' if exc.status_code==404 else 'HTTP_ERROR','资源不存在' if exc.status_code==404 else str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logging.getLogger('mapvector').exception('Unhandled request %s', request.state.request_id)
        return error(request, 500, 'INTERNAL_ERROR', '服务异常，请根据请求编号检查日志')

    @app.get('/api/health')
    def health(request: Request):
        return envelope(request, {'status': 'ready'})

    @app.get('/api/capabilities')
    def capabilities(request: Request):
        from mapvector.application.runtime_status import plugin_status
        plugins=plugin_status(settings.project_root)
        evidence_path=settings.project_root/'docs/migration/baseline-equivalence.json'
        verified=evidence_path.is_file() and json.loads(evidence_path.read_text(encoding='utf-8')).get('equivalent') is True
        return envelope(request,{'recognition':{**plugins['b2c'],'pipeline_id':'legacy_b2c','runtime_equivalence':'versioned_postprocessing_not_baseline_equivalent' if verified else 'not_verified','frozen_baseline_verified':verified,'postprocess_revision':'valid_region_lines_text_v1'},'ocr':{'rapid':plugins['rapid'],'paddle':plugins['paddle']},'project':{'available':True},'policy_id':'baseline_compatible'})

    @app.get('/api/plugins')
    def plugins(request:Request):
        from mapvector.application.runtime_status import plugin_status
        return envelope(request,{'items':list(plugin_status(settings.project_root).values()),'next_cursor':None})

    @app.get('/api/pipelines')
    def pipelines(request:Request):
        from mapvector.application.runtime_status import plugin_status
        plugins=plugin_status(settings.project_root)
        plugins['combined']={'available':plugins['rapid']['available'] and plugins['paddle']['available'],'missing_or_invalid':plugins['rapid']['missing_or_invalid']+plugins['paddle']['missing_or_invalid']}
        items=[]
        for identity,stages,engine in [('legacy_b2c',['vectorize'],None),('legacy_b2c_rapid',['vectorize','ocr'],'rapid'),('legacy_b2c_paddle',['vectorize','ocr'],'paddle'),('ocr_rapid',['ocr'],'rapid'),('ocr_paddle',['ocr'],'paddle'),('legacy_b2c_combined',['vectorize','ocr_rapid','ocr_paddle'],'combined'),('ocr_combined',['ocr_rapid','ocr_paddle'],'combined')]:
            available=plugins['b2c']['available'] if identity.startswith('legacy_b2c') else plugins[engine]['available']
            items.append({'pipeline_id':identity,'pipeline_revision':'1.0','available':available,'stages':stages,'ocr_optional':identity.startswith('legacy_b2c_'),'ocr_available':plugins[engine]['available'] if engine else None,'ocr_failure_reason':plugins[engine]['missing_or_invalid'] if engine else []})
        return envelope(request,{'items':items,'next_cursor':None})

    @app.post('/api/projects', status_code=201, response_model=ProjectEnvelope)
    def create_project(payload: CreateProject, request: Request):
        return envelope(request, asdict(repository.create(payload.project_name)))

    @app.get('/api/projects',response_model=Envelope[Page[ProjectResponse]])
    def list_projects(request: Request):
        return envelope(request, {'items': [asdict(project) for project in repository.list()], 'next_cursor': None})

    @app.get('/api/projects/{project_id}', response_model=ProjectEnvelope)
    def get_project(project_id: UUID, request: Request):
        return envelope(request, asdict(repository.get(str(project_id))))

    @app.post('/api/projects/{project_id}/name', response_model=ProjectEnvelope)
    def rename_project(project_id: UUID, payload: CreateProject, request: Request):
        directory = project_directory(str(project_id))
        with ProjectDatabase(directory / 'state/project.sqlite').transaction() as connection:
            connection.execute('UPDATE project SET project_name=?,updated_at=? WHERE project_id=?', (payload.project_name, datetime.now(timezone.utc).isoformat(), str(project_id)))
        return envelope(request, asdict(repository.get(str(project_id))))

    @app.post('/api/projects/import', status_code=201, response_model=ProjectEnvelope)
    async def import_project(request: Request, file: UploadFile = File(...),world_file:UploadFile|None=File(None),crs_file:UploadFile|None=File(None)):
        from mapvector.application.ports import probe
        import shutil
        content = await file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise CommandConflict('UPLOAD_TOO_LARGE', {'max_bytes': MAX_BYTES})
        probe(content)
        reference=None
        if bool(world_file)!=bool(crs_file):raise CommandConflict('GEOREFERENCE_PAIR_REQUIRED',{'reason':'World file and CRS file are both required'})
        if world_file:
            from mapvector.geometry.georeference import external_reference
            world=await world_file.read(65537);crs=await crs_file.read(1048577)
            if len(world)>65536 or len(crs)>1048576:raise CommandConflict('GEOREFERENCE_INVALID',{'reason':'Sidecar file is too large'})
            reference=external_reference(world,crs)
        filename = (file.filename or '原图').replace(chr(92), '/').split('/')[-1]
        name = Path(filename).stem.strip()[:120] or '原图'
        project = repository.create(name)
        directory = project_directory(project.project_id)
        try:
            service = AssetService(directory)
            source = service.upload_source(project.project_id, filename, content)
            if reference:
                from mapvector.application.ports import atomic_bytes,atomic_json
                folder=directory/source['source_rel_path']
                atomic_bytes(folder.parent/'world.txt',world);atomic_bytes(folder.parent/'crs.prj',crs)
                atomic_json(folder.parent/'georeference.json',reference)
            service.normalize_asset(project.project_id, source['source_id'], 0, {'dpi': 200})
        except BaseException:
            shutil.rmtree(directory)
            raise
        return envelope(request, asdict(repository.get(project.project_id)))

    @app.post('/api/projects/{project_id}/workflow-stage', response_model=ProjectEnvelope)
    def advance_workflow(project_id: UUID, payload: WorkflowStage, request: Request):
        directory = project_directory(str(project_id))
        with ProjectDatabase(directory / 'state/project.sqlite').transaction() as connection:
            row = connection.execute('SELECT workflow_stage,current_asset_id FROM project WHERE project_id=?', (str(project_id),)).fetchone()
            current=int(row['workflow_stage']);target=int(payload.stage)
            # Persisted review/edit cursors share one UI workspace; quality keeps ID 4.
            if (target>current+1 and not (target==4 and current in (2,3))) or (target>0 and not row['current_asset_id']):
                return error(request,409,'WORKFLOW_STAGE_LOCKED','请先完成当前步骤，再进入下一步')
            connection.execute('UPDATE project SET workflow_stage=MAX(workflow_stage,?) WHERE project_id=?',(target,str(project_id)))
        return envelope(request, asdict(repository.get(str(project_id))))

    @app.exception_handler(CommandConflict)
    async def command_error(request, exc):
        status=409 if exc.code in ('ASSET_RESULT_MISMATCH','REVISION_CONFLICT','SNAPSHOT_HASH_MISMATCH','PREVIEW_STALE','IDEMPOTENCY_CONFLICT','LINE_REVIEW_REQUIRED','LINE_REVIEW_FORBIDDEN','LINE_REVIEW_MISMATCH','PREVIEW_SCOPE_MISMATCH','RESIDUE_SPLIT_RESTORE_REQUIRES_UNDO') else 503 if exc.code in ('OCR_ENGINE_UNAVAILABLE','RUNTIME_DEPENDENCY_MISSING') else 504 if exc.code=='OCR_TIMEOUT' else 413 if exc.code=='UPLOAD_TOO_LARGE' else 422
        return error(request,status,exc.code,'请求无法提交',exc.detail)

    @app.post('/api/projects/{project_id}/sources', status_code=201,response_model=Envelope[Source])
    async def upload_source(project_id: UUID, request: Request, file: UploadFile = File(...)):
        directory=project_directory(str(project_id))
        content=await file.read(MAX_BYTES+1)
        result=AssetService(directory).upload_source(str(project_id),file.filename or 'source',content)
        return envelope(request,result)

    @app.post('/api/projects/{project_id}/assets', status_code=201,response_model=Envelope[Asset])
    def create_asset(project_id: UUID, payload: CreateAsset, request: Request):
        result=AssetService(project_directory(str(project_id))).normalize_asset(str(project_id),str(payload.source_id),payload.page_index,payload.normalization_config.model_dump())
        return envelope(request,result)

    @app.get('/api/projects/{project_id}/assets/{asset_id}',response_model=Envelope[Asset])
    def get_asset(project_id: UUID, asset_id: UUID, request: Request):
        return envelope(request,AssetService(project_directory(str(project_id))).get(str(project_id),str(asset_id)))

    @app.get('/api/projects/{project_id}/assets',response_model=Envelope[Page[Asset]])
    def list_assets(project_id:UUID,request:Request):
        directory=project_directory(str(project_id))
        with ProjectDatabase(directory/'state/project.sqlite').read() as connection:rows=connection.execute('SELECT asset_id FROM asset WHERE project_id=? ORDER BY created_at DESC',(str(project_id),)).fetchall()
        return envelope(request,{'items':[AssetService(directory).get(str(project_id),row[0]) for row in rows],'next_cursor':None})

    @app.get('/api/projects/{project_id}/sources',response_model=Envelope[Page[Source]])
    def list_sources(project_id:UUID,request:Request):
        directory=project_directory(str(project_id))
        with ProjectDatabase(directory/'state/project.sqlite').read() as connection:rows=connection.execute('SELECT * FROM source_file WHERE project_id=? ORDER BY created_at DESC',(str(project_id),)).fetchall()
        items=[]
        for row in rows:
            item=decode_record(row)
            manifest=json.loads((directory/item['source_rel_path']).with_name('manifest.json').read_text(encoding='utf-8'))
            items.append({**item,'source_type':manifest['source_type']})
        return envelope(request,{'items':items,'next_cursor':None})

    @app.post('/api/projects/{project_id}/assets/{asset_id}/adopt')
    def adopt_asset(project_id: UUID, asset_id: UUID, payload: CreateSnapshot, request: Request):
        result=AssetService(project_directory(str(project_id))).adopt(str(project_id),str(asset_id),payload.base_revision)
        return envelope(request,result)

    @app.get('/api/projects/{project_id}/assets/{asset_id}/raster')
    def get_asset_raster(project_id: UUID, asset_id: UUID):
        from fastapi.responses import FileResponse
        asset=AssetService(project_directory(str(project_id))).get(str(project_id),str(asset_id))
        return FileResponse(relative_file(str(project_id),asset['raster_rel_path']),media_type='image/png')

    @app.get('/api/projects/{project_id}/assets/{asset_id}/crop')
    def asset_crop(project_id:UUID,asset_id:UUID,bounds_px:str):
        import io
        from fastapi.responses import Response
        asset=AssetService(project_directory(str(project_id))).get(str(project_id),str(asset_id))
        try:
            bounds=[float(value) for value in bounds_px.split(',')]
            if len(bounds)!=4 or not all(math.isfinite(value) for value in bounds):raise ValueError()
            x0,y0,x1,y1=bounds
            x0=max(0,math.floor(x0));y0=max(0,math.floor(y0));x1=min(asset['width_px'],math.ceil(x1));y1=min(asset['height_px'],math.ceil(y1))
            if x1<=x0 or y1<=y0 or (x1-x0)*(y1-y0)>4_000_000:raise ValueError()
        except ValueError:raise CommandConflict('VALIDATION_ERROR',{'field':'bounds_px'})
        with Image.open(relative_file(str(project_id),asset['raster_rel_path'])) as image:
            output=io.BytesIO();image.crop((x0,y0,x1,y1)).save(output,'PNG')
        return Response(output.getvalue(),media_type='image/png',headers={'X-Coordinate-Space':'pixel','Cache-Control':'no-store'})

    @app.get('/api/projects/{project_id}/features',response_model=FeatureEnvelope)
    def list_features(project_id: UUID, request: Request, asset_id: UUID, feature_type: str | None = None, bbox_px: str | None = None, limit: int = Query(500, ge=1, le=2000), cursor: str | None = Query(None,max_length=1024),layer_type:str|None=None):
        from mapvector.api.pagination import query_digest,encode_cursor,decode_cursor
        project_id = str(project_id)
        directory = project_directory(project_id)
        if feature_type not in (None, 'face', 'line', 'text'):
            return error(request, 422, 'VALIDATION_ERROR', '对象类别无效')
        try:
            bounds = [float(value) for value in bbox_px.split(',')] if bbox_px else None
            if bounds is not None and (len(bounds) != 4 or not all(map(math.isfinite, bounds)) or bounds[2] < bounds[0] or bounds[3] < bounds[1]):
                raise ValueError()
        except ValueError:
            return error(request, 422, 'VALIDATION_ERROR', 'bbox_px必须是有限的[min_x,min_y,max_x,max_y]')
        if layer_type not in (None,'face','line','text','isolated_line'):raise CommandConflict('VALIDATION_ERROR',{'field':'layer_type'})
        with ProjectDatabase(directory / 'state' / 'project.sqlite').read() as connection:
            connection.execute('BEGIN')
            if connection.execute('SELECT 1 FROM asset WHERE asset_id=? AND project_id=?', (str(asset_id), project_id)).fetchone() is None:
                raise KeyError(str(asset_id))
            conditions = ['project_id=?', 'asset_id=?', "lifecycle_status IN ('active','isolated')"]
            values = [project_id, str(asset_id)]
            revision=connection.execute('SELECT working_revision FROM project WHERE project_id=?',(project_id,)).fetchone()[0]
            digest=query_digest(project_id,str(asset_id),feature_type,bounds,layer_type)
            if cursor:
                conditions.append('feature_id>?')
                values.append(decode_cursor(cursor,revision,digest))
            if feature_type:
                conditions.append('feature_type=?'); values.append(feature_type)
            if layer_type:
                conditions.append('feature_type=?');values.append('line' if layer_type=='isolated_line' else layer_type)
                conditions.append('lifecycle_status=?');values.append('isolated' if layer_type=='isolated_line' else 'active')
            if bounds:
                conditions.append('rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_display_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?)')
                values.extend([bounds[0], bounds[2], bounds[1], bounds[3]]*2)
            rows = connection.execute('SELECT feature_id FROM feature WHERE ' + ' AND '.join(conditions) + ' ORDER BY feature_id LIMIT ?', [*values, limit + 1]).fetchall()
            next_cursor = encode_cursor(rows[limit - 1]['feature_id'],revision,digest) if len(rows) > limit else None
            items = [CommandService._feature(connection, row['feature_id']) for row in rows[:limit]]
            project = connection.execute('SELECT working_revision FROM project WHERE project_id=?', (project_id,)).fetchone()
        return envelope(request, {'items': items, 'next_cursor': next_cursor, 'working_revision': project['working_revision'],'coordinate_space':'pixel','asset_id':str(asset_id)})

    @app.post('/api/projects/{project_id}/edit-commands',response_model=EditEnvelope)
    def edit_command(project_id: UUID, request: Request, command: EditCommand):
        try:
            result = CommandService(ProjectDatabase(project_directory(str(project_id)) / 'state' / 'project.sqlite')).apply(str(project_id), command)
            return envelope(request, result)
        except CommandConflict as exc:
            status = 409 if exc.code in ('REVISION_CONFLICT', 'IDEMPOTENCY_CONFLICT', 'ASSET_RESULT_MISMATCH','PREVIEW_STALE','OCR_DUPLICATE_TEXT','OCR_POSITION_CONFLICT','LINE_REVIEW_REQUIRED','LINE_REVIEW_FORBIDDEN','LINE_REVIEW_MISMATCH','PREVIEW_SCOPE_MISMATCH','RESIDUE_SPLIT_RESTORE_REQUIRES_UNDO') else 422
            return error(request, status, exc.code, '编辑命令未提交', exc.detail)
        except ValueError as exc:
            return error(request, 422, 'VALIDATION_ERROR', '命令参数无效', {'detail': str(exc)})

    from mapvector.domain.selection import SelectionRequest,PreviewRequest
    @app.post('/api/projects/{project_id}/selections',response_model=Envelope[SelectionResult])
    def select_features(project_id:UUID,body:SelectionRequest,request:Request):
        from mapvector.application.previews import select
        directory=project_directory(str(project_id))
        with ProjectDatabase(directory/'state/project.sqlite').read() as connection:
            result=select(connection,str(project_id),body,directory)
            revision=connection.execute('SELECT working_revision FROM project WHERE project_id=?',(str(project_id),)).fetchone()[0]
        return envelope(request,{'feature_ids':result,'working_revision':revision})

    @app.post('/api/projects/{project_id}/edit-previews',response_model=Envelope[Preview])
    def preview_edit(project_id:UUID,body:PreviewRequest,request:Request):
        from mapvector.application.previews import create_preview
        directory=project_directory(str(project_id))
        database=ProjectDatabase(directory/'state/project.sqlite')
        if body.preview_type=='text_residue':
            from mapvector.application.text_residue_review import create_local_preview
            result=create_local_preview(database,str(project_id),body,directory)
        else:
            with database.transaction() as connection:result=create_preview(connection,str(project_id),body,directory)
        return envelope(request,result)

    @app.get('/api/projects/{project_id}/reviews',response_model=Envelope[ReviewPage])
    def review_queue(project_id: UUID,asset_id: UUID,request: Request,include_all:bool=False):
        from mapvector.application.exports import DELIVERABLE
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            asset=connection.execute('SELECT 1 FROM asset WHERE asset_id=? AND project_id=?',(str(asset_id),str(project_id))).fetchone()
            if asset is None:raise KeyError(str(asset_id))
            features=[CommandService._feature(connection,row[0]) for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active' ORDER BY feature_id",(str(project_id),str(asset_id)))]
            for feature in features:
                candidate=connection.execute('SELECT score,engine_id FROM ocr_candidate WHERE candidate_id=?',(feature['primary_candidate_id'],)).fetchone() if feature['primary_candidate_id'] else None
                feature.update(ocr_score=candidate['score'] if candidate else None,ocr_engine_id=candidate['engine_id'] if candidate else None)
        counts={}
        for feature in features:counts[feature['review_status']]=counts.get(feature['review_status'],0)+1
        return envelope(request,{'items':features if include_all else [f for f in features if f['review_status'] not in DELIVERABLE],'status_counts':counts,'policy_id':'baseline_compatible','next_cursor':None})

    @app.get('/api/projects/{project_id}/text-layer-assessments',response_model=Envelope[TextLayerAssessmentReport])
    def text_layer_assessments(project_id:UUID,asset_id:UUID,request:Request):
        from mapvector.application.text_layer_assessment import assess
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            connection.execute('BEGIN')
            result=assess(connection,str(project_id),str(asset_id),project_directory(str(project_id)))
        return envelope(request,result)

    @app.get('/api/projects/{project_id}/styles',response_model=Envelope[Page[Style]])
    def list_styles(project_id:UUID,request:Request):
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:rows=connection.execute('SELECT * FROM style WHERE project_id=? ORDER BY style_name',(str(project_id),)).fetchall()
        items=[]
        for row in rows:
            item=dict(row);item['dash_pattern_px']=json.loads(item['dash_pattern_px']);items.append(item)
        return envelope(request,{'items':items,'next_cursor':None})

    @app.get('/api/projects/{project_id}/layers',response_model=Envelope[Page[Layer]])
    def list_layers(project_id:UUID,asset_id:UUID,request:Request):
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            if connection.execute('SELECT 1 FROM asset WHERE asset_id=? AND project_id=?',(str(asset_id),str(project_id))).fetchone() is None:raise KeyError(str(asset_id))
            rows=connection.execute('SELECT * FROM layer_setting WHERE project_id=? AND asset_id=?',(str(project_id),str(asset_id))).fetchall()
        return envelope(request,{'items':[decode_record(row) for row in rows],'next_cursor':None})

    @app.get('/api/projects/{project_id}/roi',response_model=Envelope[RoiResult])
    def get_roi(project_id:UUID,asset_id:UUID,request:Request):
        from mapvector.application.relations import roi_state
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            if connection.execute('SELECT 1 FROM asset WHERE asset_id=? AND project_id=?',(str(asset_id),str(project_id))).fetchone() is None:raise KeyError(str(asset_id))
            row=connection.execute('SELECT * FROM roi WHERE project_id=? AND asset_id=?',(str(project_id),str(asset_id))).fetchone()
        return envelope(request,{'roi':roi_state(row) if row else None})

    @app.post('/api/projects/{project_id}/roi-audits')
    def roi_audit(project_id:UUID,request:Request,body:RoiAudit):
        from mapvector.geometry.scope import audit
        from mapvector.application.relations import roi_state
        asset_id=str(body.asset_id)
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            row=connection.execute('SELECT * FROM roi WHERE project_id=? AND asset_id=?',(str(project_id),asset_id)).fetchone()
            if row is None:raise CommandConflict('EXPORT_SCOPE_INVALID')
            if body.roi_id and str(body.roi_id)!=row['roi_id']:raise CommandConflict('EXPORT_SCOPE_INVALID')
            features=[CommandService._feature(connection,item[0]) for item in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated')",(str(project_id),asset_id))]
            result={kind:audit([f for f in features if f['feature_type']==kind],dict(row)) for kind in ('face','line','text')}
        return envelope(request,{'roi':roi_state(row),'counts':result})

    @app.get('/api/projects/{project_id}/quality')
    def quality(project_id:UUID,asset_id:UUID,request:Request):
        from shapely.geometry import shape,box
        from shapely import union_all,coverage_is_valid
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            asset=connection.execute('SELECT * FROM asset WHERE project_id=? AND asset_id=?',(str(project_id),str(asset_id))).fetchone()
            if asset is None:raise KeyError(str(asset_id))
            features=[CommandService._feature(connection,row[0]) for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status='active'",(str(project_id),str(asset_id)))]
            revision=connection.execute('SELECT working_revision FROM project WHERE project_id=?',(str(project_id),)).fetchone()[0]
        from mapvector.geometry.raster_mask import valid_region
        faces=[shape(f['geometry']) for f in features if f['feature_type']=='face'];region=valid_region(project_directory(str(project_id))/asset['raster_rel_path']);union=union_all(faces)
        return envelope(request,{'working_revision':revision,'quality_report':{'target':'full_asset_pixel_extent','target_area_px2':region.area,'face_count':len(faces),'valid_geometry_count':sum(shape(f['geometry']).is_valid for f in features),'coverage_is_valid':bool(coverage_is_valid(faces)) if faces else None,'covered_area_px2':union.intersection(region).area,'uncovered_area_px2':region.difference(union).area,'overlap_area_px2':max(0,sum(g.area for g in faces)-union.area),'recognition_accuracy':None,'tolerance_px2':max(1e-6,region.area*1e-12),'note':'Geometric coverage only; true holes and image correctness require visual review'}})

    @app.post('/api/projects/{project_id}/roi-previews')
    def roi_preview(project_id:UUID,body:RoiAudit,request:Request):
        from mapvector.geometry.scope import scoped_features
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            roi=connection.execute('SELECT * FROM roi WHERE project_id=? AND asset_id=?',(str(project_id),str(body.asset_id))).fetchone()
            if roi is None or body.roi_id and str(body.roi_id)!=roi['roi_id']:raise CommandConflict('EXPORT_SCOPE_INVALID')
            features=[CommandService._feature(connection,row[0]) for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated')",(str(project_id),str(body.asset_id)))]
            revision=connection.execute('SELECT working_revision FROM project WHERE project_id=?',(str(project_id),)).fetchone()[0]
        return envelope(request,{'working_revision':revision,'coordinate_space':'pixel','roi_id':roi['roi_id'],'roi_revision':roi['revision'],'keep_crossing':scoped_features(features,'keep_crossing',dict(roi)),'clip':scoped_features(features,'clip',dict(roi))})

    @app.get('/api/projects/{project_id}/rasters/{raster_type}')
    def raster(project_id:UUID,raster_type:str,asset_id:UUID,request:Request,threshold:int|None=Query(None,ge=0,le=255),run_id:UUID|None=None,layer:str|None=None):
        from mapvector.application.rendering import render_raster
        from fastapi.responses import Response
        if layer not in (None,'face','line','text'):raise CommandConflict('VALIDATION_ERROR',{'field':'layer'})
        if layer is not None and raster_type!='render_compare':raise CommandConflict('VALIDATION_ERROR',{'field':'layer','reason':'Category filters apply only to recognition baseline previews'})
        content,revision=render_raster(project_directory(str(project_id)),str(project_id),str(asset_id),raster_type,threshold,str(run_id) if run_id else None,layer)
        return Response(content,media_type='image/png',headers={'X-Working-Revision':str(revision),'X-Coordinate-Space':'pixel','X-Text-Glyphs':'excluded','Cache-Control':'no-store'})

    @app.get('/api/projects/{project_id}/ocr-candidates',response_model=Envelope[Page[Candidate]])
    def ocr_candidates(project_id:UUID,asset_id:UUID,request:Request):
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            if connection.execute('SELECT 1 FROM asset WHERE asset_id=? AND project_id=?',(str(asset_id),str(project_id))).fetchone() is None:raise KeyError(str(asset_id))
            rows=connection.execute('SELECT * FROM ocr_candidate WHERE project_id=? AND asset_id=? ORDER BY created_at,candidate_id',(str(project_id),str(asset_id))).fetchall()
        items=[]
        for row in rows:
            item=dict(row)
            item['detected_quad_px']=json.loads(item['detected_quad_px']) if item['detected_quad_px'] else None
            item['rule_suggestions']=json.loads(item['rule_suggestions']);items.append(item)
        return envelope(request,{'items':items,'next_cursor':None})

    @app.post('/api/projects/{project_id}/snapshots', status_code=201,response_model=Envelope[Snapshot])
    def create_snapshot(project_id: UUID, request: Request, body: CreateSnapshot):
        try:
            result = SnapshotService(project_directory(str(project_id))).create(str(project_id), body.base_revision, body.snapshot_note)
            return envelope(request, result)
        except CommandConflict as exc:
            return error(request, 409, exc.code, '保存时工作修订发生变化')

    @app.get('/api/projects/{project_id}/snapshots',response_model=Envelope[Page[Snapshot]])
    def list_snapshots(project_id: UUID, request: Request):
        directory = project_directory(str(project_id))
        with ProjectDatabase(directory / 'state/project.sqlite').read() as connection:
            rows = connection.execute("SELECT * FROM snapshot WHERE snapshot_status='committed' ORDER BY snapshot_sequence DESC").fetchall()
        return envelope(request, {'items':[decode_record(row) for row in rows], 'next_cursor':None})

    @app.post('/api/projects/{project_id}/snapshots/{snapshot_id}/restore')
    def restore_snapshot(project_id: UUID, snapshot_id: UUID, body: RestoreSnapshot, request: Request):
        return envelope(request,SnapshotService(project_directory(str(project_id))).restore(str(project_id),str(snapshot_id),body.base_revision))

    @app.post('/api/projects/{project_id}/runs',status_code=202,response_model=Envelope[Run])
    def start_run(project_id: UUID,body: StartRun,request: Request):
        result=job_service(str(project_id)).start(str(project_id),body.model_dump())
        return envelope(request,result)

    @app.get('/api/projects/{project_id}/runs',response_model=Envelope[Page[Run]])
    def list_runs(project_id: UUID,request: Request):
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            rows=connection.execute('SELECT * FROM run WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(str(project_id),)).fetchall()
        service=job_service(str(project_id))
        return envelope(request,{'items':[decode_record(service.get(str(project_id),row['run_id'])) for row in rows],'next_cursor':None})

    @app.get('/api/projects/{project_id}/runs/{run_id}',response_model=Envelope[Run])
    def get_run(project_id: UUID,run_id: UUID,request: Request):
        service=job_service(str(project_id));service.recover()
        return envelope(request,decode_record(service.get(str(project_id),str(run_id))))

    @app.post('/api/projects/{project_id}/runs/{run_id}/cancel',response_model=Envelope[Run])
    def cancel_run(project_id: UUID,run_id: UUID,request: Request):
        service=job_service(str(project_id));service.cancel(str(project_id),str(run_id))
        return envelope(request,decode_record(service.get(str(project_id),str(run_id))))

    @app.get('/api/projects/{project_id}/runs/{run_id}/logs/{stream}')
    def run_log(project_id:UUID,run_id:UUID,stream:str):
        from fastapi.responses import PlainTextResponse
        job_service(str(project_id)).get(str(project_id),str(run_id))
        if stream not in ('stdout','stderr'):raise CommandConflict('VALIDATION_ERROR',{'field':'stream'})
        path=relative_file(str(project_id),'runs/'+str(run_id)+'/'+stream+'.log')
        if not path.is_file():return PlainTextResponse('',headers={'X-Log-State':'pending'})
        with path.open('rb') as source:
            source.seek(max(0,path.stat().st_size-1024*1024));content=source.read().decode('utf-8',errors='replace')
        return PlainTextResponse(content,headers={'Cache-Control':'no-store'})

    @app.get('/api/projects/{project_id}/runs/{run_id}/events',response_model=Envelope[Page[JobEvent]])
    def run_events(project_id: UUID,run_id: UUID,request: Request,after_event_id:int=Query(0,ge=0)):
        service=job_service(str(project_id))
        events=service.events(str(project_id),str(run_id),after_event_id)
        return envelope(request,{'items':[decode_record(item) for item in events],'next_cursor':events[-1]['event_id'] if events else None})

    @app.get('/api/projects/{project_id}/runs/{run_id}/artifacts')
    def run_artifacts(project_id: UUID,run_id: UUID,request: Request):
        return envelope(request,{'items':job_service(str(project_id)).artifacts(str(project_id),str(run_id)),'next_cursor':None})

    @app.post('/api/projects/{project_id}/runs/{run_id}/adopt')
    def adopt_run(project_id: UUID,run_id: UUID,body: AdoptRun,request: Request):
        try:
            result=job_service(str(project_id)).adopt(str(project_id),str(run_id),body.base_revision,body.adoption_mode,body.idempotency_key)
            return envelope(request,result)
        except CommandConflict as exc:
            return error(request,409,exc.code,'运行结果未采用',exc.detail)

    @app.get('/api/projects/{project_id}/operations',response_model=Envelope[Page[Operation]])
    def operation_history(project_id:UUID,request:Request,asset_id:UUID|None=None,include_results:bool=True):
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            if asset_id and connection.execute('SELECT 1 FROM asset WHERE project_id=? AND asset_id=?',(str(project_id),str(asset_id))).fetchone() is None:raise KeyError(str(asset_id))
            fields='*' if include_results else "operation_id,project_id,operation_type,base_revision,result_revision,operation_status,created_at,'{}' AS result_summary"
            rows=[dict(row) for row in connection.execute('SELECT '+fields+' FROM operation WHERE project_id=? ORDER BY result_revision DESC LIMIT 500',(str(project_id),))]
            applied=next((row['operation_id'] for row in rows if row['operation_status']=='applied' and row['operation_type'] not in ('undo','redo')),None)
            undone=[row for row in rows if row['operation_status']=='undone' and row['operation_type'] not in ('undo','redo')]
            redo=min(undone,key=lambda row:row['result_revision'])['operation_id'] if undone else None
            for row in rows:
                row['can_undo']=row['operation_id']==applied
                row['can_redo']=row['operation_id']==redo
                row['result_summary']=json.loads(row['result_summary'])
        return envelope(request,{'items':rows,'next_cursor':None})

    @app.get('/api/projects/{project_id}/feature-lineage')
    def lineage(project_id:UUID,request:Request,feature_id:UUID|None=None):
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            sql='SELECT l.* FROM feature_lineage l JOIN feature f ON l.target_feature_id=f.feature_id WHERE f.project_id=?';values=[str(project_id)]
            if feature_id:sql+=' AND (l.source_feature_id=? OR l.target_feature_id=?)';values.extend([str(feature_id),str(feature_id)])
            rows=[dict(row) for row in connection.execute(sql,values)]
        for row in rows:row['source_attributes']=json.loads(row['source_attributes'])
        return envelope(request,{'items':rows,'next_cursor':None})

    @app.post('/api/projects/{project_id}/exports', status_code=201)
    def create_export(project_id: UUID, request: Request, body: CreateExport):
        try:
            result=ExportService(project_directory(str(project_id))).create(str(project_id),body.model_dump(mode='json'))
            return envelope(request,result)
        except CommandConflict as exc:
            status=409 if exc.code in ('FORMAL_REVIEW_INCOMPLETE','SNAPSHOT_HASH_MISMATCH') else 422
            return error(request,status,exc.code,'导出请求未完成',exc.detail)

    @app.get('/api/projects/{project_id}/exports/{export_id}',response_model=Envelope[Export])
    def get_export(project_id: UUID, export_id: UUID, request: Request):
        service=export_service(str(project_id));service.recover()
        result=decode_record(service.get(str(project_id),str(export_id)))
        return envelope(request,result)

    @app.post('/api/projects/{project_id}/export-jobs',status_code=202,response_model=Envelope[Export])
    def start_export_job(project_id:UUID,body:CreateExport,request:Request):
        return envelope(request,export_service(str(project_id)).start(str(project_id),body.model_dump(mode='json')))

    @app.post('/api/projects/{project_id}/exports/{export_id}/cancel',response_model=Envelope[Export])
    def cancel_export_job(project_id:UUID,export_id:UUID,request:Request):
        return envelope(request,decode_record(export_service(str(project_id)).cancel(str(project_id),str(export_id))))

    @app.get('/api/projects/{project_id}/exports',response_model=Envelope[Page[Export]])
    def list_exports(project_id: UUID,request: Request):
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            rows=connection.execute('SELECT * FROM export WHERE project_id=? ORDER BY created_at DESC LIMIT 100',(str(project_id),)).fetchall()
        service=export_service(str(project_id))
        return envelope(request,{'items':[decode_record(service.get(str(project_id),row['export_id'])) for row in rows],'next_cursor':None})

    @app.get('/api/projects/{project_id}/exports/{export_id}/delivery-package')
    def download_delivery(project_id:UUID,export_id:UUID):
        from fastapi.responses import Response
        from mapvector.application.delivery import delivery_package
        return Response(delivery_package(project_directory(str(project_id)),str(project_id),str(export_id)),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="mapvector-gis-delivery.zip"'})

    @app.get('/api/projects/{project_id}/exports/{export_id}/download')
    def download_export(project_id: UUID, export_id: UUID):
        from fastapi.responses import FileResponse
        with ProjectDatabase(project_directory(str(project_id))/'state/project.sqlite').read() as connection:
            row=connection.execute("SELECT output_rel_path,export_format,output_sha256 FROM export WHERE export_id=? AND project_id=? AND export_status='completed'",(str(export_id),str(project_id))).fetchone()
        if row is None:
            raise KeyError(str(export_id))
        from mapvector.infrastructure.storage.files import sha256_file
        path=settings.resolve_project_path(project_directory(str(project_id)),row['output_rel_path'])
        if sha256_file(path)!=row['output_sha256']:raise CommandConflict('EXPORT_HASH_MISMATCH')
        mime={'gpkg':'application/geopackage+sqlite3','shp':'application/zip','geojson':'application/geo+json','pixel_json':'application/json'}[row['export_format']]
        return FileResponse(path,media_type=mime,filename=path.name)

    from mapvector.api.face_repairs import register as register_face_repairs
    register_face_repairs(app,project_directory,envelope,error)
    from mapvector.api.line_checks import register as register_line_checks
    register_line_checks(app,project_directory,envelope)
    from mapvector.api.text_residue_review import register as register_text_residue_review
    register_text_residue_review(app,project_directory,envelope)
    static=settings.project_root/'frontend/dist'
    if (static/'assets').is_dir() and (static/'index.html').is_file():
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse
        app.mount('/assets',StaticFiles(directory=static/'assets'),name='frontend_assets')

        @app.get('/{path:path}',include_in_schema=False)
        def frontend(path:str):
            if path.startswith('api/'):
                raise StarletteHTTPException(404)
            return FileResponse(static/'index.html',media_type='text/html')
    for existing in repository.list():
        job_service(existing.project_id);export_service(existing.project_id)
    return app

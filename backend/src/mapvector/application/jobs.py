"""Persistent serial jobs: pinned inputs, owned subprocesses, explicit result adoption."""
import hashlib
import json
import math
import os
import shutil
import sys
import threading
import time
from concurrent.futures import Future,ThreadPoolExecutor
from datetime import datetime,timezone
from importlib.metadata import version,PackageNotFoundError
from pathlib import Path
from uuid import uuid4

from shapely import to_wkb
from shapely.geometry import shape,Point
from mapvector.domain.errors import CommandConflict
from mapvector.domain.ports import get_ports
from mapvector.application.ports import ProjectDatabase
from mapvector.application.ports import load_feature,restore_feature,update_index
from mapvector.application.ports import atomic_json,atomic_bytes,sha256_file
from mapvector.application.ports import run_process,worker_is_alive

EXECUTOR=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mapvector-recognition')
OWNER_ID=str(uuid4())
ACTIVE=set()
ACTIVE_LOCK=threading.RLock()
TERMINAL={'completed','completed_with_warnings','failed','cancelled','interrupted'}


def utcnow():return datetime.now(timezone.utc).isoformat()


def model_inventory(root,engine):
    manifest_path=root/'models'/engine/'manifest.json'
    if not manifest_path.is_file():raise CommandConflict('OCR_ENGINE_UNAVAILABLE',{'engine_id':engine,'manifest':str(manifest_path)})
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'));files=[]
    for item in manifest['files']:
        path=(manifest_path.parent/item['rel_path']).resolve()
        if not path.is_relative_to(manifest_path.parent.resolve()) or not path.is_file():raise CommandConflict('MODEL_HASH_MISMATCH',{'file':item['rel_path']})
        digest=sha256_file(path)
        if digest!=item['sha256']:raise CommandConflict('MODEL_HASH_MISMATCH',{'file':item['rel_path']})
        files.append({'rel_path':path.relative_to(root).as_posix(),'sha256':digest})
    return {'manifest_rel_path':manifest_path.relative_to(root).as_posix(),'manifest_sha256':sha256_file(manifest_path),'model_id':manifest['model_id'],'files':files}


class JobService:
    def __init__(self,project_dir:Path,project_root:Path|None=None,executor=None):
        self.project_dir=project_dir.resolve();self.project_root=(project_root or project_dir.parents[3]).resolve()
        self.database=ProjectDatabase(self.project_dir/'state/project.sqlite');self.owner_id=OWNER_ID
        self._executor=executor or EXECUTOR;self._futures={};self._lock=threading.RLock()
        self.recover()

    def recover(self):
        queued=[]
        with self.database.transaction() as connection:
            rows=connection.execute("SELECT * FROM run WHERE run_status IN ('queued','starting','running','cancelling')").fetchall()
            for row in rows:
                identity=(str(self.database.path),row['run_id'])
                with ACTIVE_LOCK:active=identity in ACTIVE and row['worker_owner_id']==OWNER_ID
                if active:continue
                if row['run_status']=='queued':
                    queued.append((row['project_id'],row['run_id']));continue
                # Never kill an unowned live PID after a restart. Preserve state and recheck it later.
                if worker_is_alive(row['worker_pid'],row['run_id']):continue
                status='cancelled' if row['cancel_requested'] else 'interrupted'
                connection.execute('UPDATE run SET run_status=?,finished_at=?,worker_pid=NULL,error_code=? WHERE run_id=?',(status,utcnow(),'SERVICE_RESTART',row['run_id']))
                self._event(connection,row['run_id'],'error',None,{'code':'SERVICE_RESTART','run_status':status})
        for project_id,run_id in queued:self._schedule(project_id,run_id)

    def _schedule(self,project_id,run_id):
        identity=(str(self.database.path),run_id)
        with ACTIVE_LOCK:
            if identity in ACTIVE:return
            ACTIVE.add(identity)
        try:self._futures[run_id]=self._executor.submit(self._execute,project_id,run_id)
        except BaseException:
            with ACTIVE_LOCK:ACTIVE.discard(identity)
            raise

    @staticmethod
    def _event(connection,run_id,event_type,stage,data):
        run=connection.execute('SELECT created_at,started_at FROM run WHERE run_id=?',(run_id,)).fetchone()
        start=(run['started_at'] or run['created_at']) if run else None
        data={**data,'elapsed_ms':max(0,int((datetime.now(timezone.utc)-datetime.fromisoformat(start)).total_seconds()*1000)) if start else 0}
        if stage:data.update(stdout_rel_path='runs/'+run_id+'/stdout.log',stderr_rel_path='runs/'+run_id+'/stderr.log')
        sequence=connection.execute('SELECT COALESCE(MAX(event_id),0)+1 FROM job_event WHERE run_id=?',(run_id,)).fetchone()[0]
        if sequence>9007199254740991:raise CommandConflict('REVISION_LIMIT_EXCEEDED')
        connection.execute('INSERT INTO job_event VALUES (?,?,?,?,?,?)',(run_id,sequence,event_type,stage,json.dumps(data,ensure_ascii=False,allow_nan=False),utcnow()))

    def _pin(self,pipeline):
        source_root=get_ports().workers.source_root();paths=get_ports().workers.pinned_algorithm_paths()
        files=[{'source_rel_path':path.relative_to(source_root).as_posix(),'sha256':sha256_file(path)} for path in paths]
        packages={}
        for name in ('numpy','shapely','geopandas','pyogrio','rasterio','scikit-image','scipy','rapidocr','onnxruntime'):
            try:packages[name]=version(name)
            except PackageNotFoundError:packages[name]=None
        pinned={'schema_revision':'1.0','files':files,'packages':packages,'ocr_optional':pipeline.startswith('legacy_b2c_'),'engine_id':pipeline.rsplit('_',1)[-1] if pipeline!='legacy_b2c' else None}
        if pinned['engine_id']=='combined':
            pinned['engines']={engine:self._pin('legacy_b2c_'+engine) for engine in ('rapid','paddle')}
        engine=pinned['engine_id']
        if engine in ('rapid','paddle'):
            try:pinned['model']=model_inventory(self.project_root,engine)
            except CommandConflict as exc:
                if not pinned['ocr_optional']:raise
                pinned['ocr_unavailable']={'code':exc.code,'detail':exc.detail}
            interpreter=self.project_root/('.venv-ocr-paddle/Scripts/python.exe' if os.name=='nt' else '.venv-ocr-paddle/bin/python') if engine=='paddle' else Path(sys.executable)
            if not interpreter.is_file():
                if not pinned['ocr_optional']:raise CommandConflict('OCR_ENGINE_UNAVAILABLE',{'interpreter':str(interpreter)})
                pinned['ocr_unavailable']={'code':'OCR_ENGINE_UNAVAILABLE','detail':{'interpreter':str(interpreter)}}
            pinned['interpreter']=str(interpreter)
            if engine=='paddle' and interpreter.is_file():
                try:pinned['worker_packages']=get_ports().workers.package_versions(str(interpreter),['paddlepaddle','paddleocr','paddlex','numpy'])
                except Exception as exc:
                    if not pinned['ocr_optional']:raise CommandConflict('OCR_ENGINE_UNAVAILABLE',{'interpreter':str(interpreter),'reason':str(exc)}) from exc
                    pinned['ocr_unavailable']={'code':'OCR_ENGINE_UNAVAILABLE','detail':{'reason':str(exc)}}
        return pinned

    def start(self,project_id,payload):
        pipeline=payload['pipeline_id'];config=dict(payload.get('config_snapshot') or {});region=payload.get('input_region_px')
        if payload.get('pipeline_revision','1.0')!='1.0' or config:raise CommandConflict('PIPELINE_CONFIG_UNSUPPORTED')
        if pipeline not in ('legacy_b2c','legacy_b2c_rapid','legacy_b2c_paddle','ocr_rapid','ocr_paddle','ocr_combined','legacy_b2c_combined'):raise CommandConflict('PIPELINE_CONFIG_UNSUPPORTED')
        if region is not None and pipeline not in ('ocr_rapid','ocr_paddle','ocr_combined'):raise CommandConflict('OCR_REGION_INVALID')
        pinned=self._pin(pipeline);run_id=str(uuid4());now=utcnow();retry_of=str(payload['retry_of_run_id']) if payload.get('retry_of_run_id') else None
        with self.database.transaction() as connection:
            project=connection.execute('SELECT * FROM project WHERE project_id=?',(project_id,)).fetchone()
            if project is None:raise KeyError(project_id)
            asset=connection.execute('SELECT * FROM asset WHERE project_id=? AND asset_id=?',(project_id,project['current_asset_id'])).fetchone()
            if asset is None:raise CommandConflict('ASSET_REQUIRED')
            if region is not None:
                x0,y0,x1,y1=region
                if not all(math.isfinite(x) for x in region) or not(0<=x0<x1<=asset['width_px'] and 0<=y0<y1<=asset['height_px']):raise CommandConflict('OCR_REGION_INVALID')
            if sha256_file(self.project_dir/asset['raster_rel_path'])!=asset['raster_sha256']:raise CommandConflict('ASSET_RESULT_MISMATCH')
            if retry_of and connection.execute('SELECT 1 FROM run WHERE run_id=? AND project_id=?',(retry_of,project_id)).fetchone() is None:raise KeyError(retry_of)
            # BEGIN IMMEDIATE makes the active-input check atomic across API instances.
            active=connection.execute("SELECT * FROM run WHERE project_id=? AND asset_id=? AND pipeline_id=? AND input_raster_sha256=? AND run_status IN ('queued','starting','running','cancelling') ORDER BY created_at DESC",(project_id,asset['asset_id'],pipeline,asset['raster_sha256'])).fetchall()
            for previous in active:
                if json.loads(previous['input_region_px'] or 'null')==(list(region) if region is not None else None):
                    return {'run_id':previous['run_id'],'run_status':previous['run_status'],'asset_id':previous['asset_id'],'input_raster_sha256':previous['input_raster_sha256'],'pipeline_id':pipeline,'input_region_px':region}
            config={'input_region_px':region,'ocr_optional':pinned['ocr_optional'],'create_text_drafts':pipeline.startswith('legacy_b2c_'),'scales':[1,2],'min_score':0.0}
            affine=[1,0,int(region[0]),0,1,int(region[1])] if region else None
            record={'run_id':run_id,'project_id':project_id,'asset_id':asset['asset_id'],'input_raster_sha256':asset['raster_sha256'],'pipeline_id':pipeline,'pipeline_revision':'1.0','config_snapshot':json.dumps(config),'plugin_manifest':json.dumps(pinned),'run_status':'queued','run_type':'ocr_region' if region else 'recognition','base_revision':project['working_revision'],'created_at':now,'retry_of_run_id':retry_of,'input_region_px':json.dumps(region) if region else None,'local_to_asset_affine':json.dumps(affine) if affine else None,'worker_owner_id':OWNER_ID}
            connection.execute('INSERT INTO run ('+','.join(record)+') VALUES ('+','.join('?' for _ in record)+')',tuple(record.values()))
            self._event(connection,run_id,'progress',None,{'run_status':'queued'})
        self._schedule(project_id,run_id)
        return {'run_id':run_id,'run_status':'queued','asset_id':asset['asset_id'],'input_raster_sha256':asset['raster_sha256'],'pipeline_id':pipeline,'input_region_px':region}

    def _check_pins(self,run):
        return self._validate_pins(json.loads(run['plugin_manifest']))

    def _validate_pins(self,pinned):
        source_root=get_ports().workers.source_root()
        for item in pinned['files']:
            if sha256_file(source_root/item['source_rel_path'])!=item['sha256']:raise CommandConflict('PLUGIN_HASH_MISMATCH',{'file':item['source_rel_path']})
        for name,expected in pinned.get('packages',{}).items():
            try:actual=version(name)
            except PackageNotFoundError:actual=None
            if actual!=expected:raise CommandConflict('RUNTIME_DEPENDENCY_MISMATCH',{'package':name,'expected':expected,'actual':actual})
        if pinned.get('worker_packages'):
            actual=get_ports().workers.package_versions(pinned['interpreter'],list(pinned['worker_packages']))
            if actual!=pinned['worker_packages']:raise CommandConflict('RUNTIME_DEPENDENCY_MISMATCH',{'resource':'worker_interpreter'})
        if 'model' in pinned:
            model=pinned['model'];manifest=self.project_root/model['manifest_rel_path']
            if sha256_file(manifest)!=model['manifest_sha256']:raise CommandConflict('MODEL_HASH_MISMATCH')
            for item in model['files']:
                if sha256_file(self.project_root/item['rel_path'])!=item['sha256']:raise CommandConflict('MODEL_HASH_MISMATCH',{'file':item['rel_path']})
        return pinned

    def _execute(self,project_id,run_id):
        identity=(str(self.database.path),run_id);work=self.project_dir/'runs'/run_id
        try:
            with self.database.transaction() as connection:
                run=connection.execute('SELECT * FROM run WHERE project_id=? AND run_id=?',(project_id,run_id)).fetchone()
                if run is None or run['run_status']!='queued' or run['cancel_requested']:return
                connection.execute("UPDATE run SET run_status='starting',started_at=?,heartbeat_at=?,worker_owner_id=? WHERE run_id=?",(utcnow(),utcnow(),OWNER_ID,run_id))
                asset=connection.execute('SELECT * FROM asset WHERE project_id=? AND asset_id=?',(project_id,run['asset_id'])).fetchone()
            pinned=self._check_pins(run)
            if asset is None or sha256_file(self.project_dir/asset['raster_rel_path'])!=run['input_raster_sha256']:raise CommandConflict('ASSET_RESULT_MISMATCH')
            work.mkdir(parents=True,exist_ok=False)
            atomic_json(work/'request.json',{'schema_revision':'1.0','run_id':run_id,'asset_id':asset['asset_id'],'input_raster_sha256':run['input_raster_sha256'],'config_snapshot':json.loads(run['config_snapshot']),'plugin_manifest':pinned})
            # Every subprocess reads a frozen per-run input, never a mutable current asset path.
            frozen=work/'input.png';shutil.copyfile(self.project_dir/asset['raster_rel_path'],frozen)
            if sha256_file(frozen)!=run['input_raster_sha256']:raise CommandConflict('ASSET_RESULT_MISMATCH')
            warnings=[]
            if pinned['engine_id']=='combined':
                warnings.extend(self._combined_ocr(project_id,run_id,frozen,work,run,pinned))
            elif pinned['engine_id']:
                try:
                    if pinned.get('ocr_unavailable'):raise CommandConflict(pinned['ocr_unavailable']['code'],pinned['ocr_unavailable']['detail'])
                    arguments=self._ocr_arguments(frozen,work,run,pinned)
                    self._stage(run,work,'ocr',arguments,1800 if pinned['engine_id']=='paddle' else 900)
                    self._register_ocr(project_id,run_id,run['asset_id'],work/'ocr_candidates.json')
                except CommandConflict as exc:
                    if not pinned['ocr_optional'] or exc.code=='RUN_CANCELLED':raise
                    warnings.append({'code':exc.code,'detail':exc.detail})
                    with self.database.transaction() as connection:self._event(connection,run_id,'error','ocr',{'code':exc.code,'detail':exc.detail,'optional':True})
            if run['pipeline_id'].startswith('legacy_b2c'):
                self._stage(run,work,'vectorize',get_ports().workers.vector_arguments(sys.executable,frozen,work/'vector_layers.gpkg'),3600)
                self._register(project_id,run_id,work/'vector_layers.gpkg','vector_layers','vector_layers')
                self._register(project_id,run_id,work/'run_report.json','quality_report','run_report')
            with self.database.transaction() as connection:
                if self._cancelled(connection,run_id):raise CommandConflict('RUN_CANCELLED')
                state='completed_with_warnings' if warnings else 'completed'
                connection.execute('UPDATE run SET run_status=?,progress_percent=100,stage_name=NULL,finished_at=?,heartbeat_at=?,worker_pid=NULL,error_code=?,error_detail=? WHERE run_id=?',(state,utcnow(),utcnow(),warnings[0]['code'] if warnings else None,json.dumps(warnings) if warnings else None,run_id))
                self._event(connection,run_id,'progress',None,{'run_status':state,'progress_percent':100,'warnings':warnings})
            atomic_json(work/'manifest.json',{'run_id':run_id,'run_status':state,'input_raster_sha256':run['input_raster_sha256'],'warnings':warnings,'artifacts':self.artifacts(project_id,run_id)})
        except Exception as exc:
            code=exc.code if isinstance(exc,CommandConflict) else 'RECOGNITION_FAILED';detail=exc.detail if isinstance(exc,CommandConflict) else {'reason':str(exc)}
            with self.database.transaction() as connection:
                state='cancelled' if code=='RUN_CANCELLED' else 'failed'
                connection.execute('UPDATE run SET run_status=?,finished_at=?,worker_pid=NULL,error_code=?,error_detail=? WHERE run_id=?',(state,utcnow(),code,json.dumps(detail),run_id))
                self._event(connection,run_id,'error',None,{'code':code,'detail':detail,'run_status':state})
        finally:
            with ACTIVE_LOCK:ACTIVE.discard(identity)

    @staticmethod
    def _cancelled(connection,run_id):
        row=connection.execute('SELECT cancel_requested FROM run WHERE run_id=?',(run_id,)).fetchone()
        return row is None or bool(row[0])

    def _stage(self,run,work,stage,arguments,timeout):
        stage_started=time.monotonic()
        environment=get_ports().workers.environment(self.project_root)
        with self.database.transaction() as connection:
            if self._cancelled(connection,run['run_id']):raise CommandConflict('RUN_CANCELLED')
            connection.execute("UPDATE run SET run_status='running',stage_name=?,heartbeat_at=? WHERE run_id=?",(stage,utcnow(),run['run_id']))
            self._event(connection,run['run_id'],'stage_started',stage,{'stage_name':stage})
        def started(process):
            with self.database.transaction() as connection:connection.execute('UPDATE run SET worker_pid=?,worker_owner_id=?,heartbeat_at=? WHERE run_id=?',(process.pid,OWNER_ID,utcnow(),run['run_id']))
        def heartbeat():
            with self.database.transaction() as connection:connection.execute('UPDATE run SET heartbeat_at=? WHERE run_id=?',(utcnow(),run['run_id']))
        def cancelled():
            with self.database.read() as connection:return self._cancelled(connection,run['run_id'])
        run_process(arguments,work,environment,started,heartbeat,cancelled,timeout,'OCR_TIMEOUT' if stage.startswith('ocr') else 'RECOGNITION_TIMEOUT')
        with self.database.transaction() as connection:
            connection.execute('UPDATE run SET worker_pid=NULL,heartbeat_at=? WHERE run_id=?',(utcnow(),run['run_id']))
            counts={}
            report_path=work/('run_report.json' if stage=='vectorize' else 'ocr_candidates.json')
            if report_path.is_file():
                report=json.loads(report_path.read_text(encoding='utf-8'))
                counts={key:report[key] for key in ('faces','lines','b2c_objects','colour_classes') if key in report} if stage=='vectorize' else {'candidates':len(report['items'])}
            self._event(connection,run['run_id'],'stage_finished',stage,{'stage_name':stage,'stage_elapsed_ms':int((time.monotonic()-stage_started)*1000),'counts':counts})

    def _combined_ocr(self,project_id,run_id,raster,work,run,pinned):
        from mapvector.application.ocr_fusion import fuse_results
        results=[];warnings=[]
        for engine,config in pinned['engines'].items():
            with self.database.read() as connection:
                if self._cancelled(connection,run_id):raise CommandConflict('RUN_CANCELLED')
            try:
                self._validate_pins(config)
                if config.get('ocr_unavailable'):raise CommandConflict(config['ocr_unavailable']['code'],config['ocr_unavailable']['detail'])
                output=work/('ocr_'+engine+'.json')
                self._stage(run,work,'ocr_'+engine,self._ocr_arguments(raster,work,run,config,output),1800 if engine=='paddle' else 900)
                result=json.loads(output.read_text(encoding='utf-8'))
                # Retain each engine's immutable raw evidence independently.
                self._register(project_id,run_id,output,'ocr_raw_'+engine,'ocr_candidates')
                results.append(result)
            except CommandConflict as exc:
                if exc.code=='RUN_CANCELLED':raise
                warning={'code':exc.code,'detail':{**exc.detail,'engine':engine}}
                warnings.append(warning)
                with self.database.transaction() as connection:self._event(connection,run_id,'error','ocr_'+engine,warning)
        if not results and not pinned['ocr_optional']:raise CommandConflict('OCR_ALL_ENGINES_FAILED',{'failures':warnings})
        if results:
            merged=fuse_results(results)
            atomic_json(work/'ocr_candidates.json',{**merged,'warnings':warnings})
            self._register_ocr(project_id,run_id,run['asset_id'],work/'ocr_candidates.json')
        return warnings

    def _ocr_arguments(self,raster,work,run,pinned,output=None):
        engine=pinned['engine_id'];model=self.project_root/'models'/engine;interpreter=pinned['interpreter']
        args=get_ports().workers.ocr_arguments(interpreter,raster,output or work/'ocr_candidates.json',model,engine)
        region=json.loads(run['config_snapshot']).get('input_region_px')
        if region:args+=['--region',*[str(value) for value in region]]
        return args

    def _register(self,project_id,run_id,path,kind,schema_name):
        if not path.is_file():raise CommandConflict('ARTIFACT_MISSING',{'artifact_type':kind})
        record={'artifact_id':str(uuid4()),'project_id':project_id,'run_id':run_id,'artifact_type':kind,'artifact_rel_path':path.relative_to(self.project_dir).as_posix(),'sha256':sha256_file(path),'byte_size':path.stat().st_size,'schema_name':schema_name,'schema_revision':'1.0','created_at':utcnow()}
        with self.database.transaction() as connection:
            connection.execute('INSERT INTO artifact ('+','.join(record)+') VALUES ('+','.join('?' for _ in record)+')',tuple(record.values()))
            self._event(connection,run_id,'artifact',None,record)
        return record

    def _register_ocr(self,project_id,run_id,asset_id,path):
        data=json.loads(path.read_text(encoding='utf-8'));items=data['items'];now=utcnow()
        from mapvector.application.ocr_fusion import fuse_results
        # Keep all scale/engine evidence inside each representative candidate.
        items=fuse_results([{'items':items}])['items']
        data.update(items=items,deduplication_revision='spatial_exact_text_v2')
        atomic_json(path,data)
        with self.database.transaction() as connection:
            for item in items:
                quad=item['detected_quad_px'];score=item['score']
                if len(quad)!=4 or any(len(point)!=2 or not all(math.isfinite(value) for value in point) for point in quad) or not math.isfinite(score) or not 0<=score<=1:raise CommandConflict('OCR_RESULT_INVALID')
                connection.execute('INSERT INTO ocr_candidate (candidate_id,project_id,asset_id,run_id,text_feature_id,raw_text,suggested_text,score,detected_quad_px,engine_id,model_id,rule_suggestions,candidate_status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(str(uuid4()),project_id,asset_id,run_id,None,item['raw_text'],item.get('suggested_text'),score,json.dumps(quad),item['engine_id'],item['model_id'],json.dumps(item.get('rule_suggestions',[]),ensure_ascii=False),'unreviewed',now))
        return self._register(project_id,run_id,path,'ocr_candidates','ocr_candidates')

    def cancel(self,project_id,run_id):
        with self.database.transaction() as connection:
            row=connection.execute('SELECT * FROM run WHERE project_id=? AND run_id=?',(project_id,run_id)).fetchone()
            if row is None:raise KeyError(run_id)
            if row['run_status'] in TERMINAL:return {'run_id':run_id,'run_status':row['run_status']}
            state='cancelled' if row['run_status']=='queued' else 'cancelling'
            connection.execute('UPDATE run SET run_status=?,cancel_requested=1,finished_at=? WHERE run_id=?',(state,utcnow() if state=='cancelled' else None,run_id))
            self._event(connection,run_id,'progress',None,{'run_status':state})
        return {'run_id':run_id,'run_status':state}

    def get(self,project_id,run_id):
        with self.database.read() as connection:row=connection.execute('SELECT * FROM run WHERE project_id=? AND run_id=?',(project_id,run_id)).fetchone()
        if row is None:raise KeyError(run_id)
        result=dict(row);start=result['started_at'] or result['created_at']
        end=datetime.fromisoformat(result['finished_at']) if result['finished_at'] else datetime.now(timezone.utc)
        result['elapsed_ms']=max(0,int((end-datetime.fromisoformat(start)).total_seconds()*1000)) if start else 0
        result['stdout_rel_path']='runs/'+run_id+'/stdout.log';result['stderr_rel_path']='runs/'+run_id+'/stderr.log'
        return result

    def events(self,project_id,run_id,after_event_id=0):
        self.get(project_id,run_id)
        with self.database.read() as connection:return [dict(row) for row in connection.execute('SELECT * FROM job_event WHERE run_id=? AND event_id>? ORDER BY event_id LIMIT 1000',(run_id,after_event_id))]

    def artifacts(self,project_id,run_id):
        self.get(project_id,run_id)
        with self.database.read() as connection:return [dict(row) for row in connection.execute('SELECT * FROM artifact WHERE run_id=? AND project_id=? ORDER BY created_at,artifact_id',(run_id,project_id))]

    def adopt(self,project_id,run_id,base_revision,adoption_mode='keep_current',idempotency_key=None):
        with ACTIVE_LOCK:
            return self._adopt(project_id,run_id,base_revision,adoption_mode,idempotency_key)

    def _adopt(self,project_id,run_id,base_revision,adoption_mode,idempotency_key):
        # Implemented below as a single transaction after validating all frozen artifacts.
        with self.database.read() as connection:
            run=connection.execute('SELECT * FROM run WHERE project_id=? AND run_id=?',(project_id,run_id)).fetchone()
            project=connection.execute('SELECT * FROM project WHERE project_id=?',(project_id,)).fetchone()
            if run is None:raise KeyError(run_id)
            if run['run_status'] not in ('completed','completed_with_warnings'):raise CommandConflict('RUN_NOT_ADOPTABLE')
            adoption_digest=hashlib.sha256(json.dumps({'run_id':run_id,'base_revision':base_revision,'adoption_mode':adoption_mode},sort_keys=True).encode()).hexdigest()
            key=idempotency_key or 'adopt:'+run_id
            forked=connection.execute('SELECT request_sha256,result_summary FROM run_adoption_request WHERE project_id=? AND idempotency_key=?',(project_id,key)).fetchone()
            if forked:
                if forked['request_sha256']!=adoption_digest:raise CommandConflict('IDEMPOTENCY_CONFLICT')
                return json.loads(forked['result_summary'])
            previous=connection.execute('SELECT request_sha256,result_summary FROM operation WHERE project_id=? AND idempotency_key=?',(project_id,key)).fetchone()
            if previous:
                if previous['request_sha256']!=adoption_digest:raise CommandConflict('IDEMPOTENCY_CONFLICT')
                return json.loads(previous['result_summary'])
            if run['adopted_operation_id']:
                previous=connection.execute('SELECT result_summary FROM operation WHERE operation_id=?',(run['adopted_operation_id'],)).fetchone()
                return json.loads(previous[0])
            if project['working_revision']!=base_revision or project['current_asset_id']!=run['asset_id']:raise CommandConflict('REVISION_CONFLICT',{'working_revision':project['working_revision']})
            asset=connection.execute('SELECT * FROM asset WHERE project_id=? AND asset_id=?',(project_id,run['asset_id'])).fetchone()
            artifacts=[dict(row) for row in connection.execute('SELECT * FROM artifact WHERE project_id=? AND run_id=?',(project_id,run_id))]
        if sha256_file(self.project_dir/asset['raster_rel_path'])!=run['input_raster_sha256']:raise CommandConflict('ASSET_RESULT_MISMATCH')
        for artifact in artifacts:
            if sha256_file(self.project_dir/artifact['artifact_rel_path'])!=artifact['sha256']:raise CommandConflict('ARTIFACT_HASH_MISMATCH')
        vector=next((item for item in artifacts if item['artifact_type']=='vector_layers'),None)
        if vector is None:raise CommandConflict('ARTIFACT_MISSING')
        import geopandas as gpd,pyogrio
        path=self.project_dir/vector['artifact_rel_path'];available={name for name,_ in pyogrio.list_layers(path)}
        if 'colour_faces' not in available:raise CommandConflict('ARTIFACT_SCHEMA_INVALID')
        frames=[('face',gpd.read_file(path,layer='colour_faces',engine='pyogrio'))]
        if 'visual_lines' in available:frames.append(('line',gpd.read_file(path,layer='visual_lines',engine='pyogrio')))
        from mapvector.application.snapshots import SnapshotService
        with self.database.read() as connection:existing=connection.execute("SELECT COUNT(*) FROM feature WHERE asset_id=? AND lifecycle_status IN ('active','isolated')",(run['asset_id'],)).fetchone()[0]
        if existing and adoption_mode=='keep_current':raise CommandConflict('WORKING_FEATURES_EXIST',{'available_choices':['keep_current','replace','new_project']})
        if adoption_mode=='new_project':
            result=self._fork_result(project_id,run_id,run,asset,artifacts)
            with self.database.transaction() as connection:
                connection.execute('INSERT INTO run_adoption_request VALUES (?,?,?,?,?)',(project_id,key,adoption_digest,json.dumps(result,ensure_ascii=False),utcnow()))
            return result
        if adoption_mode=='replace':SnapshotService(self.project_dir).create(project_id,base_revision,'Before explicit recognition replacement')
        now=utcnow();operation_id=str(uuid4());revision=base_revision+1;before=[];after=[]
        with self.database.transaction() as connection:
            current=connection.execute('SELECT * FROM project WHERE project_id=?',(project_id,)).fetchone()
            if current['working_revision']!=base_revision or current['current_asset_id']!=run['asset_id']:raise CommandConflict('REVISION_CONFLICT')
            for row in connection.execute("SELECT feature_id FROM feature WHERE asset_id=? AND lifecycle_status IN ('active','isolated')",(run['asset_id'],)).fetchall():
                old=load_feature(connection,row[0]);before.append(old)
                connection.execute("UPDATE feature SET lifecycle_status='superseded',revision=?,updated_at=? WHERE feature_id=?",(revision,now,old['feature_id']));update_index(connection,old['feature_id'])
            line_groups={}
            for kind,frame in frames:
                for _,row in frame.iterrows():
                    geometry=row.geometry
                    if geometry is None or geometry.is_empty or not geometry.is_valid or geometry.geom_type not in (('Polygon','MultiPolygon') if kind=='face' else ('LineString',)):raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
                    bounds=geometry.bounds
                    if bounds[0]<-1e-6 or bounds[1]<-1e-6 or bounds[2]>asset['width_px']+1e-6 or bounds[3]>asset['height_px']+1e-6:raise CommandConflict('ASSET_RESULT_MISMATCH')
                    fid=str(uuid4());connection.execute('INSERT INTO feature VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(fid,project_id,run['asset_id'],run_id,kind,geometry.geom_type,to_wkb(geometry),*bounds,'active','algorithm',None,revision,now,now))
                    if kind=='face':connection.execute('INSERT INTO face_attribute VALUES (?,?,?,?,?,?,?,?)',(fid,str(row['rgb']),str(row['label']),str(row['colour_class']),geometry.area,float(row['observed_px']),float(row['inferred_px']),'unchecked'))
                    else:
                        connection.execute('INSERT INTO line_attribute VALUES (?,?,?,?,?,?,?,?,?)',(fid,str(row['rgb']),float(row['width_px']),'unknown','unknown',geometry.length,int(row['draw_order']),None,None))
                        if row.get('logical_id') is not None:line_groups.setdefault(str(row['logical_id']),[]).append(fid)
                    update_index(connection,fid);after.append(load_feature(connection,fid))
            if run['pipeline_id'].startswith('legacy_b2c_'):
                from mapvector.geometry.text import display_bbox,ocr_layout
                from mapvector.application.ocr_fusion import same_location,default_candidate_text
                adopted_boxes=[]
                candidates=connection.execute('SELECT * FROM ocr_candidate WHERE project_id=? AND asset_id=? AND run_id=? AND text_feature_id IS NULL',(project_id,run['asset_id'],run_id)).fetchall()
                candidates=[c for c in candidates if not any('OCR_ENGINE_DISAGREEMENT' in rule.get('reason_codes',[]) for rule in json.loads(c['rule_suggestions']))]
                # Historical runs may predate fusion metadata. Check their
                # actual readings again at the adoption boundary.
                from mapvector.application.ocr_fusion import normalized_text
                conflicts=set()
                for index,left in enumerate(candidates):
                    for right in candidates[index+1:]:
                        if normalized_text(left['raw_text'])!=normalized_text(right['raw_text']) and same_location({'detected_quad_px':json.loads(left['detected_quad_px'])},{'detected_quad_px':json.loads(right['detected_quad_px'])}):
                            conflicts.update((left['candidate_id'],right['candidate_id']))
                for candidate in candidates:
                    if candidate['candidate_id'] in conflicts:continue
                    quad=json.loads(candidate['detected_quad_px'])
                    text=default_candidate_text(candidate)
                    if not text:continue
                    if any(normalized_text(old_text)==normalized_text(text) and same_location({'detected_quad_px':quad},{'detected_quad_px':old_quad}) for old_text,old_quad in adopted_boxes):continue
                    adopted_boxes.append((text,quad))
                    try:layout=ocr_layout(text,quad)
                    except (ValueError,TypeError):raise CommandConflict('OCR_EVIDENCE_MISSING')
                    x,y,size,angle=layout['x'],layout['y'],layout['font_size_px'],layout['rotation_deg']
                    fid=str(uuid4());point=Point(x,y);bounds=point.bounds
                    connection.execute('INSERT INTO feature VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(fid,project_id,run['asset_id'],run_id,'text','Point',to_wkb(point),*bounds,'active','algorithm',None,revision,now,now))
                    connection.execute('INSERT INTO text_attribute (feature_id,text_value,original_text,font_size_px,rotation_deg,text_color,text_anchor,text_content_revision,review_status,review_reason_codes,reviewed_content_revision,reviewed_at,reviewer_id,cleanup_status,display_bbox_px,primary_candidate_id,font_family,review_basis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(fid,text,candidate['raw_text'],size,angle,'#000000','center',0,'required','[]',None,None,None,'not_checked',json.dumps(display_bbox(x,y,text,size,angle)),candidate['candidate_id'],'sans-serif','none'))
                    connection.execute("UPDATE ocr_candidate SET text_feature_id=?,candidate_status='adopted' WHERE candidate_id=?",(fid,candidate['candidate_id']))
                    from mapvector.application.text_layout import set_ocr_layout
                    restore_feature(connection,set_ocr_layout(connection,fid,quad,self.project_dir))
                    from mapvector.application.review import route_adopted_text
                    route_adopted_text(connection,fid)
                    update_index(connection,fid);after.append(load_feature(connection,fid))
            result={'operation_id':operation_id,'result_revision':revision,'adopted_run_id':run_id,'created_feature_count':len(after),'upserted_features':after,'removed_feature_ids':[f['feature_id'] for f in before],'changed_groups':[],'changed_styles':[],'changed_layers':[],'warnings':[]}
            digest=hashlib.sha256(json.dumps({'run_id':run_id,'base_revision':base_revision,'adoption_mode':adoption_mode},sort_keys=True).encode()).hexdigest()
            connection.execute('INSERT INTO operation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(operation_id,project_id,'adopt_run',base_revision,revision,idempotency_key or 'adopt:'+run_id,digest,'applied','local-user',None,json.dumps(result,ensure_ascii=False),now))
            for legacy_group,members in line_groups.items():
                gid=str(uuid4());group={'group_id':gid,'project_id':project_id,'asset_id':run['asset_id'],'feature_type':'line','group_name':legacy_group,'revision':revision}
                result['changed_groups'].append({**group,'feature_ids':members})
                connection.execute('INSERT INTO logical_group VALUES (?,?,?,?,?,?)',tuple(group.values()))
                connection.execute('INSERT INTO operation_change VALUES (?,?,?,?,?,?,?,?,?)',(str(uuid4()),operation_id,'logical_group',gid,None,json.dumps(group),None,None,'1.0'))
                for fid in members:
                    connection.execute('INSERT INTO group_member VALUES (?,?)',(gid,fid));member={'group_id':gid,'feature_id':fid}
                    connection.execute('INSERT INTO operation_change VALUES (?,?,?,?,?,?,?,?,?)',(str(uuid4()),operation_id,'group_member',gid+':'+fid,None,json.dumps(member),None,None,'1.0'))
            connection.execute('UPDATE operation SET result_summary=? WHERE operation_id=?',(json.dumps(result,ensure_ascii=False),operation_id))
            for left,right in [(old,{**old,'lifecycle_status':'superseded','revision':revision,'updated_at':now}) for old in before]+[(None,new) for new in after]:
                f=right or left;connection.execute('INSERT INTO operation_change VALUES (?,?,?,?,?,?,?,?,?)',(str(uuid4()),operation_id,'feature',f['feature_id'],json.dumps(left,ensure_ascii=False) if left else None,json.dumps(right,ensure_ascii=False) if right else None,to_wkb(shape(left['geometry'])) if left else None,to_wkb(shape(right['geometry'])) if right else None,'1.0'))
            connection.execute('UPDATE project SET working_revision=?,updated_at=? WHERE project_id=?',(revision,now,project_id))
            from mapvector.application.history import synchronize_candidates
            synchronize_candidates(connection,project_id)
            connection.execute('UPDATE run SET result_revision=?,adopted_operation_id=? WHERE run_id=?',(revision,operation_id,run_id))
            connection.execute("UPDATE operation SET operation_status='abandoned' WHERE project_id=? AND operation_status='undone'",(project_id,))
        return result

    def _fork_result(self,project_id,run_id,run,asset,artifacts):
        from mapvector.application.ports import ProjectRepository
        from mapvector.application.assets import AssetService
        target=ProjectRepository(self.project_dir.parents[1]).create('Recognition result '+run_id[:8]);directory=self.project_dir.parent/target.project_id
        service=AssetService(directory);source=service.upload_source(target.project_id,'frozen_input.png',(self.project_dir/asset['raster_rel_path']).read_bytes());new_asset=service.normalize_asset(target.project_id,source['source_id'],0,{'dpi':200})
        new_run=str(uuid4());work=directory/'runs'/new_run;work.mkdir(parents=True)
        clone={**dict(run),'run_id':new_run,'project_id':target.project_id,'asset_id':new_asset['asset_id'],'input_raster_sha256':new_asset['raster_sha256'],'adopted_operation_id':None,'base_revision':0,'result_revision':None}
        db=ProjectDatabase(directory/'state/project.sqlite')
        with db.transaction() as connection:
            connection.execute('UPDATE asset SET coordinate_mode=?,crs_wkt=?,pixel_to_map_affine=?,normalization_config=? WHERE asset_id=?',(asset['coordinate_mode'],asset['crs_wkt'],asset['pixel_to_map_affine'],asset['normalization_config'],new_asset['asset_id']))
            connection.execute('INSERT INTO run ('+','.join(clone)+') VALUES ('+','.join('?' for _ in clone)+')',tuple(clone.values()))
            for artifact in artifacts:
                original=self.project_dir/artifact['artifact_rel_path'];copied=work/original.name;shutil.copyfile(original,copied)
                item={**artifact,'artifact_id':str(uuid4()),'project_id':target.project_id,'run_id':new_run,'artifact_rel_path':copied.relative_to(directory).as_posix()}
                connection.execute('INSERT INTO artifact ('+','.join(item)+') VALUES ('+','.join('?' for _ in item)+')',tuple(item.values()))
            with self.database.read() as source_connection:
                candidates=source_connection.execute('SELECT * FROM ocr_candidate WHERE project_id=? AND run_id=?',(project_id,run_id)).fetchall()
            for candidate in candidates:
                item={**dict(candidate),'candidate_id':str(uuid4()),'project_id':target.project_id,'asset_id':new_asset['asset_id'],'run_id':new_run,'text_feature_id':None,'candidate_status':'unreviewed'}
                connection.execute('INSERT INTO ocr_candidate ('+','.join(item)+') VALUES ('+','.join('?' for _ in item)+')',tuple(item.values()))
        atomic_json((directory/new_asset['raster_rel_path']).parent/'manifest.json',service.get(target.project_id,new_asset['asset_id']))
        service=JobService(directory,self.project_root);result=service.adopt(target.project_id,new_run,0)
        return {**result,'created_project_id':target.project_id,'source_run_id':run_id}

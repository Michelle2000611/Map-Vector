"""Persistent background exports with process ownership and fixed snapshot input."""
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4

from mapvector.domain.errors import CommandConflict
from mapvector.domain.ports import get_ports
from mapvector.application.ports import ProjectDatabase
from mapvector.application.ports import atomic_json
from mapvector.application.ports import run_process,worker_is_alive

EXECUTOR=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mapvector-export')
OWNER_ID=str(uuid4());ACTIVE=set();LOCK=threading.RLock()
TERMINAL={'completed','failed','cancelled','interrupted'}
def now():return datetime.now(timezone.utc).isoformat()


class ExportJobService:
    def __init__(self,project_dir,executor=None):
        self.project_dir=Path(project_dir).resolve();self.database=ProjectDatabase(self.project_dir/'state/project.sqlite');self.executor=executor or EXECUTOR
        self.recover()

    def start(self,project_id,payload):
        export_id=str(uuid4())
        with self.database.transaction() as connection:
            snapshot=connection.execute("SELECT s.*,a.coordinate_mode FROM snapshot s JOIN asset a USING(asset_id) WHERE s.project_id=? AND s.snapshot_id=? AND s.snapshot_status='committed'",(project_id,payload['snapshot_id'])).fetchone()
            if snapshot is None:raise CommandConflict('SNAPSHOT_NOT_FOUND')
            values={'export_id':export_id,'project_id':project_id,'asset_id':snapshot['asset_id'],'snapshot_id':payload['snapshot_id'],'export_format':payload['export_format'],'export_mode':payload['export_mode'],'roi_id':payload['roi_id'],'scope_mode':payload['scope_mode'],'coordinate_mode':snapshot['coordinate_mode'],'policy_snapshot':json.dumps({'policy_id':payload['policy_id']}),'export_status':'queued','created_at':now(),'layer_types':json.dumps(payload['layer_types']),'payload_snapshot':json.dumps(payload),'worker_owner_id':OWNER_ID,'stage_name':'queued'}
            connection.execute('INSERT INTO export ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
        self.schedule(project_id,export_id)
        return {'export_id':export_id,'export_status':'queued','snapshot_id':payload['snapshot_id']}

    def schedule(self,project_id,export_id):
        key=(str(self.database.path),export_id)
        with LOCK:
            if key in ACTIVE:return
            ACTIVE.add(key)
        try:self.executor.submit(self.execute,project_id,export_id)
        except BaseException:
            with LOCK:ACTIVE.discard(key)
            raise

    def get(self,project_id,export_id):
        with self.database.read() as connection:row=connection.execute('SELECT * FROM export WHERE project_id=? AND export_id=?',(project_id,export_id)).fetchone()
        if row is None:raise KeyError(export_id)
        value=dict(row);start=value['started_at'] or value['created_at'];end=value['finished_at'] or now()
        value['elapsed_ms']=max(0,int((datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()*1000))
        return value

    def cancel(self,project_id,export_id):
        with self.database.transaction() as connection:
            row=connection.execute('SELECT * FROM export WHERE project_id=? AND export_id=?',(project_id,export_id)).fetchone()
            if row is None:raise KeyError(export_id)
            if row['export_status'] not in TERMINAL:
                status='cancelled' if row['export_status']=='queued' else 'cancelling'
                connection.execute('UPDATE export SET cancel_requested=1,export_status=?,finished_at=? WHERE export_id=?',(status,now() if status=='cancelled' else None,export_id))
        return self.get(project_id,export_id)

    def recover(self):
        queued=[]
        with self.database.transaction() as connection:
            for row in connection.execute("SELECT * FROM export WHERE export_status IN ('queued','running','cancelling')").fetchall():
                key=(str(self.database.path),row['export_id'])
                with LOCK:active=key in ACTIVE and row['worker_owner_id']==OWNER_ID
                if active:continue
                if row['export_status']=='queued':queued.append((row['project_id'],row['export_id']));continue
                if worker_is_alive(row['worker_pid'],row['export_id']):continue
                connection.execute("UPDATE export SET export_status=?,error_code='SERVICE_RESTART',finished_at=?,worker_pid=NULL WHERE export_id=?",('cancelled' if row['cancel_requested'] else 'interrupted',now(),row['export_id']))
        for project_id,export_id in queued:self.schedule(project_id,export_id)

    def execute(self,project_id,export_id):
        key=(str(self.database.path),export_id);work=self.project_dir/'exports'/export_id
        try:
            with self.database.transaction() as connection:
                row=connection.execute('SELECT * FROM export WHERE project_id=? AND export_id=?',(project_id,export_id)).fetchone()
                if row is None or row['export_status']!='queued' or row['cancel_requested']:return
                connection.execute("UPDATE export SET export_status='running',stage_name='write_and_readback',started_at=?,heartbeat_at=?,worker_owner_id=? WHERE export_id=?",(now(),now(),OWNER_ID,export_id))
            work.mkdir(parents=True,exist_ok=True);atomic_json(work/'request.json',json.loads(row['payload_snapshot']))
            environment=get_ports().workers.environment(Path(__file__).resolve().parents[4])
            def started(process):
                with self.database.transaction() as connection:connection.execute('UPDATE export SET worker_pid=? WHERE export_id=?',(process.pid,export_id))
            def heartbeat():
                with self.database.transaction() as connection:connection.execute('UPDATE export SET heartbeat_at=? WHERE export_id=?',(now(),export_id))
            def cancelled():return bool(self.get(project_id,export_id)['cancel_requested'])
            run_process(get_ports().workers.export_arguments(sys.executable,self.project_dir,project_id,export_id),work,environment,started,heartbeat,cancelled,3600,'EXPORT_TIMEOUT')
            if self.get(project_id,export_id)['export_status']!='completed':raise CommandConflict('EXPORT_WORKER_INCOMPLETE')
        except Exception as exc:
            code=exc.code if isinstance(exc,CommandConflict) else 'EXPORT_FAILED'
            with self.database.transaction() as connection:
                current=connection.execute('SELECT export_status,cancel_requested FROM export WHERE export_id=?',(export_id,)).fetchone()
                if current and current['export_status']!='completed':
                    status='cancelled' if current['cancel_requested'] or code=='RUN_CANCELLED' else 'failed'
                    detail=exc.detail if isinstance(exc,CommandConflict) else {'reason':str(exc)}
                    fault=work/'fault.json'
                    if fault.is_file():detail=json.loads(fault.read_text(encoding='utf-8'));code=detail.get('code',code)
                    connection.execute('UPDATE export SET export_status=?,stage_name=?,error_code=?,error_detail=?,finished_at=?,worker_pid=NULL WHERE export_id=?',(status,status,code,json.dumps(detail),now(),export_id))
        finally:
            with LOCK:ACTIVE.discard(key)
            with self.database.transaction() as connection:connection.execute('UPDATE export SET worker_pid=NULL WHERE export_id=?',(export_id,))

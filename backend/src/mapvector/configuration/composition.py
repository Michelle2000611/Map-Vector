"""Composition root. Concrete implementations are imported only at their boundaries."""
from mapvector.domain.ports import RuntimePorts,configure_ports
from contextlib import contextmanager

class Archives:
    @property
    def operational_error(self):
        import sqlite3
        return sqlite3.OperationalError
    @contextmanager
    def open(self,path):
        import sqlite3
        connection=sqlite3.connect(path);connection.row_factory=sqlite3.Row
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback();raise
        finally:connection.close()
    def backup(self,source,target):source.backup(target)

class Features:
    def load(self,*args):
        from mapvector.infrastructure.repositories.feature import load_feature
        return load_feature(*args)
    def restore(self,*args):
        from mapvector.infrastructure.repositories.feature import restore_feature
        return restore_feature(*args)
    def update_index(self,*args):
        from mapvector.infrastructure.repositories.feature import update_index
        return update_index(*args)

class Files:
    def sha256(self,*args):
        from mapvector.infrastructure.storage.files import sha256_file
        return sha256_file(*args)
    def atomic_bytes(self,*args):
        from mapvector.infrastructure.storage.files import atomic_bytes
        return atomic_bytes(*args)
    def atomic_json(self,*args):
        from mapvector.infrastructure.storage.files import atomic_json
        return atomic_json(*args)

class Raster:
    max_bytes=500*1024*1024
    def probe(self,*args):
        from mapvector.infrastructure.storage.raster import probe
        return probe(*args)
    def sniff(self,*args):
        from mapvector.infrastructure.storage.raster import sniff
        return sniff(*args)
    def decode(self,*args):
        from mapvector.infrastructure.storage.raster import decode
        return decode(*args)

class Editor:
    face_layer='colour_faces';line_layer='visual_lines'
    @property
    def error_type(self):
        from mapvector.algorithms.legacy_editor.core import EditError
        return EditError
    def document(self,*args,**kwargs):
        from mapvector.algorithms.adapters.editor import document
        return document(*args,**kwargs)
    def apply(self,*args,**kwargs):
        from mapvector.algorithms.adapters.editor import apply
        return apply(*args,**kwargs)
    def render_frames(self,*args,**kwargs):
        from mapvector.algorithms.legacy_editor.render import render_frames
        return render_frames(*args,**kwargs)
    def render(self,*args,**kwargs):
        from mapvector.algorithms.legacy_editor.render import render
        return render(*args,**kwargs)
    def residual(self,*args,**kwargs):
        from mapvector.algorithms.legacy_editor.render import residual
        return residual(*args,**kwargs)
    def png_bytes(self,*args,**kwargs):
        from mapvector.algorithms.legacy_editor.render import png_bytes
        return png_bytes(*args,**kwargs)

class Workers:
    def environment(self,project_root):
        import os
        environment=os.environ.copy();environment.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True')
        environment['PYTHONPATH']=str(self.source_root().parent)
        for key,relative in {'TEMP':'runtime/temp','TMP':'runtime/temp','TMPDIR':'runtime/temp','PADDLE_PDX_CACHE_HOME':'.venv/cache/paddle','HF_HOME':'.venv/cache/huggingface','XDG_CACHE_HOME':'.venv/cache'}.items():
            path=project_root/relative;path.mkdir(parents=True,exist_ok=True);environment[key]=str(path)
        return environment
    def source_root(self):
        from pathlib import Path
        return Path(__file__).resolve().parents[1]
    def pinned_algorithm_paths(self):
        root=self.source_root();paths=sorted((root/'algorithms/legacy_b2c').glob('*.py'))
        paths+=sorted((root/'algorithms/legacy_b2c/resources').glob('*.json'))
        paths+=[root/'algorithms/adapters'/name for name in ('rapid.py','paddle.py','text_rules.py')]
        return paths+[root/'algorithms/ocr_worker.py',root/'algorithms/vector_worker.py',root/'algorithms/line_recovery.py',root/'algorithms/text_ink_mask.py',root/'geometry/raster_mask.py',root/'geometry/text.py',root/'application/ocr_fusion.py']
    def package_versions(self,python,packages):
        import subprocess,json,os
        program="import importlib.metadata as m,json,sys;print(json.dumps({n:m.version(n) for n in sys.argv[1:]}))"
        environment=os.environ.copy();environment['PYTHONUTF8']='1'
        result=subprocess.run([python,'-X','utf8','-c',program,*packages],capture_output=True,text=True,encoding='utf-8',timeout=20,env=environment)
        if result.returncode:raise RuntimeError('Required worker distribution unavailable: '+result.stderr[-1500:])
        return json.loads(result.stdout)
    def export_arguments(self,python,project_dir,project_id,export_id):return [python,'-X','utf8','-m','mapvector.infrastructure.workers.export_worker',str(project_dir),project_id,export_id]
    def vector_arguments(self,python,raster,output):return [python,'-X','utf8','-m','mapvector.algorithms.vector_worker',str(raster),str(output)]
    def ocr_arguments(self,python,raster,output,model,engine):return [python,'-X','utf8','-m','mapvector.algorithms.ocr_worker',str(raster),str(output),str(model),'--engine',engine]
    def run(self,*args,**kwargs):
        from mapvector.infrastructure.workers.process import run_process
        return run_process(*args,**kwargs)
    def is_alive(self,*args):
        from mapvector.infrastructure.workers.process import worker_is_alive
        return worker_is_alive(*args)

def database(path):
    from mapvector.infrastructure.repositories.database import ProjectDatabase
    return ProjectDatabase(path)
def catalog(path):
    from mapvector.infrastructure.repositories.project import ProjectRepository
    return ProjectRepository(path)
def write_gis(*args,**kwargs):
    from mapvector.infrastructure.storage.gis import write_gis as writer
    return writer(*args,**kwargs)
def compose():
    ports=RuntimePorts(database,Features(),Files(),Raster(),Editor(),Workers(),catalog,write_gis,Archives())
    configure_ports(ports)
    return ports

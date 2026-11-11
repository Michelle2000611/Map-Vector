import os
from pathlib import Path
from threadpoolctl import threadpool_limits


def configure_runtime(project_root:Path):
    folders={'TEMP':'runtime/temp','TMP':'runtime/temp','TMPDIR':'runtime/temp','XDG_CACHE_HOME':'.venv/cache','HF_HOME':'.venv/cache/huggingface','PADDLE_PDX_CACHE_HOME':'.venv/cache/paddle','MPLCONFIGDIR':'.venv/cache/matplotlib'}
    for name,relative in folders.items():
        path=project_root/relative;path.mkdir(parents=True,exist_ok=True);os.environ[name]=str(path)
    os.environ['PYTHONUTF8']='1';os.environ['PYTHONIOENCODING']='utf-8'
    threadpool_limits(limits=1,user_api='blas')

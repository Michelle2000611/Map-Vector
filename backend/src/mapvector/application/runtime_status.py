import importlib.util
import json
import os
from pathlib import Path
from mapvector.application.ports import sha256_file
from mapvector.domain.ports import get_ports
from functools import lru_cache

@lru_cache(maxsize=8)
def worker_versions(interpreter,stamp):return get_ports().workers.package_versions(interpreter,['paddlepaddle','paddleocr','paddlex','numpy'])


def plugin_status(root:Path):
    missing=[name for name in ('cv2','scipy','skimage','rasterio','pyogrio') if importlib.util.find_spec(name) is None]
    statuses={'b2c':{'plugin_id':'b2c','available':not missing,'pipeline_revision':'1.0','reason_code':'RUNTIME_DEPENDENCY_MISSING' if missing else None,'missing_dependencies':missing}}
    for engine,package in [('rapid','rapidocr'),('paddle','paddleocr')]:
        path=root/'models'/engine/'manifest.json';problems=[]
        if not path.is_file():problems.append('manifest.json')
        else:
            try:
                manifest=json.loads(path.read_text(encoding='utf-8'))
                for item in manifest['files']:
                    file=path.parent/item['rel_path']
                    if not file.is_file() or sha256_file(file)!=item['sha256']:problems.append(item['rel_path'])
            except (OSError,ValueError,KeyError):problems.append('manifest.json invalid')
        if engine=='rapid' and (importlib.util.find_spec('rapidocr') is None or importlib.util.find_spec('onnxruntime') is None):problems.append('rapidocr/onnxruntime')
        interpreter=root/('.venv-ocr-paddle/Scripts/python.exe' if os.name=='nt' else '.venv-ocr-paddle/bin/python')
        if engine=='paddle' and not interpreter.is_file():problems.append(str(interpreter.relative_to(root)))
        versions={}
        if engine=='paddle' and interpreter.is_file():
            try:versions=worker_versions(str(interpreter),interpreter.stat().st_mtime_ns)
            except Exception:problems.append('paddlepaddle/paddleocr/paddlex/numpy')
        statuses[engine]={'plugin_id':package,'available':not problems,'reason_code':'OCR_ENGINE_UNAVAILABLE' if problems else None,'missing_or_invalid':problems,'runtime_packages':versions}
    return statuses

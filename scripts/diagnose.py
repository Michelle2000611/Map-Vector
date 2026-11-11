import importlib.util,json,socket,sys
from importlib.metadata import version,PackageNotFoundError
from pathlib import Path
from mapvector.configuration.settings import Settings
from mapvector.infrastructure.storage.files import sha256_file

root=Settings().project_root;dependencies={}
for name in ['map-vector','fastapi','pydantic','numpy','shapely','rasterio','pyogrio','rapidocr','onnxruntime','psutil']:
    try:dependencies[name]=version(name)
    except PackageNotFoundError:dependencies[name]=None
models={}
for engine in ('rapid','paddle'):
    manifest_path=root/'models'/engine/'manifest.json'
    if not manifest_path.is_file():models[engine]={'available':False,'missing':['manifest.json']};continue
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'));missing=[item['rel_path'] for item in manifest['files'] if not (manifest_path.parent/item['rel_path']).is_file() or sha256_file(manifest_path.parent/item['rel_path'])!=item['sha256']]
    models[engine]={'available':not missing,'missing_or_invalid':missing,'model_id':manifest['model_id']}
with socket.socket() as probe:
    try:probe.bind(('127.0.0.1',8840));port='available'
    except OSError:port='in_use'
print(json.dumps({'python':sys.executable,'python_version':sys.version,'project_root':str(root),'workspace':str(Settings().workspace),'api_port_8840':port,'dependencies':dependencies,'models':models,'frontend_built':(root/'frontend/dist/index.html').is_file()},ensure_ascii=False,indent=2))

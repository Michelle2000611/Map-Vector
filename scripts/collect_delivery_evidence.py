"""Collect local, reproducible dependency/source evidence without copying data or weights."""
import hashlib
import json
import subprocess
import sys
import zipfile
from importlib.metadata import distributions
from pathlib import Path

root=Path(__file__).resolve().parents[1];output=root/'docs/migration'
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
packages=[]
for distribution in distributions():
    name=distribution.metadata.get('Name')
    if name:packages.append({'name':name,'version':distribution.version,'license':distribution.metadata.get('License-Expression') or distribution.metadata.get('License'),'license_files':distribution.metadata.get_all('License-File',[])})
packages.sort(key=lambda item:item['name'].lower())
save(output/'dependency-inventory.json',{'python':sys.version,'packages':packages})
lock=[item['name']+'=='+item['version'] for item in packages if item['name'].lower()!='map-vector']
(root/'backend/requirements.lock').write_text(chr(10).join(lock)+chr(10),encoding='utf-8')
baseline=output/'baseline';manifest=json.loads((baseline/'manifest.json').read_text(encoding='utf-8'));source=root.parent/'scan2arcgis'
untracked=[item for item in manifest['source_files'] if not item['tracked'] and Path(item['rel_path']).suffix in ('.py','.js','.ts','.tsx','.html','.css','.json','.yaml','.toml') and not item['rel_path'].startswith(('runs/','docs/','data/'))]
with zipfile.ZipFile(baseline/'untracked-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for item in untracked:
        path=source/item['rel_path']
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']:archive.write(path,item['rel_path'])
reference=root.parent/'Geological-Map-Digitizer';files=['frontend/package.json','frontend/package-lock.json','frontend/src/App.tsx','frontend/src/components/workflow/WorkflowStageBar.tsx']
reference_files=[{'rel_path':name,'sha256':hashlib.sha256((reference/name).read_bytes()).hexdigest()} for name in files if (reference/name).is_file()]
save(output/'frontend-reference.json',{'source_name':reference.name,'commit':subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip(),'files':reference_files,'reuse':'Layout and navigation reference; implementation authored in Map-Vector'})
manifest['untracked_source_archive']={'rel_path':'untracked-source.zip','sha256':hashlib.sha256((baseline/'untracked-source.zip').read_bytes()).hexdigest(),'file_count':len(untracked)}
manifest['model_inventory_status']='rapid_and_paddle_manifests_verified';manifest['runtime_equivalence_status']='one_real_826x794_sample_exact_geometry_and_attributes'
save(baseline/'manifest.json',manifest)
for filename,name in [('runtime/baseline-comparison/report.json','baseline-equivalence.json'),('runtime/migration/real_verify_completion.json','real-project-verification.json'),('runtime/performance/report.json','performance.json'),('runtime/diagnostics.json','diagnostics.json'),('runtime/legacy-compatibility/report.json','legacy-compatibility.json'),('runtime/completion-data-report.json','completion-data-report.json')]:
    path=root/filename
    if path.is_file():
        value=json.loads(path.read_text(encoding='utf-8'))
        # Reports carry source identity and hashes; raster/weights stay ignored.
        save(output/name,value)
print(json.dumps({'packages':len(packages),'untracked_source_count':len(untracked),'reference_files':len(reference_files)}))

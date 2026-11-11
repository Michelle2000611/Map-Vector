"""Write proof beside the new workspace, never into the read-only legacy project."""
import json
from pathlib import Path
from mapvector.configuration.settings import Settings
from mapvector.infrastructure.storage.files import atomic_json,sha256_file
root=Settings().project_root;source=root.parent/'scan2arcgis/runs/stitchvector/studio_v02/workspace/projects/p-20261106-003921-0933c4'
comparison=root/'runtime/baseline-comparison/report.json';run=root/'runtime/baseline-comparison/run_report.json';vectors=root/'runtime/baseline-comparison/vectors.gpkg'
result=json.loads(comparison.read_text(encoding='utf-8'));report=json.loads(run.read_text(encoding='utf-8'))
assert result['equivalent'] and report['source_sha256']==sha256_file(source/'normalized/doc-p0-d300/raster.png')
proof={'baseline_commit':'c7b74d9c9a16d1b082f0dab694cecc8dc45363f9','input_raster_sha256':report['source_sha256'],'working_sha256':sha256_file(source/'working/current.gpkg'),'equivalent':True,'checks':[{'path':str(path.resolve()),'sha256':sha256_file(path)} for path in (comparison,run,vectors)]}
atomic_json(root/'workspaces/migration_proofs'/(source.name+'.json'),proof)
print('Local proof written; source remains unchanged')

import argparse,json
from pathlib import Path
from mapvector.application.legacy_export import export_legacy

parser=argparse.ArgumentParser(description='Explicit frozen-editor compatibility output; never replaces a project database')
parser.add_argument('project',type=Path);parser.add_argument('snapshot_id');parser.add_argument('output',type=Path)
parser.add_argument('--formal',action='store_true');parser.add_argument('--scope',choices=['full','keep_crossing','clip'],default='full')
args=parser.parse_args();result=export_legacy(args.project,args.snapshot_id,args.output,not args.formal,args.scope)
print(json.dumps(result,ensure_ascii=False,indent=2))

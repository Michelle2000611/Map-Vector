import argparse,json
from pathlib import Path
from mapvector.application.backup import backup_project,restore_backup

parser=argparse.ArgumentParser();parser.add_argument('action',choices=['create','restore']);parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path);args=parser.parse_args()
result=backup_project(args.source,args.destination) if args.action=='create' else restore_backup(args.source,args.destination)
print(json.dumps(result,ensure_ascii=False,indent=2))

"""Scan/dry-run/import/verify/report legacy project copies without modifying source."""
import argparse,json,sys,sqlite3
from pathlib import Path
from mapvector.application.migration import scan,import_project
from mapvector.configuration.settings import Settings
from mapvector.infrastructure.storage.files import atomic_json


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['scan','dry-run','import','verify','report']);parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--workspace',type=Path,default=Settings().workspace);args=parser.parse_args()
    if args.action in ('verify','report'):
        path=args.source/'migration/report.json';result=json.loads(path.read_text(encoding='utf-8'))
        if args.action=='verify':
            from mapvector.application.migration_verify import verify_import
            result['readback_report']=verify_import(args.source)
    else:result=import_project(args.source,args.workspace) if args.action=='import' else scan(args.source)
    if args.output:atomic_json(args.output,result)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result.get('import_status') in ('committed','validated') else 2


if __name__=='__main__':raise SystemExit(main())

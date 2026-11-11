import argparse,json
from pathlib import Path
from mapvector.infrastructure.storage.legacy_compare import compare_vector_layers
from mapvector.infrastructure.storage.files import atomic_json
parser=argparse.ArgumentParser();parser.add_argument('baseline',type=Path);parser.add_argument('current',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();report=compare_vector_layers(args.baseline,args.current);atomic_json(args.output,report);print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report['equivalent'] else 2)

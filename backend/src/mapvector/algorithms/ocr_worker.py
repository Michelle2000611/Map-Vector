import argparse
from pathlib import Path

import json,os


def main():
    parser=argparse.ArgumentParser();parser.add_argument('raster',type=Path);parser.add_argument('output',type=Path);parser.add_argument('model_dir',type=Path);parser.add_argument('--region',nargs=4,type=float);parser.add_argument('--engine',choices=['rapid','paddle'],default='rapid')
    args=parser.parse_args()
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'
    if args.engine=='rapid':
        from mapvector.algorithms.adapters.rapid import recognize
    else:
        from mapvector.algorithms.adapters.paddle import recognize
    result=recognize(args.raster,args.model_dir,args.region)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary=args.output.with_suffix('.tmp');content=json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
    with temporary.open('wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
    temporary.replace(args.output)


if __name__=='__main__':main()

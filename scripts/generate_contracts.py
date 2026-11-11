"""Deterministic OpenAPI snapshot from Pydantic; frontend types use openapi-typescript."""
import argparse,json,tempfile
from pathlib import Path
from mapvector.api.app import create_app
from mapvector.configuration.settings import Settings


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'contracts/openapi.json');args=parser.parse_args()
    temporary_root=Path(__file__).resolve().parents[1]/'runtime/temp';temporary_root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mapvector-contract-',dir=temporary_root) as directory:
        schema=create_app(Settings(project_root=Path(directory))).openapi()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(schema,ensure_ascii=False,indent=2,sort_keys=True),encoding='utf-8')
    print(str(args.output))


if __name__=='__main__':main()

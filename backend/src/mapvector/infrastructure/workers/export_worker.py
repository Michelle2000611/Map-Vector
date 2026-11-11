"""Owned subprocess entry for an immutable export request."""
import json
import sys
from pathlib import Path
from mapvector.application.exports import ExportService
from mapvector.domain.errors import CommandConflict
from mapvector.infrastructure.storage.files import atomic_json

def main():
    directory=Path(sys.argv[1]);project_id=sys.argv[2];export_id=sys.argv[3];work=directory/'exports'/export_id
    try:
        request=json.loads((work/'request.json').read_text(encoding='utf-8'))
        result=ExportService(directory).create(project_id,request,export_id=export_id)
        atomic_json(work/'manifest.json',result)
        return 0
    except Exception as exc:
        atomic_json(work/'fault.json',{'code':exc.code if isinstance(exc,CommandConflict) else 'EXPORT_FAILED','detail':exc.detail if isinstance(exc,CommandConflict) else {'reason':str(exc)}})
        return 1

if __name__=='__main__':raise SystemExit(main())

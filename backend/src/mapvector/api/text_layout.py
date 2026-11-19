"""Read-only layout repair preview and the font used by layout measurements."""
import hashlib
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from fastapi import Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from mapvector.application.text_layout import repair_preview
from mapvector.geometry.text import layout_font
from mapvector.infrastructure.repositories.database import ProjectDatabase


class TextLayoutPreviewRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    asset_id:UUID
    base_revision:int=Field(ge=0,strict=True)


@lru_cache(maxsize=1)
def measured_font():
    font,_=layout_font()
    data=Path(font.path).read_bytes()
    return data,'"'+hashlib.sha256(data).hexdigest()+'"'


def register(app,project_directory,envelope):
    @app.get('/api/text-layout/font',include_in_schema=False)
    def text_font(request:Request):
        data,etag=measured_font()
        headers={'ETag':etag,'Cache-Control':'private, max-age=0, must-revalidate'}
        if request.headers.get('if-none-match')==etag:return Response(status_code=304,headers=headers)
        return Response(content=data,media_type='font/collection' if data[:4]==b'ttcf' else 'font/ttf',headers=headers)

    @app.post('/api/projects/{project_id}/text-layout-previews')
    def preview(project_id:UUID,body:TextLayoutPreviewRequest,request:Request):
        directory=project_directory(str(project_id))
        with ProjectDatabase(directory/'state/project.sqlite').read() as connection:
            connection.execute('BEGIN')
            result,_,_=repair_preview(connection,str(project_id),str(body.asset_id),body.base_revision,directory)
        return envelope(request,result)

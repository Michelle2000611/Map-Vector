from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from xml.etree import ElementTree as ET

root=Path(__file__).resolve().parents[1];folder=root/'20261106'
for name in ('Map-Vector_新项目迁移技术设计.md','迁移设计内容.json'):
    path=folder/name;data=path.read_text(encoding='utf-8')
    data=data.replace('.venv-ocr-rapid/Scripts/python.exe','.venv/Scripts/python.exe').replace('.venv-ocr-rapid/','# RapidOCR shares .venv')
    path.write_text(data,encoding='utf-8')
path=folder/'Map-Vector_新项目迁移技术设计.docx'
with ZipFile(path) as archive:parts={name:archive.read(name) for name in archive.namelist()}
xml=parts['word/document.xml'].decode('utf-8')
xml=xml.replace('.venv-ocr-rapid/Scripts/python.exe','.venv/Scripts/python.exe').replace('.venv-ocr-rapid/','# RapidOCR shares .venv')
parts['word/document.xml']=xml.encode('utf-8')
temporary=path.with_suffix('.tmp.docx')
with ZipFile(temporary,'w',ZIP_DEFLATED) as archive:
    for name,data in parts.items():archive.writestr(name,data)
temporary.replace(path)
with ZipFile(path) as archive:
    text=''.join(ET.fromstring(archive.read('word/document.xml')).itertext())
    assert '.venv-api' not in text and '.venv-ocr-rapid' not in text
assert '.venv-api' not in (folder/'Map-Vector_新项目迁移技术设计.md').read_text(encoding='utf-8')
print('Environment paths synchronized across DOCX, Markdown and JSON')

"""Same RapidOCR scales and filters as frozen plugin, with explicit local weights."""
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
from PIL import Image

from mapvector.application.commands import CommandConflict
from mapvector.infrastructure.storage.files import sha256_file


def recognize(raster:Path,model_dir:Path,region=None):
    manifest_path=model_dir/'manifest.json'
    if not manifest_path.is_file():raise CommandConflict('OCR_ENGINE_UNAVAILABLE',{'model_manifest':str(manifest_path)})
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    for item in manifest['files']:
        path=model_dir/item['rel_path']
        if not path.is_file() or sha256_file(path)!=item['sha256']:
            raise CommandConflict('MODEL_HASH_MISMATCH',{'file':item['rel_path']})
    from rapidocr import RapidOCR
    params={'Det.model_path':str(model_dir/'ch_PP-OCRv4_det_infer.onnx'),'Rec.model_path':str(model_dir/'ch_PP-OCRv4_rec_infer.onnx'),'Cls.model_path':str(model_dir/'ch_ppocr_mobile_v2.0_cls_infer.onnx'),'Rec.rec_keys_path':str(model_dir/'ppocr_keys_v1.txt')}
    engine=RapidOCR(params=params)
    with Image.open(raster) as original:
        image=original.convert('RGB')
    origin=(0.,0.)
    if region:
        x0,y0,x1,y1=region
        if not 0<=x0<x1<=image.width or not 0<=y0<y1<=image.height:raise CommandConflict('OCR_REGION_INVALID')
        origin=(int(x0),int(y0));image=image.crop((int(x0),int(y0),int(x1),int(y1)))
    items=[]
    for scale in (1,2):
        result=engine(np.asarray(image.resize((image.width*scale,image.height*scale),Image.Resampling.LANCZOS)))
        for quad,text,score in zip(result.boxes if result.boxes is not None else [],result.txts or [],result.scores or []):
            if float(score)<0:continue
            points=(np.asarray(quad,dtype=float)/scale).round(1)
            points+=np.asarray(origin)
            items.append({'raw_text':str(text),'score':round(float(score),3),'detected_quad_px':points.tolist(),'engine_id':'rapidocr','model_id':'PP-OCRv4','scale':scale,'rule_suggestions':[]})
    return {'schema_revision':'1.0','engine_id':'rapidocr','engine_version':version('rapidocr'),'model_id':'PP-OCRv4','region_px':region,'items':items}

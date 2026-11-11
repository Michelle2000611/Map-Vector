"""Frozen Paddle plugin algorithm; explicit local model paths and CPU settings."""
import json
import hashlib
import sys
from importlib.metadata import version
from pathlib import Path


def iou(a,b):
    ax0,ay0,ax1,ay1=a;bx0,by0,bx1,by1=b
    inter=max(0,min(ax1,bx1)-max(ax0,bx0))*max(0,min(ay1,by1)-max(ay0,by0))
    union=(ax1-ax0)*(ay1-ay0)+(bx1-bx0)*(by1-by0)-inter
    return inter/union if union>0 else 0.


def recognize(raster:Path,model_dir:Path,region=None):
    manifest=json.loads((model_dir/'manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path=model_dir/item['rel_path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('MODEL_HASH_MISMATCH: '+item['rel_path'])
    import numpy as np
    from PIL import Image
    from paddleocr import PaddleOCR
    if __package__:
        from .text_rules import suggest,RULES_VERSION
    else:
        from text_rules import suggest,RULES_VERSION
    options={'enable_mkldnn':False} if sys.platform=='win32' else {}
    engine=PaddleOCR(lang='ch',use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=True,device='cpu',text_detection_model_name='PP-OCRv6_medium_det',text_detection_model_dir=str(model_dir/'PP-OCRv6_medium_det'),text_recognition_model_name='PP-OCRv6_medium_rec',text_recognition_model_dir=str(model_dir/'PP-OCRv6_medium_rec'),textline_orientation_model_name='PP-LCNet_x1_0_textline_ori',textline_orientation_model_dir=str(model_dir/'PP-LCNet_x1_0_textline_ori'),**options)
    with Image.open(raster) as source:image=source.convert('RGB')
    origin=(0,0)
    if region:
        x0,y0,x1,y1=region
        if not(0<=x0<x1<=image.width and 0<=y0<y1<=image.height):raise ValueError('OCR_REGION_INVALID')
        origin=(int(x0),int(y0));image=image.crop(tuple(int(x) for x in region))
    raw=[]
    for scale in (1,2):
        pixels=np.asarray(image if scale==1 else image.resize((image.width*scale,image.height*scale),Image.Resampling.LANCZOS))[:,:,::-1].copy()
        prediction=list(engine.predict(pixels))[0]
        for quad,text,score in zip(prediction['rec_polys'],prediction['rec_texts'],prediction['rec_scores']):
            if not str(text).strip() or float(score)<0:continue
            points=(np.asarray(quad,float)/scale).round(1);points+=np.asarray(origin)
            xs=points[:,0];ys=points[:,1]
            raw.append({'quad':points.tolist(),'bbox':[float(xs.min()),float(ys.min()),float(xs.max()),float(ys.max())],'text':str(text),'score':round(float(score),3),'scale':scale})
    # Preserve both scale readings, including disagreements. The shared
    # registration/fusion step deduplicates exact text and retains provenance.
    items=[]
    for record in sorted(raw,key=lambda item:(item['bbox'][1],item['bbox'][0])):
        suggested,values,reasons=suggest(record['text'])
        items.append({'raw_text':record['text'],'suggested_text':suggested,'score':record['score'],'detected_quad_px':record['quad'],'engine_id':'paddleocr','model_id':manifest['model_id'],'rule_suggestions':[{'candidate_texts':values,'reason_codes':reasons}],'scale':record['scale']})
    return {'schema_revision':'1.0','engine_id':'paddleocr','engine_version':version('paddleocr'),'model_id':manifest['model_id'],'rules_revision':RULES_VERSION,'raw_detection_count':len(raw),'region_px':region,'items':items}


if __name__=='__main__':
    import argparse,os
    parser=argparse.ArgumentParser();parser.add_argument('raster',type=Path);parser.add_argument('output',type=Path);parser.add_argument('model_dir',type=Path);parser.add_argument('--region',nargs=4,type=float)
    args=parser.parse_args();result=recognize(args.raster,args.model_dir,args.region)
    args.output.parent.mkdir(parents=True,exist_ok=True);temporary=args.output.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    temporary.replace(args.output)

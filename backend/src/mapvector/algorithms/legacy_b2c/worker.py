"""Worker entry point calling the frozen U2 B2c pipeline functions."""
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import sv_lf as LF
from . import sv_d71 as D
from . import sv_oracle as O
from . import vector_writer as O2
from .full_build import line_objects


def main(arguments=None):
    source,output=map(Path,arguments or sys.argv[1:3])
    started=time.monotonic()
    image=np.asarray(Image.open(source).convert('RGB'))
    shape=image.shape[:2]
    log={'multipart_split':[]}
    labels,palette=LF.labels(image)
    raw,lines=line_objects(image,log)
    footprint=LF.footprint(lines,shape,LF.Q['halo'])
    face_image=D.fill(labels,footprint)
    faces=O.faces(face_image,LF.Q['tol'])
    observed,inferred=O.provenance(face_image,footprint,faces)
    output.parent.mkdir(parents=True,exist_ok=True)
    O2.write(output,faces,palette,np.arange(len(palette)),observed,inferred,lines,[])
    report={'source_sha256':__import__('hashlib').sha256(source.read_bytes()).hexdigest(),'width_px':image.shape[1],'height_px':image.shape[0],'faces':len(faces['polys']),'lines':len(lines),'b2c_objects':len(raw),'colour_classes':len(palette),'multipart_split':log['multipart_split'],'elapsed_seconds':round(time.monotonic()-started,3),'algorithm':'frozen B2c baseline','pipeline_revision':'1.0'}
    report_path=output.with_name('run_report.json')
    report_path.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,allow_nan=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())

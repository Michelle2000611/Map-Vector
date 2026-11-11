"""Migrated worker wrapper; frozen baseline functions remain unchanged."""
import json,sys,hashlib
from pathlib import Path
import geopandas as gpd
import numpy as np
from PIL import Image
from mapvector.geometry.raster_mask import valid_region,white_rgb
from mapvector.algorithms.legacy_b2c.worker import main as baseline


def main(arguments=None):
    source,output=map(Path,arguments or sys.argv[1:3])
    output.parent.mkdir(parents=True,exist_ok=True)
    with Image.open(source) as image:
        masked='A' in image.getbands()
        display=output.with_name('display-input.png')
        if masked:white_rgb(image).save(display)
    input_path=display if masked else source
    baseline([input_path,output])
    from mapvector.algorithms.line_recovery import recover_lines,normalize_groups
    from mapvector.algorithms.text_ink_mask import suppress_text_ink
    from mapvector.algorithms.legacy_b2c import sv_lf as LF,sv_d71 as D,sv_oracle as O,vector_writer as writer
    from mapvector.algorithms.legacy_b2c.full_build import line_objects
    with Image.open(input_path) as image:rgb=np.asarray(image.convert('RGB'))
    ocr_path=output.with_name('ocr_candidates.json')
    rgb,erased=suppress_text_ink(rgb,json.loads(ocr_path.read_text('utf-8'))['items']) if ocr_path.is_file() else (rgb,0)
    _,lines=line_objects(rgb,{'multipart_split':[]})
    recovered=recover_lines(rgb,lines)
    if recovered or erased:
        # Keep the unmodified frozen output beside the enhanced, explicitly versioned result.
        import shutil
        shutil.copyfile(output,output.with_name('baseline-vector_layers.gpkg'))
        lines+=recovered
        normalize_groups(lines)
        labels,palette=LF.labels(rgb);footprint=LF.footprint(lines,rgb.shape[:2],LF.Q['halo'])
        filled=D.fill(labels,footprint);faces=O.faces(filled,LF.Q['tol'])
        observed,inferred=O.provenance(filled,footprint,faces)
        writer.write(output,faces,palette,np.arange(len(palette)),observed,inferred,lines,[])
    region=valid_region(source)
    if masked:
        frames=[]
        for name in gpd.list_layers(output)['name']:
            frame=gpd.read_file(output,layer=name)
            frame.geometry=frame.geometry.intersection(region)
            frame=frame[~frame.geometry.is_empty].explode(index_parts=False,ignore_index=True)
            if name=='colour_faces':
                frame=frame[frame.geometry.geom_type=='Polygon'].copy()
                frame['observed_px']=frame.geometry.area;frame['inferred_px']=0
            else:frame=frame[frame.geometry.geom_type.isin(['LineString','Polygon'])]
            frames.append((name,frame))
        temporary=output.with_name('masked-vectors.gpkg')
        for name,frame in frames:frame.to_file(temporary,layer=name,driver='GPKG',engine='pyogrio')
        temporary.replace(output)
        display.unlink(missing_ok=True)
    report_path=output.with_name('run_report.json')
    report=json.loads(report_path.read_text('utf-8'))
    frame=gpd.read_file(output,layer='colour_faces')
    report.update(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),faces=len(frame),lines=len(lines),recovered_lines=len(recovered),suppressed_text_ink_pixels=erased,valid_area_px2=region.area,mask_applied=masked,postprocess_revision='valid_region_lines_text_v2')
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    return 0


if __name__=='__main__':raise SystemExit(main())

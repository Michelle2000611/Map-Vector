"""Same deterministic legacy pixel renderer; text glyphs intentionally excluded."""
import json
from mapvector.domain.ports import get_ports
from pathlib import Path

import numpy as np
from PIL import Image
from mapvector.domain.errors import CommandConflict
from mapvector.application.ports import ProjectDatabase
from mapvector.application.ports import load_feature
from mapvector.application.ports import document
renderer=get_ports().editor
from mapvector.application.ports import sha256_file


def render_raster(project_dir,project_id,asset_id,raster_type,threshold=None,run_id=None,layer=None):
    if layer is not None and (layer not in ('face','line','text') or raster_type!='render_compare'):
        raise CommandConflict('VALIDATION_ERROR',{'field':'layer'})
    with ProjectDatabase(project_dir/'state/project.sqlite').read() as connection:
        asset=connection.execute('SELECT * FROM asset WHERE project_id=? AND asset_id=?',(project_id,asset_id)).fetchone()
        if asset is None:raise KeyError(asset_id)
        revision=connection.execute('SELECT working_revision FROM project WHERE project_id=?',(project_id,)).fetchone()[0]
        if raster_type=='source' and threshold is None:
            path=project_dir/asset['raster_rel_path']
            if sha256_file(path)!=asset['raster_sha256']:raise CommandConflict('ASSET_RESULT_MISMATCH')
            return path.read_bytes(),revision
        features=[load_feature(connection,row[0]) for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated') ORDER BY feature_id",(project_id,asset_id))]
        from mapvector.application.previews import load_groups
        groups=load_groups(connection,project_id,asset_id)
        styles=[dict(row) for row in connection.execute('SELECT * FROM style WHERE project_id=?',(project_id,))]
        baseline=connection.execute("SELECT a.* FROM artifact a JOIN run r ON a.run_id=r.run_id WHERE a.project_id=? AND r.asset_id=? AND a.artifact_type='vector_layers' AND r.run_status IN ('completed','completed_with_warnings') ORDER BY r.started_at DESC LIMIT 1",(project_id,asset_id)).fetchone()
        if run_id is not None:
            run=connection.execute('SELECT * FROM run WHERE project_id=? AND asset_id=? AND run_id=?',(project_id,asset_id,run_id)).fetchone()
            if run is None:raise KeyError(run_id)
            if run['run_status'] not in ('completed','completed_with_warnings'):raise CommandConflict('COMPARISON_UNAVAILABLE')
            baseline=connection.execute("SELECT * FROM artifact WHERE project_id=? AND run_id=? AND artifact_type='vector_layers'",(project_id,run_id)).fetchone()
            if baseline is None:raise CommandConflict('COMPARISON_UNAVAILABLE')
        original=connection.execute("SELECT * FROM migration_import WHERE project_id=? AND import_status='committed' LIMIT 1",(project_id,)).fetchone()
    with Image.open(project_dir/asset['raster_rel_path']) as image:scan=np.asarray(image.convert('RGB'))
    def current():
        doc,_=document(features,asset['width_px'],asset['height_px'],groups=groups,styles=styles)
        return renderer.render_frames(doc.F,doc.L,None,(asset['height_px'],asset['width_px']))[0]
    def compare():
        if baseline:
            path=project_dir/baseline['artifact_rel_path']
            if sha256_file(path)!=baseline['sha256']:raise CommandConflict('ARTIFACT_HASH_MISMATCH')
        elif original:
            path=project_dir/'migration/evidence/source_vectors.gpkg'
            if not path.is_file():raise CommandConflict('COMPARISON_UNAVAILABLE')
        else:raise CommandConflict('COMPARISON_UNAVAILABLE')
        return renderer.render(path,(asset['height_px'],asset['width_px']))[0]
    if raster_type=='source':pixels=scan
    elif layer in ('face','line','text'):
        if not baseline:raise CommandConflict('COMPARISON_UNAVAILABLE')
        path=project_dir/baseline['artifact_rel_path']
        if sha256_file(path)!=baseline['sha256']:raise CommandConflict('ARTIFACT_HASH_MISMATCH')
        pixels=renderer.render(path,(asset['height_px'],asset['width_px']),faces=layer=='face',lines=layer=='line',text_boxes=layer=='text')[0]
    elif raster_type=='render_current':pixels=current()
    elif raster_type=='render_compare':pixels=compare()
    elif raster_type=='residual_scan_current':pixels=renderer.residual(scan,current())[1]
    elif raster_type=='residual_scan_compare':pixels=renderer.residual(scan,compare())[1]
    elif raster_type=='residual_compare_current':pixels=renderer.residual(compare(),current())[1]
    elif raster_type=='overlay':pixels=((scan.astype(float)+current().astype(float))/2).astype(np.uint8)
    else:raise CommandConflict('RASTER_TYPE_INVALID')
    if threshold is not None:
        if pixels.ndim!=2:raise CommandConflict('RASTER_THRESHOLD_INVALID')
        pixels=np.where(pixels>=threshold,255,0).astype(np.uint8)
    return renderer.png_bytes(pixels),revision

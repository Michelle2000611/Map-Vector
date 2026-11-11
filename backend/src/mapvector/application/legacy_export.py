"""Explicit compatibility output for the frozen editor, with loss and identity manifests."""
import json
from mapvector.domain.ports import get_ports
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from mapvector.application.snapshots import SnapshotService
from mapvector.application.ports import document
from mapvector.application.previews import load_groups
from mapvector.application.ports import load_feature
from mapvector.application.ports import atomic_json,sha256_file
from mapvector.domain.errors import CommandConflict

REVIEW={'confirmed':'OCR_CONFIRMED','manual_edited':'HUMAN_EDITED','pipeline_complete_unverified':'TEXT_LAYER_COMPLETE','auto_accepted_unverified':'AUTO_ACCEPTED_UNVERIFIED','skipped':'REVIEW_SKIPPED','required':'REVIEW_REQUIRED'}


def export_legacy(project_dir:Path,snapshot_id:str,output:Path,draft=True,scope_mode='full'):
    project_dir=project_dir.resolve();output=output.resolve()
    if output.exists():raise ValueError('Legacy output already exists; overwrite is forbidden')
    if output.suffix.lower()!='.gpkg':raise ValueError('Legacy output must be a separate .gpkg file')
    if scope_mode not in ('full','keep_crossing','clip'):raise ValueError('Invalid legacy scope mode')
    with get_ports().archives.open(project_dir/'state/project.sqlite') as connection:project_id=connection.execute('SELECT project_id FROM project').fetchone()[0]
    snapshot,directory=SnapshotService(project_dir).validate(project_id,snapshot_id)
    with get_ports().archives.open(directory/'project.sqlite') as connection:
        asset=dict(connection.execute('SELECT * FROM asset WHERE asset_id=?',(snapshot['asset_id'],)).fetchone())
        features=[load_feature(connection,row[0]) for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated') ORDER BY feature_id",(project_id,snapshot['asset_id']))]
        groups=load_groups(connection,project_id,snapshot['asset_id']);styles=[dict(row) for row in connection.execute('SELECT * FROM style WHERE project_id=?',(project_id,))]
        roi=connection.execute('SELECT geometry_wkb FROM roi WHERE asset_id=?',(snapshot['asset_id'],)).fetchone()
        candidates=[dict(row) for row in connection.execute('SELECT * FROM ocr_candidate WHERE asset_id=?',(snapshot['asset_id'],))]
        lineage=[dict(row) for row in connection.execute('SELECT l.* FROM feature_lineage l JOIN feature f ON f.feature_id=l.target_feature_id WHERE f.asset_id=?',(snapshot['asset_id'],))]
    doc,identities=document(features,asset['width_px'],asset['height_px'],groups=groups,styles=styles)
    # source identity is immutable evidence used by the frozen writer's readback verification.
    doc.src=directory/'vectors.gpkg';doc.src_sha=sha256_file(doc.src)
    if roi:
        from shapely import from_wkb
        doc.roi=from_wkb(roi[0])
    by_id={feature['feature_id']:feature for feature in features}
    for _,row in doc.T.iterrows():
        index=int(row['_eid']);feature=by_id[identities[('text',index)]];mask=doc.T['_eid']==index
        doc.T.loc[mask,'review_status']=REVIEW.get(feature['review_status'],'REVIEW_REQUIRED')
        doc.T.loc[mask,'reviewed_at']=feature['reviewed_at'] or ''
        doc.T.loc[mask,'review_actor']=feature['reviewer_id'] or ''
        doc.T.loc[mask,'review_reason']=json.dumps(feature['review_reason_codes'],ensure_ascii=False)
    output.parent.mkdir(parents=True,exist_ok=True)
    try:verification=doc.save_as(output,draft=draft,roi_mode={'full':None,'keep_crossing':'keep','clip':'clip'}[scope_mode])
    except Exception as exc:raise CommandConflict('LEGACY_EXPORT_REJECTED',{'reason':str(exc)}) from exc
    manifest={'schema_revision':'1.0','project_id':project_id,'asset_id':snapshot['asset_id'],'snapshot_id':snapshot_id,'working_revision':snapshot['working_revision'],'format':'frozen_editor_compatible_gpkg','coordinate_space':'pixel','output_sha256':sha256_file(output),'scope_mode':scope_mode,'draft':draft,'verification':verification,'identity_map':[{'legacy_layer':{'face':'colour_faces','line':'visual_lines','text':'text_labels','isolated_line':'text_residue_lines'}[kind],'legacy_eid':index,'feature_id':fid} for (kind,index),fid in identities.items()],'losses':[{'field':'layout_width_px/layout_height_px/baseline_offset_px/font_family/layout_basis','resolution':'Preserved in source_features in this compatibility manifest; frozen editor text renderer cannot reproduce width-constrained layout exactly'},{'field':'operation/review audit, UUID foreign keys, OCR relations','resolution':'Retained in this manifest; legacy editor cannot replay new SQLite audit history'},{'field':'geographic metadata','resolution':'Legacy editing stays in pixel space; CRS/affine retained in asset_metadata'}],'asset_metadata':asset,'source_features':features,'groups':groups,'styles':styles,'ocr_candidates':candidates,'lineage':lineage}
    atomic_json(output.with_suffix('.compatibility.json'),manifest)
    return {'output':str(output),'manifest':str(output.with_suffix('.compatibility.json')),'feature_count':len(features),'output_sha256':manifest['output_sha256'],'verification':verification}

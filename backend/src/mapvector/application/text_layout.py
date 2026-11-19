"""Backend ownership of OCR typography with auditable repair of existing objects."""
import json
import copy
import hashlib
from contextlib import contextmanager
from mapvector.configuration.settings import Settings
from mapvector.domain.errors import CommandConflict
from mapvector.geometry.text import ocr_layout,layout_bbox
from mapvector.application.ports import load_feature,restore_feature,update_index


def set_ocr_layout(connection,feature_id,quad,project_dir=None):
    feature=load_feature(connection,feature_id)
    layout=source_layout(connection,feature['asset_id'],feature['text_value'],quad,project_dir)
    return with_layout(feature,layout)


def with_layout(feature,layout):
    layout=copy.deepcopy(layout)
    reasons=list(layout.pop('quality_reasons',[]) or [])
    if layout.pop('script_review_required',False) and not reasons:reasons.append('script_position_uncertain')
    if reasons:
        if not layout.get('layout_runs'):
            layout['layout_runs']=[{'text':feature['text_value'],'script':'normal','font_size_px':layout['font_size_px'],'x_offset_px':-layout['layout_width_px']/2,'baseline_offset_px':layout['baseline_offset_px'],'width_px':layout['layout_width_px'],'source_index':0,'basis':'conservative_fallback'}]
        for run in layout['layout_runs']:
            run['review_required']=True
            run['quality_reasons']=sorted(set([*run.get('quality_reasons',[]),*reasons]))
    x,y=layout['x'],layout['y']
    return {**feature,**{k:v for k,v in layout.items() if k not in ('x','y','script_review_required')},'geometry':{'type':'Point','coordinates':[x,y]},'bbox_min_x_px':x,'bbox_max_x_px':x,'bbox_min_y_px':y,'bbox_max_y_px':y,'display_bbox_px':layout_bbox(x,y,layout['layout_width_px'],layout['layout_height_px'],layout['rotation_deg'])}


def manual_layout_ids(connection,project_id,asset_id):
    ids=set()
    # An explicit typography binding is intent even when its values happened
    # to match the old OCR estimate at binding time. Color-only styles do not
    # reserve text placement. Old stores can be inspected before migration.
    style_fields={row['name'] for row in connection.execute('PRAGMA table_info(style)')}
    if {'font_size_px','rotation_deg'}.issubset(style_fields):
        ids.update(row[0] for row in connection.execute("SELECT f.feature_id FROM feature f JOIN style s ON s.style_id=f.style_id AND s.project_id=f.project_id WHERE f.project_id=? AND f.asset_id=? AND f.feature_type='text' AND (s.font_size_px IS NOT NULL OR s.rotation_deg IS NOT NULL)",(project_id,asset_id)))
    # Only differences in explicit user text/layout commands count as manual layout intent.
    rows=connection.execute("SELECT c.before_state,c.after_state,c.before_geometry_wkb,c.after_geometry_wkb FROM operation_change c JOIN operation o USING(operation_id) JOIN feature f ON c.entity_id=f.feature_id WHERE o.project_id=? AND f.asset_id=? AND f.feature_type='text' AND o.operation_type IN ('update_text','adopt_ocr_candidate','apply_text_format','bind_style','set_style','rebind_style','clear_style_override') AND o.operation_status='applied' AND c.entity_type='feature' AND c.before_state IS NOT NULL",(project_id,asset_id))
    for row in rows:
        before=json.loads(row['before_state']);after=json.loads(row['after_state'])
        if before.get('attributes'):before.update(before.pop('attributes'))
        if after.get('attributes'):after.update(after.pop('attributes'))
        fields=('text_value','font_family','font_size_px','rotation_deg','layout_runs','layout_width_px','layout_height_px','baseline_offset_px','layout_basis')
        if any(before.get(k)!=after.get(k) for k in fields) or row['before_geometry_wkb']!=row['after_geometry_wkb']:ids.add(before['feature_id'])
    return ids


def _raster_digest(connection,asset_id,project_dir):
    asset=connection.execute('SELECT raster_rel_path,raster_sha256 FROM asset WHERE asset_id=?',(asset_id,)).fetchone()
    if asset is None:raise KeyError(asset_id)
    path=Settings.resolve_project_path(project_dir,asset['raster_rel_path'])
    checksum=hashlib.sha256()
    try:
        with path.open('rb') as source:
            for block in iter(lambda:source.read(1024*1024),b''):checksum.update(block)
    except OSError as exc:raise CommandConflict('OCR_EVIDENCE_MISSING',{'reason':'source_raster_unavailable'}) from exc
    if checksum.hexdigest()!=asset['raster_sha256']:raise CommandConflict('ASSET_RESULT_MISMATCH',{'reason':'source_raster_changed'})
    return path,checksum.hexdigest()


@contextmanager
def _repair_source(connection,asset_id,project_dir):
    if project_dir is None:
        yield None;return
    from PIL import Image,UnidentifiedImageError
    path,_=_raster_digest(connection,asset_id,project_dir)
    try:
        source=Image.open(path)
        source.load()
    except (OSError,ValueError,UnidentifiedImageError) as exc:raise CommandConflict('OCR_EVIDENCE_MISSING',{'reason':'source_raster_unreadable'}) from exc
    try:
        yield source
    finally:source.close()


def plan_repairs(connection,project_id,asset_id,project_dir=None):
    with _repair_source(connection,asset_id,project_dir) as source:
        return _plan_repairs(connection,project_id,asset_id,project_dir,source)


def _plan_repairs(connection,project_id,asset_id,project_dir=None,source_image=None):
    manual=manual_layout_ids(connection,project_id,asset_id)
    changes=[];skipped=[]
    from mapvector.application.ocr_fusion import spatial_conflicts
    evidence=[dict(row) for row in connection.execute("SELECT f.feature_id,c.raw_text,c.detected_quad_px,c.rule_suggestions FROM feature f JOIN text_attribute t USING(feature_id) JOIN ocr_candidate c ON c.candidate_id=t.primary_candidate_id WHERE f.project_id=? AND f.asset_id=? AND f.feature_type='text' AND f.lifecycle_status='active' AND c.detected_quad_px IS NOT NULL",(project_id,asset_id))]
    for item in evidence:item['detected_quad_px']=json.loads(item['detected_quad_px'])
    conflicts=spatial_conflicts(evidence)
    conflicted={evidence[item[key]]['feature_id'] for item in conflicts for key in ('left_index','right_index')}
    for row in connection.execute("SELECT f.feature_id,c.detected_quad_px,c.raw_text FROM feature f JOIN text_attribute t USING(feature_id) JOIN ocr_candidate c ON c.candidate_id=t.primary_candidate_id WHERE f.project_id=? AND f.asset_id=? AND f.feature_type='text' AND f.lifecycle_status='active'",(project_id,asset_id)).fetchall():
        old=load_feature(connection,row['feature_id'])
        if old['feature_id'] in manual or old['source_type']!='algorithm' or old['text_content_revision']!=0 or old.get('layout_basis')=='manual' or not row['detected_quad_px']:
            skipped.append(old['feature_id']);continue
        try:
            quad=json.loads(row['detected_quad_px'])
            new=with_layout(old,source_layout(connection,asset_id,old['text_value'],quad,project_dir,source_image))
        except (ValueError,TypeError):skipped.append(old['feature_id']);continue
        if old['feature_id'] in conflicted:
            for run in new.get('layout_runs',[]):
                run['review_required']=True
                run['quality_reasons']=sorted(set([*run.get('quality_reasons',[]),'ocr_spatial_conflict']))
        layout_reasons=[*old.get('review_reason_codes',[])]
        if any(run.get('quality_reasons') for run in new.get('layout_runs',[])) and 'layout_fit_uncertain' not in layout_reasons:layout_reasons.append('layout_fit_uncertain')
        if old['feature_id'] in conflicted and 'ocr_spatial_conflict' not in layout_reasons:layout_reasons.append('ocr_spatial_conflict')
        new['review_reason_codes']=layout_reasons
        if old['review_status'] in ('auto_accepted_unverified','pipeline_complete_unverified') and any(run.get('review_required') for run in new.get('layout_runs',[])):
            # Automatic acceptance is not a human decision. Newly discovered
            # layout risks must reappear in the existing review queue.
            new['review_status']='required'
        if all(old.get(key)==new.get(key) for key in ('font_size_px','rotation_deg','font_family','layout_width_px','layout_height_px','baseline_offset_px','layout_basis','layout_runs','geometry','display_bbox_px','review_reason_codes','review_status')):continue
        changes.append((old,new))
    return changes,skipped


def repair_preview(connection,project_id,asset_id,base_revision,project_dir=None):
    current=connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()
    if current is None:raise KeyError(project_id)
    if current['working_revision']!=base_revision:raise CommandConflict('REVISION_CONFLICT')
    if current['current_asset_id']!=asset_id:raise CommandConflict('ASSET_RESULT_MISMATCH')
    changes,skipped=plan_repairs(connection,project_id,asset_id,project_dir)
    raster_digest=_raster_digest(connection,asset_id,project_dir)[1] if project_dir is not None else None
    digest=hashlib.sha256(json.dumps({'project_id':project_id,'asset_id':asset_id,'base_revision':base_revision,'changes':changes,'skipped':skipped,'raster':raster_digest},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'base_revision':base_revision,'asset_id':asset_id,'input_sha256':digest,'updated_count':len(changes),'skipped_count':len(skipped),'review_required_count':sum(any(run.get('review_required') for run in new.get('layout_runs',[])) for _,new in changes),'changes':[{'feature_id':old['feature_id'],'text_value':old['text_value'],'before':old,'after':new} for old,new in changes]},changes,skipped


def repair(connection,project_id,asset_id,revision,timestamp,project_dir=None,expected_preview_sha256=None):
    if expected_preview_sha256:
        preview,changes,skipped=repair_preview(connection,project_id,asset_id,revision-1,project_dir)
        if preview['input_sha256']!=expected_preview_sha256:raise CommandConflict('PREVIEW_STALE')
    else:changes,skipped=plan_repairs(connection,project_id,asset_id,project_dir)
    for old,new in changes:
        new.update(revision=revision,updated_at=timestamp)
        restore_feature(connection,new);update_index(connection,new['feature_id'])
    return changes,skipped


def source_layout(connection,asset_id,text,quad,project_dir,source_image=None):
    if source_image is not None:return ocr_layout(text,quad,source_image=source_image)
    if project_dir is None:return ocr_layout(text,quad)
    from PIL import Image
    asset=connection.execute('SELECT raster_rel_path FROM asset WHERE asset_id=?',(asset_id,)).fetchone()
    with Image.open(project_dir/asset['raster_rel_path']) as source:
        return ocr_layout(text,quad,source_image=source)

"""Backend ownership of OCR typography with auditable repair of existing objects."""
import json
from mapvector.geometry.text import ocr_layout,layout_bbox
from mapvector.application.ports import load_feature,restore_feature,update_index


def set_ocr_layout(connection,feature_id,quad,project_dir=None):
    feature=load_feature(connection,feature_id)
    layout=source_layout(connection,feature['asset_id'],feature['text_value'],quad,project_dir)
    return with_layout(feature,layout)


def with_layout(feature,layout):
    x,y=layout['x'],layout['y']
    return {**feature,**{k:v for k,v in layout.items() if k not in ('x','y','script_review_required')},'geometry':{'type':'Point','coordinates':[x,y]},'bbox_min_x_px':x,'bbox_max_x_px':x,'bbox_min_y_px':y,'bbox_max_y_px':y,'display_bbox_px':layout_bbox(x,y,layout['layout_width_px'],layout['layout_height_px'],layout['rotation_deg'])}


def manual_layout_ids(connection,project_id,asset_id):
    ids=set()
    # Only differences in explicit user text/layout commands count as manual layout intent.
    rows=connection.execute("SELECT c.before_state,c.after_state,c.before_geometry_wkb,c.after_geometry_wkb FROM operation_change c JOIN operation o USING(operation_id) JOIN feature f ON c.entity_id=f.feature_id WHERE o.project_id=? AND f.asset_id=? AND f.feature_type='text' AND o.operation_type IN ('update_text','adopt_ocr_candidate') AND o.operation_status='applied' AND c.entity_type='feature' AND c.before_state IS NOT NULL",(project_id,asset_id))
    for row in rows:
        before=json.loads(row['before_state']);after=json.loads(row['after_state'])
        if before.get('attributes'):before.update(before.pop('attributes'))
        if after.get('attributes'):after.update(after.pop('attributes'))
        fields=('text_value','font_size_px','rotation_deg')
        if any(before.get(k)!=after.get(k) for k in fields) or row['before_geometry_wkb']!=row['after_geometry_wkb']:ids.add(before['feature_id'])
    return ids


def repair(connection,project_id,asset_id,revision,timestamp,project_dir=None):
    manual=manual_layout_ids(connection,project_id,asset_id)
    changes=[];skipped=[]
    for row in connection.execute("SELECT f.feature_id,c.detected_quad_px,c.raw_text FROM feature f JOIN text_attribute t USING(feature_id) JOIN ocr_candidate c ON c.candidate_id=t.primary_candidate_id WHERE f.project_id=? AND f.asset_id=? AND f.feature_type='text' AND f.lifecycle_status='active'",(project_id,asset_id)).fetchall():
        old=load_feature(connection,row['feature_id'])
        if old['feature_id'] in manual or old['source_type']!='algorithm' or old['text_content_revision']!=0 or old.get('layout_basis')=='manual' or not row['detected_quad_px']:
            skipped.append(old['feature_id']);continue
        try:
            quad=json.loads(row['detected_quad_px'])
            new=with_layout(old,source_layout(connection,asset_id,old['text_value'],quad,project_dir))
        except (ValueError,TypeError):skipped.append(old['feature_id']);continue
        if all(old.get(key)==new.get(key) for key in ('font_size_px','rotation_deg','font_family','layout_width_px','layout_height_px','baseline_offset_px','layout_basis','layout_runs','geometry','display_bbox_px')):continue
        new.update(revision=revision,updated_at=timestamp)
        restore_feature(connection,new);update_index(connection,new['feature_id']);changes.append((old,new))
    return changes,skipped


def source_layout(connection,asset_id,text,quad,project_dir):
    if project_dir is None:return ocr_layout(text,quad)
    from PIL import Image
    asset=connection.execute('SELECT raster_rel_path FROM asset WHERE asset_id=?',(asset_id,)).fetchone()
    with Image.open(project_dir/asset['raster_rel_path']) as source:
        return ocr_layout(text,quad,source_image=source)

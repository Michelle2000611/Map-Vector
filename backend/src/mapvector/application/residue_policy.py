"""Shared, evidence-bound residue decisions. No geometry mutations."""
import hashlib
import json
from pathlib import Path
from shapely.geometry import shape,box,Polygon
from mapvector.application.ports import load_feature

_RASTER_CACHE = {}


def raster_sha256(path):
    """Reuse immutable file evidence while its filesystem identity is unchanged."""
    stat=path.stat()
    key=(str(path),stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,getattr(stat,'st_ino',0))
    cached=_RASTER_CACHE.get(key)
    if cached is not None:return cached
    checksum=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):checksum.update(chunk)
    result=checksum.hexdigest();after=path.stat()
    if (after.st_size,after.st_mtime_ns,after.st_ctime_ns,getattr(after,'st_ino',0))==key[1:]:
        if len(_RASTER_CACHE)>32:_RASTER_CACHE.clear()
        _RASTER_CACHE[key]=result
    return result

_POLICY = "residue-shared-v1"
_IGNORED = {"revision","updated_at","created_at","review_status","review_basis","review_reason_codes","reviewed_content_revision","reviewed_at","reviewer_id","cleanup_status","text_content_revision"}

def _stable(value):
    return {k:v for k,v in value.items() if k not in _IGNORED}

def evidence(connection, project_id, asset_id, text_id, feature_id):
    feature=load_feature(connection,feature_id); text=load_feature(connection,text_id)
    asset=dict(connection.execute("SELECT asset_id,raster_sha256 FROM asset WHERE project_id=? AND asset_id=?",(project_id,asset_id)).fetchone())
    candidate=connection.execute("SELECT * FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?",(text.get("primary_candidate_id"),project_id,asset_id)).fetchone()
    binding=connection.execute("SELECT style_id FROM feature_style WHERE feature_id=?",(feature_id,)).fetchone()
    layer=connection.execute("SELECT default_style_id FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type=?",(project_id,asset_id,feature["feature_type"])).fetchone()
    style_ids={feature.get("style_id"),binding[0] if binding else None,layer[0] if layer else None}-{None}
    styles=[_stable(dict(row)) for sid in sorted(style_ids) if (row:=connection.execute("SELECT * FROM style WHERE project_id=? AND style_id=?",(project_id,sid)).fetchone())]
    geom=shape(feature['geometry']);overlaps=[]
    for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active' AND feature_id!=? ORDER BY feature_id",(project_id,asset_id,text_id)):
        other=load_feature(connection,row[0]);ocr=connection.execute("SELECT detected_quad_px FROM ocr_candidate WHERE candidate_id=?",(other.get('primary_candidate_id'),)).fetchone()
        quad=json.loads(ocr[0]) if ocr and ocr[0] else None
        region=Polygon(quad) if quad else box(*other['display_bbox_px']) if other.get('display_bbox_px') else None
        if region is not None and region.intersects(geom):overlaps.append({'text':_stable(other),'quad':quad})
    asset_row=connection.execute("SELECT raster_rel_path FROM asset WHERE project_id=? AND asset_id=?",(project_id,asset_id)).fetchone()
    db_path=next((row[2] for row in connection.execute('PRAGMA database_list') if row[1]=='main'),'')
    actual_raster=None
    if db_path and asset_row:
        directory=Path(db_path).resolve().parents[1];path=(directory/asset_row[0]).resolve()
        if path.is_relative_to(directory):
            try:
                actual_raster=raster_sha256(path)
            except OSError:actual_raster='unavailable'
    value={"actual_raster_sha256":actual_raster,"overlapping_texts":overlaps,"policy":_POLICY,"asset":asset,"text":_stable(text),"candidate":_stable(dict(candidate)) if candidate else None,"feature":_stable(feature),"styles":styles,"binding":binding[0] if binding else None}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str,separators=(",",":")).encode()).hexdigest()

def write_decision(connection,project_id,asset_id,text_id,feature_id,decision,preview_id,timestamp):
    write_object_decision(connection,project_id,asset_id,feature_id,decision,preview_id,timestamp)
    connection.execute("INSERT INTO residue_decision VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(project_id,asset_id,text_feature_id,feature_id) DO UPDATE SET evidence_sha256=excluded.evidence_sha256,decision=excluded.decision,updated_at=excluded.updated_at,preview_id=excluded.preview_id",(project_id,asset_id,text_id,feature_id,evidence(connection,project_id,asset_id,text_id,feature_id),decision,timestamp,preview_id))

def is_kept(connection,project_id,asset_id,text_ids,feature_id):
    row=connection.execute('SELECT evidence_sha256,decision FROM residue_object_decision WHERE project_id=? AND asset_id=? AND feature_id=?',(project_id,asset_id,feature_id)).fetchone()
    if row and row['evidence_sha256']==confirmation_evidence(connection,project_id,asset_id,feature_id):return row['decision']=='keep'
    for text_id in text_ids:
        row=connection.execute("SELECT evidence_sha256,decision FROM residue_decision WHERE project_id=? AND asset_id=? AND text_feature_id=? AND feature_id=?",(project_id,asset_id,text_id,feature_id)).fetchone()
        if row and row["decision"]=="keep" and row["evidence_sha256"]==evidence(connection,project_id,asset_id,text_id,feature_id):return True
    return False

def candidate_is_kept(connection,project_id,asset_id,candidate):
    return candidate["kind"]=="text_stroke" and any(is_kept(connection,project_id,asset_id,candidate["reference_text_ids"],fid) for fid in candidate["feature_ids"])


def decision_for(connection,project_id,asset_id,text_id,feature_id):
    row=connection.execute("SELECT evidence_sha256,decision FROM residue_decision WHERE project_id=? AND asset_id=? AND text_feature_id=? AND feature_id=?",(project_id,asset_id,text_id,feature_id)).fetchone()
    return row["decision"] if row and row["evidence_sha256"]==evidence(connection,project_id,asset_id,text_id,feature_id) else None


def line_protection(connection,project_id,asset_id,line):
    from mapvector.geometry.text_residue import effective_line_appearance
    binding=connection.execute("SELECT style_id FROM feature_style WHERE feature_id=?",(line['feature_id'],)).fetchone()
    layer=connection.execute("SELECT default_style_id FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type='line'",(project_id,asset_id)).fetchone()
    sid=binding[0] if binding else line.get('style_id') or (layer[0] if layer else None)
    row=connection.execute("SELECT * FROM style WHERE project_id=? AND style_id=?",(project_id,sid)).fetchone()
    style=dict(row) if row else None
    effective=effective_line_appearance(line,{'styles':{sid:style} if style else {},'style_bindings':{line['feature_id']:sid} if sid else {}})
    reasons=[]
    if line['source_type']=='manual':reasons.append('manual_line')
    if line['line_role']=='split':reasons.append('explicit_split_line')
    patterns={str(line.get('line_pattern','')).lower(),str(effective.get('line_pattern','')).lower()}
    if patterns & {'dash','dashed','teeth','tooth','toothed'} or style and (style.get('tooth_spacing_px') or style.get('tooth_height_px') or json.loads(style.get('dash_pattern_px') or '[]')):reasons.append('semantic_line_pattern')
    return {'reasons':reasons,'style':style,'effective_appearance':effective}


def has_decision(connection,project_id,asset_id,text_id,feature_id):
    return connection.execute("SELECT 1 FROM residue_decision WHERE project_id=? AND asset_id=? AND text_feature_id=? AND feature_id=?",(project_id,asset_id,text_id,feature_id)).fetchone() is not None


def related_text_ids(connection,project_id,asset_id,feature_id):
    """Active source-text references for one object, independent of entrance.

    OCR footprints remain authoritative after display movement; a current
    display is used only for a label without original detection evidence.
    """
    from mapvector.geometry.text_residue import text_residue_regions
    feature=load_feature(connection,feature_id)
    if feature['project_id']!=project_id or feature['asset_id']!=asset_id:return []
    geometry=shape(feature['geometry'])
    if feature['feature_type']=='line':
        try:margin=min(3.,max(.75,float(line_protection(connection,project_id,asset_id,feature)['effective_appearance'].get('stroke_width_px') or 1)/2+.5))
        except (ValueError,TypeError):margin=1
        geometry=geometry.buffer(margin)
    x0,y0,x1,y1=geometry.bounds
    rows=connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active' AND rowid IN (SELECT id FROM text_ocr_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_display_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) ORDER BY feature_id",(project_id,asset_id,x0,x1,y0,y1,x0,x1,y0,y1))
    related=[]
    for row in rows:
        text=load_feature(connection,row[0])
        candidate=connection.execute('SELECT detected_quad_px FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(text.get('primary_candidate_id'),project_id,asset_id)).fetchone()
        text['detected_quad_px']=json.loads(candidate[0]) if candidate and candidate[0] else None
        if any(item['geometry'].intersects(geometry) for item in text_residue_regions([text])):related.append(text['feature_id'])
    return related


def confirmation_evidence(connection,project_id,asset_id,feature_id):
    """Object-bound authority, identical at every entry and invalidated by evidence changes."""
    from mapvector.application.residue_context import raster_binding
    feature=load_feature(connection,feature_id)
    if feature['project_id']!=project_id or feature['asset_id']!=asset_id:
        raise ValueError('Object is outside the current asset')
    text_ids=related_text_ids(connection,project_id,asset_id,feature_id)
    binding=connection.execute('SELECT style_id FROM feature_style WHERE feature_id=?',(feature_id,)).fetchone()
    layer=connection.execute('SELECT default_style_id FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type=?',(project_id,asset_id,feature['feature_type'])).fetchone()
    style_ids={feature.get('style_id'),binding[0] if binding else None,layer[0] if layer else None}-{None}
    styles=[_stable(dict(row)) for sid in sorted(style_ids) if (row:=connection.execute('SELECT * FROM style WHERE project_id=? AND style_id=?',(project_id,sid)).fetchone())]
    geometry=shape(feature['geometry'])
    unadopted=[]
    for row in connection.execute('SELECT * FROM ocr_candidate WHERE project_id=? AND asset_id=? AND text_feature_id IS NULL AND detected_quad_px IS NOT NULL ORDER BY candidate_id',(project_id,asset_id)):
        candidate=dict(row)
        try:region=Polygon(json.loads(candidate['detected_quad_px']))
        except (ValueError,TypeError):continue
        if region.is_valid and region.buffer(3).intersects(geometry):unadopted.append(_stable(candidate))
    protecting_lines=[]
    if feature['feature_type']=='face':
        for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='line' AND lifecycle_status='active' ORDER BY feature_id",(project_id,asset_id)):
            line=load_feature(connection,row[0]);policy=line_protection(connection,project_id,asset_id,line)
            width=float(policy['effective_appearance'].get('stroke_width_px') or 1)
            if shape(line['geometry']).buffer(max(width/2,.001)).intersects(geometry):protecting_lines.append({'line':_stable(line),'policy':policy})
    value={'policy':'residue-confirmation-2','unadopted_ocr':unadopted,'protecting_lines':protecting_lines,'feature':_stable(feature),'raster':raster_binding(connection,project_id,asset_id),'styles':styles,'binding':binding[0] if binding else None,'texts':{tid:evidence(connection,project_id,asset_id,tid,feature_id) for tid in text_ids}}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str,separators=(',',':')).encode()).hexdigest()


def is_confirmed(connection,project_id,asset_id,feature_id):
    row=connection.execute('SELECT evidence_sha256 FROM residue_confirmation WHERE project_id=? AND asset_id=? AND feature_id=?',(project_id,asset_id,feature_id)).fetchone()
    return bool(row and row[0]==confirmation_evidence(connection,project_id,asset_id,feature_id))


def clear_confirmation(connection,project_id,asset_id,feature_id):
    connection.execute('DELETE FROM residue_confirmation WHERE project_id=? AND asset_id=? AND feature_id=?',(project_id,asset_id,feature_id))


def write_confirmation(connection,project_id,asset_id,feature_id,preview_id,timestamp):
    # A mismatched source is stale evidence, not a semantic protection to override.
    from mapvector.application.residue_context import raster_binding
    from mapvector.domain.errors import CommandConflict
    if raster_binding(connection,project_id,asset_id).get('status')=='mismatch':raise CommandConflict('PREVIEW_STALE',{'reason':'RASTER_SOURCE_MISMATCH'})
    # An explicit new review replaces earlier keep decisions for this object.
    checksum=confirmation_evidence(connection,project_id,asset_id,feature_id)
    connection.execute('DELETE FROM residue_object_decision WHERE project_id=? AND asset_id=? AND feature_id=?',(project_id,asset_id,feature_id))
    connection.execute('DELETE FROM residue_decision WHERE project_id=? AND asset_id=? AND feature_id=?',(project_id,asset_id,feature_id))
    connection.execute('DELETE FROM text_residue_decision WHERE project_id=? AND asset_id=? AND line_feature_id=?',(project_id,asset_id,feature_id))
    connection.execute('INSERT INTO residue_confirmation VALUES (?,?,?,?,?,?) ON CONFLICT(project_id,asset_id,feature_id) DO UPDATE SET evidence_sha256=excluded.evidence_sha256,preview_id=excluded.preview_id,updated_at=excluded.updated_at',(project_id,asset_id,feature_id,checksum,preview_id,timestamp))


def write_object_decision(connection,project_id,asset_id,feature_id,decision,preview_id,timestamp):
    """Keep/reopen also works for ordinary fragments without a related text."""
    clear_confirmation(connection,project_id,asset_id,feature_id)
    checksum=confirmation_evidence(connection,project_id,asset_id,feature_id)
    connection.execute('INSERT INTO residue_object_decision VALUES (?,?,?,?,?,?,?) ON CONFLICT(project_id,asset_id,feature_id) DO UPDATE SET evidence_sha256=excluded.evidence_sha256,decision=excluded.decision,preview_id=excluded.preview_id,updated_at=excluded.updated_at',(project_id,asset_id,feature_id,checksum,decision,preview_id,timestamp))

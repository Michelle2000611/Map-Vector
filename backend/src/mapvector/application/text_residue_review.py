"""Local line review evidence and metadata decisions; never mutates map geometry."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import Polygon, box, shape

from mapvector.application.ports import load_feature
from mapvector.domain.commands import UUIDString
from mapvector.domain.errors import CommandConflict


class TextResidueDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    asset_id: UUIDString
    base_revision: int = Field(ge=0, le=9007199254740990, strict=True)
    preview_id: UUIDString
    feature_ids: list[UUIDString] = Field(min_length=1, max_length=2000)
    decision: Literal['keep', 'reopen']

    @model_validator(mode='after')
    def unique_ids(self):
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError('Feature identities must be unique')
        return self


class TextResidueDecisionResult(BaseModel):
    feature_ids: list[str]
    decision: Literal['keep', 'reopen']


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


def _evidence_feature(feature):
    # Timestamps and working revisions are not evidence. Unrelated edits do not
    # invalidate a keep decision for the same text and line geometry/semantics.
    return {key:value for key,value in feature.items() if key not in ('revision','updated_at','created_at')}


def _text_evidence(connection, text):
    candidate = connection.execute('SELECT * FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?', (text.get('primary_candidate_id'), text['project_id'], text['asset_id'])).fetchone()
    # Content acceptance is independent of residue evidence. Reviewing an
    # unchanged label must not silently reopen kept geology underneath it.
    text_evidence={key:value for key,value in _evidence_feature(text).items() if key not in ('review_status','review_basis','review_reason_codes','reviewed_content_revision','reviewed_at','reviewer_id','cleanup_status','text_content_revision')}
    return {'text':text_evidence, 'candidate':dict(candidate) if candidate else None}


def _hard_protection(connection,project_id,asset_id,line):
    reasons=[]
    if line['source_type']=='manual':reasons.append('manual_line')
    if line['line_role']=='split':reasons.append('explicit_split_line')
    binding=connection.execute('SELECT style_id FROM feature_style WHERE feature_id=?',(line['feature_id'],)).fetchone()
    layer=connection.execute("SELECT default_style_id FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type='line'",(project_id,asset_id)).fetchone()
    style_id=binding['style_id'] if binding else line.get('style_id') or (layer['default_style_id'] if layer else None)
    style_row=connection.execute('SELECT * FROM style WHERE style_id=? AND project_id=?',(style_id,project_id)).fetchone()
    style=dict(style_row) if style_row else None
    patterns={str(line.get('line_pattern','')).lower(),str(style.get('line_pattern','')).lower() if style else ''}
    if patterns & {'dash','dashed','teeth','tooth','toothed'} or style and (style.get('tooth_spacing_px') or style.get('tooth_height_px') or json.loads(style.get('dash_pattern_px') or '[]')):
        reasons.append('semantic_line_pattern')
    return reasons,style


def _other_texts(connection,project_id,asset_id,target_id,geometry,local_texts,evidence_cache):
    x0,y0,x1,y1=geometry.bounds
    identities=set(local_texts)
    identities.update(row[0] for row in connection.execute("SELECT f.feature_id FROM feature f WHERE f.project_id=? AND f.asset_id=? AND f.feature_type='text' AND f.lifecycle_status='active' AND f.feature_id!=? AND f.rowid IN (SELECT id FROM text_display_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_ocr_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) ORDER BY f.feature_id",(project_id,asset_id,target_id or '',x0,x1,y0,y1,x0,x1,y0,y1)))
    result=[]
    for fid in sorted(identities):
        other=local_texts.get(fid) or load_feature(connection,fid);bbox=other.get('display_bbox_px')
        if fid not in evidence_cache:evidence_cache[fid]=_text_evidence(connection,other)
        evidence=evidence_cache[fid];candidate=evidence['candidate']
        quad=json.loads(candidate['detected_quad_px']) if candidate and candidate.get('detected_quad_px') else None
        other_region=box(*bbox) if bbox else shape(other['geometry'])
        if geometry.intersects(other_region) or quad and geometry.intersects(Polygon(quad)):result.append(evidence)
    return result


def protect_without_target(connection,project_id,asset_id,features,display):
    """Legacy text creation has no text-bound authority to override protection."""
    safe=set(display['line_feature_ids']);protected=set(display['protected_line_feature_ids'])
    local_texts={f['feature_id']:f for f in features if f['feature_type']=='text' and f['lifecycle_status']=='active'}
    evidence_cache={}
    for line in features:
        if line['feature_id'] in safe and (_hard_protection(connection,project_id,asset_id,line)[0] or _other_texts(connection,project_id,asset_id,None,shape(line['geometry']),local_texts,evidence_cache)):
            protected.add(line['feature_id']);safe.remove(line['feature_id'])
    display.update(line_feature_ids=sorted(safe),cleanup_line_feature_ids=sorted(safe),protected_line_feature_ids=sorted(protected))


def review_lines(connection, project_id, asset_id, text_id, features, display):
    """Materialize only preview lines, effective styles and intersecting text."""
    region = box(*display['bounds_px'])
    text = next((f for f in features if f['feature_id']==text_id), None)
    if text is None: raise CommandConflict('TEXT_TARGET_REQUIRED')
    target_evidence = _text_evidence(connection,text)
    asset = dict(connection.execute('SELECT asset_id,raster_sha256 FROM asset WHERE asset_id=? AND project_id=?',(asset_id,project_id)).fetchone())
    protected = set(display['protected_line_feature_ids'])
    suggested = set(display['line_feature_ids'])
    local_texts={f['feature_id']:f for f in features if f['feature_type']=='text' and f['lifecycle_status']=='active' and f['feature_id']!=text_id}
    text_evidence={}
    items = {}
    for line in features:
        fid = line['feature_id']
        if line['feature_type']!='line' or line['lifecycle_status']!='active': continue
        geometry = shape(line['geometry'])
        if geometry.intersection(region.buffer(-1e-6)).length<=1e-7: continue
        reasons,style=_hard_protection(connection,project_id,asset_id,line)
        others=_other_texts(connection,project_id,asset_id,text_id,geometry,local_texts,text_evidence)
        if others: reasons.append('other_text_overlap')
        hard=bool(reasons)
        if not region.buffer(1e-6).covers(geometry): reasons.append('crosses_review_bounds')
        if not hard and fid not in protected: continue
        if not reasons: reasons.append('uncertain_text_line')
        protected.add(fid);suggested.discard(fid)
        evidence=digest({'policy':'text-residue-review-1','asset':asset,'target':target_evidence,'line':_evidence_feature(line),'style':_evidence_feature(style) if style else None,'other_texts':others,'bounds_px':display['bounds_px'],'reason_codes':sorted(reasons)})
        decision=connection.execute('SELECT evidence_sha256,decision FROM text_residue_decision WHERE project_id=? AND asset_id=? AND text_feature_id=? AND line_feature_id=?',(project_id,asset_id,text_id,fid)).fetchone()
        status='kept' if decision and decision['decision']=='keep' and decision['evidence_sha256']==evidence else 'pending'
        items[fid]={'feature_id':fid,'reason_codes':sorted(reasons),'can_confirm':not hard,'status':status,'evidence_sha256':evidence,'geometry':geometry}
    groups=[];pending=set(items)
    while pending:
        first=min(pending);pending.remove(first);members=[first];queue=[first]
        while queue:
            current=items[queue.pop()]
            nearby=[fid for fid in sorted(pending) if all(items[fid][k]==current[k] for k in ('reason_codes','can_confirm','status')) and items[fid]['geometry'].distance(current['geometry'])<=max(4,text['font_size_px'])]
            for fid in nearby:pending.remove(fid);members.append(fid);queue.append(fid)
        members.sort();head=items[first];bounds=[items[fid]['geometry'].intersection(region).bounds for fid in members]
        evidence=digest({fid:items[fid]['evidence_sha256'] for fid in members})
        groups.append({'group_id':digest({'text_id':text_id,'feature_ids':members,'evidence':evidence})[:24],'feature_ids':members,'bounds_px':[min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds)],'reason_codes':head['reason_codes'],'status':head['status'],'can_confirm':head['can_confirm'],'evidence_sha256':evidence})
    display.update(line_feature_ids=sorted(suggested),cleanup_line_feature_ids=sorted(suggested),protected_line_feature_ids=sorted(protected),review_groups=groups,verification_pending_feature_ids=sorted(fid for fid,i in items.items() if i['status']=='pending'))
    return {fid:{key:value for key,value in item.items() if key!='geometry'} for fid,item in items.items()}


def validate_preview(connection, project_id, asset_id, revision, preview_id):
    from mapvector.application.previews import residue_scope_features
    from mapvector.domain.selection import PreviewRequest
    current=connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()
    if not current or current['working_revision']!=revision or current['current_asset_id']!=asset_id: raise CommandConflict('REVISION_CONFLICT')
    row=connection.execute('SELECT * FROM edit_preview WHERE preview_id=? AND project_id=? AND asset_id=?',(preview_id,project_id,asset_id)).fetchone()
    if row is None or row['base_revision']!=revision or datetime.fromisoformat(row['expires_at'])<=datetime.now(timezone.utc): raise CommandConflict('PREVIEW_STALE')
    request=PreviewRequest.model_validate_json(row['request_json']);stored=json.loads(row['result_json'])
    if request.preview_type!='text_residue' or len(request.feature_ids)!=1 or not stored.get('scope_bounds_px') or 'line_review_evidence' not in stored: raise CommandConflict('PREVIEW_STALE')
    features=residue_scope_features(connection,project_id,asset_id,stored['scope_bounds_px'])
    actual=hashlib.sha256(json.dumps(features,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
    if actual!=row['input_sha256']: raise CommandConflict('PREVIEW_STALE')
    display=json.loads(json.dumps(stored['text_residue_display']))
    evidence=review_lines(connection,project_id,asset_id,request.feature_ids[0],features,display)
    if {fid:i['evidence_sha256'] for fid,i in evidence.items()}!={fid:i['evidence_sha256'] for fid,i in stored['line_review_evidence'].items()}: raise CommandConflict('PREVIEW_STALE')
    return request,stored,evidence


def validate_confirmation(connection,project_id,request,display):
    verified=request.verified_line_feature_ids
    if not verified:return []
    if request.preview_type!='text_residue' or not request.complete_region or request.line_review_preview_id is None:raise CommandConflict('LINE_REVIEW_REQUIRED')
    source,stored,evidence=validate_preview(connection,project_id,request.asset_id,request.base_revision,request.line_review_preview_id)
    if source.feature_ids!=request.feature_ids or source.bounds_px!=request.bounds_px or stored['text_residue_display']['bounds_px']!=display['bounds_px']:raise CommandConflict('PREVIEW_SCOPE_MISMATCH')
    for fid in verified:
        item=evidence.get(fid);original=stored['line_review_evidence'].get(fid)
        if not item or not original or not original['can_confirm'] or original['status']!='pending' or not item['can_confirm'] or item['status']!='pending':raise CommandConflict('LINE_REVIEW_FORBIDDEN',{'feature_id':fid})
    return sorted(verified)


def decide(database, project_id, request):
    with database.transaction() as connection:
        source,stored,evidence=validate_preview(connection,project_id,request.asset_id,request.base_revision,request.preview_id)
        # Complete validation precedes the first write, including every requested ID.
        if any(fid not in evidence for fid in request.feature_ids):raise CommandConflict('PREVIEW_SCOPE_MISMATCH')
        timestamp=datetime.now(timezone.utc).isoformat()
        for fid in request.feature_ids:
            connection.execute('INSERT INTO text_residue_decision VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(project_id,asset_id,text_feature_id,line_feature_id) DO UPDATE SET evidence_sha256=excluded.evidence_sha256,decision=excluded.decision,updated_at=excluded.updated_at,preview_id=excluded.preview_id',(project_id,request.asset_id,source.feature_ids[0],fid,evidence[fid]['evidence_sha256'],request.decision,timestamp,request.preview_id))
        return {'feature_ids':request.feature_ids,'decision':request.decision}


def create_local_preview(database,project_id,request,project_dir):
    """Compute local geometry on a coherent WAL read snapshot; publish briefly."""
    from mapvector.application.previews import prepare_preview,residue_scope_features
    from mapvector.domain.selection import PreviewRequest
    with database.read() as connection:
        connection.execute('BEGIN')
        response,record=prepare_preview(connection,project_id,request,project_dir)
    stored=json.loads(record[6]);effective=PreviewRequest.model_validate_json(record[5])
    with database.transaction() as connection:
        current=connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()
        if current['working_revision']!=request.base_revision or current['current_asset_id']!=request.asset_id:raise CommandConflict('REVISION_CONFLICT')
        features=residue_scope_features(connection,project_id,request.asset_id,stored['scope_bounds_px'])
        actual=hashlib.sha256(json.dumps(features,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
        if actual!=record[7]:raise CommandConflict('PREVIEW_STALE')
        if 'line_review_evidence' in stored:
            current_display=json.loads(json.dumps(stored['text_residue_display']))
            evidence=review_lines(connection,project_id,request.asset_id,effective.feature_ids[0],features,current_display)
            if evidence!=stored['line_review_evidence']:raise CommandConflict('PREVIEW_STALE')
            validate_confirmation(connection,project_id,effective,current_display)
        connection.execute('INSERT INTO edit_preview VALUES (?,?,?,?,?,?,?,?)',record)
    return response

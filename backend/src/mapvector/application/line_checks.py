"""Materialized read snapshots, short preview writes, and line-only change plans."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from PIL import Image
from shapely import STRtree, from_wkb
from shapely.geometry import LineString, Polygon, mapping, shape

from mapvector.application.residue_policy import candidate_is_kept, write_decision, decision_for, is_confirmed, write_confirmation, clear_confirmation
from mapvector.application.ports import load_feature
from mapvector.application.review import text_decision
from mapvector.domain.commands import UUIDString
from mapvector.domain.errors import CommandConflict
from mapvector.geometry.line_checks import ALGORITHM_REVISION, MAX_CANDIDATES, MAX_RASTER_IMAGE_PIXELS, diagnose, digest


class LineCheckRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    asset_id: UUIDString
    base_revision: int = Field(ge=0, le=9007199254740990, strict=True)
    max_gap_px: float = Field(default=8, ge=0, le=50)
    angle_tolerance_deg: float = Field(default=15, ge=1, le=45)
    max_short_length_px: float = Field(default=12, ge=1, le=100)
    mode: Literal['automatic', 'manual'] = 'automatic'
    manual_feature_ids: list[UUIDString] = Field(default_factory=list, max_length=2)
    manual_connector_px: list[tuple[float, float]] | None = Field(default=None, min_length=2, max_length=1000)

    @model_validator(mode='after')
    def manual_scope(self):
        if self.mode == 'manual':
            if len(self.manual_feature_ids) != 2 or len(set(self.manual_feature_ids)) != 2:
                raise ValueError('Manual continuation requires exactly two unique line identities')
        elif self.manual_feature_ids or self.manual_connector_px is not None:
            raise ValueError('Manual continuation parameters require manual mode')
        return self


class LineCheckDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    asset_id: UUIDString
    base_revision: int = Field(ge=0, le=9007199254740990, strict=True)
    preview_id: UUIDString
    candidate_ids: list[str] = Field(min_length=1, max_length=2000)
    decision: Literal['keep', 'reopen', 'confirm']

    @model_validator(mode='after')
    def unique_candidates(self):
        if len(self.candidate_ids) != len(set(self.candidate_ids)): raise ValueError('Line check candidates must be unique')
        return self


class LineCheckCandidate(BaseModel):
    candidate_id: str
    kind: Literal['join_gap', 'text_stroke', 'dash_group']
    feature_ids: list[str]
    bounds_px: tuple[float, float, float, float]
    connectors: list[list[tuple[float, float]]]
    metrics: dict[str, float]
    reason_codes: list[str]
    blocked_reasons: list[str]
    reference_text_ids: list[str]
    status: Literal['pending', 'kept']
    review_required: bool
    manually_confirmed: bool = False
    allowed_action: Literal['join', 'isolate', 'group']
    connection_mode: Literal['automatic', 'manual'] = 'automatic'
    connector_kind: Literal['straight', 'smooth', 'manual'] = 'straight'
    evidence: dict[str, Any] = Field(default_factory=dict)


class LineCheckHistory(LineCheckCandidate):
    status: Literal['applied']
    operation_id: str
    result_revision: int
    created_at: str


class LineCheckReport(BaseModel):
    preview_id: str
    asset_id: str
    base_revision: int
    algorithm_revision: str
    expires_at: str
    input_sha256: str
    mode: Literal['automatic', 'manual'] = 'automatic'
    request_sha256: str
    candidates: list[LineCheckCandidate]
    history: list[LineCheckHistory]
    summary: dict[str, int | bool]


class LineCheckPage(BaseModel):
    preview_id: str
    asset_id: str
    base_revision: int
    expires_at: str
    kind: Literal['join_gap', 'text_stroke', 'dash_group']
    filter: Literal['pending', 'kept', 'applied', 'all']
    offset: int
    limit: int
    total: int
    items: list[LineCheckCandidate | LineCheckHistory]


class LineCheckDecisionResult(BaseModel):
    candidate_ids: list[str]
    decision: Literal['keep', 'reopen', 'confirm']


def _scope(connection, project_id, asset_id, revision):
    current = connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()
    if current is None: raise KeyError(project_id)
    if current['working_revision'] != revision: raise CommandConflict('REVISION_CONFLICT', {'working_revision':current['working_revision']})
    if current['current_asset_id'] != asset_id: raise CommandConflict('ASSET_RESULT_MISMATCH')
    asset = connection.execute('SELECT asset_id,project_id,width_px,height_px,raster_sha256,raster_rel_path FROM asset WHERE asset_id=? AND project_id=?',(asset_id,project_id)).fetchone()
    if asset is None: raise CommandConflict('ASSET_RESULT_MISMATCH')
    return dict(asset)


def snapshot(connection, project_id, asset_id, revision,*,text_feature_ids=None):
    asset = _scope(connection,project_id,asset_id,revision)
    if text_feature_ids is not None:
        return _residue_snapshot(connection,project_id,asset_id,asset,text_feature_ids)
    # Materialize references only; image decoding and candidate work happen after closing the read.
    lines = []
    for row in connection.execute("SELECT f.*,l.* FROM feature f JOIN line_attribute l USING(feature_id) WHERE f.project_id=? AND f.asset_id=? AND f.lifecycle_status='active' ORDER BY f.feature_id",(project_id,asset_id)):
        line=dict(row); geometry=from_wkb(line.pop('geometry_wkb')); line['geometry']=json.loads(json.dumps(mapping(geometry))); lines.append(line)
    texts = []
    for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active' ORDER BY feature_id",(project_id,asset_id)):
        text=load_feature(connection,row[0]); candidate=None
        if text.get('primary_candidate_id'):
            item=connection.execute('SELECT * FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(text['primary_candidate_id'],project_id,asset_id)).fetchone()
            if item: candidate=dict(item)
        text['detected_quad_px']=json.loads(candidate['detected_quad_px']) if candidate and candidate['detected_quad_px'] else None
        risks=set(text_decision(text,candidate)['review_reason_codes'])
        text['geological_symbol']=bool(risks & {'stratigraphic_or_lithology_code','orientation_measurement','numeric_or_short'})
        texts.append(text)
    groups=[]
    for row in connection.execute("SELECT * FROM logical_group WHERE project_id=? AND asset_id=? AND feature_type='line' ORDER BY group_id",(project_id,asset_id)):
        group=dict(row);group['feature_ids']=[item[0] for item in connection.execute('SELECT feature_id FROM group_member WHERE group_id=? ORDER BY feature_id',(group['group_id'],))];groups.append(group)
    styles={row['style_id']:dict(row) for row in connection.execute("SELECT * FROM style WHERE project_id=? AND feature_type='line' ORDER BY style_id",(project_id,))}
    layer=connection.execute("SELECT default_style_id FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type='line'",(project_id,asset_id)).fetchone()
    bindings={row['feature_id']:row['style_id'] for row in connection.execute('SELECT fs.* FROM feature_style fs JOIN feature f USING(feature_id) WHERE f.project_id=? AND f.asset_id=? AND f.feature_type=?',(project_id,asset_id,'line'))}
    source, path = _raster_source(connection, asset)
    unassigned=[]
    for row in connection.execute("SELECT candidate_id,detected_quad_px FROM ocr_candidate WHERE project_id=? AND asset_id=? AND text_feature_id IS NULL AND detected_quad_px IS NOT NULL ORDER BY candidate_id",(project_id,asset_id)):
        value=dict(row);value['detected_quad_px']=json.loads(value['detected_quad_px']);unassigned.append(value)
    return {'unassigned_ocr_candidates':unassigned,'asset':asset,'lines':lines,'texts':texts,'groups':groups,'styles':styles,'style_bindings':bindings,
            'default_style_id':layer['default_style_id'] if layer else None, 'raster_source':source, '_raster_path':path}


def _residue_snapshot(connection,project_id,asset_id,asset,text_feature_ids):
    """Load indexed local sources plus their ownership/protection neighbors."""
    from mapvector.geometry.text_residue import text_residue_regions
    texts={};lines={}
    def text(identity):
        if identity not in texts:
            value=load_feature(connection,identity)
            if value['project_id']!=project_id or value['asset_id']!=asset_id or value['feature_type']!='text' or value['lifecycle_status']!='active':raise CommandConflict('SELECTION_SCOPE_INVALID')
            candidate=connection.execute('SELECT * FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(value.get('primary_candidate_id'),project_id,asset_id)).fetchone()
            candidate=dict(candidate) if candidate else None
            value['detected_quad_px']=json.loads(candidate['detected_quad_px']) if candidate and candidate['detected_quad_px'] else None
            value['geological_symbol']=bool(set(text_decision(value,candidate)['review_reason_codes']) & {'stratigraphic_or_lithology_code','orientation_measurement','numeric_or_short'})
            texts[identity]=value
        return texts[identity]
    regions=text_residue_regions([text(identity) for identity in text_feature_ids])
    def nearby_lines(geometry,margin,short_only=False):
        x0,y0,x1,y1=geometry.buffer(margin).bounds
        query="SELECT f.feature_id FROM feature f JOIN line_attribute l USING(feature_id) WHERE f.project_id=? AND f.asset_id=? AND f.lifecycle_status='active' AND f.rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?)"
        if short_only:query+=' AND l.length_px<=12'
        selected=[]
        for row in connection.execute(query,(project_id,asset_id,x0,x1,y0,y1)):
            identity=row[0]
            if identity not in lines:lines[identity]=load_feature(connection,identity)
            if shape(lines[identity]['geometry']).distance(geometry)<=margin:selected.append(identity)
        return selected
    # Stroke margins are capped at three; independent wide strokes can still
    # protect a face. Aggregate widths without decoding unrelated geometries.
    width=connection.execute("SELECT MAX(MAX(l.stroke_width_px,COALESCE(json_extract(l.style_override,'$.stroke_width_px'),0))) FROM line_attribute l JOIN feature f USING(feature_id) WHERE f.project_id=? AND f.asset_id=? AND f.lifecycle_status='active'",(project_id,asset_id)).fetchone()[0] or 1
    style_width=connection.execute("SELECT MAX(stroke_width_px) FROM style WHERE project_id=? AND feature_type='line'",(project_id,)).fetchone()[0] or 1
    margin=max(3.,float(width)/2,float(style_width)/2)
    discovery=set()
    for region in regions:
        geometry=region['geometry'];discovery.update(nearby_lines(geometry,3.))
        nearby_lines(geometry,margin)
        x0,y0,x1,y1=geometry.bounds
        for row in connection.execute("SELECT f.geometry_wkb FROM feature f WHERE f.project_id=? AND f.asset_id=? AND f.feature_type='face' AND f.lifecycle_status='active' AND f.rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?)",(project_id,asset_id,x0,x1,y0,y1)):
            face=from_wkb(row[0])
            height=region['character_height_px'] if region['text'].get('detected_quad_px') else max(1,float(region['text'].get('font_size_px',12))/.8)
            if face.area<geometry.area*.8 and face.area<=max(120,height**2*2) and face.intersects(geometry):nearby_lines(face,margin)
    # Dash inference compares short runs within at most 40 pixels. Two such
    # neighborhoods retain every trio that could mark a local stroke semantic.
    for identity in discovery:
        geometry=shape(lines[identity]['geometry'])
        if geometry.length<=12:nearby_lines(geometry,80.,True)
    # Shared owners may lie at another end of a long source. Keep their exact
    # source footprints for ambiguous ownership and geological symbol guards.
    for identity in discovery:
        geometry=shape(lines[identity]['geometry']).buffer(3.);x0,y0,x1,y1=geometry.bounds
        for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active' AND rowid IN (SELECT id FROM text_ocr_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_display_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?)",(project_id,asset_id,x0,x1,y0,y1,x0,x1,y0,y1)):
            text(row[0])
            # Indexed bounds overselect safely; source polygon filtering happens
            # in the shared stroke ownership tree.
    styles={row['style_id']:dict(row) for row in connection.execute("SELECT * FROM style WHERE project_id=? AND feature_type='line' ORDER BY style_id",(project_id,))}
    layer=connection.execute("SELECT default_style_id FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type='line'",(project_id,asset_id)).fetchone()
    bindings={}
    for identity in lines:
        row=connection.execute('SELECT style_id FROM feature_style WHERE feature_id=?',(identity,)).fetchone()
        if row:bindings[identity]=row[0]
    source,path=_raster_source(connection,asset)
    return {'unassigned_ocr_candidates':[],'asset':asset,'lines':[lines[identity] for identity in sorted(lines)],'texts':[texts[identity] for identity in sorted(texts)],'groups':[],'styles':styles,'style_bindings':bindings,'default_style_id':layer[0] if layer else None,'raster_source':source,'_raster_path':path}


def _raster_source(connection, asset):
    """Hash the actual local original so an externally changed image invalidates previews."""
    database = next((row[2] for row in connection.execute('PRAGMA database_list') if row[1] == 'main'), '')
    if not database:
        return {'status':'unavailable'}, None
    directory = Path(database).resolve().parents[1]
    path = (directory / asset['raster_rel_path']).resolve()
    if not path.is_relative_to(directory):
        return {'status':'unavailable'}, None
    try:
        from mapvector.application.residue_policy import raster_sha256
        actual = raster_sha256(path)
    except OSError:
        return {'status':'unavailable'}, str(path)
    return {'status':'available' if actual == asset['raster_sha256'] else 'mismatch', 'sha256':actual}, str(path)


def _raster_image(materialized):
    if materialized.get('raster_source', {}).get('status') != 'available':
        return None
    try:
        image = Image.open(materialized['_raster_path'])
        asset = materialized['asset']
        if image.size != (asset['width_px'], asset['height_px']) or image.size[0] * image.size[1] > MAX_RASTER_IMAGE_PIXELS:
            image.close()
            return None
        return image
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def _public(candidate):
    return {key:copy.deepcopy(value) for key,value in candidate.items() if not key.startswith('_')}


def _decisions(connection,project_id,asset_id):
    return {row['candidate_id']:dict(row) for row in connection.execute('SELECT * FROM line_check_decision WHERE project_id=? AND asset_id=?',(project_id,asset_id))}


def _shared_status(connection,project_id,asset_id,candidate):
    candidate['manually_confirmed']=candidate['kind']=='text_stroke' and bool(candidate['feature_ids']) and all(is_confirmed(connection,project_id,asset_id,fid) for fid in candidate['feature_ids'])
    candidate['_shared_kept']=candidate_is_kept(connection,project_id,asset_id,candidate)
    pairs=[decision_for(connection,project_id,asset_id,text_id,fid) for text_id in candidate.get('reference_text_ids',[]) for fid in candidate['feature_ids']] if candidate['kind']=='text_stroke' else []
    candidate['_shared_reopened']=bool(pairs) and all(value=='reopen' for value in pairs)


def _status(candidate, decisions):
    if candidate.get("_shared_kept"):return "kept"
    if candidate.get('manually_confirmed'):return 'pending'
    if candidate.get("_shared_reopened"):return candidate["status"]
    decision=decisions.get(candidate['candidate_id'])
    if decision and decision['evidence_sha256']==candidate['_evidence_sha256']:
        return 'kept' if decision['decision']=='keep' else 'pending'
    return candidate['status']


def history(connection,project_id,asset_id):
    rows=connection.execute("""SELECT operation_id,result_revision,created_at,result_summary FROM operation
        WHERE project_id=? AND operation_type='apply_line_check' AND operation_status='applied'
        AND json_extract(result_summary,'$.review_summary.line_check.asset_id')=? ORDER BY result_revision DESC LIMIT 200""",(project_id,asset_id))
    result=[]
    for row in rows:
        report=json.loads(row['result_summary'])['review_summary']['line_check']
        for candidate in report.get('candidates',[]):
            result.append({**candidate,'status':'applied','operation_id':row['operation_id'],'result_revision':row['result_revision'],'created_at':row['created_at']})
    return result


def create_preview(database,project_id,request):
    # Close the consistent read snapshot before CPU work or cache mutation.
    with database.read() as connection:
        connection.execute('BEGIN')
        materialized=snapshot(connection,project_id,request.asset_id,request.base_revision)
        previous=history(connection,project_id,request.asset_id)
    if request.mode == 'manual' and not set(request.manual_feature_ids).issubset(line['feature_id'] for line in materialized['lines']):
        raise CommandConflict('SELECTION_SCOPE_INVALID')
    image = _raster_image(materialized)
    try:
        result=diagnose(materialized,request,image,candidate_limit=None)
    finally:
        if image is not None:image.close()
    expires=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()
    stored={'preview_id':str(uuid4()),'asset_id':request.asset_id,'base_revision':request.base_revision,
            'algorithm_revision':ALGORITHM_REVISION,'expires_at':expires,'input_sha256':digest(materialized),
            'mode':request.mode,'request_sha256':digest(request.model_dump(mode='json')),
            'candidates':result['candidates'],'history':previous,'summary':result['summary']}
    with database.transaction() as connection:
        _scope(connection,project_id,request.asset_id,request.base_revision)
        decisions=_decisions(connection,project_id,request.asset_id)
        for item in stored['candidates']:_shared_status(connection,project_id,request.asset_id,item)
        # Cache intrinsic geometry statuses. A live keep decision is valid only
        # for its matching evidence and must not become the cached fallback.
        connection.execute('INSERT INTO edit_preview VALUES (?,?,?,?,?,?,?,?)',(stored['preview_id'],project_id,request.asset_id,request.base_revision,expires,request.model_dump_json(),json.dumps(stored,ensure_ascii=False),stored['input_sha256']))
    visible=stored['candidates'][:MAX_CANDIDATES]
    return {**stored,'candidates':[{**_public(item),'status':_status(item,decisions)} for item in visible],
            'summary':{**stored['summary'],'returned_count':len(visible),
                       'truncated':len(visible)<len(stored['candidates'])}}


def _validated_preview(connection,project_id,asset_id,base_revision,preview_id):
    _scope(connection,project_id,asset_id,base_revision)
    row=connection.execute('SELECT * FROM edit_preview WHERE preview_id=? AND project_id=? AND asset_id=?',(preview_id,project_id,asset_id)).fetchone()
    if row is None or row['base_revision']!=base_revision or datetime.fromisoformat(row['expires_at'])<=datetime.now(timezone.utc):raise CommandConflict('PREVIEW_STALE')
    report=json.loads(row['result_json'])
    if report.get('algorithm_revision')!=ALGORITHM_REVISION or report.get('asset_id')!=asset_id:raise CommandConflict('PREVIEW_TYPE_MISMATCH')
    if digest(snapshot(connection,project_id,asset_id,base_revision))!=row['input_sha256']:raise CommandConflict('PREVIEW_STALE')
    preview_request = LineCheckRequest.model_validate_json(row['request_json'])
    if report.get('request_sha256') != digest(preview_request.model_dump(mode='json')) or report.get('mode') != preview_request.mode:
        raise CommandConflict('PREVIEW_TYPE_MISMATCH')
    return report,preview_request


def candidate_page(database,project_id,asset_id,base_revision,preview_id,kind,filter,offset=0,limit=25):
    with database.read() as connection:
        connection.execute('BEGIN')
        report,_=_validated_preview(connection,project_id,asset_id,base_revision,preview_id)
        decisions=_decisions(connection,project_id,asset_id)
        for item in report['candidates']:_shared_status(connection,project_id,asset_id,item)
        current=sorted(report['candidates'],key=lambda item:(item['kind'],bool(item['blocked_reasons']),item['candidate_id']))
        previous=sorted(report['history'],key=lambda item:(-item['result_revision'],item['operation_id'],item['candidate_id']))
        rows=[{**item,'status':_status(item,decisions)} for item in current]
        rows.extend(previous)
        selected=[item for item in rows if item['kind']==kind and (filter=='all' or item['status']==filter)]
        return {'preview_id':report['preview_id'],'asset_id':report['asset_id'],
                'base_revision':report['base_revision'],'expires_at':report['expires_at'],
                'kind':kind,'filter':filter,'offset':offset,'limit':limit,'total':len(selected),
                'items':[_public(item) for item in selected[offset:offset+limit]]}


def _validated_report(connection,project_id,request):
    report,preview_request=_validated_preview(connection,project_id,request.asset_id,request.base_revision,request.preview_id)
    by_id={item['candidate_id']:item for item in report['candidates']}
    if any(identity not in by_id for identity in request.candidate_ids):raise CommandConflict('LINE_CHECK_CANDIDATE_INVALID')
    for identity in request.candidate_ids:
        candidate = by_id[identity]
        if candidate.get('connection_mode', 'automatic') == 'manual':
            authorization = candidate.get('_plan', {}).get('manual_authorization', {})
            expected = {'mode':'manual','feature_ids':sorted(preview_request.manual_feature_ids),
                        'connector_sha256':digest(candidate['connectors'])}
            if (preview_request.mode != 'manual' or candidate['kind'] != 'join_gap'
                    or sorted(candidate['feature_ids']) != expected['feature_ids'] or authorization != expected):
                raise CommandConflict('PREVIEW_TYPE_MISMATCH')
        elif preview_request.mode != 'automatic':raise CommandConflict('PREVIEW_TYPE_MISMATCH')
    return report,[by_id[identity] for identity in request.candidate_ids]


def decide(database,project_id,request):
    with database.transaction() as connection:
        _,selected=_validated_report(connection,project_id,request)
        # Validate the whole batch before recording any manual authorization.
        if request.decision=='confirm':
            for candidate in selected:
                if candidate['kind']!='text_stroke' or candidate['allowed_action']!='isolate':raise CommandConflict('LINE_CHECK_ACTION_MISMATCH')
                if 'RASTER_SOURCE_MISMATCH' in candidate['blocked_reasons']:raise CommandConflict('LINE_CHECK_CANDIDATE_BLOCKED',{'reason_codes':['RASTER_SOURCE_MISMATCH']})
                for fid in candidate['feature_ids']:
                    feature=load_feature(connection,fid)
                    if (feature['project_id'],feature['asset_id'],feature['feature_type'],feature['lifecycle_status'])!=(project_id,request.asset_id,'line','active'):raise CommandConflict('SELECTION_SCOPE_INVALID')
        timestamp=datetime.now(timezone.utc).isoformat()
        for candidate in selected:
            if candidate['kind']=='text_stroke':
                for fid in candidate['feature_ids']:
                    if request.decision=='confirm':write_confirmation(connection,project_id,request.asset_id,fid,request.preview_id,timestamp)
                    else:
                        from mapvector.application.residue_policy import write_object_decision
                        write_object_decision(connection,project_id,request.asset_id,fid,request.decision,request.preview_id,timestamp)
                if request.decision!='confirm':
                    for text_id in candidate['reference_text_ids']:
                        for fid in candidate['feature_ids']:write_decision(connection,project_id,request.asset_id,text_id,fid,request.decision,request.preview_id,timestamp)
            # The shared confirmation owns authorization. Reopen this entrance's
            # previous keep using its existing keep/reopen database contract.
            stored_decision='reopen' if request.decision=='confirm' else request.decision
            connection.execute('INSERT INTO line_check_decision VALUES (?,?,?,?,?,?,?) ON CONFLICT(project_id,asset_id,candidate_id) DO UPDATE SET evidence_sha256=excluded.evidence_sha256,decision=excluded.decision,updated_at=excluded.updated_at,preview_id=excluded.preview_id',
                (project_id,request.asset_id,candidate['candidate_id'],candidate['_evidence_sha256'],stored_decision,timestamp,request.preview_id))
    return {'candidate_ids':request.candidate_ids,'decision':request.decision}


def _validate_connector_batch(selected, originals):
    """Protect the final combined topology before planning any mutation."""
    bridges = []
    for candidate in selected:
        half_width = max(originals[identity]['stroke_width_px'] for identity in candidate['feature_ids']) / 2
        for connector in candidate['connectors']:
            bridges.append((candidate['candidate_id'], LineString(connector), half_width))
    if len(bridges) < 2:return
    tree = STRtree([bridge[1] for bridge in bridges])
    largest = max(bridge[2] for bridge in bridges)
    for index, (identity, geometry, half_width) in enumerate(bridges):
        for other in tree.query(geometry.buffer(half_width + largest + 1e-9)):
            other = int(other)
            if other <= index or bridges[other][0] == identity:continue
            other_identity, other_geometry, other_half_width = bridges[other]
            if geometry.distance(other_geometry) <= half_width + other_half_width + 1e-9:
                raise CommandConflict('LINE_CHECK_CANDIDATE_BLOCKED',
                    {'candidate_ids':[identity,other_identity], 'reason_codes':['CROSSES_SELECTED_CONNECTOR']})


def plan_changes(connection,project_id,command,timestamp):
    report,selected=_validated_report(connection,project_id,command)
    if set(command.verified_candidate_ids)!=set(command.candidate_ids):raise CommandConflict('LINE_CHECK_REVIEW_REQUIRED')
    decisions=_decisions(connection,project_id,command.asset_id)
    seen=set()
    for candidate in selected:
        _shared_status(connection,project_id,command.asset_id,candidate)
        if candidate['allowed_action']!=command.action:raise CommandConflict('LINE_CHECK_ACTION_MISMATCH')
        confirmed_isolation=command.action=='isolate' and candidate['kind']=='text_stroke' and candidate['manually_confirmed']
        if candidate['blocked_reasons'] and (not confirmed_isolation or 'RASTER_SOURCE_MISMATCH' in candidate['blocked_reasons']):raise CommandConflict('LINE_CHECK_CANDIDATE_BLOCKED',{'candidate_id':candidate['candidate_id'],'reason_codes':candidate['blocked_reasons']})
        if candidate_is_kept(connection,project_id,command.asset_id,candidate) or _status(candidate,decisions)=='kept':raise CommandConflict('LINE_CHECK_CANDIDATE_KEPT')
        if seen.intersection(candidate['feature_ids']):raise CommandConflict('LINE_CHECK_SELECTION_OVERLAP')
        seen.update(candidate['feature_ids'])
        if command.action=='join':
            members=set(candidate['feature_ids'])
            for identity in members:
                related=connection.execute('SELECT group_id FROM group_member WHERE feature_id=?',(identity,)).fetchall()
                for row in related:
                    if any(member[0] not in members for member in connection.execute('SELECT feature_id FROM group_member WHERE group_id=?',(row[0],))):
                        raise CommandConflict('LINE_CHECK_CANDIDATE_BLOCKED',{'reason_codes':['EXISTING_GROUP_MEMBERSHIP']})
    # Validate all candidates before planning any feature or relation mutation.
    originals={identity:load_feature(connection,identity) for identity in seen}
    for feature in originals.values():
        if (feature['project_id'],feature['asset_id'],feature['feature_type'],feature['lifecycle_status'])!=(project_id,command.asset_id,'line','active'):raise CommandConflict('SELECTION_SCOPE_INVALID')
    for candidate in selected:
        # Explicit manual continuation authorizes joining these two members only;
        # Geometry protections remain mandatory for joining and grouping.
        if candidate.get('connection_mode', 'automatic') == 'manual' and command.action == 'join':continue
        if command.action=='isolate' and candidate['kind']=='text_stroke' and candidate['manually_confirmed']:continue
        if any(originals[identity]['source_type'] == 'manual' or originals[identity]['line_role'] == 'split' for identity in candidate['feature_ids']):
            raise CommandConflict('LINE_CHECK_CANDIDATE_BLOCKED')
    if command.action == 'join':_validate_connector_batch(selected, originals)
    changes=[];relations=[];groups=[];lineages=[]
    revision=command.base_revision+1
    for candidate in selected:
        identities=candidate['feature_ids']
        if command.action=='group':
            for identity in identities:
                for membership in connection.execute('SELECT * FROM group_member WHERE feature_id=?',(identity,)).fetchall():
                    gid=membership['group_id']
                    members=[row[0] for row in connection.execute('SELECT feature_id FROM group_member WHERE group_id=?',(gid,))]
                    if members!=[identity]:raise CommandConflict('LINE_CHECK_CANDIDATE_BLOCKED',{'reason_codes':['EXISTING_GROUP_MEMBERSHIP']})
                    old=dict(membership);relations.append(('group_member',gid+':'+identity,old,None))
                    if not any(group['group_id']==gid for group in groups):groups.append(dict(connection.execute('SELECT * FROM logical_group WHERE group_id=?',(gid,)).fetchone()))
            group={'group_id':str(uuid4()),'project_id':project_id,'asset_id':command.asset_id,'feature_type':'line','group_name':'线检查虚线编组','revision':revision}
            groups.append(group);relations.append(('logical_group',group['group_id'],None,group))
            for identity in identities:relations.append(('group_member',group['group_id']+':'+identity,None,{'group_id':group['group_id'],'feature_id':identity}))
        elif command.action=='isolate':
            regions=candidate.get('evidence',{}).get('source_regions',[])
            region=None
            footprints=[]
            for evidence_region in regions:
                try:
                    footprint=Polygon(evidence_region['polygon_px'])
                    if footprint.is_valid and not footprint.is_empty and footprint.area>0:footprints.append(footprint)
                except (KeyError,ValueError,TypeError):pass
            if footprints:
                from shapely import union_all
                region=union_all(footprints)
            crossing=region is not None and any(not region.buffer(1e-6).covers(shape(originals[identity]['geometry'])) for identity in identities)
            if crossing:
                from mapvector.application.residue_cleanup import plan_changes as plan_residue_changes
                display={'bounds_px':region.bounds,'region_geometry':mapping(region),'face_feature_ids':[],
                         'line_feature_ids':identities,'protected_line_feature_ids':[]}
                planned,split_sources=plan_residue_changes([originals[identity] for identity in identities],display,None,revision,timestamp,candidate['reference_text_ids'][0] if len(candidate['reference_text_ids'])==1 else None,identities)
                if not planned:raise CommandConflict('PREVIEW_SCOPE_MISMATCH')
                changes.extend(planned)
                for target,source in split_sources.items():
                    lineages.append((source,target,{key:value for key,value in originals[source].items() if key!='geometry'}))
                    binding=connection.execute('SELECT style_id FROM feature_style WHERE feature_id=?',(source,)).fetchone()
                    if binding:relations.append(('feature_style',target,None,{'feature_id':target,'style_id':binding[0]}))
            else:
                for identity in identities:
                    old=originals[identity];new={**copy.deepcopy(old),'lifecycle_status':'isolated','isolation_reason':'text_residue','revision':revision,'updated_at':timestamp}
                    if len(candidate['reference_text_ids'])==1:new['associated_text_feature_id']=candidate['reference_text_ids'][0]
                    changes.append((old,new))
        else:
            plan=candidate.get('_plan',{});order=plan.get('ordered_feature_ids',[])
            if set(order)!=set(identities) or len(order)!=len(identities):raise CommandConflict('PREVIEW_TYPE_MISMATCH')
            geometry=LineString(plan['coordinates']);asset=connection.execute('SELECT width_px,height_px FROM asset WHERE asset_id=?',(command.asset_id,)).fetchone()
            if geometry.is_empty or not geometry.is_valid or not geometry.is_simple or not(0<=geometry.bounds[0]<=geometry.bounds[2]<=asset['width_px'] and 0<=geometry.bounds[1]<=geometry.bounds[3]<=asset['height_px']):raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
            keep=plan.get('keep_feature_id',order[0])
            if keep not in identities:raise CommandConflict('PREVIEW_TYPE_MISMATCH')
            old=originals[keep];bounds=geometry.bounds
            new={**copy.deepcopy(old),'geometry':json.loads(json.dumps(mapping(geometry))),'geometry_type':'LineString','bbox_min_x_px':bounds[0],'bbox_min_y_px':bounds[1],
                 'bbox_max_x_px':bounds[2],'bbox_max_y_px':bounds[3],'length_px':geometry.length,'revision':revision,'updated_at':timestamp}
            if any(originals[identity]['source_type'] == 'manual' for identity in identities):new['source_type'] = 'manual'
            changes.append((old,new))
            for identity in (identity for identity in order if identity!=keep):
                old=originals[identity];changes.append((old,{**copy.deepcopy(old),'lifecycle_status':'superseded','revision':revision,'updated_at':timestamp}))
                lineages.append((identity,keep,{key:value for key,value in old.items() if key!='geometry'}))
    evidence={'asset_id':command.asset_id,'preview_id':command.preview_id,'algorithm_revision':report['algorithm_revision'],
              'candidate_ids':command.candidate_ids,'verified_candidate_ids':command.verified_candidate_ids,'action':command.action,'candidates':[_public(item) for item in selected]}
    return changes,relations,groups,lineages,evidence

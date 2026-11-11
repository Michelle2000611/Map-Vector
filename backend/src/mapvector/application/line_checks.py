"""Materialized read snapshots, short preview writes, and line-only change plans."""
import copy
import json
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely import from_wkb
from shapely.geometry import LineString, mapping

from mapvector.application.ports import load_feature
from mapvector.application.review import text_decision
from mapvector.domain.commands import UUIDString
from mapvector.domain.errors import CommandConflict
from mapvector.geometry.line_checks import ALGORITHM_REVISION, diagnose, digest


class LineCheckRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    asset_id: UUIDString
    base_revision: int = Field(ge=0, le=9007199254740990, strict=True)
    max_gap_px: float = Field(default=8, ge=0, le=50)
    angle_tolerance_deg: float = Field(default=15, ge=1, le=45)
    max_short_length_px: float = Field(default=12, ge=1, le=100)


class LineCheckDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    asset_id: UUIDString
    base_revision: int = Field(ge=0, le=9007199254740990, strict=True)
    preview_id: UUIDString
    candidate_ids: list[str] = Field(min_length=1, max_length=2000)
    decision: Literal['keep', 'reopen']

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
    allowed_action: Literal['join', 'isolate', 'group']


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
    candidates: list[LineCheckCandidate]
    history: list[LineCheckHistory]
    summary: dict[str, int | bool]


class LineCheckDecisionResult(BaseModel):
    candidate_ids: list[str]
    decision: Literal['keep', 'reopen']


def _scope(connection, project_id, asset_id, revision):
    current = connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()
    if current is None: raise KeyError(project_id)
    if current['working_revision'] != revision: raise CommandConflict('REVISION_CONFLICT', {'working_revision':current['working_revision']})
    if current['current_asset_id'] != asset_id: raise CommandConflict('ASSET_RESULT_MISMATCH')
    asset = connection.execute('SELECT asset_id,project_id,width_px,height_px,raster_sha256 FROM asset WHERE asset_id=? AND project_id=?',(asset_id,project_id)).fetchone()
    if asset is None: raise CommandConflict('ASSET_RESULT_MISMATCH')
    return dict(asset)


def snapshot(connection, project_id, asset_id, revision):
    asset = _scope(connection,project_id,asset_id,revision)
    # Bulk load lines. No faces and no image data are loaded for line diagnostics.
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
    return {'asset':asset,'lines':lines,'texts':texts,'groups':groups,'styles':styles,'style_bindings':bindings,'default_style_id':layer['default_style_id'] if layer else None}


def _public(candidate):
    return {key:copy.deepcopy(value) for key,value in candidate.items() if not key.startswith('_')}


def _decisions(connection,project_id,asset_id):
    return {row['candidate_id']:dict(row) for row in connection.execute('SELECT * FROM line_check_decision WHERE project_id=? AND asset_id=?',(project_id,asset_id))}


def _status(candidate, decisions):
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
    result=diagnose(materialized,request)
    expires=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()
    stored={'preview_id':str(uuid4()),'asset_id':request.asset_id,'base_revision':request.base_revision,
            'algorithm_revision':ALGORITHM_REVISION,'expires_at':expires,'input_sha256':digest(materialized),
            'candidates':result['candidates'],'history':previous,'summary':result['summary']}
    with database.transaction() as connection:
        _scope(connection,project_id,request.asset_id,request.base_revision)
        decisions=_decisions(connection,project_id,request.asset_id)
        for item in stored['candidates']:item['status']=_status(item,decisions)
        connection.execute('INSERT INTO edit_preview VALUES (?,?,?,?,?,?,?,?)',(stored['preview_id'],project_id,request.asset_id,request.base_revision,expires,request.model_dump_json(),json.dumps(stored,ensure_ascii=False),stored['input_sha256']))
    return {**stored,'candidates':[_public(item) for item in stored['candidates']]}


def _validated_report(connection,project_id,request):
    _scope(connection,project_id,request.asset_id,request.base_revision)
    row=connection.execute('SELECT * FROM edit_preview WHERE preview_id=? AND project_id=? AND asset_id=?',(request.preview_id,project_id,request.asset_id)).fetchone()
    if row is None or row['base_revision']!=request.base_revision or datetime.fromisoformat(row['expires_at'])<=datetime.now(timezone.utc):raise CommandConflict('PREVIEW_STALE')
    report=json.loads(row['result_json'])
    if report.get('algorithm_revision')!=ALGORITHM_REVISION or report.get('asset_id')!=request.asset_id:raise CommandConflict('PREVIEW_TYPE_MISMATCH')
    if digest(snapshot(connection,project_id,request.asset_id,request.base_revision))!=row['input_sha256']:raise CommandConflict('PREVIEW_STALE')
    by_id={item['candidate_id']:item for item in report['candidates']}
    if any(identity not in by_id for identity in request.candidate_ids):raise CommandConflict('LINE_CHECK_CANDIDATE_INVALID')
    return report,[by_id[identity] for identity in request.candidate_ids]


def decide(database,project_id,request):
    with database.transaction() as connection:
        _,selected=_validated_report(connection,project_id,request)
        timestamp=datetime.now(timezone.utc).isoformat()
        for candidate in selected:
            connection.execute('INSERT INTO line_check_decision VALUES (?,?,?,?,?,?,?) ON CONFLICT(project_id,asset_id,candidate_id) DO UPDATE SET evidence_sha256=excluded.evidence_sha256,decision=excluded.decision,updated_at=excluded.updated_at,preview_id=excluded.preview_id',
                (project_id,request.asset_id,candidate['candidate_id'],candidate['_evidence_sha256'],request.decision,timestamp,request.preview_id))
    return {'candidate_ids':request.candidate_ids,'decision':request.decision}


def plan_changes(connection,project_id,command,timestamp):
    report,selected=_validated_report(connection,project_id,command)
    if set(command.verified_candidate_ids)!=set(command.candidate_ids):raise CommandConflict('LINE_CHECK_REVIEW_REQUIRED')
    decisions=_decisions(connection,project_id,command.asset_id)
    seen=set()
    for candidate in selected:
        if candidate['allowed_action']!=command.action:raise CommandConflict('LINE_CHECK_ACTION_MISMATCH')
        if candidate['blocked_reasons']:raise CommandConflict('LINE_CHECK_CANDIDATE_BLOCKED',{'candidate_id':candidate['candidate_id'],'reason_codes':candidate['blocked_reasons']})
        if _status(candidate,decisions)=='kept':raise CommandConflict('LINE_CHECK_CANDIDATE_KEPT')
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
            changes.append((old,new))
            for identity in (identity for identity in order if identity!=keep):
                old=originals[identity];changes.append((old,{**copy.deepcopy(old),'lifecycle_status':'superseded','revision':revision,'updated_at':timestamp}))
                lineages.append((identity,keep,{key:value for key,value in old.items() if key!='geometry'}))
    evidence={'asset_id':command.asset_id,'preview_id':command.preview_id,'algorithm_revision':report['algorithm_revision'],
              'candidate_ids':command.candidate_ids,'verified_candidate_ids':command.verified_candidate_ids,'action':command.action,'candidates':[_public(item) for item in selected]}
    return changes,relations,groups,lineages,evidence

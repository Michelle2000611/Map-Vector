"""Preview-bound, explicit polygon ownership transfers with ordinary edit history."""
import copy
import hashlib
import json
import math
import warnings
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np
import rasterio
from affine import Affine
from PIL import ImageColor
from pydantic import BaseModel, ConfigDict, Field
from rasterio.errors import NotGeoreferencedWarning
from rasterio.features import rasterize
from rasterio.windows import Window
from shapely import coverage_is_valid, union_all
from shapely.geometry import box, mapping, shape

from mapvector.application.ports import load_feature
from mapvector.domain.commands import UUIDString
from mapvector.domain.errors import CommandConflict
from mapvector.geometry.face_repairs import diagnose, narrow_metrics
from mapvector.geometry.raster_mask import valid_region


ALGORITHM_REVISION='vector_face_repair_review_v4'


class FaceRepairRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:UUIDString
    feature_id:UUIDString
    width_px:float=Field(default=2,ge=1,le=4)
    min_length_px:float=Field(default=12,ge=4,le=1000)
    max_area_px2:float=Field(default=150,gt=0,le=2000)


def _scope(connection,project_id,asset_id,bounds):
    x0,y0,x1,y1=bounds
    rows=connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated') AND rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_display_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) ORDER BY feature_id",(project_id,asset_id,x0,x1,y0,y1,x0,x1,y0,y1))
    return [load_feature(connection,row[0]) for row in rows]


def _maximum_stroke(connection,project_id,asset_id):
    return float(connection.execute("SELECT COALESCE(MAX(l.stroke_width_px),0) FROM feature f JOIN line_attribute l USING(feature_id) WHERE f.project_id=? AND f.asset_id=? AND f.lifecycle_status='active'",(project_id,asset_id)).fetchone()[0])


def _digest(features,region,maximum_stroke,raster_inputs=None,parameters=None):
    payload={'features':features,'valid_region':mapping(region),'maximum_stroke_px':maximum_stroke,'raster_inputs':raster_inputs or [],
             'algorithm_revision':ALGORITHM_REVISION,'parameters':parameters}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _region(asset,directory):
    return valid_region(directory/asset['raster_rel_path']).intersection(box(0,0,asset['width_px'],asset['height_px']))


def _merge_owners(hole,source_id,active):
    """Return whole active owners only when they exactly partition one hole."""
    owners={fid:geometry for fid,geometry in active.items() if geometry.intersection(hole).area>1e-7}
    if not owners or source_id in owners:return []
    geometries=list(owners.values())
    if any(geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon','MultiPolygon') or not hole.covers(geometry) for geometry in geometries):return []
    combined=union_all(geometries)
    if not combined.equals(hole) or not bool(coverage_is_valid(geometries)) or abs(sum(geometry.area for geometry in geometries)-combined.area)>1e-7:return []
    return sorted(owners)


def _references(candidate,features):
    """Return spatial intersections only; these are not semantic matches."""
    lines=[];texts=[]
    for feature in features:
        if feature['lifecycle_status']!='active':continue
        if feature['feature_type']=='line' and shape(feature['geometry']).buffer(feature['stroke_width_px']/2).intersects(candidate):lines.append(feature['feature_id'])
        elif feature['feature_type']=='text' and feature.get('display_bbox_px') and box(*feature['display_bbox_px']).intersects(candidate):texts.append(feature['feature_id'])
    return sorted(lines),sorted(texts)


def _hole_count(geometry):
    parts=list(geometry.geoms) if geometry.geom_type=='MultiPolygon' else [geometry]
    return sum(len(part.interiors) for part in parts)


def _part_count(geometry):
    return len(geometry.geoms) if geometry.geom_type=='MultiPolygon' else 1


def _read_raster_window(path,bounds):
    """Read only a bounded original-pixel window; never resample the evidence."""
    x0,y0,x1,y1=bounds
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',NotGeoreferencedWarning)
            with rasterio.open(path) as raster:
                values=raster.read(window=Window(x0,y0,x1-x0,y1-y0))
                roles=tuple(value.name for value in raster.colorinterp)
        if values.shape[1:]!=(y1-y0,x1-x0) or not values.size:return None
        valid=np.ones(values.shape[1:],dtype=bool)
        if 'alpha' in roles:valid&=values[roles.index('alpha')]>0
        if all(channel in roles for channel in ('red','green','blue')):
            rgb=np.moveaxis(values[[roles.index(channel) for channel in ('red','green','blue')]],0,-1)
        else:rgb=np.repeat(values[0,:,:,None],3,axis=2)
        signature=hashlib.sha256(str((values.shape,str(values.dtype),roles)).encode()+values.tobytes()).hexdigest()
        return rgb,valid,signature
    except (OSError,rasterio.errors.RasterioIOError,ValueError):return None


def _color_rgb(value):
    try:return np.asarray(ImageColor.getrgb(value)[:3],dtype=float)
    except (ValueError,TypeError):return None


def _local_raster_evidence(path,asset,candidate,source,source_color,options,width_px):
    """Color/stroke evidence informs review and ranking, never ownership itself."""
    x0,y0,x1,y1=candidate.bounds;pad=max(3,int(math.ceil(width_px*2)))
    bounds=[max(0,math.floor(x0)-pad),max(0,math.floor(y0)-pad),min(asset['width_px'],math.ceil(x1)+pad),min(asset['height_px'],math.ceil(y1)+pad)]
    w,h=bounds[2]-bounds[0],bounds[3]-bounds[1]
    evidence={'status':'ambiguous','sample_count':0,'bounds_px':bounds,'reason_codes':[]}
    if w<=0 or h<=0 or w>512 or h>512:
        evidence.update(status='unavailable',reason_codes=['RASTER_EVIDENCE_WINDOW_LIMIT'])
        return evidence
    read=_read_raster_window(path,bounds)
    if read is None:
        evidence.update(status='unavailable',sha256='unavailable',reason_codes=['RASTER_EVIDENCE_UNAVAILABLE'])
        return evidence
    rgb,valid,signature=read;evidence['sha256']=signature
    transform=Affine.translation(bounds[0],bounds[1])
    def samples(geometry):
        mask=rasterize([(geometry,1)],out_shape=(h,w),transform=transform,dtype='uint8').astype(bool)&valid
        return rgb[mask].astype(float)
    values=samples(candidate)
    evidence['sample_count']=len(values)
    if len(values)<4:
        evidence['reason_codes']=['RASTER_INSUFFICIENT_SAMPLES'];return evidence
    median=np.median(values,axis=0)
    evidence['median_rgb']=[float(value) for value in median]
    dark_fraction=float(np.mean((values.max(axis=1)<100)&((values.max(axis=1)-values.min(axis=1))<60)))
    evidence['dark_fraction']=dark_fraction
    source_rgb=_color_rgb(source_color)
    source_samples=samples(source.difference(candidate))
    source_median=np.median(source_samples,axis=0) if len(source_samples)>=4 else None
    credible_source=source_rgb is not None and source_median is not None and np.linalg.norm(source_median-source_rgb)<=35
    evidence['source_context_supported']=bool(credible_source)
    if source_rgb is not None:evidence['source_color_distance']=float(np.linalg.norm(median-source_rgb))
    for option in options:
        color=_color_rgb(option['color'])
        if color is not None:option['color_distance']=float(np.linalg.norm(median-color))
    supported=[option for option in options if option.get('color_distance',math.inf)<=35]
    if dark_fraction>=.6:
        evidence.update(status='stroke_supported',reason_codes=['RASTER_DARK_STROKE'])
    elif supported and evidence.get('source_color_distance',0)>50:
        evidence.update(status='receiver_color_supported',reason_codes=['RASTER_MATCHES_RECEIVER_COLOR'])
    elif credible_source and float(np.linalg.norm(median-source_median))>60:
        evidence.update(status='distinct_region',reason_codes=['RASTER_COLOR_CONTRADICTS_SOURCE'])
    else:evidence['reason_codes']=['RASTER_EVIDENCE_AMBIGUOUS']
    return evidence


def _enrich_evidence(item,candidate,geometry,target,asset,directory,width_px,features=()):
    options=item['receiver_options']
    raster=_local_raster_evidence(directory/asset['raster_rel_path'],asset,candidate,geometry,target['fill_color'],options,width_px)
    reasons=item['review_reason_codes']
    if item.get('discovery_method')=='vector_opening':reasons.append('VECTOR_APPENDAGE_SEMANTICS_UNCONFIRMED')
    distinct_hole=(raster['status']=='distinct_region' or raster['status']=='stroke_supported'
                   and raster.get('source_context_supported') and raster.get('source_color_distance',0)>60)
    if item['kind'] in ('void','occupied_hole') and distinct_hole:
        raster['status']='distinct_hole_region';reasons.append('RASTER_DISTINCT_HOLE_REGION')
    if item['kind']=='occupied_hole' and item.get('mergeable') and len(item.get('merging_feature_ids',[]))>1:
        # A whole-hole median can hide one real island among same-color owners.
        owner_ids=set(item['merging_feature_ids']);owner_evidence=[]
        for owner in features:
            if owner['feature_id'] not in owner_ids:continue
            local=_local_raster_evidence(directory/asset['raster_rel_path'],asset,shape(owner['geometry']),geometry,target['fill_color'],[],width_px)
            owner_evidence.append({'feature_id':owner['feature_id'],**local})
            distinct_owner=(local['status']=='distinct_region' or local['status']=='stroke_supported'
                            and local.get('source_context_supported') and local.get('source_color_distance',0)>60)
            if distinct_owner:
                reasons.append('RASTER_DISTINCT_HOLE_OWNER')
                raster['status']='distinct_hole_region'
        item['owner_raster_evidence']=owner_evidence
    item['review_reason_codes']=sorted(set(reasons));item['review_required']=bool(reasons)
    item['raster_evidence']=raster
    for option in options:
        edge_score=option['shared_edge_px']/max(candidate.length,1e-8)
        color_score=max(0.,1-option['color_distance']/math.sqrt(3*255**2)) if 'color_distance' in option else 0.
        option['recommendation_score']=float(.6*edge_score+.4*color_score)
        option['recommendation_reason_codes']=['SHARED_BOUNDARY']+(['RASTER_COLOR_DISTANCE'] if 'color_distance' in option else [])
    ranked=sorted(options,key=lambda option:(-option['recommendation_score'],option['feature_id']))
    item['recommended_receiver_id']=ranked[0]['feature_id'] if ranked and (len(ranked)==1 or ranked[0]['recommendation_score']-ranked[1]['recommendation_score']>.05) else None
    confirmable={'PROTECTED_LINE_OR_TEXT','OCCUPIED_HOLE_REQUIRES_MERGE','BOUNDARY_GAP_REQUIRES_REVIEW'}
    blocked=item.get('blocked_reason')
    # Whole owners already validated to exactly fill this internal hole need a
    # merge operation, not an additional human review unless actual risk exists.
    ownership_instruction=(item['kind']=='occupied_hole' and item.get('mergeable')
                           and blocked=='OCCUPIED_HOLE_REQUIRES_MERGE')
    item['risk_level']='blocked' if blocked and blocked not in confirmable else 'review' if item['review_required'] or blocked and not ownership_instruction else 'ready'
    item['evidence']={'reason_codes':sorted(set(item['review_reason_codes']+raster['reason_codes'])),
                      'geometry_method':item.get('discovery_method','complete_region'),'semantic_ownership_inferred':False}
    transfer=item['kind'] in ('spur','occupied_hole','boundary_gap')
    item['delta_geometry']={'removed':item['geometry'] if item['kind']=='spur' else None,'added':item['geometry'] if item['kind']!='spur' else None,'transferred':item['geometry'] if transfer else None}
    item['metrics']={'source_area_before_px2':float(geometry.area),'source_area_after_px2':float(geometry.area+(-candidate.area if item['kind']=='spur' else candidate.area)),
                     'changed_area_px2':float(candidate.area),'coverage_delta_px2':0. if transfer else float(candidate.area),
                     **{name:item[name] for name in ('width_px','length_px','attachment_width_px','attachment_count') if name in item}}


def _raster_inputs(candidates):
    evidence=[record for item in candidates for record in [item.get('raster_evidence',{}),*item.get('owner_raster_evidence',[])]]
    records={tuple(record['bounds_px']):record['sha256'] for record in evidence if 'sha256' in record}
    return [{'bounds_px':list(bounds),'sha256':records[bounds]} for bounds in sorted(records)]


def _current_raster_inputs(path,records):
    current=[]
    for record in records:
        read=_read_raster_window(path,record['bounds_px'])
        current.append({'bounds_px':record['bounds_px'],'sha256':read[2] if read else 'unavailable'})
    return current


def _diagnose_target(connection,project_id,asset_id,asset,directory,target,width_px,min_length_px,max_area_px2):
    """Per-face candidate generation shared by the single-face preview and the asset-wide scan."""
    geometry=shape(target['geometry'])
    if not geometry.is_valid or geometry.is_empty:raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
    maximum_stroke=_maximum_stroke(connection,project_id,asset_id)
    margin=float(maximum_stroke)/2+1
    bounds=list(geometry.buffer(margin).bounds);features=_scope(connection,project_id,asset_id,bounds)
    faces=[f for f in features if f['feature_type']=='face' and f['lifecycle_status']=='active']
    # Include the target: another component of the same multipart face may be
    # an existing island inside this component's ring and must stay occupied.
    ownership=[(f['feature_id'],shape(f['geometry'])) for f in faces]
    region=_region(asset,directory);candidates=diagnose(geometry,ownership,width_px,min_length_px,max_area_px2)
    for item in candidates:
        candidate=shape(item['geometry'])
        lines,texts=_references(candidate,features)
        reasons=['BOUNDARY_GAP'] if item['kind']=='boundary_gap' else []
        if item['kind']=='spur' and not lines and not texts:reasons.extend(['STROKE_LIKE_GEOMETRY','MISSING_INDEPENDENT_REFERENCE'])
        if item['kind'] in ('void','occupied_hole'):
            metrics=narrow_metrics(candidate,width_px,min_length_px,max_area_px2)
            if metrics:
                item.update(metrics)
                reasons.append('STROKE_LIKE_GEOMETRY')
                if not lines and not texts:reasons.append('MISSING_INDEPENDENT_REFERENCE')
        if reasons:
            if lines:reasons.append('INTERSECTS_INDEPENDENT_LINE')
            if texts:reasons.append('INTERSECTS_TEXT_DISPLAY')
        item.update(mergeable=False,merging_feature_ids=[],review_required=bool(reasons),review_reason_codes=reasons,reference_line_ids=lines,reference_text_ids=texts)
        if not region.covers(candidate):item['blocked_reason']='OUTSIDE_VALID_RASTER'
        elif item['kind'] in ('occupied_hole','boundary_gap') and candidate.area<=max_area_px2:
            owners=_merge_owners(candidate,target['feature_id'],dict(ownership))
            grown=geometry.union(candidate)
            safe_boundary=item['kind']!='boundary_gap' or (grown.geom_type==geometry.geom_type and grown.is_valid and _hole_count(grown)==_hole_count(geometry))
            if owners and safe_boundary:item.update(mergeable=True,merging_feature_ids=owners,blocked_reason='BOUNDARY_GAP_REQUIRES_REVIEW' if item['kind']=='boundary_gap' else 'OCCUPIED_HOLE_REQUIRES_MERGE')
        if item['kind']=='spur':
            for feature in faces:
                if feature['feature_id']==target['feature_id']:continue
                neighbor=shape(feature['geometry']);edge=candidate.boundary.intersection(neighbor.boundary).length
                grown=neighbor.union(candidate)
                if (edge>1e-7 and candidate.intersection(neighbor).area<=1e-7 and grown.geom_type in ('Polygon','MultiPolygon')
                        and grown.is_valid and _part_count(grown)==_part_count(neighbor) and _hole_count(grown)==_hole_count(neighbor)):
                    item['receiver_options'].append({'feature_id':feature['feature_id'],'color':feature['fill_color'],'shared_edge_px':edge})
            if not item['receiver_options']:item.setdefault('blocked_reason','NO_VALID_EDGE_RECEIVER')
            protected=[]
            for feature in features:
                if feature['feature_type']=='line' and feature['lifecycle_status']=='active' and feature['line_role'] in ('split','unknown'):
                    if shape(feature['geometry']).buffer(feature['stroke_width_px']/2).intersects(candidate):protected.append(feature['feature_id'])
                elif feature['feature_type']=='text' and feature.get('display_bbox_px') and box(*feature['display_bbox_px']).intersects(candidate):protected.append(feature['feature_id'])
            if protected:item.setdefault('blocked_reason','PROTECTED_LINE_OR_TEXT');item['protected_feature_ids']=protected
        identity=hashlib.sha256((target['feature_id']+item['kind']+candidate.normalize().wkb_hex).encode()).hexdigest()[:32]
        item['candidate_id']=identity
        item['receiver_options'].sort(key=lambda option:(-option['shared_edge_px'],option['feature_id']))
        _enrich_evidence(item,candidate,geometry,target,asset,directory,width_px,features)
    return list({item['candidate_id']:item for item in candidates}.values()),features,region,maximum_stroke,bounds


def create_preview(connection,project_id,request,directory):
    project=connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()
    if project is None:raise KeyError(project_id)
    if project['current_asset_id']!=request.asset_id:raise CommandConflict('ASSET_RESULT_MISMATCH')
    target=load_feature(connection,request.feature_id)
    if (target['project_id'],target['asset_id'],target['feature_type'],target['lifecycle_status'])!=(project_id,request.asset_id,'face','active'):raise CommandConflict('SELECTION_SCOPE_INVALID')
    asset=dict(connection.execute('SELECT * FROM asset WHERE asset_id=? AND project_id=?',(request.asset_id,project_id)).fetchone())
    candidates,features,region,maximum_stroke,bounds=_diagnose_target(connection,project_id,request.asset_id,asset,directory,target,request.width_px,request.min_length_px,request.max_area_px2)
    raster_inputs=_raster_inputs(candidates)
    parameters={name:getattr(request,name) for name in ('width_px','min_length_px','max_area_px2')}
    digest=_digest(features,region,maximum_stroke,raster_inputs,parameters);preview_id=str(uuid4());expires=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()
    response={'preview_id':preview_id,'project_id':project_id,'asset_id':request.asset_id,'algorithm_revision':ALGORITHM_REVISION,'parameters':parameters,
              'base_revision':project['working_revision'],'feature_id':request.feature_id,'expires_at':expires,'input_sha256':digest,'candidates':candidates,'summary':{name+'_count':sum(item['kind']==name for item in candidates) for name in ('spur','void','occupied_hole','boundary_gap')}}
    stored={**response,'scope_bounds_px':bounds,'algorithm_revision':ALGORITHM_REVISION,'raster_inputs':raster_inputs}
    connection.execute('INSERT INTO edit_preview VALUES (?,?,?,?,?,?,?,?)',(preview_id,project_id,request.asset_id,project['working_revision'],expires,request.model_dump_json(),json.dumps(stored,ensure_ascii=False),digest))
    return response


MAX_SCAN_FACES=2000


def scan_asset(connection,project_id,asset_id,directory,width_px=2,min_length_px=12,max_area_px2=150):
    """Read-only, asset-wide pass: which faces have a repair candidate worth a look.

    Does not persist an edit_preview; a face the operator picks from this list
    still goes through the normal single-face face-repair-previews flow before
    anything is applied. Bounded so an unusually large asset degrades to a
    truncated, clearly-marked result instead of an unbounded scan.
    """
    project=connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()
    if project is None:raise KeyError(project_id)
    if project['current_asset_id']!=asset_id:raise CommandConflict('ASSET_RESULT_MISMATCH')
    asset=connection.execute('SELECT * FROM asset WHERE asset_id=? AND project_id=?',(asset_id,project_id)).fetchone()
    if asset is None:raise KeyError(asset_id)
    asset=dict(asset)
    rows=connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='face' AND lifecycle_status='active' ORDER BY feature_id LIMIT ?",(project_id,asset_id,MAX_SCAN_FACES+1)).fetchall()
    face_ids=[row[0] for row in rows];truncated=len(face_ids)>MAX_SCAN_FACES;face_ids=face_ids[:MAX_SCAN_FACES]
    results=[]
    for feature_id in face_ids:
        target=load_feature(connection,feature_id)
        if target['lifecycle_status']!='active':continue
        try:
            candidates,_features,_region,_stroke,_bounds=_diagnose_target(connection,project_id,asset_id,asset,directory,target,width_px,min_length_px,max_area_px2)
        except CommandConflict:continue
        flagged=[item for item in candidates if item.get('review_required') or item.get('mergeable')]
        if flagged:results.append({'feature_id':feature_id,'candidate_count':len(flagged),'kinds':sorted({item['kind'] for item in flagged})})
    return {'base_revision':project['working_revision'],'scanned_face_count':len(face_ids),'flagged_faces':results,'truncated':truncated}


def plan_changes(connection,project_id,command,timestamp,directory):
    row=connection.execute('SELECT * FROM edit_preview WHERE preview_id=? AND project_id=? AND asset_id=?',(command.preview_id,project_id,command.asset_id)).fetchone()
    if row is None or row['base_revision']!=command.base_revision or datetime.fromisoformat(row['expires_at'])<=datetime.now(timezone.utc):raise CommandConflict('PREVIEW_STALE')
    report=json.loads(row['result_json'])
    if report.get('algorithm_revision')!=ALGORITHM_REVISION or command.feature_ids!=[report.get('feature_id')]:raise CommandConflict('PREVIEW_TYPE_MISMATCH')
    asset=dict(connection.execute('SELECT * FROM asset WHERE asset_id=? AND project_id=?',(command.asset_id,project_id)).fetchone())
    features=_scope(connection,project_id,command.asset_id,report['scope_bounds_px']);region=_region(asset,directory)
    raster_inputs=_current_raster_inputs(directory/asset['raster_rel_path'],report.get('raster_inputs',[]))
    if _digest(features,region,_maximum_stroke(connection,project_id,command.asset_id),raster_inputs,report.get('parameters'))!=row['input_sha256']:raise CommandConflict('PREVIEW_STALE')
    candidates={item['candidate_id']:item for item in report['candidates']};original={f['feature_id']:f for f in features}
    if any(identity not in candidates for identity in command.candidate_ids):raise CommandConflict('REPAIR_CANDIDATE_INVALID')
    selected=[candidates[identity] for identity in command.candidate_ids]
    verified=set(command.verified_protected_candidate_ids)
    if not verified.issubset(command.candidate_ids) or any(candidates[identity].get('blocked_reason')!='PROTECTED_LINE_OR_TEXT' for identity in verified):raise CommandConflict('REPAIR_PROTECTION_CONFIRMATION_INVALID')
    reviewed=set(command.verified_review_candidate_ids)
    if not reviewed.issubset(command.candidate_ids) or any(not candidates[identity].get('review_required',False) for identity in reviewed):raise CommandConflict('REPAIR_REVIEW_CONFIRMATION_INVALID')
    if any(item.get('review_required',False) and item['candidate_id'] not in reviewed for item in selected):raise CommandConflict('REPAIR_REVIEW_REQUIRED')
    merge_confirmed=set(command.merge_occupied_candidate_ids)
    if not merge_confirmed.issubset(command.candidate_ids) or any(candidates[identity]['kind'] not in ('occupied_hole','boundary_gap') or not candidates[identity].get('mergeable') or candidates[identity].get('blocked_reason') not in ('OCCUPIED_HOLE_REQUIRES_MERGE','BOUNDARY_GAP_REQUIRES_REVIEW') or not candidates[identity].get('merging_feature_ids') for identity in merge_confirmed):raise CommandConflict('REPAIR_MERGE_CONFIRMATION_INVALID')
    if any(item['kind'] in ('occupied_hole','boundary_gap') and item['candidate_id'] not in merge_confirmed or item.get('blocked_reason') and not (item['blocked_reason']=='PROTECTED_LINE_OR_TEXT' and item['candidate_id'] in verified or item['blocked_reason'] in ('OCCUPIED_HOLE_REQUIRES_MERGE','BOUNDARY_GAP_REQUIRES_REVIEW') and item['candidate_id'] in merge_confirmed) for item in selected):raise CommandConflict('REPAIR_CANDIDATE_BLOCKED')
    selected_geometry=[shape(item['geometry']) for item in selected]
    if abs(sum(item.area for item in selected_geometry)-union_all(selected_geometry).area)>1e-7:raise CommandConflict('REPAIR_SELECTION_OVERLAP')
    spur_ids={item['candidate_id'] for item in selected if item['kind']=='spur'}
    if set(command.assignments)!=spur_ids:raise CommandConflict('REPAIR_RECEIVER_REQUIRED')
    retiring_ids={fid for item in selected if item['kind'] in ('occupied_hole','boundary_gap') for fid in item.get('merging_feature_ids',[])}
    if set(command.assignments.values())&retiring_ids:raise CommandConflict('REPAIR_RECEIVER_INVALID')
    source_id=command.feature_ids[0];active={fid:shape(f['geometry']) for fid,f in original.items() if f['feature_type']=='face' and f['lifecycle_status']=='active'}
    before_union=union_all(list(active.values()));original_source=active[source_id]
    fills=[];merging_ids=set()
    for item in selected:
        candidate=shape(item['geometry'])
        if item['kind']=='spur':
            receiver_id=command.assignments[item['candidate_id']]
            if receiver_id not in {option['feature_id'] for option in item['receiver_options']} or receiver_id==source_id:raise CommandConflict('REPAIR_RECEIVER_INVALID')
            if not region.covers(candidate) or not original_source.covers(candidate) or active[receiver_id].intersection(candidate).area>1e-7:raise CommandConflict('REPAIR_RECEIVER_INVALID')
            active[source_id]=active[source_id].difference(candidate);active[receiver_id]=active[receiver_id].union(candidate)
        elif item['kind'] in ('occupied_hole','boundary_gap'):
            # IDs come only from the stored preview, then are checked against
            # current scoped database geometry, never supplied by the client.
            owners=_merge_owners(candidate,source_id,active)
            if not region.covers(candidate) or owners!=item['merging_feature_ids']:raise CommandConflict('REPAIR_CANDIDATE_BLOCKED')
            active[source_id]=active[source_id].union(union_all([active[fid] for fid in owners]))
            for fid in owners:del active[fid]
            merging_ids.update(owners);fills.append(candidate)
        else:
            others=union_all([g for fid,g in active.items() if fid!=source_id])
            if not region.covers(candidate) or candidate.intersection(others).area>1e-7:raise CommandConflict('REPAIR_CANDIDATE_BLOCKED')
            active[source_id]=active[source_id].union(candidate);fills.append(candidate)
    values=list(active.values());after_union=union_all(values)
    repaired_source=active[source_id]
    if original_source.geom_type=='Polygon' and repaired_source.geom_type!='Polygon':raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
    closed_fills=sum(item['kind'] in ('void','occupied_hole') for item in selected)
    if _hole_count(repaired_source)!=_hole_count(original_source)-closed_fills:raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
    if any(g.is_empty or not g.is_valid or g.geom_type not in ('Polygon','MultiPolygon') for g in values) or not bool(coverage_is_valid(values)):raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
    expected=before_union.union(union_all(fills))
    if after_union.symmetric_difference(expected).area>1e-6 or abs(sum(g.area for g in values)-after_union.area)>1e-6:raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
    changes=[]
    for fid,geometry in active.items():
        old=original[fid]
        if geometry.equals(shape(old['geometry'])):continue
        new=copy.deepcopy(old);bounds=geometry.bounds
        new.update(geometry=mapping(geometry),geometry_type=geometry.geom_type,bbox_min_x_px=bounds[0],bbox_min_y_px=bounds[1],bbox_max_x_px=bounds[2],bbox_max_y_px=bounds[3],area_px2=geometry.area,coverage_status='unchecked',observed_area_px2=None,inferred_area_px2=None,revision=command.base_revision+1,updated_at=timestamp)
        changes.append((old,new))
    for fid in sorted(merging_ids):
        old=original[fid]
        changes.append((old,{**copy.deepcopy(old),'lifecycle_status':'superseded','revision':command.base_revision+1,'updated_at':timestamp}))
    if not changes:raise CommandConflict('REPAIR_NO_CHANGE')
    evidence={'preview_id':command.preview_id,'asset_id':command.asset_id,'source_feature_id':source_id,'candidate_ids':command.candidate_ids,'assignments':command.assignments,
              'algorithm_revision':report['algorithm_revision'],'transfers':[{**copy.deepcopy(item),'receiver_feature_id':command.assignments.get(item['candidate_id'])} for item in selected],
              'modified_feature_ids':[new['feature_id'] for old,new in changes],'preserved_line_and_text':True}
    evidence['merge_occupied_candidate_ids']=command.merge_occupied_candidate_ids
    evidence['merging_feature_ids']=sorted(merging_ids)
    evidence['verified_protected_candidate_ids']=command.verified_protected_candidate_ids
    evidence['verified_review_candidate_ids']=command.verified_review_candidate_ids
    evidence['protected_feature_ids']=sorted({fid for item in selected for fid in item.get('protected_feature_ids',[])})
    return changes,evidence


def repair_history(connection,project_id,asset_id,feature_id):
    """Derive bounded history from immutable operation evidence, including undo."""
    items=[]
    rows=connection.execute("""SELECT operation_id,result_revision,created_at,operation_status,result_summary
        FROM operation WHERE project_id=? AND operation_type='repair_face_geometry'
        AND json_extract(result_summary,'$.review_summary.face_repair.source_feature_id')=?
        AND COALESCE(json_extract(result_summary,'$.review_summary.face_repair.asset_id'),json_extract(result_summary,'$.current_asset_id'))=?
        ORDER BY result_revision DESC LIMIT 500""",(project_id,feature_id,asset_id))
    for row in rows:
        result=json.loads(row['result_summary'])
        evidence=result.get('review_summary',{}).get('face_repair',{})
        if evidence.get('source_feature_id')!=feature_id or evidence.get('asset_id',result.get('current_asset_id'))!=asset_id:continue
        for transfer in evidence.get('transfers',[]):
            entry={'receiver_options':[],'mergeable':bool(transfer.get('merging_feature_ids')),'merging_feature_ids':[],
                   'review_required':False,'review_reason_codes':[],'reference_line_ids':[],'reference_text_ids':[],
                   'protected_feature_ids':[],'geometry':None,**transfer,
                   'operation_id':row['operation_id'],'result_revision':row['result_revision'],'created_at':row['created_at'],
                   'operation_status':row['operation_status'],'source_feature_id':feature_id,'asset_id':asset_id}
            items.append(entry)
    return {'items':items}

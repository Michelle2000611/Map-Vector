"""Preview-bound whole-selection face merges with explicit local ownership changes."""
import copy
import hashlib
import json
import math
import warnings
from datetime import datetime, timedelta, timezone
from statistics import median
from uuid import uuid4

import numpy as np
import rasterio
from affine import Affine
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rasterio.features import rasterize
from rasterio.errors import NotGeoreferencedWarning
from rasterio.windows import Window
from shapely import get_coordinates, union_all
from shapely.geometry import Polygon, box, mapping, shape
from shapely.strtree import STRtree

from mapvector.application.face_repairs import _read_raster_window
from mapvector.application.face_splits import _scope
from mapvector.application.ports import load_feature
from mapvector.domain.commands import UUIDString
from mapvector.domain.errors import CommandConflict

ALGORITHM_REVISION = 'face_merge_modes_v1'
MODES = ('single', 'multipart', 'gap_single')


class FaceMergeParameters(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    max_gap_px: float | None = Field(default=None, gt=0, le=100)
    max_added_area_px2: float = Field(default=150., gt=0, le=10000)


class FaceMergeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    asset_id: UUIDString
    base_revision: int = Field(ge=0, le=9007199254740990, strict=True)
    feature_ids: list[UUIDString] = Field(min_length=2, max_length=1000)
    attribute_source_feature_id: UUIDString | None = None
    allow_mixed_algorithm_labels: bool = False
    selected_gap_candidate_ids: list[str] = Field(default_factory=list, max_length=2000)
    source_preview_id: UUIDString | None = None
    ownership_transfer_feature_ids: list[UUIDString] = Field(default_factory=list, max_length=1000)
    parameters: FaceMergeParameters = Field(default_factory=FaceMergeParameters)

    @model_validator(mode='after')
    def unique_scope(self):
        for values in (self.feature_ids, self.selected_gap_candidate_ids, self.ownership_transfer_feature_ids):
            if len(values) != len(set(values)):
                raise ValueError('合并输入身份不能重复')
        if self.attribute_source_feature_id and self.attribute_source_feature_id not in self.feature_ids:
            raise ValueError('属性来源必须是所选面')
        if set(self.feature_ids) & set(self.ownership_transfer_feature_ids):
            raise ValueError('局部转移对象必须在完整合并选择之外')
        return self


def _sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _geo(geometry):
    geometry=_polygonal(geometry)
    return mapping(geometry) if geometry is not None and not geometry.is_empty else None


def _polygonal(geometry):
    """Retain every area component while excluding zero-area overlay remnants."""
    if geometry is None or geometry.is_empty or geometry.geom_type in ('Polygon','MultiPolygon'):return geometry
    if geometry.geom_type=='GeometryCollection':
        parts=[_polygonal(part) for part in geometry.geoms]
        return union_all([part for part in parts if part is not None and not part.is_empty])
    if geometry.area>0:raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
    return Polygon()


def _parts(geometry):
    return len(geometry.geoms) if geometry.geom_type == 'MultiPolygon' else int(not geometry.is_empty)


def _holes(geometry):
    return sum(len(part.interiors) for part in (geometry.geoms if geometry.geom_type == 'MultiPolygon' else [geometry])) if geometry.geom_type in ('Polygon', 'MultiPolygon') else 0


def _hole_geometries(geometry):
    if geometry is None or geometry.geom_type not in ('Polygon','MultiPolygon'):return []
    return [mapping(Polygon(ring)) for part in (geometry.geoms if geometry.geom_type=='MultiPolygon' else [geometry]) for ring in part.interiors]


def _local_area_epsilon(geometry):
    # Numerical comparisons concern only this local patch, never the total map area.
    return max(1e-8,geometry.area*1e-10)


def _nearby(connection, project_id, asset_id, bounds, cache=None):
    x0, y0, x1, y1 = bounds
    rows = connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated') AND rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) ORDER BY feature_id LIMIT 10001", (project_id, asset_id, x0, x1, y0, y1)).fetchall()
    if len(rows)>10000:raise CommandConflict('FACE_MERGE_CONTEXT_LIMIT',{'reason':'局部范围内对象超过10000，请缩小选择范围'})
    cache=cache if cache is not None else {}
    for row in rows:
        if row[0] not in cache:cache[row[0]]=load_feature(connection,row[0])
    return [cache[row[0]] for row in rows]


def _local_neighbors(connection, project_id, asset_id, geometries, margin):
    nearby={}
    for geometry in geometries:
        for part in geometry.geoms if geometry.geom_type=='MultiPolygon' else [geometry]:
            x0,y0,x1,y1=part.bounds
            for item in _nearby(connection,project_id,asset_id,(x0-margin,y0-margin,x1+margin,y1+margin),nearby):
                nearby[item['feature_id']]=item
                if len(nearby)>10000:raise CommandConflict('FACE_MERGE_CONTEXT_LIMIT',{'reason':'局部范围内对象超过10000，请缩小选择范围'})
    return [nearby[identity] for identity in sorted(nearby)]


def _read_window(path, bounds):
    read=_read_raster_window(path,bounds)
    if read is None:return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',NotGeoreferencedWarning)
            with rasterio.open(path) as raster:
                x0,y0,x1,y1=bounds
                masks=raster.read_masks(window=Window(x0,y0,x1-x0,y1-y0))
                valid=np.all(masks>0,axis=0)&read[1]
                digest=hashlib.sha256((read[2]+str(raster.nodatavals)).encode()+masks.tobytes()).hexdigest()
        return read[0],valid,digest
    except (OSError,ValueError,rasterio.errors.RasterioIOError):return None


def _raster_evidence(path, asset, geometry, budget):
    """Bounded uint8 windows and per-region samples; no whole-image float array."""
    evidence = {'status': 'unavailable', 'reason_codes': [], 'windows': [], 'sample_count': 0}
    if path is None:
        evidence['reason_codes'] = ['RASTER_EVIDENCE_UNAVAILABLE']; return evidence
    x0, y0, x1, y1 = geometry.bounds
    bounds = (max(0, math.floor(x0)-1), max(0, math.floor(y0)-1), min(asset['width_px'], math.ceil(x1)+1), min(asset['height_px'], math.ceil(y1)+1))
    samples = []; invalid = False
    for y in range(bounds[1], bounds[3], 512):
        for x in range(bounds[0], bounds[2], 512):
            if not geometry.intersects(box(x, y, min(x+512,bounds[2]), min(y+512,bounds[3]))): continue
            if budget[0] <= 0:
                evidence['reason_codes'] = ['RASTER_EVIDENCE_WINDOW_LIMIT']; return evidence
            budget[0] -= 1
            window = [x,y,min(x+512,bounds[2]),min(y+512,bounds[3])]
            read = _read_window(path, window)
            evidence['windows'].append({'bounds_px':window,'sha256':read[2] if read else 'unavailable'})
            if read is None:
                evidence['reason_codes'] = ['RASTER_EVIDENCE_UNAVAILABLE']; return evidence
            rgb, valid, _ = read
            mask = rasterize([(geometry,1)], out_shape=valid.shape, transform=Affine.translation(x,y), dtype='uint8').astype(bool)
            invalid = invalid or bool(np.any(mask & ~valid))
            values = rgb[mask & valid]
            evidence['sample_count'] += len(values)
            if len(values): samples.append(values[::max(1,math.ceil(len(values)/4096))])
    if invalid:
        evidence['reason_codes'] = ['PATCH_OUTSIDE_VALID_RASTER']; return evidence
    if not samples:
        evidence['reason_codes'] = ['RASTER_INSUFFICIENT_SAMPLES']; return evidence
    values = np.concatenate(samples)
    evidence['median_rgb'] = np.median(values,axis=0).tolist()
    dark = (values.max(axis=1)<100)&((values.max(axis=1).astype(int)-values.min(axis=1))<60)
    evidence['dark_fraction'] = float(np.mean(dark))
    evidence['status'] = 'stroke_supported' if evidence['dark_fraction'] >= .6 else 'ambiguous'
    evidence['reason_codes'] = ['RASTER_DARK_STROKE'] if evidence['status']=='stroke_supported' else ['RASTER_EVIDENCE_AMBIGUOUS']
    return evidence


def _materialize(connection, project_id, request, directory):
    asset = _scope(connection, project_id, request.asset_id, request.base_revision)
    targets = []
    for identity in sorted(request.feature_ids):
        try: item = load_feature(connection,identity)
        except (KeyError, TypeError, ValueError): raise CommandConflict('SELECTION_SCOPE_INVALID')
        if (item['project_id'],item['asset_id'],item['feature_type'],item['lifecycle_status']) != (project_id,request.asset_id,'face','active'):
            raise CommandConflict('SELECTION_SCOPE_INVALID')
        geometry = shape(item['geometry'])
        if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon','MultiPolygon') or not np.isfinite(get_coordinates(geometry)).all():
            raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
        if not box(0,0,asset['width_px'],asset['height_px']).covers(geometry): raise CommandConflict('GEOMETRY_OUTSIDE_ASSET')
        targets.append(item)
    geometries = [shape(item['geometry']) for item in targets]
    union = union_all(geometries)
    # Local line widths are derived from the selected area, never an unrelated map maximum.
    nearby = _local_neighbors(connection,project_id,request.asset_id,geometries,2)
    widths = [item['stroke_width_px'] for item in nearby if item['feature_type']=='line' and item['lifecycle_status']=='active' and shape(item['geometry']).intersects(union)]
    width = request.parameters.max_gap_px
    fallback = width is None and not widths
    width = width if width is not None else min(100.,2*median(widths)) if widths else 2.
    parameters = {**request.parameters.model_dump(), 'max_gap_px':width,'scale_source':'explicit' if request.parameters.max_gap_px is not None else 'local_line_median' if widths else 'fallback','max_candidates':2000,
                  'raster_window_size_px':512,'raster_max_windows':128,'context_feature_limit':10000}
    nearby = _local_neighbors(connection,project_id,request.asset_id,geometries,width)
    groups=[];bindings=[]
    for item in targets:
        groups.extend(dict(row) for row in connection.execute('SELECT * FROM group_member WHERE feature_id=? ORDER BY group_id',(item['feature_id'],)))
        bindings.extend(dict(row) for row in connection.execute('SELECT * FROM feature_style WHERE feature_id=?',(item['feature_id'],)))
    source = request.attribute_source_feature_id or min(targets,key=lambda item:(-shape(item['geometry']).area,item['feature_id']))['feature_id']
    return asset, targets, union, nearby, groups, bindings, source, parameters, fallback


def _capability(geometry, blocked, reasons, mode, scope, added=None, transferred=None):
    geometry=_polygonal(geometry)
    reasons=sorted(set(reasons));blocked=sorted(set(blocked))
    evidence=[_sha({'scope':scope,'mode':mode,'reason':reason})[:32] for reason in reasons]
    affected=set(scope['feature_ids'])
    if mode=='gap_single':affected.update(scope['gap_owner_feature_ids'])
    associations=[{'evidence_id':identity,'reason_code':reason,'feature_ids':sorted(affected),
                   'gap_candidate_ids':scope['selected'] if mode=='gap_single' else []}
                  for identity,reason in zip(evidence,reasons)]
    return {'eligible':not blocked,'blocked_reasons':blocked,'review_required':bool(reasons),
            'review_reason_codes':reasons,'review_evidence_ids':evidence,'review_evidence':associations,'result_geometry':_geo(geometry),
            'output_geometry_type':geometry.geom_type if geometry is not None else None,
            'output_component_count':_parts(geometry) if geometry is not None else 0,
            'hole_count':_holes(geometry) if geometry is not None else 0,'preserved_hole_geometries':_hole_geometries(geometry),
            'added_empty_geometry':_geo(added),'transferred_geometry':_geo(transferred)}


def _build(connection, project_id, request, directory):
    from mapvector.geometry.face_merges import analyze_geometry
    asset,targets,union,nearby,groups,bindings,source,parameters,fallback = _materialize(connection,project_id,request,directory)
    base_block=[];base_review=[]
    geometries=[shape(target['geometry']) for target in targets]
    tree=STRtree(geometries)
    if any(first.intersection(geometries[int(other)]).area>0 for index,first in enumerate(geometries)
           for other in tree.query(first,predicate='intersects') if int(other)>index):
        base_block.append('UNRESOLVED_FACE_OVERLAP')
    shared_boundaries=[]
    if 'UNRESOLVED_FACE_OVERLAP' not in base_block:
        for index,first in enumerate(geometries):
            for other in sorted(tree.query(first,predicate='intersects')):
                if int(other)<=index:continue
                boundary=first.boundary.intersection(geometries[int(other)].boundary)
                if boundary.length>0:shared_boundaries.append(boundary)
    if union.geom_type not in ('Polygon','MultiPolygon') or not union.is_valid:base_block.append('GEOMETRY_VALIDATION_FAILED')
    labels={item.get('algorithm_label') for item in targets}
    if len(labels)>1:
        if not request.allow_mixed_algorithm_labels:base_block.append('MIXED_ALGORITHM_LABELS')
        else:base_review.append('MIXED_ALGORITHM_LABELS')
    if len({(item.get('fill_color'),item.get('color_class_id')) for item in targets})>1:base_review.append('DIFFERENT_SOURCE_APPEARANCE')
    selected=set(request.feature_ids)
    owners=[item for item in nearby if item['feature_type']=='face' and item['feature_id'] not in selected]
    for owner in owners:
        # A small occupied region remains real beside an arbitrarily large source face.
        if shape(owner['geometry']).intersection(union).area>0:base_block.append('UNRESOLVED_FACE_OVERLAP')
    independent_lines=[shape(line['geometry']) for line in nearby if line['feature_type']=='line']
    disappearing_seams=union_all(shared_boundaries)
    if any(line.intersection(disappearing_seams).length>0 for line in independent_lines):
        base_review.append('INDEPENDENT_GEOLOGICAL_BOUNDARY')
    try:
        analysis=({'gap_candidates':[],'truncated':False} if 'UNRESOLVED_FACE_OVERLAP' in base_block else
                  analyze_geometry(targets,max_gap_px=parameters['max_gap_px'],max_added_area_px2=parameters['max_added_area_px2'],max_candidates=2000))
    except ValueError as exc:
        raise CommandConflict('GEOMETRY_VALIDATION_FAILED',{'reason':str(exc)}) from exc
    budget=[128];path=directory/asset['raster_rel_path'] if directory is not None else None
    source_evidence=[];boundary_evidence=[]
    for target in targets:
        geometry=shape(target['geometry']);point=geometry.representative_point()
        local=geometry.intersection(box(point.x-2,point.y-2,point.x+2,point.y+2))
        source_evidence.append({'feature_id':target['feature_id'],**_raster_evidence(path,asset,local,budget)})
    for evidence in source_evidence:
        if evidence['status']=='unavailable':base_review.extend(evidence['reason_codes'])
    medians=[np.asarray(item['median_rgb']) for item in source_evidence if 'median_rgb' in item]
    if medians and any(np.linalg.norm(value-medians[0])>60 for value in medians[1:]):base_review.append('RASTER_DISTINCT_SOURCE_REGIONS')
    for boundary in shared_boundaries:
        evidence=_raster_evidence(path,asset,boundary.buffer(.75).intersection(union),budget)
        boundary_evidence.append(evidence)
        if evidence.get('dark_fraction',0)>=.6:base_review.append('RASTER_GEOLOGICAL_BOUNDARY')
        elif evidence['status']=='unavailable':base_review.extend(evidence['reason_codes'])
    candidates=[]
    for original in analysis['gap_candidates']:
        item=copy.deepcopy(original);patch=shape(item['geometry']);blocked=[];reasons=[];transfers=[]
        region=box(0,0,asset['width_px'],asset['height_px'])
        if not region.covers(patch):
            if patch.difference(region).area>_local_area_epsilon(patch):blocked.append('PATCH_OUTSIDE_ASSET')
            else:
                # Remove only numerical edge penetration from corridor construction.
                patch=patch.intersection(region)
        patch=_polygonal(patch)
        if patch.is_empty:continue
        item['geometry']=mapping(patch);item['area_px2']=float(patch.area)
        for owner in owners:
            geometry=shape(owner['geometry']);piece=_polygonal(geometry.intersection(patch))
            if piece.area<=0:continue
            remaining=geometry.difference(patch)
            owner_reasons=[]
            if owner['lifecycle_status']!='active' or owner['source_type']=='manual':owner_reasons.append('PROTECTED_THIRD_PARTY')
            if remaining.is_empty:owner_reasons.append('TRANSFER_WOULD_EMPTY_OWNER')
            elif not remaining.is_valid or remaining.geom_type not in ('Polygon','MultiPolygon'):owner_reasons.append('TRANSFER_INVALID_REMAINDER')
            elif _parts(remaining)>_parts(geometry):owner_reasons.append('TRANSFER_WOULD_SPLIT_OWNER')
            if not remaining.is_empty:
                parts=list(remaining.geoms) if remaining.geom_type=='MultiPolygon' else [remaining]
                if any(part.area<1e-6 for part in parts):owner_reasons.append('TRANSFER_TINY_REMAINDER')
            evidence=_raster_evidence(path,asset,piece,budget)
            transfers.append({'feature_id':owner['feature_id'],'geometry':_geo(piece),'remaining_geometry':_geo(remaining),'area_px2':piece.area,'blocked_reasons':owner_reasons,'raster_evidence':evidence})
            blocked.extend(owner_reasons);reasons.append('THIRD_PARTY_OWNERSHIP_TRANSFER')
        raster=_raster_evidence(path,asset,patch,budget)
        if 'PATCH_OUTSIDE_VALID_RASTER' in raster['reason_codes']:blocked.append('PATCH_OUTSIDE_VALID_RASTER')
        if raster['status']!='stroke_supported':reasons.extend(raster['reason_codes'])
        for transfer in transfers:
            evidence=transfer['raster_evidence']
            # Every occupied owner is independently checked, even when its display color matches.
            reasons.extend(evidence['reason_codes'])
        if fallback:reasons.append('GAP_SCALE_FALLBACK')
        item.update(owner_feature_ids=[part['feature_id'] for part in transfers],occupying_feature_ids=[part['feature_id'] for part in transfers],ownership_transfers=transfers,
                    transferred_area_px2=sum(part['area_px2'] for part in transfers),
                    blocked_reasons=sorted(set(blocked)),review_reason_codes=sorted(set(reasons)),raster_evidence=raster,
                    review_required=True,risk_level='blocked' if blocked else 'review',recommended=False,
                    metrics={key:item[key] for key in ('width_px','area_px2','contact_length_px') if key in item})
        candidates.append(item)
    scope={'project_id':project_id,'asset':asset,'revision':request.base_revision,'targets':targets,'neighbors':nearby,
           'groups':groups,'bindings':bindings,'attribute_source_feature_id':source,'allow_mixed_algorithm_labels':request.allow_mixed_algorithm_labels,
           'parameters':parameters,'algorithm_revision':ALGORITHM_REVISION,'gap_candidates':candidates,
           'source_raster_evidence':source_evidence,'boundary_raster_evidence':boundary_evidence}
    digest=_sha(scope)
    if request.selected_gap_candidate_ids:
        if not request.source_preview_id:raise CommandConflict('GAP_CANDIDATE_SOURCE_REQUIRED')
        row=_load_preview(connection,project_id,request.asset_id,request.source_preview_id,request.base_revision)
        prior=json.loads(row['result_json'])
        if prior['input_sha256']!=digest:raise CommandConflict('PREVIEW_STALE')
        if not set(request.selected_gap_candidate_ids)<=set(item['candidate_id'] for item in prior['gap_candidates']):raise CommandConflict('GAP_CANDIDATE_SCOPE_INVALID')
    chosen=[item for item in candidates if item['candidate_id'] in request.selected_gap_candidate_ids]
    if len(chosen)!=len(request.selected_gap_candidate_ids):raise CommandConflict('GAP_CANDIDATE_SCOPE_INVALID')
    cap_scope={'input':digest,'feature_ids':sorted(request.feature_ids),'selected':sorted(request.selected_gap_candidate_ids),
               'ownership':sorted(request.ownership_transfer_feature_ids),
               'gap_owner_feature_ids':sorted({part['feature_id'] for item in chosen for part in item['ownership_transfers']})}
    capabilities={}
    capabilities['single']=_capability(union,base_block+([] if union.geom_type=='Polygon' else ['SELECTION_DISCONNECTED']),base_review,'single',cap_scope)
    capabilities['multipart']=_capability(union,base_block+([] if union.geom_type=='MultiPolygon' else ['MULTIPART_NOT_REQUIRED']),base_review+['MULTIPART_SAME_OBJECT'],'multipart',cap_scope)
    patch=union_all([shape(item['geometry']) for item in chosen]);output=union_all([union,patch])
    transfer_parts=[shape(part['geometry']) for item in chosen for part in item['ownership_transfers']]
    transferred=union_all(transfer_parts);empty=patch.difference(union).difference(transferred)
    gap_block=base_block+([code for item in chosen for code in item['blocked_reasons']])
    if not chosen:gap_block.append('GAP_SELECTION_REQUIRED')
    if union.geom_type=='Polygon':gap_block.append('GAP_NOT_REQUIRED')
    if output.geom_type!='Polygon' or not output.is_valid:gap_block.append('GAP_RESULT_DISCONNECTED')
    if patch.area>parameters['max_added_area_px2']+_local_area_epsilon(patch):gap_block.append('GAP_AREA_LIMIT')
    transfer_ids={part['feature_id'] for item in chosen for part in item['ownership_transfers']}
    if transfer_ids!=set(request.ownership_transfer_feature_ids):gap_block.append('OWNERSHIP_TRANSFER_CONFIRMATION_REQUIRED')
    # Several patches may split or consume an owner even if each was safe alone.
    affected=[]
    for owner in owners:
        if owner['feature_id'] not in transfer_ids:continue
        original=shape(owner['geometry']);remaining=original.difference(patch)
        if remaining.is_empty:gap_block.append('TRANSFER_WOULD_EMPTY_OWNER')
        elif not remaining.is_valid or remaining.geom_type not in ('Polygon','MultiPolygon'):gap_block.append('TRANSFER_INVALID_REMAINDER')
        elif _parts(remaining)>_parts(original):gap_block.append('TRANSFER_WOULD_SPLIT_OWNER')
        if not remaining.is_empty and remaining.geom_type in ('Polygon','MultiPolygon'):
            parts=list(remaining.geoms) if remaining.geom_type=='MultiPolygon' else [remaining]
            if any(part.area<1e-6 for part in parts):gap_block.append('TRANSFER_TINY_REMAINDER')
        affected.append({'feature_id':owner['feature_id'],'role':'ownership_transfer','modes':['gap_single'],'before_geometry':owner['geometry'],'after_geometry':_geo(remaining),'transferred_geometry':_geo(original.intersection(patch))})
    gap_review=base_review+['GAP_EXTENT_CONFIRMATION']+[code for item in chosen for code in item['review_reason_codes']]
    if any(line.intersects(patch) for line in independent_lines):gap_review.append('INDEPENDENT_GEOLOGICAL_BOUNDARY')
    capabilities['gap_single']=_capability(output,gap_block,gap_review,'gap_single',cap_scope,empty,transferred)
    affected = [
        {'feature_id':target['feature_id'],'role':'attribute_source' if target['feature_id']==source else 'merge_source',
         'modes':list(MODES),'before_geometry':target['geometry'],
         'after_lifecycle_status':'active' if target['feature_id']==source else 'superseded',
         'after_geometry_by_mode':{mode:capabilities[mode]['result_geometry'] if target['feature_id']==source else None for mode in MODES}}
        for target in targets
    ] + affected
    return {'project_id':project_id,'asset_id':request.asset_id,'base_revision':request.base_revision,'algorithm_revision':ALGORITHM_REVISION,
            'parameter_snapshot':parameters,'input_sha256':digest,'feature_ids':sorted(request.feature_ids),
            'attribute_source_feature_id':source,'capabilities':capabilities,'input_component_count':_parts(union),
            'hole_count_before':_holes(union),'gap_candidates':candidates,'selected_gap_candidate_ids':sorted(request.selected_gap_candidate_ids),
            'ownership_transfer_feature_ids':sorted(request.ownership_transfer_feature_ids),'affected_features':affected,
            'source_raster_evidence':source_evidence,'boundary_raster_evidence':boundary_evidence,
            'truncated':analysis.get('truncated',False)},targets,groups,bindings


def _load_preview(connection, project_id, asset_id, preview_id, revision):
    row=connection.execute('SELECT * FROM edit_preview WHERE preview_id=? AND project_id=? AND asset_id=?',(preview_id,project_id,asset_id)).fetchone()
    if row is None or row['base_revision']!=revision or datetime.fromisoformat(row['expires_at'])<=datetime.now(timezone.utc):raise CommandConflict('PREVIEW_STALE')
    report=json.loads(row['result_json'])
    if report.get('algorithm_revision')!=ALGORITHM_REVISION:raise CommandConflict('PREVIEW_TYPE_MISMATCH')
    if report.get('result_sha256')!=_sha({key:value for key,value in report.items() if key!='result_sha256'}):raise CommandConflict('PREVIEW_STALE')
    return row


def create_preview(connection, project_id, request, directory=None):
    report,*_=_build(connection,project_id,request,directory)
    report.update(preview_id=str(uuid4()),expires_at=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat())
    report['result_sha256']=_sha(report)
    connection.execute('INSERT INTO edit_preview VALUES (?,?,?,?,?,?,?,?)',(report['preview_id'],project_id,request.asset_id,request.base_revision,report['expires_at'],request.model_dump_json(),json.dumps(report,ensure_ascii=False),report['input_sha256']))
    return report


def _updated(old, geometry, revision, timestamp):
    bounds=geometry.bounds
    return {**copy.deepcopy(old),'geometry':mapping(geometry),'geometry_type':geometry.geom_type,
            'bbox_min_x_px':bounds[0],'bbox_min_y_px':bounds[1],'bbox_max_x_px':bounds[2],'bbox_max_y_px':bounds[3],
            'area_px2':geometry.area,'observed_area_px2':None,'inferred_area_px2':None,'coverage_status':'unchecked',
            'source_type':'manual','revision':revision,'updated_at':timestamp}


def plan_changes(connection, project_id, command, timestamp, directory=None):
    row=_load_preview(connection,project_id,command.asset_id,command.preview_id,command.base_revision)
    report=json.loads(row['result_json']);request=FaceMergeRequest.model_validate_json(row['request_json'])
    if set(command.feature_ids)!=set(request.feature_ids) or len(command.feature_ids)!=len(set(command.feature_ids)):raise CommandConflict('SELECTION_SCOPE_INVALID')
    fresh,targets,groups,bindings=_build(connection,project_id,request,directory)
    saved={key:value for key,value in report.items() if key not in ('preview_id','expires_at','result_sha256')}
    if _sha(fresh)!=_sha(saved) or fresh['input_sha256']!=row['input_sha256']:raise CommandConflict('PREVIEW_STALE')
    if command.mode not in MODES:raise CommandConflict('PREVIEW_TYPE_MISMATCH')
    capability=report['capabilities'][command.mode]
    if not capability['eligible']:raise CommandConflict('FACE_MERGE_BLOCKED',{'blocked_reasons':capability['blocked_reasons']})
    if set(command.verified_review_evidence_ids)!=set(capability['review_evidence_ids']):raise CommandConflict('FACE_MERGE_REVIEW_REQUIRED',{'review_evidence_ids':capability['review_evidence_ids']})
    expected_gaps=set(request.selected_gap_candidate_ids) if command.mode=='gap_single' else set()
    expected_owners=set(request.ownership_transfer_feature_ids) if command.mode=='gap_single' else set()
    if set(command.confirmed_gap_candidate_ids)!=expected_gaps:raise CommandConflict('GAP_CONFIRMATION_REQUIRED')
    if set(command.confirmed_ownership_transfer_feature_ids)!=expected_owners:raise CommandConflict('OWNERSHIP_TRANSFER_CONFIRMATION_REQUIRED')
    keep=report['attribute_source_feature_id'];revision=command.base_revision+1
    originals={item['feature_id']:item for item in targets};changes=[];relations=[];lineages=[]
    for old in targets:
        if old['feature_id']==keep:
            changes.append((old,_updated(old,shape(capability['result_geometry']),revision,timestamp)))
        else:
            changes.append((old,{**copy.deepcopy(old),'lifecycle_status':'superseded','revision':revision,'updated_at':timestamp}))
            lineages.append((old['feature_id'],keep,{key:value for key,value in old.items() if key!='geometry'}))
    existing={item['group_id'] for item in groups if item['feature_id']==keep}
    for gid in sorted({item['group_id'] for item in groups}-existing):
        member={'group_id':gid,'feature_id':keep};relations.append(('group_member',gid+':'+keep,None,member))
    # Keep the attribute source's actual relation, which can differ from feature.style_id.
    # It remains attached to the kept identity; retired bindings are removed by CommandService.
    if command.mode=='gap_single':
        for affected in report['affected_features']:
            if affected['feature_id'] in originals:continue
            old=load_feature(connection,affected['feature_id'])
            changes.append((old,_updated(old,shape(affected['after_geometry']),revision,timestamp)))
    evidence={'preview_id':command.preview_id,'mode':command.mode,'algorithm_revision':ALGORITHM_REVISION,
              'input_sha256':report['input_sha256'],'result_sha256':report['result_sha256'],'parameter_snapshot':report['parameter_snapshot'],
              'attribute_source_feature_id':keep,'source_attribute_snapshots':{identity:{key:value for key,value in item.items() if key!='geometry'} for identity,item in originals.items()},
              'source_style_bindings':bindings,'selected_gap_candidate_ids':sorted(expected_gaps),'confirmed_ownership_transfer_feature_ids':sorted(expected_owners),
              'verified_review_evidence_ids':command.verified_review_evidence_ids,'added_empty_geometry':capability['added_empty_geometry'],
              'transferred_geometry':capability['transferred_geometry'],'preserved_line_and_text':True}
    return changes,relations,lineages,evidence

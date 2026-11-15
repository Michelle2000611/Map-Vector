"""Explicit zero-width polygon subdivision, bound to immutable preview evidence."""
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely import coverage_is_valid, union_all
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import nearest_points, split

from mapvector.application.ports import load_feature
from mapvector.domain.commands import UUIDString
from mapvector.domain.errors import CommandConflict

ALGORITHM_REVISION='zero_width_selected_face_split_v1'


class FaceSplitRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:UUIDString
    base_revision:int=Field(ge=0,le=9007199254740990,strict=True)
    feature_ids:list[UUIDString]=Field(min_length=1,max_length=1000)
    cutter_points_px:list[tuple[float,float]]|None=Field(default=None,min_length=2,max_length=4000)
    line_feature_id:UUIDString|None=None
    snap_tolerance_px:float=Field(default=.5,ge=0,le=2)
    min_piece_area_px2:float=Field(default=1,ge=0,le=10000)

    @model_validator(mode='after')
    def inputs(self):
        if len(self.feature_ids)!=len(set(self.feature_ids)):raise ValueError('Split targets must be unique')
        if (self.cutter_points_px is None)==(self.line_feature_id is None):raise ValueError('Choose a drawn path or an existing line')
        return self


def _scope(connection,project_id,asset_id,revision):
    project=connection.execute('SELECT current_asset_id,working_revision FROM project WHERE project_id=?',(project_id,)).fetchone()
    if project is None:raise KeyError(project_id)
    if project['current_asset_id']!=asset_id:raise CommandConflict('ASSET_RESULT_MISMATCH')
    if project['working_revision']!=revision:raise CommandConflict('REVISION_CONFLICT')
    asset=connection.execute('SELECT * FROM asset WHERE project_id=? AND asset_id=?',(project_id,asset_id)).fetchone()
    if asset is None:raise KeyError(asset_id)
    return dict(asset)


def _materialize(connection,project_id,request):
    asset=_scope(connection,project_id,request.asset_id,request.base_revision)
    targets=[]
    for identity in request.feature_ids:
        try:item=load_feature(connection,identity)
        except (KeyError,TypeError):raise CommandConflict('SELECTION_SCOPE_INVALID')
        if (item['project_id'],item['asset_id'],item['feature_type'],item['lifecycle_status'])!=(project_id,request.asset_id,'face','active'):raise CommandConflict('SELECTION_SCOPE_INVALID')
        geometry=shape(item['geometry'])
        if geometry.is_empty or not geometry.is_valid or geometry.geom_type not in ('Polygon','MultiPolygon'):raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
        targets.append(item)
    source_line=None
    if request.line_feature_id:
        source_line=load_feature(connection,request.line_feature_id)
        if (source_line['project_id'],source_line['asset_id'],source_line['feature_type'],source_line['lifecycle_status'])!=(project_id,request.asset_id,'line','active'):raise CommandConflict('SELECTION_SCOPE_INVALID')
        coords=source_line['geometry']['coordinates']
    else:coords=request.cutter_points_px
    cutter=LineString(coords)
    if cutter.is_empty or not cutter.is_valid or not cutter.is_simple or cutter.length<=1e-8:raise CommandConflict('SPLIT_PATH_INVALID')
    if any(not(0<=x<=asset['width_px'] and 0<=y<=asset['height_px']) for x,y in cutter.coords):raise CommandConflict('SPLIT_PATH_OUTSIDE_ASSET')
    memberships=[];bindings=[]
    for item in targets:
        memberships.extend(dict(row) for row in connection.execute('SELECT * FROM group_member WHERE feature_id=?',(item['feature_id'],)))
        bindings.extend(dict(row) for row in connection.execute('SELECT * FROM feature_style WHERE feature_id=?',(item['feature_id'],)))
    digest=hashlib.sha256(json.dumps({'request':request.model_dump(mode='json'),'targets':targets,'line':source_line,'groups':memberships,'bindings':bindings,'algorithm':ALGORITHM_REVISION},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return asset,targets,cutter,digest,memberships,bindings


def _snap_cutter(geometry,cutter,tolerance):
    # Only path endpoints may snap. Never round the polygon or buffer a cut strip.
    coords=list(cutter.coords)
    if tolerance:
        for index in (0,-1):
            point=Point(coords[index]);distance=geometry.boundary.distance(point)
            if 0<distance<=tolerance:coords[index]=nearest_points(point,geometry.boundary)[1].coords[0]
    path=LineString(coords)
    if not path.is_simple or path.length<=1e-8:raise CommandConflict('SPLIT_PATH_INVALID')
    return path


def _partition_diagnostic(geometry,cutter,tolerance):
    path=_snap_cutter(geometry,cutter,tolerance)
    components=list(geometry.geoms) if geometry.geom_type=='MultiPolygon' else [geometry]
    def location(coordinate):
        point=Point(coordinate)
        if geometry.contains(point):return 'inside'
        # A multipart component can fill another component's hole.
        if any(part.exterior.distance(point)<=1e-8 for part in components):return 'boundary'
        if any(Polygon(ring).covers(point) or ring.distance(point)<=1e-8 for part in components for ring in part.interiors):return 'hole'
        if geometry.boundary.distance(point)<=1e-8:return 'boundary'
        return 'outside'
    start,end=(location(path.coords[index]) for index in (0,-1))
    endpoints={'start':{'location':start,'point_px':list(path.coords[0])},'end':{'location':end,'point_px':list(path.coords[-1])}}
    if start=='hole' or end=='hole':
        where='起点和末端' if start==end=='hole' else '起点' if start=='hole' else '末端'
        code='CUTTER_ENDPOINTS_IN_HOLE' if start==end=='hole' else 'CUTTER_START_IN_HOLE' if start=='hole' else 'CUTTER_END_IN_HOLE'
        return {'reason_code':code,'reason':f'路径{where}落在面内孔洞中，尚未穿出外边界；请将{where}画到面的最外圈边界之外。','endpoints':endpoints}
    if start=='inside' or end=='inside':
        where='起点和末端' if start==end=='inside' else '起点' if start=='inside' else '末端'
        code='CUTTER_ENDPOINTS_INSIDE_FACE' if start==end=='inside' else 'CUTTER_START_INSIDE_FACE' if start=='inside' else 'CUTTER_END_INSIDE_FACE'
        return {'reason_code':code,'reason':f'路径{where}仍在面内部，请将{where}画到面的外边界之外。','endpoints':endpoints}
    return {'reason_code':'CUTTER_NO_PARTITION','reason':'路径未将同一面区域分开，请确认路径穿过所选面的外边界，且没有只沿边界或经过角点。','endpoints':endpoints}


def _subdivide(geometry,cutter,tolerance):
    path=_snap_cutter(geometry,cutter,tolerance)
    components=list(geometry.geoms) if geometry.geom_type=='MultiPolygon' else [geometry]
    pieces=[];cut=False
    for component in components:
        try:parts=[part for part in split(component,path).geoms if part.geom_type=='Polygon' and part.area>0]
        except ValueError as exc:raise CommandConflict('SPLIT_PATH_INVALID',{'reason':str(exc)}) from exc
        cut=cut or len(parts)>1;pieces.extend(parts)
    if not cut:return None
    merged=union_all(pieces);epsilon=max(1e-8,geometry.area*1e-10)
    if any(not part.is_valid for part in pieces) or merged.symmetric_difference(geometry).area>epsilon or abs(sum(part.area for part in pieces)-geometry.area)>epsilon or not bool(coverage_is_valid(pieces)):raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
    return sorted(pieces,key=lambda part:(-part.area,part.bounds,part.normalize().wkb_hex)),path


def create_preview(connection,project_id,request,directory=None):
    _asset,targets,cutter,digest,_groups,_bindings=_materialize(connection,project_id,request)
    results=[];warnings=[];paths=[];diagnostics=[]
    for target in targets:
        geometry=shape(target['geometry']);result=_subdivide(geometry,cutter,request.snap_tolerance_px)
        if result is None:
            diagnostics.append({'feature_id':target['feature_id'],**_partition_diagnostic(geometry,cutter,request.snap_tolerance_px)})
            warnings.append({'code':'TARGET_NOT_SPLIT','feature_id':target['feature_id']});continue
        pieces,path=result;paths.append(mapping(path))
        output=[]
        for piece in pieces:
            key=hashlib.sha256((target['feature_id']+piece.normalize().wkb_hex).encode()).hexdigest()[:32]
            small=piece.area<request.min_piece_area_px2
            output.append({'piece_id':key,'geometry':mapping(piece),'area_px2':piece.area,'small_piece':small})
            if small:warnings.append({'code':'SMALL_SPLIT_PIECE','feature_id':target['feature_id'],'piece_id':key})
        results.append({'feature_id':target['feature_id'],'original_area_px2':geometry.area,'pieces':output})
    if not results:
        detail={key:value for key,value in diagnostics[0].items() if key!='feature_id'} if len(diagnostics)==1 else {'reason_code':'CUTTER_NO_PARTITION','reason':'路径未将所选面分开，请检查各面的路径端点与外边界。'}
        raise CommandConflict('SPLIT_NO_PARTITION',{**detail,'targets':diagnostics})
    if sum(len(item['pieces']) for item in results)>5000:raise CommandConflict('SPLIT_TOO_MANY_PARTS')
    preview_id=str(uuid4());expires=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()
    result={'preview_id':preview_id,'base_revision':request.base_revision,'expires_at':expires,'input_sha256':digest,'algorithm_revision':ALGORITHM_REVISION,'targets':results,'feature_ids':request.feature_ids,'cutter_geometry':mapping(cutter),'target_cutters':paths,'warnings':warnings}
    connection.execute('INSERT INTO edit_preview VALUES (?,?,?,?,?,?,?,?)',(preview_id,project_id,request.asset_id,request.base_revision,expires,request.model_dump_json(),json.dumps(result,ensure_ascii=False),digest))
    return result


def plan_changes(connection,project_id,command,timestamp):
    row=connection.execute('SELECT * FROM edit_preview WHERE preview_id=? AND project_id=? AND asset_id=?',(command.preview_id,project_id,command.asset_id)).fetchone()
    if row is None or row['base_revision']!=command.base_revision or datetime.fromisoformat(row['expires_at'])<=datetime.now(timezone.utc):raise CommandConflict('PREVIEW_STALE')
    report=json.loads(row['result_json'])
    if report.get('algorithm_revision')!=ALGORITHM_REVISION:raise CommandConflict('PREVIEW_TYPE_MISMATCH')
    request=FaceSplitRequest.model_validate_json(row['request_json'])
    if set(command.feature_ids)!=set(request.feature_ids):raise CommandConflict('SELECTION_SCOPE_INVALID')
    _asset,targets,_cutter,digest,groups,bindings=_materialize(connection,project_id,request)
    if digest!=row['input_sha256']:raise CommandConflict('PREVIEW_STALE')
    small={piece['piece_id'] for target in report['targets'] for piece in target['pieces'] if piece['small_piece']}
    if set(command.confirmed_small_piece_ids)!=small:raise CommandConflict('SPLIT_SMALL_PIECE_REVIEW_REQUIRED')
    originals={item['feature_id']:item for item in targets};changes=[];relations=[];lineages=[]
    for target in report['targets']:
        old=originals[target['feature_id']]
        changes.append((old,{**copy.deepcopy(old),'lifecycle_status':'superseded','revision':command.base_revision+1,'updated_at':timestamp}))
        for piece in target['pieces']:
            geometry=shape(piece['geometry']);bounds=geometry.bounds;identity=str(uuid4())
            child={**copy.deepcopy(old),'feature_id':identity,'geometry':mapping(geometry),'geometry_type':'Polygon','bbox_min_x_px':bounds[0],'bbox_min_y_px':bounds[1],'bbox_max_x_px':bounds[2],'bbox_max_y_px':bounds[3],'area_px2':geometry.area,'observed_area_px2':None,'inferred_area_px2':None,'coverage_status':'unchecked','source_type':'manual','lifecycle_status':'active','revision':command.base_revision+1,'created_at':timestamp,'updated_at':timestamp}
            changes.append((None,child));lineages.append((old['feature_id'],identity,{key:value for key,value in old.items() if key!='geometry'}))
            for group in groups:
                if group['feature_id']==old['feature_id']:relations.append(('group_member',group['group_id']+':'+identity,None,{'group_id':group['group_id'],'feature_id':identity}))
            for binding in bindings:
                if binding['feature_id']==old['feature_id']:relations.append(('feature_style',identity,None,{'feature_id':identity,'style_id':binding['style_id']}))
    return changes,relations,lineages,{'preview_id':command.preview_id,'target_feature_ids':request.feature_ids,'preserved_line_and_text':True,'piece_count':sum(len(item['pieces']) for item in report['targets']),'cutter_geometry':report['cutter_geometry']}

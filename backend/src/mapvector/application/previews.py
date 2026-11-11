import hashlib
import json
from datetime import datetime,timezone,timedelta
from uuid import uuid4

import numpy as np
from PIL import Image
from shapely import from_wkb
from mapvector.application.ports import document
from mapvector.domain.ports import get_ports
EditError=get_ports().editor.error_type
FACE=get_ports().editor.face_layer
LINE=get_ports().editor.line_layer
from mapvector.application.ports import load_feature
from mapvector.domain.errors import CommandConflict


def load_document(connection,project_id,asset_id,project_dir):
    asset=connection.execute('SELECT * FROM asset WHERE asset_id=? AND project_id=?',(asset_id,project_id)).fetchone()
    if asset is None:raise KeyError(asset_id)
    features=[load_feature(connection,row[0]) for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated') ORDER BY feature_id",(project_id,asset_id))]
    with Image.open(project_dir/asset['raster_rel_path']) as image:pixels=np.asarray(image.convert('RGB'))
    groups=load_groups(connection,project_id,asset_id)
    styles=[dict(row) for row in connection.execute('SELECT * FROM style WHERE project_id=?',(project_id,))]
    doc,identities=document(features,asset['width_px'],asset['height_px'],pixels,groups,styles)
    roi=connection.execute('SELECT geometry_wkb FROM roi WHERE asset_id=?',(asset_id,)).fetchone()
    if roi:doc.roi=from_wkb(roi[0])
    return doc,identities,features


def residue_scope_features(connection,project_id,asset_id,bounds):
    x0,y0,x1,y1=bounds
    rows=connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated') AND rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_display_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) ORDER BY feature_id",(project_id,asset_id,x0,x1,y0,y1,x0,x1,y0,y1)).fetchall()
    return [load_feature(connection,row[0]) for row in rows]


def load_groups(connection,project_id,asset_id):
    groups=[]
    for row in connection.execute('SELECT * FROM logical_group WHERE project_id=? AND asset_id=?',(project_id,asset_id)):
        group=dict(row);group['feature_ids']=[item[0] for item in connection.execute('SELECT feature_id FROM group_member WHERE group_id=?',(row['group_id'],))];groups.append(group)
    return groups


def validate_selection_scope(connection,project_id,request,kind):
    if request.lifecycle_status=='isolated' and kind!='line':raise CommandConflict('SELECTION_SCOPE_INVALID')
    if connection.execute('SELECT 1 FROM asset WHERE project_id=? AND asset_id=?',(project_id,request.asset_id)).fetchone() is None:raise KeyError(request.asset_id)
    identities=list(set(request.feature_ids))
    for offset in range(0,len(identities),500):
        batch=identities[offset:offset+500]
        count=connection.execute('SELECT COUNT(*) FROM feature INDEXED BY sqlite_autoindex_feature_1 WHERE feature_id IN ('+','.join('?' for _ in batch)+') AND project_id=? AND asset_id=? AND feature_type=? AND lifecycle_status=?',(*batch,project_id,request.asset_id,kind,request.lifecycle_status)).fetchone()[0]
        if count!=len(batch):raise CommandConflict('SELECTION_SCOPE_INVALID')


def point_selection(connection,project_id,request):
    """Same pixel hit rules as the legacy editor, using indexed candidates only."""
    from shapely.geometry import Point
    from mapvector.geometry.text import hit_text
    kind='text' if request.selection_type=='text_pick' else request.feature_type
    validate_selection_scope(connection,project_id,request,kind)
    padding=3 if kind=='line' else 3 if kind=='text' else 0
    index='text_display_index' if kind=='text' else 'feature_index'
    x,y=request.x,request.y
    rows=connection.execute('SELECT f.feature_id,f.geometry_wkb FROM feature f WHERE f.rowid IN (SELECT id FROM '+index+' WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) AND f.project_id=? AND f.asset_id=? AND f.feature_type=? AND f.lifecycle_status=? ORDER BY f.feature_id',(x-padding,x+padding,y-padding,y+padding,project_id,request.asset_id,kind,request.lifecycle_status)).fetchall()
    point=Point(x,y);hits=[]
    if kind=='text':
        hits=[r['feature_id'] for r in rows if hit_text(load_feature(connection,r['feature_id']),x,y)]
    elif kind=='face':
        hits=[r['feature_id'] for r in rows if from_wkb(r['geometry_wkb']).contains(point)]
    else:
        distances=[(from_wkb(r['geometry_wkb']).distance(point),r['feature_id']) for r in rows]
        if distances:
            distance,identity=min(distances)
            if distance<=3:hits=[identity]
    result=set(hits);existing=set(request.feature_ids)
    if request.selection_mode=='add':result|=existing
    elif request.selection_mode=='subtract':result=existing-result
    return sorted(result)


def select(connection,project_id,request,project_dir):
    if request.selection_type in ('pick','text_pick'):return point_selection(connection,project_id,request)
    if request.selection_type in ('box','gesture'):
        from shapely.geometry import box as make_box,Point,LineString,Polygon
        from shapely import make_valid
        kind=request.feature_type;validate_selection_scope(connection,project_id,request,kind)
        if request.selection_type=='box':
            if request.bounds_px is None:raise CommandConflict('VALIDATION_ERROR')
            x0,y0,x1,y1=request.bounds_px;region=make_box(min(x0,x1),min(y0,y1),max(x0,x1),max(y0,y1))
        elif request.gesture_kind=='brush':
            if not request.points:raise CommandConflict('SELECTION_INVALID',{'reason':'empty brush stroke'})
            region=(LineString(request.points) if len(request.points)>1 else Point(request.points[0])).buffer(max(request.radius_px,.5),quad_segs=8)
        elif request.gesture_kind=='lasso':
            if len(request.points)<3:raise CommandConflict('SELECTION_INVALID',{'reason':'a lasso needs at least 3 points'})
            region=make_valid(Polygon(request.points))
            if region.is_empty or region.area<=0:raise CommandConflict('SELECTION_INVALID',{'reason':'lasso has no area'})
        else:raise CommandConflict('SELECTION_INVALID',{'reason':'unknown gesture'})
        bounds=region.bounds
        rows=connection.execute('SELECT f.feature_id,f.geometry_wkb FROM feature f WHERE f.rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) AND f.project_id=? AND f.asset_id=? AND f.feature_type=? AND f.lifecycle_status=?',(bounds[0],bounds[2],bounds[1],bounds[3],project_id,request.asset_id,kind,request.lifecycle_status)).fetchall()
        hits=[]
        for row in rows:
            geom=from_wkb(row['geometry_wkb'])
            if kind in ('line','text'):hit=geom.intersects(region)
            elif request.selection_type=='box' or request.rule=='center':hit=region.contains(geom.representative_point())
            elif request.rule=='cover50':hit=geom.intersection(region).area>=geom.area*.5
            else:hit=geom.intersects(region)
            if request.selection_type=='gesture' and kind=='face' and request.max_area_px2 is not None:hit=hit and geom.area<=request.max_area_px2
            if hit:hits.append(row['feature_id'])
        current=set(request.feature_ids);result=set(hits)
        if request.selection_mode=='add':result|=current
        elif request.selection_mode=='subtract':result=current-result
        return sorted(result)
    doc,ids,features=load_document(connection,project_id,request.asset_id,project_dir)
    if request.lifecycle_status=='isolated':
        if request.feature_type!='line':raise CommandConflict('SELECTION_SCOPE_INVALID')
        doc.L=doc.Q.copy()
        ids={('line' if kind=='isolated_line' else kind,index):identity for (kind,index),identity in ids.items() if kind!='line'}
    reverse={identity:(kind,index) for (kind,index),identity in ids.items()}
    kind=request.feature_type
    selected=[]
    for identity in request.feature_ids:
        if identity not in reverse or reverse[identity][0]!=kind:raise CommandConflict('SELECTION_SCOPE_INVALID')
        selected.append(reverse[identity][1])
    layer=FACE if kind=='face' else LINE
    try:
        action=request.selection_type
        if action=='text_pick':result=doc.pick_text(request.x,request.y)
        elif action=='pick':result=doc.pick_text(request.x,request.y) if kind=='text' else doc.pick(request.x,request.y,layer)
        elif action=='box':
            if request.bounds_px is None:raise CommandConflict('VALIDATION_ERROR')
            if kind=='text':
                region=__import__('shapely').box(*request.bounds_px)
                result=[int(row['_eid']) for _,row in doc.T.iterrows() if region.intersects(row.geometry)]
            else:result=doc.box(*request.bounds_px,layer)
        elif action=='group':
            if kind not in ('face','line') or len(selected)!=1:raise CommandConflict('SELECTION_SCOPE_INVALID')
            member=connection.execute('SELECT group_id FROM group_member WHERE feature_id=?',(request.feature_ids[0],)).fetchone()
            if not member:result=selected
            else:
                members={item[0] for item in connection.execute('SELECT feature_id FROM group_member WHERE group_id=?',(member[0],))}
                result=[index for (member_kind,index),identity in ids.items() if member_kind==kind and identity in members]
        elif action=='same_color':
            if kind!='face' or not selected:raise CommandConflict('SELECTION_SCOPE_INVALID')
            result=doc.adjacent_similar(selected,request.color_distance)
        elif action=='gesture':
            region=doc.gesture(request.gesture_kind,request.points,request.radius_px)
            result=[int(row['_eid']) for _,row in doc.T.iterrows() if region.intersects(row.geometry)] if kind=='text' else doc.select_region(region,layer,request.rule,request.max_area_px2)
        elif action=='grow':
            if kind!='face':raise CommandConflict('SELECTION_SCOPE_INVALID')
            result=doc.grow(selected,request.steps)
        else:
            if kind!='face':raise CommandConflict('SELECTION_SCOPE_INVALID')
            result=doc.shrink(selected,request.steps)
    except (EditError,IndexError,ValueError) as exc:raise CommandConflict('SELECTION_INVALID',{'reason':str(exc)}) from exc
    result_kind='text' if action=='text_pick' else kind
    identities={ids[(result_kind,index)] for index in result if (result_kind,index) in ids}
    current=set(request.feature_ids)
    if request.selection_mode=='add':identities|=current
    elif request.selection_mode=='subtract':identities=current-identities
    return sorted(identities)


def prepare_preview(connection,project_id,request,project_dir):
    if request.verified_line_feature_ids and len(request.feature_ids)!=1:raise CommandConflict('TEXT_TARGET_REQUIRED')
    current=connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()
    if current['working_revision']!=request.base_revision or current['current_asset_id']!=request.asset_id:raise CommandConflict('REVISION_CONFLICT')
    scope_bounds=None
    if request.preview_type=='text_residue':
        asset=connection.execute('SELECT width_px,height_px FROM asset WHERE project_id=? AND asset_id=?',(project_id,request.asset_id)).fetchone()
        bounds=request.bounds_px
        if len(request.feature_ids)==1:
            target=load_feature(connection,request.feature_ids[0])
            if target['project_id']!=project_id or target['asset_id']!=request.asset_id or target['feature_type']!='text' or target['lifecycle_status']!='active':raise CommandConflict('SELECTION_SCOPE_INVALID')
            display=target['display_bbox_px']
            candidate=connection.execute('SELECT detected_quad_px FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(target.get('primary_candidate_id'),project_id,request.asset_id)).fetchone()
            quad=json.loads(candidate['detected_quad_px']) if candidate and candidate['detected_quad_px'] else None
            regions=[list(display)] if display else []
            if quad:regions.append([min(p[0] for p in quad),min(p[1] for p in quad),max(p[0] for p in quad),max(p[1] for p in quad)])
            if not regions:raise CommandConflict('OCR_EVIDENCE_MISSING')
            required=[min(r[0] for r in regions)-4,min(r[1] for r in regions)-4,max(r[2] for r in regions)+4,max(r[3] for r in regions)+4]
            if bounds is not None:required=[min(required[0],bounds[0]),min(required[1],bounds[1]),max(required[2],bounds[2]),max(required[3],bounds[3])]
            bounds=tuple(required)
            request=request.model_copy(update={'bounds_px':bounds})
        if bounds is None:raise CommandConflict('VALIDATION_ERROR')
        # A small margin includes adjoining background faces and line endpoints.
        scope_bounds=[bounds[0]-120,bounds[1]-120,bounds[2]+120,bounds[3]+120]
        features=residue_scope_features(connection,project_id,request.asset_id,scope_bounds)
        doc,identities=document(features,asset['width_px'],asset['height_px'],None)
    else:doc,identities,features=load_document(connection,project_id,request.asset_id,project_dir)
    reverse={identity:(kind,index) for (kind,index),identity in identities.items()}
    kind='face' if request.preview_type in ('merge_faces','heal_faces','merge_suggest') else 'text' if request.preview_type=='text_residue' and request.feature_ids else 'line'
    ids=[]
    for identity in request.feature_ids:
        if identity not in reverse or reverse[identity][0]!=kind:raise CommandConflict('SELECTION_SCOPE_INVALID')
        ids.append(reverse[identity][1])
    try:
        if request.preview_type=='merge_faces':report=doc.merge_preview(ids)
        elif request.preview_type=='join_lines':report=doc.join_preview(ids)
        elif request.preview_type=='heal_faces':report=doc.heal_preview(doc.gesture('brush',request.points,request.radius_px),request.max_area_px2)
        elif request.preview_type=='split_faces':
            if len(ids)!=1:raise CommandConflict('SELECTION_SCOPE_INVALID')
            report=doc.split_face_preview(ids[0])
        elif request.preview_type=='merge_suggest':
            if not ids:raise CommandConflict('SELECTION_SCOPE_INVALID')
            report=doc.merge_suggest(ids)
        elif request.preview_type=='line_to_face':
            from shapely.geometry import shape,mapping
            from shapely import union_all
            if not ids:raise CommandConflict('SELECTION_SCOPE_INVALID')
            region=union_all([shape(f['geometry']).buffer((request.stroke_width_px or f['stroke_width_px'])/2) for f in features if f['feature_id'] in request.feature_ids])
            impacted=[f['feature_id'] for f in features if f['feature_type']=='face' and shape(f['geometry']).intersects(region)]
            report={'experimental':True,'removed_line_feature_ids':request.feature_ids,'affected_face_feature_ids':impacted,'buffer_geometry':mapping(region),'effect':'Subtract buffered area from intersecting faces, create narrow faces and remove source lines; final frozen coverage validation may reject'}
        else:
            bounds=request.bounds_px
            if bounds is None and len(ids)==1:
                text=doc.T.loc[doc.T['_eid']==ids[0]].iloc[0];bounds=[float(text[field])+(-4 if index<2 else 4) for index,field in enumerate(('box_x0','box_y0','box_x1','box_y1'))]
                request=request.model_copy(update={'bounds_px':tuple(bounds)})
            if bounds is None:raise CommandConflict('VALIDATION_ERROR')
            report=doc.text_preview(bounds,ocr=False)
            if len(request.feature_ids)>1:raise CommandConflict('SELECTION_SCOPE_INVALID')
            if not request.feature_ids and len(report.get('existing',[]))>1:raise CommandConflict('TEXT_TARGET_REQUIRED',{'reason':'Multiple text objects overlap the box; select one explicit text object'})
    except (EditError,ValueError,IndexError) as exc:raise CommandConflict('PREVIEW_INVALID',{'reason':str(exc)}) from exc
    digest=hashlib.sha256(json.dumps(features,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
    preview_id=str(uuid4());expires=(datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()
    # Internal integer IDs are evidence only; stable object IDs are returned alongside the legacy report.
    affected=set(request.feature_ids);normalized=json.loads(json.dumps(report,ensure_ascii=False,default=str))
    if request.preview_type=='merge_faces':
        for group in normalized.get('groups',[]):
            group['feature_ids']=[identities[('face',index)] for index in group['faces']];affected.update(group['feature_ids'])
            labels=sorted({f['algorithm_label'] for f in features if f['feature_id'] in group['feature_ids'] and f.get('algorithm_label') is not None})
            group['algorithm_labels']=labels;group['mixed_algorithm_labels']=len(labels)>1
    elif request.preview_type=='heal_faces':
        for item in normalized.get('candidates',[]):
            item['feature_id']=identities.get(('face',item['id']))
            item['target_feature_id']=identities.get(('face',item.get('target')))
            affected.update(value for value in (item['feature_id'],item['target_feature_id']) if value)
    elif request.preview_type=='split_faces':
        pv=next(iter(doc.previews.values()),{})
        affected.update(identities[('face',index)] for index in pv.get('plan',{}))
    elif request.preview_type=='line_to_face':affected.update(normalized['affected_face_feature_ids'])
    elif request.preview_type=='text_residue':
        for group in normalized.get('groups',[]):
            group.pop('options',None)
            group['feature_ids']=[identities[('face',index)] for index in group.get('faces',[])];affected.update(group['feature_ids'])
            group['ground_feature_ids']=[identities[('face',index)] for index in group.get('grounds',[])];affected.update(group['ground_feature_ids'])
            group['target_feature_id']=identities.get(('face',group.get('target')))
            if group['target_feature_id']:affected.add(group['target_feature_id'])
        for item in normalized.get('line_info',[]):
            item['feature_id']=identities.get(('line',item['id']))
            if item['feature_id']:affected.add(item['feature_id'])
    elif request.preview_type=='merge_suggest':
        for item in normalized.get('candidates',[]):
            item['feature_id']=identities.get(('face',item['eid']))
            if item['feature_id']:affected.add(item['feature_id'])
    response={'preview_id':preview_id,'base_revision':request.base_revision,'input_sha256':digest,'expires_at':expires,'preview_type':request.preview_type,'feature_ids':request.feature_ids,'affected_feature_ids':sorted(affected),'legacy_report':normalized,'warnings':[]}
    if request.preview_type=='text_residue':
        # Display glyph fragments, not every affected background face. Assessment evidence is
        # read-only and does not extend the legacy cleanup command's mutation plan.
        from mapvector.application.text_layer_assessment import assess
        face_ids={fid for group in normalized.get('groups',[]) for fid in group['feature_ids']}
        line_ids={item['feature_id'] for item in normalized.get('line_info',[]) if item.get('feature_id') and item.get('suggested')}
        protected={item['feature_id'] for item in normalized.get('line_info',[]) if item.get('feature_id') and not item.get('suggested')}
        extra_faces=set();extra_lines=set()
        if request.feature_ids:
            assessment=assess(connection,project_id,request.asset_id,project_dir,request.feature_ids)
            for item in assessment['items']:
                extra_faces.update(item['suspected_face_ids']);extra_lines.update(item['suspected_line_ids'])
                protected.difference_update(item['suspected_line_ids'])
                protected.update(item['protected_line_ids'])
        # The display/cleanup box is the same for legacy and evidence candidates.
        from shapely.geometry import box as region_box,shape as feature_shape
        region=region_box(*normalized['box']).buffer(-1e-6)
        for feature in features:
            if feature['feature_type']=='line' and feature['lifecycle_status']=='active' and feature_shape(feature['geometry']).intersection(region).length>1e-7:
                if feature['feature_id'] not in line_ids|extra_lines or not region_box(*normalized['box']).buffer(1e-6).covers(feature_shape(feature['geometry'])):protected.add(feature['feature_id'])
        response['text_residue_display']={'bounds_px':normalized['box'],'face_feature_ids':sorted(face_ids|extra_faces),'line_feature_ids':sorted((line_ids|extra_lines)-protected),'protected_line_feature_ids':sorted(protected),'assessment_only_face_ids':sorted(extra_faces-face_ids),'assessment_only_line_ids':sorted(extra_lines-line_ids-protected),'preserves_existing_text':bool(request.feature_ids or normalized.get('existing')),'complete_region_available':True,'complete_region':request.complete_region,'cleanup_face_feature_ids':sorted(face_ids|extra_faces),'cleanup_line_feature_ids':sorted((line_ids|extra_lines)-protected),'verification_pending_feature_ids':[],'verification_summary':{}}
    internal_preview_data={'scope_bounds_px':scope_bounds} if scope_bounds is not None else {}
    if request.preview_type=='text_residue' and len(request.feature_ids)==1:
        from mapvector.application.text_residue_review import review_lines,validate_confirmation
        display=response['text_residue_display']
        internal_preview_data['line_review_evidence']=review_lines(connection,project_id,request.asset_id,request.feature_ids[0],features,display)
        verified=validate_confirmation(connection,project_id,request,display)
        internal_preview_data['verified_line_feature_ids']=verified
        display['line_feature_ids']=sorted(set(display['line_feature_ids'])|set(verified))
        display['cleanup_line_feature_ids']=display['line_feature_ids']
        display['assessment_only_line_ids']=sorted(set(display['assessment_only_line_ids'])-set(display['protected_line_feature_ids']))
    elif request.preview_type=='text_residue':
        from mapvector.application.text_residue_review import protect_without_target
        protect_without_target(connection,project_id,request.asset_id,features,response['text_residue_display'])
    if request.preview_type=='text_residue':
        # Keep the review overlay protected, while only the explicit verified
        # set can be included in the complete plan.
        for item in normalized.get('line_info',[]):
            if item.get('feature_id') in response['text_residue_display']['protected_line_feature_ids']:item['suggested']=False
    if request.preview_type=='text_residue' and request.complete_region:
        from mapvector.application.residue_cleanup import plan_changes
        text_ids=request.feature_ids or [identities[('text',item['id'])] for item in normalized.get('existing',[]) if ('text',item['id']) in identities]
        if len(text_ids)!=1:raise CommandConflict('TEXT_TARGET_REQUIRED')
        changes,split_sources=plan_changes(features,response['text_residue_display'],None,request.base_revision+1,datetime.now(timezone.utc).isoformat(),text_ids[0],request.verified_line_feature_ids)
        internal_preview_data.update({'complete_cleanup_target_text_id':text_ids[0],'complete_cleanup_split_sources':split_sources,'complete_cleanup_changes':[{'before':old,'after':new} for old,new in changes]})
        response['text_residue_display']['verification_summary']={'face_count':len(response['text_residue_display']['face_feature_ids']),'line_count':len(response['text_residue_display']['cleanup_line_feature_ids']),'outside_line_parts':len(split_sources)}
    record=(preview_id,project_id,request.asset_id,request.base_revision,expires,request.model_dump_json(),json.dumps({**response,**internal_preview_data},ensure_ascii=False,default=str),digest)
    return response,record


def create_preview(connection,project_id,request,project_dir):
    response,record=prepare_preview(connection,project_id,request,project_dir)
    connection.execute('INSERT INTO edit_preview VALUES (?,?,?,?,?,?,?,?)',record)
    return response

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
    rows=connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated') AND rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_display_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_ocr_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) ORDER BY feature_id",(project_id,asset_id,x0,x1,y0,y1,x0,x1,y0,y1,x0,x1,y0,y1)).fetchall()
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
    if request.selection_type=='by_style':
        if not request.style_id:raise CommandConflict('VALIDATION_ERROR',{'field':'style_id'})
        kind=request.feature_type;validate_selection_scope(connection,project_id,request,kind) if request.feature_ids else None
        rows=connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type=? AND lifecycle_status=? AND style_id=?",(project_id,request.asset_id,kind,request.lifecycle_status,request.style_id)).fetchall()
        result=set(row['feature_id'] for row in rows);current=set(request.feature_ids)
        if request.selection_mode=='add':result|=current
        elif request.selection_mode=='subtract':result=current-result
        return sorted(result)
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
    residue_region=None
    residue_region_source=None
    residue_context=None
    residue_raster_source=None
    if request.preview_type=='text_residue':
        from mapvector.application.residue_context import materialize,raster_binding
        if len(request.feature_ids)==1:
            residue_context=materialize(connection,project_id,request.asset_id,request.base_revision)
            residue_raster_source=residue_context['source']['raster_source']
        else:residue_raster_source=raster_binding(connection,project_id,request.asset_id)
        asset=connection.execute('SELECT width_px,height_px FROM asset WHERE project_id=? AND asset_id=?',(project_id,request.asset_id)).fetchone()
        bounds=request.bounds_px
        if len(request.feature_ids)==1:
            target=load_feature(connection,request.feature_ids[0])
            if target['project_id']!=project_id or target['asset_id']!=request.asset_id or target['feature_type']!='text' or target['lifecycle_status']!='active':raise CommandConflict('SELECTION_SCOPE_INVALID')
            display=target['display_bbox_px']
            candidate=connection.execute('SELECT detected_quad_px FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(target.get('primary_candidate_id'),project_id,request.asset_id)).fetchone()
            quad=json.loads(candidate['detected_quad_px']) if candidate and candidate['detected_quad_px'] else None
            from shapely.geometry import Polygon,box as source_box,mapping as source_mapping
            from mapvector.geometry.text_residue import text_residue_regions
            source_regions=text_residue_regions([{**target,'detected_quad_px':quad}])
            source=source_regions[0]['geometry'] if source_regions else None
            if source is None or not source.is_valid or source.is_empty or source.area<=0:raise CommandConflict('OCR_EVIDENCE_MISSING')
            residue_region=source_mapping(source)
            residue_region_source='source_uncertain' if source_regions[0].get('uncertain') else 'ocr_quad' if quad else 'display_bbox'
            # Display movement never broadens the original-pixel cleanup authority.
            # Explicit ranges must cover the evidence, rather than silently joining
            # a source label and its moved display with one large erase rectangle.
            required=list(source.bounds) if quad else [value+(-4 if index<2 else 4) for index,value in enumerate(source.bounds)]
            if bounds is not None:
                selected_box=source_box(*bounds)
                if not selected_box.covers(source):raise CommandConflict('PREVIEW_SCOPE_MISMATCH')
                required=list(bounds)
            bounds=tuple(required)
            if not quad:residue_region=source_mapping(source_box(*bounds))
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
        elif request.preview_type=='heal_faces':
            report=doc.heal_preview(doc.gesture('brush',request.points,request.radius_px),request.max_area_px2)
            if ids:
                target=ids[0]
                report={**report,'candidates':[item for item in report['candidates'] if item.get('target')==target]}
                report['counts']={k:sum(1 for r in report['candidates'] if r['decision']==k) for k in ('merge','keep','uncertain')}
        elif request.preview_type=='split_faces':
            if len(ids)!=1:raise CommandConflict('SELECTION_SCOPE_INVALID')
            report=doc.split_face_preview(ids[0])
        elif request.preview_type=='merge_suggest':
            if not ids:raise CommandConflict('SELECTION_SCOPE_INVALID')
            report=doc.merge_suggest(ids)
            # Discovery also includes immediate close faces across a narrow gap.
            # They stay unselected suggestions; execution still uses exact previews.
            from statistics import median
            from shapely import STRtree, union_all
            from shapely.geometry import shape
            faces=[feature for feature in features if feature['feature_type']=='face']
            face_geometries=[shape(feature['geometry']) for feature in faces]
            selected_geometries=[shape(feature['geometry']) for feature in faces if feature['feature_id'] in request.feature_ids]
            selected_union=union_all(selected_geometries)
            widths=[feature['stroke_width_px'] for feature in features if feature['feature_type']=='line' and feature['lifecycle_status']=='active' and shape(feature['geometry']).intersects(selected_union)]
            distance=min(100.,2*median(widths)) if widths else 2.
            tree=STRtree(face_geometries)
            nearby=set(int(index) for geometry in selected_geometries for index in tree.query(geometry,predicate='dwithin',distance=distance))
            existing={item['eid'] for item in report['candidates']}
            seed_labels={feature.get('algorithm_label') for feature in faces if feature['feature_id'] in request.feature_ids}
            for index in sorted(nearby,key=lambda index:faces[index]['feature_id']):
                feature=faces[index];eid=reverse[feature['feature_id']][1]
                if eid in existing:continue
                if len(report['candidates'])>=1000:raise CommandConflict('FACE_MERGE_CANDIDATE_LIMIT',{'limit':1000})
                risks=['nearby_gap'] if selected_union.distance(face_geometries[index])>0 else ['adjacent_unverified']
                if feature.get('algorithm_label') not in seed_labels:risks.append('mixed_label')
                report['candidates'].append({'eid':eid,'rgb':feature.get('fill_color'),'label':feature.get('algorithm_label'),'area':face_geometries[index].area,'risks':risks,'suggested':False})
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
            group['bridge_feature_ids']=[identities[('face',index)] for index in group.get('bridge_faces',[]) if ('face',index) in identities];affected.update(group['bridge_feature_ids'])
            group['corner_contact_feature_ids']=[identities[('face',index)] for index in group.get('corner_contact_faces',[]) if ('face',index) in identities]
    elif request.preview_type=='heal_faces':
        for item in normalized.get('candidates',[]):
            item['feature_id']=identities.get(('face',item['id']))
            item['target_feature_id']=identities.get(('face',item.get('target')))
            item['receiver_options']=[identities[('face',index)] for index in item.get('receiver_options',[]) if ('face',index) in identities]
            affected.update(value for value in (item['feature_id'],item['target_feature_id']) if value)
        from mapvector.application.face_repairs import annotate_heal_residue
        annotate_heal_residue(connection,project_id,request.asset_id,normalized,project_dir)
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
        # Selected-text cleanup uses canonical assessment identities. Legacy
        # overlap-only candidates cannot silently broaden cleanup authority.
        from mapvector.application.text_layer_assessment import assess
        face_ids={fid for group in normalized.get('groups',[]) for fid in group['feature_ids']}
        line_ids={item['feature_id'] for item in normalized.get('line_info',[]) if item.get('feature_id') and item.get('suggested')}
        protected={item['feature_id'] for item in normalized.get('line_info',[]) if item.get('feature_id') and not item.get('suggested')}
        extra_faces=set();extra_lines=set();assessment_face_protection={}
        if request.feature_ids:
            assessment=assess(connection,project_id,request.asset_id,project_dir,request.feature_ids,residue_context=residue_context)
            for item in assessment['items']:
                extra_faces.update(item['suspected_face_ids']);extra_lines.update(item['suspected_line_ids'])
                protected.difference_update(item['suspected_line_ids'])
                protected.update(item['protected_line_ids'])
                for fid,entries in item.get('protected_face_reasons',{}).items():
                    # Source-scope guards persist. Independent-line guards are
                    # recalculated below after this preview's explicit review.
                    scope_entries=[entry for entry in entries if not entry.get('line_feature_id')]
                    if scope_entries:assessment_face_protection.setdefault(fid,[]).extend(scope_entries)
            face_ids=set(extra_faces)
            line_ids=set(extra_lines)
        # The display/cleanup box is the same for legacy and evidence candidates.
        from shapely.geometry import box as region_box,shape as feature_shape
        cleanup_region=feature_shape(residue_region) if residue_region else region_box(*normalized['box'])
        region=cleanup_region.buffer(-1e-6)
        if residue_region_source=='ocr_quad':
            valid_faces={feature['feature_id'] for feature in features if feature['feature_type']=='face' and cleanup_region.buffer(1e-6).covers(feature_shape(feature['geometry']))}
            face_ids.intersection_update(valid_faces|set(assessment_face_protection));extra_faces.intersection_update(valid_faces|set(assessment_face_protection))
        for feature in features:
            if feature['feature_type']=='line' and feature['lifecycle_status']=='active' and feature_shape(feature['geometry']).intersection(region).length>1e-7:
                if feature['feature_id'] not in line_ids|extra_lines or not cleanup_region.buffer(1e-6).covers(feature_shape(feature['geometry'])):protected.add(feature['feature_id'])
        response['text_residue_display']={'bounds_px':normalized['box'],'face_feature_ids':sorted(face_ids|extra_faces),'line_feature_ids':sorted((line_ids|extra_lines)-protected),'protected_line_feature_ids':sorted(protected),'assessment_only_face_ids':sorted(extra_faces-face_ids),'assessment_only_line_ids':sorted(extra_lines-line_ids-protected),'preserves_existing_text':bool(request.feature_ids or normalized.get('existing')),'complete_region_available':True,'complete_region':request.complete_region,'cleanup_face_feature_ids':sorted(face_ids|extra_faces),'cleanup_line_feature_ids':sorted((line_ids|extra_lines)-protected),'verification_pending_feature_ids':[],'verification_summary':{}}
    if request.preview_type=='text_residue' and residue_region is not None:
        response['text_residue_display'].update(region_geometry=residue_region,region_source=residue_region_source)
    internal_preview_data={'scope_bounds_px':scope_bounds} if scope_bounds is not None else {}
    if request.preview_type=='text_residue':internal_preview_data['residue_raster_source']=residue_raster_source
    review_text_ids=request.feature_ids if request.preview_type=='text_residue' else []
    if request.preview_type=='text_residue' and not review_text_ids:
        review_text_ids=[identities[('text',item['id'])] for item in normalized.get('existing',[]) if ('text',item['id']) in identities]
    if request.preview_type=='text_residue' and len(review_text_ids)==1:
        from mapvector.application.text_residue_review import review_lines,validate_confirmation
        display=response['text_residue_display']
        from mapvector.application.residue_policy import evidence as residue_evidence,is_kept,related_text_ids,is_confirmed
        text_id=review_text_ids[0]
        internal_preview_data['residue_review_target_text_id']=text_id
        internal_preview_data['residue_face_evidence']={fid:residue_evidence(connection,project_id,request.asset_id,text_id,fid) for fid in display['face_feature_ids']}
        kept_faces={fid for fid in display['face_feature_ids'] if is_kept(connection,project_id,request.asset_id,sorted(set([text_id]+related_text_ids(connection,project_id,request.asset_id,fid))),fid)}
        confirmed_faces={fid for fid in display['face_feature_ids'] if is_confirmed(connection,project_id,request.asset_id,fid)}
        display['manually_confirmed_face_feature_ids']=sorted(confirmed_faces)
        display['kept_face_feature_ids']=sorted(kept_faces)
        display['cleanup_face_feature_ids']=sorted(set(display['face_feature_ids'])-kept_faces-(set(assessment_face_protection)-confirmed_faces))
        internal_preview_data['line_review_evidence']=review_lines(connection,project_id,request.asset_id,text_id,features,display,residue_context=residue_context)
        verified=validate_confirmation(connection,project_id,request,display)
        internal_preview_data['verified_line_feature_ids']=verified
        display['line_feature_ids']=sorted(set(display['line_feature_ids'])|set(verified))
        display['cleanup_line_feature_ids']=display['line_feature_ids']
        display['assessment_only_line_ids']=sorted(set(display['assessment_only_line_ids'])-set(display['protected_line_feature_ids']))
        display['verification_summary'].update(face_count=len(display['cleanup_face_feature_ids']),line_count=len(display['cleanup_line_feature_ids']),kept_face_count=len(kept_faces))
    elif request.preview_type=='text_residue':
        from mapvector.application.text_residue_review import protect_without_target
        protect_without_target(connection,project_id,request.asset_id,features,response['text_residue_display'])
    if request.preview_type=='text_residue':
        # Keep the review overlay protected, while only the explicit verified
        # set can be included in the complete plan.
        for item in normalized.get('line_info',[]):
            if item.get('feature_id') in response['text_residue_display']['protected_line_feature_ids']:item['suggested']=False
    if request.preview_type=='text_residue':
        from mapvector.application.face_residue_protection import face_line_protection,effective_line_policies
        display=response['text_residue_display']
        line_policies=effective_line_policies(connection,project_id,request.asset_id,features)
        protected_faces=face_line_protection(features,display['face_feature_ids'],display['cleanup_line_feature_ids'],line_policies)
        for fid,entries in assessment_face_protection.items():
            if fid in display['face_feature_ids']:protected_faces.setdefault(fid,[]).extend(entries)
        display.update(protected_face_feature_ids=sorted(protected_faces),protected_face_reasons=protected_faces)
        display['cleanup_face_feature_ids']=sorted(set(display['cleanup_face_feature_ids'])-(set(protected_faces)-set(display.get('manually_confirmed_face_feature_ids',[]))))
        display['verification_summary'].update(protected_face_count=len(protected_faces),face_count=len(display['cleanup_face_feature_ids']))
        # Persist effective policies so the geometry-only planner repeats hard
        # checks without querying mutable state outside its coherent preview.
        display['line_semantic_policies']=line_policies
    if request.preview_type=='text_residue' and request.complete_region:
        from mapvector.application.residue_cleanup import plan_changes
        text_ids=request.feature_ids or [identities[('text',item['id'])] for item in normalized.get('existing',[]) if ('text',item['id']) in identities]
        if len(text_ids)!=1:raise CommandConflict('TEXT_TARGET_REQUIRED')
        changes,split_sources=plan_changes(features,response['text_residue_display'],None,request.base_revision+1,datetime.now(timezone.utc).isoformat(),text_ids[0],request.verified_line_feature_ids,request.face_assignments)
        response['text_residue_display']['cleanup_face_feature_ids']=sorted(new['feature_id'] for old,new in changes if new['feature_type']=='face' and new['lifecycle_status']=='superseded')
        response['text_residue_display']['cleanup_line_feature_ids']=sorted(new['feature_id'] for old,new in changes if new['feature_type']=='line' and new['lifecycle_status']=='isolated')
        from mapvector.application.residue_cleanup_preview import cleanup_scene
        response['cleanup_preview']=cleanup_scene(connection,features,changes,response['text_residue_display']['bounds_px'],project_id,split_sources)
        internal_preview_data.update({'complete_cleanup_target_text_id':text_ids[0],'complete_cleanup_split_sources':split_sources,'complete_cleanup_changes':[{'before':old,'after':new} for old,new in changes]})
        response['text_residue_display']['verification_summary'].update({'face_count':len(response['text_residue_display']['cleanup_face_feature_ids']),'line_count':len(response['text_residue_display']['cleanup_line_feature_ids']),'outside_line_parts':len(split_sources)})
    record=(preview_id,project_id,request.asset_id,request.base_revision,expires,request.model_dump_json(),json.dumps({**response,**internal_preview_data},ensure_ascii=False,default=str),digest)
    return response,record


def create_preview(connection,project_id,request,project_dir):
    response,record=prepare_preview(connection,project_id,request,project_dir)
    connection.execute('INSERT INTO edit_preview VALUES (?,?,?,?,?,?,?,?)',record)
    return response

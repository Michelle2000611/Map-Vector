"""Build an ephemeral legacy Document from SQLite-derived features; never cache it."""
import copy
import json
from uuid import uuid4

import geopandas as gpd
import numpy as np
from shapely.geometry import shape,mapping

from mapvector.algorithms.legacy_editor.core import Document,FACE,LINE,TEXT_COLS,default_styles,EditError


def document(features,width,height,image=None,groups=None,styles=None):
    d=Document.__new__(Document)
    identities={};records={'face':[],'line':[],'text':[],'isolated_line':[]}
    next_line=0
    for f in features:
        layer='isolated_line' if f['feature_type']=='line' and f['lifecycle_status']=='isolated' else f['feature_type']
        index=next_line if layer in ('line','isolated_line') else len(records[layer])
        if layer in ('line','isolated_line'):next_line+=1
        identities[(layer,index)]=f['feature_id']
        row={'_eid':index,'geometry':shape(f['geometry']),'legend_id':f.get('style_id')}
        if layer=='face':
            row.update(rgb=f['fill_color'],label=f['algorithm_label'],colour_class=f['color_class_id'],observed_px=f['observed_area_px2'],inferred_px=f['inferred_area_px2'],source=f['source_type'],merged_from=None,face_group='')
        elif layer in ('line','isolated_line'):
            row.update(line_id=f['feature_id'],logical_id=f['feature_id'],kind='dash' if f['line_pattern']=='dashed' else f['line_pattern'],width_px=f['stroke_width_px'],rgb=f['stroke_color'],source=f['source_type'],draw_order=f['draw_order'],line_role=f['line_role'].upper())
        else:
            bbox=f['display_bbox_px'] or [*f['geometry']['coordinates'],*f['geometry']['coordinates']]
            row.update(label_id=f['feature_id'],text=f['text_value'],ocr_text=f['original_text'] or '',ocr_score=0.,font_px=f['font_size_px'],angle_deg=f['rotation_deg'],anchor='center',rgb=f['text_color'],box_x0=bbox[0],box_y0=bbox[1],box_x1=bbox[2],box_y1=bbox[3],source=f['source_type'],review_status='HUMAN_EDITED',review_reason='',reviewed_at='',review_actor='')
        records[layer].append(row)
    def frame(layer,columns):
        return gpd.GeoDataFrame(records[layer] if records[layer] else {key:[] for key in [*columns,'geometry','_eid']},geometry='geometry')
    d.F=frame('face',['rgb','label','colour_class','observed_px','inferred_px','source','merged_from','face_group','legend_id'])
    d.L=frame('line',['line_id','logical_id','kind','width_px','rgb','source','draw_order','line_role','legend_id'])
    d.T=frame('text',TEXT_COLS);d.Q=frame('isolated_line',d.L.columns.drop('geometry').tolist())
    d.W=width;d.H=height;d.img=image;d.other={};d.src=None;d.src_sha=None
    d.face_cols=[key for key in d.F.columns if key not in ('geometry','_eid')];d.line_cols=[key for key in d.L.columns if key not in ('geometry','_eid')]
    d.F0=d.F.copy();d.L0=d.L.copy();d.T0=d.T.copy();d.next_f=len(d.F);d.next_l=next_line;d.next_t=len(d.T);d.next_fg=1
    d.styles=default_styles();d.undo=[];d.redo=[];d.log=[];d.dirty=False;d.version=0;d.previews={};d._pid=0;d.roi=None
    for group in groups or []:
        column='face_group' if group['feature_type']=='face' else 'logical_id'
        frame=d.F if group['feature_type']=='face' else d.L
        members=set(group['feature_ids'])
        indices=[index for (kind,index),identity in identities.items() if kind==group['feature_type'] and identity in members]
        frame.loc[frame['_eid'].isin(indices),column]=group['group_id']
    for style in styles or []:
        d.styles[style['style_id']]={'kind':style['feature_type'],'name':style['style_name'],'rgb':style['fill_color'] if style['feature_type']=='face' else style['stroke_color'],'width':style['stroke_width_px'] or 0,'line_type':'dash' if style['line_pattern']=='dashed' else style['line_pattern'] or '', 'dash':','.join(str(value) for value in json.loads(style['dash_pattern_px'])),'tooth_spacing':style['tooth_spacing_px'] or 0,'tooth_size':style['tooth_height_px'] or 0,'tooth_side':style['tooth_side'] or 'left'}
    return d,identities


def apply(features,asset,command,now,image=None,preview_request=None,groups=None,styles=None,inherited_memberships=None):
    d,identities=document(features,asset['width_px'],asset['height_px'],image,groups,styles)
    original={f['feature_id']:f for f in features}
    by_id={value:key for key,value in identities.items()}
    ids=[]
    for identity in command.feature_ids:
        if identity not in by_id:raise EditError('Unknown feature '+identity)
        ids.append(by_id[identity][1])
    operation=command.operation_type
    expected_kind='face' if operation.startswith('merge_') else command.feature_type if operation=='set_feature_color' else 'text' if operation=='delete_text' else 'line'
    if operation not in ('create_line','heal_faces','split_faces','cleanup_text_residue'):
        for identity in command.feature_ids:
            kind=by_id[identity][0]
            expected='isolated_line' if operation=='restore_lines' else expected_kind
            if kind!=expected:raise EditError('Feature category or lifecycle does not match command')
    if operation=='merge_adjacent_faces':d.merge_faces(ids,command.allow_mixed_algorithm_labels)
    elif operation=='merge_face_components':d.merge_components(ids,command.allow_mixed_algorithm_labels)
    elif operation=='create_line':d.add_line(command.coordinates,command.stroke_width_px,command.stroke_color,snap=command.snap_px)
    elif operation=='split_line':d.split_line(ids[0],command.x,command.y)
    elif operation=='join_lines':d.join_lines(ids,command.max_gap_px)
    elif operation=='set_feature_color':d.recolour(FACE if command.feature_type=='face' else LINE,ids,command.color)
    elif operation=='set_line_width':d.rewidth(ids,command.stroke_width_px)
    elif operation=='set_line_role':d.set_role(ids,command.line_role.upper())
    elif operation=='delete_lines':d.delete_lines(ids)
    elif operation=='isolate_lines':d.isolate_lines(ids,command.isolation_reason)
    elif operation=='restore_lines':d.restore_residue_lines(ids)
    elif operation=='delete_text':d.delete_text(ids[0])
    elif operation=='line_to_face':d.line_to_face(ids,command.stroke_width_px,command.fill_color)
    elif operation in ('heal_faces','split_faces','cleanup_text_residue'):
        if preview_request is None:raise EditError('Preview required')
        if operation=='heal_faces':
            pv=d.heal_preview(d.gesture('brush',preview_request.points,preview_request.radius_px),preview_request.max_area_px2)
            if any(identity not in by_id or by_id[identity][0]!='face' for identity in command.accept_uncertain_feature_ids):raise EditError('Uncertain face selection includes unknown or wrong-layer features')
            accepted=[by_id[identity][1] for identity in command.accept_uncertain_feature_ids]
            d.heal_apply(pv['preview_id'],accepted,command.allow_mixed_algorithm_labels)
        elif operation=='split_faces':
            line_ids=[by_id[identity][1] for identity in preview_request.feature_ids if identity in by_id and by_id[identity][0]=='line']
            if len(line_ids)!=1:raise EditError('Exactly one split line is required')
            pv=d.split_face_preview(line_ids[0]);d.split_face_apply(pv['preview_id'])
        else:
            pv=d.text_preview(preview_request.bounds_px,ocr=False)
            if preview_request.feature_ids:
                targets=preview_request.feature_ids
                if len(targets)!=1 or targets[0] not in by_id or by_id[targets[0]][0]!='text':raise EditError('Residue cleanup requires one explicit text target')
                target=by_id[targets[0]][1]
                stored=d.previews[pv['preview_id']]
                stored['existing']=[item for item in stored.get('existing',[]) if item['id']==target]
                if not stored['existing']:raise EditError('Explicit residue text target is outside preview')
            elif len(d.previews[pv['preview_id']].get('existing',[]))>1:
                raise EditError('Multiple existing texts overlap; choose the text object before residue cleanup')
            if command.line_feature_ids is not None and any(identity not in by_id or by_id[identity][0]!='line' for identity in command.line_feature_ids):raise EditError('Residue line selection includes unknown or wrong-layer features')
            selected_lines=None if command.line_feature_ids is None else [by_id[identity][1] for identity in command.line_feature_ids]
            assignments={index:by_id[identity][1] for index,identity in command.face_assignments.items() if identity in by_id and by_id[identity][0]=='face'}
            if len(assignments)!=len(command.face_assignments):raise EditError('Residue assignment includes unknown or wrong-layer features')
            existing=d.previews[pv['preview_id']].get('existing') or []
            if existing:
                target=next((int(item['id']) for item in existing if item.get('anchor_in_box')),int(existing[0]['id']))
                original_text=d.T.loc[d.T['_eid']==target].iloc[0]
                # Geometric cleanup must be independent of unsaved text form values.
                clean_text=str(original_text['text']);clean_size=float(original_text['font_px'])
                clean_angle=float(original_text['angle_deg']);clean_color=original_text['rgb']
            else:
                if command.text_value is None:raise EditError('Text is required when cleanup creates a new text object')
                clean_text=command.text_value;clean_size=command.font_size_px
                clean_angle=command.rotation_deg;clean_color=command.text_color
            d.text_apply(pv['preview_id'],clean_text,clean_size,clean_angle,clean_color,assign=assignments,line_ids=selected_lines,preserve_existing=True)
    else:raise EditError('Unsupported adapter operation')
    result={};changes=[]
    residue_text_id=identities.get(('text',getattr(d,'_last_text',{}).get('text_id')))
    if operation=='cleanup_text_residue' and residue_text_id is None and getattr(d,'_last_text',None):
        residue_text_id=str(uuid4());identities[('text',d._last_text['text_id'])]=residue_text_id
    for kind,frame in (('face',d.F),('line',d.L),('isolated_line',d.Q),('text',d.T)):
        for _,row in frame.iterrows():
            index=int(row['_eid'])
            identity=identities.get((kind,index))
            if kind=='isolated_line' and row.get('line_id') in original:identity=str(row['line_id'])
            if kind=='line' and row.get('line_id') in original and original[str(row['line_id'])]['lifecycle_status']=='isolated':identity=str(row['line_id'])
            if identity is None:identity=str(uuid4())
            previous=original.get(identity)
            if kind=='text' and previous is not None:
                result[identity]=copy.deepcopy(previous)
                continue
            feature_type='line' if kind=='isolated_line' else kind
            geom=row.geometry;bounds=geom.bounds
            if not geom.is_valid or geom.is_empty:raise EditError('Invalid resulting geometry')
            if bounds[0]<-1e-6 or bounds[1]<-1e-6 or bounds[2]>asset['width_px']+1e-6 or bounds[3]>asset['height_px']+1e-6:raise EditError('Resulting geometry lies outside asset pixel bounds')
            value={**previous} if previous else {'feature_id':identity,'project_id':asset['project_id'],'asset_id':asset['asset_id'],'origin_run_id':None,'feature_type':feature_type,'geometry_type':geom.geom_type,'style_id':None,'source_type':'manual','created_at':now}
            value.update(geometry_type=geom.geom_type,geometry=json.loads(json.dumps(mapping(geom))),bbox_min_x_px=bounds[0],bbox_min_y_px=bounds[1],bbox_max_x_px=bounds[2],bbox_max_y_px=bounds[3],lifecycle_status='isolated' if kind=='isolated_line' else 'active',updated_at=now,revision=command.base_revision+1)
            if feature_type=='face':
                value.update(fill_color=row['rgb'],algorithm_label=previous['algorithm_label'] if previous else str(row['label']) if row.get('label') is not None else None,color_class_id=previous['color_class_id'] if previous else str(row['colour_class']) if row.get('colour_class') is not None else None,area_px2=float(geom.area),observed_area_px2=previous['observed_area_px2'] if previous else None,inferred_area_px2=previous['inferred_area_px2'] if previous else None,coverage_status='unchecked')
            elif feature_type=='line':
                value.update(stroke_color=row['rgb'],stroke_width_px=float(row['width_px']),line_pattern=previous['line_pattern'] if previous else 'solid',line_role=str(row.get('line_role','UNKNOWN')).lower(),length_px=float(geom.length),draw_order=int(row['draw_order'] or 0),isolation_reason=command.isolation_reason if kind=='isolated_line' and operation=='isolate_lines' else previous.get('isolation_reason') if previous else None,associated_text_feature_id=previous.get('associated_text_feature_id') if previous else None)
                if kind=='isolated_line' and value['isolation_reason'] is None:value['isolation_reason']='text_residue'
                if kind=='isolated_line' and operation=='cleanup_text_residue' and (previous is None or previous['lifecycle_status']!='isolated'):value['associated_text_feature_id']=residue_text_id
            else:
                changed=previous is not None and str(row['text']).strip()!=previous['text_value']
                value.update(text_value=str(row['text']).strip(),original_text=previous['original_text'] if previous else str(row.get('ocr_text') or '') or None,font_size_px=float(row['font_px']),rotation_deg=(float(row['angle_deg'])+180)%360-180,text_color=row['rgb'],text_anchor='center',text_content_revision=(previous['text_content_revision']+int(changed)) if previous else 0,review_status='manual_edited' if changed or previous is None and operation=='cleanup_text_residue' else previous['review_status'] if previous else 'required',review_basis='manual_content_edit' if changed or previous is None and operation=='cleanup_text_residue' else previous['review_basis'] if previous else 'none',review_reason_codes=previous['review_reason_codes'] if previous else [],reviewed_content_revision=None if changed or previous is None else previous['reviewed_content_revision'],reviewed_at=None if changed or previous is None else previous['reviewed_at'],reviewer_id=None if changed or previous is None else previous['reviewer_id'],cleanup_status=previous['cleanup_status'] if previous and operation=='cleanup_text_residue' and preview_request.feature_ids else 'partial' if operation=='cleanup_text_residue' and identity==residue_text_id else previous['cleanup_status'] if previous else 'not_checked',display_bbox_px=[float(row[key]) for key in ('box_x0','box_y0','box_x1','box_y1')],primary_candidate_id=previous['primary_candidate_id'] if previous else None,font_family=previous['font_family'] if previous else 'sans-serif')
            if previous is not None and feature_type=='text' and previous.get('layout_basis')=='ocr_quad_v2':
                value['display_bbox_px']=previous['display_bbox_px']
            if previous is None:
                style_id=row.get('legend_id')
                if style_id in d.styles and any(style['style_id']==style_id for style in styles or []):
                    value['style_id']=style_id
                if feature_type=='line':
                    value['line_pattern']='dashed' if row.get('kind')=='dash' else 'solid' if row.get('kind')=='manual' else str(row.get('kind') or 'solid')
                    if value['style_id']:value['line_pattern']=next(style['line_pattern'] for style in styles if style['style_id']==value['style_id'])
                if inherited_memberships is not None and feature_type in ('face','line'):
                    group_id=row.get('face_group' if feature_type=='face' else 'logical_id')
                    if any(group['group_id']==group_id for group in groups or []):inherited_memberships[identity]=group_id
            compare=lambda item:{key:value for key,value in item.items() if key not in ('updated_at','revision')}
            if previous is None or compare(previous)!=compare(value):changes.append((previous,value))
            result[identity]=value
    for identity,previous in original.items():
        if identity not in result:
            deleted={**previous,'lifecycle_status':'superseded' if operation.startswith('merge_') else 'deleted','revision':command.base_revision+1,'updated_at':now}
            changes.append((previous,deleted))
    return changes

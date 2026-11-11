import hashlib
import json
import math
from datetime import datetime, timezone
from uuid import uuid4

from shapely import from_wkb, to_wkb
from shapely.geometry import Point, shape

from mapvector.domain.commands import CreateText, EditCommand, ReviewText, UpdateText, HistoryCommand, GeometryCommand,SetRoi,GroupFeatures,UngroupFeatures,AdoptOcrCandidate
from mapvector.application.relations import apply_relations,restore_relation
from mapvector.domain.commands import SetStyle,BindStyle,SetLayer,ClassifyReview,RestoreOcrLayout
from mapvector.domain.commands import DeleteFaces,DeleteLines,DeleteText,SetFeatureProperties,RepairFace,ApplyLineCheck
from mapvector.application.appearance import apply_appearance
from mapvector.domain.ports import DatabasePort
from mapvector.application.ports import load_feature,restore_feature,update_index
from mapvector.geometry.text import display_bbox,ocr_layout


from mapvector.domain.errors import CommandConflict


def _remove_feature_relations(connection,feature_id,relation_changes,changed_groups):
    """Use the same reversible relation removal for every retired feature."""
    memberships=connection.execute('SELECT * FROM group_member WHERE feature_id=?',(feature_id,)).fetchall()
    for membership in memberships:
        member=dict(membership);gid=member['group_id']
        relation_changes.append(('group_member',gid+':'+feature_id,member,None))
        connection.execute('DELETE FROM group_member WHERE group_id=? AND feature_id=?',(gid,feature_id))
        if not any(item['group_id']==gid for item in changed_groups):changed_groups.append(dict(connection.execute('SELECT * FROM logical_group WHERE group_id=?',(gid,)).fetchone()))
    binding=connection.execute('SELECT * FROM feature_style WHERE feature_id=?',(feature_id,)).fetchone()
    if binding:
        relation_changes.append(('feature_style',feature_id,dict(binding),None))
        connection.execute('DELETE FROM feature_style WHERE feature_id=?',(feature_id,))


class CommandService:
    def __init__(self, database: DatabasePort):
        self.database = database

    def apply(self, project_id: str, command: EditCommand, actor_id: str = 'local-user') -> dict:
        payload = command.model_dump(mode='json')
        # Preserve the digest of previously accepted repair commands that
        # predate review acknowledgements. Nonempty reviews stay hash-bound.
        if isinstance(command,RepairFace) and not command.verified_review_candidate_ids:payload.pop('verified_review_candidate_ids')
        if 'verified_line_feature_ids' in payload and not command.verified_line_feature_ids:payload.pop('verified_line_feature_ids')
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
        with self.database.transaction() as connection:
            previous = connection.execute('SELECT request_sha256,result_summary FROM operation WHERE project_id=? AND idempotency_key=?', (project_id, command.idempotency_key)).fetchone()
            if connection.execute('SELECT 1 FROM run_adoption_request WHERE project_id=? AND idempotency_key=?',(project_id,command.idempotency_key)).fetchone():raise CommandConflict('IDEMPOTENCY_CONFLICT')
            if previous:
                if previous['request_sha256'] != digest:
                    raise CommandConflict('IDEMPOTENCY_CONFLICT')
                return json.loads(previous['result_summary'])
            project = connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?', (project_id,)).fetchone()
            if project is None:
                raise KeyError(project_id)
            if project['working_revision'] != command.base_revision:
                raise CommandConflict('REVISION_CONFLICT', {'working_revision': project['working_revision']})
            if project['current_asset_id'] != command.asset_id:
                raise CommandConflict('ASSET_RESULT_MISMATCH')
            asset = connection.execute('SELECT width_px,height_px FROM asset WHERE asset_id=? AND project_id=?', (command.asset_id, project_id)).fetchone()
            if asset is None:
                raise CommandConflict('ASSET_RESULT_MISMATCH')
            if command.operation_type=='restore_lines':
                from mapvector.application.residue_cleanup import validate_line_restore
                validate_line_restore(connection,project_id,command.asset_id,command.feature_ids)
            timestamp = datetime.now(timezone.utc).isoformat()
            before = []
            after = []
            removed = []
            review_summary = {}
            history_changes = []
            review_events = []
            target_operation_id = None
            relation_changes=[];changed_groups=[];changed_styles=[];changed_layers=[];roi=None
            if isinstance(command, CreateText):
                if not (0 <= command.x <= asset['width_px'] and 0 <= command.y <= asset['height_px']):
                    raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
                text = command.text_value.strip()
                if not text:
                    raise CommandConflict('VALIDATION_ERROR')
                feature_id = str(uuid4())
                geometry = Point(command.x, command.y)
                geometry_wkb = to_wkb(geometry, hex=False, output_dimension=2, byte_order=1)
                box = geometry.bounds
                connection.execute('INSERT INTO feature VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (feature_id, project_id, command.asset_id, None, 'text', 'Point', geometry_wkb, *box, 'active', 'manual', None, command.base_revision + 1, timestamp, timestamp))
                rotation=(command.rotation_deg+180)%360-180
                display = display_bbox(command.x,command.y,text,command.font_size_px,rotation)
                connection.execute('INSERT INTO text_attribute (feature_id,text_value,original_text,font_size_px,rotation_deg,text_color,text_anchor,text_content_revision,review_status,review_reason_codes,reviewed_content_revision,reviewed_at,reviewer_id,cleanup_status,display_bbox_px,primary_candidate_id,font_family,review_basis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (feature_id, text, None, command.font_size_px, rotation, command.text_color, 'center', 0, 'manual_edited', '[]', None, None, None, 'not_checked', json.dumps(display), None, 'sans-serif', 'manual_content_edit'))
                update_index(connection,feature_id)
                after.append(self._feature(connection, feature_id))
                before.append(None)
            elif isinstance(command, UpdateText):
                feature_id = command.feature_ids[0]
                row = connection.execute('SELECT f.*,t.* FROM feature f JOIN text_attribute t USING(feature_id) WHERE f.feature_id=? AND f.project_id=? AND f.asset_id=? AND f.lifecycle_status=char(97,99,116,105,118,101)', (feature_id, project_id, command.asset_id)).fetchone()
                if row is None:
                    raise CommandConflict('RESOURCE_NOT_FOUND')
                state = dict(row)
                before.append(self._feature(connection, feature_id))
                geometry = from_wkb(row['geometry_wkb'])
                x, y = command.x if command.x is not None else geometry.x, command.y if command.y is not None else geometry.y
                if not (0 <= x <= asset['width_px'] and 0 <= y <= asset['height_px']):
                    raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
                text = command.text_value.strip() if command.text_value is not None else row['text_value']
                size = command.font_size_px if command.font_size_px is not None else row['font_size_px']
                rotation = (command.rotation_deg if -180<=command.rotation_deg<180 else (command.rotation_deg+180)%360-180) if command.rotation_deg is not None else row['rotation_deg']
                if abs(rotation-row['rotation_deg'])<1e-10:rotation=row['rotation_deg']
                color = command.text_color if command.text_color is not None else row['text_color']
                content_changed = text != row['text_value']
                point = Point(x, y)
                bbox = point.bounds
                connection.execute('UPDATE feature SET geometry_wkb=?,bbox_min_x_px=?,bbox_min_y_px=?,bbox_max_x_px=?,bbox_max_y_px=?,revision=?,updated_at=? WHERE feature_id=?', (to_wkb(point, hex=False, output_dimension=2, byte_order=1), *bbox, command.base_revision + 1, timestamp, feature_id))
                connection.execute('UPDATE text_attribute SET text_value=?,font_size_px=?,rotation_deg=?,text_color=?,text_content_revision=text_content_revision+?,review_status=?,review_basis=?,reviewed_content_revision=NULL,reviewed_at=NULL,reviewer_id=NULL,display_bbox_px=? WHERE feature_id=?', (text, size, rotation, color, int(content_changed), 'manual_edited' if content_changed else row['review_status'], 'manual_content_edit' if content_changed else row['review_basis'], json.dumps(display_bbox(x,y,text,size,rotation)), feature_id))
                if any(getattr(command,k) is not None for k in ('text_value','font_size_px','rotation_deg','x','y')) and (content_changed or size!=row['font_size_px'] or rotation!=row['rotation_deg'] or x!=geometry.x or y!=geometry.y):
                    connection.execute("UPDATE text_attribute SET layout_width_px=NULL,layout_height_px=NULL,baseline_offset_px=NULL,layout_runs='[]',layout_basis='manual' WHERE feature_id=?",(feature_id,))
                if not content_changed and size==row['font_size_px'] and rotation==row['rotation_deg'] and x==geometry.x and y==geometry.y:
                    connection.execute('UPDATE text_attribute SET display_bbox_px=? WHERE feature_id=?',(row['display_bbox_px'],feature_id))
                if not content_changed:
                    connection.execute('UPDATE text_attribute SET reviewed_content_revision=?,reviewed_at=?,reviewer_id=? WHERE feature_id=?', (row['reviewed_content_revision'], row['reviewed_at'], row['reviewer_id'], feature_id))
                update_index(connection,feature_id)
                after.append(self._feature(connection, feature_id))
            elif isinstance(command, HistoryCommand):
                from mapvector.application.history import apply_history
                target_operation_id=command.target_operation_id
                history_changes,relation_changes,after,removed,changed_groups,changed_styles,changed_layers,roi=apply_history(connection,project_id,command,timestamp)
            elif isinstance(command,RestoreOcrLayout):
                from mapvector.application.text_layout import repair
                targets=[row[0] for row in connection.execute('SELECT asset_id FROM asset WHERE project_id=?',(project_id,))] if command.all_assets else [command.asset_id]
                skipped=[]
                for target_asset in targets:
                    changed,kept=repair(connection,project_id,target_asset,command.base_revision+1,timestamp,self.database.path.parents[1]);history_changes.extend(changed);skipped.extend(kept)
                after.extend(new for old,new in history_changes if new['asset_id']==command.asset_id)
                review_summary={'ocr_layout':{'updated':len(history_changes),'skipped':len(skipped),'assets':len(targets)}}
            elif isinstance(command,ClassifyReview):
                from mapvector.application.review import classify
                history_changes=classify(connection,project_id,command,timestamp)
                after.extend(value for old,value in history_changes)
            elif isinstance(command,(SetStyle,BindStyle,SetLayer)):
                relation_changes,history_changes,changed_styles,changed_layers=apply_appearance(connection,project_id,command,command.base_revision+1,timestamp)
                after.extend(value for old,value in history_changes)
            elif isinstance(command,AdoptOcrCandidate):
                candidate=connection.execute('SELECT * FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(command.candidate_id,project_id,command.asset_id)).fetchone()
                if candidate is None:raise CommandConflict('RESOURCE_NOT_FOUND')
                if candidate['text_feature_id'] is not None:raise CommandConflict('OCR_CANDIDATE_ALREADY_ADOPTED',{'text_feature_id':candidate['text_feature_id']})
                quad=json.loads(candidate['detected_quad_px']) if candidate['detected_quad_px'] else None
                if not quad or len(quad)!=4:raise CommandConflict('OCR_EVIDENCE_MISSING')
                from mapvector.application.ocr_fusion import default_candidate_text,existing_text_duplicate
                text=(command.text_value.strip() if command.text_value is not None else default_candidate_text(candidate))
                if command.candidate_mode=='create':
                    duplicate=existing_text_duplicate(connection,project_id,command.asset_id,candidate,text,quad)
                    if duplicate:raise CommandConflict(duplicate[1],{'text_feature_id':duplicate[0],'reason':'同位置已有对应文字，请定位原对象，或明确更新原对象'})
                try:layout=ocr_layout(text,quad)
                except (ValueError,TypeError):raise CommandConflict('OCR_EVIDENCE_MISSING')
                x,y,size,angle=layout['x'],layout['y'],layout['font_size_px'],layout['rotation_deg']
                if not text or not(0<=x<=asset['width_px'] and 0<=y<=asset['height_px']):raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
                if command.candidate_mode=='update':
                    if len(command.feature_ids)!=1:raise CommandConflict('OCR_TARGET_REQUIRED')
                    feature_id=command.feature_ids[0];old=load_feature(connection,feature_id)
                    if old['project_id']!=project_id or old['asset_id']!=command.asset_id or old['feature_type']!='text' or old['lifecycle_status']!='active':raise CommandConflict('OCR_TARGET_INVALID')
                    before.append(old);point=shape(old['geometry'])
                    updated={**old,'text_value':text,'original_text':candidate['raw_text'],'primary_candidate_id':command.candidate_id,'text_content_revision':old['text_content_revision']+int(text!=old['text_value']),'review_status':'required','review_basis':'none','review_reason_codes':[],'reviewed_content_revision':None,'reviewed_at':None,'reviewer_id':None,'revision':command.base_revision+1,'updated_at':timestamp}
                    if text!=old['text_value']:
                        updated.update(display_bbox_px=display_bbox(point.x,point.y,text,old['font_size_px'],old['rotation_deg']),layout_width_px=None,layout_height_px=None,baseline_offset_px=None,layout_basis='manual',layout_runs=[])
                    restore_feature(connection,updated)
                else:
                    feature_id=str(uuid4());point=Point(x,y);bounds=point.bounds
                    connection.execute('INSERT INTO feature VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(feature_id,project_id,command.asset_id,candidate['run_id'],'text','Point',to_wkb(point),*bounds,'active','algorithm',None,command.base_revision+1,timestamp,timestamp))
                    connection.execute('INSERT INTO text_attribute (feature_id,text_value,original_text,font_size_px,rotation_deg,text_color,text_anchor,text_content_revision,review_status,review_reason_codes,reviewed_content_revision,reviewed_at,reviewer_id,cleanup_status,display_bbox_px,primary_candidate_id,font_family,review_basis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(feature_id,text,candidate['raw_text'],size,angle,'#000000','center',0,'required','[]',None,None,None,'not_checked',json.dumps(display_bbox(x,y,text,size,angle)),command.candidate_id,'sans-serif','none'))
                    before.append(None)
                connection.execute("UPDATE ocr_candidate SET text_feature_id=?,candidate_status='adopted' WHERE candidate_id=?",(feature_id,command.candidate_id))
                if command.candidate_mode=='create':
                    from mapvector.application.text_layout import set_ocr_layout
                    restore_feature(connection,set_ocr_layout(connection,feature_id,quad,self.database.path.parents[1]))
                    from mapvector.application.review import route_adopted_text
                    route_adopted_text(connection,feature_id)
                update_index(connection,feature_id)
                after.append(load_feature(connection,feature_id))
            elif isinstance(command,(SetRoi,GroupFeatures,UngroupFeatures)):
                relation_changes,changed_groups,roi=apply_relations(connection,project_id,command,command.base_revision+1)
            elif isinstance(command,ApplyLineCheck):
                from mapvector.application.line_checks import plan_changes
                history_changes,line_relations,changed_groups,lineages,line_evidence=plan_changes(connection,project_id,command,timestamp)
                review_summary={'line_check':line_evidence}
                for old,new in history_changes:
                    restore_feature(connection,new);update_index(connection,new['feature_id'])
                    if new['lifecycle_status'] in ('deleted','superseded'):
                        _remove_feature_relations(connection,new['feature_id'],relation_changes,changed_groups)
                        removed.append(new['feature_id'])
                    else:after.append(load_feature(connection,new['feature_id']))
                for kind,identity,old,new in line_relations:
                    restore_relation(connection,kind,identity,new)
                relation_changes.extend(line_relations)
            elif isinstance(command,RepairFace):
                from mapvector.application.face_repairs import plan_changes
                history_changes,repair_evidence=plan_changes(connection,project_id,command,timestamp,self.database.path.parents[1])
                review_summary={'face_repair':repair_evidence}
                for old,new in history_changes:
                    restore_feature(connection,new);update_index(connection,new['feature_id'])
                    if new['lifecycle_status'] in ('deleted','superseded'):
                        _remove_feature_relations(connection,new['feature_id'],relation_changes,changed_groups)
                        removed.append(new['feature_id'])
                    else:after.append(load_feature(connection,new['feature_id']))
            elif not isinstance(command,ReviewText):
                from mapvector.application.ports import apply_geometry
                from mapvector.domain.ports import get_ports
                EditError=get_ports().editor.error_type
                asset=dict(connection.execute('SELECT * FROM asset WHERE asset_id=? AND project_id=?',(command.asset_id,project_id)).fetchone())
                stored_preview=None
                if getattr(command,'preview_id',None):
                    stored_preview=connection.execute('SELECT * FROM edit_preview WHERE preview_id=? AND project_id=? AND asset_id=?',(command.preview_id,project_id,command.asset_id)).fetchone()
                stored_result=json.loads(stored_preview['result_json']) if stored_preview else {}
                scoped_features=None
                if stored_result.get('scope_bounds_px') is not None:
                    from mapvector.application.previews import residue_scope_features
                    scoped_features=residue_scope_features(connection,project_id,command.asset_id,stored_result['scope_bounds_px'])
                direct_feature_edit=isinstance(command,(DeleteFaces,DeleteLines,DeleteText,SetFeatureProperties))
                features=[] if direct_feature_edit else scoped_features if scoped_features is not None and getattr(command,'complete_region',False) else [load_feature(connection,row[0]) for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated') ORDER BY feature_id",(project_id,command.asset_id))]
                try:
                    preview_request=None;pixels=None;complete_plan=None
                    if getattr(command,'preview_id',None):
                        row=connection.execute('SELECT * FROM edit_preview WHERE preview_id=? AND project_id=? AND asset_id=?',(command.preview_id,project_id,command.asset_id)).fetchone()
                        if row is None or row['base_revision']!=command.base_revision or datetime.fromisoformat(row['expires_at'])<=datetime.now(timezone.utc):raise CommandConflict('PREVIEW_STALE')
                        from mapvector.domain.selection import PreviewRequest
                        preview_request=PreviewRequest.model_validate_json(row['request_json'])
                        actual_digest=hashlib.sha256(json.dumps(scoped_features if scoped_features is not None else features,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
                        if actual_digest!=row['input_sha256']:raise CommandConflict('PREVIEW_STALE')
                        expected={'heal_faces':'heal_faces','split_faces':'split_faces','cleanup_text_residue':'text_residue','merge_adjacent_faces':'merge_faces','merge_face_components':'merge_faces','join_lines':'join_lines','line_to_face':'line_to_face'}[command.operation_type]
                        if preview_request.preview_type!=expected:raise CommandConflict('PREVIEW_TYPE_MISMATCH')
                        if command.operation_type in ('merge_adjacent_faces','merge_face_components','join_lines','line_to_face') and set(preview_request.feature_ids)!=set(command.feature_ids):raise CommandConflict('PREVIEW_STALE')
                        if command.operation_type=='line_to_face' and (command.stroke_width_px!=preview_request.stroke_width_px or command.fill_color!=preview_request.fill_color):raise CommandConflict('PREVIEW_STALE')
                        if command.operation_type=='cleanup_text_residue':
                            if command.complete_region!=preview_request.complete_region:raise CommandConflict('PREVIEW_TYPE_MISMATCH')
                            if set(command.verified_line_feature_ids)!=set(preview_request.verified_line_feature_ids):raise CommandConflict('LINE_REVIEW_MISMATCH')
                            stored_result=json.loads(row['result_json'])
                            if 'line_review_evidence' in stored_result:
                                from mapvector.application.text_residue_review import validate_preview
                                validate_preview(connection,project_id,command.asset_id,command.base_revision,command.preview_id)
                            if command.verified_line_feature_ids:
                                from mapvector.application.text_residue_review import validate_confirmation
                                validate_confirmation(connection,project_id,preview_request,stored_result['text_residue_display'])
                            if command.line_feature_ids is not None and not set(command.line_feature_ids)<=set(stored_result.get('text_residue_display',{}).get('cleanup_line_feature_ids',[])):raise CommandConflict('LINE_REVIEW_FORBIDDEN')
                            if not command.complete_region and command.line_feature_ids is None and 'text_residue_display' in stored_result:
                                safe={item['feature_id'] for item in stored_result['legacy_report'].get('line_info',[]) if item.get('suggested')}
                                command=command.model_copy(update={'line_feature_ids':sorted(safe&set(stored_result['text_residue_display']['cleanup_line_feature_ids']))})
                            if command.complete_region:
                                complete_plan=stored_result
                                if 'complete_cleanup_changes' not in complete_plan:raise CommandConflict('PREVIEW_STALE')
                        if complete_plan is None:
                            import numpy as np
                            from PIL import Image
                            with Image.open(self.database.path.parents[1]/asset['raster_rel_path']) as image:pixels=np.asarray(image.convert('RGB'))
                    from mapvector.application.previews import load_groups
                    groups=load_groups(connection,project_id,command.asset_id)
                    styles=[dict(row) for row in connection.execute('SELECT * FROM style WHERE project_id=?',(project_id,))]
                    inherited_memberships={};inherited_styles={}
                    if complete_plan is not None:
                        current_evidence={}
                        from mapvector.application.text_residue_review import validate_preview
                        # Decisions do not advance the revision; recheck metadata
                        # even when this stored geometry plan is still current.
                        if 'line_review_evidence' in complete_plan:
                            _,_,current_evidence=validate_preview(connection,project_id,command.asset_id,command.base_revision,command.preview_id)
                            if any(current_evidence.get(fid,{}).get('status')=='kept' for fid in complete_plan['text_residue_display']['cleanup_line_feature_ids']):raise CommandConflict('LINE_REVIEW_FORBIDDEN')
                        for target_id,source_id in complete_plan.get('complete_cleanup_split_sources',{}).items():
                            member=connection.execute('SELECT group_id FROM group_member WHERE feature_id=?',(source_id,)).fetchone()
                            if member:inherited_memberships[target_id]=member[0]
                            binding=connection.execute('SELECT style_id FROM feature_style WHERE feature_id=?',(source_id,)).fetchone()
                            if binding:inherited_styles[target_id]=binding[0]
                        changes=[]
                        if not complete_plan['complete_cleanup_changes']:raise CommandConflict('RESIDUE_ALREADY_CLEAN')
                        for item in complete_plan['complete_cleanup_changes']:
                            new=item['after'];new.update(revision=command.base_revision+1,updated_at=timestamp)
                            changes.append((item['before'],new))
                    elif direct_feature_edit:
                        from mapvector.application.feature_properties import plan_feature_edit
                        changes=plan_feature_edit(connection,project_id,command,timestamp)
                    else:changes=apply_geometry(features,asset,command,timestamp,pixels,preview_request,groups,styles,inherited_memberships)
                except EditError as exc:
                    message=str(exc)
                    code='FACES_NOT_EDGE_CONNECTED' if 'edge-connected' in message or 'share an edge' in message else 'DASH_JOIN_FORBIDDEN' if 'dash' in message.lower() else 'GEOMETRY_VALIDATION_FAILED'
                    raise CommandConflict(code,{'reason':message}) from exc
                # Text must exist before isolated residue lines establish their text association.
                for old,new in sorted(changes,key=lambda pair:0 if pair[1]['feature_type']=='text' else 1):
                    restore_feature(connection,new);update_index(connection,new['feature_id'])
                    if new['lifecycle_status'] in ('deleted','superseded') or complete_plan is not None and new['feature_id'] in set(complete_plan.get('complete_cleanup_split_sources',{}).values()):
                        _remove_feature_relations(connection,new['feature_id'],relation_changes,changed_groups)
                    history_changes.append((old,new))
                    if new['lifecycle_status'] in ('deleted','superseded'):
                        removed.append(new['feature_id'])
                    else:
                        after.append(load_feature(connection,new['feature_id']))
                if complete_plan is not None:
                    from shapely.geometry import box
                    region=box(*complete_plan['text_residue_display']['bounds_px']).buffer(-1e-6)
                    pending=[]
                    for fid in complete_plan['text_residue_display']['face_feature_ids']:
                        if load_feature(connection,fid)['lifecycle_status']=='active':pending.append(fid)
                    for row_id in connection.execute("SELECT feature_id FROM feature WHERE asset_id=? AND feature_type='line' AND lifecycle_status='active' AND rowid IN (SELECT id FROM feature_index WHERE max_x>? AND min_x<? AND max_y>? AND min_y<?)",(command.asset_id,region.bounds[0],region.bounds[2],region.bounds[1],region.bounds[3])):
                        feature=load_feature(connection,row_id[0])
                        if row_id[0] in complete_plan['text_residue_display']['cleanup_line_feature_ids'] and shape(feature['geometry']).intersection(region).length>1e-7:pending.append(row_id[0])
                    from mapvector.application.text_layer_assessment import assess
                    remaining=assess(connection,project_id,command.asset_id,self.database.path.parents[1],[complete_plan['complete_cleanup_target_text_id']])
                    for assessment in remaining['items']:
                        # Existing assessment heuristics do not include hard
                        # protection metadata. Only planned line IDs are required.
                        pending.extend(assessment['suspected_face_ids']+[fid for fid in assessment['suspected_line_ids'] if fid in complete_plan['text_residue_display']['cleanup_line_feature_ids']])
                    if pending:raise CommandConflict('RESIDUE_CLEANUP_INCOMPLETE',{'feature_ids':sorted(set(pending))})
                    review_summary={'residue_cleanup':{'complete':True,'face_count':len(complete_plan['text_residue_display']['face_feature_ids']),'line_count':len(complete_plan['text_residue_display']['cleanup_line_feature_ids']),'text_unchanged':True,'remaining_count':0,'protected_line_count':len(complete_plan['text_residue_display']['protected_line_feature_ids'])}}
                    review_summary['residue_cleanup'].update(verified_line_feature_ids=preview_request.verified_line_feature_ids,kept_line_feature_ids=sorted(fid for fid,item in current_evidence.items() if item['status']=='kept'),split_sources=complete_plan.get('complete_cleanup_split_sources',{}))
                for fid,gid in inherited_memberships.items():
                    member={'group_id':gid,'feature_id':fid}
                    connection.execute('INSERT INTO group_member VALUES (?,?)',(gid,fid))
                    relation_changes.append(('group_member',gid+':'+fid,None,member))
                    if not any(item['group_id']==gid for item in changed_groups):changed_groups.append(dict(connection.execute('SELECT * FROM logical_group WHERE group_id=?',(gid,)).fetchone()))
                for fid,style_id in inherited_styles.items():
                    binding={'feature_id':fid,'style_id':style_id}
                    connection.execute('INSERT INTO feature_style VALUES (?,?)',(fid,style_id))
                    relation_changes.append(('feature_style',fid,None,binding))
            else:
                from mapvector.application.review_decision import decide
                history_changes,review_events,after,review_summary=decide(connection,project_id,command,timestamp,actor_id)
            revision = command.base_revision + 1
            from mapvector.application.history import synchronize_candidates
            face_only=isinstance(command,(RepairFace,ApplyLineCheck)) or command.operation_type=='cleanup_text_residue' and getattr(command,'complete_region',False)
            if isinstance(command,HistoryCommand):
                history_target=connection.execute('SELECT operation_type,result_summary FROM operation WHERE operation_id=? AND project_id=?',(command.target_operation_id,project_id)).fetchone()
                face_only=history_target is not None and (history_target['operation_type'] in ('repair_face_geometry','apply_line_check') or history_target['operation_type']=='cleanup_text_residue' and json.loads(history_target['result_summary']).get('review_summary',{}).get('residue_cleanup',{}).get('complete'))
            if not face_only:synchronize_candidates(connection,project_id)
            operation_id = str(uuid4())
            operation_type = command.operation_type
            result = {'operation_id': operation_id, 'result_revision': revision, 'upserted_features': after, 'removed_feature_ids': removed, 'changed_groups':changed_groups,'changed_styles':changed_styles,'changed_layers':changed_layers,'roi':roi, 'review_summary': review_summary, 'warnings': []}
            current_asset=connection.execute('SELECT current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()[0]
            result['current_asset_id']=current_asset
            result['roi_changed']=any(kind=='roi' for kind,identity,left,right in relation_changes)
            for group in result['changed_groups']:
                group['feature_ids']=[row[0] for row in connection.execute('SELECT feature_id FROM group_member WHERE group_id=? ORDER BY feature_id',(group['group_id'],))]
            connection.execute('INSERT INTO operation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (operation_id, project_id, operation_type, command.base_revision, revision, command.idempotency_key, digest, 'applied', actor_id, target_operation_id, json.dumps(result, ensure_ascii=False), timestamp))
            if isinstance(command,ApplyLineCheck):
                for source_id,target_id,attributes in lineages:
                    connection.execute('INSERT INTO feature_lineage VALUES (?,?,?,?,?,?,?)',(str(uuid4()),source_id,target_id,'merged_from',operation_id,json.dumps(attributes,ensure_ascii=False),None))
            for review_event in review_events:
                connection.execute('INSERT INTO review VALUES (?,?,?,?,?,?,?,?,?)', (*review_event, operation_id))
            if not isinstance(command, HistoryCommand):
                connection.execute("UPDATE operation SET operation_status='abandoned' WHERE project_id=? AND operation_status='undone'", (project_id,))
            for old, new in list(zip(before, after)) + history_changes:
                entity_id = (new or old)['feature_id']
                old_wkb = to_wkb(shape(old['geometry'])) if old else None
                new_wkb = to_wkb(shape(new['geometry'])) if new else None
                before_attributes={key:value for key,value in old.items() if key!='geometry'} if old else None
                after_attributes={key:value for key,value in new.items() if key!='geometry'} if new else None
                connection.execute('INSERT INTO operation_change VALUES (?,?,?,?,?,?,?,?,?)', (str(uuid4()), operation_id, 'feature', entity_id, json.dumps(before_attributes, ensure_ascii=False) if old else None, json.dumps(after_attributes, ensure_ascii=False) if new else None, old_wkb, new_wkb, '1.0'))
            for kind,identity,left,right in relation_changes:
                connection.execute('INSERT INTO operation_change VALUES (?,?,?,?,?,?,?,?,?)',(str(uuid4()),operation_id,kind,identity,json.dumps(left,ensure_ascii=False) if left else None,json.dumps(right,ensure_ascii=False) if right else None,to_wkb(shape(left['geometry'])) if left and kind=='roi' else None,to_wkb(shape(right['geometry'])) if right and kind=='roi' else None,'1.0'))
            if command.operation_type.startswith('merge_') or command.operation_type in ('heal_faces','cleanup_text_residue') or isinstance(command,RepairFace) and repair_evidence['merging_feature_ids']:
                sources=[old for old,new in history_changes if old is not None and (not isinstance(command,RepairFace) or old['feature_id'] in repair_evidence['merging_feature_ids'])]
                targets=[new for old,new in history_changes if new['lifecycle_status']=='active' and (not isinstance(command,RepairFace) or new['feature_id']==repair_evidence['source_feature_id'])]
                for source in sources:
                    for target in targets:
                        if source['feature_type']=='face' and target['feature_type']=='face' and source['feature_id']!=target['feature_id'] and shape(target['geometry']).covers(shape(source['geometry'])):
                            attributes={key:value for key,value in source.items() if key!='geometry'}
                            connection.execute('INSERT INTO feature_lineage VALUES (?,?,?,?,?,?,?)',(str(uuid4()),source['feature_id'],target['feature_id'],'merged_from',operation_id,json.dumps(attributes,ensure_ascii=False),None))
            if command.operation_type=='cleanup_text_residue' and getattr(command,'complete_region',False):
                for target_id,source_id in complete_plan.get('complete_cleanup_split_sources',{}).items():
                    source=next(old for old,new in history_changes if old and old['feature_id']==source_id)
                    connection.execute('INSERT INTO feature_lineage VALUES (?,?,?,?,?,?,?)',(str(uuid4()),source_id,target_id,'split_from',operation_id,json.dumps({k:v for k,v in source.items() if k!='geometry'},ensure_ascii=False),None))
            if command.operation_type in ('split_line','split_faces','line_to_face'):
                for old,new in history_changes:
                    if old is not None or new['lifecycle_status']!='active':continue
                    geometry=shape(new['geometry'])
                    for source,target in history_changes:
                        if source is None:continue
                        original=shape(source['geometry'])
                        if command.operation_type=='line_to_face':matched=source['feature_type']=='line' and geometry.intersects(original);relation='converted_from'
                        else:matched=source['feature_type']==new['feature_type'] and original.covers(geometry);relation='split_from'
                        if matched:connection.execute('INSERT INTO feature_lineage VALUES (?,?,?,?,?,?,?)',(str(uuid4()),source['feature_id'],new['feature_id'],relation,operation_id,json.dumps({key:value for key,value in source.items() if key!='geometry'},ensure_ascii=False),None))
            connection.execute('UPDATE project SET working_revision=?,updated_at=? WHERE project_id=?', (revision, timestamp, project_id))
            return result

    @staticmethod
    def _restore(connection, feature):
        restore_feature(connection,feature)

    @staticmethod
    def _feature(connection, feature_id):
        return load_feature(connection,feature_id)


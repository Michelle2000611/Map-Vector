"""Dependency-ordered compensation preserving stable identities and audit history."""
import json
from shapely import from_wkb,to_wkb
from shapely.geometry import mapping,shape

from mapvector.domain.errors import CommandConflict
from mapvector.application.ports import load_feature,restore_feature,update_index
from mapvector.application.relations import restore_relation,roi_state


def decode_state(change,side):
    value=json.loads(change[side+'_state']) if change[side+'_state'] else None
    if value is None:return None
    if change['entity_type']=='feature':
        attrs=value.pop('attributes',{})
        value.update(attrs)
    geometry=change[side+'_geometry_wkb']
    if geometry is not None and 'geometry' not in value:
        value['geometry']=json.loads(json.dumps(mapping(from_wkb(geometry))))
    return value


def current_state(connection,kind,identity):
    if kind=='feature':
        row=connection.execute('SELECT 1 FROM feature WHERE feature_id=?',(identity,)).fetchone()
        return load_feature(connection,identity) if row else None
    if kind=='project':
        row=connection.execute('SELECT * FROM project WHERE project_id=?',(identity,)).fetchone()
    elif kind=='group_member':
        group_id,feature_id=identity.split(':');row=connection.execute('SELECT * FROM group_member WHERE group_id=? AND feature_id=?',(group_id,feature_id)).fetchone()
    elif kind=='layer_setting':
        project_id,asset_id,layer=identity.split(':');row=connection.execute('SELECT * FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type=?',(project_id,asset_id,layer)).fetchone()
    else:
        key={'style':'style_id','logical_group':'group_id','roi':'roi_id','feature_lineage':'relation_id','feature_style':'feature_id'}.get(kind)
        if key is None:raise CommandConflict('HISTORY_ENTITY_UNSUPPORTED',{'entity_type':kind})
        row=connection.execute('SELECT * FROM '+kind+' WHERE '+key+'=?',(identity,)).fetchone()
    return roi_state(row) if row and kind=='roi' else dict(row) if row else None


def apply_history(connection,project_id,command,timestamp):
    target=connection.execute('SELECT * FROM operation WHERE operation_id=? AND project_id=?',(command.target_operation_id,project_id)).fetchone()
    if target is None or target['operation_type'] in ('undo','redo'):raise CommandConflict('HISTORY_TARGET_INVALID')
    undo=command.operation_type=='undo'
    if target['operation_status']!=('applied' if undo else 'undone'):raise CommandConflict('HISTORY_TARGET_INVALID')
    expected=connection.execute("SELECT operation_id FROM operation WHERE project_id=? AND operation_type NOT IN ('undo','redo') AND operation_status=? ORDER BY result_revision "+('DESC' if undo else 'ASC')+' LIMIT 1',(project_id,'applied' if undo else 'undone')).fetchone()
    if expected is None or expected[0]!=target['operation_id']:raise CommandConflict('HISTORY_ORDER_INVALID')
    changes=connection.execute('SELECT * FROM operation_change WHERE operation_id=? ORDER BY rowid',(target['operation_id'],)).fetchall()
    plans=[]
    for change in changes:
        state=decode_state(change,'before' if undo else 'after')
        previous=current_state(connection,change['entity_type'],change['entity_id'])
        if state and state.get('project_id',project_id)!=project_id:raise CommandConflict('HISTORY_SCOPE_INVALID')
        if change['entity_type']=='feature' and previous and previous['project_id']!=project_id:raise CommandConflict('HISTORY_SCOPE_INVALID')
        plans.append((change['entity_type'],change['entity_id'],previous,state))
    priority={'group_member':0,'feature_style':0,'layer_setting':1,'feature_lineage':2,'roi':3,'feature':4,'logical_group':5,'style':6,'project':7}
    # Remove dependency edges before restoring resources. Do not destroy feature or history identities.
    for kind,identity,old,state in plans:
        if kind=='group_member':restore_relation(connection,kind,identity,None)
        if kind=='feature_style':restore_relation(connection,kind,identity,None)
        if kind=='layer_setting':restore_relation(connection,kind,identity,None)
    for kind,identity,old,state in sorted(plans,key=lambda item:{'style':0,'logical_group':1,'feature':2,'roi':3,'project':4,'feature_lineage':5,'layer_setting':6,'group_member':7,'feature_style':7}.get(item[0],99)):
        if state is None:continue
        state=dict(state)
        if 'revision' in state:state['revision']=command.base_revision+1
        if 'updated_at' in state:state['updated_at']=timestamp
        if kind=='feature':
            restore_feature(connection,state);update_index(connection,identity)
        elif kind=='project':
            connection.execute('UPDATE project SET current_asset_id=?,current_snapshot_id=?,updated_at=? WHERE project_id=?',(state.get('current_asset_id'),state.get('current_snapshot_id'),timestamp,project_id))
        elif kind=='feature_lineage':
            fields=list(state);connection.execute('INSERT INTO feature_lineage ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+') ON CONFLICT(relation_id) DO NOTHING',tuple(state.values()))
        else:restore_relation(connection,kind,identity,state)
    for kind,identity,old,state in sorted(plans,key=lambda item:priority.get(item[0],99)):
        if state is not None:continue
        if kind=='feature':
            connection.execute("UPDATE feature SET lifecycle_status='deleted',revision=?,updated_at=? WHERE feature_id=? AND project_id=?",(command.base_revision+1,timestamp,identity,project_id));update_index(connection,identity)
        elif kind=='project':raise CommandConflict('HISTORY_PROJECT_DELETION_INVALID')
        elif kind=='feature_lineage':
            # Lineage is immutable evidence. Its operation's derived status tells whether it is applied.
            continue
        else:restore_relation(connection,kind,identity,None)
    complete_residue=target['operation_type']=='cleanup_text_residue' and json.loads(target['result_summary']).get('review_summary',{}).get('residue_cleanup',{}).get('complete')
    if target['operation_type'] not in ('repair_face_geometry','apply_line_check') and not complete_residue:synchronize_candidates(connection,project_id)
    connection.execute('UPDATE operation SET operation_status=? WHERE operation_id=?',('undone' if undo else 'applied',target['operation_id']))
    feature_changes=[];relation_changes=[];upserts=[];removed=[];groups=[];styles=[];layers=[];roi=None
    for kind,identity,old,state in plans:
        new=current_state(connection,kind,identity)
        if kind=='feature':
            feature_changes.append((old,new))
            if new and new['lifecycle_status'] in ('active','isolated'):upserts.append(new)
            else:removed.append(identity)
        else:
            relation_changes.append((kind,identity,old,new))
            if kind=='logical_group':
                groups=[group for group in groups if group['group_id']!=identity]
                groups.append(new or {'group_id':identity,'removed':True})
            if kind=='group_member':
                group_id=identity.split(':')[0]
                if not any(group['group_id']==group_id for group in groups):
                    group=current_state(connection,'logical_group',group_id)
                    if group:groups.append(group)
            if kind=='style':styles.append(new or {'style_id':identity,'removed':True})
            if kind=='layer_setting':layers.append(new or {'entity_id':identity,'removed':True})
            if kind=='roi':roi=new
    return feature_changes,relation_changes,upserts,removed,groups,styles,layers,roi


def synchronize_candidates(connection,project_id):
    connection.execute("UPDATE ocr_candidate SET text_feature_id=NULL,candidate_status='unreviewed' WHERE project_id=? AND candidate_status='adopted'",(project_id,))
    rows=connection.execute("SELECT t.feature_id,t.primary_candidate_id,f.asset_id FROM text_attribute t JOIN feature f USING(feature_id) WHERE f.project_id=? AND f.lifecycle_status='active' AND t.primary_candidate_id IS NOT NULL",(project_id,)).fetchall()
    for row in rows:
        candidate=connection.execute('SELECT project_id,asset_id FROM ocr_candidate WHERE candidate_id=?',(row['primary_candidate_id'],)).fetchone()
        if candidate is None or candidate['project_id']!=project_id or candidate['asset_id']!=row['asset_id']:raise CommandConflict('OCR_CANDIDATE_LINK_INVALID')
        connection.execute("UPDATE ocr_candidate SET text_feature_id=?,candidate_status='adopted' WHERE candidate_id=? AND project_id=?",(row['feature_id'],row['primary_candidate_id'],project_id))

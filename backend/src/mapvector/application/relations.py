import json
from uuid import uuid4
from shapely.geometry import box,mapping,shape
from shapely import to_wkb,from_wkb

from mapvector.domain.commands import SetRoi,GroupFeatures,UngroupFeatures


def apply_relations(connection,project_id,command,revision):
    from mapvector.application.commands import CommandConflict
    changes=[];groups=[];roi=None
    if isinstance(command,SetRoi):
        asset=connection.execute('SELECT width_px,height_px FROM asset WHERE asset_id=?',(command.asset_id,)).fetchone()
        row=connection.execute('SELECT * FROM roi WHERE asset_id=? AND project_id=?',(command.asset_id,project_id)).fetchone()
        old=roi_state(row) if row else None
        if command.bounds_px is None:
            if row:connection.execute('DELETE FROM roi WHERE roi_id=?',(row['roi_id'],))
            if old:changes.append(('roi',old['roi_id'],old,None))
        else:
            x0,y0,x1,y1=command.bounds_px
            if not (0<=x0<x1<=asset['width_px'] and 0<=y0<y1<=asset['height_px']):
                raise CommandConflict('EXPORT_SCOPE_INVALID')
            roi_id=row['roi_id'] if row else str(uuid4())
            roi={'roi_id':roi_id,'project_id':project_id,'asset_id':command.asset_id,'geometry':json.loads(json.dumps(mapping(box(x0,y0,x1,y1)))),'revision':revision}
            connection.execute('INSERT INTO roi VALUES (?,?,?,?,?) ON CONFLICT(roi_id) DO UPDATE SET geometry_wkb=excluded.geometry_wkb,revision=excluded.revision',(roi_id,project_id,command.asset_id,to_wkb(box(x0,y0,x1,y1)),revision))
            changes.append(('roi',roi_id,old,roi))
    else:
        features=[]
        for feature_id in dict.fromkeys(command.feature_ids):
            row=connection.execute("SELECT feature_type FROM feature WHERE feature_id=? AND project_id=? AND asset_id=? AND lifecycle_status='active'",(feature_id,project_id,command.asset_id)).fetchone()
            if row is None:raise CommandConflict('RESOURCE_NOT_FOUND')
            features.append((feature_id,row['feature_type']))
        kinds={kind for _,kind in features}
        if len(kinds)!=1 or not kinds<={'face','line'}:raise CommandConflict('GROUP_TYPE_INVALID')
        for feature_id,_ in features:
            for row in connection.execute('SELECT * FROM group_member WHERE feature_id=?',(feature_id,)).fetchall():
                old=dict(row);changes.append(('group_member',row['group_id']+':'+feature_id,old,None))
            connection.execute('DELETE FROM group_member WHERE feature_id=?',(feature_id,))
        if isinstance(command,GroupFeatures):
            if next(iter(kinds))=='face' and len(features)<2:
                raise CommandConflict('GROUP_SIZE_INVALID')
            group_id=str(uuid4());group={'group_id':group_id,'project_id':project_id,'asset_id':command.asset_id,'feature_type':next(iter(kinds)),'group_name':command.group_name,'revision':revision}
            connection.execute('INSERT INTO logical_group VALUES (?,?,?,?,?,?)',tuple(group.values()))
            changes.append(('logical_group',group_id,None,group));groups.append(group)
            for feature_id,_ in features:
                member={'group_id':group_id,'feature_id':feature_id}
                connection.execute('INSERT INTO group_member VALUES (?,?)',(group_id,feature_id))
                changes.append(('group_member',group_id+':'+feature_id,None,member))
    return changes,groups,roi


def roi_state(row):
    result=dict(row);result['geometry']=json.loads(json.dumps(mapping(from_wkb(result.pop('geometry_wkb')))))
    return result


def restore_relation(connection,kind,entity_id,state):
    if kind=='style':
        if state is None:
            connection.execute('DELETE FROM style WHERE style_id=?',(entity_id,))
        else:
            fields=list(state)
            connection.execute('INSERT INTO style ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+') ON CONFLICT(style_id) DO UPDATE SET '+','.join(field+'=excluded.'+field for field in fields if field!='style_id'),tuple(state.values()))
    elif kind=='layer_setting':
        project_id,asset_id,layer_type=entity_id.split(':')
        connection.execute('DELETE FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type=?',(project_id,asset_id,layer_type))
        if state:connection.execute('INSERT INTO layer_setting VALUES (?,?,?,?,?,?)',tuple(state[key] for key in ('project_id','asset_id','layer_type','is_visible','opacity','default_style_id')))
    elif kind=='roi':
        connection.execute('DELETE FROM roi WHERE roi_id=?',(entity_id,))
        if state:connection.execute('INSERT INTO roi VALUES (?,?,?,?,?)',(state['roi_id'],state['project_id'],state['asset_id'],to_wkb(shape(state['geometry'])),state['revision']))
    elif kind=='logical_group':
        if state:connection.execute('INSERT INTO logical_group VALUES (?,?,?,?,?,?) ON CONFLICT(group_id) DO UPDATE SET group_name=excluded.group_name,revision=excluded.revision',tuple(state[field] for field in ('group_id','project_id','asset_id','feature_type','group_name','revision')))
        else:connection.execute('DELETE FROM logical_group WHERE group_id=?',(entity_id,))
    elif kind=='group_member':
        group_id,feature_id=entity_id.split(':')
        connection.execute('DELETE FROM group_member WHERE group_id=? AND feature_id=?',(group_id,feature_id))
        if state:connection.execute('INSERT INTO group_member VALUES (?,?)',(state['group_id'],state['feature_id']))
    elif kind=='feature_style':
        connection.execute('DELETE FROM feature_style WHERE feature_id=?',(entity_id,))
        if state:connection.execute('INSERT INTO feature_style VALUES (?,?)',(state['feature_id'],state['style_id']))
    else:raise ValueError('Unknown relation type')

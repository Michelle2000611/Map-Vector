import json
from uuid import uuid4

from mapvector.domain.commands import SetStyle,BindStyle,SetLayer,DeleteStyle,RebindStyle,ClearStyleOverride
from mapvector.application.ports import load_feature,restore_feature

FEATURE_KEYS={'face':('fill_color',),'line':('stroke_color','stroke_width_px','line_pattern')}


def apply_legend(value,style):
    override=value.get('style_override') or {}
    for key in FEATURE_KEYS[value['feature_type']]:value[key]=override.get(key,style[key])
    return value


def apply_appearance(connection,project_id,command,revision,timestamp):
    from mapvector.application.commands import CommandConflict
    changes=[];features=[];styles=[];layers=[]
    if isinstance(command,DeleteStyle):
        row=connection.execute('SELECT * FROM style WHERE style_id=? AND project_id=?',(command.style_id,project_id)).fetchone()
        if row is None:raise CommandConflict('RESOURCE_NOT_FOUND')
        for item in connection.execute('SELECT feature_id FROM feature WHERE project_id=? AND style_id=?',(project_id,command.style_id)).fetchall():
            before=load_feature(connection,item[0])
            after={**before,'style_id':None,'style_override':None,'revision':revision,'updated_at':timestamp}
            restore_feature(connection,after);features.append((before,after))
        for item in connection.execute('SELECT * FROM feature_style WHERE style_id=?',(command.style_id,)).fetchall():
            changes.append(('feature_style',item['feature_id'],dict(item),None))
        connection.execute('DELETE FROM feature_style WHERE style_id=?',(command.style_id,))
        for item in connection.execute('SELECT * FROM layer_setting WHERE project_id=? AND default_style_id=?',(project_id,command.style_id)).fetchall():
            before=dict(item);after={**before,'default_style_id':None}
            connection.execute('UPDATE layer_setting SET default_style_id=NULL WHERE project_id=? AND asset_id=? AND layer_type=?',(project_id,item['asset_id'],item['layer_type']))
            changes.append(('layer_setting',project_id+':'+item['asset_id']+':'+item['layer_type'],before,after));layers.append(after)
        old=dict(row)
        connection.execute('DELETE FROM style WHERE style_id=?',(command.style_id,))
        changes.append(('style',command.style_id,old,None))
    elif isinstance(command,RebindStyle):
        source=connection.execute('SELECT * FROM style WHERE style_id=? AND project_id=?',(command.from_style_id,project_id)).fetchone()
        target=connection.execute('SELECT * FROM style WHERE style_id=? AND project_id=?',(command.to_style_id,project_id)).fetchone()
        if source is None or target is None:raise CommandConflict('RESOURCE_NOT_FOUND')
        if source['feature_type']!=command.feature_type or target['feature_type']!=command.feature_type:raise CommandConflict('STYLE_TYPE_MISMATCH')
        for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND style_id=? AND lifecycle_status IN ('active','isolated')",(project_id,command.from_style_id)).fetchall():
            old=load_feature(connection,row[0])
            value={**old,'style_id':command.to_style_id,'revision':revision,'updated_at':timestamp}
            apply_legend(value,target)
            restore_feature(connection,value);features.append((old,value))
    elif isinstance(command,SetStyle):
        identifier=command.style_id or str(uuid4())
        row=connection.execute('SELECT * FROM style WHERE style_id=?',(identifier,)).fetchone()
        if row and row['project_id']!=project_id:raise CommandConflict('RESOURCE_NOT_FOUND')
        old=dict(row) if row else None
        if command.feature_type=='face' and command.fill_color is None:raise CommandConflict('STYLE_INVALID')
        if command.feature_type=='line':
            if command.stroke_color is None or command.stroke_width_px is None or command.line_pattern is None:raise CommandConflict('STYLE_INVALID')
            if command.line_pattern=='dashed' and (len(command.dash_pattern_px)<2 or any(value<=0 for value in command.dash_pattern_px)):raise CommandConflict('STYLE_INVALID')
            if command.line_pattern=='teeth' and None in (command.tooth_height_px,command.tooth_spacing_px,command.tooth_side):raise CommandConflict('STYLE_INVALID')
        value={'style_id':identifier,'project_id':project_id,'feature_type':command.feature_type,'style_name':command.style_name,'fill_color':command.fill_color,'stroke_color':command.stroke_color,'stroke_width_px':command.stroke_width_px,'line_pattern':command.line_pattern,'dash_pattern_px':json.dumps(command.dash_pattern_px),'tooth_spacing_px':command.tooth_spacing_px,'tooth_height_px':command.tooth_height_px,'tooth_side':command.tooth_side,'revision':revision}
        if row and row['feature_type']!=command.feature_type:raise CommandConflict('STYLE_TYPE_MISMATCH')
        fields=list(value)
        connection.execute('INSERT INTO style VALUES ('+','.join('?' for _ in fields)+') ON CONFLICT(style_id) DO UPDATE SET '+','.join(field+'=excluded.'+field for field in fields if field!='style_id'),tuple(value.values()))
        changes.append(('style',identifier,old,value));styles.append(value)
        for row in connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND style_id=? AND lifecycle_status IN ('active','isolated')",(project_id,identifier)).fetchall():
            before=load_feature(connection,row[0]);after={**before,'revision':revision,'updated_at':timestamp}
            apply_legend(after,value)
            restore_feature(connection,after);features.append((before,after))
    elif isinstance(command,BindStyle):
        row=connection.execute('SELECT * FROM style WHERE style_id=? AND project_id=?',(command.style_id,project_id)).fetchone()
        if row is None:raise CommandConflict('RESOURCE_NOT_FOUND')
        for feature_id in dict.fromkeys(command.feature_ids):
            old=load_feature(connection,feature_id)
            if old['project_id']!=project_id or old['asset_id']!=command.asset_id or old['feature_type']!=row['feature_type']:raise CommandConflict('STYLE_TYPE_MISMATCH')
            value={**old,'style_id':command.style_id,'style_override':None,'revision':revision,'updated_at':timestamp}
            apply_legend(value,row)
            restore_feature(connection,value);features.append((old,value))
    elif isinstance(command,ClearStyleOverride):
        for feature_id in dict.fromkeys(command.feature_ids):
            old=load_feature(connection,feature_id)
            if old['project_id']!=project_id or old['asset_id']!=command.asset_id or old['feature_type'] not in FEATURE_KEYS:raise CommandConflict('STYLE_TYPE_MISMATCH')
            if not old.get('style_id'):raise CommandConflict('STYLE_NOT_BOUND')
            if not old.get('style_override'):continue
            row=connection.execute('SELECT * FROM style WHERE style_id=? AND project_id=?',(old['style_id'],project_id)).fetchone()
            value={**old,'style_override':None,'revision':revision,'updated_at':timestamp}
            apply_legend(value,row)
            restore_feature(connection,value);features.append((old,value))
    else:
        if command.default_style_id:
            row=connection.execute('SELECT * FROM style WHERE project_id=? AND style_id=?',(project_id,command.default_style_id)).fetchone()
            if row is None or row['feature_type']!=('line' if command.layer_type=='isolated_line' else command.layer_type):raise CommandConflict('STYLE_TYPE_MISMATCH')
        row=connection.execute('SELECT * FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type=?',(project_id,command.asset_id,command.layer_type)).fetchone()
        old=dict(row) if row else None
        value={'project_id':project_id,'asset_id':command.asset_id,'layer_type':command.layer_type,'is_visible':int(command.is_visible),'opacity':command.opacity,'default_style_id':command.default_style_id}
        connection.execute('INSERT INTO layer_setting VALUES (?,?,?,?,?,?) ON CONFLICT(project_id,asset_id,layer_type) DO UPDATE SET is_visible=excluded.is_visible,opacity=excluded.opacity,default_style_id=excluded.default_style_id',tuple(value.values()))
        changes.append(('layer_setting',project_id+':'+command.asset_id+':'+command.layer_type,old,value));layers.append(value)
    return changes,features,styles,layers

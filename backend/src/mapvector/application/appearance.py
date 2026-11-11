import json
from uuid import uuid4

from mapvector.domain.commands import SetStyle,BindStyle,SetLayer
from mapvector.application.ports import load_feature,restore_feature


def apply_appearance(connection,project_id,command,revision,timestamp):
    from mapvector.application.commands import CommandConflict
    changes=[];features=[];styles=[];layers=[]
    if isinstance(command,SetStyle):
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
            if command.feature_type=='face':after['fill_color']=command.fill_color
            else:after.update(stroke_color=command.stroke_color,stroke_width_px=command.stroke_width_px,line_pattern=command.line_pattern)
            restore_feature(connection,after);features.append((before,after))
    elif isinstance(command,BindStyle):
        row=connection.execute('SELECT * FROM style WHERE style_id=? AND project_id=?',(command.style_id,project_id)).fetchone()
        if row is None:raise CommandConflict('RESOURCE_NOT_FOUND')
        for feature_id in dict.fromkeys(command.feature_ids):
            old=load_feature(connection,feature_id)
            if old['project_id']!=project_id or old['asset_id']!=command.asset_id or old['feature_type']!=row['feature_type']:raise CommandConflict('STYLE_TYPE_MISMATCH')
            value={**old,'style_id':command.style_id,'revision':revision,'updated_at':timestamp}
            # Preserve baseline apply-legend attribute changes; they are in the same command/history.
            if row['feature_type']=='face':value['fill_color']=row['fill_color']
            else:value.update(stroke_color=row['stroke_color'],stroke_width_px=row['stroke_width_px'],line_pattern=row['line_pattern'])
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

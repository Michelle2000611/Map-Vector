"""Render data projected from a frozen cleanup plan; never recomputes authority."""
import json
from shapely.geometry import box,shape


def cleanup_scene(connection,features,changes,bounds,project_id,split_sources=None):
    effective={item['feature_id']:item for item in features}
    for _,after in changes:effective[after['feature_id']]=after
    region=box(*bounds)
    visible=[]
    for item in effective.values():
        if item['lifecycle_status']!='active':continue
        if item['feature_type']=='text' and item.get('display_bbox_px'):
            geometry=box(*item['display_bbox_px'])
        else:geometry=shape(item['geometry'])
        if geometry.intersects(region):visible.append(item)
    visible.sort(key=lambda item:(dict(face=0,line=1,text=2)[item['feature_type']],item.get('draw_order',0),item['feature_id']))
    # Resolve bindings and layer defaults exactly as the editing canvas does.
    for index,item in enumerate(visible):
        binding=connection.execute('SELECT style_id FROM feature_style WHERE feature_id=?',((split_sources or {}).get(item['feature_id'],item['feature_id']),)).fetchone()
        layer=connection.execute('SELECT default_style_id FROM layer_setting WHERE project_id=? AND asset_id=? AND layer_type=?',(project_id,item['asset_id'],item['feature_type'])).fetchone()
        style_id=binding[0] if binding else item.get('style_id') or (layer[0] if layer else None)
        if style_id!=item.get('style_id'):visible[index]={**item,'style_id':style_id}
    style_ids={item.get('style_id') for item in visible}-{None}
    styles=[]
    for row in connection.execute('SELECT * FROM style WHERE project_id=? ORDER BY style_id',(project_id,)):
        if row['style_id'] not in style_ids:continue
        value=dict(row);value['dash_pattern_px']=json.loads(value['dash_pattern_px']);styles.append(value)
    return {'features':visible,'styles':styles,'has_changes':bool(changes)}

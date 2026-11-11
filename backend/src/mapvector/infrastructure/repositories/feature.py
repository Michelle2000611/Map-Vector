"""Typed WKB/attribute persistence and complete API feature representations."""
import json
from shapely import from_wkb,to_wkb
from shapely.geometry import mapping,shape

TABLES={'face':'face_attribute','line':'line_attribute','text':'text_attribute'}
JSON_FIELDS={'review_reason_codes','display_bbox_px','rule_suggestions','detected_quad_px','layout_runs'}


def load_feature(connection,feature_id):
    row=connection.execute('SELECT * FROM feature WHERE feature_id=?',(feature_id,)).fetchone()
    if row is None:
        raise KeyError(feature_id)
    feature=dict(row)
    geometry=from_wkb(feature.pop('geometry_wkb'))
    feature['geometry']=json.loads(json.dumps(mapping(geometry)))
    attributes=connection.execute('SELECT * FROM '+TABLES[feature['feature_type']]+' WHERE feature_id=?',(feature_id,)).fetchone()
    if attributes is None:
        raise ValueError('Feature has no matching attribute record: '+feature_id)
    feature.update(dict(attributes))
    for field in JSON_FIELDS:
        if field in feature and feature[field] is not None:
            feature[field]=json.loads(feature[field])
    if feature['feature_type']=='text':
        for key,value in {'layout_width_px':None,'layout_height_px':None,'baseline_offset_px':None,'layout_basis':'legacy_estimate','layout_runs':[]}.items():feature.setdefault(key,value)
    return feature


def restore_feature(connection,feature):
    fields=[row['name'] for row in connection.execute('PRAGMA table_info(feature)')]
    geometry=shape(feature['geometry'])
    data={**feature,'geometry_wkb':to_wkb(geometry)}
    insert='INSERT INTO feature ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+') ON CONFLICT(feature_id) DO UPDATE SET '+','.join(field+'=excluded.'+field for field in fields if field!='feature_id')
    connection.execute(insert,tuple(data[field] for field in fields))
    table=TABLES[feature['feature_type']]
    if feature['feature_type']=='text':feature={**{'layout_width_px':None,'layout_height_px':None,'baseline_offset_px':None,'layout_basis':'legacy_estimate','layout_runs':[]},**feature}
    fields=[row['name'] for row in connection.execute('PRAGMA table_info('+table+')')]
    data={key:json.dumps(value,ensure_ascii=False) if key in JSON_FIELDS and value is not None and not isinstance(value,str) else value for key,value in feature.items()}
    insert='INSERT INTO '+table+' ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+') ON CONFLICT(feature_id) DO UPDATE SET '+','.join(field+'=excluded.'+field for field in fields if field!='feature_id')
    connection.execute(insert,tuple(data[field] for field in fields))


def spatial_id(connection,feature_id):
    return connection.execute('SELECT rowid FROM feature WHERE feature_id=?',(feature_id,)).fetchone()[0]


def update_index(connection,feature_id):
    feature=load_feature(connection,feature_id)
    identifier=spatial_id(connection,feature_id)
    connection.execute('DELETE FROM feature_index WHERE id=?',(identifier,))
    connection.execute('DELETE FROM text_display_index WHERE id=?',(identifier,))
    if feature['lifecycle_status'] in ('active','isolated'):
        bounds=shape(feature['geometry']).bounds
        connection.execute('INSERT INTO feature_index VALUES (?,?,?,?,?)',(identifier,bounds[0],bounds[2],bounds[1],bounds[3]))
        if feature['feature_type']=='text' and feature['display_bbox_px']:
            bounds=feature['display_bbox_px']
            connection.execute('INSERT INTO text_display_index VALUES (?,?,?,?,?)',(identifier,bounds[0],bounds[2],bounds[1],bounds[3]))

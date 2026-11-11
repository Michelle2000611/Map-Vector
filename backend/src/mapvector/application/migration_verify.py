"""Reconcile a migrated database with frozen source geometry and attribute evidence."""
import json
from mapvector.domain.ports import get_ports
from contextlib import closing

import geopandas as gpd
from shapely import normalize,to_wkb,from_wkb

from mapvector.application.ports import sha256_file
from mapvector.application.ports import load_feature


def verify_import(project_dir):
    from mapvector.application.migration import clean
    project_dir=project_dir.resolve();report=json.loads((project_dir/'migration/report.json').read_text(encoding='utf-8'))
    evidence=project_dir/'migration/evidence/source_vectors.gpkg';manifest=json.loads((project_dir/'migration/evidence_manifest.json').read_text(encoding='utf-8'))
    if sha256_file(evidence)!=manifest['vectors_sha256']:raise ValueError('Frozen source vectors hash mismatch')
    with get_ports().archives.open(project_dir/'state/project.sqlite') as connection:
        integrity=connection.execute('PRAGMA integrity_check').fetchone()[0];foreign=[list(row) for row in connection.execute('PRAGMA foreign_key_check')]
        mappings=[dict(row) for row in connection.execute('SELECT * FROM migration_id_map WHERE import_id=?',(report['import_id'],))]
        layers={name:gpd.read_file(evidence,layer=name,engine='pyogrio') for name in {row['legacy_layer_name'] for row in mappings}}
        source_maps={}
        for name,frame in layers.items():
            source_maps[name]={}
            for position,(_,row) in enumerate(frame.iterrows()):
                attrs=row.drop(labels=['geometry']).to_dict();key=str(attrs.get('_eid',attrs.get('line_id',attrs.get('label_id',position))))
                source_maps[name][key]=(row.geometry,clean(attrs))
        mismatches=[];attribute_mismatches=[];checked=0
        for item in mappings:
            row=connection.execute('SELECT geometry_wkb,source_type FROM feature WHERE feature_id=?',(item['feature_id'],)).fetchone()
            if row is None:mismatches.append({'feature_id':item['feature_id'],'reason':'missing'});continue
            # A current object may be edited after migration; compare the immutable imported baseline only.
            modified=connection.execute("SELECT 1 FROM operation_change WHERE entity_type='feature' AND entity_id=? LIMIT 1",(item['feature_id'],)).fetchone()
            if modified:continue
            original,attributes=source_maps[item['legacy_layer_name']][item['legacy_object_key']]
            if to_wkb(normalize(original))!=to_wkb(normalize(from_wkb(row['geometry_wkb']))):mismatches.append({'feature_id':item['feature_id'],'reason':'geometry'})
            if json.loads(item['legacy_attributes'])!=attributes:attribute_mismatches.append({'feature_id':item['feature_id'],'field':'legacy_attributes'})
            feature=load_feature(connection,item['feature_id'])
            fields={'face':{'fill_color':'rgb','algorithm_label':'label','color_class_id':'colour_class','observed_area_px2':'observed_px','inferred_area_px2':'inferred_px'},'line':{'stroke_color':'rgb','stroke_width_px':'width_px'},'text':{'text_value':'text','font_size_px':'font_px'}}[feature['feature_type']]
            for current,legacy in fields.items():
                expected=attributes.get(legacy)
                if expected is None:continue
                actual=feature[current]
                if current in ('algorithm_label','color_class_id'):expected=str(expected)
                if current=='text_value':expected=str(expected).strip()
                if actual!=expected:attribute_mismatches.append({'feature_id':item['feature_id'],'field':current,'expected':expected,'actual':actual})
            checked+=1
        counts=dict(connection.execute('SELECT feature_type,count(*) FROM feature GROUP BY feature_type'))
    result={'integrity_check':integrity,'foreign_key_check':foreign,'mapped_feature_count':len(mappings),'unchanged_geometry_checked':checked,'geometry_mismatches':mismatches,'attribute_mismatches':attribute_mismatches,'feature_counts':counts,'frozen_vectors_sha256':manifest['vectors_sha256']}
    if integrity!='ok' or foreign or mismatches or attribute_mismatches:raise ValueError('Migration readback failed: '+json.dumps(result))
    return result

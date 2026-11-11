"""GIS writers with explicit coordinate conversion and actual readback validation."""
import json
import sqlite3
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.affinity import affine_transform
from shapely.geometry import shape,mapping
from shapely.ops import transform

from mapvector.infrastructure.storage.files import atomic_json,sha256_file


def map_geometry(geometry,asset,wgs84=False):
    if asset['coordinate_mode']=='pixel':
        if wgs84:raise ValueError('GeoJSON requires georeferencing')
        return geometry
    affine=asset['pixel_to_map_affine']
    affine=json.loads(affine) if isinstance(affine,str) else affine
    a,b,c,d,e,f=affine
    result=affine_transform(geometry,[a,b,d,e,c,f])
    if wgs84:
        from pyproj import Transformer
        converter=Transformer.from_crs(asset['crs_wkt'],'EPSG:4326',always_xy=True)
        result=transform(converter.transform,result)
    return result


def clean_properties(feature):
    return {key:json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True) if isinstance(value,(dict,list)) else value for key,value in feature.items() if key!='geometry'}


def validate_rows(frame,expected,tolerance=1e-8,exact_text=False):
    if len(frame)!=len(expected):raise ValueError('GIS readback feature count mismatch')
    by_id={str(row['feature_id']):row for _,row in frame.iterrows()}
    for identity,geometry,properties in expected:
        if identity not in by_id:raise ValueError('GIS readback identity missing: '+identity)
        row=by_id[identity]
        if not row.geometry.equals_exact(geometry,tolerance) and not row.geometry.equals(geometry):
            raise ValueError('GIS readback geometry mismatch: '+identity)
        for key,value in properties.items():
            actual=row.get(key)
            if value is None:
                if actual is not None and not pd.isna(actual):raise ValueError('GIS null changed: '+key)
            elif exact_text:
                if not isinstance(actual,str) or actual!=value:raise ValueError('GIS attribute changed: '+key)
            elif isinstance(value,(float,int)) and not isinstance(value,bool):
                if pd.isna(actual) or abs(float(actual)-float(value))>max(1e-8,abs(float(value))*1e-12):raise ValueError('GIS numeric value changed: '+key)
            elif key.endswith('_at'):
                if pd.Timestamp(actual)!=pd.Timestamp(value):raise ValueError('GIS timestamp changed: '+key)
            elif str(actual)!=str(value):raise ValueError('GIS attribute changed: '+key)


def dbf_text(value,identity,key,losses):
    """Encode the documented DBF text projection before validating every stored value.

    DBF has byte widths and space padding, so a truncated JSON value may end in a
    padding space. GDAL strips surrounding ASCII spaces on read. Complete typed values live
    in property_manifest.json; the DBF is deliberately a limited text projection.
    """
    original='' if value is None else str(value)
    encoded=original.encode('utf-8')
    text=encoded[:250].decode('utf-8',errors='ignore')
    reasons=[]
    if text!=original:reasons.append('dbf_width')
    trimmed=text.strip(' ')
    if trimmed!=text:reasons.append('dbf_padding')
    if value=='':reasons.append('dbf_empty_null')
    for reason in reasons:
        losses.append({'feature_id':identity,'field':key,'reason':reason,
                       'original_utf8_bytes':len(encoded),'stored_utf8_bytes':len(trimmed.encode('utf-8')),
                       'full_value_in':'property_manifest.json'})
    return trimmed


def write_gis(directory,features,asset,format_name,layer_name):
    """Return the final path only after inspecting written geometries and attributes."""
    directory=Path(directory)
    coordinate_mode='georeferenced' if asset['coordinate_mode']=='georeferenced' else 'pixel'
    if format_name=='geojson':
        output=directory/'vectors.geojson'
        objects=[];expected=[]
        for feature in features:
            geometry=map_geometry(shape(feature['geometry']),asset,wgs84=True)
            properties=clean_properties(feature);expected.append((feature['feature_id'],geometry,properties))
            objects.append({'type':'Feature','id':feature['feature_id'],'geometry':mapping(geometry),'properties':properties})
        atomic_json(output,{'type':'FeatureCollection','features':objects})
        if objects:
            # GDAL converts datetime properties to milliseconds. Validate the actual
            # serialized values directly instead of mistaking that reader coercion for loss.
            document=json.loads(output.read_text('utf-8'))
            original={item['properties']['feature_id']:item['properties'] for item in document['features']}
            if any(original.get(identity)!=properties for identity,_,properties in expected):raise ValueError('GeoJSON properties changed')
            frame=gpd.read_file(output,engine='pyogrio')
            for key in {key for values in original.values() for key in values if key.endswith('_at')}:
                frame[key]=[original[str(identity)].get(key) for identity in frame['feature_id']]
            validate_rows(frame,expected)
        else:
            if json.loads(output.read_text(encoding='utf-8'))['features']!=[]:raise ValueError('Empty GeoJSON readback mismatch')
        return output,{'feature_count':len(objects),'coordinate_space':'WGS84','attributes_match':True,'geometry_match':True,'tolerance':1e-8}
    output=directory/'vectors.gpkg' if format_name=='gpkg' else directory/'vectors.zip'
    schema={};losses=[];layer_reports=[];dbf_types_preserved=True
    if format_name=='shp' and not features:
        from mapvector.domain.errors import CommandConflict
        raise CommandConflict('EXPORT_EMPTY_SHAPEFILE',{'reason':'No objects remain in the requested layers and scope'})
    for name in dict.fromkeys(layer_name(feature) for feature in features):
        selected=[feature for feature in features if layer_name(feature)==name]
        layer_loss_start=len(losses)
        layer_types_preserved=all(value is None or isinstance(value,str) for feature in selected for key,value in feature.items() if key!='geometry') if format_name=='shp' else True
        dbf_types_preserved=dbf_types_preserved and layer_types_preserved
        expected=[];records=[]
        for feature in selected:
            geometry=map_geometry(shape(feature['geometry']),asset)
            properties=clean_properties(feature)
            records.append({**properties,'geometry':geometry});expected.append((feature['feature_id'],geometry,properties))
        frame=gpd.GeoDataFrame(records,geometry='geometry',crs=asset['crs_wkt'] if coordinate_mode=='georeferenced' else None)
        if format_name=='gpkg':
            frame.to_file(output,layer=name,driver='GPKG',engine='pyogrio')
            actual=gpd.read_file(output,layer=name,engine='pyogrio')
            validate_rows(actual,expected)
        elif format_name=='shp':
            folder=directory/'shapefile';folder.mkdir(exist_ok=True)
            path=folder/(name+'.shp')
            fields=sorted(key for key in records[0] if key!='geometry')
            short={key:'f'+str(index).zfill(8) for index,key in enumerate(fields)}
            schema[name]=short
            text_rows=[]
            for record in records:
                values={}
                for key in fields:
                    value=record[key]
                    text=dbf_text(value,record['feature_id'],key,losses)
                    values[short[key]]=text
                text_rows.append({**values,'geometry':record['geometry']})
            short_frame=gpd.GeoDataFrame(text_rows,geometry='geometry',crs=frame.crs)
            short_frame.to_file(path,driver='ESRI Shapefile',engine='pyogrio',encoding='UTF-8')
            actual=gpd.read_file(path,engine='pyogrio').rename(columns={value:key for key,value in short.items()})
            short_expected=[]
            for index,(identity,geometry,properties) in enumerate(expected):
                values={key:text_rows[index][short[key]] or None for key in fields}
                short_expected.append((identity,geometry,values))
            validate_rows(actual,short_expected,exact_text=True)
        else:raise ValueError('Unsupported GIS format')
        layer_reports.append({'layer_type':name,'feature_count':len(selected),'attributes_match':len(losses)==layer_loss_start and layer_types_preserved,'stored_attributes_match':True,'geometry_match':True})
    if format_name=='gpkg':
        if not features:
            # Empty results still have a valid, readable GIS container.
            gpd.GeoDataFrame({'feature_id':pd.Series(dtype='str')},geometry=[],crs=None).to_file(output,layer='feature',driver='GPKG',engine='pyogrio')
        if coordinate_mode=='pixel':
            with sqlite3.connect(output) as connection:connection.execute("UPDATE gpkg_contents SET description='Pixel coordinates; x right, y down; no geographic CRS'")
    else:
        atomic_json(directory/'field_mapping.json',schema)
        atomic_json(directory/'property_manifest.json',features)
        package_manifest={'schema_revision':'1.0','coordinate_space':coordinate_mode,
                          'dbf_encoding':'UTF-8','dbf_max_text_bytes':250,
                          'dbf_attribute_storage':'text; nested values use JSON; empty text reads as null; surrounding ASCII spaces are padding',
                          'dbf_types_preserved':dbf_types_preserved,'losses':losses,
                          'full_properties_file':'property_manifest.json','feature_identity_field':'feature_id',
                          'field_mapping_file':'field_mapping.json',
                          'files':{path.name:sha256_file(path) for path in (directory/'field_mapping.json',directory/'property_manifest.json')}}
        atomic_json(directory/'shapefile_manifest.json',package_manifest)
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((directory/'shapefile').glob('*')) if (directory/'shapefile').exists() else []:archive.write(path,'shapefile/'+path.name)
            for name in ('field_mapping.json','property_manifest.json','shapefile_manifest.json'):archive.write(directory/name,name)
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() is not None:raise ValueError('Shapefile archive corruption')
            # Read the deliverable itself: a successful sidecar write is not proof
            # that the downloadable ZIP contains the complete original values.
            if json.loads(archive.read('property_manifest.json'))!=json.loads(json.dumps(features,ensure_ascii=False,allow_nan=False)):raise ValueError('Shapefile full properties changed')
            if json.loads(archive.read('field_mapping.json'))!=schema:raise ValueError('Shapefile field mapping changed')
            if json.loads(archive.read('shapefile_manifest.json'))!=package_manifest:raise ValueError('Shapefile manifest changed')
            for path in (directory/'shapefile').glob('*'):
                if archive.read('shapefile/'+path.name)!=path.read_bytes():raise ValueError('Shapefile archive member changed: '+path.name)
    return output,{'feature_count':len(features),'coordinate_space':coordinate_mode,'attributes_match':not bool(losses) and dbf_types_preserved,'stored_attributes_match':True,'full_properties_match':True,'dbf_types_preserved':dbf_types_preserved if format_name=='shp' else None,'full_properties_file':'property_manifest.json' if format_name=='shp' else None,'recommended_format':'gpkg' if losses or not dbf_types_preserved else format_name,'geometry_match':True,'layers':layer_reports,'losses':losses,'tolerance':1e-8}

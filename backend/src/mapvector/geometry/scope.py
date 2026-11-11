"""Shared ROI scope used by audits and exporters."""
import copy
import json
from shapely.geometry import shape,mapping
from shapely import from_wkb


def scoped_features(features,mode,roi):
    from mapvector.application.commands import CommandConflict
    if mode=='full':
        if roi is not None:raise CommandConflict('EXPORT_SCOPE_INVALID')
        return copy.deepcopy(features)
    if mode not in ('keep_crossing','clip') or roi is None:
        raise CommandConflict('EXPORT_SCOPE_INVALID')
    region=from_wkb(roi['geometry_wkb']) if 'geometry_wkb' in roi else shape(roi['geometry'])
    result=[]
    for source in features:
        geometry=shape(source['geometry'])
        if not region.intersects(geometry):continue
        if mode=='clip':
            geometry=geometry.intersection(region)
            if geometry.is_empty:continue
            expected={'face':('Polygon','MultiPolygon'),'line':('LineString','MultiLineString'),'text':('Point',)}[source['feature_type']]
            if geometry.geom_type=='GeometryCollection':
                from shapely import union_all
                geometry=union_all([part for part in geometry.geoms if part.geom_type in expected])
            if geometry.is_empty or geometry.geom_type not in expected:continue
        value=copy.deepcopy(source)
        value['geometry']=json.loads(json.dumps(mapping(geometry)))
        value['geometry_type']=geometry.geom_type
        bounds=geometry.bounds
        value.update(bbox_min_x_px=bounds[0],bbox_min_y_px=bounds[1],bbox_max_x_px=bounds[2],bbox_max_y_px=bounds[3])
        if source['feature_type']=='face':value['area_px2']=geometry.area
        elif source['feature_type']=='line':value['length_px']=geometry.length
        result.append(value)
    return result


def audit(features,roi):
    region=from_wkb(roi['geometry_wkb']) if 'geometry_wkb' in roi else shape(roi['geometry'])
    counts={'inside':0,'crossing':0,'outside':0}
    for feature in features:
        geometry=shape(feature['geometry'])
        status='inside' if region.covers(geometry) else 'crossing' if region.intersects(geometry) else 'outside'
        counts[status]+=1
    return counts

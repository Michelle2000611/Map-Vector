"""Read-only reconciliation of an algorithm output against a frozen GPKG."""
import hashlib
import json
from importlib.metadata import version
import geopandas as gpd
from shapely import to_wkb


def compare_vector_layers(baseline,current):
    results={}
    for layer in ('colour_faces','visual_lines'):
        left=gpd.read_file(baseline,layer=layer,engine='pyogrio');right=gpd.read_file(current,layer=layer,engine='pyogrio')
        fields=[name for name in left.columns if name!='geometry']
        def fingerprint(frame):
            hashes=[]
            for _,row in frame.iterrows():
                attrs={key:None if __import__('pandas').isna(row[key]) else row[key].item() if hasattr(row[key],'item') else row[key] for key in fields}
                hashes.append(hashlib.sha256(to_wkb(row.geometry.normalize(),byte_order=1)+json.dumps(attrs,sort_keys=True,ensure_ascii=False,default=str).encode('utf-8')).hexdigest())
            return sorted(hashes)
        exact=fingerprint(left)==fingerprint(right)
        results[layer]={'baseline_count':len(left),'current_count':len(right),'geometry_and_attributes_equal':exact,'baseline_bounds':left.total_bounds.tolist(),'current_bounds':right.total_bounds.tolist(),'baseline_area_or_length':float(left.geometry.area.sum() if layer=='colour_faces' else left.geometry.length.sum()),'current_area_or_length':float(right.geometry.area.sum() if layer=='colour_faces' else right.geometry.length.sum())}
    return {'layers':results,'equivalent':all(item['geometry_and_attributes_equal'] for item in results.values()),'runtime':{name:version(name) for name in ('numpy','pillow','shapely','scipy','scikit-image','geopandas','rasterio','pyogrio')}}

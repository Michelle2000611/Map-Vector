"""Consumer helper: run inside ArcGIS Pro's licensed Python after extraction."""
import argparse,hashlib,json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('--add-to-map',action='store_true');args=parser.parse_args()
    root=args.directory.resolve();data=json.loads((root/'delivery.json').read_text('utf-8'));output=root/data['export_file']
    if hashlib.sha256(output.read_bytes()).hexdigest()!=data['export_sha256']:raise ValueError('Export hash mismatch')
    try:import arcpy
    except ImportError:raise SystemExit('ArcPy unavailable. Run in ArcGIS Pro Python; acceptance has not run.')
    report={'arcgis_version':arcpy.GetInstallInfo(),'snapshot_id':data['snapshot_id'],'datasets':[],'status':'data_checked_visual_pending'}
    if data['format']!='gpkg':raise SystemExit('This verifier requires the recommended GPKG delivery; use GPKG for full field validation.')
    arcpy.env.workspace=str(output)
    datasets=arcpy.ListFeatureClasses() or []
    found=set()
    for name in datasets:
        dataset=str(output/name);fields=[f.name for f in arcpy.ListFields(dataset)];desc=arcpy.Describe(dataset)
        key=name.rsplit('.',1)[-1];expected=set(data['feature_ids_by_layer'].get(key,[]))
        ids={str(r[0]) for r in arcpy.da.SearchCursor(dataset,['feature_id'])}
        if ids!=expected:raise ValueError('Feature identities or counts changed: '+name)
        found.add(key)
        if data['coordinate_space']=='georeferenced':
            expected_sr=arcpy.SpatialReference();expected_sr.loadFromString(data['crs_wkt'])
            if expected_sr.factoryCode and desc.spatialReference.factoryCode!=expected_sr.factoryCode:raise ValueError('CRS changed: '+name)
        item={'name':name,'count':int(arcpy.management.GetCount(dataset)[0]),'fields':fields,'spatial_reference':desc.spatialReference.name,'bounds':[desc.extent.XMin,desc.extent.YMin,desc.extent.XMax,desc.extent.YMax]}
        if 'text_value' in fields:
            read={row[0]:row[1:] for row in arcpy.da.SearchCursor(dataset,['feature_id','text_value','font_size_px','rotation_deg','review_status'])}
            for f in data['text_features']:
                if f['feature_id'] not in expected:continue
                if f['feature_id'] not in read:raise ValueError('Text missing: '+f['feature_id'])
                text,size,angle,status=read[f['feature_id']]
                if text!=f['text_value'] or abs(size-f['font_size_px'])>1e-8 or abs(angle-f['rotation_deg'])>1e-8 or status!=f['review_status']:raise ValueError('Text or typography changed: '+f['feature_id'])
            item['text_fields_checked']=len(read)
        report['datasets'].append(item)
        if args.add_to_map:
            project=arcpy.mp.ArcGISProject('CURRENT');m=project.activeMap or project.listMaps()[0];layer=m.addDataFromPath(dataset)
            if 'text_value' in fields and layer.supports('SHOWLABELS'):
                for label in layer.listLabelClasses():label.expression='$feature.text_value';label.visible=True
                layer.showLabels=True
    if not datasets:raise ValueError('No GPKG feature classes found')
    if found!=set(data['feature_ids_by_layer']):raise ValueError('Missing delivery layers')
    (root/'arcgis_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),'utf-8')
    print('ArcGIS data checks complete. Visual labels, scale, rotation and symbols still require comparison with raster.png.')


if __name__=='__main__':main()

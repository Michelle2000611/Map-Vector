"""Build a traceable GIS exchange package from one committed export and snapshot."""
import io,json,zipfile
from mapvector.application.ports import ProjectDatabase,sha256_file
from mapvector.domain.errors import CommandConflict
from mapvector.configuration.settings import Settings


def delivery_package(directory,project_id,export_id):
    from mapvector.application.commands import CommandService
    from mapvector.application.exports import text_released
    from mapvector.geometry.scope import scoped_features
    with ProjectDatabase(directory/'state/project.sqlite').read() as c:
        row=c.execute("SELECT * FROM export WHERE project_id=? AND export_id=? AND export_status='completed'",(project_id,export_id)).fetchone()
        if row is None:raise CommandConflict('EXPORT_NOT_COMPLETE')
        export=dict(row);snapshot=dict(c.execute('SELECT * FROM snapshot WHERE snapshot_id=?',(row['snapshot_id'],)).fetchone())
    output=Settings.resolve_project_path(directory,export['output_rel_path'])
    if sha256_file(output)!=export['output_sha256']:raise CommandConflict('EXPORT_HASH_MISMATCH')
    frozen=directory/snapshot['snapshot_rel_path'];saved=json.loads((frozen/'manifest.json').read_text('utf-8'))
    if sha256_file(frozen/'manifest.json')!=snapshot['manifest_sha256']:raise CommandConflict('SNAPSHOT_HASH_MISMATCH')
    for name,digest in saved['files'].items():
        if sha256_file(Settings.resolve_project_path(frozen,name))!=digest:raise CommandConflict('SNAPSHOT_HASH_MISMATCH')
    with ProjectDatabase(frozen/'project.sqlite').read() as c:
        asset=dict(c.execute('SELECT * FROM asset WHERE asset_id=?',(snapshot['asset_id'],)).fetchone())
        features=[CommandService._feature(c,r[0]) for r in c.execute("SELECT feature_id FROM feature WHERE asset_id=? AND lifecycle_status IN ('active','isolated')",(asset['asset_id'],))]
        styles=[dict(r) for r in c.execute('SELECT * FROM style')]
        roi=c.execute('SELECT * FROM roi WHERE roi_id=?',(export['roi_id'],)).fetchone() if export['roi_id'] else None
    policy=json.loads(export['policy_snapshot']);layers=json.loads(export['layer_types'])
    features=scoped_features(features,export['scope_mode'],dict(roi) if roi else None)
    def layer(f):return ('text_confirmed' if text_released(f,policy['policy_id']) else 'text_unconfirmed') if f['feature_type']=='text' else 'isolated_line' if f['lifecycle_status']=='isolated' else f['feature_type']
    selected=[f for f in features if layer(f) in layers]
    manifest={'schema_revision':'1.0','project_id':project_id,'snapshot_id':snapshot['snapshot_id'],'working_revision':snapshot['working_revision'],'asset_id':asset['asset_id'],'coordinate_space':asset['coordinate_mode'],'crs_wkt':asset['crs_wkt'],'pixel_to_map_affine':json.loads(asset['pixel_to_map_affine']) if asset['pixel_to_map_affine'] else None,'raster_sha256':asset['raster_sha256'],'export_file':output.name,'export_sha256':export['output_sha256'],'format':export['export_format'],'policy':policy,'layers':layers,'styles':styles,'text_features':[f for f in selected if f['feature_type']=='text'],'line_styles':[{'feature_id':f['feature_id'],'style_id':f['style_id'],'stroke_color':f['stroke_color'],'stroke_width_px':f['stroke_width_px']} for f in selected if f['feature_type']=='line'],'units':{'geometry':'source_pixel' if asset['coordinate_mode']=='pixel' else 'CRS_units (GeoJSON is WGS84 degrees)','font_size_px':'source_pixel','stroke_width_px':'source_pixel','rotation_deg':'degrees_counterclockwise_in_source_image','layout_runs':'source_pixel_offsets'},'arcgis_validation':{'status':'not_run','reason':'Run the included script in a licensed ArcGIS Pro Python environment; GDAL readback is not ArcGIS visual acceptance'}}
    manifest['feature_ids_by_layer']={name:[f['feature_id'] for f in selected if layer(f)==name] for name in {layer(f) for f in selected}}
    readme='''Map-Vector GIS 交付包
推荐使用 GPKG 保存完整字段。Shapefile 长字段截断请同时读取 property_manifest.json 和 field_mapping.json。
delivery.json 记录固定快照、审核政策、字号角度、逐字上下标/竖排、图例和原图仿射。文字是点加属性，不能把导入后未显示标签当文字丢失。
字号、线宽、文字排版偏移都是原图像素，不是地图单位；不能直接填入 ArcGIS 的点值字号。逐字上下标和竖排需根据 layout_runs 创建标注或注记。
在 ArcGIS Pro 自带 Python 中运行：python ArcGIS_验收.py 交付包目录
脚本检查要素数量、CRS、字段并保存 arcgis_acceptance.json。--add-to-map 可在 Pro Notebook 中添加图层和文字标签，但不保证恢复每个对象的图形外观；需人工核对原图、旋转、虚线齿形和上下标。
像素工程未配准，不应伪造地理 CRS；请先提供 World 和 CRS 配准文件。配准工程随包提供 raster.png、raster.pgw 和 raster.prj 以便控制点叠加。
验收时核对控制点、包络、对象数量、中文及特殊字符、审核状态、标签字号角度和线型；未在 ArcGIS 运行前，不标记实机通过。
'''
    from importlib.resources import files
    script=files('mapvector.resources').joinpath('arcgis_acceptance.py').read_text('utf-8')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(output,output.name);z.writestr('delivery.json',json.dumps(manifest,ensure_ascii=False,indent=2));z.writestr('交付说明.txt',readme);z.writestr('ArcGIS_验收.py',script)
        raster=directory/asset['raster_rel_path']
        if sha256_file(raster)!=asset['raster_sha256']:raise CommandConflict('ASSET_RESULT_MISMATCH')
        z.write(raster,'raster.png')
        if manifest['pixel_to_map_affine']:
            a,b,c,d,e,f=manifest['pixel_to_map_affine']
            z.writestr('raster.pgw','\n'.join(map(str,[a,d,b,e,c+(a+b)/2,f+(d+e)/2])))
            z.writestr('raster.prj',asset['crs_wkt'])
    return buffer.getvalue()

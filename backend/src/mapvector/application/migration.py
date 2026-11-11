"""Read-only legacy scan and evidence-gated import into a new project copy."""
import hashlib
import json
import math
import shutil
from mapvector.domain.ports import get_ports
from contextlib import closing
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4,uuid5,NAMESPACE_URL

import geopandas as gpd
import pandas as pd
import pyogrio
from PIL import Image
from shapely.geometry import mapping,Point

from mapvector.application.commands import CommandConflict
from mapvector.application.assets import AssetService
from mapvector.application.ports import ProjectRepository
from mapvector.application.ports import ProjectDatabase
from mapvector.application.ports import restore_feature,update_index
from mapvector.application.ports import sha256_file,atomic_json,atomic_bytes
from mapvector.geometry.text import display_bbox

BASELINE='c7b74d9c9a16d1b082f0dab694cecc8dc45363f9'
LAYERS={'colour_faces':'face','visual_lines':'line','text_labels':'text','text_residue_lines':'line'}


def clean(value):
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if value is None:return None
    if hasattr(value,'item'):
        try:value=value.item()
        except ValueError:pass
    try:
        if pd.isna(value):return None
    except (ValueError,TypeError):pass
    if isinstance(value,(str,int,float,bool)):return value
    return str(value)


def resolve_evidence(source:Path,value):
    if not value:raise ValueError('Evidence path missing')
    path=Path(value)
    return path.resolve() if path.is_absolute() else (source/path).resolve()


def scan(source:Path):
    source=source.resolve();issues=[];files=[]
    for path in sorted(source.rglob('*')):
        if path.is_file() and not any(part.startswith('.venv') for part in path.relative_to(source).parts):
            files.append({'rel_path':path.relative_to(source).as_posix(),'sha256':sha256_file(path),'byte_size':path.stat().st_size})
    report={'legacy_project_id':source.name,'source_files':files,'issues':issues,'layers':[],'import_status':'prepared','mapping_revision':'1.2','baseline_commit':BASELINE}
    fingerprint=json.dumps({'files':files,'mapping_revision':'1.2'},sort_keys=True,separators=(',',':')).encode('utf-8')
    report['source_import_key']=hashlib.sha256(fingerprint).hexdigest()
    try:
        project=json.loads((source/'project.json').read_text(encoding='utf-8'))
        report['legacy_project_id']=project.get('project_id',source.name)
        document_ref=project.get('document') or {}
        document_path=resolve_evidence(source,document_ref.get('path'))
        document=json.loads(document_path.read_text(encoding='utf-8'))
        raster=resolve_evidence(source,document.get('raster_artifact'))
        with Image.open(raster) as image:width,height=image.size
        raster_hash=sha256_file(raster)
        if raster_hash!=document.get('raster_sha256') or (width,height)!=(document.get('width'),document.get('height')):
            issues.append({'code':'ASSET_RESULT_MISMATCH','resource':'raster','actual_dimensions':[width,height],'recorded_dimensions':[document.get('width'),document.get('height')],'actual_sha256':raster_hash,'recorded_sha256':document.get('raster_sha256')})
        working=source/'working/current.gpkg'
        if not working.is_file():raise ValueError('Missing working/current.gpkg')
        # Input identity requires at least one matching run document hash; equal dimensions alone do not prove origin.
        run_evidence=[];copy_claim=False
        working_from=project.get('working_from')
        working_run=(working_from or {}).get('run_id') if isinstance(working_from,dict) else None
        referenced=project.get('runs') or []
        referenced_ids={item.get('run_id') for item in referenced if isinstance(item,dict)}
        if working_run:
            referenced_ids.add(working_run)
        if isinstance(working_from,dict):
            working_run=working_run or working_from.get('source_run')
            if working_run:referenced_ids.add(working_run)
            if working_from.get('kind')=='hash_matched_acceptance_copy' and working_from.get('raster_sha256')==document.get('raster_sha256'):
                copy_claim=True
            if working_from.get('kind')=='fresh_v02_recognition_copy' and working_from.get('source_sha256')==document.get('source_sha256'):
                copy_claim=True
        matched_runs=[]
        for path in source.glob('runs/**/manifest.json'):
            try:
                body=json.loads(path.read_text(encoding='utf-8'))
                if body.get('run_id') not in referenced_ids and referenced_ids:continue
                if body.get('input',{}).get('raster_sha256')==raster_hash:
                    matched_runs.append(path.relative_to(source).as_posix())
            except (ValueError,OSError):continue
        run_evidence.extend(matched_runs)
        if copy_claim and not run_evidence:
            source_project=source.parent/str(working_from.get('source_project',''))
            external=source_project/'runs'/str(working_run)/'manifest.json'
            if external.is_file():
                body=json.loads(external.read_text(encoding='utf-8'))
                if body.get('run_id')==working_run and body.get('input',{}).get('raster_sha256')==raster_hash:
                    run_evidence.append({'evidence':'referenced_source_run','path':str(external),'sha256':sha256_file(external)})
            # An independently frozen rerun can prove a copy whose original run was not retained.
            from mapvector.configuration.settings import Settings
            proof_path=Settings().workspace.parent/'migration_proofs'/(source.name+'.json')
            if not run_evidence and proof_path.is_file():
                proof=json.loads(proof_path.read_text(encoding='utf-8'))
                checks=proof.get('checks') or []
                if proof.get('input_raster_sha256')==raster_hash and proof.get('working_sha256')==sha256_file(working) and proof.get('baseline_commit')==BASELINE and proof.get('equivalent') is True and checks:
                    if all(Path(item['path']).is_file() and sha256_file(Path(item['path']))==item['sha256'] for item in checks):run_evidence.append({'evidence':'frozen_independent_rerun','path':str(proof_path),'sha256':sha256_file(proof_path)})
        if not run_evidence:
            issues.append({'code':'SOURCE_PROVENANCE_UNPROVEN','resource':'working/current.gpkg','reason':'No matching referenced run input hash'})
        for name,_ in pyogrio.list_layers(working):
            frame=gpd.read_file(working,layer=name,engine='pyogrio')
            spatial=hasattr(frame,'geometry') and frame.geometry.name in frame.columns
            bounds=[float(x) for x in frame.total_bounds] if spatial and len(frame) else None
            if name in LAYERS and bounds and (not all(math.isfinite(x) for x in bounds) or bounds[0]<-1e-6 or bounds[1]<-1e-6 or bounds[2]>width+1e-6 or bounds[3]>height+1e-6):
                issues.append({'code':'ASSET_RESULT_MISMATCH','resource':name,'bounds_px':bounds,'asset_dimensions':[width,height]})
            invalid=[str(index) for index,row in frame.iterrows() if row.geometry is None or row.geometry.is_empty or not row.geometry.is_valid] if spatial else []
            if invalid:issues.append({'code':'GEOMETRY_VALIDATION_FAILED','resource':name,'object_keys':invalid})
            report['layers'].append({'legacy_layer_name':str(name),'feature_count':len(frame),'bounds_px':bounds,'columns':list(frame.columns),'recognized':name in LAYERS})
        supported_origins=('run','version','fresh_v02_recognition_copy','hash_matched_acceptance_copy')
        if not working_from or not isinstance(working_from,dict) or working_from.get('kind') not in supported_origins:
            issues.append({'code':'SOURCE_PROVENANCE_UNPROVEN','resource':'working/current.gpkg','reason':'working_from must reference a concrete run or version'})
        elif working_from.get('kind')=='fresh_v02_recognition_copy' and working_from.get('source_sha256') not in (document.get('source_sha256'),document.get('raster_sha256')):
            issues.append({'code':'ASSET_RESULT_MISMATCH','resource':'working_from','reason':'source copy hash does not match source or raster evidence'})
        elif working_from.get('kind')=='hash_matched_acceptance_copy' and working_from.get('raster_sha256')!=document.get('raster_sha256'):
            issues.append({'code':'ASSET_RESULT_MISMATCH','resource':'working_from','reason':'acceptance copy raster hash does not match the normalized raster'})
        report.update(raster_path=str(raster),working_path=str(working),raster_sha256=raster_hash,width_px=width,height_px=height,project_name=project.get('name',source.name),document=document,run_evidence=run_evidence)
    except (ValueError,OSError,KeyError) as exc:issues.append({'code':'MIGRATION_EVIDENCE_MISSING','reason':str(exc)})
    report['import_status']='quarantined' if issues else 'validated'
    return report


def _import_project(source:Path,workspace:Path):
    report=scan(source)
    if report['import_status']!='validated':return report
    for path in workspace.glob('projects/*/state/project.sqlite'):
        try:
            with get_ports().archives.open(path) as connection:
                match=connection.execute("SELECT project_id,report_rel_path FROM migration_import WHERE source_import_key=? AND import_status='committed'",(report['source_import_key'],)).fetchone()
                if match:return {**report,'project_id':match[0],'import_status':'committed','duplicate':True,'report_rel_path':match[1]}
        except get_ports().archives.operational_error:continue
    project=ProjectRepository(workspace).create(report['project_name']);directory=workspace/'projects'/project.project_id
    service=AssetService(directory)
    original=resolve_evidence(source,report['document'].get('source_path') or report['raster_path'])
    original_hash=report['document'].get('source_sha256')
    if original_hash and sha256_file(original)!=original_hash:raise CommandConflict('ASSET_RESULT_MISMATCH',{'resource':'original upload'})
    uploaded=service.upload_source(project.project_id,original.name,original.read_bytes())
    asset=service.normalize_asset(project.project_id,uploaded['source_id'],0,{'dpi':200})
    # Preserve the frozen standardization bytes and georeferencing; decoder upgrades never rewrite old evidence.
    raster_path=directory/asset['raster_rel_path'];atomic_bytes(raster_path,Path(report['raster_path']).read_bytes())
    document=report['document'];mode='georeferenced' if document.get('coordinate_mode')=='GEOREFERENCED' else 'pixel'
    with ProjectDatabase(directory/'state/project.sqlite').transaction() as connection:
        connection.execute('UPDATE asset SET raster_sha256=?,width_px=?,height_px=?,coordinate_mode=?,crs_wkt=?,pixel_to_map_affine=?,page_index=?,normalization_config=? WHERE asset_id=?',(report['raster_sha256'],report['width_px'],report['height_px'],mode,document.get('crs') if mode=='georeferenced' else None,json.dumps(document.get('transform')) if mode=='georeferenced' else None,int(document.get('page_index',0)),json.dumps({'decoder':'frozen_legacy_standardization','legacy_preprocess':document.get('preprocess'),'dpi':(document.get('pdf_render') or {}).get('dpi') or 200}),asset['asset_id']))
    import_id=str(uuid4());gpkg=Path(report['working_path']);gpkg_hash=sha256_file(gpkg);now=datetime.now(timezone.utc).isoformat()
    atomic_json(raster_path.parent/'manifest.json',service.get(project.project_id,asset['asset_id']))
    try:
        with ProjectDatabase(directory/'state/project.sqlite').transaction() as connection:
            connection.execute('INSERT INTO migration_import VALUES (?,?,?,?,?,?,?,?)',(import_id,project.project_id,report['source_import_key'],report['legacy_project_id'],BASELINE,report['mapping_revision'],'prepared','migration/report.json'))
            for layer in report['layers']:
                name=layer['legacy_layer_name']
                if name not in LAYERS:continue
                frame=gpd.read_file(gpkg,layer=name,engine='pyogrio')
                for position,(index,row) in enumerate(frame.iterrows()):
                    attributes=clean(row.drop(labels=['geometry']).to_dict());key=str(attributes.get('_eid',attributes.get('line_id',attributes.get('label_id',position))))
                    feature_id=str(uuid5(NAMESPACE_URL,report['source_import_key']+':'+name+':'+key))
                    geometry=row.geometry;kind=LAYERS[name]
                    if kind=='text' and geometry.geom_type!='Point':raise CommandConflict('GEOMETRY_VALIDATION_FAILED',{'layer':name,'object_key':key})
                    bounds=geometry.bounds
                    feature={'feature_id':feature_id,'project_id':project.project_id,'asset_id':asset['asset_id'],'origin_run_id':None,'feature_type':kind,'geometry_type':geometry.geom_type,'geometry':json.loads(json.dumps(mapping(geometry))),'bbox_min_x_px':bounds[0],'bbox_min_y_px':bounds[1],'bbox_max_x_px':bounds[2],'bbox_max_y_px':bounds[3],'lifecycle_status':'isolated' if name=='text_residue_lines' else 'active','source_type':'legacy_import','style_id':None,'revision':0,'created_at':None,'updated_at':now}
                    if kind=='face':feature.update(fill_color=attributes.get('rgb') or '#808080',algorithm_label=str(attributes['label']) if attributes.get('label') is not None else None,color_class_id=str(attributes['colour_class']) if attributes.get('colour_class') is not None else None,area_px2=geometry.area,observed_area_px2=attributes.get('observed_px'),inferred_area_px2=attributes.get('inferred_px'),coverage_status='unchecked')
                    elif kind=='line':feature.update(stroke_color=attributes.get('rgb') or '#000000',stroke_width_px=float(attributes.get('width_px') or 1),line_pattern='dashed' if attributes.get('kind')=='dash' else 'solid' if attributes.get('kind')=='solid' else 'unknown',line_role=str(attributes.get('line_role') or 'unknown').lower(),length_px=geometry.length,draw_order=int(attributes.get('draw_order') or position),isolation_reason='text_residue' if name=='text_residue_lines' else None,associated_text_feature_id=None)
                    else:
                        text=str(attributes.get('text') or '').strip();size=float(attributes.get('font_px') or 12);angle=(float(attributes.get('angle_deg') or 0)+180)%360-180
                        legacy_status=attributes.get('review_status');status={'HUMAN_EDITED':'manual_edited','AUTO_ACCEPTED_UNVERIFIED':'auto_accepted_unverified','TEXT_LAYER_COMPLETE':'pipeline_complete_unverified','REVIEW_SKIPPED':'skipped'}.get(legacy_status,'required')
                        basis={'manual_edited':'manual_content_edit','auto_accepted_unverified':'automatic_rule','pipeline_complete_unverified':'automatic_rule'}.get(status,'legacy_unknown')
                        feature.update(text_value=text,original_text=attributes.get('ocr_text'),font_size_px=size,rotation_deg=angle,text_color=attributes.get('rgb') or '#000000',text_anchor='center',text_content_revision=0,review_status=status,review_reason_codes=['legacy_evidence_unverified'],reviewed_content_revision=None,reviewed_at=None,reviewer_id=None,cleanup_status='not_checked',display_bbox_px=display_bbox(geometry.x,geometry.y,text,size,angle),primary_candidate_id=None,font_family='sans-serif',review_basis=basis)
                    restore_feature(connection,feature);update_index(connection,feature_id)
                    connection.execute('INSERT INTO migration_id_map VALUES (?,?,?,?,?,?)',(import_id,gpkg_hash,name,key,feature_id,json.dumps(attributes,ensure_ascii=False)))
            from mapvector.application.migration_relation import import_relations
            import_relations(connection,source,directory,project.project_id,asset['asset_id'],import_id,gpkg,gpkg_hash,report,clean)
            connection.execute("UPDATE migration_import SET import_status='committed' WHERE import_id=?",(import_id,))
            report.update(import_status='committed',project_id=project.project_id,import_id=import_id,duplicate=False)
        evidence=directory/'migration/evidence';evidence.mkdir(parents=True)
        shutil.copyfile(gpkg,evidence/'source_vectors.gpkg')
        for index,item in enumerate(report.get('run_evidence',[])):
            if isinstance(item,dict) and item.get('path'):
                proof_path=Path(item['path']);shutil.copyfile(proof_path,evidence/('run_proof_'+str(index)+'.json'))
                if item.get('evidence')=='frozen_independent_rerun':
                    proof=json.loads(proof_path.read_text(encoding='utf-8'));proof_files=[]
                    for check_index,check in enumerate(proof['checks']):
                        original=Path(check['path']);relative='run_proof_'+str(index)+'_'+str(check_index)+original.suffix
                        shutil.copyfile(original,evidence/relative);proof_files.append({'rel_path':relative,'sha256':check['sha256']})
                    atomic_json(evidence/('run_proof_'+str(index)+'_files.json'),proof_files)
        for item in report['source_files']:
            relative=item['rel_path'];path=source/relative
            if relative.startswith(('runs/','versions/','audit/')) or relative.endswith('.json'):
                target=evidence/'legacy'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        atomic_json(directory/'migration/report.json',report)
        atomic_json(directory/'migration/evidence_manifest.json',{'source_import_key':report['source_import_key'],'source_files':report['source_files'],'vectors_sha256':gpkg_hash,'unknown_layers':[layer for layer in report['layers'] if not layer['recognized']]})
        return report
    except Exception as exc:
        report.update(import_status='quarantined',project_id=project.project_id,reason=str(exc))
        atomic_json(directory/'migration/report.json',report)
        return report


def import_project(source:Path,workspace:Path):
    source=source.resolve();workspace=workspace.resolve();report=scan(source)
    if report['import_status']!='validated':return report
    for path in workspace.glob('projects/*/state/project.sqlite'):
        with get_ports().archives.open(path) as connection:
            try:match=connection.execute("SELECT project_id,report_rel_path FROM migration_import WHERE source_import_key=? AND import_status='committed'",(report['source_import_key'],)).fetchone()
            except get_ports().archives.operational_error:continue
            if match:return {**report,'project_id':match[0],'report_rel_path':match[1],'duplicate':True,'import_status':'committed'}
    # Keep staging on the destination volume, with a short path for Windows MAX_PATH installations.
    staging=workspace.parent/('import-'+uuid4().hex[:8])
    try:
        result=_import_project(source,staging)
        if result.get('import_status')!='committed':
            fault=workspace/'migration_reports'/report['source_import_key'];fault.mkdir(parents=True,exist_ok=True);atomic_json(fault/'report.json',result)
            return result
        project_id=result['project_id'];directory=staging/'projects'/project_id
        with get_ports().archives.open(directory/'state/project.sqlite') as connection:
            connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or connection.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Imported database integrity verification failed')
            counts=dict(connection.execute('SELECT feature_type,count(*) FROM feature GROUP BY feature_type'))
        expected={}
        for item in report['layers']:
            if item['legacy_layer_name'] in LAYERS:
                kind=LAYERS[item['legacy_layer_name']];expected[kind]=expected.get(kind,0)+item['feature_count']
        if counts!=expected:raise ValueError('Import feature count reconciliation failed')
        for item in report['source_files']:
            if sha256_file(source/item['rel_path'])!=item['sha256']:raise ValueError('Source changed during migration')
        result['readback_report']={'integrity_check':'ok','foreign_key_check':[],'feature_counts':counts,'source_unchanged':True}
        atomic_json(directory/'migration/report.json',result)
        target=workspace/'projects'/project_id;target.parent.mkdir(parents=True,exist_ok=True);directory.rename(target)
        return result
    except Exception as exc:
        report.update(import_status='quarantined',reason=str(exc))
        fault=workspace/'migration_reports'/report['source_import_key'];atomic_json(fault/'report.json',report)
        return report
    finally:
        if staging.exists():
            import gc;gc.collect()
            shutil.rmtree(staging,ignore_errors=True)

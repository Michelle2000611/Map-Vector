import hashlib
import json
from mapvector.domain.ports import get_ports
from contextlib import closing
from mapvector.configuration.settings import Settings
from datetime import datetime,timezone
from uuid import uuid4

from mapvector.domain.errors import CommandConflict
from mapvector.application.commands import CommandService
from mapvector.application.ports import ProjectDatabase
from mapvector.application.ports import atomic_json,sha256_file
from mapvector.application.ports import write_gis
from mapvector.geometry.scope import scoped_features


DELIVERABLE={'confirmed','manual_edited','pipeline_complete_unverified','auto_accepted_unverified'}


def text_released(feature,policy):
    if policy=='strict_review':
        return feature['review_status']=='confirmed' and feature.get('reviewed_content_revision')==feature.get('text_content_revision')
    return feature['review_status'] in DELIVERABLE


class ExportService:
    def __init__(self,project_dir):
        self.project_dir=project_dir;self.database=ProjectDatabase(project_dir/'state/project.sqlite')

    def create(self,project_id,payload,export_id=None):
        reserved=export_id is not None
        def stage(name):
            if reserved:
                with self.database.transaction() as connection:
                    row=connection.execute('SELECT cancel_requested FROM export WHERE export_id=? AND project_id=?',(export_id,project_id)).fetchone()
                    if row is None or row[0]:raise CommandConflict('RUN_CANCELLED')
                    connection.execute('UPDATE export SET stage_name=?,heartbeat_at=? WHERE export_id=?',(name,datetime.now(timezone.utc).isoformat(),export_id))
        stage('validate_snapshot')
        if payload['policy_id'] not in ('baseline_compatible','strict_review'):raise CommandConflict('EXPORT_POLICY_UNAVAILABLE')
        if payload['export_format'] not in ('pixel_json','gpkg','geojson','shp'):raise CommandConflict('EXPORT_FORMAT_UNAVAILABLE')
        with self.database.read() as connection:
            snapshot=connection.execute("SELECT * FROM snapshot WHERE snapshot_id=? AND project_id=? AND snapshot_status='committed'",(payload['snapshot_id'],project_id)).fetchone()
        if snapshot is None:raise KeyError(payload['snapshot_id'])
        directory=self.project_dir/snapshot['snapshot_rel_path']
        manifest_path=directory/'manifest.json'
        if sha256_file(manifest_path)!=snapshot['manifest_sha256']:raise CommandConflict('SNAPSHOT_HASH_MISMATCH')
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        for name,digest in manifest['files'].items():
            if sha256_file(Settings.resolve_project_path(directory,name))!=digest:raise CommandConflict('SNAPSHOT_HASH_MISMATCH',{'file':name})
        with get_ports().archives.open(directory/'project.sqlite') as frozen:
            asset=frozen.execute('SELECT * FROM asset WHERE asset_id=?',(snapshot['asset_id'],)).fetchone()
            if asset is None:raise CommandConflict('ASSET_RESULT_MISMATCH')
            associations={
                'styles':[dict(row) for row in frozen.execute('SELECT * FROM style WHERE project_id=?',(project_id,))],
                'groups':[dict(row) for row in frozen.execute('SELECT * FROM logical_group WHERE project_id=? AND asset_id=?',(project_id,snapshot['asset_id']))],
                'group_members':[dict(row) for row in frozen.execute('SELECT m.* FROM group_member m JOIN logical_group g USING(group_id) WHERE g.project_id=? AND g.asset_id=?',(project_id,snapshot['asset_id']))],
                'lineage':[dict(row) for row in frozen.execute('SELECT l.* FROM feature_lineage l JOIN feature f ON f.feature_id=l.target_feature_id WHERE f.project_id=? AND f.asset_id=?',(project_id,snapshot['asset_id']))],
                'layers':[dict(row) for row in frozen.execute('SELECT * FROM layer_setting WHERE project_id=? AND asset_id=?',(project_id,snapshot['asset_id']))],
            }
            features=[CommandService._feature(frozen,row[0]) for row in frozen.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND lifecycle_status IN ('active','isolated')",(project_id,snapshot['asset_id']))]
            roi=frozen.execute('SELECT * FROM roi WHERE roi_id=? AND project_id=? AND asset_id=?',(payload['roi_id'],project_id,snapshot['asset_id'])).fetchone() if payload['roi_id'] else None
            declared_roi=frozen.execute('SELECT * FROM roi WHERE project_id=? AND asset_id=?',(project_id,snapshot['asset_id'])).fetchone()
            if payload['roi_id'] and roi is None:raise CommandConflict('EXPORT_SCOPE_INVALID')
            if payload['scope_mode']=='full' and payload['roi_id'] is not None:raise CommandConflict('EXPORT_SCOPE_INVALID')
            if payload['scope_mode']!='full' and payload['roi_id'] is None:raise CommandConflict('EXPORT_SCOPE_INVALID')
        if payload['export_format']=='geojson' and asset['coordinate_mode']!='georeferenced':
            raise CommandConflict('GEOREFERENCE_REQUIRED')
        counts={}
        for feature in features:
            if feature['feature_type']=='text':counts[feature['review_status']]=counts.get(feature['review_status'],0)+1
        if payload['export_mode']=='formal' and any(not text_released(f,payload['policy_id']) for f in features if f['feature_type']=='text'):
            raise CommandConflict('FORMAL_REVIEW_INCOMPLETE',{'status_counts':counts})
        if payload['export_mode']=='formal' and payload['scope_mode']=='full' and declared_roi:
            from mapvector.geometry.scope import audit
            outside=audit([f for f in features if f['lifecycle_status']=='active'],dict(declared_roi))['outside']
            if outside:raise CommandConflict('FORMAL_OUTSIDE_ROI',{'outside_count':outside,'available_choices':['draft','keep_crossing','clip','clear_roi']})
        features=scoped_features(features,payload['scope_mode'],dict(roi) if roi else None)
        selected=[]
        for feature in features:
            layer='text_confirmed' if feature['feature_type']=='text' and text_released(feature,payload['policy_id']) else 'text_unconfirmed' if feature['feature_type']=='text' else 'isolated_line' if feature['feature_type']=='line' and feature['lifecycle_status']=='isolated' else feature['feature_type']
            if layer in payload['layer_types']:selected.append(feature)
        stage('write_and_readback')
        policy={'policy_id':payload['policy_id'],'policy_revision':'1.0','deliverable_statuses':['confirmed'] if payload['policy_id']=='strict_review' else sorted(DELIVERABLE),'human_confirmation_required':payload['policy_id']=='strict_review','status_counts':counts}
        export_id=export_id or str(uuid4());now=datetime.now(timezone.utc).isoformat();out_dir=self.project_dir/'exports'/export_id;out_dir.mkdir(parents=True,exist_ok=reserved)
        if payload['export_format']=='pixel_json':
            output=out_dir/'vectors.json';document={'schema_revision':'1.0','coordinate_space':'pixel','asset_id':snapshot['asset_id'],'width_px':asset['width_px'],'height_px':asset['height_px'],'crs_wkt':asset['crs_wkt'],'pixel_to_map_affine':json.loads(asset['pixel_to_map_affine']) if asset['pixel_to_map_affine'] else None,'policy_snapshot':policy,'features':[{'type':'Feature','id':f['feature_id'],'geometry':f['geometry'],'properties':{key:value for key,value in f.items() if key!='geometry'}} for f in selected]}
            atomic_json(output,document);readback=json.loads(output.read_text(encoding='utf-8'))
            if readback!=document:raise CommandConflict('EXPORT_READBACK_FAILED')
            report={'feature_count':len(readback['features']),'coordinate_space':document['coordinate_space'],'scope_mode':payload['scope_mode'],'attributes_match':True,'geometry_match':True,'tolerance':0}
        else:
            def layer_type(feature):
                kind=feature['feature_type']
                return 'text_confirmed' if kind=='text' and text_released(feature,payload['policy_id']) else 'text_unconfirmed' if kind=='text' else 'isolated_line' if kind=='line' and feature['lifecycle_status']=='isolated' else kind
            selected=[feature for feature in selected if layer_type(feature) in payload['layer_types']]
            if payload['export_format']=='geojson' and asset['pixel_to_map_affine'] is not None:
                asset={**dict(asset),'pixel_to_map_affine':json.loads(asset['pixel_to_map_affine'])}
            output,report=write_gis(out_dir,selected,dict(asset),payload['export_format'],layer_type)
            report['scope_mode']=payload['scope_mode']
        relative=output.relative_to(self.project_dir).as_posix();digest=sha256_file(output)
        stage('write_associations')
        association_document={'schema_revision':'1.0','project_id':project_id,'asset_id':snapshot['asset_id'],'snapshot_id':snapshot['snapshot_id'],'policy_snapshot':policy,**associations}
        if payload['export_format']=='shp':
            association_document.update(property_manifest_file='property_manifest.json',field_mapping_file='field_mapping.json',shapefile_manifest_file='shapefile_manifest.json')
        atomic_json(out_dir/'associations.json',association_document)
        if json.loads((out_dir/'associations.json').read_text(encoding='utf-8'))!=association_document:
            raise CommandConflict('EXPORT_READBACK_FAILED',{'artifact':'associations.json'})
        if payload['export_format']=='gpkg':
            embedded={**associations,'policy':policy,'source':{key:association_document[key] for key in ('schema_revision','project_id','asset_id','snapshot_id')}}
            with get_ports().archives.open(output) as derived:
                derived.execute('CREATE TABLE mapvector_manifest (manifest_type TEXT PRIMARY KEY,manifest TEXT NOT NULL)')
                for kind,value in embedded.items():derived.execute('INSERT INTO mapvector_manifest VALUES (?,?)',(kind,json.dumps(value,ensure_ascii=False)))
            with get_ports().archives.open(output) as derived:
                actual={row['manifest_type']:json.loads(row['manifest']) for row in derived.execute('SELECT * FROM mapvector_manifest')}
            if actual!=embedded:raise CommandConflict('EXPORT_READBACK_FAILED',{'artifact':'mapvector_manifest'})
        elif payload['export_format']=='shp':
            import zipfile
            with zipfile.ZipFile(output,'a',zipfile.ZIP_DEFLATED) as archive:archive.write(out_dir/'associations.json','associations.json')
            with zipfile.ZipFile(output) as archive:
                if archive.testzip() is not None or json.loads(archive.read('associations.json'))!=association_document:
                    raise CommandConflict('EXPORT_READBACK_FAILED',{'artifact':'associations.json'})
        elif payload['export_format']=='pixel_json':
            document['associations']=associations;atomic_json(output,document)
            if json.loads(output.read_text(encoding='utf-8'))!=document:raise CommandConflict('EXPORT_READBACK_FAILED')
        else:
            document=json.loads(output.read_text(encoding='utf-8'));document['mapvector_associations']=associations;atomic_json(output,document)
            if json.loads(output.read_text(encoding='utf-8'))!=document:raise CommandConflict('EXPORT_READBACK_FAILED')
        report['associations_match']=True
        digest=sha256_file(output)
        stage('commit')
        finished_at=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            if reserved:
                row=connection.execute('SELECT cancel_requested,export_status FROM export WHERE export_id=? AND project_id=?',(export_id,project_id)).fetchone()
                if row is None or row['cancel_requested'] or row['export_status']!='running':raise CommandConflict('RUN_CANCELLED')
                connection.execute("UPDATE export SET export_status='completed',output_rel_path=?,output_sha256=?,readback_report=?,policy_snapshot=?,roi_revision=?,finished_at=?,stage_name='completed' WHERE export_id=?",(relative,digest,json.dumps(report,ensure_ascii=False),json.dumps(policy,ensure_ascii=False),roi['revision'] if roi else None,finished_at,export_id))
            else:
                connection.execute('INSERT INTO export (export_id,project_id,asset_id,snapshot_id,export_format,export_mode,roi_id,scope_mode,coordinate_mode,policy_snapshot,export_status,output_rel_path,output_sha256,readback_report,created_at,finished_at,layer_types,roi_revision) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(export_id,project_id,snapshot['asset_id'],snapshot['snapshot_id'],payload['export_format'],payload['export_mode'],payload['roi_id'],payload['scope_mode'],asset['coordinate_mode'],json.dumps(policy,ensure_ascii=False),'completed',relative,digest,json.dumps(report,ensure_ascii=False),now,finished_at,json.dumps(payload['layer_types']),roi['revision'] if roi else None))
        return {'export_id':export_id,'snapshot_id':snapshot['snapshot_id'],'export_status':'completed','output_rel_path':relative,'output_sha256':digest,'readback_report':report,'policy_snapshot':policy}

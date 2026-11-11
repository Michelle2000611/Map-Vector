import io
import json
import hashlib
from mapvector.domain.ports import get_ports
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from mapvector.domain.errors import CommandConflict
from mapvector.application.ports import ProjectDatabase
from mapvector.application.ports import atomic_bytes,atomic_json,sha256_file
from mapvector.application.ports import probe,decode,sniff
MAX_BYTES=get_ports().raster.max_bytes


class AssetService:
    def __init__(self, project_dir: Path):
        self.project_dir=project_dir
        self.database=ProjectDatabase(project_dir/'state/project.sqlite')

    def upload_source(self,project_id: str,display_name: str,content: bytes):
        if len(content)>MAX_BYTES:
            raise CommandConflict('UPLOAD_TOO_LARGE',{'max_bytes':MAX_BYTES})
        kind,pages=probe(content)
        source_id=str(uuid4());relative=f'sources/{source_id}/source'
        display_name=display_name.replace(chr(92),'/').split('/')[-1] or 'source'
        record={'source_id':source_id,'project_id':project_id,'source_file_name':display_name,'source_rel_path':relative,'source_sha256':hashlib.sha256(content).hexdigest(),'byte_size':len(content),'page_count':len(pages),'created_at':datetime.now(timezone.utc).isoformat()}
        path=self.project_dir/relative
        atomic_bytes(path,content)
        atomic_json(path.parent/'manifest.json',{**record,'source_type':kind,'pages':pages})
        try:
            with self.database.transaction() as connection:
                connection.execute('INSERT INTO source_file VALUES (?,?,?,?,?,?,?,?)',tuple(record.values()))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return {**record,'source_type':kind,'pages':pages}

    def normalize_asset(self,project_id: str,source_id: str,page_index: int,config: dict):
        with self.database.transaction() as connection:
            row=connection.execute('SELECT * FROM source_file WHERE source_id=? AND project_id=?',(source_id,project_id)).fetchone()
            if row is None:
                raise KeyError(source_id)
            source=dict(row)
        if not 0<=page_index<source['page_count']:
            raise CommandConflict('ASSET_PAGE_INVALID',{'page_count':source['page_count']})
        path=self.project_dir/source['source_rel_path']
        if sha256_file(path)!=source['source_sha256']:
            raise CommandConflict('ASSET_RESULT_MISMATCH',{'reason':'Immutable source hash changed'})
        with path.open('rb') as stream:
            kind=sniff(stream.read(16))
        image,crs,affine,normalization=decode(path,kind,page_index,config['dpi'])
        external=path.parent/'georeference.json'
        if external.is_file():
            reference=json.loads(external.read_text('utf-8'))
            from pyproj import CRS
            import math
            if crs and (not CRS.from_user_input(crs).equals(CRS.from_user_input(reference['crs_wkt'])) or not all(math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9) for a,b in zip(affine,reference['pixel_to_map_affine']))):raise CommandConflict('GEOREFERENCE_CONFLICT',{'reason':'Source has internal georeferencing; external override is not automatic'})
            crs=reference['crs_wkt'];affine=reference['pixel_to_map_affine']
            from mapvector.geometry.georeference import oriented_affine
            if normalization.get('exif_orientation_applied',1)!=1:
                affine=oriented_affine(affine,normalization['exif_orientation_applied'],normalization['original_width_px'],normalization['original_height_px'])
            normalization.update(georeference_source='external_world_file',external_reference_sha256=sha256_file(external),world_file_sha256=sha256_file(external.parent/'world.txt'),crs_file_sha256=sha256_file(external.parent/'crs.prj'),pixel_convention='pixel edge origin; center=(col+0.5,row+0.5)')
        buffer=io.BytesIO();image.save(buffer,format='PNG')
        content=buffer.getvalue();asset_id=str(uuid4());relative=f'assets/{asset_id}/raster.png'
        record={'asset_id':asset_id,'project_id':project_id,'source_id':source_id,'raster_rel_path':relative,'raster_sha256':hashlib.sha256(content).hexdigest(),'width_px':image.width,'height_px':image.height,'page_index':page_index,'coordinate_mode':'georeferenced' if crs else 'pixel','crs_wkt':crs,'pixel_to_map_affine':affine,'normalization_config':normalization,'created_at':datetime.now(timezone.utc).isoformat()}
        atomic_bytes(self.project_dir/relative,content)
        atomic_json(self.project_dir/relative.replace('raster.png','manifest.json'),record)
        try:
            with self.database.transaction() as connection:
                values={**record,'pixel_to_map_affine':json.dumps(affine) if affine else None,'normalization_config':json.dumps(normalization)}
                connection.execute('INSERT INTO asset ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
                current=connection.execute('SELECT current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()[0]
                if current is None:
                    connection.execute('UPDATE project SET current_asset_id=?,updated_at=? WHERE project_id=?',(asset_id,record['created_at'],project_id))
        except BaseException:
            atomic_json((self.project_dir/relative).parent/'fault.json',{'code':'ASSET_COMMIT_FAILED','asset_id':asset_id,'recoverable':True})
            raise
        return {**record,'is_current':current is None}

    def get(self,project_id,asset_id):
        with self.database.read() as connection:
            row=connection.execute('SELECT * FROM asset WHERE project_id=? AND asset_id=?',(project_id,asset_id)).fetchone()
        if row is None:
            raise KeyError(asset_id)
        result=dict(row)
        result['normalization_config']=json.loads(result['normalization_config'])
        result['pixel_to_map_affine']=json.loads(result['pixel_to_map_affine']) if result['pixel_to_map_affine'] else None
        return result

    def adopt(self,project_id,asset_id,base_revision):
        target_asset=self.get(project_id,asset_id)
        if sha256_file(self.project_dir/target_asset['raster_rel_path'])!=target_asset['raster_sha256']:raise CommandConflict('ASSET_RESULT_MISMATCH')
        from mapvector.application.snapshots import SnapshotService
        snapshot=SnapshotService(self.project_dir).create(project_id,base_revision,'Before explicit asset adoption')
        operation_id=str(uuid4());timestamp=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            project=dict(connection.execute('SELECT * FROM project WHERE project_id=?',(project_id,)).fetchone())
            if project['working_revision']!=base_revision:
                raise CommandConflict('REVISION_CONFLICT')
            result={'operation_id':operation_id,'result_revision':base_revision+1,'current_asset_id':asset_id,'previous_snapshot_id':snapshot['snapshot_id']}
            payload={'asset_id':asset_id,'base_revision':base_revision}
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode('utf-8')).hexdigest()
            connection.execute('INSERT INTO operation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(operation_id,project_id,'adopt_asset',base_revision,base_revision+1,operation_id,digest,'applied','local-user',None,json.dumps(result),timestamp))
            after={**project,'current_asset_id':asset_id,'working_revision':base_revision+1,'updated_at':timestamp}
            connection.execute('INSERT INTO operation_change VALUES (?,?,?,?,?,?,?,?,?)',(str(uuid4()),operation_id,'project',project_id,json.dumps(project),json.dumps(after),None,None,'1.0'))
            connection.execute('UPDATE project SET current_asset_id=?,working_revision=?,updated_at=? WHERE project_id=?',(asset_id,base_revision+1,timestamp,project_id))
            connection.execute("UPDATE operation SET operation_status='abandoned' WHERE project_id=? AND operation_status='undone'",(project_id,))
        return result

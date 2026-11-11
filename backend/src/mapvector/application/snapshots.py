"""Consistent backups and compensating business-state restoration."""
import hashlib
import json
from mapvector.domain.ports import get_ports
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from mapvector.domain.errors import CommandConflict
from mapvector.application.ports import ProjectDatabase
from mapvector.application.ports import atomic_json,sha256_file


class SnapshotService:
    def __init__(self, project_dir: Path):
        self.project_dir=project_dir
        self.database=ProjectDatabase(project_dir/'state/project.sqlite')

    def create(self,project_id,base_revision,note=None):
        snapshot_id=str(uuid4());relative=f'snapshots/{snapshot_id}'
        directory=self.project_dir/relative
        now=datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as connection:
            project=connection.execute('SELECT * FROM project WHERE project_id=?',(project_id,)).fetchone()
            if project is None:
                raise KeyError(project_id)
            if project['working_revision']!=base_revision:
                raise CommandConflict('REVISION_CONFLICT')
            sequence=connection.execute('SELECT COALESCE(MAX(snapshot_sequence),0)+1 FROM snapshot').fetchone()[0]
            asset_id=project['current_asset_id']
            connection.execute('INSERT INTO snapshot VALUES (?,?,?,?,?,?,?,?,?,?)',(snapshot_id,project_id,asset_id,sequence,base_revision,relative,'',note,'prepared',now))
        directory.mkdir(parents=True)
        try:
            # First SELECT pins the WAL snapshot; derived files read the SQLite backup.
            with get_ports().archives.open(self.database.path) as source, get_ports().archives.open(directory/'project.sqlite') as target:
                source.execute('BEGIN')
                project=source.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',(project_id,)).fetchone()
                if tuple(project)!=(base_revision,asset_id):
                    raise CommandConflict('REVISION_CONFLICT')
                get_ports().archives.backup(source,target)
            self._write_vectors(directory,asset_id)
            manifest={'snapshot_id':snapshot_id,'project_id':project_id,'asset_id':asset_id,'working_revision':base_revision,'schema_revision':'1.0','snapshot_status':'committed','files':{name:sha256_file(directory/name) for name in ('project.sqlite','vectors.gpkg')}}
            atomic_json(directory/'manifest.json',manifest)
            digest=sha256_file(directory/'manifest.json')
            with self.database.transaction() as connection:
                connection.execute("UPDATE snapshot SET snapshot_status='files_ready',manifest_sha256=? WHERE snapshot_id=?",(digest,snapshot_id))
            with self.database.transaction() as connection:
                connection.execute("UPDATE snapshot SET snapshot_status='committed' WHERE snapshot_id=?",(snapshot_id,))
                connection.execute('UPDATE project SET current_snapshot_id=? WHERE project_id=?',(snapshot_id,project_id))
            return {'snapshot_id':snapshot_id,'asset_id':asset_id,'snapshot_sequence':sequence,'working_revision':base_revision,'snapshot_rel_path':relative,'snapshot_status':'committed','manifest_sha256':digest,'snapshot_note':note}
        except BaseException:
            with self.database.transaction() as connection:
                connection.execute("UPDATE snapshot SET snapshot_status='failed' WHERE snapshot_id=?",(snapshot_id,))
            raise

    @staticmethod
    def _write_vectors(directory,asset_id):
        import geopandas as gpd
        import pandas as pd
        from shapely import from_wkb
        with get_ports().archives.open(directory/'project.sqlite') as frozen:
            for kind in ('face','line','text'):
                rows=frozen.execute("SELECT * FROM feature WHERE asset_id=? AND feature_type=? AND lifecycle_status IN ('active','isolated')",(asset_id,kind)).fetchall() if asset_id else []
                records=[]
                for row in rows:
                    item=dict(row);item.pop('geometry_wkb')
                    attrs=frozen.execute('SELECT * FROM '+kind+'_attribute WHERE feature_id=?',(row['feature_id'],)).fetchone()
                    if attrs is None:
                        raise CommandConflict('FEATURE_ATTRIBUTE_MISSING',{'feature_id':row['feature_id']})
                    item.update(dict(attrs));records.append(item)
                frame=gpd.GeoDataFrame(records if records else {'feature_id':pd.Series(dtype='str'),'feature_type':pd.Series(dtype='str')},geometry=[from_wkb(row['geometry_wkb']) for row in rows],crs=None)
                frame.to_file(directory/'vectors.gpkg',layer=kind,driver='GPKG',engine='pyogrio')
        with get_ports().archives.open(directory/'vectors.gpkg') as gpkg:
            gpkg.execute("UPDATE gpkg_contents SET description='coordinate_space=pixel; units=pixel; no geographic CRS'")
            gpkg.commit()

    def validate(self,project_id,snapshot_id):
        with self.database.transaction() as connection:
            row=connection.execute("SELECT * FROM snapshot WHERE snapshot_id=? AND project_id=? AND snapshot_status='committed'",(snapshot_id,project_id)).fetchone()
        if row is None:
            raise KeyError(snapshot_id)
        directory=self.project_dir/row['snapshot_rel_path']
        if sha256_file(directory/'manifest.json')!=row['manifest_sha256']:
            raise CommandConflict('SNAPSHOT_HASH_MISMATCH')
        manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('schema_revision')!='1.0' or manifest.get('snapshot_id')!=snapshot_id or manifest.get('project_id')!=project_id:
            raise CommandConflict('SNAPSHOT_SCHEMA_MISMATCH')
        for name in ('project.sqlite','vectors.gpkg'):
            if sha256_file(directory/name)!=manifest['files'][name]:
                raise CommandConflict('SNAPSHOT_HASH_MISMATCH',{'file':name})
        return dict(row),directory

    def restore(self,project_id,snapshot_id,base_revision):
        snapshot,directory=self.validate(project_id,snapshot_id)
        self.create(project_id,base_revision,'Before restoring snapshot '+snapshot_id)
        tables=('style','layer_setting','feature','face_attribute','line_attribute','text_attribute','logical_group','group_member','roi')
        def query_table(connection,table):
            if table in ('style','layer_setting','feature','logical_group','roi'):sql='SELECT * FROM '+table+' WHERE project_id=?'
            elif table=='group_member':sql='SELECT * FROM group_member WHERE group_id IN (SELECT group_id FROM logical_group WHERE project_id=?)'
            else:sql='SELECT * FROM '+table+' WHERE feature_id IN (SELECT feature_id FROM feature WHERE project_id=?)'
            return [dict(row) for row in connection.execute(sql,(project_id,))]
        with get_ports().archives.open(directory/'project.sqlite') as frozen:
            saved={table:query_table(frozen,table) for table in tables}
        operation_id=str(uuid4());now=datetime.now(timezone.utc).isoformat();revision=base_revision+1
        with self.database.transaction() as connection:
            project=dict(connection.execute('SELECT * FROM project WHERE project_id=?',(project_id,)).fetchone())
            if project['working_revision']!=base_revision:
                raise CommandConflict('REVISION_CONFLICT')
            before={table:query_table(connection,table) for table in tables}
            connection.execute("UPDATE feature SET lifecycle_status='deleted',revision=?,updated_at=? WHERE project_id=?",(revision,now,project_id))
            connection.execute('DELETE FROM feature_index WHERE id IN (SELECT rowid FROM feature WHERE project_id=?)',(project_id,))
            connection.execute('DELETE FROM text_display_index WHERE id IN (SELECT rowid FROM feature WHERE project_id=?)',(project_id,))
            connection.execute('DELETE FROM group_member WHERE group_id IN (SELECT group_id FROM logical_group WHERE project_id=?)',(project_id,))
            connection.execute('DELETE FROM logical_group WHERE project_id=?',(project_id,))
            connection.execute('DELETE FROM roi WHERE project_id=?',(project_id,))
            connection.execute('DELETE FROM layer_setting WHERE project_id=?',(project_id,))
            saved_styles={item['style_id'] for item in saved['style']}
            for item in before['style']:
                if item['style_id'] not in saved_styles:
                    connection.execute('UPDATE feature SET style_id=NULL WHERE style_id=?',(item['style_id'],))
                    connection.execute('DELETE FROM feature_style WHERE style_id=?',(item['style_id'],))
                    connection.execute('DELETE FROM style WHERE style_id=?',(item['style_id'],))
            for table in tables:
                for item in saved[table]:
                    if table=='text_attribute':
                        item={**{'layout_width_px':None,'layout_height_px':None,'baseline_offset_px':None,'layout_basis':'legacy_estimate','layout_runs':'[]'},**item}
                    if table in ('feature','style','roi','logical_group'):
                        item['revision']=revision;item['updated_at']=now
                        if table!='feature':item.pop('updated_at',None)
                    fields=list(item)
                    sql='INSERT INTO '+table+' ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')'
                    if table=='group_member':
                        sql='INSERT INTO group_member (group_id,feature_id) VALUES (?,?) ON CONFLICT(group_id,feature_id) DO NOTHING'
                    elif table=='layer_setting':
                        sql+=' ON CONFLICT(project_id,asset_id,layer_type) DO UPDATE SET is_visible=excluded.is_visible,opacity=excluded.opacity,default_style_id=excluded.default_style_id'
                    else:
                        key='feature_id' if table in ('feature','face_attribute','line_attribute','text_attribute') else 'group_id' if table=='logical_group' else 'style_id' if table=='style' else 'roi_id'
                        sql+=' ON CONFLICT('+key+') DO UPDATE SET '+','.join(field+'=excluded.'+field for field in fields if field!=key)
                    connection.execute(sql,tuple(item[field] for field in fields))
                    if table=='feature' and item['lifecycle_status'] in ('active','isolated'):
                        identifier=connection.execute('SELECT rowid FROM feature WHERE feature_id=?',(item['feature_id'],)).fetchone()[0]
                        connection.execute('INSERT INTO feature_index VALUES (?,?,?,?,?)',(identifier,item['bbox_min_x_px'],item['bbox_max_x_px'],item['bbox_min_y_px'],item['bbox_max_y_px']))
            from mapvector.application.ports import update_index
            for item in saved['feature']:
                if item['feature_type']=='text':update_index(connection,item['feature_id'])
            result={'operation_id':operation_id,'result_revision':revision,'restored_snapshot_id':snapshot_id,'restored_asset_id':snapshot['asset_id'],'current_asset_id':snapshot['asset_id']}
            digest=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
            connection.execute('INSERT INTO operation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(operation_id,project_id,'restore_snapshot',base_revision,revision,operation_id,digest,'applied','local-user',None,json.dumps(result),now))
            after_project={**project,'current_asset_id':snapshot['asset_id'],'working_revision':revision,'updated_at':now}
            connection.execute('INSERT INTO operation_change VALUES (?,?,?,?,?,?,?,?,?)',(str(uuid4()),operation_id,'project',project_id,json.dumps(project),json.dumps(after_project),None,None,'1.0'))
            for table in ('feature','logical_group','group_member','roi','style','layer_setting'):
                def key(item):
                    return item['group_id']+':'+item['feature_id'] if table=='group_member' else item['project_id']+':'+item['asset_id']+':'+item['layer_type'] if table=='layer_setting' else item.get('feature_id') or item.get('group_id') or item.get('roi_id') or item.get('style_id')
                old={key(item):dict(item) for item in before[table]};new={key(item):dict(item) for item in saved[table]}
                for identity in old.keys()|new.keys():
                    left=old.get(identity);right=new.get(identity)
                    left_wkb=left.pop('geometry_wkb',None) if left else None
                    right_wkb=right.pop('geometry_wkb',None) if right else None
                    if table=='feature':
                        for state,data in ((left,before),(right,saved)):
                            if state:
                                attrs=next((item for item in data[state['feature_type']+'_attribute'] if item['feature_id']==identity),{})
                                state['attributes']=attrs
                    connection.execute('INSERT INTO operation_change VALUES (?,?,?,?,?,?,?,?,?)',(str(uuid4()),operation_id,table,identity,json.dumps(left,ensure_ascii=False) if left else None,json.dumps(right,ensure_ascii=False) if right else None,left_wkb,right_wkb,'1.0'))
            connection.execute('UPDATE project SET current_asset_id=?,working_revision=?,updated_at=? WHERE project_id=?',(snapshot['asset_id'],revision,now,project_id))
            from mapvector.application.history import synchronize_candidates
            synchronize_candidates(connection,project_id)
            connection.execute("UPDATE operation SET operation_status='abandoned' WHERE project_id=? AND operation_status='undone'",(project_id,))
        return result

    def recover(self):
        """Recover only evidence-complete preparations; never guess from modification times."""
        reports=[]
        with self.database.read() as connection:rows=connection.execute('SELECT * FROM snapshot').fetchall()
        for row in rows:
            directory=self.project_dir/row['snapshot_rel_path']
            manifest_path=directory/'manifest.json'
            try:
                if not manifest_path.is_file():
                    if row['snapshot_status']=='committed':raise ValueError('Committed snapshot manifest is missing')
                    reports.append({'snapshot_id':row['snapshot_id'],'code':'SNAPSHOT_PREPARATION_INCOMPLETE','status':row['snapshot_status']});continue
                manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
                if manifest.get('snapshot_id')!=row['snapshot_id'] or manifest.get('working_revision')!=row['working_revision'] or manifest.get('project_id')!=row['project_id']:raise ValueError('Snapshot identity mismatch')
                for name in ('project.sqlite','vectors.gpkg'):
                    if sha256_file(directory/name)!=manifest['files'][name]:raise ValueError('Snapshot file hash mismatch: '+name)
                digest=sha256_file(manifest_path)
                if row['snapshot_status']=='committed' and digest!=row['manifest_sha256']:raise ValueError('Snapshot manifest hash mismatch')
                if row['snapshot_status'] in ('prepared','files_ready'):
                    with self.database.transaction() as connection:connection.execute("UPDATE snapshot SET snapshot_status='committed',manifest_sha256=? WHERE snapshot_id=?",(digest,row['snapshot_id']))
                    reports.append({'snapshot_id':row['snapshot_id'],'code':'SNAPSHOT_RECOVERED','status':'committed'})
            except (ValueError,OSError,KeyError) as exc:
                reports.append({'snapshot_id':row['snapshot_id'],'code':'SNAPSHOT_HASH_MISMATCH','reason':str(exc)})
                if row['snapshot_status']=='committed':
                    with self.database.transaction() as connection:connection.execute("UPDATE snapshot SET snapshot_status='failed' WHERE snapshot_id=?",(row['snapshot_id'],))
        if reports:atomic_json(self.project_dir/'state/recovery_report.json',{'snapshots':reports})
        return reports

"""Immutable project backup/restore that never overwrites an existing project."""
import json
import shutil
from mapvector.domain.ports import get_ports
import zipfile
from contextlib import closing
from pathlib import Path,PurePosixPath
from uuid import UUID,uuid4

from mapvector.application.ports import atomic_json,sha256_file


def backup_project(project_dir:Path,output:Path):
    project_dir=project_dir.resolve();output=output.resolve()
    if output.exists():raise ValueError('Backup destination already exists')
    if output.is_relative_to(project_dir):raise ValueError('Backup must be outside its source project')
    staging=output.parent/('.backup-'+uuid4().hex[:8]);staging.mkdir(parents=True)
    try:
        destination=staging/'state/project.sqlite';destination.parent.mkdir()
        with get_ports().archives.open(project_dir/'state/project.sqlite') as source,get_ports().archives.open(destination) as target:get_ports().archives.backup(source,target)
        with get_ports().archives.open(destination) as frozen:
            project=frozen.execute('SELECT project_id,working_revision FROM project').fetchone()
            pending=frozen.execute("SELECT count(*) FROM run WHERE run_status IN ('queued','starting','running','cancelling')").fetchone()[0]
            if pending:raise ValueError('Stop or cancel recognition jobs before taking a full project backup')
            exporting=frozen.execute("SELECT count(*) FROM export WHERE export_status IN ('queued','running','cancelling')").fetchone()[0]
            if exporting:raise ValueError('Stop or cancel exports before taking a full project backup')
        files=[]
        for path in project_dir.rglob('*'):
            if not path.is_file():continue
            relative=path.relative_to(project_dir)
            if relative.as_posix().startswith('state/') or path.suffix in ('.tmp','.part') or path.name.endswith(('-wal','-shm')):continue
            copied=staging/relative;copied.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,copied)
        for path in staging.rglob('*'):
            if path.is_file():files.append({'rel_path':path.relative_to(staging).as_posix(),'sha256':sha256_file(path),'byte_size':path.stat().st_size})
        atomic_json(staging/'backup_manifest.json',{'project_id':project[0],'working_revision':project[1],'schema_revision':'1.0','files':files})
        output.parent.mkdir(parents=True,exist_ok=True);temporary=output.with_suffix('.part')
        with zipfile.ZipFile(temporary,'x',zipfile.ZIP_DEFLATED) as archive:
            for path in staging.rglob('*'):
                if path.is_file():archive.write(path,path.relative_to(staging).as_posix())
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip():raise ValueError('Backup ZIP failed integrity check')
        temporary.replace(output)
        return {'project_id':project[0],'working_revision':project[1],'backup_sha256':sha256_file(output),'file_count':len(files),'output':str(output)}
    finally:shutil.rmtree(staging)


def restore_backup(backup:Path,workspace:Path):
    workspace=workspace.resolve();staging=workspace/('.restore-'+uuid4().hex[:8]);staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(backup) as archive:
            for name in archive.namelist():
                relative=PurePosixPath(name)
                if relative.is_absolute() or '..' in relative.parts or chr(92) in name or ':' in name:raise ValueError('Unsafe backup archive path')
            archive.extractall(staging)
        manifest=json.loads((staging/'backup_manifest.json').read_text(encoding='utf-8'));project_id=str(UUID(manifest['project_id']))
        for item in manifest['files']:
            path=(staging/item['rel_path']).resolve()
            if not path.is_relative_to(staging) or sha256_file(path)!=item['sha256']:raise ValueError('Backup artifact hash mismatch')
        with get_ports().archives.open(staging/'state/project.sqlite') as connection:
            if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or connection.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Backup database integrity check failed')
            if connection.execute('SELECT project_id FROM project').fetchone()[0]!=project_id:raise ValueError('Backup identity mismatch')
        target=workspace/'projects'/project_id
        if target.exists():raise ValueError('Target project already exists; restore to a separate workspace')
        target.parent.mkdir(parents=True,exist_ok=True);staging.rename(target)
        return {'project_id':project_id,'restored_directory':str(target),'working_revision':manifest['working_revision']}
    finally:
        if staging.exists():shutil.rmtree(staging)

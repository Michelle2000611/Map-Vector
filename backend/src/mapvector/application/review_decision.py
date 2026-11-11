import hashlib
from uuid import uuid4
from mapvector.domain.errors import CommandConflict
from mapvector.application.ports import load_feature


def decide(connection,project_id,command,timestamp,actor_id):
    changes=[];events=[];features=[];status='confirmed' if command.operation_type=='confirm_text' else 'skipped'
    for identity in dict.fromkeys(command.feature_ids):
        row=connection.execute("SELECT f.feature_id,t.text_value,t.text_content_revision FROM feature f JOIN text_attribute t USING(feature_id) WHERE f.feature_id=? AND f.project_id=? AND f.asset_id=? AND f.lifecycle_status='active'",(identity,project_id,command.asset_id)).fetchone()
        if row is None:raise CommandConflict('RESOURCE_NOT_FOUND')
        before=load_feature(connection,identity)
        connection.execute('UPDATE text_attribute SET review_status=?,review_basis=?,reviewed_content_revision=?,reviewed_at=?,reviewer_id=? WHERE feature_id=?',(status,'explicit_confirmation' if status=='confirmed' else 'none',row['text_content_revision'] if status=='confirmed' else None,timestamp if status=='confirmed' else None,actor_id if status=='confirmed' else None,identity))
        connection.execute('UPDATE feature SET revision=?,updated_at=? WHERE feature_id=?',(command.base_revision+1,timestamp,identity))
        after=load_feature(connection,identity);features.append(after);changes.append((before,after))
        events.append((str(uuid4()),project_id,identity,row['text_content_revision'],'confirm' if status=='confirmed' else 'skip',actor_id,timestamp,hashlib.sha256(row['text_value'].encode('utf-8')).hexdigest()))
    return changes,events,features,{'decision':status,'count':len(events)}

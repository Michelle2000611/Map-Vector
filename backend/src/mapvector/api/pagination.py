"""Opaque cursors bound to a precise query and working revision."""
import base64
import hashlib
import json
from uuid import UUID

from mapvector.domain.errors import CommandConflict


def query_digest(project_id,asset_id,feature_type,bounds,layer_type=None):
    return hashlib.sha256(json.dumps([project_id,asset_id,feature_type,bounds,layer_type],separators=(',',':')).encode()).hexdigest()


def encode_cursor(last_feature_id,revision,digest):
    payload=json.dumps({'last_feature_id':last_feature_id,'working_revision':revision,'query_sha256':digest},separators=(',',':')).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip('=')


def decode_cursor(cursor,revision,digest):
    try:
        payload=json.loads(base64.urlsafe_b64decode(cursor+'='*((-len(cursor))%4)))
        if payload['query_sha256']!=digest:raise CommandConflict('CURSOR_QUERY_MISMATCH')
        if payload['working_revision']!=revision:raise CommandConflict('REVISION_CONFLICT',{'working_revision':revision,'reason':'Feature cursor is stale'})
        return str(UUID(payload['last_feature_id']))
    except CommandConflict:raise
    except (ValueError,KeyError,TypeError,UnicodeDecodeError) as exc:raise CommandConflict('CURSOR_INVALID') from exc

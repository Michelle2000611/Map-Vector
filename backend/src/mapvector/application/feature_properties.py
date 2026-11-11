"""Plan scoped object edits for CommandService's shared persistence and history path."""
from mapvector.application.ports import load_feature
from mapvector.domain.commands import DeleteFaces, DeleteLines, DeleteText, SetFeatureProperties
from mapvector.domain.errors import CommandConflict


def plan_feature_edit(connection, project_id, command, timestamp):
    kind = command.feature_type if isinstance(command, SetFeatureProperties) else 'face' if isinstance(command, DeleteFaces) else 'text' if isinstance(command, DeleteText) else 'line'
    statuses = ('active', 'isolated') if kind == 'line' else ('active',)
    selected = []
    # Validate the entire selection before building any changes. Identity lookup also
    # prevents unknown, cross-project, and cross-asset targets from being ignored.
    for identity in command.feature_ids:
        row = connection.execute('SELECT feature_id,project_id,asset_id,feature_type,lifecycle_status FROM feature WHERE feature_id=?', (identity,)).fetchone()
        if row is None or row['project_id'] != project_id or row['asset_id'] != command.asset_id:
            raise CommandConflict('RESOURCE_NOT_FOUND')
        if row['feature_type'] != kind or row['lifecycle_status'] not in statuses:
            raise CommandConflict('GEOMETRY_VALIDATION_FAILED', {'reason': 'Feature category or lifecycle does not match command'})
        selected.append(load_feature(connection, identity))
    changes = []
    for old in selected:
        new = {**old, 'revision': command.base_revision + 1, 'updated_at': timestamp}
        if isinstance(command, (DeleteFaces, DeleteLines, DeleteText)):
            new['lifecycle_status'] = 'deleted'
        else:
            if 'color' in command.model_fields_set:
                new['fill_color' if kind == 'face' else 'stroke_color'] = command.color
            for field in ('stroke_width_px', 'line_role'):
                if field in command.model_fields_set:
                    new[field] = getattr(command, field)
        changes.append((old, new))
    return changes

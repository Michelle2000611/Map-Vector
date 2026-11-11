"""Explicit schema updates. Revision is stored as data, never in table names."""


def migrate(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS text_residue_decision (
        project_id TEXT NOT NULL, asset_id TEXT NOT NULL, text_feature_id TEXT NOT NULL,
        line_feature_id TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('keep','reopen')), updated_at TEXT NOT NULL,
        preview_id TEXT NOT NULL, PRIMARY KEY(project_id,asset_id,text_feature_id,line_feature_id),
        FOREIGN KEY(project_id,asset_id) REFERENCES asset(project_id,asset_id),
        FOREIGN KEY(text_feature_id) REFERENCES text_attribute(feature_id),
        FOREIGN KEY(line_feature_id) REFERENCES line_attribute(feature_id))""")
    connection.execute('CREATE TABLE IF NOT EXISTS storage_migration (migration_id TEXT PRIMARY KEY,applied_at TEXT NOT NULL)')
    connection.execute("INSERT OR IGNORE INTO storage_migration VALUES ('background_export',strftime('%Y-%m-%dT%H:%M:%fZ','now'))")
    connection.execute('CREATE VIRTUAL TABLE IF NOT EXISTS text_display_index USING rtree(id,min_x,max_x,min_y,max_y)')
    connection.execute('CREATE TABLE IF NOT EXISTS schema_history (schema_revision TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS run_adoption_request (project_id TEXT NOT NULL REFERENCES project(project_id), idempotency_key TEXT NOT NULL, request_sha256 TEXT NOT NULL, result_summary TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(project_id,idempotency_key))')
    connection.execute("""CREATE TABLE IF NOT EXISTS line_check_decision (
        project_id TEXT NOT NULL, asset_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
        evidence_sha256 TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('keep','reopen')),
        updated_at TEXT NOT NULL, preview_id TEXT NOT NULL,
        PRIMARY KEY(project_id,asset_id,candidate_id),
        FOREIGN KEY(project_id,asset_id) REFERENCES asset(project_id,asset_id))""")
    columns={row[1] for row in connection.execute('PRAGMA table_info(project)')}
    if 'workflow_stage' not in columns:connection.execute('ALTER TABLE project ADD COLUMN workflow_stage INTEGER NOT NULL DEFAULT 0 CHECK(workflow_stage BETWEEN 0 AND 5)')
    if not connection.execute("SELECT 1 FROM storage_migration WHERE migration_id='text_review_before_edit'").fetchone():
        connection.execute('UPDATE project SET workflow_stage=3 WHERE workflow_stage=2')
        connection.execute("INSERT INTO storage_migration VALUES ('text_review_before_edit',strftime('%Y-%m-%dT%H:%M:%fZ','now'))")
    if 'schema_revision' not in columns:connection.execute("ALTER TABLE project ADD COLUMN schema_revision TEXT NOT NULL DEFAULT '1.0'")
    if 'export_policy_id' not in columns:connection.execute("ALTER TABLE project ADD COLUMN export_policy_id TEXT NOT NULL DEFAULT 'baseline_compatible'")
    for table,old,new in [('source_file','display_name','source_file_name'),('source_file','sha256','source_sha256'),('style','name','style_name')]:
        fields={row[1] for row in connection.execute('PRAGMA table_info('+table+')')}
        if old in fields and new not in fields:connection.execute('ALTER TABLE '+table+' RENAME COLUMN '+old+' TO '+new)
    run_fields={row[1] for row in connection.execute('PRAGMA table_info(run)')}
    columns={
        'created_at':"TEXT",
        'input_region_px':"TEXT",
        'local_to_asset_affine':"TEXT",
        'base_revision':"INTEGER NOT NULL DEFAULT 0",
        'worker_pid':"INTEGER",
        'worker_owner_id':"TEXT",
        'adopted_operation_id':"TEXT",
    }
    for name,declaration in columns.items():
        if name not in run_fields:connection.execute('ALTER TABLE run ADD COLUMN '+name+' '+declaration)
    export_fields={row[1] for row in connection.execute('PRAGMA table_info(export)')}
    for name,declaration in {'layer_types':"TEXT NOT NULL DEFAULT '[]'",'roi_revision':'INTEGER','payload_snapshot':'TEXT','stage_name':'TEXT','started_at':'TEXT','heartbeat_at':'TEXT','elapsed_ms':'INTEGER NOT NULL DEFAULT 0','worker_pid':'INTEGER','worker_owner_id':'TEXT','cancel_requested':'INTEGER NOT NULL DEFAULT 0','error_code':'TEXT','error_detail':'TEXT'}.items():
        if name not in export_fields:connection.execute('ALTER TABLE export ADD COLUMN '+name+' '+declaration)
    text_fields={row[1] for row in connection.execute('PRAGMA table_info(text_attribute)')}
    for name,declaration in {'layout_width_px':'REAL','layout_height_px':'REAL','baseline_offset_px':'REAL','layout_basis':"TEXT NOT NULL DEFAULT 'legacy_estimate'",'layout_runs':"TEXT NOT NULL DEFAULT '[]'"}.items():
        if name not in text_fields:connection.execute('ALTER TABLE text_attribute ADD COLUMN '+name+' '+declaration)
    connection.execute('CREATE INDEX IF NOT EXISTS feature_scope ON feature(project_id,asset_id,lifecycle_status,feature_id)')
    connection.execute('CREATE INDEX IF NOT EXISTS run_scope ON run(project_id,asset_id,run_status)')
    connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS group_feature_membership ON group_member(feature_id)')
    for kind in ('face','line','text'):
        table=kind+'_attribute'
        for action in ('INSERT','UPDATE'):
            trigger=table+'_'+action.lower()+'_type'
            connection.execute("CREATE TRIGGER IF NOT EXISTS "+trigger+" BEFORE "+action+" ON "+table+" WHEN (SELECT feature_type FROM feature WHERE feature_id=NEW.feature_id)!='"+kind+"' BEGIN SELECT RAISE(ABORT,'Specialized attribute type mismatch'); END")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS group_member_asset_type BEFORE INSERT ON group_member
        WHEN NOT EXISTS (SELECT 1 FROM logical_group g JOIN feature f ON f.feature_id=NEW.feature_id
        WHERE g.group_id=NEW.group_id AND g.project_id=f.project_id AND g.asset_id=f.asset_id AND g.feature_type=f.feature_type)
        BEGIN SELECT RAISE(ABORT,'Group member asset or type mismatch'); END""")
    connection.execute("""CREATE TRIGGER IF NOT EXISTS feature_style_scope BEFORE UPDATE OF style_id ON feature
        WHEN NEW.style_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM style s WHERE s.style_id=NEW.style_id AND s.project_id=NEW.project_id AND s.feature_type=NEW.feature_type)
        BEGIN SELECT RAISE(ABORT,'Feature style scope mismatch'); END""")
    connection.execute("INSERT INTO schema_history VALUES ('1.0',strftime('%Y-%m-%dT%H:%M:%fZ','now')) ON CONFLICT(schema_revision) DO NOTHING")
    enforce_contract(connection)
    if not connection.execute("SELECT 1 FROM storage_migration WHERE migration_id='text_display_index'").fetchone():
        connection.execute('DELETE FROM text_display_index')
        connection.execute("""INSERT INTO text_display_index SELECT f.rowid,
        json_extract(t.display_bbox_px,'$[0]'),json_extract(t.display_bbox_px,'$[2]'),json_extract(t.display_bbox_px,'$[1]'),json_extract(t.display_bbox_px,'$[3]')
        FROM feature f JOIN text_attribute t USING(feature_id) WHERE f.lifecycle_status='active' AND t.display_bbox_px IS NOT NULL""")
        connection.execute("INSERT INTO storage_migration VALUES ('text_display_index',strftime('%Y-%m-%dT%H:%M:%fZ','now'))")
    from mapvector.infrastructure.repositories.text_ocr_index import migrate as migrate_text_ocr_index
    migrate_text_ocr_index(connection)


def enforce_contract(connection):
    # Scope checks also protect stores created before composite foreign keys existed.
    rules={
        'run_asset':('run',"NOT EXISTS (SELECT 1 FROM asset a WHERE a.project_id=NEW.project_id AND a.asset_id=NEW.asset_id)"),
        'artifact_run':('artifact',"NOT EXISTS (SELECT 1 FROM run r WHERE r.project_id=NEW.project_id AND r.run_id=NEW.run_id)"),
        'event_run':('job_event',"NOT EXISTS (SELECT 1 FROM run r WHERE r.run_id=NEW.run_id)"),
        'roi_asset':('roi',"NOT EXISTS (SELECT 1 FROM asset a WHERE a.project_id=NEW.project_id AND a.asset_id=NEW.asset_id)"),
        'layer_asset':('layer_setting',"NOT EXISTS (SELECT 1 FROM asset a WHERE a.project_id=NEW.project_id AND a.asset_id=NEW.asset_id)"),
        'preview_asset':('edit_preview',"NOT EXISTS (SELECT 1 FROM asset a WHERE a.project_id=NEW.project_id AND a.asset_id=NEW.asset_id)"),
        'feature_run':('feature',"NEW.origin_run_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM run r WHERE r.project_id=NEW.project_id AND r.asset_id=NEW.asset_id AND r.run_id=NEW.origin_run_id)"),
        'candidate_run':('ocr_candidate',"NEW.run_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM run r WHERE r.project_id=NEW.project_id AND r.asset_id=NEW.asset_id AND r.run_id=NEW.run_id)"),
        'candidate_text':('ocr_candidate',"NEW.text_feature_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM feature f WHERE f.project_id=NEW.project_id AND f.asset_id=NEW.asset_id AND f.feature_id=NEW.text_feature_id AND f.feature_type='text')"),
        'text_candidate':('text_attribute',"NEW.primary_candidate_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ocr_candidate c JOIN feature f ON f.feature_id=NEW.feature_id WHERE c.candidate_id=NEW.primary_candidate_id AND c.project_id=f.project_id AND c.asset_id=f.asset_id)"),
        'line_text':('line_attribute',"NEW.associated_text_feature_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM feature f JOIN feature t ON t.feature_id=NEW.associated_text_feature_id WHERE f.feature_id=NEW.feature_id AND t.feature_type='text' AND f.project_id=t.project_id AND f.asset_id=t.asset_id)"),
        'feature_style_insert':('feature',"NEW.style_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM style s WHERE s.style_id=NEW.style_id AND s.project_id=NEW.project_id AND s.feature_type=NEW.feature_type)"),
        'review_text':('review',"NOT EXISTS (SELECT 1 FROM feature f WHERE f.feature_id=NEW.text_feature_id AND f.project_id=NEW.project_id AND f.feature_type='text')"),
        'export_snapshot':('export',"NOT EXISTS (SELECT 1 FROM snapshot s WHERE s.snapshot_id=NEW.snapshot_id AND s.project_id=NEW.project_id AND s.asset_id=NEW.asset_id)"),
        'lineage_scope':('feature_lineage',"NOT EXISTS (SELECT 1 FROM feature s JOIN feature t ON t.feature_id=NEW.target_feature_id WHERE s.feature_id=NEW.source_feature_id AND s.project_id=t.project_id AND s.asset_id=t.asset_id)"),
        'style_binding':('feature_style',"NOT EXISTS (SELECT 1 FROM feature f JOIN style s ON s.style_id=NEW.style_id WHERE f.feature_id=NEW.feature_id AND f.project_id=s.project_id AND f.feature_type=s.feature_type)"),
        'layer_values':('layer_setting',"NEW.is_visible NOT IN (0,1) OR NEW.opacity<0 OR NEW.opacity>1"),
    }
    json_fields={
        'asset':{'normalization_config':'object','pixel_to_map_affine':'array'},
        'run':{'config_snapshot':'object','plugin_manifest':'object','input_region_px':'array','local_to_asset_affine':'array'},
        'text_attribute':{'review_reason_codes':'array','display_bbox_px':'array'},
        'ocr_candidate':{'rule_suggestions':'array','detected_quad_px':'array'},
        'style':{'dash_pattern_px':'array'},
        'operation':{'result_summary':'object'},
        'export':{'policy_snapshot':'object','readback_report':'object','layer_types':'array'},
        'edit_preview':{'request_json':'object','result_json':'object'},
    }
    for table,fields in json_fields.items():
        for name,kind in fields.items():
            rules[table+'_'+name+'_json']=(table,"NEW."+name+" IS NOT NULL AND CASE WHEN json_valid(NEW."+name+") THEN json_type(NEW."+name+")!='"+kind+"' ELSE 1 END")
    for name,(table,condition) in rules.items():
        for action in ('INSERT','UPDATE'):
            connection.execute('CREATE TRIGGER IF NOT EXISTS contract_'+name+'_'+action.lower()+' BEFORE '+action+' ON '+table+' WHEN '+condition+" BEGIN SELECT RAISE(ABORT,'Data contract violation: "+name+"'); END")
    for table in ('operation_change','review','feature_lineage'):
        for action in ('UPDATE','DELETE'):
            connection.execute('CREATE TRIGGER IF NOT EXISTS immutable_'+table+'_'+action.lower()+' BEFORE '+action+' ON '+table+" BEGIN SELECT RAISE(ABORT,'Audit evidence is immutable'); END")

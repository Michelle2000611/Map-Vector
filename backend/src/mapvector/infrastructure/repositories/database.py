from contextlib import contextmanager
import sqlite3
from pathlib import Path


SCHEMA = '''
CREATE TABLE IF NOT EXISTS project (project_id TEXT PRIMARY KEY, project_name TEXT NOT NULL, working_revision INTEGER NOT NULL CHECK(working_revision >= 0), current_asset_id TEXT, current_snapshot_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_file (source_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id), display_name TEXT NOT NULL, source_rel_path TEXT NOT NULL, sha256 TEXT NOT NULL CHECK(length(sha256)=64), byte_size INTEGER NOT NULL CHECK(byte_size>=0), page_count INTEGER NOT NULL CHECK(page_count>0), created_at TEXT NOT NULL, UNIQUE(project_id,source_id));
CREATE TABLE IF NOT EXISTS asset (asset_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id), source_id TEXT NOT NULL, raster_rel_path TEXT NOT NULL, raster_sha256 TEXT NOT NULL CHECK(length(raster_sha256)=64), width_px INTEGER NOT NULL CHECK(width_px>0), height_px INTEGER NOT NULL CHECK(height_px>0), page_index INTEGER NOT NULL CHECK(page_index>=0), coordinate_mode TEXT NOT NULL CHECK(coordinate_mode IN ('pixel','georeferenced')), crs_wkt TEXT, pixel_to_map_affine TEXT, normalization_config TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,asset_id), FOREIGN KEY(project_id,source_id) REFERENCES source_file(project_id,source_id), CHECK((coordinate_mode='pixel' AND crs_wkt IS NULL AND pixel_to_map_affine IS NULL) OR (coordinate_mode='georeferenced' AND crs_wkt IS NOT NULL AND pixel_to_map_affine IS NOT NULL)));
CREATE TABLE IF NOT EXISTS feature (feature_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, asset_id TEXT NOT NULL, origin_run_id TEXT, feature_type TEXT NOT NULL CHECK(feature_type IN ('face','line','text')), geometry_type TEXT NOT NULL CHECK(geometry_type IN ('Point','LineString','Polygon','MultiPolygon')), geometry_wkb BLOB NOT NULL, bbox_min_x_px REAL NOT NULL, bbox_min_y_px REAL NOT NULL, bbox_max_x_px REAL NOT NULL, bbox_max_y_px REAL NOT NULL, lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN ('active','isolated','deleted','superseded')), source_type TEXT NOT NULL CHECK(source_type IN ('algorithm','manual','legacy_import','unknown')), style_id TEXT, revision INTEGER NOT NULL CHECK(revision>=0), created_at TEXT, updated_at TEXT NOT NULL, CHECK(bbox_max_x_px>=bbox_min_x_px AND bbox_max_y_px>=bbox_min_y_px), UNIQUE(project_id,asset_id,feature_id), FOREIGN KEY(project_id,asset_id) REFERENCES asset(project_id,asset_id), CHECK((feature_type='text' AND geometry_type='Point') OR (feature_type='line' AND geometry_type='LineString') OR (feature_type='face' AND geometry_type IN ('Polygon','MultiPolygon'))));
CREATE VIRTUAL TABLE IF NOT EXISTS feature_index USING rtree(id, min_x, max_x, min_y, max_y);
CREATE TABLE IF NOT EXISTS face_attribute (feature_id TEXT PRIMARY KEY REFERENCES feature(feature_id) ON DELETE CASCADE, fill_color TEXT NOT NULL, algorithm_label TEXT, color_class_id TEXT, area_px2 REAL NOT NULL, observed_area_px2 REAL, inferred_area_px2 REAL, coverage_status TEXT NOT NULL CHECK(coverage_status IN ('unchecked','valid','invalid')));
CREATE TABLE IF NOT EXISTS line_attribute (feature_id TEXT PRIMARY KEY REFERENCES feature(feature_id) ON DELETE CASCADE, stroke_color TEXT NOT NULL, stroke_width_px REAL NOT NULL CHECK(stroke_width_px>0), line_pattern TEXT NOT NULL, line_role TEXT NOT NULL, length_px REAL NOT NULL, draw_order INTEGER NOT NULL, isolation_reason TEXT, associated_text_feature_id TEXT);
CREATE TABLE IF NOT EXISTS text_attribute (feature_id TEXT PRIMARY KEY REFERENCES feature(feature_id) ON DELETE CASCADE, text_value TEXT NOT NULL, original_text TEXT, font_size_px REAL NOT NULL CHECK(font_size_px>0), rotation_deg REAL NOT NULL, text_color TEXT NOT NULL, text_anchor TEXT NOT NULL, text_content_revision INTEGER NOT NULL, review_status TEXT NOT NULL, review_reason_codes TEXT NOT NULL, reviewed_content_revision INTEGER, reviewed_at TEXT, reviewer_id TEXT, cleanup_status TEXT NOT NULL, display_bbox_px TEXT, primary_candidate_id TEXT, font_family TEXT NOT NULL, review_basis TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ocr_candidate (candidate_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, asset_id TEXT NOT NULL, run_id TEXT, text_feature_id TEXT, raw_text TEXT NOT NULL, suggested_text TEXT, score REAL CHECK(score IS NULL OR (score>=0 AND score<=1)), detected_quad_px TEXT, engine_id TEXT NOT NULL, model_id TEXT, rule_suggestions TEXT NOT NULL, candidate_status TEXT NOT NULL CHECK(candidate_status IN ('unreviewed','adopted','rejected')), created_at TEXT NOT NULL, FOREIGN KEY(project_id,asset_id) REFERENCES asset(project_id,asset_id), FOREIGN KEY(text_feature_id) REFERENCES text_attribute(feature_id));
CREATE TABLE IF NOT EXISTS operation (operation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id), operation_type TEXT NOT NULL, base_revision INTEGER NOT NULL, result_revision INTEGER NOT NULL, idempotency_key TEXT NOT NULL, request_sha256 TEXT NOT NULL, operation_status TEXT NOT NULL CHECK(operation_status IN ('applied','undone','abandoned')), actor_id TEXT NOT NULL, target_operation_id TEXT, result_summary TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(project_id,idempotency_key));
CREATE TABLE IF NOT EXISTS operation_change (change_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL REFERENCES operation(operation_id), entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, before_state TEXT, after_state TEXT, before_geometry_wkb BLOB, after_geometry_wkb BLOB, schema_revision TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feature_lineage (relation_id TEXT PRIMARY KEY, source_feature_id TEXT NOT NULL REFERENCES feature(feature_id), target_feature_id TEXT NOT NULL REFERENCES feature(feature_id), relation_type TEXT NOT NULL CHECK(relation_type IN ('merged_from','split_from','restored_from','converted_from')), operation_id TEXT REFERENCES operation(operation_id), source_attributes TEXT NOT NULL, import_id TEXT);
CREATE TABLE IF NOT EXISTS logical_group (group_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, asset_id TEXT NOT NULL, feature_type TEXT NOT NULL CHECK(feature_type IN ('face','line')), group_name TEXT, revision INTEGER NOT NULL, FOREIGN KEY(project_id,asset_id) REFERENCES asset(project_id,asset_id));
CREATE TABLE IF NOT EXISTS group_member (group_id TEXT NOT NULL REFERENCES logical_group(group_id) ON DELETE CASCADE, feature_id TEXT NOT NULL REFERENCES feature(feature_id), PRIMARY KEY(group_id,feature_id));
CREATE TABLE IF NOT EXISTS style (style_id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES project(project_id),feature_type TEXT NOT NULL,name TEXT NOT NULL,fill_color TEXT,stroke_color TEXT,stroke_width_px REAL,line_pattern TEXT,dash_pattern_px TEXT NOT NULL,tooth_spacing_px REAL,tooth_height_px REAL,tooth_side TEXT,revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS feature_style (feature_id TEXT PRIMARY KEY REFERENCES feature(feature_id),style_id TEXT NOT NULL REFERENCES style(style_id));
CREATE TABLE IF NOT EXISTS layer_setting (project_id TEXT NOT NULL,asset_id TEXT NOT NULL,layer_type TEXT NOT NULL,is_visible INTEGER NOT NULL,opacity REAL NOT NULL,default_style_id TEXT,PRIMARY KEY(project_id,asset_id,layer_type), FOREIGN KEY(project_id,asset_id) REFERENCES asset(project_id,asset_id), FOREIGN KEY(default_style_id) REFERENCES style(style_id));
CREATE TABLE IF NOT EXISTS roi (roi_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id), asset_id TEXT NOT NULL, geometry_wkb BLOB NOT NULL, revision INTEGER NOT NULL, FOREIGN KEY(project_id,asset_id) REFERENCES asset(project_id,asset_id));
CREATE TABLE IF NOT EXISTS review (review_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id), text_feature_id TEXT NOT NULL REFERENCES text_attribute(feature_id), text_content_revision INTEGER NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('confirm','skip')), reviewer_id TEXT NOT NULL, reviewed_at TEXT NOT NULL, text_sha256 TEXT NOT NULL, operation_id TEXT NOT NULL REFERENCES operation(operation_id));
CREATE TABLE IF NOT EXISTS snapshot (snapshot_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id), asset_id TEXT, snapshot_sequence INTEGER NOT NULL, working_revision INTEGER NOT NULL, snapshot_rel_path TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, snapshot_note TEXT, snapshot_status TEXT NOT NULL CHECK(snapshot_status IN ('prepared','files_ready','committed','failed')), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS export (export_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id), asset_id TEXT NOT NULL, snapshot_id TEXT NOT NULL REFERENCES snapshot(snapshot_id), export_format TEXT NOT NULL, export_mode TEXT NOT NULL, roi_id TEXT, scope_mode TEXT NOT NULL, coordinate_mode TEXT NOT NULL, policy_snapshot TEXT NOT NULL, export_status TEXT NOT NULL, output_rel_path TEXT, output_sha256 TEXT, readback_report TEXT, created_at TEXT NOT NULL, finished_at TEXT);
CREATE TABLE IF NOT EXISTS run (run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id), asset_id TEXT NOT NULL, input_raster_sha256 TEXT NOT NULL, pipeline_id TEXT NOT NULL, pipeline_revision TEXT NOT NULL, config_snapshot TEXT NOT NULL, plugin_manifest TEXT NOT NULL, run_status TEXT NOT NULL CHECK(run_status IN ('queued','starting','running','completed','completed_with_warnings','failed','cancelling','cancelled','interrupted')), progress_percent REAL, stage_name TEXT, heartbeat_at TEXT, retry_of_run_id TEXT, run_type TEXT NOT NULL, started_at TEXT, finished_at TEXT, result_revision INTEGER, error_code TEXT, error_detail TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)), UNIQUE(project_id,run_id), FOREIGN KEY(project_id,asset_id) REFERENCES asset(project_id,asset_id));
CREATE TABLE IF NOT EXISTS artifact (artifact_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES run(run_id), artifact_type TEXT NOT NULL, artifact_rel_path TEXT NOT NULL, sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL, schema_name TEXT NOT NULL, schema_revision TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(project_id,run_id) REFERENCES run(project_id,run_id));
CREATE TABLE IF NOT EXISTS job_event (run_id TEXT NOT NULL, event_id INTEGER NOT NULL, event_type TEXT NOT NULL, stage_name TEXT, event_data TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(run_id,event_id), FOREIGN KEY(run_id) REFERENCES run(run_id));
CREATE TABLE IF NOT EXISTS edit_preview (preview_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES project(project_id), asset_id TEXT NOT NULL, base_revision INTEGER NOT NULL, expires_at TEXT NOT NULL, request_json TEXT NOT NULL, result_json TEXT NOT NULL, input_sha256 TEXT NOT NULL, FOREIGN KEY(project_id,asset_id) REFERENCES asset(project_id,asset_id));
CREATE TABLE IF NOT EXISTS migration_import (import_id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES project(project_id),source_import_key TEXT NOT NULL UNIQUE,legacy_project_id TEXT NOT NULL,baseline_commit TEXT NOT NULL,mapping_revision TEXT NOT NULL,import_status TEXT NOT NULL,report_rel_path TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS migration_id_map (import_id TEXT NOT NULL REFERENCES migration_import(import_id),legacy_file_sha256 TEXT NOT NULL,legacy_layer_name TEXT NOT NULL,legacy_object_key TEXT NOT NULL,feature_id TEXT NOT NULL REFERENCES feature(feature_id),legacy_attributes TEXT NOT NULL,PRIMARY KEY(import_id,legacy_file_sha256,legacy_layer_name,legacy_object_key));
'''


class ProjectDatabase:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('BEGIN IMMEDIATE')
            yield connection
            feature_table=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feature'").fetchone()
            if feature_table:
                invalid=connection.execute("""SELECT f.feature_id FROM feature f
                    LEFT JOIN face_attribute a ON f.feature_id=a.feature_id
                    LEFT JOIN line_attribute l ON f.feature_id=l.feature_id
                    LEFT JOIN text_attribute t ON f.feature_id=t.feature_id
                    WHERE (f.feature_type='face' AND a.feature_id IS NULL)
                    OR (f.feature_type='line' AND l.feature_id IS NULL)
                    OR (f.feature_type='text' AND t.feature_id IS NULL)
                    OR ((a.feature_id IS NOT NULL)+(l.feature_id IS NOT NULL)+(t.feature_id IS NOT NULL))!=1 LIMIT 1""").fetchone()
                if invalid:raise sqlite3.IntegrityError('Feature must have exactly one matching attribute record: '+invalid[0])
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.transaction() as connection:
            connection.executescript(SCHEMA)
            from mapvector.infrastructure.repositories.migrations import migrate
            migrate(connection)

    @contextmanager
    def read(self):
        connection=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=10)
        connection.row_factory=sqlite3.Row
        try:
            connection.execute('PRAGMA foreign_keys=ON')
            yield connection
        finally:
            connection.close()

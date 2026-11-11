"""Indexed original OCR footprints, independent of later text display movement."""


def migrate(connection):
    connection.execute('CREATE VIRTUAL TABLE IF NOT EXISTS text_ocr_index USING rtree(id,min_x,max_x,min_y,max_y)')
    connection.execute('CREATE INDEX IF NOT EXISTS text_primary_candidate ON text_attribute(primary_candidate_id)')
    # CASE protects the index maintenance itself from malformed legacy JSON;
    # the existing storage-contract triggers still reject invalid new writes.
    coordinates="json_each(CASE WHEN json_valid(c.detected_quad_px) THEN c.detected_quad_px ELSE '[]' END)"
    bounds=','.join('(SELECT '+aggregate+'(json_extract(value,\'$['+axis+']\')) FROM '+coordinates+')' for axis,aggregate in [('0','min'),('0','max'),('1','min'),('1','max')])
    source="SELECT f.rowid,"+bounds+" FROM feature f JOIN text_attribute t USING(feature_id) JOIN ocr_candidate c ON c.candidate_id=t.primary_candidate_id AND c.project_id=f.project_id AND c.asset_id=f.asset_id WHERE f.lifecycle_status='active' AND c.detected_quad_px IS NOT NULL AND json_array_length(CASE WHEN json_valid(c.detected_quad_px) THEN c.detected_quad_px ELSE '[]' END)=4"
    # Footprints are updated even when a candidate quad or its text association
    # changes without a geometry write. No per-preview asset-wide OCR scan.
    for table,events,identity in [
        ('ocr_candidate',('INSERT','UPDATE'),"f.feature_id IN (SELECT feature_id FROM text_attribute WHERE primary_candidate_id=NEW.candidate_id)"),
        ('text_attribute',('INSERT','UPDATE'),"f.feature_id=NEW.feature_id"),
        ('feature',('UPDATE',),"f.feature_id=NEW.feature_id"),
    ]:
        for event in events:
            columns={'ocr_candidate':'detected_quad_px,candidate_id,project_id,asset_id','text_attribute':'primary_candidate_id,feature_id','feature':'lifecycle_status,feature_id,project_id,asset_id'}
            event_sql=event+' OF '+columns[table] if event=='UPDATE' else event
            connection.execute('CREATE TRIGGER IF NOT EXISTS text_ocr_'+table+'_'+event.lower()+' AFTER '+event_sql+' ON '+table+' BEGIN DELETE FROM text_ocr_index WHERE id IN (SELECT f.rowid FROM feature f WHERE '+identity+'); INSERT OR REPLACE INTO text_ocr_index '+source+' AND '+identity+'; END')
    connection.execute('CREATE TRIGGER IF NOT EXISTS text_ocr_feature_delete AFTER DELETE ON feature BEGIN DELETE FROM text_ocr_index WHERE id=OLD.rowid; END')
    connection.execute('CREATE TRIGGER IF NOT EXISTS text_ocr_text_delete AFTER DELETE ON text_attribute BEGIN DELETE FROM text_ocr_index WHERE id IN (SELECT rowid FROM feature WHERE feature_id=OLD.feature_id); END')
    if not connection.execute("SELECT 1 FROM storage_migration WHERE migration_id='text_ocr_index'").fetchone():
        connection.execute('DELETE FROM text_ocr_index')
        connection.execute('INSERT INTO text_ocr_index '+source)
        connection.execute("INSERT INTO storage_migration VALUES ('text_ocr_index',strftime('%Y-%m-%dT%H:%M:%fZ','now'))")

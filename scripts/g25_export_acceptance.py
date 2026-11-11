"""Read-only source / isolated-copy GIS acceptance for the 2026-11-09 G25 repair."""
import json
import sqlite3
import hashlib
from collections import Counter
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from mapvector.application.commands import CommandService
from mapvector.application.exports import text_released
from mapvector.infrastructure.storage.gis import clean_properties, validate_rows, write_gis


def full_acceptance(root, directory, database):
    """Export and download all real geometry from an isolated project, with one labelled boundary case."""
    import geopandas as gpd
    import pyogrio
    from fastapi.testclient import TestClient
    from shapely.geometry import shape
    from mapvector.api.app import create_app
    from mapvector.configuration.settings import Settings

    with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        project = dict(source.execute('SELECT * FROM project').fetchone())
        initial_dump = '\n'.join(source.iterdump())
        project_id = project['project_id']
        workspace = directory/'workspace'
        project_dir = workspace/'projects'/project_id
        copy_path = project_dir/'state/project.sqlite'
        copy_path.parent.mkdir(parents=True, exist_ok=False)
        with sqlite3.connect(copy_path) as target:
            source.backup(target)
    with sqlite3.connect(copy_path) as connection:
        identity = connection.execute("SELECT feature_id FROM feature WHERE feature_type='text' AND lifecycle_status='active' ORDER BY feature_id LIMIT 1").fetchone()[0]
        boundary_text = '中文地层Є𠀀🪨K₁⁴ ' * 40
        runs = [{'text': boundary_text, 'script': 'normal', 'font_size_px': 12.345, 'x_offset_px': -14.5,
                 'baseline_offset_px': 4.2, 'width_px': 32.1, 'source_index': 0, 'basis': 'g25_boundary_case', 'review_required': True}]
        connection.execute('UPDATE text_attribute SET text_value=?,original_text=?,layout_runs=? WHERE feature_id=?',
                           (boundary_text, boundary_text, json.dumps(runs, ensure_ascii=False), identity))
        connection.execute('UPDATE feature SET created_at=?,updated_at=? WHERE feature_id=?',
                           ('2026-11-09T09:05:10.123456+08:00', '2026-11-09T01:05:10.654321+00:00', identity))
    app = create_app(Settings(project_root=root, workspace_override=workspace))
    prefix = '/api/projects/'+project_id
    evidence = {'source_database_copy': str(database), 'project_id': project_id,
                'geopandas_version': gpd.__version__, 'pyogrio_version': pyogrio.__version__, 'gdal_version': pyogrio.__gdal_version__,
                'boundary_case_feature_id': identity, 'boundary_case_text_utf8_bytes': len(boundary_text.encode('utf-8')),
                'source_copy_dump_sha256': hashlib.sha256(initial_dump.encode('utf-8')).hexdigest(),
                'scenarios': {}}
    with TestClient(app) as client:
        response = client.post(prefix+'/snapshots', json={'base_revision': project['working_revision'], 'snapshot_note': 'G25 isolated real project + labelled Unicode boundary case'})
        assert response.status_code == 201, response.text
        snapshot = response.json()['data']
        evidence['snapshot_id'] = snapshot['snapshot_id']
        frozen = project_dir/snapshot['snapshot_rel_path']/'project.sqlite'
        with sqlite3.connect(frozen) as connection:
            connection.row_factory = sqlite3.Row
            features = [CommandService._feature(connection, row[0]) for row in connection.execute(
                "SELECT feature_id FROM feature WHERE asset_id=? AND lifecycle_status IN ('active','isolated')", (project['current_asset_id'],))]
            associations = {
                'styles': [dict(row) for row in connection.execute('SELECT * FROM style WHERE project_id=?', (project_id,))],
                'groups': [dict(row) for row in connection.execute('SELECT * FROM logical_group WHERE project_id=? AND asset_id=?', (project_id, project['current_asset_id']))],
                'group_members': [dict(row) for row in connection.execute('SELECT m.* FROM group_member m JOIN logical_group g USING(group_id) WHERE g.project_id=? AND g.asset_id=?', (project_id, project['current_asset_id']))],
                'lineage': [dict(row) for row in connection.execute('SELECT l.* FROM feature_lineage l JOIN feature f ON f.feature_id=l.target_feature_id WHERE f.project_id=? AND f.asset_id=?', (project_id, project['current_asset_id']))],
                'layers': [dict(row) for row in connection.execute('SELECT * FROM layer_setting WHERE project_id=? AND asset_id=?', (project_id, project['current_asset_id']))],
            }
        def layer_name(feature):
            if feature['feature_type'] == 'text':
                return 'text_confirmed' if text_released(feature, 'baseline_compatible') else 'text_unconfirmed'
            return 'isolated_line' if feature['feature_type'] == 'line' and feature['lifecycle_status'] == 'isolated' else feature['feature_type']
        grouped = {name: [f for f in features if layer_name(f) == name] for name in dict.fromkeys(map(layer_name, features))}
        evidence['feature_count'] = len(features)
        evidence['layer_counts'] = {name: len(selected) for name, selected in grouped.items()}
        print(json.dumps({'stage': 'snapshot_ready', 'count': len(features), 'layers': evidence['layer_counts']}), flush=True)
        for format_name in ('shp', 'gpkg'):
            response = client.post(prefix+'/exports', json={'snapshot_id': snapshot['snapshot_id'], 'export_format': format_name,
                'export_mode': 'draft', 'layer_types': list(grouped), 'scope_mode': 'full', 'roi_id': None, 'policy_id': 'baseline_compatible'})
            assert response.status_code == 201, response.text
            result = response.json()['data']
            response = client.get(prefix+'/exports/'+result['export_id']+'/download')
            assert response.status_code == 200, response.text
            content = response.content
            assert hashlib.sha256(content).hexdigest() == result['output_sha256']
            download_path = directory/('download.zip' if format_name == 'shp' else 'download.gpkg')
            download_path.write_bytes(content)
            compared = 0
            if format_name == 'shp':
                with ZipFile(BytesIO(content)) as archive:
                    assert archive.testzip() is None
                    original = json.loads(archive.read('property_manifest.json'))
                    assert original == json.loads(json.dumps(features, ensure_ascii=False))
                    schema = json.loads(archive.read('field_mapping.json'))
                    association_document = json.loads(archive.read('associations.json'))
                    assert association_document['project_id'] == project_id
                    assert association_document['snapshot_id'] == snapshot['snapshot_id']
                    assert association_document['policy_snapshot'] == result['policy_snapshot']
                    assert {key: association_document[key] for key in associations} == associations
                    archive.extractall(directory/'download-unpacked')
                for name, selected in grouped.items():
                    frame = gpd.read_file(directory/'download-unpacked/shapefile'/(name+'.shp'), engine='pyogrio').rename(columns={value:key for key,value in schema[name].items()})
                    expected = []
                    for feature in selected:
                        properties = {}
                        for key, value in clean_properties(feature).items():
                            text = '' if value is None else str(value)
                            text = text.encode('utf-8')[:250].decode('utf-8', errors='ignore').strip(' ')
                            properties[key] = text or None
                            compared += 1
                        expected.append((feature['feature_id'], shape(feature['geometry']), properties))
                    validate_rows(frame, expected, exact_text=True)
            else:
                for name, selected in grouped.items():
                    frame = gpd.read_file(download_path, layer=name, engine='pyogrio')
                    validate_rows(frame, [(f['feature_id'], shape(f['geometry']), clean_properties(f)) for f in selected])
                    compared += sum(len(clean_properties(f)) for f in selected)
                    if identity in set(frame['feature_id']):
                        boundary = frame.set_index('feature_id').loc[identity]
                        assert boundary['text_value'] == boundary_text
                        assert json.loads(boundary['layout_runs']) == runs
                        assert boundary['created_at'] == '2026-11-09T09:05:10.123456+08:00'
                        assert boundary['updated_at'] == '2026-11-09T01:05:10.654321+00:00'
                with sqlite3.connect(download_path) as connection:
                    embedded = {kind: json.loads(value) for kind, value in connection.execute('SELECT manifest_type,manifest FROM mapvector_manifest')}
                assert {key: embedded[key] for key in associations} == associations
                assert embedded['policy'] == result['policy_snapshot']
                assert embedded['source']['snapshot_id'] == snapshot['snapshot_id']
            compact = {'export_id': result['export_id'], 'download_http_status': response.status_code,
                       'content_type': response.headers['content-type'], 'download_path': str(download_path),
                       'sha256': result['output_sha256'], 'download_bytes': len(content), 'compared_attributes': compared,
                       'feature_count': result['readback_report']['feature_count'],
                       'attributes_match': result['readback_report']['attributes_match'],
                       'stored_attributes_match': result['readback_report']['stored_attributes_match'],
                       'full_properties_match': result['readback_report']['full_properties_match'],
                       'associations_match': result['readback_report']['associations_match'],
                       'loss_reasons': dict(Counter(loss['reason'] for loss in result['readback_report']['losses']))}
            evidence['scenarios'][format_name] = compact
            (directory/'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'stage': 'download_verified', 'format': format_name, **compact}), flush=True)
    with sqlite3.connect(database.as_uri()+'?mode=ro', uri=True) as source:
        assert '\n'.join(source.iterdump()) == initial_dump
    evidence['initial_source_copy_unchanged'] = True
    (directory/'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='runtime/n9-gis/real-red')
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    database = root / 'runtime/n9-gis/project/state/project.sqlite'
    if args.full:
        directory = root / args.output
        directory.mkdir(parents=True, exist_ok=True)
        full_acceptance(root, directory, database)
        return
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        features = [CommandService._feature(connection, row[0]) for row in connection.execute(
            "SELECT feature_id FROM feature WHERE feature_type='text' AND lifecycle_status='active'")]
        asset = dict(connection.execute('SELECT * FROM asset WHERE asset_id=(SELECT current_asset_id FROM project)').fetchone())
    directory = root / args.output
    directory.mkdir(parents=True, exist_ok=True)
    print(json.dumps({'real_text_count': len(features), 'with_runs': sum(bool(f['layout_runs']) for f in features)}))
    if args.inspect:
        import geopandas as gpd
        fields = sorted(clean_properties(features[0]))
        field = 'f' + str(fields.index('feature_id')).zfill(8)
        actual = gpd.read_file(directory/'shapefile/text_unconfirmed.shp', engine='pyogrio').set_index(field)
        mismatches = []
        for feature in features:
            for key, value in clean_properties(feature).items():
                if key == 'feature_id':
                    continue
                expected = '' if value is None else str(value)
                while len(expected.encode('utf-8')) > 250:
                    expected = expected[:-1]
                observed = actual.loc[feature['feature_id'], 'f' + str(fields.index(key)).zfill(8)]
                if expected and str(observed) != expected:
                    mismatches.append({'id': feature['feature_id'], 'key': key, 'expected': repr(expected), 'actual': repr(observed), 'actual_type': str(type(observed))})
        print(json.dumps(mismatches, ensure_ascii=False, indent=2))
        return
    output, report = write_gis(directory, features, asset, 'shp', lambda _: 'text_unconfirmed')
    print(json.dumps({'output': str(output), 'report': report}, ensure_ascii=False))


if __name__ == '__main__':
    main()

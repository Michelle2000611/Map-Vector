"""Read-only geometry checks with bounded, locatable issue details."""
import hashlib
import math

from shapely import STRtree, coverage_invalid_edges, coverage_is_valid, union_all
from shapely.geometry import GeometryCollection, shape

RULE_VERSION = 'delivery_checks_v1'
SCOPE_RULE_VERSION = 'delivery_scope_v1'
MAX_ISSUES = 200
MAX_PAIR_CHECKS = 10000


def _bounds(geometry):
    values = list(geometry.bounds)
    if len(values) != 4 or not all(math.isfinite(x) for x in values):
        return None
    if values[0] == values[2]:
        values[0] -= 0.5
        values[2] += 0.5
    if values[1] == values[3]:
        values[1] -= 0.5
        values[3] += 0.5
    return values


def inspect_geometry(features, region):
    tolerance = max(1e-6, region.area * 1e-12)
    geometries = [(feature, shape(feature['geometry'])) for feature in features]
    faces = [(feature, geometry) for feature, geometry in geometries if feature['feature_type'] == 'face']
    valid_faces = [(feature, geometry) for feature, geometry in faces if geometry.is_valid and not geometry.is_empty]
    issues = []
    issue_count = 0

    def add(code, severity, feature_ids, geometry, message, area=None):
        nonlocal issue_count
        issue_count += 1
        if len(issues) >= MAX_ISSUES:
            return
        ids = sorted(feature_ids)
        item = {'issue_id': hashlib.sha256((code + ':' + ':'.join(ids)).encode()).hexdigest()[:24],
                'code': code, 'severity': severity, 'feature_ids': ids,
                'bounds_px': _bounds(geometry), 'message': message}
        if area is not None:
            item['area_px2'] = area
        issues.append(item)

    for feature, geometry in geometries:
        if not geometry.is_valid or geometry.is_empty:
            add('INVALID_GEOMETRY', 'error', [feature['feature_id']], geometry, '对象几何无效，需要返回编辑核对。')

    shapes = [geometry for _, geometry in valid_faces]
    tree = STRtree(shapes)
    overlap_pairs = 0
    checked_pairs = 0
    check_complete = True
    for left, geometry in enumerate(shapes):
        for right in sorted(int(index) for index in tree.query(geometry, predicate='intersects') if index > left):
            if checked_pairs >= MAX_PAIR_CHECKS:
                check_complete = False
                break
            checked_pairs += 1
            overlap = geometry.intersection(shapes[right])
            if overlap.area > tolerance:
                overlap_pairs += 1
                add('FACE_OVERLAP', 'review', [valid_faces[left][0]['feature_id'], valid_faces[right][0]['feature_id']],
                    overlap, '两个面存在面积重叠，请对照原图核对。', overlap.area)
        if not check_complete:
            break
    valid_coverage = bool(coverage_is_valid(shapes)) if faces and check_complete else None
    if check_complete and len(valid_faces) != len(faces):
        valid_coverage = False
    if valid_coverage is False and not overlap_pairs and len(valid_faces) == len(faces):
        for (feature, _), edge in zip(valid_faces, coverage_invalid_edges(shapes)):
            if not edge.is_empty:
                add('FACE_BOUNDARY_MISMATCH', 'review', [feature['feature_id']], edge, '相邻面的公共边界不一致，请核对接边位置。')

    union = union_all(shapes) if shapes else GeometryCollection()
    invalid_count = sum(not geometry.is_valid or geometry.is_empty for _, geometry in geometries)
    return {'quality_report': {
        'target': 'full_asset_pixel_extent', 'target_area_px2': region.area,
        'face_count': len(faces), 'geometry_count': len(geometries),
        'valid_geometry_count': len(geometries) - invalid_count, 'invalid_geometry_count': invalid_count,
        'coverage_is_valid': valid_coverage, 'covered_area_px2': union.intersection(region).area,
        'uncovered_area_px2': region.difference(union).area,
        'overlap_area_px2': max(0.0, sum(g.area for g in shapes) - union.area),
        'recognition_accuracy': None, 'tolerance_px2': tolerance,
        'area_statistics_complete': len(valid_faces) == len(faces),
        'note': '仅检查几何规则；未覆盖区域不直接判为错误，真实孔洞和识别内容需要对照原图核对。'
    }, 'issues': issues, 'issue_count': issue_count, 'issues_truncated': issue_count > len(issues) or not check_complete,
       'check_complete': check_complete, 'issue_count_exact': check_complete, 'checked_pair_count': checked_pairs}

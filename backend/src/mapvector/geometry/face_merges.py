"""Exact face unions and conservative, explicitly selectable local gap patches.

No source precision reduction, geometry repair, hull filling, or hole filling is
performed. Discovery joins facing boundary segments only; a wide complement is
never treated as a gap merely because it lies inside an envelope.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np
from shapely import get_coordinates, normalize, union_all
from shapely.errors import ShapelyError
from shapely.affinity import translate
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import snap
from shapely.strtree import STRtree

ALGORITHM_REVISION = 'face_merge_modes_v1'
# A local connection must also be short along its boundary. This scales with
# the pixel-width parameter and never with absolute map coordinates or area.
_LOCAL_LENGTH_TO_GAP = 8.0


def _parts(geometry):
    if geometry.geom_type == 'Polygon':
        return [geometry] if not geometry.is_empty else []
    if geometry.geom_type in ('MultiPolygon', 'GeometryCollection'):
        return [part for child in geometry.geoms for part in _parts(child)]
    return []


def _edges(polygon):
    oriented = orient(polygon, sign=1)
    return [LineString([start, end])
            for ring in (oriented.exterior, *oriented.interiors)
            for start, end in zip(ring.coords, list(ring.coords)[1:])
            if start != end]


def _corridor(first, second, limit, epsilon):
    """A trapezoid inside the common projection of two facing segments.

    End width is bounded at both ends, hence everywhere along these straight
    boundaries. Intersections with source polygons produce the exact contact
    edges, including for arbitrary rotations and fractional coordinates.
    """
    first_coordinates = np.asarray(first.coords, dtype=float)[:, :2]
    origin = first_coordinates[0]
    a, b = first_coordinates - origin
    c, d = np.asarray(second.coords, dtype=float)[:, :2] - origin
    delta = b - a
    length = float(np.linalg.norm(delta))
    other_length = float(np.linalg.norm(d - c))
    tangent = delta / length
    other_tangent = (d - c) / other_length
    # Oriented boundaries have their polygon interior on their left.
    if float(np.dot(tangent, other_tangent)) > -0.5:
        return None
    outward = np.array([tangent[1], -tangent[0]])
    c_projection = float(np.dot(c - a, tangent))
    d_projection = float(np.dot(d - a, tangent))
    lower = max(0.0, min(c_projection, d_projection))
    upper = min(length, max(c_projection, d_projection))
    if upper - lower <= epsilon:
        return None

    def points(position):
        on_first = a + tangent * position
        on_second = c + (d - c) * ((position - c_projection) / (d_projection - c_projection))
        return on_first, on_second

    def width(position):
        on_first, on_second = points(position)
        return float(np.dot(on_second - on_first, outward))

    low_width, high_width = width(lower), width(upper)
    slope = (high_width - low_width) / (upper - lower)
    if abs(slope) > 1e-14:
        at_zero = lower - low_width / slope
        at_limit = lower + (limit - low_width) / slope
        lower = max(lower, min(at_zero, at_limit))
        upper = min(upper, max(at_zero, at_limit))
    elif low_width < -epsilon or low_width > limit + epsilon:
        return None
    if upper - lower <= epsilon:
        return None
    if upper - lower > limit * _LOCAL_LENGTH_TO_GAP:
        return None
    a0, b0 = points(lower)
    a1, b1 = points(upper)
    maximum_width = max(width(lower), width(upper))
    if maximum_width <= epsilon:
        return None
    # Tiny penetration into each source provides exact shared edges after
    # difference, avoiding floating point interpolation seams. Sources remain
    # untouched and no epsilon buffer is applied to their union.
    patch = Polygon([a0 - outward * epsilon, a1 - outward * epsilon,
                     b1 + outward * epsilon, b0 + outward * epsilon])
    if not patch.is_valid or patch.area <= epsilon * epsilon:
        return None
    return translate(patch, float(origin[0]), float(origin[1])), min(maximum_width, limit)


def analyze_geometry(features: list[dict], max_gap_px: float = 2.0,
                     max_added_area_px2: float = 150.0,
                     max_candidates: int = 2000) -> dict:
    """Classify an exact union and propose safe local positive-area connections.

    Membership, imagery, third-party ownership, and approval belong to the
    application layer. A proposal is never applied implicitly. Truncation
    concerns discovery only: the exact union always includes every input.
    """
    if not math.isfinite(max_gap_px) or max_gap_px <= 0:
        raise ValueError('连接口宽度上限必须为正有限数')
    if not math.isfinite(max_added_area_px2) or max_added_area_px2 <= 0:
        raise ValueError('连接口面积上限必须为正有限数')
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or max_candidates < 0:
        raise ValueError('候选数量上限必须为非负整数')
    if not features:
        raise ValueError('所选面不能为空')

    identifiers = []
    geometries = []
    for feature in features:
        identifier = str(feature.get('feature_id') or '')
        if not identifier or identifier in identifiers:
            raise ValueError('所选面身份不能为空或重复')
        try:
            geometry = shape(feature['geometry'])
        except (KeyError, TypeError, ValueError, ShapelyError) as exc:
            raise ValueError('所选面几何格式无效') from exc
        if (geometry.geom_type not in ('Polygon', 'MultiPolygon')
                or geometry.is_empty or not geometry.is_valid
                or not np.isfinite(get_coordinates(geometry)).all()):
            raise ValueError('所选面必须为非空、有限且有效的 Polygon 或 MultiPolygon')
        identifiers.append(identifier)
        geometries.append(geometry)

    source_tree = STRtree(geometries)
    for index, geometry in enumerate(geometries):
        for other in source_tree.query(geometry, predicate='intersects'):
            if int(other) > index and geometry.intersection(geometries[int(other)]).area > 0:
                raise ValueError('所选面存在正面积重叠冲突')

    exact_union = union_all(geometries)
    if not exact_union.is_valid or exact_union.geom_type not in ('Polygon', 'MultiPolygon'):
        raise ValueError('所选面的精确并集不是有效面')
    components = sorted(_parts(exact_union), key=lambda part: normalize(part).wkb)
    result = {
        'union_geometry': mapping(exact_union),
        'component_count': len(components),
        'hole_count': sum(len(part.interiors) for part in components),
        'single': exact_union.geom_type == 'Polygon',
        'multipart': exact_union.geom_type == 'MultiPolygon' and len(components) >= 2,
        'gap_candidates': [],
        'truncated': False,
    }
    if len(components) < 2:
        return result
    if max_candidates == 0:
        result['truncated'] = True
        return result

    extent = max(abs(value) for value in exact_union.bounds)
    epsilon = max_gap_px * 1e-10
    # World-coordinate precision is a validation constraint, never a licence
    # to enlarge the patch. Require the actual penetration guard to remain
    # representable after returning to world coordinates; a looser width-based
    # gate could silently lose all contact along a rotated boundary.
    if math.ulp(extent or 1.0) > epsilon:
        raise ValueError('坐标精度不足以可靠表达局部连接口，请先转换到局部坐标系')
    local_length_limit = max_gap_px * _LOCAL_LENGTH_TO_GAP
    component_ids = [hashlib.sha256(normalize(part).wkb).hexdigest() for part in components]
    component_tree = STRtree(components)
    boundary_cache = {}
    edge_tree_cache = {}
    work_remaining = max(2000, max_candidates * 32)
    seen = set()

    for first_index, first in enumerate(components):
        neighbors = sorted(int(index) for index in component_tree.query(first, predicate='dwithin', distance=max_gap_px)
                           if int(index) > first_index)
        for second_index in neighbors:
            if work_remaining <= 0:
                result['truncated'] = True
                return result
            if first_index not in boundary_cache:
                boundary_cache[first_index] = _edges(first)
            if second_index not in boundary_cache:
                boundary_cache[second_index] = _edges(components[second_index])
            first_edges = boundary_cache[first_index]
            second_edges = boundary_cache[second_index]
            if second_index not in edge_tree_cache:
                edge_tree_cache[second_index] = STRtree(second_edges)
            edge_tree = edge_tree_cache[second_index]
            strips = []
            maximum_width = 0.0
            exhausted = False
            for edge in first_edges:
                nearby = sorted(int(index) for index in edge_tree.query(edge, predicate='dwithin', distance=max_gap_px))
                for index in nearby:
                    if work_remaining <= 0:
                        exhausted = True
                        break
                    work_remaining -= 1
                    # Both projections are necessary: using the first edge's
                    # normal alone would depend on component sorting after a
                    # rotation when a curved boundary changes direction.
                    for start, end in ((edge, second_edges[index]), (second_edges[index], edge)):
                        corridor = _corridor(start, end, max_gap_px, epsilon)
                        if corridor:
                            strip, width = corridor
                            strips.append(strip)
                            maximum_width = max(maximum_width, width)
                if exhausted:
                    break
            if exhausted:
                result['truncated'] = True
                return result
            if not strips:
                continue
            # The exact difference preserves original source boundaries. It
            # cannot erase either existing holes or a newly enclosed wide area.
            # Penetrate at strip endpoints as well. Without this local guard,
            # roundoff at a rotated corner can leave a microscopic third edge
            # instead of sharing the original complete source edge.
            # Condition the overlay locally as well as the segment arithmetic.
            # The source union returned above remains the untouched exact union.
            origin_x, origin_y = first.bounds[:2]
            local_strips = union_all([translate(strip, -origin_x, -origin_y) for strip in strips])
            nearby_parts = component_tree.query(union_all(strips), predicate='dwithin', distance=epsilon * 16)
            contact_union = union_all([components[int(index)] for index in nearby_parts])
            local_union = translate(contact_union, -origin_x, -origin_y)
            discovered_local = local_strips.buffer(epsilon, join_style='mitre').difference(local_union)
            # Restore contact vertices from the original source after the
            # local-to-world round trip. Only candidate vertices move; the
            # exact source geometry and its precision remain unchanged.
            discovered = snap(translate(discovered_local, origin_x, origin_y),
                              contact_union, epsilon * 8).difference(contact_union)
            for patch in sorted(_parts(discovered), key=lambda part: normalize(part).wkb):
                if not patch.is_valid or patch.area <= epsilon * epsilon or patch.area > max_added_area_px2:
                    continue
                # Half the perimeter bounds the longitudinal arc, including
                # winding paths. Segmentation cannot bypass this complete-
                # patch check by joining individually short edge corridors.
                local_length = patch.length / 2
                if local_length > local_length_limit + epsilon * 100:
                    continue
                touched = []
                contact = 0.0
                for index in component_tree.query(patch, predicate='intersects'):
                    length = patch.boundary.intersection(components[int(index)].boundary).length
                    if length > epsilon:
                        touched.append(int(index))
                        contact += length
                if len(touched) < 2:
                    continue
                merged = union_all([patch, *[components[index] for index in touched]])
                if not merged.is_valid or len(_parts(merged)) >= len(touched):
                    continue
                owners = sorted(identifiers[int(index)] for index in source_tree.query(patch, predicate='intersects')
                                if patch.boundary.intersection(geometries[int(index)].boundary).length > epsilon)
                if not owners:
                    continue
                touched_component_ids = sorted(component_ids[index] for index in touched)
                digest = hashlib.sha256(json.dumps([owners, touched_component_ids], ensure_ascii=False).encode()
                                        + normalize(patch).wkb).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                if len(result['gap_candidates']) >= max_candidates:
                    result['truncated'] = True
                    return result
                result['gap_candidates'].append({
                    'candidate_id': digest,
                    'geometry': mapping(patch),
                    'feature_ids': owners,
                    'component_ids': touched_component_ids,
                    'width_px': maximum_width,
                    'local_length_px': float(local_length),
                    'area_px2': float(patch.area),
                    'contact_length_px': float(contact),
                })
    result['gap_candidates'].sort(key=lambda candidate: candidate['candidate_id'])
    return result

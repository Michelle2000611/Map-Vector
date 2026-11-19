"""Conservative, pure line diagnostics. Every proposed edit needs explicit review."""
import hashlib
import json
import math
from collections import defaultdict

import numpy as np
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, Polygon, box, shape


ALGORITHM_REVISION = 'line_check_review_v6'
MAX_CANDIDATES = 5000
MAX_ENDPOINT_NEIGHBORS = 100
MAX_RASTER_IMAGE_PIXELS = 32_000_000
MAX_RASTER_PATCH_PIXELS = 262_144
MAX_LOCAL_CONTEXT_LINES = 512


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _angle(first, second):
    return math.degrees(math.acos(float(np.clip(np.dot(first, second), -1, 1))))


def _end(geometry, side, stroke_width=1.):
    """Estimate direction over several stroke-relative spans, resisting tiny hooks."""
    point = np.asarray(geometry.coords[0 if side == 0 else -1], dtype=float)
    spans = sorted({min(max(2., stroke_width * scale), geometry.length / 2) for scale in (3., 5., 8.)})
    vectors = []
    for distance in spans:
        inner = geometry.interpolate(distance if side == 0 else geometry.length - distance)
        vector = point - np.asarray(inner.coords[0])
        norm = np.linalg.norm(vector)
        if norm > 1e-9:vectors.append(vector / norm)
    if not vectors:return point, np.zeros(2), {'scale_count':0, 'spread_deg':180.}
    # The median direction does not let the shortest sample dominate a noisy tip.
    tangent = np.median(vectors, axis=0)
    norm = float(np.linalg.norm(tangent))
    tangent = tangent / norm if norm > 1e-9 else vectors[-1]
    return point, tangent, {'scale_count':len(vectors), 'spread_deg':max(_angle(tangent, vector) for vector in vectors)}


def _smooth_connector(start, finish, first_tangent, second_tangent, stroke_width):
    """A small cubic bridge constrained to the gap corridor, with fixed endpoints."""
    gap = float(np.linalg.norm(finish - start))
    controls = [start, start + first_tangent * gap / 3, finish + second_tangent * gap / 3, finish]
    coordinates = []
    for fraction in np.linspace(0., 1., max(9, min(65, int(gap * 4) + 1))):
        a = 1 - fraction
        point = a ** 3 * controls[0] + 3 * a ** 2 * fraction * controls[1] + 3 * a * fraction ** 2 * controls[2] + fraction ** 3 * controls[3]
        coordinates.append(point.tolist())
    geometry = LineString(coordinates)
    corridor = LineString([start, finish]).buffer(max(stroke_width / 2, gap / 4))
    if not geometry.is_simple or geometry.length > gap * 1.3 or not corridor.covers(geometry):return None
    return coordinates


def _raster_evidence(connector, line, snapshot, pixels):
    """Measure color and local contrast along the *gap*, without a confidence claim."""
    source = snapshot.get('raster_source', {})
    base = {'status':'unavailable', 'source_sha256':source.get('sha256')}
    if source.get('status') == 'mismatch':return {**base, 'status':'source_mismatch'}
    if pixels is None:return base
    geometry = LineString(connector)
    width = max(.25, float(line['stroke_width_px']))
    # A local crop bounds memory independently of the overall scan dimensions.
    margin = width + 3.
    x0, y0, x1, y1 = geometry.bounds
    height, image_width = (pixels.height, pixels.width) if hasattr(pixels, 'crop') else pixels.shape[:2]
    if hasattr(pixels, 'crop') and height * image_width > MAX_RASTER_IMAGE_PIXELS:
        return {**base, 'unavailable_reason':'image_pixel_limit'}
    left, top = max(0, math.floor(x0 - margin)), max(0, math.floor(y0 - margin))
    right, bottom = min(image_width, math.ceil(x1 + margin) + 1), min(height, math.ceil(y1 + margin) + 1)
    if right <= left or bottom <= top:return {**base, 'status':'outside_raster'}
    if (right - left) * (bottom - top) > MAX_RASTER_PATCH_PIXELS:
        return {**base, 'unavailable_reason':'patch_pixel_limit'}
    try:
        patch = np.asarray(pixels.crop((left, top, right, bottom)).convert('RGB') if hasattr(pixels, 'crop') else pixels[top:bottom, left:right], dtype=np.float32)
        color = np.asarray([int(line['stroke_color'][start:start+2], 16) for start in (1, 3, 5)], dtype=float)
    except (OSError, TypeError, ValueError):return base
    if patch.ndim != 3 or patch.shape[2] < 3:return base
    def sample(points):
        points = np.rint(points).astype(int)
        valid = ((points[:,0] >= left) & (points[:,0] < right) & (points[:,1] >= top) & (points[:,1] < bottom))
        if not bool(np.all(valid)):return None
        return patch[points[:,1] - top, points[:,0] - left, :3]
    matches, contrasts = [], []
    distances = np.linspace(0., geometry.length, max(5, min(401, int(geometry.length * 4) + 1)))[1:-1]
    for distance in distances:
        point = np.asarray(geometry.interpolate(float(distance)).coords[0])
        before = np.asarray(geometry.interpolate(max(0., float(distance) - .25)).coords[0])
        after = np.asarray(geometry.interpolate(min(geometry.length, float(distance) + .25)).coords[0])
        direction = after - before
        norm = float(np.linalg.norm(direction))
        if norm <= 1e-9:continue
        normal = np.asarray([-direction[1], direction[0]]) / norm
        offsets = np.linspace(-width / 2, width / 2, max(3, min(21, int(width * 2) + 1)))
        center = sample(point + offsets[:,None] * normal)
        flank = sample(point + np.asarray([-(width + 2), width + 2])[:,None] * normal)
        if center is None or flank is None:return {**base, 'status':'outside_raster'}
        difference = np.max(np.abs(center - color), axis=1)
        best = int(np.argmin(difference))
        matches.append(bool(difference[best] <= 65))
        contrasts.append(float(np.max(np.abs(flank - center[best]), axis=1).mean()))
    if not matches:return base
    support = float(sum(matches) / len(matches))
    contrast = float(np.median(contrasts))
    longest = current = 0
    for match in matches:
        current = 0 if match else current + 1
        longest = max(longest, current)
    unsupported_run = float(longest * geometry.length / (len(matches) + 1))
    supported = support >= .75 and contrast >= 25 and unsupported_run <= max(1., width)
    status = 'supported' if supported else 'ambiguous' if support >= .75 and contrast < 25 else 'unsupported'
    return {**base, 'status':status, 'support_fraction':support, 'local_contrast':contrast, 'unsupported_run_px':unsupported_run}


def _joint_raster_evidence(connector, first, second, snapshot, pixels):
    """Raster support for a gap between two lines must not depend on which line the scan happened to visit first.

    Lines are ordered by random UUID, so measuring against only one of them made the same drawing pass or fail between
    runs whenever the two strokes differ in colour. Measure against each line and keep the better evidence."""
    rank = {'supported':3, 'ambiguous':2, 'unsupported':1}
    results = [_raster_evidence(connector, line, snapshot, pixels) for line in (first, second)]
    return max(results, key=lambda item:(rank.get(item['status'], 0), float(item.get('support_fraction', 0.)), item['status']))


def _crosses_third_line(connector, members, lines, geoms, geometry_tree, maximum_stroke):
    bridge = LineString(connector)
    connector_half_width = max(lines[index]['stroke_width_px'] for index in members) / 2
    footprint = bridge.buffer(connector_half_width, cap_style=2)
    neighbors = geometry_tree.query(bridge.buffer(connector_half_width + maximum_stroke / 2 + .5))
    return any(int(index) not in members and geoms[int(index)].buffer(lines[int(index)]['stroke_width_px'] / 2).intersects(footprint) for index in neighbors)


def _text_context(snapshot):
    regions=[]
    for text in snapshot['texts']:
        # Continuation protects the active rendered label. Moving/scaling may
        # retain its OCR layout basis, so the original detection is only a
        # fallback when current geometry is unavailable, never a ghost obstacle.
        for basis in ('layout_rectangle','display_bbox','detected_quad'):
            try:
                if basis=='layout_rectangle':
                    width,height=text.get('layout_width_px'),text.get('layout_height_px')
                    if not width or not height:continue
                    x,y=text['geometry']['coordinates']
                    region=rotate(box(x-width/2,y-height/2,x+width/2,y+height/2),
                                  -text.get('rotation_deg',0),origin=(x,y))
                else:
                    value=text.get('detected_quad_px' if basis=='detected_quad' else 'display_bbox_px')
                    region=(Polygon(value) if basis=='detected_quad' else box(*value)) if value else None
                if region is not None and region.is_valid and region.area>0:
                    regions.append((text,region,basis));break
            except (ValueError,TypeError):continue
    return regions,STRtree([region for _,region,_ in regions])


def _connector_text_conflicts(connectors,width,context):
    regions,tree=context;related={}
    for connector in connectors:
        footprint=LineString(connector).buffer(width/2,cap_style=2)
        if footprint.area<=0:continue
        for index in tree.query(footprint,predicate='intersects'):
            text,region,basis=regions[int(index)]
            area=footprint.intersection(region).area
            # Touching an OCR padding corner alone does not imply a conflict.
            # Ordinary text remains reviewable; a meaningful crossing of a
            # protected symbol blocks only automatic continuation.
            if area<=max(1e-9,min(width*width*.25,footprint.area*.1)):continue
            evidence={'feature_id':text['feature_id'],'geological_symbol':bool(text.get('geological_symbol')),
                      'region_basis':basis,'overlap_area_px2':area,
                      'connector_overlap_fraction':min(1.,area/footprint.area)}
            previous=related.get(text['feature_id'])
            if previous is None or area>previous['overlap_area_px2']:related[text['feature_id']]=evidence
    return [related[identity] for identity in sorted(related)]


def _edge_metrics(edge, geoms):
    metrics = {'gap_px':edge['gap'], 'angle_delta_deg':edge['angle'], 'gap_stroke_ratio':edge['gap_ratio'],
               'length_px':geoms[edge['a']].length + geoms[edge['b']].length,
               'tangent_scale_count':edge['scale_count'], 'tangent_spread_deg':edge['tangent_spread']}
    if 'support_fraction' in edge['raster']:metrics['raster_support_fraction'] = edge['raster']['support_fraction']
    return metrics


def _turning_sign(geometry, side):
    """Signed turning direction from the endpoint inward, or 0 if unassessable.

    Needs two interior segments near the endpoint; a single straight segment
    (most digitized strokes) has no local curvature and must not be judged.
    """
    coordinates = list(geometry.coords)
    if side != 0: coordinates = coordinates[::-1]
    if len(coordinates) < 3: return 0.
    a, b, c = (np.asarray(point, dtype=float) for point in coordinates[:3])
    first, second = b - a, c - b
    cross = float(first[0] * second[1] - first[1] * second[0])
    norms = np.linalg.norm(first) * np.linalg.norm(second)
    return 0. if norms <= 1e-9 or abs(cross) / norms < .05 else math.copysign(1., cross)


def _style_ids(line,snapshot):
    bound = snapshot.get('style_bindings',{}).get(line['feature_id'])
    style_ids={line.get('style_id'),bound} - {None}
    if not style_ids:style_ids.add(snapshot.get('default_style_id'))
    return style_ids - {None}


def _pattern(line, snapshot):
    patterns = {str(line.get('line_pattern', 'unknown')).lower()}
    for style_id in _style_ids(line,snapshot):
        style = snapshot['styles'].get(style_id)
        if style: patterns.add(str(style.get('line_pattern', 'unknown')).lower())
    return 'teeth' if 'teeth' in patterns else 'dashed' if patterns & {'dash', 'dashed'} else 'solid' if 'solid' in patterns else 'unknown'


def _compatible(first, second):
    return (first['stroke_color'].lower() == second['stroke_color'].lower()
            and math.isclose(first['stroke_width_px'],second['stroke_width_px'],rel_tol=0,abs_tol=1e-6)
            and first['line_role'] == second['line_role'] and first.get('style_id') == second.get('style_id')
            and first['line_pattern'] == second['line_pattern'])


def _components(indices, edges):
    adjacent = defaultdict(set)
    for edge in edges:
        a, b = edge['a'], edge['b']; adjacent[a].add(b); adjacent[b].add(a)
    seen = set(); result = []
    for start in sorted(indices):
        if start in seen: continue
        pending = [start]; component = set()
        while pending:
            current = pending.pop()
            if current in component: continue
            component.add(current); seen.add(current); pending.extend(adjacent[current] - component)
        result.append(sorted(component))
    return result


def _candidate(kind, members, lines, geoms, snapshot, connectors=None, metrics=None, reasons=None, blocked=None, texts=None, plan=None,
               connection_mode='automatic', connector_kind='straight', evidence=None, text_context=None):
    identities = sorted(lines[index]['feature_id'] for index in members)
    bounds = [min(geoms[index].bounds[0] for index in members), min(geoms[index].bounds[1] for index in members),
              max(geoms[index].bounds[2] for index in members), max(geoms[index].bounds[3] for index in members)]
    connectors = connectors or []
    for connector in connectors:
        for x, y in connector:
            bounds = [min(bounds[0], x), min(bounds[1], y), max(bounds[2], x), max(bounds[3], y)]
    asset = snapshot.get('asset', {})
    blocked = list(blocked or []);reasons=list(reasons or []);texts=list(texts or []);evidence=dict(evidence or {})
    if kind=='join_gap':
        conflicts=_connector_text_conflicts(connectors,max(lines[index]['stroke_width_px'] for index in members),
                                             text_context if text_context is not None else _text_context(snapshot))
        if conflicts:
            texts.extend(item['feature_id'] for item in conflicts)
            reasons.append('CONNECTOR_TEXT_OVERLAP');evidence['text_conflicts']=conflicts
            if any(item['geological_symbol'] for item in conflicts):
                reasons.append('CONNECTOR_GEOLOGICAL_SYMBOL')
                if connection_mode=='automatic':blocked.append('GEOLOGICAL_SYMBOL_TEXT_OVERLAP')
    if kind == 'join_gap' and asset and not (0 <= bounds[0] <= bounds[2] <= asset['width_px'] and 0 <= bounds[1] <= bounds[3] <= asset['height_px']):
        blocked.append('OUTSIDE_ASSET')
    normalized_connectors = sorted([min(segment, segment[::-1]) for segment in connectors])
    candidate = dict(candidate_id=digest([kind, identities, normalized_connectors, connection_mode])[:32], kind=kind,
                     feature_ids=identities, bounds_px=bounds, connectors=connectors, metrics=metrics or {},
                     reason_codes=sorted(set(reasons or [])), blocked_reasons=sorted(set(blocked or [])),
                     reference_text_ids=sorted(set(texts or [])), status='pending', review_required=True,
                     allowed_action={'join_gap':'join','text_stroke':'isolate','dash_group':'group'}[kind],
                     connection_mode=connection_mode, connector_kind=connector_kind, evidence=evidence or {})
    evidence = {'candidate': candidate, 'plan':plan or {}, 'lines': [lines[index] for index in members],
                'texts': [text for text in snapshot['texts'] if text['feature_id'] in candidate['reference_text_ids']],
                'groups': [group for group in snapshot['groups'] if set(group['feature_ids']) & set(identities)],
                'styles': {key: value for key, value in snapshot['styles'].items()
                           if any(key in _style_ids(lines[index],snapshot) for index in members)},
                'style_bindings': {identity:snapshot.get('style_bindings',{}).get(identity) for identity in identities},
                'raster_source':snapshot.get('raster_source'), 'algorithm_revision': ALGORITHM_REVISION}
    candidate['_evidence_sha256'] = digest(evidence)
    candidate['_plan'] = plan or {}
    # These explanations derive solely from inputs already covered by the
    # evidence digest. Keep their presentation out of decision identity so
    # richer diagnostics do not reopen an otherwise unchanged kept result.
    from mapvector.geometry.line_diagnostics import attribute_differences,self_intersection_locations
    if 'ATTRIBUTE_MISMATCH' in candidate['blocked_reasons']:
        selected=[lines[index] for index in members]
        candidate['evidence']['attribute_differences']=attribute_differences(
            selected,{item['feature_id']:_style_ids(item,snapshot) for item in selected})
    if 'SELF_INTERSECTION' in candidate['blocked_reasons']:
        candidate['evidence']['issue_locations']=self_intersection_locations(
            (plan or {}).get('coordinates'),bounds)
    return candidate


def _chain(members, edges, lines, geoms):
    adjacent = defaultdict(list)
    for edge in edges:
        adjacent[edge['a']].append(edge); adjacent[edge['b']].append(edge)
    terminals = [index for index in members if len(adjacent[index]) == 1]
    if len(terminals) != 2: return None
    current = min(terminals, key=lambda index: lines[index]['feature_id']); previous = None
    order = []; coordinates = []; connectors = []
    while True:
        order.append(lines[current]['feature_id'])
        remaining = [edge for edge in adjacent[current] if edge is not previous]
        outgoing = remaining[0] if remaining else None
        coords = [list(point) for point in geoms[current].coords]
        if previous is None:
            side = outgoing['sa'] if outgoing['a'] == current else outgoing['sb']
            if side == 0: coords.reverse()
        else:
            side = previous['sa'] if previous['a'] == current else previous['sb']
            if side == 1: coords.reverse()
            connector = previous['connector']
            if previous['b'] != current: connector = connector[::-1]
            connectors.append(connector)
            coordinates.extend(connector[1:-1])
        coordinates.extend(coords)
        if outgoing is None: break
        previous = outgoing; current = outgoing['b'] if outgoing['a'] == current else outgoing['a']
        if len(order) > len(members): return None
    return {'ordered_feature_ids': order, 'coordinates': coordinates}, connectors


def _local_dash_context(selected,request,lines,geoms,snapshot,geometry_tree,maximum_stroke):
    """Two endpoint hops cover every three-dash run containing a selection.

    Only short matching neighboring strokes need tangent checks. Full geometry
    stays in the obstacle tree; no unrelated gap is sampled from the raster.
    Dense neighborhoods are explicitly uncertain rather than silently ignored.
    """
    local=set(selected);frontier=set(selected);dense=False
    for _ in range(2):
        following=set()
        for index in sorted(frontier):
            if geoms[index].length>request.max_short_length_px:continue
            for point in (Point(geoms[index].coords[0]),Point(geoms[index].coords[-1])):
                nearby=[]
                for hit in geometry_tree.query(point.buffer(max(request.max_gap_px,1e-9))):
                    other=int(hit)
                    if other==index or geoms[other].length>request.max_short_length_px:continue
                    count=sum(point.distance(Point(endpoint))<=request.max_gap_px
                              for endpoint in (geoms[other].coords[0],geoms[other].coords[-1]))
                    if count:nearby.extend([other]*count)
                    if len(nearby)>MAX_ENDPOINT_NEIGHBORS:break
                if len(nearby)>MAX_ENDPOINT_NEIGHBORS:
                    dense=True;continue
                following.update(nearby)
        following-=local
        if len(local|following)>MAX_LOCAL_CONTEXT_LINES:
            dense=True;break
        local.update(following);frontier=following
        if not frontier:break
    short=[index for index in sorted(local) if geoms[index].length<=request.max_short_length_px]
    points=[];owners=[];tangents=[]
    for index in short:
        for side in (0,1):
            point,tangent,_=_end(geoms[index],side,lines[index]['stroke_width_px'])
            points.append(point);owners.append(index);tangents.append(tangent)
    edges=[]
    if points:
        points=np.asarray(points);tree=cKDTree(points)
        for end,point in enumerate(points):
            for other in tree.query_ball_point(point,request.max_gap_px):
                a,b=owners[end],owners[other]
                if end>=other or a==b:continue
                delta=points[other]-point;gap=float(np.linalg.norm(delta))
                if gap<=1e-6:continue
                direction=delta/gap
                if max(_angle(tangents[end],direction),_angle(tangents[other],-direction))>45:continue
                if not _compatible(lines[a],lines[b]) or _style_ids(lines[a],snapshot)!=_style_ids(lines[b],snapshot):continue
                if _crosses_third_line([point.tolist(),points[other].tolist()],{a,b},lines,geoms,geometry_tree,maximum_stroke):continue
                edges.append({'a':a,'b':b,'gap':gap})
    touching=defaultdict(list)
    for edge in edges:
        touching[edge['a']].append(edge);touching[edge['b']].append(edge)
    dash_members=set()
    for adjacent in touching.values():
        for first_index,first in enumerate(adjacent):
            for second in adjacent[first_index+1:]:
                members={first['a'],first['b'],second['a'],second['b']}
                if len(members)!=3 or not members.intersection(selected):continue
                lengths=[geoms[index].length for index in members]
                if (max(lengths)<=min(lengths)*1.2
                    and max(first['gap'],second['gap'])<=min(first['gap'],second['gap'])*1.2
                    and all(geoms[index].length<=np.linalg.norm(np.asarray(geoms[index].coords[-1])-np.asarray(geoms[index].coords[0]))*1.05 for index in members)):
                    dash_members.update(members)
    return dash_members,dense,len(local)


def _manual_candidate(snapshot, request, lines, geoms, patterns, dash_members, memberships, geometry_tree, maximum_stroke, pixels,text_context=None):
    """A chosen path authorizes just its two selected lines, with topology intact."""
    by_id = {line['feature_id']:index for index,line in enumerate(lines)}
    members = [by_id[identity] for identity in request.manual_feature_ids]
    supplied = request.manual_connector_px is not None
    connector = [list(point) for point in request.manual_connector_px] if supplied else None
    choices = []
    for a, b in (members, members[::-1]):
        for sa in (0, 1):
            for sb in (0, 1):
                start = np.asarray(geoms[a].coords[0 if sa == 0 else -1])
                finish = np.asarray(geoms[b].coords[0 if sb == 0 else -1])
                attachment = (float(np.linalg.norm(start - connector[0])) + float(np.linalg.norm(finish - connector[-1]))) if supplied else float(np.linalg.norm(finish - start))
                choices.append((attachment, lines[a]['feature_id'], lines[b]['feature_id'], sa, sb, a, b, start, finish))
    choices.sort(key=lambda choice:choice[:5])
    attachment, _, _, sa, sb, a, b, start, finish = choices[0]
    blocked = []
    if supplied:
        if np.linalg.norm(start - connector[0]) > .5 or np.linalg.norm(finish - connector[-1]) > .5:
            blocked.append('MANUAL_PATH_NOT_ATTACHED')
        else:
            connector[0], connector[-1] = start.tolist(), finish.tolist()
    else:
        connector = [start.tolist(), finish.tolist()]
        # Reversing the same endpoint pair is equivalent; distinct equally near
        # endpoint pairs require the operator to draw the intended attachment.
        tied = {tuple(sorted(((choice[5],choice[3]),(choice[6],choice[4])))) for choice in choices if abs(choice[0] - attachment) < 1e-6}
        if len(tied) > 1:blocked.append('AMBIGUOUS_ENDPOINT')
    # Collapse only consecutive duplicates; repeated nonadjacent points are
    # meaningful self intersection evidence and may never be normalized away.
    connector = [point for index,point in enumerate(connector) if index == 0 or point != connector[index - 1]]
    if len(connector) < 2:
        blocked.append('DEGENERATE_CONNECTOR')
        connector = [start.tolist(), finish.tolist()]
    first = [list(point) for point in geoms[a].coords]
    second = [list(point) for point in geoms[b].coords]
    if sa == 0:first.reverse()
    if sb == 1:second.reverse()
    coordinates = first + connector[1:-1] + second
    geometry = LineString(coordinates)
    bridge = LineString(connector)
    if not bridge.is_simple or not geometry.is_simple:blocked.append('SELF_INTERSECTION')
    if _crosses_third_line(connector, set(members), lines, geoms, geometry_tree, maximum_stroke):blocked.append('CROSSES_THIRD_LINE')
    if not _compatible(lines[a],lines[b]) or _style_ids(lines[a],snapshot) != _style_ids(lines[b],snapshot):blocked.append('ATTRIBUTE_MISMATCH')
    if any(patterns[index] in ('dashed','teeth') or index in dash_members for index in members):blocked.append('SEMANTIC_LINE_PATTERN')
    identities = set(request.manual_feature_ids)
    if any(not set(group['feature_ids']).issubset(identities) for identity in identities for group in memberships.get(identity, [])):
        blocked.append('EXISTING_GROUP_MEMBERSHIP')
    asset = snapshot.get('asset', {})
    if asset and not (0 <= geometry.bounds[0] <= geometry.bounds[2] <= asset['width_px'] and 0 <= geometry.bounds[1] <= geometry.bounds[3] <= asset['height_px']):
        blocked.append('OUTSIDE_ASSET')
    raster = _joint_raster_evidence(connector, lines[a], lines[b], snapshot, pixels)
    if raster['status'] == 'source_mismatch':blocked.append('RASTER_SOURCE_MISMATCH')
    plan = {'ordered_feature_ids':[lines[a]['feature_id'],lines[b]['feature_id']], 'coordinates':coordinates,
            'keep_feature_id':next((identity for identity in (lines[a]['feature_id'],lines[b]['feature_id']) if identity in memberships),lines[a]['feature_id']),
            'manual_authorization':{'mode':'manual','feature_ids':sorted(identities),'connector_sha256':digest([connector])}}
    stroke = min(lines[a]['stroke_width_px'], lines[b]['stroke_width_px'])
    reasons = ['EXPLICIT_MANUAL_CONTINUATION', 'MANUAL_PATH' if supplied else 'NEAREST_ENDPOINTS']
    if raster['status'] != 'supported':reasons.append('MANUAL_RASTER_REVIEW_REQUIRED')
    return _candidate('join_gap',members,lines,geoms,snapshot,[connector],
        {'gap_px':float(np.linalg.norm(finish - start)), 'gap_stroke_ratio':float(np.linalg.norm(finish - start)) / max(1e-6, stroke),
         'length_px':geometry.length, 'connector_length_px':bridge.length, 'attachment_distance_px':attachment},
        reasons,blocked,plan=plan,connection_mode='manual',connector_kind='manual' if supplied else 'straight',
        evidence={'raster':raster,'manual_feature_ids':sorted(identities),'endpoint_snap_tolerance_px':.5},text_context=text_context)


def _text_scan_coverage(snapshot):
    from mapvector.geometry.text_residue import text_residue_regions
    regions=text_residue_regions(snapshot['texts']);covered={item['text']['feature_id'] for item in regions}
    return {'scanned_text_count':len(snapshot['texts']),'text_source_region_count':len(covered),'texts_without_source_region_count':len(snapshot['texts'])-len(covered),'unadopted_ocr_region_count':len(snapshot.get('unassigned_ocr_candidates',[])),'uncertain_text_region_count':sum(item.get('uncertain',False) for item in regions)}


def diagnose(snapshot, request, pixels=None,*,candidate_limit=MAX_CANDIDATES):
    """All computation runs on materialized values and optional local raster pixels."""
    lines = snapshot['lines']; geoms = [shape(line['geometry']) for line in lines]
    if not lines: return {'candidates': [], 'summary': {'join_gap_count':0,'text_stroke_count':0,'dash_group_count':0,
        'scanned_line_count':0,'candidate_count':0,'returned_count':0,'truncated':False,'dense_endpoint_count':0,**_text_scan_coverage(snapshot)}}
    patterns = [_pattern(line, snapshot) for line in lines]
    geometry_tree=STRtree(geoms);maximum_stroke=max(line['stroke_width_px'] for line in lines)
    text_context=_text_context(snapshot)
    if getattr(request,'mode','automatic')=='manual':
        by_id={line['feature_id']:index for index,line in enumerate(lines)}
        selected={by_id[identity] for identity in request.manual_feature_ids}
        memberships=defaultdict(list)
        for group in snapshot['groups']:
            for identity in group['feature_ids']:memberships[identity].append(group)
        dash_members,dense,local_count=_local_dash_context(selected,request,lines,geoms,snapshot,geometry_tree,maximum_stroke)
        candidate=_manual_candidate(snapshot,request,lines,geoms,patterns,dash_members,memberships,
                                    geometry_tree,maximum_stroke,pixels,text_context)
        if dense:
            candidate['blocked_reasons']=sorted(set([*candidate['blocked_reasons'],'DENSE_ENDPOINT_REGION']))
            candidate['_evidence_sha256']=digest([candidate['_evidence_sha256'],'DENSE_ENDPOINT_REGION'])
        return {'candidates':[candidate],'summary':{'join_gap_count':1,'text_stroke_count':0,'dash_group_count':0,
            'scanned_line_count':len(selected),'context_line_count':local_count,'candidate_count':1,'returned_count':1,
            'truncated':False,'dense_endpoint_count':int(dense)}}
    points = []; tangents = []; turns = []; profiles = []
    for index, geometry in enumerate(geoms):
        for side in (0, 1):
            point, tangent, profile = _end(geometry, side, lines[index]['stroke_width_px'])
            points.append(point); tangents.append(tangent); profiles.append(profile)
            turns.append(_turning_sign(geometry, side))
    points = np.asarray(points); tree = cKDTree(points)
    edges = []; crowded = set()
    # Bound dense endpoint neighborhoods before constructing a potentially quadratic graph.
    for end, point in enumerate(points):
        count = tree.query_ball_point(point, request.max_gap_px, return_length=True)
        if count > MAX_ENDPOINT_NEIGHBORS: crowded.add(end); continue
        for other in tree.query_ball_point(point, request.max_gap_px, return_sorted=True):
            if end >= other or end // 2 == other // 2: continue
            a, b = end // 2, other // 2; delta = points[other] - point; gap = float(np.linalg.norm(delta))
            if gap <= 1e-6: continue
            direction = delta / gap
            angle = max(_angle(tangents[end], direction), _angle(tangents[other], -direction))
            if angle > max(45., request.angle_tolerance_deg): continue
            blocked = []
            if not _compatible(lines[a], lines[b]) or _style_ids(lines[a],snapshot)!=_style_ids(lines[b],snapshot): blocked.append('ATTRIBUTE_MISMATCH')
            # Local tangents can agree while the two strokes bend opposite ways;
            # only block when both ends actually have assessable curvature.
            signed_turn = float(np.cross(tangents[end], -tangents[other]))
            bridge_turn = 0 if abs(signed_turn) < .05 else math.copysign(1., signed_turn)
            if turns[end] and turns[other] and turns[end] != turns[other]:
                if not bridge_turn or -turns[end] != bridge_turn or turns[other] != bridge_turn:
                    blocked.append('DIVERGENT_CURVATURE')
            stroke = min(lines[a]['stroke_width_px'], lines[b]['stroke_width_px'])
            connector = [point.tolist(), points[other].tolist()]
            straight_raster = _joint_raster_evidence(connector, lines[a], lines[b], snapshot, pixels)
            raster = straight_raster
            connector_kind = 'straight'
            if angle > 8 and 'DIVERGENT_CURVATURE' not in blocked:
                smooth = _smooth_connector(point, points[other], tangents[end], tangents[other], stroke)
                if smooth is not None:
                    smooth_raster = _joint_raster_evidence(smooth, lines[a], lines[b], snapshot, pixels)
                    if smooth_raster['status'] == 'supported':
                        connector, connector_kind, raster = smooth, 'smooth', smooth_raster
            if angle > request.angle_tolerance_deg and connector_kind != 'smooth':blocked.append('ENDPOINT_DIRECTION_MISMATCH')
            if _crosses_third_line(connector, {a,b}, lines, geoms, geometry_tree, maximum_stroke):blocked.append('CROSSES_THIRD_LINE')
            edges.append({'a':a, 'b':b, 'sa':end%2, 'sb':other%2, 'gap':gap, 'angle':angle, 'blocked':blocked,
                          'gap_ratio':gap / max(1e-6, stroke), 'connector':connector, 'connector_kind':connector_kind, 'raster':raster,
                          'scale_count':min(profiles[end]['scale_count'],profiles[other]['scale_count']),
                          'tangent_spread':max(profiles[end]['spread_deg'], profiles[other]['spread_deg'])})
    compatible_edges = [edge for edge in edges if 'ATTRIBUTE_MISMATCH' not in edge['blocked']]
    # One end may not choose the nearest neighbor while hiding another viable branch.
    counts = defaultdict(int)
    for edge in compatible_edges:
        counts[(edge['a'],edge['sa'])] += 1; counts[(edge['b'],edge['sb'])] += 1
    for edge in edges:
        if counts[(edge['a'],edge['sa'])] > 1 or counts[(edge['b'],edge['sb'])] > 1: edge['blocked'].append('AMBIGUOUS_ENDPOINT')
    candidates = []; dash_members = set(); memberships = defaultdict(list)
    for group in snapshot['groups']:
        for identity in group['feature_ids']: memberships[identity].append(group)
    def group_protection(members):
        identities={lines[index]['feature_id'] for index in members}
        return ['EXISTING_GROUP_MEMBERSHIP'] if any(not set(group['feature_ids']).issubset(identities) for identity in identities for group in memberships.get(identity,[])) else []
    # Explicit dash pattern or >=3 near-equal short, regularly spaced segments.
    dash_edges = [edge for edge in edges if not edge['blocked'] and patterns[edge['a']] != 'teeth' and patterns[edge['b']] != 'teeth']
    explicit_edges=[edge for edge in dash_edges if patterns[edge['a']]==patterns[edge['b']]=='dashed']
    regular_edges=[];by_line=defaultdict(list)
    for edge in dash_edges:
        for index in (edge['a'],edge['b']):by_line[index].append(edge)
    # Find regular runs locally before ordinary chain construction. A long or
    # irregular neighbor must not demote an existing three-dash run to a gap.
    triples=[]
    for touching in by_line.values():
        for first_index,first in enumerate(touching):
            for second in touching[first_index+1:]:
                members={first['a'],first['b'],second['a'],second['b']}
                if len(members)!=3:continue
                lengths=[geoms[index].length for index in members]
                if (max(lengths)<=request.max_short_length_px and max(lengths)<=min(lengths)*1.2
                    and max(first['gap'],second['gap'])<=min(first['gap'],second['gap'])*1.2
                    and all(geoms[index].length<=np.linalg.norm(np.asarray(geoms[index].coords[-1])-np.asarray(geoms[index].coords[0]))*1.05 for index in members)):
                    if first not in regular_edges:regular_edges.append(first)
                    if second not in regular_edges:regular_edges.append(second)
                    triples.append(frozenset(members))
    # A line regularly fits more than one disjoint triple (e.g. a differently
    # spaced run on each side of a junction); do not let adjacency silently
    # fuse both into one group without flagging the conflicting membership.
    triples_by_line=defaultdict(set)
    for triple in triples:
        for index in triple:triples_by_line[index].add(triple)
    ambiguous_members=set()
    for index,owning in triples_by_line.items():
        if any(not (first&second) - {index} for first_index,first in enumerate(owning) for second in list(owning)[first_index+1:]):
            ambiguous_members.add(index)
    proposals=[]
    for selected,is_explicit in [(explicit_edges,True),(regular_edges,False)]:
        for members in _components({index for edge in selected for index in (edge['a'],edge['b'])},selected):
            if is_explicit or len(members)>=3:proposals.append((members,is_explicit,selected))
    for members,explicit,selected in proposals:
        within=[edge for edge in selected if edge['a'] in members and edge['b'] in members]
        lengths=[geoms[index].length for index in members];gaps=[edge['gap'] for edge in within]
        if set(members).issubset(dash_members):continue
        dash_members.update(members)
        blocked = []
        if not explicit and ambiguous_members & set(members): blocked.append('AMBIGUOUS_DASH_MEMBERSHIP')
        existing = [memberships.get(lines[index]['feature_id'],[]) for index in members]
        groups={group['group_id']:group for related in existing for group in related}
        identities={lines[index]['feature_id'] for index in members}
        already = any(len(group['feature_ids'])>1 and set(group['feature_ids'])==identities for group in groups.values())
        if already:blocked.append('ALREADY_GROUPED')
        elif any(len(group['feature_ids'])>1 for group in groups.values()):blocked.append('EXISTING_GROUP_MEMBERSHIP')
        if any(lines[index]['source_type'] == 'manual' for index in members): blocked.append('MANUAL_LINE')
        if any(lines[index]['line_role'] == 'split' for index in members): blocked.append('GEOLOGICAL_BOUNDARY')
        item = _candidate('dash_group', members, lines, geoms, snapshot,
                          metrics={'gap_px':max(gaps), 'length_px':sum(lengths), 'segment_count':len(members)},
                          reasons=['KNOWN_DASH_PATTERN' if explicit else 'REGULAR_SHORT_SEGMENTS'], blocked=blocked)
        if already: item['status'] = 'kept'
        candidates.append(item)
    join_edges = [edge for edge in edges if edge['a'] not in dash_members and edge['b'] not in dash_members
                  and patterns[edge['a']] not in ('dashed','teeth') and patterns[edge['b']] not in ('dashed','teeth')]
    for edge in join_edges:
        if any(end in crowded for end in (2*edge['a']+edge['sa'], 2*edge['b']+edge['sb'])):edge['blocked'].append('DENSE_ENDPOINT_REGION')
        if any(lines[index]['source_type'] == 'manual' for index in (edge['a'],edge['b'])):edge['blocked'].append('MANUAL_LINE')
        if any(lines[index]['line_role']=='split' for index in (edge['a'],edge['b'])):edge['blocked'].append('GEOLOGICAL_BOUNDARY')
        # Explicit contrary raster evidence blocks automatic continuation.
        # Short unknown/ambiguous gaps remain reviewable; longer or curved
        # extrapolations require actual original ink.
        if edge['raster']['status'] == 'source_mismatch':edge['blocked'].append('RASTER_SOURCE_MISMATCH')
        if edge['raster']['status'] == 'unsupported' or (edge['raster']['status'] != 'supported' and (edge['gap_ratio'] > 3 or edge['angle'] > 8)):
            edge['blocked'].append('RASTER_PATH_UNSUPPORTED')
        if edge['gap_ratio'] > 8:edge['blocked'].append('GAP_LARGE_RELATIVE_TO_STROKE')
    clear = [edge for edge in join_edges if not edge['blocked']]
    for members in _components({index for edge in clear for index in (edge['a'],edge['b'])}, clear):
        within = [edge for edge in clear if edge['a'] in members and edge['b'] in members]
        chain = _chain(members, within, lines, geoms)
        if chain:
            plan, connectors = chain
            plan['keep_feature_id']=next((identity for identity in plan['ordered_feature_ids'] if identity in memberships),plan['ordered_feature_ids'][0])
            geometry = LineString(plan['coordinates'])
            blocked = ([] if geometry.is_simple else ['SELF_INTERSECTION'])+group_protection(members)
            metrics = {'gap_px':max(edge['gap'] for edge in within), 'angle_delta_deg':max(edge['angle'] for edge in within),
                       'length_px':geometry.length, 'gap_stroke_ratio':max(edge['gap_ratio'] for edge in within),
                       'tangent_scale_count':min(edge['scale_count'] for edge in within),
                       'tangent_spread_deg':max(edge['tangent_spread'] for edge in within)}
            measured = [edge['raster']['support_fraction'] for edge in within if 'support_fraction' in edge['raster']]
            if measured:metrics['raster_support_fraction'] = min(measured)
            raster = next((edge['raster'] for edge in within if edge['raster']['status'] != 'supported'),within[0]['raster'])
            reasons = ['ALIGNED_ENDPOINT_GAP']
            if any(edge['raster']['status'] != 'supported' for edge in within):reasons.append('RASTER_EVIDENCE_UNAVAILABLE' if pixels is None else 'RASTER_PATH_REQUIRES_REVIEW')
            candidates.append(_candidate('join_gap', members, lines, geoms, snapshot, connectors,
                metrics,reasons,blocked,plan=plan,
                connector_kind='smooth' if any(edge['connector_kind']=='smooth' for edge in within) else 'straight',
                evidence={'raster':raster, 'gap_paths':[edge['raster'] for edge in within]},text_context=text_context))
        else:
            for edge in within:edge['blocked'].append('CYCLIC_CONNECTION')
            join_edges.extend(edge for edge in within if edge not in join_edges)
    for edge in join_edges:
        if not edge['blocked']: continue
        a,b=edge['a'],edge['b'];connector=edge['connector']
        reasons=['ALIGNED_ENDPOINT_GAP']
        if edge['raster']['status'] != 'supported':reasons.append('RASTER_EVIDENCE_UNAVAILABLE' if pixels is None else 'RASTER_PATH_REQUIRES_REVIEW')
        candidates.append(_candidate('join_gap',[a,b],lines,geoms,snapshot,[connector],
            _edge_metrics(edge,geoms),reasons,edge['blocked']+group_protection([a,b]),
            connector_kind=edge['connector_kind'], evidence={'raster':edge['raster']},text_context=text_context))
    from mapvector.geometry.text_residue import scan_text_strokes
    for item in scan_text_strokes(snapshot,request,pixels,lines,geoms,patterns,dash_members):
        candidates.append(_candidate('text_stroke',[item['index']],lines,geoms,snapshot,
            metrics=item['metrics'],reasons=['TEXT_STROKE_REGION'],blocked=item['blocked'],
            texts=item['texts'],evidence=item['evidence']))
    from mapvector.geometry.text_residue import scan_unassigned_strokes
    for item in scan_unassigned_strokes(snapshot,request,pixels,lines,geoms,patterns,dash_members):
        candidates.append(_candidate('text_stroke',item['members'],lines,geoms,snapshot,
            metrics=item['metrics'],reasons=item['reasons'],blocked=item['blocked'],texts=[],evidence=item['evidence']))
    unique={item['candidate_id']:item for item in candidates}; ordered=sorted(unique.values(),key=lambda item:(item['kind'],bool(item['blocked_reasons']),item['candidate_id']))
    summary={kind+'_count':sum(item['kind']==kind for item in ordered) for kind in ('join_gap','text_stroke','dash_group')}
    text_candidates=[item for item in ordered if item['kind']=='text_stroke']
    summary.update(**_text_scan_coverage(snapshot),text_referenced_line_count=len({fid for item in text_candidates if item['reference_text_ids'] for fid in item['feature_ids']}),text_edge_line_count=sum('TEXT_REGION_EDGE_REQUIRES_REVIEW' in item['blocked_reasons'] for item in text_candidates),text_complex_line_count=sum('COMPLEX_TEXT_STROKE_REQUIRES_REVIEW' in item['blocked_reasons'] for item in text_candidates))
    returned=ordered if candidate_limit is None else ordered[:candidate_limit]
    summary.update(unassigned_text_stroke_count=sum(item['kind']=='text_stroke' and item['evidence'].get('unassigned',False) for item in ordered),scanned_line_count=len(lines),candidate_count=len(ordered),returned_count=len(returned),
                   truncated=len(returned)<len(ordered),dense_endpoint_count=len(crowded))
    return {'candidates':returned,'summary':summary}

"""Conservative, pure line diagnostics. Every proposed edit needs explicit review."""
import hashlib
import json
import math
from collections import defaultdict

import numpy as np
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.geometry import LineString, Point, Polygon, box, shape


ALGORITHM_REVISION = 'line_check_review_v1'
MAX_CANDIDATES = 5000
MAX_ENDPOINT_NEIGHBORS = 100


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _angle(first, second):
    return math.degrees(math.acos(float(np.clip(np.dot(first, second), -1, 1))))


def _end(geometry, side):
    point = np.asarray(geometry.coords[0 if side == 0 else -1], dtype=float)
    distance = min(5., geometry.length / 2)
    inner = geometry.interpolate(distance if side == 0 else geometry.length - distance)
    vector = point - np.asarray(inner.coords[0])
    norm = np.linalg.norm(vector)
    return point, vector / norm if norm > 1e-9 else np.zeros(2)


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


def _candidate(kind, members, lines, geoms, snapshot, connectors=None, metrics=None, reasons=None, blocked=None, texts=None, plan=None):
    identities = sorted(lines[index]['feature_id'] for index in members)
    bounds = [min(geoms[index].bounds[0] for index in members), min(geoms[index].bounds[1] for index in members),
              max(geoms[index].bounds[2] for index in members), max(geoms[index].bounds[3] for index in members)]
    connectors = connectors or []
    normalized_connectors = sorted([sorted(segment) for segment in connectors])
    candidate = dict(candidate_id=digest([kind, identities, normalized_connectors])[:32], kind=kind,
                     feature_ids=identities, bounds_px=bounds, connectors=connectors, metrics=metrics or {},
                     reason_codes=sorted(set(reasons or [])), blocked_reasons=sorted(set(blocked or [])),
                     reference_text_ids=sorted(set(texts or [])), status='pending', review_required=True,
                     allowed_action={'join_gap':'join','text_stroke':'isolate','dash_group':'group'}[kind])
    evidence = {'candidate': candidate, 'lines': [lines[index] for index in members],
                'texts': [text for text in snapshot['texts'] if text['feature_id'] in candidate['reference_text_ids']],
                'groups': [group for group in snapshot['groups'] if set(group['feature_ids']) & set(identities)],
                'styles': {key: value for key, value in snapshot['styles'].items()
                           if any(key in _style_ids(lines[index],snapshot) for index in members)},
                'style_bindings': {identity:snapshot.get('style_bindings',{}).get(identity) for identity in identities},
                'algorithm_revision': ALGORITHM_REVISION}
    candidate['_evidence_sha256'] = digest(evidence)
    candidate['_plan'] = plan or {}
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
            connectors.append([coordinates[-1], coords[0]])
        coordinates.extend(coords)
        if outgoing is None: break
        previous = outgoing; current = outgoing['b'] if outgoing['a'] == current else outgoing['a']
        if len(order) > len(members): return None
    return {'ordered_feature_ids': order, 'coordinates': coordinates}, connectors


def diagnose(snapshot, request):
    """All computation runs on materialized values, with no database connection."""
    lines = snapshot['lines']; geoms = [shape(line['geometry']) for line in lines]
    if not lines: return {'candidates': [], 'summary': {'join_gap_count':0,'text_stroke_count':0,'dash_group_count':0,
        'scanned_line_count':0,'candidate_count':0,'returned_count':0,'truncated':False,'dense_endpoint_count':0}}
    patterns = [_pattern(line, snapshot) for line in lines]
    points = []; tangents = []
    for geometry in geoms:
        for side in (0, 1):
            point, tangent = _end(geometry, side); points.append(point); tangents.append(tangent)
    points = np.asarray(points); tree = cKDTree(points); geometry_tree = STRtree(geoms)
    edges = []; crowded = set()
    maximum_stroke = max(line['stroke_width_px'] for line in lines)
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
            if angle > request.angle_tolerance_deg: continue
            blocked = []
            if not _compatible(lines[a], lines[b]) or _style_ids(lines[a],snapshot)!=_style_ids(lines[b],snapshot): blocked.append('ATTRIBUTE_MISMATCH')
            connector = LineString([point, points[other]])
            neighbors = geometry_tree.query(connector.buffer(maximum_stroke / 2 + .5))
            if any(index not in (a,b) and geoms[index].buffer(lines[index]['stroke_width_px']/2).intersects(connector) for index in neighbors):
                blocked.append('CROSSES_THIRD_LINE')
            edges.append({'a':a, 'b':b, 'sa':end%2, 'sb':other%2, 'gap':gap, 'angle':angle, 'blocked':blocked})
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
    clear = [edge for edge in join_edges if not edge['blocked']]
    for members in _components({index for edge in clear for index in (edge['a'],edge['b'])}, clear):
        within = [edge for edge in clear if edge['a'] in members and edge['b'] in members]
        chain = _chain(members, within, lines, geoms)
        if chain:
            plan, connectors = chain
            plan['keep_feature_id']=next((identity for identity in plan['ordered_feature_ids'] if identity in memberships),plan['ordered_feature_ids'][0])
            geometry = LineString(plan['coordinates'])
            blocked = ([] if geometry.is_simple else ['SELF_INTERSECTION'])+group_protection(members)
            candidates.append(_candidate('join_gap', members, lines, geoms, snapshot, connectors,
                {'gap_px':max(edge['gap'] for edge in within), 'angle_delta_deg':max(edge['angle'] for edge in within), 'length_px':geometry.length},
                ['ALIGNED_ENDPOINT_GAP'],blocked,plan=plan))
        else:
            for edge in within:edge['blocked'].append('CYCLIC_CONNECTION')
            join_edges.extend(edge for edge in within if edge not in join_edges)
    for edge in join_edges:
        if not edge['blocked']: continue
        a,b=edge['a'],edge['b'];connector=[[float(value) for value in points[2*a+edge['sa']]], [float(value) for value in points[2*b+edge['sb']]]]
        candidates.append(_candidate('join_gap',[a,b],lines,geoms,snapshot,[connector],
            {'gap_px':edge['gap'],'angle_delta_deg':edge['angle'],'length_px':geoms[a].length+geoms[b].length},
            ['ALIGNED_ENDPOINT_GAP'],edge['blocked']+group_protection([a,b])))
    # Text regions are evidence only. No face or text geometry enters an edit plan.
    text_regions = []
    for text in snapshot['texts']:
        try:
            region = Polygon(text['detected_quad_px']) if text.get('detected_quad_px') else box(*text['display_bbox_px']) if text.get('display_bbox_px') else None
            if region is not None and region.is_valid and region.area > 0: text_regions.append((text,region))
        except (ValueError, TypeError): continue
    if text_regions:
        text_tree = STRtree([region for _,region in text_regions])
        for index,line in enumerate(lines):
            geometry=geoms[index]
            if geometry.length > request.max_short_length_px: continue
            references=[text_regions[int(i)] for i in text_tree.query(geometry,predicate='intersects')]
            if not references: continue
            blocked=[]
            if line['source_type']=='manual':blocked.append('MANUAL_LINE')
            if line['line_role']=='split':blocked.append('GEOLOGICAL_BOUNDARY')
            if patterns[index] in ('dashed','teeth') or index in dash_members:blocked.append('SEMANTIC_LINE_PATTERN')
            if any(text.get('geological_symbol') for text,_ in references):blocked.append('GEOLOGICAL_SYMBOL')
            if not any(region.buffer(-.25).covers(geometry) for _,region in references):blocked.append('CROSSES_TEXT_REGION')
            try:
                if max(int(line['stroke_color'][start:start+2],16) for start in (1,3,5))>=180:blocked.append('NON_TEXT_STROKE_COLOR')
            except (ValueError,TypeError):blocked.append('NON_TEXT_STROKE_COLOR')
            candidates.append(_candidate('text_stroke',[index],lines,geoms,snapshot,
                metrics={'length_px':geometry.length},reasons=['SHORT_LINE_IN_TEXT_REGION'],blocked=blocked,
                texts=[text['feature_id'] for text,_ in references]))
    unique={item['candidate_id']:item for item in candidates}; ordered=sorted(unique.values(),key=lambda item:(item['kind'],bool(item['blocked_reasons']),item['candidate_id']))
    summary={kind+'_count':sum(item['kind']==kind for item in ordered) for kind in ('join_gap','text_stroke','dash_group')}
    summary.update(scanned_line_count=len(lines),candidate_count=len(ordered),returned_count=min(len(ordered),MAX_CANDIDATES),
                   truncated=len(ordered)>MAX_CANDIDATES,dense_endpoint_count=len(crowded))
    return {'candidates':ordered[:MAX_CANDIDATES],'summary':summary}

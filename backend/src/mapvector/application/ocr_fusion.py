"""Merge spatial agreement without discarding competing engine readings."""
import copy
import hashlib
import json
import unicodedata
from shapely.geometry import Polygon
from shapely.strtree import STRtree
from mapvector.geometry.text_ink import _char


def normalized_text(value):
    # Canonical composition is safe; NFKC would collapse meaningful code glyphs.
    return unicodedata.normalize('NFC',str(value)).strip()


# Comparison-only confusable groups: narrow, common OCR mix-ups. Never used to
# rewrite stored text, only to decide whether two readings should be treated
# as the same observation for conflict/duplicate detection. Fullwidth/halfwidth
# digits and letters fold into their halfwidth form; 0/O and 1/l/I additionally
# fold together on top of that, so every member of a line shares one canonical
# glyph even though the groups overlap (digit '0' is in two of them).
_FOLD_FULLWIDTH = {chr(0xff10 + i): str(i) for i in range(10)} | {chr(0xff21 + i): chr(0x41 + i) for i in range(26)} | {chr(0xff41 + i): chr(0x61 + i) for i in range(26)}
_FOLD_GROUPS = {char: group[0] for group in ('0O', '1lI') for char in group}
_CONFUSABLE_CANONICAL = {char: _FOLD_GROUPS.get(halfwidth, halfwidth) for char, halfwidth in _FOLD_FULLWIDTH.items()}
_CONFUSABLE_CANONICAL.update(_FOLD_GROUPS)


def comparison_key(value):
    """Per-character (script, canonical_glyph) sequence for equivalence only.

    Subscript/superscript segments never collapse into normal text, or into
    each other, even when the underlying glyphs are confusable: a reading
    that disagrees only on script position is a different observation.
    """
    return tuple((_char(char)[1], _CONFUSABLE_CANONICAL.get(_char(char)[0], _char(char)[0])) for char in normalized_text(value))


def same_reading(left, right):
    return comparison_key(left) == comparison_key(right)


def overlap(left,right):
    """Actual quadrilateral IoU; slanted neighboring labels may share a bbox."""
    a,b=(Polygon(item['detected_quad_px']) for item in (left,right))
    if not a.is_valid or not b.is_valid or min(a.area,b.area)<=0:return 0.
    intersection=a.intersection(b).area
    union=a.area+b.area-intersection
    return intersection/union if union>0 else 0.


def same_location(left,right):
    if overlap(left,right)>=.5:return True
    # OCR padding differs across scales. A tightly centered nested box is
    # still the same observation, even when its IoU falls below one half.
    a,b=(Polygon(item['detected_quad_px']) for item in (left,right))
    if not a.is_valid or not b.is_valid or min(a.area,b.area)<=0:return False
    smaller=min(a.area,b.area);larger=max(a.area,b.area)
    return smaller/larger>=.25 and a.intersection(b).area/smaller>=.85 and a.centroid.distance(b.centroid)<=.3*smaller**.5


def _polygon(item):
    quad=item.get('detected_quad_px')
    if isinstance(quad,str):quad=json.loads(quad)
    if not quad:return None
    polygon=Polygon(quad)
    return polygon if polygon.is_valid and polygon.area>0 else None


def _spatial_relation(a,b):
    if a is None or b is None:return None
    intersection=a.intersection(b).area
    if intersection<=0:return None
    smaller,larger=sorted((a.area,b.area))
    covered=min(1.,intersection/smaller)
    iou=intersection/(a.area+b.area-intersection)
    # This is a review relation, not an identity test. A large OCR line may
    # contain several genuine labels. Touches and slight padding overlaps
    # alone do not justify withholding an independent neighboring label.
    if covered>=.85:relation='containment'
    elif covered>=.5 or covered>=.25 and iou>=.10:relation='partial_overlap'
    else:return None
    return {'relation':relation,'iou':iou,'intersection_over_min':covered,
            'area_ratio':smaller/larger}


def spatial_relation(left,right):
    """Meaningful polygon overlap requiring review; never permission to merge."""
    return _spatial_relation(_polygon(left),_polygon(right))


def _canonical(item):
    return json.dumps(item,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def _source_id(item):
    return hashlib.sha256(_canonical(item).encode('utf-8')).hexdigest()


def _source_order(item):
    engine=item['engine_id']
    return ({'rapidocr':0,'paddleocr':1}.get(engine,2),engine,
            item.get('scale',1),_canonical(item))


def spatial_conflicts(items):
    """Indexed ambiguity edges, including every engine/scale source polygon.

    Indices refer to the supplied items. Edges carry stable leaf-evidence
    identifiers; complete leaf records stay with each representative. The
    relation does not use substrings, scores, scripts, or semantic guesses.
    """
    leaves=[]
    for owner,item in enumerate(items):
        for source in _sources(item):
            polygon=_polygon(source)
            if polygon is not None:leaves.append((owner,source,polygon))
    if not leaves:return []
    tree=STRtree([leaf[2] for leaf in leaves]);edges={}
    for index,(owner,source,polygon) in enumerate(leaves):
        for other in sorted(int(value) for value in tree.query(polygon)):
            if other<=index:continue
            peer,peer_source,peer_polygon=leaves[other]
            if peer==owner:continue
            relation=_spatial_relation(polygon,peer_polygon)
            if relation is None:continue
            if same_reading(source['raw_text'],peer_source['raw_text']) and same_location(source,peer_source):continue
            left,right=sorted((owner,peer))
            left_source,right_source=(source,peer_source) if owner==left else (peer_source,source)
            witness={**relation,'left_source_id':_source_id(left_source),'right_source_id':_source_id(right_source)}
            edges.setdefault((left,right),[]).append(witness)
    result=[]
    for (left,right),witnesses in sorted(edges.items()):
        witnesses=sorted(witnesses,key=lambda value:(value['left_source_id'],value['right_source_id']))
        strongest=max(witnesses,key=lambda value:(value['intersection_over_min'],value['iou']))
        result.append({'left_index':left,'right_index':right,
                       **{key:strongest[key] for key in ('relation','iou','intersection_over_min','area_ratio')},
                       'witnesses':witnesses})
    return result


def spatial_conflict_suggestions(items,edges=None):
    """Explain ambiguity with complete peer evidence, without merging peers."""
    related={}
    for edge in spatial_conflicts(items) if edges is None else edges:
        for index,other in ((edge['left_index'],edge['right_index']),(edge['right_index'],edge['left_index'])):
            relation={key:value for key,value in edge.items() if key not in ('left_index','right_index')}
            relation['raw_text']=items[other]['raw_text']
            relation['source_evidence']=sorted(_sources(items[other]),key=_source_order)
            related.setdefault(index,[]).append(relation)
    return {index:{'reason_codes':['OCR_SPATIAL_CONFLICT'],
                   'spatial_conflicts':sorted(relations,key=_canonical)}
            for index,relations in sorted(related.items())}


def default_candidate_text(candidate):
    """Rules offer alternatives; only an explicit user edit changes OCR content."""
    return candidate['raw_text'].strip()


def _sources(item):
    rules=item.get('rule_suggestions',[])
    if isinstance(rules,str):rules=json.loads(rules)
    evidence=[source for rule in rules for source in rule.get('source_candidates',[])]
    if evidence:
        for source in evidence:yield from _sources(source)
    else:
        leaf=copy.deepcopy(item)
        # Historical DB candidates may gain review metadata without an
        # engine-source wrapper. Do not recursively treat derived peer
        # evidence as part of the immutable OCR observation next time.
        leaf['rule_suggestions']=[rule for rule in rules
                                  if not ('spatial_conflicts' in rule and rule.get('reason_codes')==['OCR_SPATIAL_CONFLICT'])]
        yield leaf


def fuse_results(results):
    groups=[];by_text={};seen=set();raw=[]
    for result in results:
        for representative in result['items']:
            for item in _sources(representative):
                key=_canonical(item)
                if key in seen:continue
                seen.add(key);raw.append(item)
    # Stable ordering keeps the same engine priority and grouping when worker
    # completion or DB row ordering changes. Scores only choose within engine.
    for item in sorted(raw,key=_source_order):
        text=normalized_text(item['raw_text'])
        if not text:continue
        # Every member must agree spatially: an oversized detection must
        # not bridge two separate occurrences of the same label.
        group=next((g for g in by_text.get(text,[]) if all(same_location(item,s) for s in g['sources'])),None)
        if group is None:
            group={'text':text,'sources':[item]};groups.append(group);by_text.setdefault(text,[]).append(group)
        else:group['sources'].append(item)
    items=[];agreement_count=0;all_engines=[]
    for group in groups:
        sources=group['sources'];engines=list(dict.fromkeys(s['engine_id'] for s in sources))
        all_engines.extend(engines)
        # Scores from different engines are not calibrated. Compare scales only
        # within the first engine and preserve all other source candidates.
        primary=sources[0]['engine_id'];selected=max((s for s in sources if s['engine_id']==primary),key=lambda s:s['score'])
        item=copy.deepcopy(selected)
        item['engine_id']='+'.join(engines)
        item['model_id']=' + '.join(dict.fromkeys(s['model_id'] for s in sources))
        reasons=['OCR_ENGINES_AGREE'] if len(engines)>1 else ['OCR_SINGLE_ENGINE_RESULT']
        if len(engines)>1:agreement_count+=1
        suggestions=[]
        for source in sources:
            for rule in source.get('rule_suggestions',[]):
                if rule not in suggestions:suggestions.append(copy.deepcopy(rule))
        item['rule_suggestions']=[*suggestions,{'reason_codes':reasons,'source_candidates':sources}]
        items.append(item)
    conflicts={}
    # Query actual polygons through a tree instead of comparing every item.
    polygons=[_polygon(item) for item in items]
    valid=[index for index,polygon in enumerate(polygons) if polygon is not None]
    tree=STRtree([polygons[index] for index in valid])
    for index in valid:
        for hit in tree.query(polygons[index]):
            other=valid[int(hit)]
            if other<=index:continue
            if same_location(items[index],items[other]) and normalized_text(items[index]['raw_text'])!=normalized_text(items[other]['raw_text']):
                conflicts.setdefault(index,set()).update((index,other))
                conflicts.setdefault(other,set()).update((index,other))
    for index,related in sorted(conflicts.items()):
        items[index]['rule_suggestions'].append({'reason_codes':['OCR_ENGINE_DISAGREEMENT'],'candidate_texts':sorted({items[other]['raw_text'] for other in related})})
    spatial=spatial_conflict_suggestions(items)
    for index,suggestion in spatial.items():items[index]['rule_suggestions'].append(suggestion)
    items.sort(key=lambda i:(min(p[1] for p in i['detected_quad_px']),min(p[0] for p in i['detected_quad_px']),i['raw_text']))
    return {'schema_revision':'1.0','engine_id':'+'.join(sorted(set(all_engines),key=lambda e:({'rapidocr':0,'paddleocr':1}.get(e,2),e))),'items':items,'agreement_count':agreement_count,'conflict_candidate_count':len(conflicts),'spatial_conflict_candidate_count':len(spatial),'raw_candidate_count':len(raw)}


def existing_text_duplicate(connection,project_id,asset_id,candidate,text,quad):
    """Return an active same-source text without overwriting manual corrections."""
    from mapvector.application.ports import load_feature
    from shapely.affinity import rotate
    from shapely.geometry import box
    rows=connection.execute("SELECT f.feature_id,c.detected_quad_px,c.raw_text,c.run_id FROM feature f JOIN text_attribute t USING(feature_id) LEFT JOIN ocr_candidate c ON c.candidate_id=t.primary_candidate_id WHERE f.project_id=? AND f.asset_id=? AND f.feature_type='text' AND f.lifecycle_status='active'",(project_id,asset_id)).fetchall()
    for row in rows:
        feature=load_feature(connection,row['feature_id'])
        readings={normalized_text(feature.get(key) or '') for key in ('text_value','original_text')}
        readings.add(normalized_text(row['raw_text'] or ''))
        reading_matches=normalized_text(text) in readings or normalized_text(candidate['raw_text']) in readings
        conflict_code='OCR_DUPLICATE_TEXT' if reading_matches else 'OCR_POSITION_CONFLICT'
        if row['detected_quad_px'] and same_location({'detected_quad_px':quad},{'detected_quad_px':json.loads(row['detected_quad_px'])}):return row['feature_id'],conflict_code
        if row['detected_quad_px'] and spatial_relation({'detected_quad_px':quad},{'detected_quad_px':json.loads(row['detected_quad_px'])}):return row['feature_id'],'OCR_POSITION_CONFLICT'
        x,y=feature['geometry']['coordinates'];width=feature.get('layout_width_px');height=feature.get('layout_height_px')
        if not width or not height:
            from mapvector.geometry.text import half_extent
            hw,hh=half_extent(feature['text_value'],feature['font_size_px']);width=hw*2;height=hh*2
        footprint=rotate(box(x-width/2,y-height/2,x+width/2,y+height/2),-feature['rotation_deg'],origin=(x,y))
        if same_location({'detected_quad_px':quad},{'detected_quad_px':list(footprint.exterior.coords)[:4]}):return row['feature_id'],conflict_code
        if spatial_relation({'detected_quad_px':quad},{'detected_quad_px':list(footprint.exterior.coords)[:4]}):return row['feature_id'],'OCR_POSITION_CONFLICT'
    return None

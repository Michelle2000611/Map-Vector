"""Merge spatial agreement without discarding competing engine readings."""
import copy
import json
import unicodedata
from shapely.geometry import Polygon


def normalized_text(value):
    # Canonical composition is safe; NFKC would collapse meaningful code glyphs.
    return unicodedata.normalize('NFC',str(value)).strip()


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


def default_candidate_text(candidate):
    """Rules offer alternatives; only an explicit user edit changes OCR content."""
    return candidate['raw_text'].strip()


def _sources(item):
    evidence=[source for rule in item.get('rule_suggestions',[]) for source in rule.get('source_candidates',[])]
    if evidence:
        for source in evidence:yield from _sources(source)
    else:yield copy.deepcopy(item)


def fuse_results(results):
    groups=[];seen=set();raw_count=0
    for result in results:
        for representative in result['items']:
            for item in _sources(representative):
                key=json.dumps(item,sort_keys=True,ensure_ascii=False)
                if key in seen:continue
                seen.add(key);raw_count+=1
                text=normalized_text(item['raw_text'])
                if not text:continue
                # Every member must agree spatially: an oversized detection must
                # not bridge two separate occurrences of the same label.
                group=next((g for g in groups if g['text']==text and all(same_location(item,s) for s in g['sources'])),None)
                if group is None:groups.append({'text':text,'sources':[item]})
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
    conflicts=set()
    for index,left in enumerate(items):
        for other,right in enumerate(items[index+1:],index+1):
            if same_location(left,right) and normalized_text(left['raw_text'])!=normalized_text(right['raw_text']):
                conflicts.update((index,other))
    for index in sorted(conflicts):
        items[index]['rule_suggestions'].append({'reason_codes':['OCR_ENGINE_DISAGREEMENT'],'candidate_texts':sorted({i['raw_text'] for i in items if same_location(items[index],i)})})
    items.sort(key=lambda i:(min(p[1] for p in i['detected_quad_px']),min(p[0] for p in i['detected_quad_px']),i['raw_text']))
    return {'schema_revision':'1.0','engine_id':'+'.join(sorted(set(all_engines),key=lambda e:({'rapidocr':0,'paddleocr':1}.get(e,2),e))),'items':items,'agreement_count':agreement_count,'conflict_candidate_count':len(conflicts),'raw_candidate_count':raw_count}


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
        same_reading=normalized_text(text) in readings or normalized_text(candidate['raw_text']) in readings
        conflict_code='OCR_DUPLICATE_TEXT' if same_reading else 'OCR_POSITION_CONFLICT'
        if row['detected_quad_px'] and same_location({'detected_quad_px':quad},{'detected_quad_px':json.loads(row['detected_quad_px'])}):return row['feature_id'],conflict_code
        x,y=feature['geometry']['coordinates'];width=feature.get('layout_width_px');height=feature.get('layout_height_px')
        if not width or not height:
            from mapvector.geometry.text import half_extent
            hw,hh=half_extent(feature['text_value'],feature['font_size_px']);width=hw*2;height=hh*2
        footprint=rotate(box(x-width/2,y-height/2,x+width/2,y+height/2),-feature['rotation_deg'],origin=(x,y))
        if same_location({'detected_quad_px':quad},{'detected_quad_px':list(footprint.exterior.coords)[:4]}):return row['feature_id'],conflict_code
    return None

"""Source-coordinate residue evidence shared by layer tools. Overlap is not ownership."""
import math
from shapely.geometry import Polygon, box

def text_residue_regions(texts):
    result=[]
    for text in texts:
        quad=text.get("detected_quad_px");region=None;uncertain=False
        if quad:
            try:
                region=Polygon(quad)
                if not region.is_valid or region.area<=0:
                    # Retain original-source coverage, but never grant erase authority
                    # to a repaired/invalid OCR detection without separate review.
                    region=region.convex_hull;uncertain=True
                if region.is_empty or region.area<=0:region=None
            except (ValueError,TypeError):uncertain=True
        if region is None and text.get("display_bbox_px"):
            try:region=box(*text["display_bbox_px"])
            except (ValueError,TypeError):continue
        if region is None or region.is_empty or not region.is_valid or region.area<=0:continue
        try:
            height=min(math.dist(quad[i],quad[(i+1)%4]) for i in range(4)) if quad and not uncertain else float(text.get("font_size_px",12))
            result.append({"text":text,"geometry":region,"basis":"source_detection" if quad and not uncertain else "uncertain_source_detection" if uncertain else "current_display_fallback","character_height_px":max(1,height),"uncertain":uncertain})
        except (ValueError,TypeError,KeyError,IndexError):continue
    return result

def effective_line_appearance(line,snapshot):
    binding=snapshot.get("style_bindings",{}).get(line["feature_id"])
    sid=binding or line.get("style_id") or snapshot.get("default_style_id")
    style=snapshot.get("styles",{}).get(sid,{})
    override=line.get("style_override") or {}
    if isinstance(override,str):
        import json
        override=json.loads(override)
    return {key:override.get(key,style.get(key,line.get(key))) for key in ("stroke_color","stroke_width_px","line_pattern")}

def stroke_raster_evidence(geometry,pixels,raster_source):
    if pixels is None:return {"status":"unavailable","proves_text_ownership":False}
    count=min(257,max(2,math.ceil(geometry.length)+1));points=[geometry.interpolate(i/(count-1),normalized=True) for i in range(count)]
    width,height=pixels.size; samples=[]
    for point in points:
        x,y=int(point.x),int(point.y)
        if 0<=x<width and 0<=y<height:
            value=pixels.getpixel((x,y));value=value if isinstance(value,tuple) else (value,value,value)
            samples.append(max(value[:3])<180)
    fraction=sum(samples)/len(samples) if samples else 0
    return {"status":"supported" if fraction>=.5 else "unsupported","support_fraction":round(fraction,3),"sample_count":len(samples),"source_sha256":raster_source.get("sha256"),"proves_text_ownership":False}


def inferred_dash_members(lines,geometries,patterns,request):
    """Conservatively protect regular short parallel runs in every entry point."""
    from shapely import STRtree
    short=[i for i,g in enumerate(geometries) if g.length<=request.max_short_length_px and g.length>0]
    if not short:return set()
    tree=STRtree([geometries[i] for i in short]);members=set()
    for i in short:
        g=geometries[i];a,b=g.coords[0],g.coords[-1];dx,dy=b[0]-a[0],b[1]-a[1];norm=math.hypot(dx,dy)
        if norm<g.length*.95:continue
        ux,uy=dx/norm,dy/norm;mx,my=(a[0]+b[0])/2,(a[1]+b[1])/2
        hits=tree.query(g.buffer(max(1,getattr(request,"max_gap_px",8))*2+g.length*2))
        if len(hits)>100:continue
        aligned=[]
        for offset in hits:
            j=short[int(offset)];other=geometries[j]
            if max(g.length,other.length)>min(g.length,other.length)*1.2:continue
            if lines[i].get('stroke_color')!=lines[j].get('stroke_color') or lines[i].get('line_role')!=lines[j].get('line_role'):continue
            c,d=other.coords[0],other.coords[-1];vx,vy=d[0]-c[0],d[1]-c[1];length=math.hypot(vx,vy)
            if length<other.length*.95 or abs((ux*vx+uy*vy)/length)<.985:continue
            cx,cy=(c[0]+d[0])/2,(c[1]+d[1])/2
            if abs((cx-mx)*uy-(cy-my)*ux)>max(1,float(lines[i].get('stroke_width_px',1))):continue
            aligned.append(((cx-mx)*ux+(cy-my)*uy,j))
        aligned.sort()
        for k in range(len(aligned)-2):
            trio=aligned[k:k+3];gaps=[trio[t+1][0]-trio[t][0]-(geometries[trio[t][1]].length+geometries[trio[t+1][1]].length)/2 for t in range(2)]
            if min(gaps)>0 and max(gaps)<=getattr(request,"max_gap_px",8) and max(gaps)<=min(gaps)*1.2:members.update(j for _,j in trio)
    return members

def scan_text_strokes(snapshot,request,pixels,lines,geometries,patterns,dash_members):
    dash_members=set(dash_members)|inferred_dash_members(lines,geometries,patterns,request)
    return _scan_region_strokes(snapshot,request,pixels,lines,geometries,patterns,dash_members,text_residue_regions(snapshot["texts"]))


def _scan_region_strokes(snapshot,request,pixels,lines,geometries,patterns,dash_members,regions):
    from shapely import STRtree
    from shapely.ops import unary_union
    if not regions:return []
    tree=STRtree([item["geometry"] for item in regions]);result=[]
    for index,line in enumerate(lines):
        geometry=geometries[index]
        if geometry.is_empty or geometry.length<=1e-7:continue
        appearance=effective_line_appearance(line,snapshot)
        try:width=max(0,float(appearance.get('stroke_width_px') or 1))
        except (ValueError,TypeError):width=1
        # Discovery may include antialiasing/half-stroke edge pixels. Erase
        # authority remains the exact source polygon, never this search margin.
        margin=min(3.,max(.75,width/2+.5))
        refs=[regions[int(i)] for i in sorted(tree.query(geometry,predicate='dwithin',distance=margin))]
        if not refs:continue
        local=max((geometry.intersection(item["geometry"]).length for item in refs),default=0)
        near=max((geometry.intersection(item["geometry"].buffer(margin)).length for item in refs),default=0)
        if near<=1e-7:continue
        cap=max(request.max_short_length_px,max(item["character_height_px"] for item in refs)*5)
        blocked=[]
        if local<=1e-7:blocked.append('TEXT_REGION_EDGE_REQUIRES_REVIEW')
        if local>cap:blocked.append('COMPLEX_TEXT_STROKE_REQUIRES_REVIEW')
        if any(item.get('uncertain') for item in refs):blocked.append('SOURCE_REGION_UNCERTAIN')
        if line["source_type"]=="manual":blocked.append("MANUAL_LINE")
        if line["line_role"]=="split":blocked.append("GEOLOGICAL_BOUNDARY")
        if patterns[index] in ("dashed","teeth") or index in dash_members:blocked.append("SEMANTIC_LINE_PATTERN")
        if any(item["text"].get("geological_symbol") for item in refs):blocked.append("GEOLOGICAL_SYMBOL")
        if not any(item["geometry"].buffer(-.25).covers(geometry) for item in refs):blocked.append("CROSSES_TEXT_REGION")
        if len(refs)>1:blocked.append("AMBIGUOUS_TEXT_OWNERSHIP")
        try:
            if max(int(appearance["stroke_color"][start:start+2],16) for start in (1,3,5))>=180:blocked.append("NON_TEXT_STROKE_COLOR")
        except (ValueError,TypeError):blocked.append("NON_TEXT_STROKE_COLOR")
        source_union=unary_union([item['geometry'] for item in refs])
        fragment=geometry.intersection(source_union if local>1e-7 else source_union.buffer(margin))
        raster=stroke_raster_evidence(fragment,pixels,snapshot.get("raster_source",{}))
        if raster['status']=='supported' and 'NON_TEXT_STROKE_COLOR' in blocked:blocked.remove('NON_TEXT_STROKE_COLOR')
        if snapshot.get('raster_source',{}).get('status')=='mismatch':blocked.append('RASTER_SOURCE_MISMATCH')
        if raster['status']=='unsupported':blocked.append('RASTER_PATH_UNSUPPORTED')
        result.append({"index":index,"texts":[item["text"]["feature_id"] for item in refs],"blocked":blocked,"metrics":{"length_px":geometry.length,"local_length_px":local,"adaptive_length_limit_px":cap,"discovery_margin_px":margin},"evidence":{"raster":raster,"effective_appearance":appearance,"source_regions":[{"text_feature_id":item["text"]["feature_id"],"basis":item["basis"],"polygon_px":list(item["geometry"].exterior.coords),"character_height_px":item["character_height_px"]} for item in refs],"ownership":"requires_review"}})
    return result

def scan_unassigned_strokes(snapshot,request,pixels,lines,geometries,patterns,dash_members):
    """Discover review-only ink clusters, including unadopted OCR source regions.

    No text object is fabricated. Missing association is an unbypassable block
    until a later explicit association produces a new, ordinary preview.
    """
    from shapely import STRtree
    from shapely.ops import unary_union
    dash_members=set(dash_members)|inferred_dash_members(lines,geometries,patterns,request)
    regions=text_residue_regions(snapshot.get('texts',[]))
    region_tree=STRtree([r['geometry'] for r in regions])
    # OCR source regions are evidence even when no text object was adopted.
    # Scan them before short-cluster heuristics so long/crossing/protected lines
    # are visible too. Missing association always forbids whole-line isolation.
    unassigned_texts=[{**item,'feature_id':item['candidate_id']} for item in snapshot.get('unassigned_ocr_candidates',[])]
    proposals=_scan_region_strokes(snapshot,request,pixels,lines,geometries,patterns,dash_members,text_residue_regions(unassigned_texts))
    discovered=[];source_members=set()
    for item in proposals:
        index=item['index']
        # Already represented by an adopted-text candidate; do not duplicate it.
        margin=item['metrics']['discovery_margin_px']
        if len(region_tree.query(geometries[index],predicate='dwithin',distance=margin)):continue
        source_members.add(index)
        evidence=item['evidence'];evidence.update(unassigned=True,basis='unadopted_ocr_region',ownership='unknown',ocr_candidate_ids=item['texts'])
        for entry in evidence['source_regions']:entry['ocr_candidate_id']=entry.pop('text_feature_id')
        discovered.append({'members':[index],'texts':[],'blocked':sorted(set(item['blocked']+['MISSING_TEXT_ASSOCIATION'])),'metrics':item['metrics'],'reasons':['UNADOPTED_OCR_REGION'],'evidence':evidence})
    eligible=[]
    for i,line in enumerate(lines):
        if i in source_members:continue
        if line['source_type']=='manual' or line['line_role']=='split' or patterns[i] in ('dashed','teeth') or i in dash_members:continue
        geometry=geometries[i]
        if geometry.is_empty or geometry.length>max(12,request.max_short_length_px):continue
        appearance=effective_line_appearance(line,snapshot)
        margin=min(3.,max(.75,float(appearance.get('stroke_width_px') or 1)/2+.5))
        if len(region_tree.query(geometry,predicate='dwithin',distance=margin)):continue
        try:
            if max(int(appearance['stroke_color'][j:j+2],16) for j in (1,3,5))>=180:continue
        except (ValueError,TypeError):continue
        eligible.append(i)
    if not eligible:return discovered
    tree=STRtree([geometries[i] for i in eligible]);groups=[]
    pending=set(eligible)
    while pending:
        first=min(pending);pending.remove(first);members=[first];queue=[first];dense=False
        while queue:
            current=queue.pop();near=tree.query(geometries[current].buffer(3))
            if len(near)>64:dense=True;continue
            for offset in near:
                other=eligible[int(offset)]
                if other in pending and geometries[current].distance(geometries[other])<=3:
                    pending.remove(other);members.append(other);queue.append(other)
        if dense or not 3<=len(members)<=64:continue
        union=unary_union([geometries[i] for i in members]);x0,y0,x1,y1=union.bounds
        if max(x1-x0,y1-y0)>max(24,request.max_short_length_px*3) or min(x1-x0,y1-y0)<2:continue
        directions=[]
        for i in members:
            coords=geometries[i].coords;dx=coords[-1][0]-coords[0][0];dy=coords[-1][1]-coords[0][1]
            if abs(dx)+abs(dy)>1e-9:directions.append(math.atan2(dy,dx)%math.pi)
        if not any(min(abs(a-b),math.pi-abs(a-b))>=math.pi/6 for a in directions for b in directions):continue
        groups.append((sorted(members),'unassigned_ink_cluster',None))
    result=discovered
    for members,basis,candidate_id in groups:
        evidence={'unassigned':True,'basis':basis,'ocr_candidate_id':candidate_id,'ownership':'unknown','proves_text_ownership':False}
        if pixels is not None:
            supports=[stroke_raster_evidence(geometries[i],pixels,snapshot.get('raster_source',{})) for i in members]
            evidence['raster_supported_count']=sum(item['status']=='supported' for item in supports)
            evidence['raster_sampled_count']=len(supports)
        result.append({'members':members,'texts':[],'blocked':['MISSING_TEXT_ASSOCIATION'],'metrics':{'length_px':sum(geometries[i].length for i in members),'segment_count':len(members)},'reasons':['UNASSIGNED_TEXT_INK_CLUSTER'],'evidence':evidence})
    return result

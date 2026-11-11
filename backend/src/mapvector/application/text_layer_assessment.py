"""Read-only cross-layer evidence; overlap is never authorization to erase geometry."""
import json
import math
import numpy as np
from PIL import Image
from shapely import from_wkb,contains_xy
from shapely.geometry import Polygon,box
from mapvector.application.ports import load_feature
from mapvector.application.review import text_decision


def assess(connection,project_id,asset_id,project_dir=None,text_feature_ids=None):
    asset=connection.execute('SELECT width_px,height_px,raster_rel_path FROM asset WHERE project_id=? AND asset_id=?',(project_id,asset_id)).fetchone()
    if asset is None:raise KeyError(asset_id)
    revision=connection.execute('SELECT working_revision FROM project WHERE project_id=?',(project_id,)).fetchone()[0]
    items=[];pixels=None
    if project_dir is not None and text_feature_ids is None:
        with Image.open(project_dir/asset['raster_rel_path']) as image:pixels=np.asarray(image.convert('RGB'))
    query="SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active'"
    params=[project_id,asset_id]
    if text_feature_ids is not None:
        if not text_feature_ids:return {'items':[],'working_revision':revision,'policy_revision':'text-layer-evidence-1','summary':{'text_count':0,'content_auto_accepted':0,'content_review_required':0,'cleanup_review_required':0},'read_only':True}
        query+=' AND feature_id IN ('+','.join('?' for _ in text_feature_ids)+')'
        params.extend(text_feature_ids)
    for row in connection.execute(query+' ORDER BY feature_id',params):
        text=load_feature(connection,row[0]);candidate=connection.execute('SELECT * FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(text['primary_candidate_id'],project_id,asset_id)).fetchone() if text['primary_candidate_id'] else None
        candidate=dict(candidate) if candidate else None
        quad=json.loads(candidate['detected_quad_px']) if candidate and candidate['detected_quad_px'] else None
        region=Polygon(quad) if quad else box(*text['display_bbox_px']) if text['display_bbox_px'] else None
        if region is None or not region.is_valid or region.area<=0:
            decision=text_decision(text,candidate)
            content=text['review_status'] if text['review_status'] in ('confirmed','manual_edited','skipped','pipeline_complete_unverified') else decision['review_status']
            items.append({'text_feature_id':text['feature_id'],'candidate_id':text['primary_candidate_id'],'text_value':text['text_value'],'ocr_score':candidate['score'] if candidate else None,'content_status':content,'content_reasons':decision['review_reason_codes'],'cleanup_status':'review_required','region_source':'missing','region_px':[],'suspected_face_ids':[],'suspected_line_ids':[],'protected_line_ids':[],'reasons':['no_detection_quad'],'evidence':[]})
            continue
        x0,y0,x1,y1=region.bounds;height=max(1,min(((quad[(i+1)%4][0]-quad[i][0])**2+(quad[(i+1)%4][1]-quad[i][1])**2)**.5 for i in range(4))) if quad else max(1,text['font_size_px']/.8)
        dark_x=dark_y=np.array([])
        if pixels is not None or project_dir is not None:
            cx0,cy0=max(0,math.floor(x0)),max(0,math.floor(y0));cx1,cy1=min(asset['width_px'],math.ceil(x1)),min(asset['height_px'],math.ceil(y1))
            if cx1>cx0 and cy1>cy0:
                if pixels is not None:patch=pixels[cy0:cy1,cx0:cx1]
                else:
                    with Image.open(project_dir/asset['raster_rel_path']) as source:patch=np.asarray(source.crop((cx0,cy0,cx1,cy1)).convert('RGB'))
                yy,xx=np.where(patch.max(axis=2)<125)
                dark_x=xx+cx0+.5;dark_y=yy+cy0+.5
        rows=connection.execute("SELECT f.feature_id,f.feature_type,f.geometry_wkb,a.fill_color,l.stroke_color,l.line_role FROM feature f LEFT JOIN face_attribute a USING(feature_id) LEFT JOIN line_attribute l USING(feature_id) WHERE f.rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) AND f.project_id=? AND f.asset_id=? AND f.feature_type IN ('face','line') AND f.lifecycle_status='active' ORDER BY f.feature_id",(x0,x1,y0,y1,project_id,asset_id)).fetchall()
        faces=[];lines=[];protected=[];reasons=[];evidence=[]
        code_like='stratigraphic_or_lithology_code' in text_decision(text,candidate)['review_reason_codes']
        def dark(color):
            try:return max(int(color[i:i+2],16) for i in (1,3,5))<150
            except (ValueError,TypeError):return False
        for feature in rows:
            geom=from_wkb(feature['geometry_wkb'])
            if not geom.intersects(region):continue
            fid=feature['feature_id']
            if feature['feature_type']=='face':
                share=geom.intersection(region).area/max(geom.area,1e-9)
                # Relative to text height, never classify a whole background face as ink.
                if geom.area<=min(120,height*height*.65) and share>=.8:
                    source_ink_share=min(1.,float(contains_xy(geom,dark_x,dark_y).sum())/max(1.,geom.intersection(region).area)) if pixels is not None or project_dir is not None else 0.
                    if dark(feature['fill_color']) or source_ink_share>=.35:
                        faces.append(fid);evidence.append({'feature_id':fid,'feature_type':'face','inside_share':round(share,3),'source_ink_share':round(source_ink_share,3),'reason':'small_dark_face_in_text_region' if dark(feature['fill_color']) else 'fragmented_face_matches_source_ink'})
            else:
                if geom.intersection(region.buffer(-1e-6)).length<=1e-7:continue
                share=geom.intersection(region).length/max(geom.length,1e-9)
                if code_like or feature['line_role']=='split' or share<.95 or not region.buffer(-.5).contains(geom):
                    protected.append(fid)
                elif dark(feature['stroke_color']) and geom.length<=height*5 and not code_like:
                    lines.append(fid);evidence.append({'feature_id':fid,'feature_type':'line','inside_share':round(share,3),'reason':'short_dark_line_in_text_region'})
        if faces:reasons.append('suspected_text_faces')
        if lines:reasons.append('suspected_text_lines')
        if protected:reasons.append('protected_boundary_or_crossing_line')
        # Content acceptance and cleanup decisions are independent dimensions.
        decision=text_decision(text,candidate)
        content=text['review_status'] if text['review_status'] in ('confirmed','manual_edited','skipped','pipeline_complete_unverified') else decision['review_status']
        cleanup='review_required' if faces or lines else 'no_suspects'
        if not quad and (faces or lines):reasons.append('no_detection_quad')
        items.append({'text_feature_id':text['feature_id'],'candidate_id':text['primary_candidate_id'],'text_value':text['text_value'],'ocr_score':candidate['score'] if candidate else None,'content_status':content,'content_reasons':decision['review_reason_codes'],'cleanup_status':cleanup,'region_source':'ocr_quad' if quad else 'display_bbox','region_px':list(region.bounds),'suspected_face_ids':faces,'suspected_line_ids':lines,'protected_line_ids':protected,'reasons':reasons,'evidence':evidence})
    return {'items':items,'working_revision':revision,'policy_revision':'text-layer-evidence-1','summary':{'text_count':len(items),'content_auto_accepted':sum(i['content_status']=='auto_accepted_unverified' for i in items),'content_review_required':sum(i['content_status']=='required' for i in items),'cleanup_review_required':sum(i['cleanup_status']=='review_required' for i in items)},'read_only':True}

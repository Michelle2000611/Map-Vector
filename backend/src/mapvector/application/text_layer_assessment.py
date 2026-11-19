"""Read-only cross-layer evidence; overlap is never authorization to erase geometry."""
import json
import math
import numpy as np
from PIL import Image
from shapely import from_wkb,contains_xy
from shapely.geometry import Polygon,box
from mapvector.application.ports import load_feature
from mapvector.application.review import text_decision
from mapvector.geometry.text_residue import text_residue_regions
from mapvector.application.residue_policy import is_kept,is_confirmed


def assess(connection,project_id,asset_id,project_dir=None,text_feature_ids=None,*,residue_context=None):
    asset=connection.execute('SELECT width_px,height_px,raster_rel_path FROM asset WHERE project_id=? AND asset_id=?',(project_id,asset_id)).fetchone()
    if asset is None:raise KeyError(asset_id)
    revision=connection.execute('SELECT working_revision FROM project WHERE project_id=?',(project_id,)).fetchone()[0]
    items=[];pixels=None
    from mapvector.application.residue_context import materialize,checked
    shared=materialize(connection,project_id,asset_id,revision,project_dir is not None) if residue_context is None else checked(residue_context,project_id,asset_id,revision,project_dir is not None)
    context=shared['source'];line_geometries=shared['geometries'];line_candidates_by_text=shared['by_text']
    query="SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active'"
    params=[project_id,asset_id]
    if text_feature_ids is not None:
        if not text_feature_ids:return {'items':[],'working_revision':revision,'policy_revision':'text-layer-evidence-2','summary':{'text_count':0,'content_auto_accepted':0,'content_review_required':0,'cleanup_review_required':0},'read_only':True}
        query+=' AND feature_id IN ('+','.join('?' for _ in text_feature_ids)+')'
        params.extend(text_feature_ids)
    for row in connection.execute(query+' ORDER BY feature_id',params):
        text=load_feature(connection,row[0]);candidate=connection.execute('SELECT * FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(text['primary_candidate_id'],project_id,asset_id)).fetchone() if text['primary_candidate_id'] else None
        candidate=dict(candidate) if candidate else None
        quad=json.loads(candidate['detected_quad_px']) if candidate and candidate['detected_quad_px'] else None
        regions=text_residue_regions([{**text,'detected_quad_px':quad}])
        region=regions[0]['geometry'] if regions else None
        if region is None or not region.is_valid or region.area<=0:
            decision=text_decision(text,candidate)
            content=text['review_status'] if text['review_status'] in ('confirmed','manual_edited','skipped','pipeline_complete_unverified') else decision['review_status']
            items.append({'text_feature_id':text['feature_id'],'candidate_id':text['primary_candidate_id'],'text_value':text['text_value'],'ocr_score':candidate['score'] if candidate else None,'content_status':content,'content_reasons':decision['review_reason_codes'],'cleanup_status':'review_required','region_source':'missing','region_px':[],'suspected_face_ids':[],'suspected_line_ids':[],'protected_line_ids':[],'reasons':['no_detection_quad'],'evidence':[]})
            continue
        x0,y0,x1,y1=region.bounds;height=regions[0]['character_height_px'] if quad else max(1,text['font_size_px']/.8)
        dark_x=dark_y=np.array([])
        if pixels is not None or project_dir is not None:
            cx0,cy0=max(0,math.floor(x0)),max(0,math.floor(y0));cx1,cy1=min(asset['width_px'],math.ceil(x1)),min(asset['height_px'],math.ceil(y1))
            if cx1>cx0 and cy1>cy0:
                if pixels is not None:patch=pixels[cy0:cy1,cx0:cx1]
                else:
                    if (cx1-cx0)*(cy1-cy0)>262144:patch=np.empty((0,0,3),dtype=np.uint8)
                    else:
                        try:
                            with Image.open(project_dir/asset['raster_rel_path']) as source:patch=np.asarray(source.crop((cx0,cy0,cx1,cy1)).convert('RGB'))
                        except (OSError,ValueError):patch=np.empty((0,0,3),dtype=np.uint8)
                yy,xx=np.where(patch.max(axis=2)<125)
                dark_x=xx+cx0+.5;dark_y=yy+cy0+.5
        rows=connection.execute("SELECT f.feature_id,f.feature_type,f.geometry_wkb,a.fill_color,l.stroke_color,l.line_role FROM feature f LEFT JOIN face_attribute a USING(feature_id) LEFT JOIN line_attribute l USING(feature_id) WHERE f.rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) AND f.project_id=? AND f.asset_id=? AND f.feature_type IN ('face','line') AND f.lifecycle_status='active' ORDER BY f.feature_id",(x0,x1,y0,y1,project_id,asset_id)).fetchall()
        faces=[];lines=[];protected=[];reasons=[];evidence=[];face_scope_protection={}
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
                automatic_area=min(120,height*height*.65)
                discovery_area=max(automatic_area,height*height*2)
                if geom.area<=discovery_area and geom.area<region.area*.8 and share>1e-7:
                    source_ink_share=min(1.,float(contains_xy(geom,dark_x,dark_y).sum())/max(1.,geom.intersection(region).area)) if pixels is not None or project_dir is not None else 0.
                    if dark(feature['fill_color']) or source_ink_share>=.35:
                        if geom.area>automatic_area:face_scope_protection.setdefault(fid,[]).append({'line_feature_id':'','reason_codes':['complex_text_face_requires_review']})
                        if not region.buffer(1e-6).covers(geom):face_scope_protection.setdefault(fid,[]).append({'line_feature_id':'','reason_codes':['face_crosses_text_region']})
                        if regions[0].get('uncertain'):face_scope_protection.setdefault(fid,[]).append({'line_feature_id':'','reason_codes':['source_region_uncertain']})
                        faces.append(fid);evidence.append({'feature_id':fid,'feature_type':'face','inside_share':round(share,3),'source_ink_share':round(source_ink_share,3),'reason':'small_dark_face_in_text_region' if dark(feature['fill_color']) else 'fragmented_face_matches_source_ink'})
        for proposal in line_candidates_by_text.get(text['feature_id'],[]):
            line=context['lines'][proposal['index']];fid=line['feature_id']
            geom=line_geometries[proposal['index']]
            kept=is_kept(connection,project_id,asset_id,proposal['texts'],fid)
            if (proposal['blocked'] and not is_confirmed(connection,project_id,asset_id,fid)) or kept:protected.append(fid)
            else:
                lines.append(fid)
                evidence.append({'feature_id':fid,'feature_type':'line','inside_share':round(geom.intersection(region).length/max(geom.length,1e-9),3),'reason':'short_dark_line_in_text_region'})
        from mapvector.application.face_residue_protection import face_line_protection,effective_line_policies
        assessment_features=[load_feature(connection,item['feature_id']) for item in rows if item['feature_type']=='face']+context['lines']
        line_policies=effective_line_policies(connection,project_id,asset_id,assessment_features)
        protected_faces=face_line_protection(assessment_features,faces,lines,line_policies)
        for fid,entries in face_scope_protection.items():protected_faces.setdefault(fid,[]).extend(entries)
        from mapvector.application.residue_policy import related_text_ids
        kept_faces=[fid for fid in faces if is_kept(connection,project_id,asset_id,sorted(set([text['feature_id']]+related_text_ids(connection,project_id,asset_id,fid))),fid)]
        kept_lines=[fid for fid in protected if is_kept(connection,project_id,asset_id,sorted(set([text['feature_id']]+related_text_ids(connection,project_id,asset_id,fid))),fid)]
        if any(any(entry.get('line_feature_id') for entry in entries) for entries in protected_faces.values()):reasons.append('protected_face_independent_line')
        if face_scope_protection:reasons.append('protected_face_source_scope')
        if faces:reasons.append('suspected_text_faces')
        if lines:reasons.append('suspected_text_lines')
        if protected:reasons.append('protected_boundary_or_crossing_line')
        # Content acceptance and cleanup decisions are independent dimensions.
        decision=text_decision(text,candidate)
        content=text['review_status'] if text['review_status'] in ('confirmed','manual_edited','skipped','pipeline_complete_unverified') else decision['review_status']
        cleanup='review_required' if faces or lines or protected else 'no_suspects'
        if not quad and (faces or lines):reasons.append('no_detection_quad')
        items.append({'text_feature_id':text['feature_id'],'candidate_id':text['primary_candidate_id'],'text_value':text['text_value'],'ocr_score':candidate['score'] if candidate else None,'content_status':content,'content_reasons':decision['review_reason_codes'],'cleanup_status':cleanup,'region_source':'source_uncertain' if regions[0].get('uncertain') else 'ocr_quad' if quad else 'display_bbox','region_px':list(region.bounds),'suspected_face_ids':faces,'suspected_line_ids':lines,'protected_line_ids':protected,'manually_confirmed_face_ids':[fid for fid in faces if is_confirmed(connection,project_id,asset_id,fid)],'manually_confirmed_line_ids':[fid for fid in lines+protected if is_confirmed(connection,project_id,asset_id,fid)],'kept_face_ids':kept_faces,'kept_line_ids':kept_lines,'protected_face_ids':sorted(protected_faces),'protected_face_reasons':protected_faces,'reasons':reasons,'evidence':evidence})
    return {'items':items,'working_revision':revision,'policy_revision':'text-layer-evidence-2','summary':{'text_count':len(items),'content_auto_accepted':sum(i['content_status']=='auto_accepted_unverified' for i in items),'content_review_required':sum(i['content_status']=='required' for i in items),'cleanup_review_required':sum(i['cleanup_status']=='review_required' for i in items)},'read_only':True}

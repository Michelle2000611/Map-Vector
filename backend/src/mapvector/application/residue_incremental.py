"""Find text scopes touched by a committed residue plan, using original evidence."""
import json

from shapely import from_wkb
from shapely.geometry import shape

from mapvector.application.ports import load_feature
from mapvector.geometry.text_residue import text_residue_regions


def affected_text_ids(connection,project_id,asset_id,changes,target_text_ids=()):
    identities=set(target_text_ids)
    footprints=[]
    face_dependencies=[]
    from mapvector.application.residue_policy import line_protection
    for before,after in changes:
        feature=after or before
        feature_id=feature['feature_id']
        for value in (before,after):
            if value and value.get('associated_text_feature_id'):identities.add(value['associated_text_feature_id'])
        for row in connection.execute('SELECT text_feature_id FROM residue_decision WHERE project_id=? AND asset_id=? AND feature_id=? UNION SELECT text_feature_id FROM text_residue_decision WHERE project_id=? AND asset_id=? AND line_feature_id=?',(project_id,asset_id,feature_id,project_id,asset_id,feature_id)):
            identities.add(row[0])
        old=shape(before['geometry']) if before and before['lifecycle_status']=='active' else None
        new=shape(after['geometry']) if after and after['lifecycle_status']=='active' else None
        if feature['feature_type']=='text':
            identities.add(feature_id);continue
        if feature['feature_type']=='face' and old is not None and new is not None:
            # Absorbing a tiny glyph changes only that glyph's footprint, even
            # when the receiver spans most of the map.
            footprint=old.symmetric_difference(new)
            face_dependencies.append((old,new))
        elif old is not None and new is not None:footprint=old.union(new)
        else:footprint=old if old is not None else new
        if footprint is None or footprint.is_empty:continue
        if feature['feature_type']=='line':
            width=max(float(line_protection(connection,project_id,asset_id,value)['effective_appearance'].get('stroke_width_px') or 1) for value in (before,after) if value)
            # Discovery uses three pixels; independent face guards use the full
            # visible half-width, which can extend beyond that discovery margin.
            visible=footprint.buffer(max(3.,width/2))
            footprints.append(visible)
            x0,y0,x1,y1=visible.bounds
            for row in connection.execute("SELECT geometry_wkb FROM feature WHERE project_id=? AND asset_id=? AND feature_type='face' AND lifecycle_status='active' AND rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?)",(project_id,asset_id,x0,x1,y0,y1)):
                face=from_wkb(row[0])
                if face.intersects(visible):face_dependencies.append((face,face))
            # Inferred dash runs compare short line neighbors within 40 pixels;
            # either of two hops can change a third member's semantic protection.
            if any(value and shape(value['geometry']).length<=12 for value in (before,after)):
                x0,y0,x1,y1=footprint.buffer(80.).bounds
                for row in connection.execute("SELECT f.feature_id,f.geometry_wkb FROM feature f JOIN line_attribute l USING(feature_id) WHERE f.project_id=? AND f.asset_id=? AND f.lifecycle_status='active' AND l.length_px<=12 AND f.rowid IN (SELECT id FROM feature_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?)",(project_id,asset_id,x0,x1,y0,y1)):
                    neighbor=from_wkb(row['geometry_wkb'])
                    if neighbor.distance(footprint)<=80.:footprints.append(neighbor.buffer(3.))
            footprint=visible
        footprints.append(footprint)
    for footprint in footprints:
        x0,y0,x1,y1=footprint.bounds
        rows=connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active' AND rowid IN (SELECT id FROM text_ocr_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_display_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) ORDER BY feature_id",(project_id,asset_id,x0,x1,y0,y1,x0,x1,y0,y1))
        for row in rows:
            text=load_feature(connection,row[0])
            candidate=connection.execute('SELECT detected_quad_px FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(text.get('primary_candidate_id'),project_id,asset_id)).fetchone()
            text['detected_quad_px']=json.loads(candidate[0]) if candidate and candidate[0] else None
            if any(region['geometry'].intersects(footprint) for region in text_residue_regions([text])):identities.add(row[0])
    # Candidate classification also depends on the receiver's total area.
    # Query its full footprint, then retain only source regions where either
    # version can be a glyph candidate under the shared assessment thresholds.
    for old,new in face_dependencies:
        geometry=old.union(new);x0,y0,x1,y1=geometry.bounds
        rows=connection.execute("SELECT feature_id FROM feature WHERE project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active' AND rowid IN (SELECT id FROM text_ocr_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=? UNION SELECT id FROM text_display_index WHERE max_x>=? AND min_x<=? AND max_y>=? AND min_y<=?) ORDER BY feature_id",(project_id,asset_id,x0,x1,y0,y1,x0,x1,y0,y1))
        for row in rows:
            if row[0] in identities:continue
            text=load_feature(connection,row[0])
            candidate=connection.execute('SELECT detected_quad_px FROM ocr_candidate WHERE candidate_id=? AND project_id=? AND asset_id=?',(text.get('primary_candidate_id'),project_id,asset_id)).fetchone()
            text['detected_quad_px']=json.loads(candidate[0]) if candidate and candidate[0] else None
            for source in text_residue_regions([text]):
                region=source['geometry'];height=source['character_height_px'] if text['detected_quad_px'] else max(1,float(text['font_size_px'])/.8)
                discovery=max(min(120,height**2*.65),height**2*2)
                if any(face.area<=discovery and face.area<region.area*.8 and face.intersection(region).area/max(face.area,1e-9)>1e-7 for face in (old,new)):
                    identities.add(row[0]);break
    return sorted(identity for identity in identities if connection.execute("SELECT 1 FROM feature WHERE feature_id=? AND project_id=? AND asset_id=? AND feature_type='text' AND lifecycle_status='active'",(identity,project_id,asset_id)).fetchone())

"""Normalize legacy relationships without inventing unsupported historical identities."""
import json
from datetime import datetime,timezone
from uuid import uuid5,NAMESPACE_URL

import geopandas as gpd
from shapely import to_wkb


def relation_id(import_id,*parts):return str(uuid5(NAMESPACE_URL,import_id+':'+':'.join(str(part) for part in parts)))


def import_relations(connection,source,directory,project_id,asset_id,import_id,gpkg,gpkg_hash,report,clean):
    maps={}
    for row in connection.execute('SELECT * FROM migration_id_map WHERE import_id=?',(import_id,)):
        item=dict(row);item['legacy_attributes']=json.loads(item['legacy_attributes']);maps[(item['legacy_layer_name'],item['legacy_object_key'])]=item
    # Preserve every nonempty logical grouping within its own layer; never combine face/line labels.
    group_members={}
    for item in maps.values():
        attributes=item['legacy_attributes'];layer=item['legacy_layer_name'];kind='face' if layer=='colour_faces' else 'line' if layer in ('visual_lines','text_residue_lines') else None
        value=attributes.get('face_group') if kind=='face' else attributes.get('logical_id') if kind=='line' else None
        if value is None or str(value)=='':continue
        group_members.setdefault((kind,str(value)),[]).append(item['feature_id'])
    for (kind,legacy_key),members in group_members.items():
        gid=relation_id(import_id,'logical_group',kind,legacy_key)
        connection.execute('INSERT INTO logical_group VALUES (?,?,?,?,?,?)',(gid,project_id,asset_id,kind,legacy_key,0))
        for fid in members:connection.execute('INSERT INTO group_member VALUES (?,?)',(gid,fid))
    layer_names={item['legacy_layer_name'] for item in report['layers']}
    style_map={}
    legend_layer='legend_styles' if 'legend_styles' in layer_names else None
    if legend_layer:
        frame=gpd.read_file(gpkg,layer=legend_layer,engine='pyogrio')
        for index,row in frame.iterrows():
            attrs=clean(row.drop(labels=['geometry'],errors='ignore').to_dict());legacy_key=str(attrs.get('legend_id',index));kind=attrs.get('kind')
            if kind not in ('face','line'):
                report.setdefault('warnings',[]).append({'code':'STYLE_TYPE_UNKNOWN','legacy_style_id':legacy_key});continue
            sid=relation_id(import_id,'style',legacy_key);style_map[legacy_key]=sid
            dash=attrs.get('dash') or '';dash=[float(value) for value in dash.split(',') if value] if isinstance(dash,str) else dash
            pattern='dashed' if attrs.get('line_type')=='dash' else attrs.get('line_type')
            connection.execute('INSERT INTO style VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,project_id,kind,str(attrs.get('name') or legacy_key),attrs.get('rgb') if kind=='face' else None,attrs.get('rgb') if kind=='line' else None,attrs.get('width') if kind=='line' else None,pattern if kind=='line' else None,json.dumps(dash or []),attrs.get('tooth_spacing') if kind=='line' else None,attrs.get('tooth_size') if kind=='line' else None,attrs.get('tooth_side') if kind=='line' else None,0))
        for item in maps.values():
            sid=style_map.get(str(item['legacy_attributes'].get('legend_id')))
            if sid:connection.execute('UPDATE feature SET style_id=? WHERE feature_id=?',(sid,item['feature_id']))
    if 'project_roi' in layer_names:
        frame=gpd.read_file(gpkg,layer='project_roi',engine='pyogrio')
        if len(frame):
            from shapely import union_all
            region=union_all(list(frame.geometry));rid=relation_id(import_id,'roi')
            connection.execute('INSERT INTO roi VALUES (?,?,?,?,?)',(rid,project_id,asset_id,to_wkb(region),0))
    ocr_path=source/'working/ocr_candidates.json';candidate_map={}
    if ocr_path.is_file():
        data=json.loads(ocr_path.read_text(encoding='utf-8'));file_hash=__import__('hashlib').sha256(ocr_path.read_bytes()).hexdigest()
        text_by_legacy={str(item['legacy_attributes'].get('ocr_candidate_id')):item for item in maps.values() if item['legacy_layer_name']=='text_labels' and item['legacy_attributes'].get('ocr_candidate_id') is not None}
        for index,item in enumerate(data.get('items',[])):
            key=str(item.get('id',index));cid=relation_id(import_id,'ocr_candidate',file_hash,key);linked=text_by_legacy.get(key);quad=item.get('quad');score=item.get('score')
            if quad is not None and len(quad)!=4:report.setdefault('warnings',[]).append({'code':'OCR_QUAD_UNKNOWN','legacy_candidate_id':key});quad=None
            reasons=[{'candidate_texts':item.get('candidate_texts',[]),'reasons':item.get('rule_reasons',[])}]
            # Legacy run strings remain evidence; do not fabricate a run FK merely to fill a field.
            connection.execute('INSERT INTO ocr_candidate VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,project_id,asset_id,None,linked['feature_id'] if linked else None,str(item.get('text','')),item.get('suggested_text'),score,json.dumps(quad) if quad else None,str(data.get('engine') or 'legacy_unknown'),data.get('model'),json.dumps(reasons,ensure_ascii=False),'adopted' if linked else 'unreviewed',datetime.now(timezone.utc).isoformat()))
            candidate_map[key]=cid
            if linked:connection.execute('UPDATE text_attribute SET primary_candidate_id=?,original_text=? WHERE feature_id=?',(cid,str(item.get('text','')),linked['feature_id']))
        report.setdefault('warnings',[]).append({'code':'LEGACY_CANDIDATE_RUN_UNPROVEN','candidate_count':len(candidate_map),'message':'Original run IDs retained in frozen candidate evidence; no synthetic run created'})
    # Existing confirmed statuses only retain deliverability when their actor/time evidence is explicit.
    for item in maps.values():
        attrs=item['legacy_attributes']
        if item['legacy_layer_name']=='text_residue_lines' and attrs.get('residue_of'):
            value=str(attrs['residue_of']);legacy_text=value.removeprefix('text#')
            target=maps.get(('text_labels',legacy_text)) or next((entry for entry in maps.values() if entry['legacy_layer_name']=='text_labels' and str(entry['legacy_attributes'].get('label_id','')).lstrip('T')==legacy_text),None)
            if target:connection.execute('UPDATE line_attribute SET associated_text_feature_id=? WHERE feature_id=?',(target['feature_id'],item['feature_id']))
            else:report.setdefault('warnings',[]).append({'code':'LEGACY_RESIDUE_TEXT_UNRESOLVED','feature_id':item['feature_id'],'residue_of':value})
        if item['legacy_layer_name']=='text_labels' and attrs.get('review_status')=='OCR_CONFIRMED':
            if attrs.get('review_actor') and attrs.get('reviewed_at'):
                connection.execute("UPDATE text_attribute SET review_status='confirmed',review_basis='explicit_confirmation',reviewed_content_revision=0,reviewed_at=?,reviewer_id=? WHERE feature_id=?",(str(attrs['reviewed_at']),str(attrs['review_actor']),item['feature_id']))
            else:report.setdefault('warnings',[]).append({'code':'LEGACY_CONFIRMATION_UNPROVEN','feature_id':item['feature_id']})
        provenance=attrs.get('merged_from')
        if provenance:
            try:entries=json.loads(provenance) if isinstance(provenance,str) else provenance
            except (ValueError,TypeError):entries=[]
            for entry in entries or []:
                previous=maps.get(('colour_faces',str(entry.get('eid'))))
                if previous:
                    connection.execute('INSERT INTO feature_lineage VALUES (?,?,?,?,?,?,?)',(relation_id(import_id,'lineage',previous['feature_id'],item['feature_id']),previous['feature_id'],item['feature_id'],'merged_from',None,json.dumps(entry,ensure_ascii=False),import_id))
                else:report.setdefault('warnings',[]).append({'code':'LEGACY_LINEAGE_UNRESOLVED','feature_id':item['feature_id'],'source_attributes':entry})
    report['relation_counts']={'logical_groups':len(group_members),'group_members':sum(map(len,group_members.values())),'styles':len(style_map),'ocr_candidates':len(candidate_map)}

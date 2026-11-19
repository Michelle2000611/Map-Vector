"""Explicit complete cleanup of a reviewed local region, preserving semantic text."""
import copy
from uuid import uuid4
from shapely.geometry import shape,box,mapping
from shapely import union_all
from mapvector.domain.errors import CommandConflict


def validate_line_restore(connection,project_id,asset_id,feature_ids):
    """An applied split cleanup must be undone as one audited operation."""
    for fid in feature_ids:
        split=connection.execute("""SELECT o.operation_id FROM feature source
            JOIN line_attribute a ON a.feature_id=source.feature_id
            JOIN feature_lineage l ON l.source_feature_id=source.feature_id AND l.relation_type='split_from'
            JOIN operation o ON o.operation_id=l.operation_id AND o.operation_status='applied'
            WHERE source.feature_id=? AND source.project_id=? AND source.asset_id=?
            AND source.lifecycle_status='isolated' AND a.isolation_reason='text_residue_complete'
            AND o.operation_type IN ('cleanup_text_residue','apply_line_check') LIMIT 1""",(fid,project_id,asset_id)).fetchone()
        if split:raise CommandConflict('RESIDUE_SPLIT_RESTORE_REQUIRES_UNDO',{'operation_id':split['operation_id'],'reason':'请撤销对应残影清理以恢复原线'})


def _parts(geometry,kind):
    if geometry.is_empty:return []
    if geometry.geom_type==kind:return [geometry]
    if hasattr(geometry,'geoms'):return [part for child in geometry.geoms for part in _parts(child,kind)]
    return []


def plan_changes(features,display,asset,revision,timestamp,text_id,verified_line_feature_ids=(),face_assignments=None):
    """Work only on previewed IDs. Original line evidence survives in isolation."""
    original={f['feature_id']:f for f in features}
    face_ids=set(display.get('cleanup_face_feature_ids',display['face_feature_ids']))
    verified=set(verified_line_feature_ids)|set(display.get('manually_confirmed_line_feature_ids',[]))
    line_ids=(set(display['line_feature_ids'])-set(display['protected_line_feature_ids']))|verified
    from mapvector.application.face_residue_protection import face_line_protection
    protected_faces=face_line_protection(features,face_ids,line_ids,display.get('line_semantic_policies'))
    protected_faces={fid:reasons for fid,reasons in protected_faces.items() if fid not in display.get('manually_confirmed_face_feature_ids',[])}
    if protected_faces:raise CommandConflict('RESIDUE_FACE_PROTECTED',{'protected_faces':protected_faces})
    x0,y0,x1,y1=display['bounds_px'];region=shape(display['region_geometry']) if display.get('region_geometry') else box(x0,y0,x1,y1);inside=region.buffer(-1e-6)
    if not region.is_valid or region.is_empty or region.area<=0:raise CommandConflict('PREVIEW_SCOPE_MISMATCH')
    assignments=face_assignments or {}
    if not set(assignments)<=face_ids:raise CommandConflict('RESIDUE_GROUND_INVALID')
    geometries={f['feature_id']:shape(f['geometry']) for f in features if f['feature_type']=='face' and f['lifecycle_status']=='active' and f['bbox_max_x_px']>=x0 and f['bbox_min_x_px']<=x1 and f['bbox_max_y_px']>=y0 and f['bbox_min_y_px']<=y1}
    changes={};active=dict(geometries)
    def update(old,geometry,**extra):
        value=copy.deepcopy(old);b=geometry.bounds
        value.update(geometry=mapping(geometry),geometry_type=geometry.geom_type,bbox_min_x_px=b[0],bbox_min_y_px=b[1],bbox_max_x_px=b[2],bbox_max_y_px=b[3],revision=revision,updated_at=timestamp,**extra)
        if value['feature_type']=='face':value.update(area_px2=geometry.area,coverage_status='unchecked')
        if value['feature_type']=='line':value.update(length_px=geometry.length)
        return value
    pending=set(face_ids);resolved={};unresolved=[]
    # Each step grows an adjacent background; edge sharing preserves the face coverage.
    while pending:
        choices=[]
        for fid in sorted(pending):
            if fid not in active:raise CommandConflict('PREVIEW_STALE')
            glyph=active[fid]
            if fid not in display.get('manually_confirmed_face_feature_ids',[]) and not region.buffer(1e-6).covers(glyph):raise CommandConflict('PREVIEW_SCOPE_MISMATCH',{'feature_id':fid})
            for target,ground in active.items():
                if target in pending or target in face_ids:continue
                if not glyph.bounds[0]<=ground.bounds[2] or not ground.bounds[0]<=glyph.bounds[2] or not glyph.bounds[1]<=ground.bounds[3] or not ground.bounds[1]<=glyph.bounds[3]:continue
                edge=glyph.boundary.intersection(ground.boundary).length
                if edge<=1e-7:continue
                merged=union_all([glyph,ground])
                if merged.is_valid and merged.geom_type in ('Polygon','MultiPolygon'):
                    choices.append((edge,ground.area,target,fid,merged))
        if not choices:
            if set(assignments)&pending:raise CommandConflict('RESIDUE_GROUND_INVALID',{'feature_ids':sorted(set(assignments)&pending)})
            # No receiver means no face mutation; other independent residues can
            # still be cleaned without opening a coverage hole.
            unresolved=sorted(pending);break
        # The user reviews the resulting scene; receiver selection is an
        # implementation detail. Prefer the strongest shared boundary, then
        # the larger ground, with stable IDs as the deterministic tie breaker.
        by_face={fid:[item for item in choices if item[3]==fid] for fid in sorted(pending)}
        eligible=[]
        for fid,options in by_face.items():
            if not options:continue
            receiver=assignments.get(fid)
            if receiver is not None:
                matching=[item for item in options if item[2]==receiver]
                if not matching:raise CommandConflict('RESIDUE_GROUND_INVALID',{'feature_id':fid,'receiver_options':sorted({item[2] for item in options})})
                eligible.extend(matching)
            else:eligible.extend(options)
        _,_,target,fid,merged=max(eligible,key=lambda item:(item[0],item[1],item[2],item[3]))
        old=original[fid];removed={**old,'lifecycle_status':'superseded','revision':revision,'updated_at':timestamp}
        changes[fid]=(old,removed);changes[target]=(original[target],update(original[target],merged))
        active[target]=merged;active.pop(fid);pending.remove(fid);resolved[fid]=target
    split_sources={}
    for fid in sorted(line_ids):
        old=original.get(fid)
        if not old or old['feature_type']!='line' or old['lifecycle_status']!='active':raise CommandConflict('PREVIEW_STALE')
        geometry=shape(old['geometry'])
        if not region.buffer(1e-6).covers(geometry) and fid not in verified:continue
        cut_region=region
        if geometry.intersection(inside).length<=1e-7:
            # Explicit edge review may include ink whose centreline is just
            # outside the footprint while its visible stroke overlaps it.
            margin=min(3.,max(.75,float(old.get('stroke_width_px') or 1)/2+.5))
            if fid not in verified or geometry.intersection(region.buffer(margin)).length<=1e-7:continue
            cut_region=region.buffer(margin)

        isolated={**old,'lifecycle_status':'isolated','isolation_reason':'text_residue_complete','associated_text_feature_id':text_id,'revision':revision,'updated_at':timestamp}
        changes[fid]=(old,isolated)
        # Retain the exterior line network as separate active, traceable pieces.
        for part in _parts(geometry.difference(cut_region),'LineString'):
            if part.length<=1e-7:continue
            new=update(old,part,feature_id=str(uuid4()),created_at=timestamp)
            changes[new['feature_id']]=(None,new);split_sources[new['feature_id']]=fid
    # Local union and overlap checks do not rebuild an entire GeoDataFrame.
    changed_faces=[fid for fid in changes if fid in geometries]
    before_union=union_all([geometries[fid] for fid in changed_faces]) if changed_faces else None
    after_geometries=[shape(new['geometry']) for _,new in changes.values() if new['feature_type']=='face' and new['lifecycle_status']=='active']
    if before_union is not None:
        after_union=union_all(after_geometries) if after_geometries else before_union.difference(before_union)
        if before_union.symmetric_difference(after_union).area>1e-5 or abs(sum(g.area for g in after_geometries)-after_union.area)>1e-5:raise CommandConflict('GEOMETRY_VALIDATION_FAILED')
    if any(new['feature_type']=='text' for _,new in changes.values()):raise CommandConflict('RESIDUE_TEXT_CHANGED')
    display.update(resolved_face_assignments=resolved,unresolved_face_feature_ids=unresolved)
    return list(changes.values()),split_sources

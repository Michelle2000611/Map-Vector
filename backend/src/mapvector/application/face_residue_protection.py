"""Independent line semantics guard residue face absorption across entry points."""
from shapely.geometry import shape


def face_line_protection(features,face_ids,planned_line_ids=(),line_policies=None):
    """Return face -> reasons. A reviewed residue stroke is not an independent line.

    Explicit manual/boundary/semantic protections remain hard even if a caller
    accidentally includes their IDs in a cleanup proposal.
    """
    wanted=set(face_ids);planned=set(planned_line_ids);policies=line_policies or {}
    faces={item['feature_id']:shape(item['geometry']) for item in features if item['feature_id'] in wanted and item['feature_type']=='face' and item['lifecycle_status']=='active'}
    result={}
    for line in features:
        if line['feature_type']!='line' or line['lifecycle_status']!='active':continue
        policy=policies.get(line['feature_id'],{})
        reasons=list(policy.get('reasons',[]))
        if line.get('source_type')=='manual':reasons.append('manual_line')
        if line.get('line_role')=='split':reasons.append('explicit_split_line')
        if line.get('line_pattern') in ('dash','dashed','teeth','tooth','toothed'):reasons.append('semantic_line_pattern')
        if not reasons and line['feature_id'] in planned:continue
        if line.get('line_role')=='unknown':reasons.append('unknown_independent_line')
        if not reasons:continue
        width=float(policy.get('effective_appearance',{}).get('stroke_width_px',line.get('stroke_width_px',1)))
        footprint=shape(line['geometry']).buffer(max(width/2,1e-6))
        for fid,geometry in faces.items():
            if footprint.intersects(geometry):
                result.setdefault(fid,[]).append({'line_feature_id':line['feature_id'],'reason_codes':sorted(set(reasons))})
    return result


def effective_line_policies(connection,project_id,asset_id,features):
    from mapvector.application.residue_policy import line_protection
    return {line['feature_id']:line_protection(connection,project_id,asset_id,line) for line in features if line['feature_type']=='line' and line['lifecycle_status']=='active'}

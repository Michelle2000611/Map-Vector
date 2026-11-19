"""Bounded explanations of existing line guards; never edit or decide geometry."""
import math

from shapely import STRtree
from shapely.geometry import LineString


MAX_DIAGNOSTIC_SEGMENTS=2048
MAX_DIAGNOSTIC_CHECKS=4096
MAX_ISSUE_LOCATIONS=16


def attribute_differences(lines,effective_style_ids):
    """Mirror the actual comparison fields, including its numeric tolerance."""
    ordered=sorted(lines,key=lambda item:item['feature_id'])
    result=[]
    for field in ('stroke_color','stroke_width_px','line_role','line_pattern','style_ids'):
        values=[(sorted(effective_style_ids.get(item['feature_id'],())) if field=='style_ids'
                 else item[field].lower() if field=='stroke_color' else item[field]) for item in ordered]
        different=(bool(values) and not math.isclose(min(values),max(values),rel_tol=0,abs_tol=1e-6)
                   if field=='stroke_width_px' else any(value!=values[0] for value in values[1:]))
        if different:
            result.append({'field':field,'values':[{'feature_id':item['feature_id'],'value':value}
                                                   for item,value in zip(ordered,values)]})
    # Legacy stores can have direct and relation bindings in opposite order:
    # equal effective sets do not remove _compatible's direct-binding guard.
    direct=[item.get('style_id') for item in ordered]
    if any(value!=direct[0] for value in direct[1:]) and not any(item['field']=='style_ids' for item in result):
        result.append({'field':'style_id','values':[{'feature_id':item['feature_id'],'value':value}
                                                   for item,value in zip(ordered,direct)]})
    return result


def _parts(geometry):
    if geometry.is_empty:return
    if geometry.geom_type in ('Point','LineString'):yield geometry
    elif hasattr(geometry,'geoms'):
        for part in geometry.geoms:yield from _parts(part)


def self_intersection_locations(coordinates,bounds_px,*,segment_budget=MAX_DIAGNOSTIC_SEGMENTS,
                                intersection_budget=MAX_DIAGNOSTIC_CHECKS,max_locations=MAX_ISSUE_LOCATIONS):
    """Locate crossings/retraces with explicit bounds when exact work is capped.

    Bounds come from the complete proposed line. Segment and pair limits are
    independent of raster/map size and prevent quadratic diagnostic work from
    becoming a prerequisite for showing an already blocked candidate.
    """
    maximum=max(1,min(MAX_ISSUE_LOCATIONS,max_locations))
    found={}
    def fallback(reason):
        locations=[found[key] for key in sorted(found)][:maximum-1]
        return [*locations,{'reason_code':'SELF_INTERSECTION','bounds_px':list(bounds_px),
                            'precise':False,'approximation_reason':reason}]
    if not coordinates or len(coordinates)<2:return fallback('not_localized')
    if len(coordinates)-1>segment_budget:return fallback('segment_budget_exceeded')
    try:
        points=[tuple(float(value) for value in point[:2]) for point in coordinates]
        if any(len(point)!=2 or not all(math.isfinite(value) for value in point) for point in points):
            return fallback('invalid_geometry')
        points=[point for index,point in enumerate(points) if index==0 or point!=points[index-1]]
        segments=[LineString([left,right]) for left,right in zip(points,points[1:])]
    except (TypeError,ValueError):return fallback('invalid_geometry')
    if not segments:return fallback('not_localized')
    tree=STRtree(segments);checks=0
    for index,segment in enumerate(segments):
        for other in sorted(int(hit) for hit in tree.query(segment)):
            if other<=index:continue
            if checks>=intersection_budget:return fallback('check_budget_exceeded')
            checks+=1
            intersection=segment.intersection(segments[other])
            adjacent=other==index+1 or index==0 and other==len(segments)-1 and points[0]==points[-1]
            # A normal consecutive vertex (including a closed line's first/
            # last vertex) is not self intersection. Retraced edges still are.
            if adjacent and intersection.geom_type=='Point':continue
            for part in _parts(intersection):
                bounds=tuple(float(value) for value in part.bounds)
                key=tuple(round(value,9) for value in bounds)
                found.setdefault(key,{'reason_code':'SELF_INTERSECTION','bounds_px':list(bounds),'precise':True})
                if len(found)>maximum:return fallback('location_limit_reached')
    return [found[key] for key in sorted(found)] or fallback('not_localized')

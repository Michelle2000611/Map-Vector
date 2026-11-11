"""Recover supported thin map strokes without bridging gaps or crossing branches."""
import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize
from shapely.geometry import LineString,Point
from shapely import union_all
from shapely.ops import nearest_points


def recover_lines(rgb,existing=()):
    values=rgb.astype(np.int16);chroma=values.max(2)-values.min(2)
    neutral=(values.max(2)<180)&(chroma<55)
    colored=(values.max(2)<195)&(values.min(2)<110)&(chroma>=55)
    dark=neutral|colored
    components,count=ndimage.label(dark,np.ones((3,3)))
    widths=ndimage.distance_transform_edt(dark)*2
    result=[];identity=len(existing)+100000
    network=union_all([f['geom'] for f in existing]) if existing else None
    occupied=union_all([f['geom'].buffer(min(2.5,max(1.5,float(f['width'])*.3)),cap_style=2) for f in existing]) if existing else None
    for label,slices in enumerate(ndimage.find_objects(components),1):
        if slices is None:continue
        ys,xs=slices;h,w=ys.stop-ys.start,xs.stop-xs.start
        if max(h,w)<15 or (max(h,w)<65 and max(h,w)/max(1,min(h,w))<2.5):continue
        local=components[slices]==label
        if local.mean()>.7 and min(h,w)>15:continue
        # A solid colored strip is a narrow face, not evidence of a line.
        is_colored=bool(np.mean(colored[slices][local])>.5)
        if is_colored:
            import cv2
            _,(rect_w,rect_h),_=cv2.minAreaRect(np.argwhere(local).astype(np.float32))
            fill_ratio=float(local.sum())/max(1,(rect_w+1)*(rect_h+1))
            if fill_ratio>.7 and min(rect_w,rect_h)>=3:continue
        skeleton=skeletonize(local)
        points={(int(y+ys.start),int(x+xs.start)) for y,x in np.argwhere(skeleton)}
        def neighbors(p):
            y,x=p
            return [q for dy in (-1,0,1) for dx in (-1,0,1) if (dx or dy) and (q:=(y+dy,x+dx)) in points and not(dx and dy and ((y,x+dx) in points or (y+dy,x) in points))]
        adjacency={p:neighbors(p) for p in points};nodes={p for p,ns in adjacency.items() if len(ns)!=2}
        visited=set();paths=[]
        for start in sorted(nodes or points):
            for nxt in adjacency[start]:
                edge=frozenset((start,nxt))
                if edge in visited:continue
                chain=[start];previous=start;current=nxt;visited.add(edge)
                while True:
                    chain.append(current)
                    if current in nodes or current==start:break
                    following=next((p for p in adjacency[current] if p!=previous),None)
                    if following is None:break
                    visited.add(frozenset((current,following)));previous,current=current,following
                if len(chain)>=3:paths.append(chain)
        for chain in paths:
            geometry=LineString([(x+.5,y+.5) for y,x in chain]).simplify(.65)
            if geometry.length<6:continue
            samples=np.maximum(1,np.array([widths[y,x] for y,x in chain])-1)
            width=float(np.clip(np.median(samples),1,50))
            if width>(9 if is_colored else 18):continue
            color=np.median([rgb[y,x] for y,x in chain],axis=0).astype(np.uint8)
            # Persist changes in thickness as connected pieces instead of
            # flattening an entire variable-width line to one median value.
            smooth=ndimage.median_filter(samples,size=min(7,len(samples)//2*2+1),mode='nearest')
            breaks=[0]
            for i in range(5,len(chain)-5):
                if abs(float(np.median(smooth[max(breaks[-1],i-5):i]))-float(np.median(smooth[i:i+5])))>2.5:
                    if i-breaks[-1]>=6:breaks.append(i)
            breaks.append(len(chain)-1)
            for lo,hi in zip(breaks,breaks[1:]):
                part=LineString([(x+.5,y+.5) for y,x in chain[lo:hi+1]]).simplify(.65)
                if part.length<1:continue
                measured=float(np.clip(np.median(samples[lo:hi+1]),1,50))
                missing=part.difference(occupied) if occupied is not None else part
                pieces=list(missing.geoms) if missing.geom_type=='MultiLineString' else [missing]
                for piece in pieces:
                    if piece.is_empty or piece.geom_type!='LineString' or piece.length<2:continue
                    coords=list(piece.coords)
                    if network is not None:
                        # Only close the tiny cut introduced by subtracting the
                        # existing centerline buffer; never join raster dash gaps.
                        for end in (0,-1):
                            point=Point(coords[end]);nearest=nearest_points(point,network)[1]
                            if geometry.distance(network)<=.75 and occupied.boundary.distance(point)<=1e-6 and point.distance(nearest)<=3.5:
                                coords[end]=nearest.coords[0]
                    piece=LineString(coords)
                    result.append({'id':identity,'group':f'recovered_{label}','geom':piece,'raw':list(piece.coords),'kind':'colored_skeleton' if is_colored else 'neutral_skeleton','width':measured,'rgb':color})
                    identity+=1
    normalize_groups(result)
    return result


def normalize_groups(lines):
    """Split disconnected auto groups and preserve straight paths at crossings.

    This changes grouping only; geometries and intentional dash gaps stay intact.
    """
    from scipy.spatial import cKDTree
    if not lines:return
    parents=list(range(len(lines)))
    def root(index):
        while parents[index]!=index:
            parents[index]=parents[parents[index]];index=parents[index]
        return index
    endpoints=[];owners=[];directions=[]
    for index,line in enumerate(lines):
        coords=np.asarray(line['geom'].coords)
        for end,near in [(0,min(3,len(coords)-1)),(-1,max(-4,-len(coords)))]:
            endpoints.append(coords[end]);owners.append(index)
            vector=coords[near]-coords[end];directions.append(vector/max(np.linalg.norm(vector),1e-9))
    tree=cKDTree(endpoints)
    for a,point in enumerate(endpoints):
        nearby=tree.query_ball_point(point,1.6)
        for b in nearby:
            i,j=owners[a],owners[b]
            if i==j or lines[i].get('group')!=lines[j].get('group'):continue
            if lines[i].get('kind')!=lines[j].get('kind'):continue
            if np.linalg.norm(np.asarray(lines[i]['rgb'],float)-np.asarray(lines[j]['rgb'],float))>35:continue
            if len({owners[k] for k in nearby})>2 and np.dot(directions[a],directions[b])>-.94:continue
            ri,rj=root(i),root(j)
            if ri!=rj:parents[max(ri,rj)]=min(ri,rj)
    original=[line.get('group',line['id']) for line in lines]
    for i,line in enumerate(lines):line['group']=f'{original[i]}:connected:{root(i)}'

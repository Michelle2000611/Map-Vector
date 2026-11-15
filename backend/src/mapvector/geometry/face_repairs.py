"""Conservative local appendage discovery; every proposal retains vector coverage."""
import math

import numpy as np
from affine import Affine
from rasterio.features import rasterize, shapes
from scipy import ndimage
from shapely import get_coordinates, maximum_inscribed_circle, union_all
from shapely.geometry import Polygon, box, mapping, shape


def _pixel_width(mask):
    """Conservative orthogonal cell width, with exact odd/even strip widths.

    Twice the EDT overstates odd pixel widths. Crossings and sharp bends can
    overstate this run measure; those candidates are conservatively omitted.
    """
    horizontal=np.zeros(mask.shape,dtype=np.int32)
    vertical=np.zeros(mask.shape,dtype=np.int32)
    for row,values in enumerate(mask):
        edges=np.diff(np.r_[False,values,False].astype(np.int8))
        for start,end in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
            horizontal[row,start:end]=end-start
    for column,values in enumerate(mask.T):
        edges=np.diff(np.r_[False,values,False].astype(np.int8))
        for start,end in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
            vertical[start:end,column]=end-start
    return float(np.minimum(horizontal,vertical).max())


def _orthogonal_grid(geometry):
    coordinates=get_coordinates(geometry)
    if not np.allclose(coordinates,np.round(coordinates),atol=1e-8,rtol=0):return False
    return all(not np.any((np.abs(delta[:,0])>1e-8)&(np.abs(delta[:,1])>1e-8))
               for delta in (np.diff(np.asarray(ring.coords),axis=0) for ring in [geometry.exterior,*geometry.interiors]))


def narrow_metrics(geometry,width_px,min_length_px,max_area_px2):
    """Measure a complete owner, using local inscribed width for vector curves.

    Pixel-aligned inputs retain their exact cell-run measure. Other vectors use
    the largest inscribed disk, so bends that become too wide are omitted.
    Neither method trims a large face to manufacture a narrow owner.
    """
    if geometry.geom_type!='Polygon' or geometry.is_empty or not geometry.is_valid or geometry.area>max_area_px2:return None
    x0,y0,x1,y1=geometry.bounds
    extent=max(x1-x0,y1-y0)
    if not _orthogonal_grid(geometry):
        # Bound this expensive metric as well as the pixel-grid path below.
        if len(get_coordinates(geometry))>100_000:return None
        thickness=float(maximum_inscribed_circle(geometry,tolerance=1e-4).length*2)
        if thickness<=1e-8 or thickness>width_px+1e-7:return None
        rectangle=np.asarray(geometry.minimum_rotated_rectangle.exterior.coords)
        extent=max(float(np.linalg.norm(np.diff(rectangle,axis=0),axis=1).max()),float(geometry.area/thickness))
        return {'length_px':extent,'width_px':thickness} if extent>=min_length_px else None
    if extent<min_length_px:return None
    height=int(y1-y0);width=int(x1-x0)
    if not height or not width or height*width>16_000_000:return None
    mask=rasterize([(geometry,1)],out_shape=(height,width),transform=Affine.translation(x0,y0),dtype='uint8').astype(bool)
    thickness=_pixel_width(mask)
    if thickness>width_px+1e-7:return None
    return {'length_px':float(extent),'width_px':thickness}


def _boundary_gaps(target,ownership_faces,width_px,min_length_px,max_area_px2):
    """Discover open notches and complete narrow owners in a broader notch.

    The bounding envelope only bounds discovery. Ownership is revalidated by
    the application, and every discovered region requires explicit review.
    """
    if target.geom_type!='Polygon':return []
    envelope=box(*target.bounds)
    outside=envelope.difference(target)
    components=list(outside.geoms) if outside.geom_type=='MultiPolygon' else [outside]
    proposed=[]
    for component in components:
        if component.is_empty or component.boundary.intersection(envelope.boundary).length<=1e-7:continue
        metrics=narrow_metrics(component,width_px,min_length_px,max_area_px2)
        if metrics:proposed.append((component,metrics))
    # A thin whole face can meet the source exterior inside a broad open
    # complement. Its other disconnected pieces must never be discarded.
    for fid,owner in ownership_faces:
        if not envelope.covers(owner) or owner.intersection(target).area>1e-7:continue
        if owner.boundary.intersection(target.exterior).length<=1e-7:continue
        if any(owner.intersection(component).area>1e-7 for component,metrics in proposed):continue
        metrics=narrow_metrics(owner,width_px,min_length_px,max_area_px2)
        if metrics:proposed.append((owner,metrics))
    return [{'kind':'boundary_gap','geometry':mapping(candidate),'area_px2':candidate.area,
             'receiver_options':[],'occupying_feature_ids':sorted(fid for fid,owner in ownership_faces if owner.intersection(candidate).area>1e-7),
             'blocked_reason':'BOUNDARY_GAP_UNSAFE_OWNERSHIP',**metrics} for candidate,metrics in proposed]


def _pixel_spurs(target,width_px,min_length_px,max_area_px2):
    """Retain the exact legacy cell subset for genuine integer-grid inputs."""
    candidates=[]
    radius=max(1,int(math.ceil(width_px/2)))
    x0,y0,x1,y1=map(int,target.bounds);pad=radius+1
    height=y1-y0+2*pad;width=x1-x0+2*pad
    if height*width>16_000_000:return candidates
    transform=Affine.translation(x0-pad,y0-pad)
    mask=rasterize([(target,1)],out_shape=(height,width),transform=transform,dtype='uint8').astype(bool)
    opened=ndimage.binary_opening(mask,structure=np.ones((2*radius+1,2*radius+1),bool))
    cores,core_count=ndimage.label(opened)
    if not core_count:return candidates
    lost=mask&~opened;labels,count=ndimage.label(lost)
    slices=ndimage.find_objects(labels)
    for label,section in enumerate(slices,1):
        if section is None:continue
        ys,xs=section;local=labels[section]==label;area=int(local.sum())
        extent=max(ys.stop-ys.start,xs.stop-xs.start)
        if area>max_area_px2 or extent<min_length_px:continue
        # Local cell thickness and the wide-core attachment are separate guards.
        thickness=_pixel_width(local)
        if thickness>width_px+1e-7:continue
        full=labels==label
        adjoining=np.unique(cores[ndimage.binary_dilation(full)&opened]);adjoining=adjoining[adjoining>0]
        if len(adjoining)!=1:continue
        polygons=[shape(value) for value,flag in shapes(full.astype('uint8'),mask=full,transform=transform) if flag==1]
        removed=union_all(polygons);remaining=target.difference(removed)
        if removed.geom_type!='Polygon' or remaining.geom_type!='Polygon' or not remaining.is_valid:continue
        if len(remaining.interiors)!=len(target.interiors) or removed.area>=target.area*.25:continue
        candidates.append({'kind':'spur','geometry':mapping(removed),'area_px2':removed.area,'length_px':float(extent),'width_px':thickness,'receiver_options':[],
                           'discovery_method':'pixel_grid','attachment_count':1})
    return candidates


def _vector_spurs(target,width_px,min_length_px,max_area_px2):
    """Use vector morphology for discovery, with exact original-vector subsets.

    Removing a candidate must leave one connected wide body and all its holes.
    Thus thin whole units, bridges and detached multipart islands stay intact.
    A peninsula can still be geologically real: this is evidence for review.
    """
    coordinates=get_coordinates(target)
    if len(coordinates)>100_000:return []
    residual=float(np.abs(coordinates-np.round(coordinates)).max())
    # Tiny grid jitter does not establish an intentional subpixel boundary.
    if 1e-8<residual<.01:return []
    radius=width_px/2+1e-4
    eroded=target.buffer(-radius,join_style='mitre')
    if eroded.is_empty:return []
    wide=eroded.buffer(radius,join_style='mitre').intersection(target)
    lost=target.difference(wide)
    pieces=list(lost.geoms) if hasattr(lost,'geoms') else [lost]
    cores=list(eroded.geoms) if eroded.geom_type=='MultiPolygon' else [eroded]
    candidates=[]
    for removed in pieces:
        metrics=narrow_metrics(removed,width_px,min_length_px,max_area_px2)
        if not metrics or removed.area>=target.area*.25:continue
        remaining=target.difference(removed)
        if remaining.geom_type!='Polygon' or not remaining.is_valid or len(remaining.interiors)!=len(target.interiors):continue
        attached=[core for core in cores if removed.distance(core)<=radius+1e-7]
        if len(attached)!=1:continue
        # Candidates cut only along the original boundary and one local join.
        # Coincident rotated edges can carry machine-precision needles after
        # buffer overlay. Measure only the interior join, without snapping or
        # rewriting the original coordinates used for the transfer.
        attachment=removed.boundary.difference(target.boundary.buffer(1e-7))
        if attachment.is_empty or attachment.length>width_px*2+1e-7:continue
        candidates.append({'kind':'spur','geometry':mapping(removed),'area_px2':removed.area,'receiver_options':[],
                           'discovery_method':'vector_opening','attachment_count':1,'attachment_width_px':float(attachment.length),**metrics})
    return candidates


def diagnose(target,ownership_faces,width_px=2,min_length_px=12,max_area_px2=150):
    """Propose local subsets while preserving narrow bodies, bridges and holes."""
    candidates=[]
    parts=list(target.geoms) if target.geom_type=='MultiPolygon' else [target]
    for part in parts:
        if part.geom_type!='Polygon' or part.is_empty or not part.is_valid:continue
        for ring in part.interiors:
            hole=Polygon(ring)
            owners=[fid for fid,geometry in ownership_faces if geometry.intersection(hole).area>1e-7]
            candidates.append({'kind':'occupied_hole' if owners else 'void','geometry':mapping(hole),'area_px2':hole.area,'receiver_options':[],
                               'occupying_feature_ids':sorted(owners),
                               **({'blocked_reason':'OCCUPIED_HOLE_USE_MERGE'} if owners else {'blocked_reason':'HOLE_EXCEEDS_AREA_LIMIT'} if hole.area>max_area_px2 else {})})
        # A separate component inside this component's envelope is an island,
        # not an absorbable notch. Keep that established ownership protection.
        envelope=box(*part.bounds)
        if not any(other is not part and envelope.intersection(other).area>1e-7 for other in parts):
            candidates.extend(_boundary_gaps(part,ownership_faces,width_px,min_length_px,max_area_px2))
        discover=_pixel_spurs if _orthogonal_grid(part) else _vector_spurs
        candidates.extend(discover(part,width_px,min_length_px,max_area_px2))
    return candidates

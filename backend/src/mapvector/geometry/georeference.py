"""World file pixel-center coordinates become the project's pixel-edge affine."""
import math
from pyproj import CRS
from mapvector.domain.errors import CommandConflict


def external_reference(world,crs):
    try:
        values=[float(x) for x in world.decode('utf-8-sig').split()]
        if len(values)!=6 or not all(math.isfinite(x) for x in values):raise ValueError('World file needs six finite numbers')
        a,d,b,e,c,f=values
        if abs(a*e-b*d)<1e-15:raise ValueError('Singular affine')
        reference=CRS.from_user_input(crs.decode('utf-8-sig').strip())
        return {'crs_wkt':reference.to_wkt(),'pixel_to_map_affine':[a,b,c-(a+b)/2,d,e,f-(d+e)/2]}
    except Exception as exc:raise CommandConflict('GEOREFERENCE_INVALID',{'reason':str(exc)}) from exc


def oriented_affine(affine,orientation,width,height):
    """Map oriented pixel edges through their original pixel-edge coordinates."""
    transforms={1:(1,0,0,0,1,0),2:(-1,0,width,0,1,0),3:(-1,0,width,0,-1,height),4:(1,0,0,0,-1,height),5:(0,1,0,1,0,0),6:(0,1,0,-1,0,height),7:(0,-1,width,-1,0,height),8:(0,-1,width,1,0,0)}
    u,v,w,x,y,z=transforms.get(orientation,transforms[1]);a,b,c,d,e,f=affine
    return [a*u+b*x,a*v+b*y,a*w+b*z+c,d*u+e*x,d*v+e*y,d*w+e*z+f]

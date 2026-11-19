import type {Feature,Point} from './models';

export type LineJoinEndpoint={featureId:string;point:Point;side:0|1};

export function lineJoinEndpoints(features:Feature[]):LineJoinEndpoint[]{
 return features.flatMap(feature=>feature.feature_type==='line'&&feature.lifecycle_status==='active'&&feature.geometry.type==='LineString'&&feature.geometry.coordinates.length>=2
  ?[{featureId:feature.feature_id,point:feature.geometry.coordinates[0] as Point,side:0 as const},{featureId:feature.feature_id,point:feature.geometry.coordinates.at(-1)! as Point,side:1 as const}]:[]);
}

/** Interaction radius is in screen pixels; submitted points remain exact source coordinates. */
export function snapLineJoinEndpoint(point:Point,endpoints:LineJoinEndpoint[],zoom:number,excludeFeatureId?:string):LineJoinEndpoint|undefined{
 if(!Number.isFinite(zoom)||zoom<=0)return;
 const nearby=endpoints.filter(item=>item.featureId!==excludeFeatureId).map(item=>({item,distance:Math.hypot(item.point[0]-point[0],item.point[1]-point[1])*zoom})).filter(item=>item.distance<=8).sort((a,b)=>a.distance-b.distance);
 if(nearby.length>1&&Math.abs(nearby[0].distance-nearby[1].distance)<.01)return;
 return nearby[0]?.item;
}

export function lineJoinPathAttached(points:Point[],endpoints:LineJoinEndpoint[]):boolean{
 if(points.length<2)return false;
 const matches=(point:Point)=>endpoints.filter(item=>Math.hypot(item.point[0]-point[0],item.point[1]-point[1])<1e-6);
 return matches(points[0]).some(first=>matches(points.at(-1)!).some(last=>last.featureId!==first.featureId));
}

import type {EditResult,Feature,Preview,Style} from './models';

export type ResidueComparison={preview:Preview;features:Record<string,Feature>;sourceImage:{url:string;bounds:number[]}};
export type ResidueScene=NonNullable<Preview['cleanup_preview']>;

function intersects(feature:Feature,bounds:number[]):boolean{
 const coordinates=feature.geometry.coordinates;
 const box=feature.feature_type==='text'&&feature.display_bbox_px?feature.display_bbox_px:geometryBounds(coordinates);
 return box[0]<=bounds[2]&&box[2]>=bounds[0]&&box[1]<=bounds[3]&&box[3]>=bounds[1];
}
function geometryBounds(coordinates:unknown):number[]{
 const bounds=[Infinity,Infinity,-Infinity,-Infinity];
 function visit(value:unknown){
  if(!Array.isArray(value))return;
  if(typeof value[0]==='number'&&typeof value[1]==='number'){bounds[0]=Math.min(bounds[0],value[0]);bounds[1]=Math.min(bounds[1],value[1]);bounds[2]=Math.max(bounds[2],value[0]);bounds[3]=Math.max(bounds[3],value[1]);}
  else value.forEach(visit);
 }
 visit(coordinates);return bounds;
}
/** Keep only the original inspection's local geometry; workspace objects stay mutable. */
export function captureResidueComparison(preview:Preview,features:Record<string,Feature>,sourceImage:{url:string;bounds:number[]}):ResidueComparison{
 const display=preview.text_residue_display!;
 const ids=new Set([...preview.feature_ids,...display.face_feature_ids,...display.line_feature_ids,...display.protected_line_feature_ids]);
 const local=Object.values(features).filter(feature=>feature.lifecycle_status==='active'&&(ids.has(feature.feature_id)||intersects(feature,display.bounds_px)));
 return structuredClone({preview,features:Object.fromEntries(local.map(feature=>[feature.feature_id,feature])),sourceImage});
}
/** Draw committed objects, including receiver geometry that differs from a projected plan. */
export function actualResidueScene(features:Record<string,Feature>,bounds:number[],result:Pick<EditResult,'removed_feature_ids'|'upserted_features'>,styles:Style[]):ResidueScene{
 const effective={...features};
 for(const id of result.removed_feature_ids)delete effective[id];
 for(const feature of result.upserted_features)effective[feature.feature_id]=feature;
 const order={face:0,line:1,text:2};
 const visible=Object.values(effective).filter(feature=>feature.lifecycle_status==='active'&&intersects(feature,bounds));
 visible.sort((a,b)=>order[a.feature_type]-order[b.feature_type]||(typeof a.draw_order==='number'?a.draw_order:0)-(typeof b.draw_order==='number'?b.draw_order:0)||a.feature_id.localeCompare(b.feature_id));
 return structuredClone({features:visible,styles,has_changes:result.removed_feature_ids.length>0||result.upserted_features.length>0});
}

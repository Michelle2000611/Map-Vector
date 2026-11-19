import type {Asset,Preview} from './models';
/** The same raster rectangle is used in global and single-object inspection. */
export function residueSourceCrop(projectId:string,asset:Asset,preview:Preview){
 const b=preview.text_residue_display!.bounds_px;
 const bounds=[Math.max(0,Math.floor(b[0])),Math.max(0,Math.floor(b[1])),Math.min(asset.width_px,Math.ceil(b[2])),Math.min(asset.height_px,Math.ceil(b[3]))];
 return {bounds,url:'/api/projects/'+projectId+'/assets/'+asset.asset_id+'/crop?bounds_px='+bounds.join(',')+'&preview_id='+encodeURIComponent(preview.preview_id)};
}

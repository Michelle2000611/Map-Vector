import {ApiError,request} from './client';

export type FlaggedFace={feature_id:string;candidate_count:number;kinds:string[]};
export type FaceScanReport={base_revision:number;scanned_face_count:number;flagged_faces:FlaggedFace[];truncated:boolean};

const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
const strings=(value:unknown):value is string[]=>Array.isArray(value)&&value.every(item=>typeof item==='string');

function flagged(value:unknown):FlaggedFace|null{
 if(!object(value)||typeof value.feature_id!=='string'||!value.feature_id||typeof value.candidate_count!=='number'||!Number.isFinite(value.candidate_count)||!strings(value.kinds))return null;
 return {feature_id:value.feature_id,candidate_count:value.candidate_count,kinds:value.kinds};
}

export function parseFaceScanReport(value:unknown):FaceScanReport{
 const invalid=()=>new ApiError('FACE_CHECK_INVALID_RESPONSE','面检查返回的数据格式异常，请重新检查。');
 if(!object(value)||!Number.isSafeInteger(value.base_revision)||typeof value.scanned_face_count!=='number'||!Array.isArray(value.flagged_faces)||typeof value.truncated!=='boolean')throw invalid();
 const faces=value.flagged_faces.map(item=>flagged(item));
 if(faces.some(item=>!item))throw invalid();
 return {base_revision:value.base_revision as number,scanned_face_count:value.scanned_face_count,flagged_faces:faces as FlaggedFace[],truncated:value.truncated};
}

export async function scanFaces(projectId:string,assetId:string,signal:AbortSignal){
 const endpoint='/projects/'+projectId+'/face-repair-scan?asset_id='+assetId;
 let raw=await request<unknown>(endpoint,undefined,signal);
 let combined=parseFaceScanReport(raw);
 const cursors=new Set<string>();
 while(combined.truncated){
  if(!object(raw)||typeof raw.next_cursor!=='string'||!raw.next_cursor||cursors.has(raw.next_cursor))throw new ApiError('FACE_CHECK_INCOMPLETE','面检查未返回完整的后续范围，请重新检查。');
  cursors.add(raw.next_cursor);
  raw=await request<unknown>(endpoint+'&cursor='+encodeURIComponent(raw.next_cursor)+'&base_revision='+combined.base_revision,undefined,signal);
  const page=parseFaceScanReport(raw);
  if(page.base_revision!==combined.base_revision)throw new ApiError('FACE_CHECK_STALE','项目已更新，请重新检查。');
  combined={base_revision:combined.base_revision,scanned_face_count:combined.scanned_face_count+page.scanned_face_count,flagged_faces:[...combined.flagged_faces,...page.flagged_faces],truncated:page.truncated};
 }
 return combined;
}

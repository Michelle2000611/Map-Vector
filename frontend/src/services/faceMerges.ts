import {ApiError,request} from './client';
import type {components} from './generated';
export type FaceMergeMode=components['schemas']['ApplyFaceMerge']['mode'];
export type FaceMergeCapability=components['schemas']['FaceMergeCapabilityResponse'];
export type FaceMergeGapCandidate=components['schemas']['FaceMergeGapCandidateResponse'];
export type FaceMergePreview=components['schemas']['FaceMergePreviewResponse'];
export type FaceMergePreviewRequest=components['schemas']['FaceMergeRequest'];
const reasonLabels:Record<string,string>={FACE_MERGE_CONTEXT_LIMIT:'局部对象过多，请缩小检查范围',FACE_MERGE_CANDIDATE_LIMIT:'候选对象过多，请缩小检查范围',GEOMETRY_OUTSIDE_ASSET:'所选面超出原图范围，请先修正几何',RASTER_EVIDENCE_WINDOW_LIMIT:'原图局部采样达到上限，请人工核对',RASTER_INSUFFICIENT_SAMPLES:'局部像素样本不足，请人工核对',RASTER_EVIDENCE_AMBIGUOUS:'原图不能可靠确认连接口归属，请人工核对',RASTER_DARK_STROKE:'原图呈线状深色范围，请核对归属',SELECTION_DISCONNECTED:'所选对象仍有分离部件，无法合并为一个连续面',MULTIPART_NOT_REQUIRED:'所选面已连续，请使用“合并为一个面”',MIXED_ALGORITHM_LABELS:'识别标签不同，请确认归属并允许跨标签合并',DIFFERENT_SOURCE_APPEARANCE:'源面的颜色或样式不同，需核对属性来源',INDEPENDENT_GEOLOGICAL_BOUNDARY:'涉及独立地质分界线，请核对归属',RASTER_DISTINCT_SOURCE_REGIONS:'原图显示不同区域，请核对地质归属',RASTER_GEOLOGICAL_BOUNDARY:'原图可能存在真实地质分界线',MULTIPART_SAME_OBJECT:'请确认这些分离部件属于同一个地质对象',GAP_EXTENT_CONFIRMATION:'请核对并确认本次局部补缝范围',GAP_SELECTION_REQUIRED:'请明确选择局部补缝连接口',GAP_NOT_REQUIRED:'所选面已连续，无需补缝',GAP_RESULT_DISCONNECTED:'所选连接口不足以连成一个面',GAP_AREA_LIMIT:'补缝面积超过允许上限',OWNERSHIP_TRANSFER_CONFIRMATION_REQUIRED:'补缝涉及第三方面，请明确授权局部转移',THIRD_PARTY_OWNERSHIP_TRANSFER:'涉及第三方面的局部归属转移',PROTECTED_THIRD_PARTY:'局部连接口涉及受保护的第三方面',TRANSFER_WOULD_EMPTY_OWNER:'局部转移会清空第三方面，不能执行',TRANSFER_WOULD_SPLIT_OWNER:'局部转移会拆分第三方面，不能执行',TRANSFER_INVALID_REMAINDER:'局部转移后第三方面几何无效',TRANSFER_TINY_REMAINDER:'局部转移后会留下过小残片',GAP_SCALE_FALLBACK:'缺少可信尺度，使用保守宽度，请核对连接口',PATCH_OUTSIDE_ASSET:'连接口超出影像范围',PATCH_OUTSIDE_VALID_RASTER:'连接口超出有效原图范围',UNRESOLVED_FACE_OVERLAP:'所选范围存在未解决的面重叠',RASTER_EVIDENCE_UNAVAILABLE:'缺少局部原图依据，请人工核对',RASTER_BUDGET_EXHAUSTED:'局部原图采样达到上限，请人工核对',RASTER_REGION_DISTINCT:'连接口的原图颜色可能属于独立区域',RASTER_PATCH_NOT_STROKE:'原图无法确认连接口为细缝，请人工核对',PREVIEW_STALE:'预览已变化或过期，请重新检查',REVISION_CONFLICT:'项目版本已更新，请重新检查',GAP_CANDIDATE_SCOPE_INVALID:'所选连接口不属于当前预览，请重新检查',GAP_CANDIDATE_SOURCE_REQUIRED:'缺少连接口来源预览，请重新检查',GEOMETRY_VALIDATION_FAILED:'结果几何未通过检查，不能执行'};
export function faceMergeReason(code:string){return reasonLabels[code]??(/^[A-Z][A-Z0-9_]+$/.test(code)?'存在需人工核对的局部依据（'+code+'）':code);}
export async function createFaceMergePreview(projectId:string,body:FaceMergePreviewRequest,signal?:AbortSignal):Promise<FaceMergePreview>{
 try{
  const result=await request<FaceMergePreview>('/projects/'+encodeURIComponent(projectId)+'/face-merge-previews',body,signal,{quiet:true});
  // Older preview producers called occupied objects owners. Keep one UI shape.
  result.gap_candidates=result.gap_candidates.map(candidate=>{const raw=candidate as FaceMergeGapCandidate&{owner_feature_ids?:string[]};return {...candidate,occupying_feature_ids:candidate.occupying_feature_ids??raw.owner_feature_ids??[],transferred_area_px2:candidate.transferred_area_px2??candidate.ownership_transfers?.reduce((sum,item)=>sum+item.area_px2,0)};});
  return result;
 }catch(error){if(error instanceof ApiError){
  if((error.status===404||error.status===405)&&['HTTP_ERROR','404','405'].includes(error.code))throw new Error('当前后端尚未加载面合并检查接口，请重新启动后端后再检查。');
  const reasons=Array.isArray(error.detail.blocked_reasons)?error.detail.blocked_reasons.map(String).map(faceMergeReason):[];throw new Error(reasons.length?reasons.join('；'):reasonLabels[error.code]??error.message);
 }throw error;}
}
export function faceMergeCapabilityReason(mode:FaceMergeMode,capability:FaceMergeCapability|undefined):string{
 if(!capability)return '请勾选至少两个面并等待检查完成';
 if(!capability.eligible)return capability.blocked_reasons?.map(faceMergeReason).join('；')||'当前所选范围不满足此操作条件';
 if(capability.result_geometry?.type!==(mode==='multipart'?'MultiPolygon':'Polygon')||(mode==='multipart'?capability.output_component_count<2:capability.output_component_count!==1))return mode==='multipart'?'结果必须是一个包含至少两个部件的多部件面':'结果必须是一个连续的面';
 return '';
}

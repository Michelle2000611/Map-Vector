import type {CommandInput,Geometry} from './models';

export type FaceBatchCandidate={candidate_id:string;kind:'spur'|'void'|'occupied_hole'|'boundary_gap';geometry?:Geometry;area_px2?:number;receiver_options?:{feature_id:string;color?:string;shared_edge_px?:number}[];blocked_reason?:string;risk_level?:string;mergeable?:boolean;merging_feature_ids?:string[];review_required?:boolean;review_reason_codes?:string[];reference_text_ids?:string[];protected_feature_ids?:string[];raster_evidence?:{sha256?:string;status?:string};owner_raster_evidence?:{feature_id:string;sha256?:string}[]};
export type FaceBatchPlan={preview_id:string;feature_id:string;base_revision:number;expires_at:string;candidates:FaceBatchCandidate[]};
const semanticReasons=new Set(['PROTECTED_LINE_OR_TEXT','RESIDUE_KEPT']);
export function faceCandidateSelectable(item:FaceBatchCandidate){
 const semantic=semanticReasons.has(item.blocked_reason??'');
 if(item.risk_level==='blocked'&&!semantic)return false;
 if(item.kind==='occupied_hole'||item.kind==='boundary_gap')return item.mergeable===true&&!!item.merging_feature_ids?.length&&['OCCUPIED_HOLE_REQUIRES_MERGE','BOUNDARY_GAP_REQUIRES_REVIEW','RESIDUE_KEPT'].includes(item.blocked_reason??'');
 if(item.kind==='spur'&&!item.receiver_options?.length)return false;
 return !item.blocked_reason||semantic;
}
export function faceCandidateNeedsReview(item:Pick<FaceBatchCandidate,'kind'|'mergeable'|'merging_feature_ids'|'review_required'|'review_reason_codes'|'risk_level'|'blocked_reason'> & {raster_evidence?:{status?:string};owner_raster_evidence?:unknown[]}){
 const ownershipOnly=item.kind==='occupied_hole'&&item.mergeable===true&&item.review_required===false&&!item.review_reason_codes?.length&&(item.merging_feature_ids?.length===1||item.owner_raster_evidence?.length===item.merging_feature_ids?.length);
 const distinct=(item.kind==='void'||item.kind==='occupied_hole')&&['distinct_region','distinct_hole_region'].includes(item.raster_evidence?.status??'');
 return distinct||item.risk_level==='review'&&!ownershipOnly||item.review_required===true||item.kind==='boundary_gap'||semanticReasons.has(item.blocked_reason??'');
}
export function faceCandidateEvidence(item:FaceBatchCandidate){
 return JSON.stringify({candidate_id:item.candidate_id,kind:item.kind,geometry:item.geometry,blocked_reason:item.blocked_reason,mergeable:item.mergeable,merging_feature_ids:[...(item.merging_feature_ids??[])].sort(),receivers:(item.receiver_options??[]).map(option=>option.feature_id).sort(),reference_text_ids:[...(item.reference_text_ids??[])].sort(),protected_feature_ids:[...(item.protected_feature_ids??[])].sort(),raster_sha256:item.raster_evidence?.sha256,owner_raster_evidence:(item.owner_raster_evidence??[]).map(record=>({feature_id:record.feature_id,sha256:record.sha256})),review_required:item.review_required,review_reason_codes:[...(item.review_reason_codes??[])].sort()});
}
export function faceRepairBatchCommand(plan:Pick<FaceBatchPlan,'preview_id'|'feature_id'|'candidates'>,ids:string[],assignments:Record<string,string>):CommandInput{
 const selected=plan.candidates.filter(item=>ids.includes(item.candidate_id));
 if(!ids.length||selected.length!==ids.length||new Set(ids).size!==ids.length||selected.some(item=>!faceCandidateSelectable(item)))throw Error('所选面候选已变化，请重新检查并核对。');
 for(const item of selected)if(item.kind==='spur'&&!item.receiver_options?.some(option=>option.feature_id===assignments[item.candidate_id]))throw Error('请为每个线状附着明确选择接收面。');
 return {operation_type:'repair_face_geometry',feature_ids:[plan.feature_id],preview_id:plan.preview_id,candidate_ids:ids,
  assignments:Object.fromEntries(selected.filter(item=>item.kind==='spur').map(item=>[item.candidate_id,assignments[item.candidate_id]])),
  merge_occupied_candidate_ids:selected.filter(item=>item.kind==='occupied_hole'||item.kind==='boundary_gap').map(item=>item.candidate_id),
  verified_protected_candidate_ids:selected.filter(item=>semanticReasons.has(item.blocked_reason??'')).map(item=>item.candidate_id),
  verified_review_candidate_ids:selected.filter(item=>item.review_required).map(item=>item.candidate_id)} as CommandInput;
}

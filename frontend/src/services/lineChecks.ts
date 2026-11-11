import {ApiError,request} from './client';
import type {components} from './generated';
import type {CommandInput} from './models';

type Schema=components['schemas'];
export type LineCheckKind=Schema['LineCheckCandidate']['kind'];
export type LineCheckAction=Schema['LineCheckCandidate']['allowed_action'];
export type LineCheckCandidate=Omit<Schema['LineCheckCandidate'],'status'>&{status:Schema['LineCheckCandidate']['status']|'applied'}&Partial<Pick<Schema['LineCheckHistory'],'operation_id'|'result_revision'|'created_at'>>;
export type LineCheckReport=Omit<Schema['LineCheckReport'],'candidates'|'history'>&{candidates:LineCheckCandidate[];history:LineCheckCandidate[]};
export type LineCheckParameters=Required<Pick<Schema['LineCheckRequest'],'max_gap_px'|'angle_tolerance_deg'|'max_short_length_px'>>;
export type ApplyLineCheckInput=Extract<CommandInput,{operation_type:'apply_line_check'}>;
const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
const strings=(value:unknown):value is string[]=>Array.isArray(value)&&value.every(item=>typeof item==='string');
const numbers=(value:unknown):value is number[]=>Array.isArray(value)&&value.every(item=>typeof item==='number'&&Number.isFinite(item));
const actionFor:Record<LineCheckKind,LineCheckAction>={join_gap:'join',text_stroke:'isolate',dash_group:'group'};
function candidate(value:unknown,history=false):LineCheckCandidate|null{
 if(!object(value)||typeof value.candidate_id!=='string'||!value.candidate_id||!['join_gap','text_stroke','dash_group'].includes(String(value.kind))||!strings(value.feature_ids)||!value.feature_ids.length||!numbers(value.bounds_px)||value.bounds_px.length!==4)return null;
 const kind=value.kind as LineCheckKind;
 if(value.allowed_action!==actionFor[kind]||!['pending','kept',...(history?['applied']:[])].includes(String(value.status))||!strings(value.reason_codes)||!strings(value.blocked_reasons)||!strings(value.reference_text_ids)||!Array.isArray(value.connectors)||!value.connectors.every(segment=>Array.isArray(segment)&&segment.length===2&&segment.every(point=>numbers(point)&&point.length===2)))return null;
 return {...value,kind,metrics:object(value.metrics)?Object.fromEntries(Object.entries(value.metrics).filter((entry):entry is [string,number]=>typeof entry[1]==='number'&&Number.isFinite(entry[1]))):{}} as LineCheckCandidate;
}
export function parseLineCheckReport(value:unknown):LineCheckReport{
 const invalid=()=>new ApiError('LINE_CHECK_INVALID_RESPONSE','线检查返回的数据格式异常，请重新检查。');
 if(!object(value)||typeof value.preview_id!=='string'||!value.preview_id||typeof value.asset_id!=='string'||!Number.isSafeInteger(value.base_revision)||typeof value.expires_at!=='string'||!Number.isFinite(Date.parse(value.expires_at))||!Array.isArray(value.candidates))throw invalid();
 const candidates=value.candidates.map(item=>candidate(item));
 if(candidates.some(item=>!item)||new Set(candidates.map(item=>item!.candidate_id)).size!==candidates.length)throw invalid();
 return {preview_id:value.preview_id,asset_id:value.asset_id,base_revision:value.base_revision as number,algorithm_revision:String(value.algorithm_revision??''),expires_at:value.expires_at,input_sha256:String(value.input_sha256??''),candidates:candidates as LineCheckCandidate[],history:Array.isArray(value.history)?value.history.map(item=>candidate(item,true)).filter((item):item is LineCheckCandidate=>!!item&&item.status==='applied'):[],summary:object(value.summary)?Object.fromEntries(Object.entries(value.summary).filter((entry):entry is [string,number|boolean]=>typeof entry[1]==='boolean'||typeof entry[1]==='number'&&Number.isFinite(entry[1]))):{}};
}
export async function inspectLines(projectId:string,assetId:string,revision:number,parameters:LineCheckParameters,signal:AbortSignal){
 return parseLineCheckReport(await request<unknown>('/projects/'+projectId+'/line-check-previews',{asset_id:assetId,base_revision:revision,...parameters},signal,{quiet:true}));
}
export async function decideLines(projectId:string,assetId:string,report:LineCheckReport,candidateIds:string[],decision:'keep'|'reopen',signal:AbortSignal){
 const result=await request<{candidate_ids:string[];decision:string}>('/projects/'+projectId+'/line-check-decisions',{asset_id:assetId,base_revision:report.base_revision,preview_id:report.preview_id,candidate_ids:candidateIds,decision},signal,{quiet:true});
 if(!result||result.decision!==decision||!strings(result.candidate_ids)||result.candidate_ids.length!==candidateIds.length||candidateIds.some(id=>!result.candidate_ids.includes(id)))throw new ApiError('LINE_CHECK_INVALID_RESPONSE','线检查决定未返回完整结果，请重新检查。');
 return result;
}

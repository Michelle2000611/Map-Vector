import {request} from './client';
import type {Feature,Roi} from './models';
export type Bounds=[number,number,number,number];
export type ScopeMode='full'|'keep_crossing'|'clip';
export type DeliveryRoi=Roi&{scope_mode?:Exclude<ScopeMode,'full'>};
export type CheckContext={asset_id:string;working_revision:number;rule_version:string;coordinate_space:string};
export type DeliveryIssue={issue_id:string;code:string;severity:'error'|'review';feature_ids:string[];bounds_px:Bounds|null;message:string;area_px2?:number};
export type QualityCheck=CheckContext&{quality_report:{face_count:number;geometry_count?:number;valid_geometry_count:number;invalid_geometry_count?:number;area_statistics_complete?:boolean;coverage_is_valid:boolean|null;target_area_px2:number;covered_area_px2:number;uncovered_area_px2:number;overlap_area_px2:number;tolerance_px2:number;note:string};issues:DeliveryIssue[];issue_count:number;issues_truncated:boolean;check_complete?:boolean;issue_count_exact?:boolean;checked_pair_count?:number};
export type RangeAudit=CheckContext&{roi:Roi;roi_revision:number;counts:Record<'face'|'line'|'text',{inside:number;crossing:number;outside:number}>};
export type RangePreview=CheckContext&{roi_id:string;roi_revision:number;keep_crossing:Feature[];clip:Feature[]};
export type SnapshotScope={snapshot_id:string;asset_id:string;working_revision:number;coordinate_space:string;roi:DeliveryRoi|null};
const object=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const count=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
export function isBounds(v:unknown):v is Bounds{return Array.isArray(v)&&v.length===4&&v.every(finite)&&v[0]<v[2]&&v[1]<v[3];}
export function roiBounds(roi:Roi|null):Bounds|null{
 if(!roi||roi.geometry.type!=='Polygon')return null;
 const ring=roi.geometry.coordinates[0];if(!ring?.length)return null;
 const xs=ring.map(p=>p[0]),ys=ring.map(p=>p[1]),b=[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];return isBounds(b)?b:null;
}
function invalid():never{throw new Error('检查数据格式不完整，请确认后端已更新后重试。');}
function context(data:unknown,assetId:string,revision:number):asserts data is CheckContext&Record<string,unknown>{
 if(!object(data)||data.asset_id!==assetId||data.working_revision!==revision||typeof data.rule_version!=='string'||data.coordinate_space!=='pixel')invalid();
}
export async function checkQuality(projectId:string,assetId:string,revision:number,signal:AbortSignal):Promise<QualityCheck>{
 const data=await request<unknown>(`/projects/${projectId}/quality?asset_id=${assetId}&base_revision=${revision}`,undefined,signal,{quiet:true});context(data,assetId,revision);
 const q=data.quality_report;if(!object(q)||!['face_count','valid_geometry_count'].every(k=>count(q[k]))||!['target_area_px2','covered_area_px2','uncovered_area_px2','overlap_area_px2','tolerance_px2'].every(k=>finite(q[k])&&(q[k] as number)>=0)||![true,false,null].includes(q.coverage_is_valid as boolean|null))invalid();
 if(!Array.isArray(data.issues)||!count(data.issue_count)||typeof data.issues_truncated!=='boolean'||data.issue_count<data.issues.length||(!data.issues_truncated&&data.issue_count!==data.issues.length))invalid();
 const ids=new Set<string>();for(const issue of data.issues){if(!object(issue)||typeof issue.issue_id!=='string'||ids.has(issue.issue_id)||typeof issue.code!=='string'||!['error','review'].includes(String(issue.severity))||typeof issue.message!=='string'||!Array.isArray(issue.feature_ids)||!issue.feature_ids.length||issue.feature_ids.some(id=>typeof id!=='string')||(issue.bounds_px!==null&&!isBounds(issue.bounds_px)))invalid();ids.add(issue.issue_id);}
 return data as QualityCheck;
}
export async function checkRange(projectId:string,assetId:string,revision:number,roi:Roi,signal:AbortSignal):Promise<{audit:RangeAudit;preview:RangePreview}>{
 const body={asset_id:assetId,roi_id:roi.roi_id,base_revision:revision};
 const [audit,preview]=await Promise.all([request<unknown>(`/projects/${projectId}/roi-audits`,body,signal,{quiet:true}),request<unknown>(`/projects/${projectId}/roi-previews`,body,signal,{quiet:true})]);
 context(audit,assetId,revision);context(preview,assetId,revision);
 if(!object(audit.roi)||audit.roi.roi_id!==roi.roi_id||audit.roi_revision!==roi.revision||!object(audit.counts)||preview.roi_id!==roi.roi_id||preview.roi_revision!==roi.revision)invalid();
 for(const kind of ['face','line','text']){const c=audit.counts[kind];if(!object(c)||!['inside','crossing','outside'].every(k=>count(c[k])))invalid();}
 for(const mode of ['keep_crossing','clip']){const rows=preview[mode];if(!Array.isArray(rows))invalid();const ids=new Set<string>();for(const f of rows){if(!object(f)||typeof f.feature_id!=='string'||ids.has(f.feature_id)||!['face','line','text'].includes(String(f.feature_type))||!object(f.geometry)||typeof f.geometry.type!=='string'||!Array.isArray(f.geometry.coordinates))invalid();ids.add(f.feature_id);}}
 return {audit:audit as RangeAudit,preview:preview as RangePreview};
}
export async function snapshotScope(projectId:string,snapshotId:string,signal:AbortSignal):Promise<SnapshotScope>{
 const data=await request<unknown>(`/projects/${projectId}/snapshots/${snapshotId}/scope`,undefined,signal,{quiet:true});
 if(!object(data)||data.snapshot_id!==snapshotId||typeof data.asset_id!=='string'||!count(data.working_revision)||data.coordinate_space!=='pixel'||(data.roi!==null&&(!object(data.roi)||!roiBounds(data.roi as DeliveryRoi)||data.roi.asset_id!==data.asset_id||!['clip','keep_crossing'].includes(String(data.roi.scope_mode)))))invalid();
 return data as SnapshotScope;
}

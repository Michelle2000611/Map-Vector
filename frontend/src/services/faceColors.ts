import {ApiError,request} from './client';
import type {components} from './generated';

export type FaceColorMode=NonNullable<components['schemas']['FaceColorRequest']['mode']>;
export type FaceColorMatch=components['schemas']['FaceColorMatch'];
export type FaceColorReport=components['schemas']['FaceColorReport'];
export type FaceColorInput=Required<components['schemas']['FaceColorRequest']>;
const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
const color=(value:unknown):value is string=>typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value);
const count=(value:unknown):value is number=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0;
export function parseFaceColorReport(value:unknown):FaceColorReport{
 const invalid=()=>new ApiError('FACE_COLOR_INVALID_RESPONSE','颜色查找返回的数据异常，请重新检查。');
 if(!object(value)||typeof value.asset_id!=='string'||!value.asset_id||!count(value.base_revision)||typeof value.source_feature_id!=='string'||!value.source_feature_id||!color(value.source_color)||!['exact','similar'].includes(String(value.mode))||typeof value.tolerance!=='number'||!Number.isFinite(value.tolerance)||value.tolerance<0||value.tolerance>100||!count(value.scanned_face_count)||!count(value.invalid_color_count)||!count(value.match_count)||!Array.isArray(value.matches)||value.matches.length!==value.match_count||value.scanned_face_count<value.match_count+value.invalid_color_count)throw invalid();
 const ids=new Set<string>(),matches:FaceColorMatch[]=[];
 for(const entry of value.matches){
  if(!object(entry)||typeof entry.feature_id!=='string'||!entry.feature_id||ids.has(entry.feature_id)||!color(entry.fill_color)||typeof entry.delta_e!=='number'||!Number.isFinite(entry.delta_e)||entry.delta_e<0||!['exact','similar'].includes(String(entry.match_type)))throw invalid();
  const exact=entry.fill_color.toLowerCase()===value.source_color.toLowerCase();
  if(exact!==(entry.match_type==='exact')||exact&&entry.delta_e!==0||!exact&&entry.delta_e===0||entry.delta_e>value.tolerance+1e-9||value.mode==='exact'&&(!exact||value.tolerance!==0))throw invalid();
  ids.add(entry.feature_id);matches.push({feature_id:entry.feature_id,fill_color:entry.fill_color.toLowerCase(),delta_e:entry.delta_e,match_type:entry.match_type as FaceColorMode});
 }
 if(!matches.some(item=>item.feature_id===value.source_feature_id&&item.match_type==='exact'))throw invalid();
 return {asset_id:value.asset_id,base_revision:value.base_revision,source_feature_id:value.source_feature_id,source_color:value.source_color.toLowerCase(),mode:value.mode as FaceColorMode,tolerance:value.tolerance,scanned_face_count:value.scanned_face_count,invalid_color_count:value.invalid_color_count,match_count:value.match_count,matches};
}
export async function searchFaceColors(projectId:string,input:FaceColorInput,signal:AbortSignal){return parseFaceColorReport(await request<unknown>('/projects/'+projectId+'/face-color-searches',input,signal,{quiet:true}));}

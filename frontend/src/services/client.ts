import type {components} from './generated';
import {projectRequestSignal} from './session';
import {beginLoading,requestLoadingLabel} from './loading';
export type EditCommand=import('./generated').paths['/api/projects/{project_id}/edit-commands']['post']['requestBody']['content']['application/json'];

const messages:Record<string,string>={REPAIR_REVIEW_REQUIRED:'请先核对所选候选，确认区域归属及线、文字表达后再应用。',REPAIR_REVIEW_CONFIRMATION_INVALID:'核对确认与当前候选不匹配，请重新检查当前面。',REPAIR_SELECTION_OVERLAP:'所选修复范围存在重叠，请选择不重叠的候选后再应用。',REPAIR_MERGE_CONFIRMATION_INVALID:'内部碎面归属与当前候选不匹配，请重新检查当前面。',REPAIR_CANDIDATE_INVALID:'所选修复候选已变化，请重新检查面几何。',REPAIR_CANDIDATE_BLOCKED:'该候选涉及受保护对象或已占用面，当前未修改。',REPAIR_RECEIVER_REQUIRED:'请为每个线状附着选择接收面。',REPAIR_RECEIVER_INVALID:'接收面不符合共边与覆盖规则，请重新选择。',REPAIR_NO_CHANGE:'当前选择没有可应用的面几何修改。',GEOREFERENCE_PAIR_REQUIRED:'外部配准需要同时提供 World 文件和 CRS 文件。',GEOREFERENCE_INVALID:'配准文件格式或坐标信息无效。',GEOREFERENCE_CONFLICT:'影像自带配准与外部文件冲突，请核对文件，不会自动覆盖。',OCR_POSITION_CONFLICT:'该位置已有其他读法，请定位原对象并明确更新。',OCR_DUPLICATE_TEXT:'同一位置已有相同文字，请定位原对象或明确更新，避免重复新增。',TEXT_TARGET_REQUIRED:'无法确定对应的单条文字，请缩小范围后重试。',RESIDUE_ALREADY_CLEAN:'当前检查框已无待清理痕迹。',RESIDUE_GROUND_UNRESOLVED:'部分碎面缺少可相接的背景面，整次清理已取消，请检查图形归属。',RESIDUE_CLEANUP_INCOMPLETE:'复查发现仍有残影，本次清理已回滚，请检查预览范围。',REVISION_CONFLICT:'数据已经更新，请保留选择并重新加载。',PREVIEW_STALE:'预览已过期，请重新预览。',PREVIEW_REQUIRED:'该操作必须先预览并检查受影响对象。',PREVIEW_TYPE_MISMATCH:'预览与所请求的操作类型不匹配，请重新预览。',IDEMPOTENCY_CONFLICT:'同一请求键已用于不同的操作；请重新提交并使用新请求键。',FACES_NOT_EDGE_CONNECTED:'所选面不通过共享边连成一组，请按相连组分别合并或逻辑归组。',DASH_JOIN_FORBIDDEN:'虚线间隔受保护，可使用逻辑归组。',ASSET_RESULT_MISMATCH:'影像与结果的资产证据不匹配。',FORMAL_REVIEW_INCOMPLETE:'仍有被当前政策阻断的文字，请查看审核队列。',FORMAL_OUTSIDE_ROI:'ROI 外仍有对象，正式输出必须明确保留跨界、裁切或处理范围。',EXPORT_SCOPE_INVALID:'范围参数无效，请保存包含该 ROI 的快照。',EXPORT_EMPTY_SHAPEFILE:'所选范围没有 Shapefile 对象，请修改图层或范围。',EXPORT_POLICY_UNAVAILABLE:'该导出政策尚未启用。',CONTRACT_REVISION_UNSUPPORTED:'客户端契约修订不受支持，请刷新页面或升级客户端。',OCR_ENGINE_UNAVAILABLE:'OCR 引擎或本地模型不可用。',OCR_TIMEOUT:'OCR 运行超时，可重试或手工补字。',OCR_TARGET_INVALID:'请先选择同一项目、同一资产的有效文字。',GEOMETRY_VALIDATION_FAILED:'几何校验失败，本次修改已回滚。',WORKING_FEATURES_EXIST:'本项目已有编辑内容，请选择“替换本项目的编辑内容”或“另建项目保存”。'};
Object.assign(messages, {
 LINE_REVIEW_REQUIRED: '请先查看当前文字残影，并核对需要处理的线段。',
 LINE_REVIEW_FORBIDDEN: '所选线段已保留或涉及受保护地质线，本次未修改。',
 LINE_REVIEW_MISMATCH: '确认的线段与当前预览不一致，请重新查看残影。',
 PREVIEW_SCOPE_MISMATCH: '预览范围或所属文字已变化，请重新查看当前文字残影。',
 RESIDUE_SPLIT_RESTORE_REQUIRES_UNDO: '这条线已保留框外部分，请撤销对应的残影清理来恢复完整原线，避免产生重复线。',
 LINE_CHECK_REVIEW_REQUIRED: '请先核对所选线候选，确认处理方式后再应用。',
 LINE_CHECK_CANDIDATE_INVALID: '所选线候选已变化，请重新检查当前线层。',
 LINE_CHECK_ACTION_MISMATCH: '处理方式与所选候选不一致，请分别处理不同类型的候选。',
 LINE_CHECK_CANDIDATE_BLOCKED: '所选候选涉及受保护线或连接歧义，本次未修改。请查看候选中的保护原因。',
 LINE_CHECK_CANDIDATE_KEPT: '所选候选已标记为保留，请先选择重新核对。',
 LINE_CHECK_SELECTION_OVERLAP: '所选候选使用了相同的线，不能同时应用。请分组处理，本次未修改。',
});
export class ApiError extends Error {constructor(public code:string,message:string,public detail:Record<string,unknown>={}){super(message);}}
export type RequestOptions={quiet?:boolean};
export async function request<T=unknown>(path:string,body?:unknown,signal?:AbortSignal,options:RequestOptions={}):Promise<T>{
 signal=signal??(path.startsWith('/projects/')?projectRequestSignal():undefined);
 const label=options.quiet?undefined:requestLoadingLabel(path,body),finish=label?beginLoading(label):()=>{};
 try{
 const response=await fetch('/api'+path,body===undefined?{signal}:{signal,method:'POST',headers:body instanceof FormData?{}:{'Content-Type':'application/json'},body:body instanceof FormData?body:JSON.stringify(body)});
 const text=await response.text();
 let parsed:unknown=null;
 try{if(text.trim())parsed=JSON.parse(text);}catch{/* Report malformed responses below without leaking a JSON parser error. */}
 const result=parsed&&typeof parsed==='object'&&!Array.isArray(parsed)?parsed as Record<string,unknown>:null;
 if(!response.ok){
  const code=typeof result?.code==='string'?result.code:String(response.status);
  const fallback=response.status>=500?'后端服务暂时不可用，请确认服务已启动后重试。':'请求失败，请稍后重试。';
  const message=messages[code]??(typeof result?.message==='string'?result.message:fallback);
  const detail=result?.detail&&typeof result.detail==='object'&&!Array.isArray(result.detail)?result.detail as Record<string,unknown>:{status:response.status,path};
  throw new ApiError(code,message+' ('+code+')',detail);
 }
 if(!text.trim())throw new ApiError('API_EMPTY_RESPONSE','服务返回了空响应，请刷新重试；若仍失败，请检查后端服务。',{status:response.status,path});
 if(!result||!Object.prototype.hasOwnProperty.call(result,'data'))throw new ApiError('API_INVALID_RESPONSE','服务返回的数据格式异常，请刷新重试；若仍失败，请检查后端服务。',{status:response.status,path});
 return result.data as T;
 }finally{finish();}
}

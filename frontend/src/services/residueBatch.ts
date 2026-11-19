import {ApiError,request} from './client';
import type {Command,Preview} from './models';

type ReviewDisplay=NonNullable<Preview['text_residue_display']>;
export type ResidueBatchItem={textId:string;textValue:string;review?:Preview;plan?:Preview;approvedIds:string[];faceCount:number;lineCount:number;protectedCount:number;status:'review'|'ready'|'empty'|'blocked'|'cleaned'|'partial';message?:string};
export type ResidueBatchContext={projectId:string;assetId:string;revision:()=>number;current:()=>boolean};
const unique=(ids:string[])=>[...new Set(ids)];
export function residueBatchIds(display:ReviewDisplay){return unique([...display.face_feature_ids,...(display.protected_face_feature_ids??[]),...display.line_feature_ids,...display.protected_line_feature_ids]);}
function assertCurrent(context:ResidueBatchContext,revision:number){if(!context.current())throw new DOMException('已切换项目或原图，本次批量操作已停止。','AbortError');if(context.revision()!==revision)throw Error('项目已更新，请重新核对所选残影。');}
function validatePreview(context:ResidueBatchContext,preview:Preview,textId:string,revision:number,complete:boolean){
 assertCurrent(context,revision);
 if(preview.preview_type!=='text_residue'||preview.feature_ids.length!==1||preview.feature_ids[0]!==textId||preview.base_revision!==revision||!preview.text_residue_display?.preserves_existing_text)throw Error('残影检查范围已变化，请重新核对。');
 if(preview.expires_at&&Date.parse(preview.expires_at)<=Date.now())throw Error('残影检查已过期，请重新核对。');
 if(complete&&(!preview.text_residue_display.complete_region||!preview.cleanup_preview))throw Error('缺少完整清理方案，请重新核对。');
}
async function preview(context:ResidueBatchContext,textId:string,complete=false){
 const revision=context.revision();assertCurrent(context,revision);
 const result=await request<Preview>('/projects/'+context.projectId+'/edit-previews',{asset_id:context.assetId,base_revision:revision,preview_type:'text_residue',feature_ids:[textId],...(complete?{complete_region:true,face_assignments:{}}:{})},undefined,{quiet:true});
 validatePreview(context,result,textId,revision,complete);return result;
}
function remaining(plan:Preview){
 const display=plan.text_residue_display!,cleaned=new Set([...display.cleanup_face_feature_ids,...display.cleanup_line_feature_ids]),unresolved=new Set(display.unresolved_face_feature_ids??[]);
 return {unresolved:unresolved.size,review:residueBatchIds(display).filter(id=>!cleaned.has(id)&&!unresolved.has(id)).length};
}
export function residueCleanupMessage(plan:Preview,cleaned=false){
 const pending=remaining(plan),notes=[];
 if(cleaned)notes.push('已清理可处理残影');
 if(pending.review)notes.push('另有 '+pending.review+' 项受保护、已保留或待核对对象，请先确认核对后再清理');
 if(pending.unresolved)notes.push('另有 '+pending.unresolved+' 个碎面无法归并，未修改');
 return notes.length?notes.join('；'):undefined;
}
const message=(error:unknown)=>error instanceof ApiError&&error.code==='RESIDUE_GROUND_AMBIGUOUS'?'当前后端尚未加载自动清理功能，需要重新加载后端后再检查。':error instanceof Error?error.message:String(error);
/** Read each text independently; selection is not a geometry or protection override. */
export async function prepareResidueBatch(context:ResidueBatchContext,texts:{textId:string;textValue:string}[],onProgress?:(index:number)=>void){
 const revision=context.revision(),items:ResidueBatchItem[]=[];
 for(const [index,text] of texts.entries()){
  assertCurrent(context,revision);onProgress?.(index);
  const item:ResidueBatchItem={...text,approvedIds:[],faceCount:0,lineCount:0,protectedCount:0,status:'review'};
  try{const review=await preview(context,text.textId),display=review.text_residue_display!;item.review=review;item.approvedIds=residueBatchIds(display);item.faceCount=unique(display.face_feature_ids).length;item.lineCount=unique([...display.line_feature_ids,...display.protected_line_feature_ids]).length;item.protectedCount=unique([...(display.protected_face_feature_ids??[]),...display.protected_line_feature_ids]).length;if(!item.approvedIds.length)item.status='empty';}
  catch(error){assertCurrent(context,revision);item.status='blocked';item.message=message(error);}
  items.push(item);
 }
 return items;
}
/** Confirmation is persisted through the same shared decision endpoint used by object review. */
export async function confirmResidueBatch(context:ResidueBatchContext,items:ResidueBatchItem[],onProgress?:(index:number)=>void){
 const revision=context.revision(),result:ResidueBatchItem[]=[];
 for(const [index,original] of items.entries()){
  assertCurrent(context,revision);onProgress?.(index);const item={...original};
  if(item.status==='blocked'||item.status==='empty'){result.push(item);continue;}
  try{
   let review=await preview(context,item.textId);const currentIds=residueBatchIds(review.text_residue_display!);
   if(currentIds.some(id=>!item.approvedIds.includes(id)))throw Error('关联残影已变化，请重新核对该文字。');
   // Decisions change shared evidence, so acquire a fresh review before each
   // chunk rather than reusing a preview invalidated by an earlier decision.
   for(let offset=0;offset<currentIds.length;offset+=2000){
    if(offset)review=await preview(context,item.textId);
    assertCurrent(context,revision);
    await request('/projects/'+context.projectId+'/text-residue-decisions',{asset_id:context.assetId,base_revision:revision,preview_id:review.preview_id,feature_ids:currentIds.slice(offset,offset+2000),decision:'confirm'},undefined,{quiet:true});
    assertCurrent(context,revision);
   }
   item.review=await preview(context,item.textId);item.plan=await preview(context,item.textId,true);
   const pending=remaining(item.plan);
   item.status=item.plan.cleanup_preview!.has_changes?'ready':pending.review?'review':pending.unresolved?'blocked':'empty';
   item.message=residueCleanupMessage(item.plan,false);
  }catch(error){assertCurrent(context,revision);item.status='blocked';item.message=message(error);}
  result.push(item);
 }
 return result;
}
/** Each command commits independently. Rebuild after every preceding revision,
 * including overlapping text scopes; never submit the batch's old previews. */
export async function cleanupResidueBatch(context:ResidueBatchContext,items:ResidueBatchItem[],command:Command,onProgress?:(index:number)=>void){
 const result=items.map(item=>({...item}));
 for(const [index,item] of result.entries()){
  if(!context.current())throw new DOMException('已切换项目或原图，本次批量操作已停止。','AbortError');
  if(!['review','ready','partial'].includes(item.status))continue;onProgress?.(index);
  const revision=context.revision();let submitted=false;
  try{
   const review=await preview(context,item.textId);
   if(residueBatchIds(review.text_residue_display!).some(id=>!item.approvedIds.includes(id)))throw Error('前序清理改变了关联残影，请重新核对该文字。');
   const plan=await preview(context,item.textId,true);item.review=review;item.plan=plan;
   if(!plan.cleanup_preview!.has_changes){const pending=remaining(plan);item.status=pending.review?'review':pending.unresolved?'blocked':'empty';item.message=residueCleanupMessage(plan,false);continue;}
   const display=plan.text_residue_display!;
   if([...display.cleanup_face_feature_ids,...display.cleanup_line_feature_ids].some(id=>!item.approvedIds.includes(id)))throw Error('清理方案出现未核对的对象，请重新核对该文字。');
   validatePreview(context,plan,item.textId,revision,true);
   submitted=true;
   const changed=await command({operation_type:'cleanup_text_residue',preview_id:plan.preview_id,complete_region:true,face_assignments:{}},{quiet:true});
   if(!changed)throw Error('清理尚未提交，本次批量操作已停止。');
   if(!context.current())throw new DOMException('已切换项目或原图，本次批量操作已停止。','AbortError');
   if(context.revision()!==changed.result_revision)throw Error('提交后项目又发生变化，请重新检查剩余文字。');
   const pending=remaining(plan);item.status=pending.review||pending.unresolved?'partial':'cleaned';item.message=residueCleanupMessage(plan,item.status==='partial');
  }catch(error){
   if(!context.current())throw error;
   item.status='blocked';item.message=message(error);
   // A rejected read has no geometry side effects; other text scopes can still
   // proceed. A command/foreign revision failure must stop the remaining queue.
   if(submitted||context.revision()!==revision){
    for(const remaining of result.slice(index+1))if(['review','ready','partial'].includes(remaining.status)){remaining.status='blocked';remaining.message='批量清理已停止，请重新检查。';}break;
   }
  }
 }
 return result;
}

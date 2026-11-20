import {mergeResidueAssessment,publishResidueUpdate,replaceResidueAssessments,residueRevisionCovered} from '../services/residueUpdates';
import {ReasonList} from './ReasonList';
import {useEffect,useId,useRef,useState} from 'react';
import type {TextResidueReview} from './GlobalResidueTools';
import {FeaturePreview} from './FeaturePreview';
import {Alert,Button,Checkbox,InputNumber,Modal,Segmented,Table,Tabs,Tag,Tooltip} from 'antd';
import {InspectionStatus} from './InspectionStatus';
import type {TableColumnsType} from 'antd';
import {request} from '../services/client';
import {useWorkspace} from '../stores/workspace';
import type {Asset,Candidate,Command,CommandInput,EditResult,Page,Project,TextFeature,TextLayerAssessment as Assessment,TextLayerAssessmentReport as Report,Work} from '../services/models';
import './TextReviewPanel.css';
import {matchesResidueFilter,residueState,TEXT_REVIEW_PAGE_SIZE,useReviewPanelVisible,useTextReviewReveal} from './textReviewReveal';
import type {TextReviewFilter,TextReviewRevealRequest} from './textReviewReveal';
import {statusColor} from './statusTags';
import {TextInformationPanel} from './TextInformationPanel';
import {prepareResidueBatch,confirmResidueBatch,cleanupResidueBatch} from '../services/residueBatch';
import type {ResidueBatchItem,ResidueBatchContext} from '../services/residueBatch';

const labels:Record<string,string>={required:'待核对',auto_accepted_unverified:'自动通过（未人工确认）',confirmed:'已确认',manual_edited:'人工修改（待核对）',skipped:'稍后处理',pipeline_complete_unverified:'流程通过（未人工确认）'};
const reasons:Record<string,string>={protected_face_source_scope:'字形碎面较大或超出可靠文字范围，暂不清理',protected_face_independent_line:'碎面涉及独立线，暂不清理',layout_fit_uncertain:'文字排版依据不足',ocr_spatial_conflict:'识别范围重叠，需核对采用结果',script_position_uncertain:'上下标位置需核对',no_ocr_evidence:'缺少 OCR 依据',low_ocr_score:'OCR 分数偏低',stratigraphic_or_lithology_code:'地质代号需核对',sub_or_superscript:'上下标或字母数字组合',numeric_or_short:'数字注记需核对',rotated_or_vertical:'旋转或竖排文字',orientation_measurement:'方位或角度数值需核对',special_symbol:'特殊符号',ocr_engine_disagreement:'两种引擎结果不同',text_changed_from_ocr:'采用文字与原识别不同',empty_text:'内容为空',suspected_text_faces:'疑似文字碎面',suspected_text_lines:'疑似文字残线',protected_boundary_or_crossing_line:'存在需保护的跨框线或边界',no_detection_quad:'缺少检测范围，无法检查残影；请人工定位'};
const candidateReasons:Record<string,string>={OCR_SPATIAL_CONFLICT:'识别范围重叠，需核对采用结果',OCR_ENGINE_DISAGREEMENT:'识别读法存在分歧'};
function candidateReasonTexts(candidate:Candidate){
 const items=candidate.rule_suggestions.flatMap(suggestion=>typeof suggestion==='object'&&suggestion!==null&&'reason_codes' in suggestion&&Array.isArray(suggestion.reason_codes)?suggestion.reason_codes.map(code=>candidateReasons[String(code)]??String(code)):[]).filter(Boolean);
 return items.length?items:['需对照原图'];
}

type Props={project:Project;asset:Asset;busy:boolean;work:Work;command:Command;focus:(id:string,residue?:boolean)=>void;revealRequest?:TextReviewRevealRequest;onReviewResidue?:(id:string)=>void;residueReview?:TextResidueReview};
type LayoutPreview={base_revision:number;asset_id:string;input_sha256:string;updated_count:number;skipped_count:number;review_required_count:number;changes:{feature_id:string;text_value:string;before:TextFeature;after:TextFeature}[]};
type Filter=TextReviewFilter;
const filters:{value:Filter;label:string}[]=[{value:'required',label:'待核对'},{value:'kept',label:'已保留'},{value:'none',label:'未发现'},{value:'all',label:'全部'}];
// Status words are shared with the face/line panels (see statusTags.ts); text-only wording is mapped onto them.
const tagLabels:Record<string,string>={required:'待核对',manual_edited:'待核对',skipped:'待核对',confirmed:'已确认',auto_accepted_unverified:'自动通过',pipeline_complete_unverified:'流程通过'};
const statusLabel=(f:TextFeature)=>tagLabels[f.review_status]??labels[f.review_status]??f.review_status;
const score=(n:number|null|undefined)=>typeof n==='number'?(n*100).toFixed(1)+'%':'无依据';
type Inspection={ticket:string;report:Report};
type CleanupBatch={scope:string;revision:number;stage:'review'|'confirmed'|'done';items:ResidueBatchItem[]};

function residueEvidence(item:Assessment|undefined){
 if(!item)return <span className="text-review-unchecked">未检查</span>;
 const detail=<ReasonList items={[...item.reasons.map(reason=>reasons[reason]??reason),...(item.protected_line_ids.length>0?['受保护对象暂不自动清理，人工确认核对后可参与清理。']:[])]}/>;
 if(item.region_source==='missing')return <Tooltip title={detail}><span>需人工定位</span></Tooltip>;
 if(item.cleanup_status!=='review_required'&&item.cleanup_status!=='no_suspects')return <span>检查结果不完整</span>;
 return <Tooltip title={item.reasons.length?detail:undefined}><div className="text-review-residue">
  {residueState(item)==='none'?<span>未发现残影</span>:<div className="text-review-residue-counts"><span>碎面 {item.suspected_face_ids.length}</span><span>线段 {item.suspected_line_ids.length}</span></div>}
  {item.protected_line_ids.length>0&&<small>保护线 {item.protected_line_ids.length}</small>}
 </div></Tooltip>;
}

export function TextReviewPanel({project,asset,busy,work,command,focus,revealRequest,onReviewResidue,residueReview}:Props){
 const session=useWorkspace(state=>state.session),detailsId=useId();
 const residueUpdates=useWorkspace(state=>state.residueUpdates);
 const relevantUpdates=residueUpdates.filter(item=>item.projectId===project.project_id&&item.session===session&&item.asset_id===asset.asset_id);
 const [filter,setFilter]=useState<Filter>('required'),[rows,setRows]=useState<TextFeature[]>([]),[candidates,setCandidates]=useState<Candidate[]>([]),[threshold,setThreshold]=useState(90),[moreOpen,setMoreOpen]=useState(false),[page,setPage]=useState(1),[inspection,setInspection]=useState<Inspection|null>(null),[selected,setSelected]=useState<string[]>([]),[error,setError]=useState(''),[inspectionError,setInspectionError]=useState('');
 const [category,setCategory]=useState<'residue'|'information'>('residue');
 const [batch,setBatch]=useState<CleanupBatch|null>(null),[batchPhase,setBatchPhase]=useState<'idle'|'preparing'|'confirming'|'cleaning'>('idle'),[batchProgress,setBatchProgress]=useState(0),[batchTotal,setBatchTotal]=useState(0),[batchMessage,setBatchMessage]=useState('');
 const batchBusy=useRef(false),batchGeneration=useRef(0);
 const batchPending=batchPhase!=='idle',locked=busy||!!residueReview?.locked||batchPending;
 const [layoutPreview,setLayoutPreview]=useState<LayoutPreview|null>(null),[layoutChecking,setLayoutChecking]=useState(false);
 const prefix='/projects/'+project.project_id,scope=JSON.stringify([project.project_id,asset.asset_id,session]),ticket=JSON.stringify([scope,project.working_revision]);
 const panel=useRef<HTMLDivElement>(null),visible=useReviewPanelVisible(panel);
 const loadedRevision=useRef<{scope:string;revision:number}|null>(null);
 const [loadedTicket,setLoadedTicket]=useState<string|null>(null),[showOriginal,setShowOriginal]=useState(false),[showScore,setShowScore]=useState(false);
 const [checkAttempted,setCheckAttempted]=useState(false),[checking,setChecking]=useState(false);
 const currentScope=useRef(scope),currentTicket=useRef(ticket),currentRevision=useRef(project.working_revision),queueRequest=useRef(0),inspectionRequest=useRef(0),mounted=useRef(false);currentScope.current=scope;currentTicket.current=ticket;currentRevision.current=project.working_revision;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;queueRequest.current+=1;batchGeneration.current++;};},[]);
 useEffect(()=>{batchGeneration.current++;batchBusy.current=false;setBatch(null);setBatchPhase('idle');setBatchMessage('');setCategory('residue');setFilter('required');setPage(1);setThreshold(90);setMoreOpen(false);setRows([]);setCandidates([]);setLoadedTicket(null);setSelected([]);setCheckAttempted(false);setChecking(false);},[scope]);
 async function load(){
  if(!mounted.current||currentScope.current!==scope)return;
  const requestedTicket=currentTicket.current,requestedRevision=currentRevision.current,serial=++queueRequest.current;
  const [queue,ocr]=await Promise.all([request<Page<TextFeature>>(prefix+'/reviews?asset_id='+asset.asset_id+'&include_all=true'),request<Page<Candidate>>(prefix+'/ocr-candidates?asset_id='+asset.asset_id)]);
  if(!mounted.current||currentTicket.current!==requestedTicket||queueRequest.current!==serial)return;
  if(queue.working_revision!==undefined&&queue.working_revision!==requestedRevision){setRows([]);setCandidates([]);setLoadedTicket(null);setError('文字核对列表已过期，请刷新。');return;}
  setError('');
  loadedRevision.current={scope,revision:requestedRevision};setRows(queue.items);setCandidates(ocr.items);setLoadedTicket(requestedTicket);
 }
 const incremental=!!loadedRevision.current&&loadedRevision.current.scope===scope&&loadedRevision.current.revision<project.working_revision&&residueRevisionCovered(loadedRevision.current.revision,relevantUpdates,asset.asset_id,project.working_revision);
 useEffect(()=>{let active=true;setError('');
  if(incremental){loadedRevision.current={scope,revision:project.working_revision};setLoadedTicket(ticket);}
  else void load().catch(e=>{if(active&&e.name!=='AbortError')setError(String(e));});
  return()=>{active=false;queueRequest.current+=1;};},[ticket]);
 useEffect(()=>{setLayoutPreview(null);setLayoutChecking(false);
  if(incremental)setInspection(previous=>{if(!previous)return null;const merged=mergeResidueAssessment(previous.report,relevantUpdates,asset.asset_id,project.working_revision);return merged?{ticket,report:merged}:null;});
  else if(!batchBusy.current)setInspection(null);
  setInspectionError('');setChecking(false);if(!incremental&&!batchBusy.current){setSelected([]);setMoreOpen(false);}inspectionRequest.current+=1;
 },[ticket]);
 async function runCommand(input:CommandInput,propagateError=false){
  const expectedScope=scope;let failure:unknown;
  const result=await work(async()=>{
   let changed;
   try{changed=await command(input);}catch(exc){failure=exc;throw exc;}
   if(changed&&mounted.current&&currentScope.current===expectedScope){
    try{await load();}catch(exc){if(mounted.current&&currentScope.current===expectedScope)setError('编辑已保存，文字列表刷新失败：'+String(exc));}
   }
   return changed;
  });
  // The app work wrapper reports failures globally and returns undefined. Keep
  // form errors inside the open dialog as well, so a failed draft can be retried.
  if(propagateError&&failure)throw failure;
  return !!result;
 }
 async function previewLayout(){
  if(busy||layoutChecking)return;
  const requestedTicket=currentTicket.current;setLayoutChecking(true);setError('');
  try{
   const value=await request<LayoutPreview>(prefix+'/text-layout-previews',{asset_id:asset.asset_id,base_revision:project.working_revision});
   if(mounted.current&&currentTicket.current===requestedTicket)setLayoutPreview(value);
  }catch(e){if(mounted.current&&currentTicket.current===requestedTicket)setError('排版检查失败：'+String(e));}
  finally{if(mounted.current&&currentTicket.current===requestedTicket)setLayoutChecking(false);}
 }
 async function applyLayout(){
  const preview=layoutPreview;if(!preview||busy)return;
  if(preview.base_revision!==project.working_revision){setLayoutPreview(null);setError('项目已更新，请重新预览排版修复。');return;}
  await runCommand({operation_type:'restore_ocr_layout',expected_preview_sha256:preview.input_sha256});
 }
 async function inspectReport(){
  const requestedTicket=currentTicket.current,requestedRevision=currentRevision.current,serial=++inspectionRequest.current;
  setInspection(null);setInspectionError('');setSelected([]);setChecking(true);
  try{
   const result=await request<Report>(prefix+'/text-layer-assessments?asset_id='+asset.asset_id);
   if(!mounted.current||currentTicket.current!==requestedTicket||serial!==inspectionRequest.current)return;
   if(result.working_revision!==requestedRevision){setInspectionError('检查结果已过期，请重新检查全图残影。');return;}
   if(!result.items.length&&(rows.length||result.summary.text_count)){setInspectionError('检查结果缺少文字数据，请重新检查全图残影。');return;}
   setInspection({ticket:requestedTicket,report:result});
  }catch(e){if(mounted.current&&currentTicket.current===requestedTicket&&serial===inspectionRequest.current)setInspectionError('残影检查失败：'+String(e));}
  finally{if(mounted.current&&currentTicket.current===requestedTicket&&serial===inspectionRequest.current)setChecking(false);}
 }
 async function inspect(){if(locked||checking)return;closeResidue();const expectedScope=scope;setCheckAttempted(true);await work(async()=>{if(mounted.current&&currentScope.current===expectedScope)await inspectReport();});}
 function closeResidue(){if(residueReview?.locked||batchBusy.current)return;residueReview?.close();}
 function changeCategory(next:'residue'|'information'){if(locked)return;closeResidue();setSelected([]);setCategory(next);}
 useEffect(()=>{if(revealRequest)setCategory('residue');},[revealRequest?.ticket]);
 function changeFilter(next:Filter){if(locked)return;setBatch(null);setBatchMessage('');closeResidue();setFilter(next);setPage(1);setSelected([]);}
 function openResidue(id:string){
  if(locked)return;
  if(residueReview)void residueReview.open(id);else onReviewResidue?.(id);
 }
 function batchContext():ResidueBatchContext {
  const expectedScope=scope,expectedSession=session;
  return {projectId:project.project_id,assetId:asset.asset_id,revision:()=>useWorkspace.getState().project?.working_revision??-1,
   current:()=>{const state=useWorkspace.getState();return mounted.current&&currentScope.current===expectedScope&&state.session===expectedSession&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id;}};
 }
 async function refreshBatchAssessment(context:ResidueBatchContext,action:'confirm'|'cleanup',items:ResidueBatchItem[]){
  if(action==='cleanup')return;
  const original=inspection?.report;if(!original||original.working_revision!==context.revision())return;
  const objectIds=new Set(items.flatMap(item=>item.approvedIds));
  const affected=original.items.filter(item=>items.some(value=>value.textId===item.text_feature_id)||[...item.suspected_face_ids,...item.suspected_line_ids,...item.protected_line_ids,...(item.protected_face_ids??[])].some(id=>objectIds.has(id))).map(item=>item.text_feature_id);
  let latest=original;const revision=context.revision();
  for(let offset=0;offset<affected.length;offset+=100){
   const query=new URLSearchParams({asset_id:asset.asset_id});affected.slice(offset,offset+100).forEach(id=>query.append('text_feature_ids',id));
   const patch=await request<Report>(prefix+'/text-layer-assessments?'+query,undefined,undefined,{quiet:true});
   if(!context.current()||context.revision()!==revision)return;
   const merged=replaceResidueAssessments(latest,patch);if(!merged)return;latest=merged;
  }
  if(context.current())setInspection({ticket:JSON.stringify([scope,revision]),report:latest});
 }
 async function runResidueBatch(action:'confirm'|'cleanup',ids=selected){
  if(locked||batchBusy.current||!resultsReady)return;
  const texts=rows.filter(row=>ids.includes(row.feature_id)).map(row=>({textId:row.feature_id,textValue:row.text_value}));
  if(!texts.length)return;
  const context=batchContext(),serial=++batchGeneration.current;let lastChanged:EditResult|undefined;
  batchBusy.current=true;setBatchPhase('preparing');setBatchProgress(0);setBatchTotal(texts.length);setBatchMessage('');
  setBatch({scope,revision:context.revision(),stage:'review',items:[]});
  const publish=(items:ResidueBatchItem[],stage:CleanupBatch['stage'])=>{if(context.current()&&serial===batchGeneration.current)setBatch({scope,revision:context.revision(),stage,items});};
  await work(async()=>{
   try{
    const items=await prepareResidueBatch(context,texts,index=>setBatchProgress(index+1));
    if(!context.current()||serial!==batchGeneration.current)return;
    publish(items,'review');setBatchProgress(0);setBatchPhase(action==='confirm'?'confirming':'cleaning');
    const result=action==='confirm'?await confirmResidueBatch(context,items,index=>setBatchProgress(index+1)):await cleanupResidueBatch(context,items,async(input,options)=>{const changed=await command(input,options);if(changed){publishResidueUpdate(changed);lastChanged=changed;}return changed;},index=>setBatchProgress(index+1));
    if(!context.current()||serial!==batchGeneration.current)return;
    publish(result,action==='confirm'?'confirmed':'done');
    await refreshBatchAssessment(context,action,result);
   }catch(error){if(context.current()&&serial===batchGeneration.current)setBatchMessage(error instanceof Error?error.message:String(error));}
   finally{if(context.current()&&serial===batchGeneration.current){
    try{if(residueReview?.targetId){if(lastChanged)await residueReview.applyResult(lastChanged);else if(action==='confirm')await residueReview.refresh();}}
    finally{if(context.current()&&serial===batchGeneration.current){batchBusy.current=false;setBatchPhase('idle');}}
   }}
  },{quiet:true});
 }

 useEffect(()=>{
  const patch=residueReview?.report;
  if(!patch||patch.working_revision!==project.working_revision)return;
  const original=inspection?.report;
  setInspection(previous=>{if(!previous)return previous;const base=mergeResidueAssessment(previous.report,relevantUpdates,asset.asset_id,project.working_revision);const merged=base&&replaceResidueAssessments(base,patch);return merged?{ticket,report:merged}:previous;});
  // A shared keep/confirm decision does not advance geometry revision. Refresh
  // other rows that reference the same objects without scanning the full layer.
  if(!original||original.working_revision!==patch.working_revision||relevantUpdates.some(update=>update.result_revision===patch.working_revision&&update.assessment===patch))return;
  const patched=new Set(patch.items.map(item=>item.text_feature_id));
  const touched=new Set(original.items.filter(item=>patched.has(item.text_feature_id)).flatMap(item=>[...item.suspected_face_ids,...item.suspected_line_ids,...item.protected_line_ids,...(item.protected_face_ids??[])]));
  const related=original.items.filter(item=>!patched.has(item.text_feature_id)&&[...item.suspected_face_ids,...item.suspected_line_ids,...item.protected_line_ids,...(item.protected_face_ids??[])].some(id=>touched.has(id))).map(item=>item.text_feature_id);
  if(!related.length)return;
  const controller=new AbortController(),expected=ticket;
  void (async()=>{for(let offset=0;offset<related.length;offset+=100){
   const query=new URLSearchParams({asset_id:asset.asset_id});related.slice(offset,offset+100).forEach(id=>query.append('text_feature_ids',id));
   const result=await request<Report>(prefix+'/text-layer-assessments?'+query,undefined,controller.signal,{quiet:true});
   if(controller.signal.aborted||currentTicket.current!==expected)return;
   setInspection(previous=>{const merged=previous&&replaceResidueAssessments(previous.report,result);return merged?{ticket:expected,report:merged}:previous;});
  }})().catch(error=>{if(!controller.signal.aborted&&currentTicket.current===expected){setInspection(null);setInspectionError('残影检查失败：'+String(error));}});
  return()=>controller.abort();
 },[residueReview?.report,ticket]);
 const advancedReport=inspection&&inspection.ticket!==ticket?mergeResidueAssessment(inspection.report,relevantUpdates,asset.asset_id,project.working_revision):null;
 const report=advancedReport??(inspection&&(batchPending||inspection.ticket===ticket&&inspection.report.working_revision===project.working_revision)?inspection.report:null);
 const resultsReady=!!report&&(batchPending||loadedTicket===ticket||incremental);
 const assessments=new Map(report?.items.map(item=>[item.text_feature_id,item]));
 const matches=(feature:TextFeature,value:Filter)=>matchesResidueFilter(assessments.get(feature.feature_id),value);
 const counts:Record<Filter,number>={required:rows.filter(f=>matches(f,'required')).length,kept:rows.filter(f=>matches(f,'kept')).length,none:rows.filter(f=>matches(f,'none')).length,all:rows.length};
 // Keep the current detail visible until the user collapses it, including after cleanup changes its status.
 const currentBatch=batch?.scope===scope&&(batchPending||batch.revision===project.working_revision)?batch:null;
 const batchResults=new Map(currentBatch?.items.map(item=>[item.textId,item]));
 const visibleRows=rows.filter(f=>matches(f,filter)||f.feature_id===residueReview?.targetId||batchResults.has(f.feature_id));
 const visiblePageKey=JSON.stringify(visibleRows.slice((page-1)*TEXT_REVIEW_PAGE_SIZE,page*TEXT_REVIEW_PAGE_SIZE).filter(row=>residueState(assessments.get(row.feature_id))!=='none').map(row=>row.feature_id));
 useEffect(()=>{const available=new Set<string>(JSON.parse(visiblePageKey));setSelected(current=>current.filter(id=>available.has(id)));},[visiblePageKey]);
 useEffect(()=>{setPage(current=>Math.min(current,Math.max(1,Math.ceil(visibleRows.length/TEXT_REVIEW_PAGE_SIZE))));},[visibleRows.length]);
 const externalInspection=useRef('');
 useEffect(()=>{
  const targetId=residueReview?.targetId??revealRequest?.feature_id;
  const key=targetId?JSON.stringify([targetId,revealRequest?.ticket,ticket]):'';
  if(category!=='residue'||!key||externalInspection.current===key||report||checking||inspectionError||busy||!visible||loadedTicket!==ticket)return;
  externalInspection.current=key;setCheckAttempted(true);void work(inspectReport);
 },[category,revealRequest?.ticket,residueReview?.targetId,ticket,loadedTicket,visible,!!report,checking,inspectionError,busy]);
 useEffect(()=>{if(loadedTicket===ticket&&residueReview?.targetId&&!rows.some(row=>row.feature_id===residueReview.targetId))residueReview.close();},[loadedTicket,ticket,rows,residueReview?.targetId]);
 const revealedId=useTextReviewReveal({request:revealRequest,ticket,rows,loadedTicket,visible:category==='residue'&&visible&&resultsReady,panel,filter,setFilter,setPage,matches});
 const [located,setLocated]=useState<{ticket:string;id:string;revealTicket?:number}|null>(null);
 const highlightedId=located?.ticket===ticket&&located.revealTicket===revealRequest?.ticket?located.id:revealedId;
 const unused=candidates.filter(c=>!c.text_feature_id);
 const columns:TableColumnsType<TextFeature>=[
  {title:'文字',dataIndex:'text_value',render:(value:string,f:TextFeature)=><div className="text-review-text-cell"><span className="text-review-value" title={'文字 '+f.feature_id+' · 内容核对：'+statusLabel(f)}>{value||'（空文字）'}</span>{(f.layout_runs??[]).filter(r=>r.script==='subscript'||r.script==='superscript').map((r,i)=><Tag key={i}>{r.script==='subscript'?'下标':'上标'} {r.text}</Tag>)}</div>},
  ...(showOriginal?[{title:'原始候选',dataIndex:'original_text',render:(value:string)=><span className="text-review-value">{value||'—'}</span>}]:[]),
  ...(showScore?[{title:'识别分数',render:(_:unknown,f:TextFeature)=>score(f.ocr_score)}]:[]),
  {title:'残影状态',className:'text-review-nowrap',render:(_,f)=>{const state=residueState(assessments.get(f.feature_id)),label=state==='required'?'待核对':state==='kept'?'已保留':'未发现';const result=batchResults.get(f.feature_id),displayLabel=result?.status==='ready'?'已确认':label;return <div className="text-review-result"><Tag color={state==='none'?undefined:statusColor(displayLabel)}>{displayLabel}</Tag>{result&&<span className="text-review-batch-result" role="status">{result.message??(batchPending&&result.status==='review'?'正在处理…':({review:'请先确认核对后再清理',ready:'已确认核对',empty:'无需清理',blocked:'未处理，请查看原因',cleaned:'已清理',partial:'部分已清理'}[result.status]))}</span>}</div>;}},
  {title:'残影',className:'text-review-residue-col',render:(_,f)=>residueEvidence(assessments.get(f.feature_id))},
  {title:'原因',render:(_,f)=><ReasonList className="inspection-reasons" items={[...new Set(assessments.get(f.feature_id)?.reasons??[])].map(code=>reasons[code]??code)}/>},
  {title:'操作',className:'text-review-nowrap',render:(_,f)=>{
   const opened=residueReview?.targetId===f.feature_id,reviewable=residueState(assessments.get(f.feature_id))!=='none';
   return <div className="text-review-row-actions"><div className="text-review-row-navigation">
    {(onReviewResidue||residueReview)&&(reviewable||opened)&&<Button disabled={locked} aria-expanded={residueReview?opened:undefined} aria-controls={opened?detailsId:undefined} onClick={()=>{if(opened)closeResidue();else openResidue(f.feature_id);}}>{opened?'收起详情':'核对残影'}</Button>}
    <Button disabled={locked} onClick={()=>{setLocated({ticket,id:f.feature_id,revealTicket:revealRequest?.ticket});focus(f.feature_id);}}>定位</Button>
   </div>{opened?<div className="text-review-row-cleanup" ref={residueReview.cleanupActionRef}/>:reviewable&&(onReviewResidue||residueReview)?<div className="text-review-row-cleanup"><Button danger disabled={locked} onClick={()=>void runResidueBatch('cleanup',[f.feature_id])}>清理残影</Button></div>:null}</div>;
  }}
 ];
 return <div ref={panel} className="text-review-panel">
  <div className="text-review-toolbar" aria-label="文字残影检查工具">
   <InspectionStatus ariaLabel="文字核对检查状态" state={checking?'checking':resultsReady?'done':'waiting'} attempted={checkAttempted} disabled={locked} onCheck={()=>void inspect()} extra={<><Button aria-expanded={moreOpen} aria-controls="text-review-more" onClick={()=>setMoreOpen(value=>!value)}>检查设置</Button>{resultsReady&&<span className="inspection-total">共 {rows.length} 项</span>}</>}/>
  </div>
  <Modal open={!!layoutPreview} title="排版修复预览" width={900} okText="应用修复" cancelText="取消" confirmLoading={busy} okButtonProps={{disabled:busy||!layoutPreview?.updated_count}} onCancel={()=>setLayoutPreview(null)} onOk={()=>void applyLayout()}>
   {layoutPreview&&<><p>更新 {layoutPreview.updated_count} 项，跳过 {layoutPreview.skipped_count} 项（含人工编辑），其中排版仍需核对 {layoutPreview.review_required_count} 项。原始识别内容保留，修复可撤销。</p><div style={{maxHeight:'60vh',overflow:'auto'}}>{layoutPreview.changes.map(item=><section key={item.feature_id}><strong>{item.text_value}</strong><div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:16}}><div><p>修复前 · 字号 {item.before.font_size_px.toFixed(2)} · 位置 {item.before.geometry.coordinates.map(v=>v.toFixed(1)).join(", ")}</p><FeaturePreview features={[item.before]} styles={[]}/></div><div><p>修复后 · 字号 {item.after.font_size_px.toFixed(2)} · 位置 {item.after.geometry.coordinates.map(v=>v.toFixed(1)).join(", ")}</p><FeaturePreview features={[item.after]} styles={[]}/></div></div></section>)}</div></>}
  </Modal>
  <div id="text-review-more" className="text-review-more" hidden={!moreOpen}>
   <div className="text-review-column-options" role="group" aria-label="显示列"><Checkbox checked={showOriginal} onChange={event=>setShowOriginal(event.target.checked)}>原始候选</Checkbox><Checkbox checked={showScore} onChange={event=>setShowScore(event.target.checked)}>识别分数</Checkbox></div>
   <div className="text-review-advanced-controls"><label htmlFor="text-review-threshold">自动通过分数</label><InputNumber id="text-review-threshold" aria-label="自动通过分数门槛" min={1} max={100} value={threshold} addonAfter="%" onChange={n=>setThreshold(Number(n??90))}/><Button disabled={busy} onClick={()=>void runCommand({operation_type:'classify_review',threshold:threshold/100})}>重新评估文字</Button><Button loading={layoutChecking} disabled={busy||layoutChecking} onClick={()=>void previewLayout()}>预览排版修复</Button></div>
   <p className="review-note">模型分数不是正确率；自动通过的文字仍未人工确认。</p>
   <details className="ocr-candidate-details"><summary>未采用的识别结果（{unused.length}）</summary><Table rowKey="candidate_id" size="small" dataSource={unused} pagination={{pageSize:8}} scroll={{x:650}} columns={[{title:'原文',dataIndex:'raw_text'},{title:'识别分数',render:(_,c:Candidate)=>score(c.score)},{title:'引擎 / 模型',render:(_:unknown,c:Candidate)=>(c.engine_id||'—')+' / '+(c.model_id||'—')},{title:'建议',render:(_:unknown,c:Candidate)=><ReasonList items={candidateReasonTexts(c)}/>},{title:'操作',render:(_,c:Candidate)=><Button disabled={busy} onClick={()=>void runCommand({operation_type:'adopt_ocr_candidate',candidate_id:c.candidate_id})}>保存为文字</Button>}]}/></details>
  </div>
  {error&&<Alert type="error" message={error}/>}
  {inspectionError&&<Alert type="error" message={inspectionError}/>}
  <Tabs className="text-review-categories" aria-label="文字检查类型" activeKey={category} onChange={key=>changeCategory(key as 'residue'|'information')} items={[{key:'residue',label:'残影清理'+(resultsReady?' '+(counts.required+counts.kept):''),disabled:locked},{key:'information',label:'文字信息 '+rows.length,disabled:locked}]}/>
  {category==='information'?<TextInformationPanel key={scope} project={project} asset={asset} rows={rows} ready={loadedTicket===ticket} busy={busy} mutate={input=>runCommand(input,true)} focus={focus}/>:resultsReady&&<>
  <Segmented className="text-review-filters" aria-label="文字残影状态筛选" role="group" size="small" value={filter} disabled={locked} onChange={value=>changeFilter(value as Filter)} options={filters.map(item=>({value:item.value,label:item.label+' '+counts[item.value]}))}/>
  {selected.length>0&&<div className="text-review-selection" role="group" aria-label="所选残影操作"><span>已选 {selected.length} 项</span><Button disabled={locked} onClick={()=>void runResidueBatch('confirm')}>确认核对</Button><Button danger disabled={locked} onClick={()=>void runResidueBatch('cleanup')}>清理残影</Button></div>}
  {batchPending&&<div className="text-review-batch-progress" role="status">{batchPhase==='preparing'?'正在检查所选残影':batchPhase==='confirming'?'正在确认核对':'正在清理残影'}：{batchProgress} / {batchTotal} 项</div>}
  {batchMessage&&<Alert type="error" message={batchMessage}/>}
  {!batchPending&&currentBatch&&<div className="text-review-batch-summary" role="status">{currentBatch.stage==='confirmed'?'确认核对完成':'处理完成'}：已清理 {currentBatch.items.filter(item=>item.status==='cleaned').length} 项 · 部分清理 {currentBatch.items.filter(item=>item.status==='partial').length} 项 · 需先核对 {currentBatch.items.filter(item=>item.status==='review').length} 项 · 未处理 {currentBatch.items.filter(item=>item.status==='blocked').length} 项 · 无需清理 {currentBatch.items.filter(item=>item.status==='empty').length} 项{currentBatch.stage==='confirmed'&&<> · 已确认 {currentBatch.items.filter(item=>item.status==='ready').length} 项</>}</div>}
  <Table className="text-review-table" rowKey="feature_id" size="small" dataSource={visibleRows} rowClassName={row=>[row.feature_id===highlightedId?'text-review-revealed':'',row.feature_id===residueReview?.targetId?'text-review-residue-open':''].filter(Boolean).join(' ')} onRow={row=>({'aria-selected':row.feature_id===highlightedId})} rowSelection={{selectedRowKeys:selected,onChange:keys=>{if(locked)return;setBatch(null);setBatchMessage('');setSelected(keys.map(String));},columnWidth:40,getCheckboxProps:row=>({disabled:locked||residueState(assessments.get(row.feature_id))==='none'})}} expandable={residueReview?{expandedRowKeys:residueReview.targetId?[residueReview.targetId]:[],expandedRowRender:row=>row.feature_id===residueReview.targetId?<div id={detailsId} className="text-review-inline-residue">{residueReview.content}</div>:null,showExpandColumn:false,expandedRowClassName:()=> 'text-review-residue-details'}:undefined} pagination={{pageSize:TEXT_REVIEW_PAGE_SIZE,current:page,disabled:locked,onChange:next=>{closeResidue();setPage(next);setSelected([]);},showSizeChanger:false}} scroll={{x:600}} columns={columns}/>
  </>}
 </div>;
}

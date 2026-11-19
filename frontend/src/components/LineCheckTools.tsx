import {useEffect,useRef,useState} from 'react';
import {Alert,Button,InputNumber,Modal,Pagination,Segmented,Tabs,Tooltip} from 'antd';
import {LineCheckTable} from './LineCheckTable';
import {InspectionStatus} from './InspectionStatus';
import {LineContinuationCard} from './LineContinuationCard';
import {useWorkspace} from '../stores/workspace';
import {geometryPath} from './FeatureGlyph';
import {decideLines,inspectLines,pageLineCandidates} from '../services/lineChecks';
import {feedback} from '../services/feedback';
import type {ApplyLineCheckInput,LineCheckAction,LineCheckCandidate,LineCheckKind,LineCheckParameters,LineCheckReport,LineCheckPage} from '../services/lineChecks';
import type {Asset,Command,Feature,Point,Project,Style,Geometry} from '../services/models';
import './LineCheckTools.css';

type Filter='pending'|'kept'|'applied'|'all';
export type LineCheckDisplay={items:LineCheckCandidate[];highlighted:string;checked:string[]};
export type LineCheckSettings={parameters:Record<keyof LineCheckParameters,number|null>;parameterDrafts:{max_gap_px:string;angle_tolerance_deg:string;max_short_length_px:string};lastValidParameters?:LineCheckParameters};
const initialParameters:LineCheckParameters={max_gap_px:8,angle_tolerance_deg:15,max_short_length_px:12};
export function createLineCheckSettings():LineCheckSettings{return {parameters:{...initialParameters},parameterDrafts:{max_gap_px:'8',angle_tolerance_deg:'15',max_short_length_px:'12'},lastValidParameters:{...initialParameters}};}
type Props={mode:'automatic'|'manual';project:Project;asset:Asset;active:boolean;busy:boolean;command:Command;flush:()=>Promise<boolean>;onLocate:(bounds:number[],ids?:string[],geometries?:Geometry[])=>void;onSelect:(ids:string[])=>void;onPreview:(display:LineCheckDisplay|null)=>void;manualConnector?:Point[];drawingManualConnector?:boolean;onDrawManualConnector?:()=>void;onCancelManualConnector?:()=>void;onFinishManualConnector?:()=>void;settings?:LineCheckSettings;onSettingsChange?:(next:LineCheckSettings)=>void;choosingSecondLine?:boolean;onChooseSecondLine?:()=>void;onCancelChooseSecondLine?:()=>void;onReselectLines?:()=>void;styles?:Style[];onReviewResidue?:(item:LineCheckCandidate)=>void};
const kinds:{key:LineCheckKind;label:string;action:LineCheckAction}[]=[{key:'join_gap',label:'断线接续',action:'join'},{key:'text_stroke',label:'疑似文字残线',action:'isolate'},{key:'dash_group',label:'虚线编组',action:'group'}];
const filters:{key:Filter;label:string}[]=[{key:'pending',label:'待核对'},{key:'kept',label:'已保留'},{key:'applied',label:'已处理'},{key:'all',label:'全部'}];
const explanations:Record<string,string>={ALIGNED_ENDPOINT_GAP:'端点邻近且方向一致',ENDPOINTS_ALIGNED:'端点邻近且方向一致',ENDPOINT_GAP:'端点间有缺口',TANGENT_ALIGNED:'切向一致',REGULAR_DASH_SPACING:'短段间隔规则',REGULAR_SHORT_SEGMENTS:'间隔规律的短线段可能属于虚线',KNOWN_DASH_PATTERN:'已有虚线样式，应保留间隔',DASH_STYLE:'已有虚线样式',TEXT_OVERLAP:'与文字范围重叠',TEXT_BOX_OVERLAP:'与文字范围重叠',SHORT_LINE_IN_TEXT_REGION:'短线位于文字范围内，需对照原图',ASSOCIATED_TEXT:'存在关联文字',CROSSES_OTHER_LINE:'跨越其他线',CROSSES_THIRD_LINE:'跨越其他线，需保留',AMBIGUOUS_BRANCH:'附近有分叉，接续方向不明确',AMBIGUOUS_ENDPOINT:'附近有多个可能接续端点',ATTRIBUTE_MISMATCH:'线条属性不一致',STYLE_MISMATCH:'线条外观不一致',ROLE_MISMATCH:'线用途不一致',DENSE_ENDPOINT_REGION:'端点分布密集，跳过自动建议',SEMANTIC_LINE_PATTERN:'线型间隔有语义，应保留',DASH_PROTECTED:'虚线间隔需要保留',MANUAL_LINE:'手工线需保留',EXISTING_GROUP_MEMBERSHIP:'已有逻辑编组',ALREADY_GROUPED:'已有编组',GEOLOGICAL_BOUNDARY:'地质分界需保留',GEOLOGICAL_SYMBOL:'地质符号线需保留',CROSSES_TEXT_REGION:'线跨出文字范围，需核对局部清理并保留范围外部分',NON_TEXT_STROKE_COLOR:'线条颜色不像文字笔画',CROSSES_TEXT_BOUNDS:'线延伸到文字框外',SELF_INTERSECTION:'线存在自相交',CYCLIC_CONNECTION:'接续会形成闭合环'};
const summaryLabels:Record<string,string>={join_gap_count:'断线接续',text_stroke_count:'疑似文字残线',dash_group_count:'虚线编组',scanned_line_count:'检查线数',scanned_text_count:'检查文字数',text_source_region_count:'有效文字范围数',texts_without_source_region_count:'缺少文字范围数',unadopted_ocr_region_count:'未采用识别范围数',text_referenced_line_count:'关联文字线数',text_edge_line_count:'框边缘候选线数',text_complex_line_count:'复杂长残线数',uncertain_text_region_count:'异常文字范围数',candidate_count:'候选总数',returned_count:'返回候选数',dense_endpoint_count:'密集端点数',truncated:'候选截断'};
Object.assign(explanations,{EXPLICIT_MANUAL_CONTINUATION:'明确指定的人工接续',MANUAL_PATH:'使用人工绘制路径',NEAREST_ENDPOINTS:'连接最近端点',MANUAL_RASTER_REVIEW_REQUIRED:'人工接续需对照原图核对',MANUAL_PATH_NOT_ATTACHED:'人工路径未贴合两条线的端点',DEGENERATE_CONNECTOR:'连接路径长度不足',OUTSIDE_ASSET:'接续路径超出原图范围',RASTER_SOURCE_MISMATCH:'原图依据与当前资产不一致',RASTER_PATH_UNSUPPORTED:'原图不支持连接路径',RASTER_EVIDENCE_UNAVAILABLE:'原图依据暂不可用',RASTER_PATH_REQUIRES_REVIEW:'连接路径的原图依据需核对',GAP_LARGE_RELATIVE_TO_STROKE:'缺口相对线宽过大',DIVERGENT_CURVATURE:'两端曲率方向不一致',ENDPOINT_DIRECTION_MISMATCH:'端点方向不一致',AMBIGUOUS_DASH_MEMBERSHIP:'可能属于多组虚线，需保留间隔'});
Object.assign(explanations,{CONNECTOR_TEXT_OVERLAP:'连接路径经过文字范围，需对照原图核对',CONNECTOR_GEOLOGICAL_SYMBOL:'连接路径涉及地质符号，需保留符号表达',GEOLOGICAL_SYMBOL_TEXT_OVERLAP:'与地质符号注记重叠，需保留符号表达'});
Object.assign(explanations,{COMPLEX_TEXT_STROKE_REQUIRES_REVIEW:'复杂或较长笔画，需人工核对',TEXT_REGION_EDGE_REQUIRES_REVIEW:'线宽涉及文字框边缘，仅供核对，不扩大清理范围',SOURCE_REGION_UNCERTAIN:'原识别范围异常，需人工核对'});
Object.assign(explanations,{MISSING_TEXT_ASSOCIATION:'未关联文字，需人工核对后清理',RASTER_STROKE_UNSUPPORTED:'原图不支持该残线',SOURCE_REGION_REQUIRED:'缺少可靠原图文字范围',TEXT_STROKE_REGION:'线段与原图文字范围相关',ADAPTIVE_TEXT_STROKE:'按字高与笔宽发现疑似笔画',UNASSIGNED_TEXT_INK_CLUSTER:'未关联文字的墨迹簇，需人工核对',AMBIGUOUS_TEXT_OWNERSHIP:'涉及多个文字，需核对残影归属',UNADOPTED_OCR_REGION:'未采用识别范围内的疑似残线'});
const reason=(code:string)=>explanations[code.toUpperCase()]??code;
const pageSize=25;
const actionLabels:Record<LineCheckAction,string>={join:'接续各组线',isolate:'清理残影',group:'分别建立编组'};
const successMessages:Record<LineCheckAction,string>={join:'线接续已完成，可撤销。',isolate:'所选残影已清理，可撤销。',group:'虚线编组已建立，可撤销。'};
const parameterFields:{key:keyof LineCheckParameters;label:string;min:number;max:number}[]=[{key:'max_gap_px',label:'最大接续间距',min:0,max:50},{key:'angle_tolerance_deg',label:'方向偏差上限',min:1,max:45},{key:'max_short_length_px',label:'文字残线基础尺度',min:1,max:100}];
function validParameter(field:(typeof parameterFields)[number],value:number|null|undefined,draft?:string):value is number{return value!=null&&Number.isFinite(value)&&value>=field.min&&value<=field.max&&(draft===undefined||/^\+?(?:\d+|\d*\.\d+)$/.test(draft.trim())&&Number(draft)===value);}

export function LineCheckTools({mode,project,asset,active,busy,command,flush,onLocate,onSelect,onPreview,manualConnector,drawingManualConnector=false,onDrawManualConnector,onCancelManualConnector,onFinishManualConnector,settings,onSettingsChange,choosingSecondLine=false,onChooseSecondLine,onCancelChooseSecondLine,onReselectLines,styles=[],onReviewResidue}:Props){
 const [report,setReport]=useState<LineCheckReport|null>(null),[kind,setKind]=useState<LineCheckKind>('join_gap'),[filter,setFilter]=useState<Filter>('pending');
 const [checked,setChecked]=useState<string[]>([]),[verified,setVerified]=useState<string[]>([]),[highlighted,setHighlighted]=useState(''),[page,setPage]=useState(1),[parametersOpen,setParametersOpen]=useState(false);
 const [localSettings,setLocalSettings]=useState(createLineCheckSettings);
 const currentSettings=settings??localSettings,{parameters,parameterDrafts}=currentSettings;
 const settingsRef=useRef(currentSettings);settingsRef.current=currentSettings;
 function updateSettings(update:LineCheckSettings|((current:LineCheckSettings)=>LineCheckSettings)){
  const previous=settingsRef.current,next=typeof update==='function'?update(previous):update;
  const lastValidParameters={...initialParameters,...previous.lastValidParameters};
  for(const field of parameterFields){const value=next.parameters[field.key];if(validParameter(field,value,next.parameterDrafts[field.key]))lastValidParameters[field.key]=value;}
  const remembered={...next,lastValidParameters};settingsRef.current=remembered;
  if(onSettingsChange)onSettingsChange(remembered);else setLocalSettings(remembered);
 }
 const manualParameters={...initialParameters};
 for(const field of parameterFields){const value=parameters[field.key],remembered=currentSettings.lastValidParameters?.[field.key];if(validParameter(field,value,parameterDrafts[field.key]))manualParameters[field.key]=value;else if(validParameter(field,remembered))manualParameters[field.key]=remembered;}
 const [status,setStatus]=useState<'idle'|'checking'|'checked'|'error'>('idle'),[pending,setPending]=useState(false),[error,setError]=useState(''),[reviewIds,setReviewIds]=useState<string[]>([]);
 const [checkAttempted,setCheckAttempted]=useState(false);
 const [serverPage,setServerPage]=useState<LineCheckPage|null>(null),[pagePending,setPagePending]=useState(false);
 const pageRequest=useRef(0),pageAbort=useRef<AbortController|null>(null);
 const [confirmedSelection,setConfirmedSelection]=useState<LineCheckCandidate[]>([]);
 const session=useWorkspace(state=>state.session),layer=useWorkspace(state=>state.layer),selectionKey=useWorkspace(state=>JSON.stringify([...state.selected].sort()));
 const featuresById=useWorkspace(state=>state.featuresById);
 const selectedIds=JSON.parse(selectionKey) as string[];
 // Selection order (not sorted): the first selected line is the continuation's start line.
 const orderedSelection=useWorkspace(state=>state.selected.join(','));
 const manualFeatureIds=selectedIds.filter(id=>featuresById[id]?.feature_type==='line'&&featuresById[id]?.lifecycle_status==='active');
 const validManualSelection=selectedIds.length===2&&manualFeatureIds.length===2;
 const validManualPath=!drawingManualConnector&&(!manualConnector?.length||(manualConnector.length>=2&&manualConnector.length<=1000&&manualConnector.every(point=>point.length===2&&point.every(Number.isFinite))));
 useEffect(()=>setHighlighted(''),[selectionKey]);
 const baseContext=JSON.stringify([project.project_id,asset.asset_id,session,layer,active,mode,mode==='manual'?selectionKey:null]);
 const context=JSON.stringify([baseContext,mode==='manual'?[manualConnector,drawingManualConnector,choosingSecondLine]:null]);
 const contextRef=useRef(context),reportRef=useRef(report),requestSerial=useRef(0),requestRef=useRef<{controller:AbortController;revision:number}|null>(null),inFlight=useRef(false),mounted=useRef(true);
 const idempotency=useRef<{payload:string;key:string}|null>(null);contextRef.current=context;reportRef.current=report;
 const parameterKey=JSON.stringify([parameters,parameterDrafts,manualParameters]);
 const viewKey=JSON.stringify([context,parameterKey,project.working_revision,report?.preview_id,kind,filter,page]);
 const viewRef=useRef(viewKey);viewRef.current=viewKey;
 const validParameters=parameterFields.every(field=>validParameter(field,parameters[field.key],parameterDrafts[field.key]));
 function clearReport(message=''){
  pageRequest.current++;pageAbort.current?.abort();setServerPage(null);setPagePending(false);
  requestSerial.current++;requestRef.current?.controller.abort();requestRef.current=null;
  reportRef.current=null;setReport(null);setConfirmedSelection([]);setChecked([]);setVerified([]);setHighlighted('');setReviewIds([]);setPage(1);setStatus('idle');setError(message);onPreview(null);idempotency.current=null;
 }
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;requestSerial.current++;requestRef.current?.controller.abort();pageRequest.current++;pageAbort.current?.abort();onPreview(null);};},[]);
 useEffect(()=>{clearReport();},[context,parameterKey]);
 useEffect(()=>{setKind('join_gap');setFilter('pending');setPage(1);},[mode]);
 useEffect(()=>{setCheckAttempted(false);},[baseContext]);
 useEffect(()=>{
  const old=reportRef.current;
  if(old&&old.base_revision!==project.working_revision)clearReport('项目已更新，请重新检查当前线层。');
  else if(requestRef.current&&requestRef.current.revision!==project.working_revision)clearReport('检查期间项目已更新，请重新检查当前线层。');
 },[project.working_revision]);
 useEffect(()=>{
  if(!report)return;
  const remaining=Date.parse(report.expires_at)-Date.now();
  if(remaining<=0){clearReport('检查结果已过期，请重新检查当前线层。');return;}
  // Recheck very distant fixture expiries without overflowing the browser timer.
  if(remaining>2147483647)return;
  const timer=window.setTimeout(()=>clearReport('检查结果已过期，请重新检查当前线层。'),remaining);
  return()=>window.clearTimeout(timer);
 },[report?.preview_id]);
 function sameContext(expected:string){const state=useWorkspace.getState();return mounted.current&&contextRef.current===expected&&state.session===session&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id&&state.layer==='line'&&active;}
 async function protect(currentReport:LineCheckReport|null=reportRef.current){
  const expected=contextRef.current,view=viewRef.current;
  if(!sameContext(expected)||viewRef.current!==view)return null;
  if(!await flush()){if(sameContext(expected))setError('属性草稿未能保存，请先修正或重试保存。');return null;}
  if(!sameContext(expected)||viewRef.current!==view)return null;
  const state=useWorkspace.getState();
  if(currentReport&&(reportRef.current?.preview_id!==currentReport.preview_id||currentReport.asset_id!==asset.asset_id||currentReport.base_revision!==state.project?.working_revision||Date.parse(currentReport.expires_at)<=Date.now())){clearReport('项目或检查结果已更新，请重新检查当前线层。');return null;}
  return {expected,view,revision:state.project!.working_revision,report:currentReport};
 }
 function stillCurrent(guard:{expected:string;view:string;revision:number}|null){return !!guard&&sameContext(guard.expected)&&viewRef.current===guard.view&&useWorkspace.getState().project?.working_revision===guard.revision;}
 async function inspect(){
  if(busy||inFlight.current||!active||(mode==='automatic'&&!validParameters)||(mode==='manual'&&(!validManualSelection||!validManualPath||choosingSecondLine)))return;
  const expected=contextRef.current;
  inFlight.current=true;setPending(true);setError('');setStatus('checking');setCheckAttempted(true);
  try{
   const guard=await protect(null);if(!guard)return;
   requestRef.current?.controller.abort();setStatus('checking');
   const controller=new AbortController(),serial=++requestSerial.current;requestRef.current={controller,revision:guard.revision};
   const result=await inspectLines(project.project_id,asset.asset_id,guard.revision,(mode==='automatic'?parameters:manualParameters) as LineCheckParameters,controller.signal,{mode,...(mode==='manual'?{manual_feature_ids:manualFeatureIds,manual_connector_px:manualConnector?.length?manualConnector:null}:{})});
   if(!sameContext(guard.expected)||serial!==requestSerial.current||controller.signal.aborted)return;
   if(result.asset_id!==asset.asset_id||result.base_revision!==guard.revision||result.mode&&result.mode!==mode||useWorkspace.getState().project?.working_revision!==guard.revision||Date.parse(result.expires_at)<=Date.now())throw Error('检查结果已失效，请重新检查当前线层。');
   if(mode==='manual'&&(result.candidates.length!==1||result.candidates[0].kind!=='join_gap'||result.candidates[0].allowed_action!=='join'||result.candidates[0].feature_ids.length!==2||new Set(result.candidates[0].feature_ids).size!==2||result.candidates[0].feature_ids.some(id=>!manualFeatureIds.includes(id))))throw Error('接续检查没有返回当前两条线的唯一方案，请重新检查。');
   reportRef.current=result;setReport(result);setConfirmedSelection([]);setChecked(mode==='manual'?result.candidates.map(item=>item.candidate_id):[]);setVerified([]);setHighlighted('');setReviewIds([]);setPage(1);idempotency.current=null;setStatus('checked');
  }catch(e){if(sameContext(expected)&&!(e instanceof DOMException&&e.name==='AbortError')){if(mode==='manual'){reportRef.current=null;setReport(null);setConfirmedSelection([]);setChecked([]);setVerified([]);setHighlighted('');onPreview(null);}setError(e instanceof Error?e.message:String(e));setStatus('error');}}
  finally{inFlight.current=false;if(mounted.current){setPending(false);setStatus(value=>value==='checking'?'idle':value);}requestRef.current=null;}
 }
 const manualCandidate=mode==='manual'&&active&&validManualSelection&&validManualPath&&!choosingSecondLine&&report&&report.asset_id===asset.asset_id&&report.base_revision===project.working_revision&&Date.parse(report.expires_at)>Date.now()&&(!report.mode||report.mode==='manual')&&report.candidates.length===1&&report.candidates[0].kind==='join_gap'&&report.candidates[0].allowed_action==='join'&&report.candidates[0].feature_ids.length===2&&new Set(report.candidates[0].feature_ids).size===2&&report.candidates[0].feature_ids.every(id=>manualFeatureIds.includes(id))?report.candidates[0]:null;
 const paged=report?.summary.truncated===true;
 const allRows=paged?(serverPage?.items??[]):[...(report?.candidates??[]),...(report?.history??[])];
 const typeRows=allRows.filter(item=>item.kind===kind),rows=typeRows.filter(item=>filter==='all'||item.status===filter);
 const visibleRows=paged?rows:rows.slice((page-1)*pageSize,page*pageSize);
 const totalRows=paged?(serverPage?.total??0):rows.length;
 const chosen=mode==='manual'?(manualCandidate&&manualCandidate.status!=='applied'?[manualCandidate]:[]):(paged?[...new Map([...confirmedSelection,...rows].map(item=>[item.candidate_id,item])).values()]:(report?.candidates??[])).filter(item=>item.status!=='applied'&&checked.includes(item.candidate_id));
 const withinBatchLimit=chosen.length<=2000;
 const chosenPending=chosen.length>0&&withinBatchLimit&&chosen.every(item=>item.status==='pending'),chosenKept=chosen.length>0&&withinBatchLimit&&chosen.every(item=>item.status==='kept');
 const reviewable=chosen.length>0&&withinBatchLimit&&chosen.every(item=>item.kind==='text_stroke'?!item.blocked_reasons.includes('RASTER_SOURCE_MISMATCH'):item.status==='pending'&&!item.blocked_reasons.length);
 const action=kinds.find(item=>item.key===kind)!.action;
 const residueNeedsReview=chosen.filter(item=>item.kind==='text_stroke'&&!item.manually_confirmed&&(item.blocked_reasons.length>0||item.status==='kept'));
 const applicableCandidates=action==='isolate'?chosen.filter(item=>item.allowed_action===action&&(item.manually_confirmed||item.status!=='kept'&&!item.blocked_reasons.length)&&!item.blocked_reasons.includes('RASTER_SOURCE_MISMATCH')):chosen;
 const applicable=withinBatchLimit&&(action==='isolate'?applicableCandidates.length>0:reviewable&&chosen.every(item=>item.allowed_action===action&&verified.includes(item.candidate_id)));
 const disabled=busy||pending||pagePending||!active||(paged&&!serverPage);
 const selectableRows=rows.filter(item=>filter==='kept'?item.status==='kept':item.status==='pending'&&(!item.blocked_reasons.length||item.kind==='text_stroke'&&!item.blocked_reasons.includes('RASTER_SOURCE_MISMATCH')));
 const allSelected=selectableRows.length>0&&selectableRows.every(item=>checked.includes(item.candidate_id));
 useEffect(()=>{if(!paged||serverPage)setPage(current=>Math.min(current,Math.max(1,Math.ceil(totalRows/pageSize))));},[totalRows,paged,serverPage]);
 useEffect(()=>{
  pageAbort.current?.abort();const serial=++pageRequest.current;
  if(!report||!paged||!active){setServerPage(null);setPagePending(false);return;}
  const controller=new AbortController(),expected=contextRef.current,plan=report;
  pageAbort.current=controller;setServerPage(null);setPagePending(true);setHighlighted('');setReviewIds([]);onPreview(null);
  void pageLineCandidates(project.project_id,plan,kind,filter,(page-1)*pageSize,pageSize,controller.signal).then(result=>{
   if(controller.signal.aborted||serial!==pageRequest.current||!sameContext(expected)||reportRef.current?.preview_id!==plan.preview_id||useWorkspace.getState().project?.working_revision!==plan.base_revision)return;
   if(Date.parse(result.expires_at)<=Date.now()){clearReport('检查结果已过期，请重新检查当前线层。');return;}
   setServerPage(result);setError('');
  }).catch(e=>{if(!controller.signal.aborted&&serial===pageRequest.current&&sameContext(expected)){setServerPage(null);setError(e instanceof Error?e.message:String(e));}}).finally(()=>{if(serial===pageRequest.current&&mounted.current)setPagePending(false);});
  return()=>controller.abort();
 },[report?.preview_id,report?.base_revision,paged,kind,filter,page,context,project.working_revision]);
 useEffect(()=>{
  if(!active||!report){onPreview(null);return;}
  const items=[...new Map([...confirmedSelection,...allRows].map(item=>[item.candidate_id,item])).values()].filter(item=>item.candidate_id===highlighted||checked.includes(item.candidate_id));
  onPreview(items.length?{items,checked,highlighted}:null);
 },[report,serverPage,confirmedSelection,checked,highlighted,active]);
 async function choose(id:string,value:boolean){if(disabled)return;const guard=await protect();if(!stillCurrent(guard))return;setChecked(old=>value?[...new Set([...old,id])]:old.filter(item=>item!==id));setError('');}
 async function changeView(nextKind:LineCheckKind,nextFilter:Filter){if(busy||pending||!active)return;const guard=await protect();if(!stillCurrent(guard))return;setKind(nextKind);setFilter(nextFilter);setConfirmedSelection([]);setChecked([]);setVerified([]);setHighlighted('');setReviewIds([]);setPage(1);setError('');}
 async function locate(item:LineCheckCandidate){if(disabled)return;const guard=await protect();if(!stillCurrent(guard))return;setHighlighted(item.candidate_id);onLocate(item.bounds_px,item.feature_ids);}
 async function selectFeatures(item:LineCheckCandidate){if(disabled)return;const guard=await protect();if(!stillCurrent(guard))return;setHighlighted(item.candidate_id);onSelect(item.feature_ids);}
 async function selectAll(value:boolean){if(disabled)return;const guard=await protect();if(!stillCurrent(guard))return;setChecked(value?selectableRows.map(item=>item.candidate_id):[]);}
 async function review(){if(disabled||!reviewable)return;const guard=await protect();if(!stillCurrent(guard))return;const ids=(action==='isolate'?residueNeedsReview:chosen).map(item=>item.candidate_id);if(action==='isolate')await confirmReview(ids);else setReviewIds(ids);}
 async function latestCandidates(plan:LineCheckReport,signal:AbortSignal,requiredIds?:string[]):Promise<{items:LineCheckCandidate[];serverPage:LineCheckPage|null}>{
  if(paged&&!requiredIds){const current=await pageLineCandidates(project.project_id,plan,kind,filter,(page-1)*pageSize,pageSize,signal);return {items:current.items,serverPage:current};}
  const first=await pageLineCandidates(project.project_id,plan,kind,'all',0,200,signal),items=[...first.items];
  for(let offset=200;offset<first.total&&(!requiredIds||requiredIds.some(id=>!items.some(item=>item.candidate_id===id)));offset+=200)items.push(...(await pageLineCandidates(project.project_id,plan,kind,'all',offset,200,signal)).items);
  return {items,serverPage:null};
 }
 async function confirmReview(selectedIds=reviewIds){
  const ids=selectedIds.filter(id=>chosen.some(item=>item.candidate_id===id));
  if(disabled||inFlight.current||!report||!ids.length)return;
  if(action!=='isolate'){const guard=await protect();if(!stillCurrent(guard))return;setVerified(old=>[...new Set([...old,...ids])]);setReviewIds([]);return;}
  const plan=report,expected=contextRef.current;inFlight.current=true;setPending(true);setError('');
  try{
   const guard=await protect(plan);if(!stillCurrent(guard))return;
   const controller=new AbortController(),serial=++requestSerial.current;requestRef.current={controller,revision:plan.base_revision};
   await decideLines(project.project_id,asset.asset_id,plan,ids,'confirm',controller.signal);
   if(!sameContext(expected)||serial!==requestSerial.current||useWorkspace.getState().project?.working_revision!==plan.base_revision)return;
   // Read current shared decisions back before enabling the cleanup action.
   const current=await latestCandidates(plan,controller.signal,chosen.some(item=>item.status==='kept')?ids:undefined);
   if(!sameContext(expected)||serial!==requestSerial.current||useWorkspace.getState().project?.working_revision!==plan.base_revision)return;
   if(paged&&!current.serverPage&&filter==='all'&&page===1){
    current.serverPage=await pageLineCandidates(project.project_id,plan,kind,filter,0,pageSize,controller.signal);
    if(!sameContext(expected)||serial!==requestSerial.current||useWorkspace.getState().project?.working_revision!==plan.base_revision)return;
   }
   const byId=new Map(current.items.filter(item=>item.status!=='applied').map(item=>[item.candidate_id,item]));
   if(ids.some(id=>!byId.get(id)?.manually_confirmed))throw new Error('核对状态已更新，请重新检查所选残线。');
   const next={...plan,candidates:plan.candidates.map(item=>byId.get(item.candidate_id)??item)};
   reportRef.current=next;setReport(next);
   if(paged){setServerPage(current.serverPage);setConfirmedSelection(chosen.map(item=>byId.get(item.candidate_id)??item));}
   if(chosen.some(item=>item.status==='kept')){setFilter('all');setPage(1);}
   setVerified(old=>[...new Set([...old,...ids])]);setReviewIds([]);
  }catch(e){if(sameContext(expected)&&!(e instanceof DOMException&&e.name==='AbortError'))setError(e instanceof Error?e.message:String(e));}
  finally{inFlight.current=false;if(mounted.current)setPending(false);requestRef.current=null;}
 }
 async function decision(value:'keep'|'reopen'){
  if(disabled||inFlight.current||!report||(value==='keep'?!chosenPending:!chosenKept))return;
  const plan=report,ids=chosen.map(item=>item.candidate_id),expected=contextRef.current;inFlight.current=true;setPending(true);setError('');
  try{
   const guard=await protect(plan);if(!stillCurrent(guard))return;
   const controller=new AbortController(),serial=++requestSerial.current;requestRef.current={controller,revision:plan.base_revision};
   await decideLines(project.project_id,asset.asset_id,plan,ids,value,controller.signal);
   if(!sameContext(expected)||serial!==requestSerial.current||useWorkspace.getState().project?.working_revision!==plan.base_revision)return;
   const current=await latestCandidates(plan,controller.signal);
   if(!sameContext(expected)||serial!==requestSerial.current||useWorkspace.getState().project?.working_revision!==plan.base_revision)return;
   const byId=new Map(current.items.filter(item=>item.status!=='applied').map(item=>[item.candidate_id,item]));
   const next={...plan,candidates:plan.candidates.map(item=>byId.get(item.candidate_id)??item)};
   reportRef.current=next;setReport(next);setConfirmedSelection([]);setChecked(mode==='manual'?ids:[]);setVerified(old=>old.filter(id=>!ids.includes(id)));setHighlighted('');
   if(paged)setServerPage(current.serverPage);
  }catch(e){if(sameContext(expected)&&!(e instanceof DOMException&&e.name==='AbortError'))setError(e instanceof Error?e.message:String(e));}
  finally{inFlight.current=false;if(mounted.current)setPending(false);requestRef.current=null;}
 }
 async function apply(){
  if(disabled||inFlight.current||!report||!applicable)return;
  const plan=report,ids=applicableCandidates.map(item=>item.candidate_id),remaining=chosen.length-ids.length,expected=contextRef.current;inFlight.current=true;setPending(true);setError('');
  try{
   const guard=await protect(plan);if(!stillCurrent(guard))return;
   const body:ApplyLineCheckInput={operation_type:'apply_line_check',preview_id:plan.preview_id,candidate_ids:ids,action,verified_candidate_ids:ids};
   const payload=JSON.stringify(body);
   if(idempotency.current?.payload!==payload)idempotency.current={payload,key:crypto.randomUUID()};
   const result=await command(body,{quiet:true,idempotencyKey:idempotency.current.key});
   if(result&&sameContext(expected)){clearReport(remaining?'已清理 '+ids.length+' 项；另有 '+remaining+' 项受保护或已保留对象，需重新检查并确认核对后再清理。':'');feedback.success(successMessages[action]);}
  }catch(e){if(sameContext(expected))setError(e instanceof Error?e.message:String(e));}
  finally{inFlight.current=false;if(mounted.current)setPending(false);}
 }
 async function verifyManual(value:boolean){
  const candidate=manualCandidate;
  if(disabled||!candidate||candidate.status!=='pending'||candidate.blocked_reasons.length||error)return;
  const guard=await protect();if(!stillCurrent(guard))return;
  setChecked([candidate.candidate_id]);setVerified(value?[candidate.candidate_id]:[]);
 }
 function selectedLineBounds(){
  const bounds=[Infinity,Infinity,-Infinity,-Infinity];
  for(const id of manualFeatureIds){
   const item=featuresById[id];if(item?.feature_type!=='line'||item.geometry.type!=='LineString')continue;
   for(const [x,y] of item.geometry.coordinates){bounds[0]=Math.min(bounds[0],x);bounds[1]=Math.min(bounds[1],y);bounds[2]=Math.max(bounds[2],x);bounds[3]=Math.max(bounds[3],y);}
  }
  return Number.isFinite(bounds[0])?bounds:null;
 }

 async function locateManual(issue=false){
  if(disabled)return;
  const candidate=manualCandidate,guard=await protect();if(!stillCurrent(guard))return;
  const locations=issue&&Array.isArray(candidate?.evidence?.issue_locations)?candidate.evidence.issue_locations:[];
  const precise=locations.flatMap(item=>{
   if(!item||typeof item!=='object')return [];
   const location=item as Record<string,unknown>,bounds=location.bounds_px;
   return location.reason_code==='SELF_INTERSECTION'&&location.precise===true&&Array.isArray(bounds)&&bounds.length===4&&bounds.every(value=>typeof value==='number'&&Number.isFinite(value))&&bounds[0]<=bounds[2]&&bounds[1]<=bounds[3]?[bounds as number[]]:[];
  });
  if(precise.length){
   const boxes=precise.map(([x0,y0,x1,y1])=>[Math.max(0,x0-2),Math.max(0,y0-2),Math.min(asset.width_px,x1+2),Math.min(asset.height_px,y1+2)]);
   const geometries:Geometry[]=boxes.map(([x0,y0,x1,y1])=>({type:'Polygon',coordinates:[[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}));
   onLocate([Math.min(...boxes.map(b=>b[0])),Math.min(...boxes.map(b=>b[1])),Math.max(...boxes.map(b=>b[2])),Math.max(...boxes.map(b=>b[3]))],[],geometries);return;
  }
  const bounds=candidate?.bounds_px??selectedLineBounds();if(bounds)onLocate(bounds,candidate?.feature_ids??manualFeatureIds);
 }
 if(mode==='manual'){
  const relatedHistory=(report?.history??[]).filter(item=>item.kind==='join_gap'&&item.allowed_action==='join'&&item.feature_ids.some(id=>manualFeatureIds.includes(id)));
  return <section className="line-check-tools" aria-label="线检查工具">
   <LineContinuationCard features={orderedSelection.split(',').filter(Boolean).map(id=>featuresById[id]).filter((item):item is Feature=>!!item)} candidate={manualCandidate} busy={busy||pending||!active} checking={status==='checking'} attempted={checkAttempted} verified={!!manualCandidate&&verified.includes(manualCandidate.candidate_id)} error={error||(!validManualPath&&!drawingManualConnector?'接续路径需要 2 至 1000 个有效点。':'')} connector={manualConnector??[]} drawing={drawingManualConnector} choosingSecondLine={choosingSecondLine} styles={styles} reason={reason}
    onChooseSecondLine={()=>onChooseSecondLine?.()} onCancelChooseSecondLine={()=>onCancelChooseSecondLine?.()} onReselect={()=>{onCancelManualConnector?.();onReselectLines?.();}} onDrawPath={()=>onDrawManualConnector?.()} onFinishPath={()=>onFinishManualConnector?.()} onClearPath={()=>onCancelManualConnector?.()} onInspect={()=>void inspect()} onVerifiedChange={value=>void verifyManual(value)} onApply={()=>void apply()} onLocateIssue={()=>void locateManual(true)} onLocateScope={()=>void locateManual()} onReopen={manualCandidate?.status==='kept'?()=>void decision('reopen'):undefined}/>
   {relatedHistory.length>0&&<details className="line-continuation-details"><summary>处理记录（{relatedHistory.length}）</summary><ul>{relatedHistory.map(item=><li key={item.operation_id+':'+item.candidate_id}>修订 {item.result_revision} · 已接续 {item.feature_ids.length} 条线</li>)}</ul></details>}
  </section>;
 }
 return <section className="line-check-tools" aria-label="线检查工具">

  <div className="line-check-toolbar">
   <div className="line-check-options"><InspectionStatus ariaLabel="线检查状态" state={status==='checking'?'checking':status==='checked'?'done':'waiting'} attempted={checkAttempted} disabled={busy||pending||!active||!validParameters} onCheck={()=>void inspect()} extra={mode==='automatic'?<><Button disabled={pending} aria-expanded={parametersOpen} onClick={()=>setParametersOpen(value=>!value)}>检查设置</Button>{report&&<span className="line-check-total">共 {report.summary.candidate_count??report.candidates.length} 项</span>}</>:undefined}/></div>
  </div>
  {mode==='automatic'&&parametersOpen&&<div className="line-check-parameters">{parameterFields.map(field=><label key={field.key}>{field.label}（{field.key==='angle_tolerance_deg'?'°':'px'}）<InputNumber aria-label={field.label} min={field.min} max={field.max} disabled={pending} value={parameters[field.key]} onInput={value=>updateSettings(current=>({...current,parameterDrafts:{...current.parameterDrafts,[field.key]:value}}))} onChange={value=>{updateSettings(current=>({...current,parameters:{...current.parameters,[field.key]:value===null?null:Number(value)},parameterDrafts:{...current.parameterDrafts,[field.key]:value===null?'':String(value)}}));}}/></label>)}</div>}
  {report&&<>{mode==='automatic'&&<Tabs aria-label="线检查类型" activeKey={kind} onChange={value=>void changeView(value as LineCheckKind,'pending')} items={kinds.map(item=>({key:item.key,label:item.label+' '+(paged?report.summary[item.key+'_count']??0:allRows.filter(row=>row.kind===item.key).length)}))}/>}
  <Segmented className="line-check-filter" aria-label="线检查状态筛选" size="small" value={filter} disabled={busy||pending||!active} onChange={value=>void changeView(kind,value as Filter)} options={filters.map(item=>({value:item.key,label:item.label+(paged?'':' '+(item.key==='all'?typeRows.length:typeRows.filter(row=>row.status===item.key).length))}))}/>
  <div className="line-check-summary">候选仅供人工核对，不会自动接续。历史 {report.history.length} 项。{Object.entries(report.summary).length>0&&<Tooltip title={<div className="line-check-summary-tip">{Object.entries(report.summary).map(([name,count])=><div key={name}>{summaryLabels[name]??kinds.find(item=>item.key===name)?.label??reason(name)}：{typeof count==='boolean'?(count?'是':'否'):count}</div>)}</div>}><span className="line-check-details" tabIndex={0}>检查数量明细</span></Tooltip>}</div></>}
  {error&&<Alert type="error" showIcon message={error}/>}
  {!withinBatchLimit&&<Alert type="warning" showIcon message="每批最多 2000 项，请减少选择后分批核对、保留或应用。当前选择仍保留。"/>}
  {paged&&<p className="line-check-page-note" role="status">{pagePending?'正在加载候选…':`按类型与状态分页显示全部候选，当前筛选 ${totalRows} 项；翻页清空本页选择。`}</p>}
  {report&&typeof report.summary.dense_endpoint_count==='number'&&report.summary.dense_endpoint_count>0&&report.summary.truncated!==true&&<Alert type="info" showIcon message={'密集端点 '+report.summary.dense_endpoint_count+' 处已跳过自动建议，请人工核对。'}/>}
  {report&&mode==='automatic'&&kind==='text_stroke'&&<p className="line-check-page-note">已检查 {report.summary.scanned_text_count??0} 条文字、{report.summary.scanned_line_count??0} 条线；长线、粘连线和框边缘候选均纳入核对。</p>}
  {report&&typeof report.summary.texts_without_source_region_count==='number'&&report.summary.texts_without_source_region_count>0&&<Alert type="warning" message={report.summary.texts_without_source_region_count+' 条文字缺少有效范围，暂无法检查其残影，请先定位补全。'}/>}
  {report&&<LineCheckTable key={JSON.stringify([report.preview_id,kind,filter,page])} items={visibleRows} checked={checked} verified={verified} highlighted={highlighted} disabled={disabled} selectAll={{checked:allSelected,indeterminate:!allSelected&&selectableRows.some(item=>checked.includes(item.candidate_id)),disabled:disabled||!selectableRows.length,label:!selectableRows.length?'当前没有可核对的候选':filter==='kept'?'全选已保留项':'全选待核对候选',onChange:value=>void selectAll(value)}} parameters={(mode==='automatic'?parameters:manualParameters) as LineCheckParameters} reason={reason} onCheck={(id,value)=>void choose(id,value)} onLocate={item=>void locate(item)} onSelect={item=>void selectFeatures(item)} onReviewResidue={onReviewResidue}/>}
  {totalRows>pageSize&&<div className="line-check-pagination"><Pagination size="small" disabled={disabled} current={page} pageSize={pageSize} total={totalRows} showSizeChanger={false} onChange={value=>{void protect().then(guard=>{if(stillCurrent(guard)){setConfirmedSelection([]);setChecked([]);setVerified([]);setHighlighted('');setReviewIds([]);setPage(value);}});}}/></div>}
  {report&&residueNeedsReview.length>0&&<Alert type="info" message={'所选 '+residueNeedsReview.length+' 项受保护或已保留对象，请先确认核对后再清理。'}/>}
  {report&&chosen.length>0&&<div className="line-check-actionbar" role="toolbar" aria-label="线检查批量操作"><span className="line-check-selection" aria-live="polite">已选 {chosen.length} 项 · 涉及 {new Set(chosen.flatMap(item=>item.feature_ids)).size} 条线{paged&&chosen.some(item=>!visibleRows.some(row=>row.candidate_id===item.candidate_id))?'（含其他页的已核对项）':''}</span><div className="line-check-actionbar-buttons">{chosenKept&&action!=='isolate'?<Button disabled={disabled} onClick={()=>void decision('reopen')}>重新纳入核对</Button>:<><Button disabled={disabled||!chosenPending} onClick={()=>void decision('keep')}>保留原状</Button>{reviewable&&(action==='isolate'?residueNeedsReview.length>0:chosen.some(item=>!verified.includes(item.candidate_id)))&&<Button disabled={disabled} onClick={()=>void review()}>{action==='isolate'?'确认核对':'核对所选'}</Button>}<Button danger={action==='isolate'} type="primary" disabled={disabled||!applicable} title={actionLabels[action]} onClick={()=>void apply()}>{action==='isolate'?'清理残影':'应用所选'}</Button></>}</div></div>}
  <Modal title={'核对所选 '+reviewIds.length+' 项候选'} open={reviewIds.length>0} okText="确认核对" cancelText="返回检查" onCancel={()=>setReviewIds([])} okButtonProps={{disabled}} onOk={()=>void confirmReview()}><p>{action==='isolate'?'请对照原图核对所选残线。确认表示你明确选择清理这些对象，受保护项也将按本次人工选择处理；原有保护原因仍会保留展示。':<>请对照原图确认这些候选适合{actionLabels[action]}，并确认需保护的线与文字已保留。</>}</p><p>{action==='isolate'?'确认后还需点击“清理残影”执行；跨出单一文字范围的线将保留范围外部分。':'确认后仍需点击“应用所选”执行。'}多个候选分别处理，存在共享对象时整批不执行。</p></Modal>
 </section>;
}

export function LineCheckOverlay({display,features}:{display:LineCheckDisplay;features:Record<string,Feature>}){
 const ordered=[...display.items].sort((a,b)=>Number(a.candidate_id===display.highlighted)-Number(b.candidate_id===display.highlighted));
 return <g className="line-check-overlay" pointerEvents="none">{ordered.map(item=><g opacity={display.highlighted&&item.candidate_id!==display.highlighted ? .2 : 1} key={(item.operation_id??'')+item.candidate_id}>{item.feature_ids.map(id=>features[id]?.feature_type==='line'?<path key={id} data-line-check-feature={id} d={geometryPath(features[id].geometry)} fill="none" stroke={item.candidate_id===display.highlighted?'#722ed1':'#fa8c16'} strokeWidth={3} vectorEffect="non-scaling-stroke"/>:null)}{item.connectors.map((segment,index)=><path key={'connector-'+index} data-line-check-connector={item.candidate_id} d={'M '+segment.map(point=>point.join(' ')).join(' L ')} fill="none" stroke="#722ed1" strokeWidth={3} strokeDasharray="5 3" vectorEffect="non-scaling-stroke"/>)}</g>)}</g>;
}

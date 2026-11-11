import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Checkbox,InputNumber,Modal,Pagination,Tabs,Tag} from 'antd';
import {useWorkspace} from '../stores/workspace';
import {geometryPath} from './FeatureGlyph';
import {decideLines,inspectLines} from '../services/lineChecks';
import {feedback} from '../services/feedback';
import type {ApplyLineCheckInput,LineCheckAction,LineCheckCandidate,LineCheckKind,LineCheckParameters,LineCheckReport} from '../services/lineChecks';
import type {Asset,Command,Feature,Project} from '../services/models';
import './LineCheckTools.css';

type Filter='pending'|'kept'|'applied'|'all';
export type LineCheckDisplay={items:LineCheckCandidate[];highlighted:string;checked:string[]};
type Props={project:Project;asset:Asset;active:boolean;busy:boolean;command:Command;flush:()=>Promise<boolean>;onLocate:(bounds:number[])=>void;onSelect:(ids:string[])=>void;onPreview:(display:LineCheckDisplay|null)=>void};
const kinds:{key:LineCheckKind;label:string;action:LineCheckAction}[]=[{key:'join_gap',label:'断线接续',action:'join'},{key:'text_stroke',label:'疑似文字短线',action:'isolate'},{key:'dash_group',label:'虚线编组',action:'group'}];
const filters:{key:Filter;label:string}[]=[{key:'pending',label:'待核对'},{key:'kept',label:'已保留'},{key:'applied',label:'已处理'},{key:'all',label:'全部'}];
const explanations:Record<string,string>={ALIGNED_ENDPOINT_GAP:'端点邻近且方向一致',ENDPOINTS_ALIGNED:'端点邻近且方向一致',ENDPOINT_GAP:'端点间有缺口',TANGENT_ALIGNED:'切向一致',REGULAR_DASH_SPACING:'短段间隔规则',REGULAR_SHORT_SEGMENTS:'间隔规律的短线段可能属于虚线',KNOWN_DASH_PATTERN:'已有虚线样式，应保留间隔',DASH_STYLE:'已有虚线样式',TEXT_OVERLAP:'与文字范围重叠',TEXT_BOX_OVERLAP:'与文字范围重叠',SHORT_LINE_IN_TEXT_REGION:'短线位于文字范围内，需对照原图',ASSOCIATED_TEXT:'存在关联文字',CROSSES_OTHER_LINE:'跨越其他线',CROSSES_THIRD_LINE:'跨越其他线，需保留',AMBIGUOUS_BRANCH:'附近有分叉，接续方向不明确',AMBIGUOUS_ENDPOINT:'附近有多个可能接续端点',ATTRIBUTE_MISMATCH:'线条属性不一致',STYLE_MISMATCH:'线条外观不一致',ROLE_MISMATCH:'线用途不一致',DENSE_ENDPOINT_REGION:'端点分布密集，跳过自动建议',SEMANTIC_LINE_PATTERN:'线型间隔有语义，应保留',DASH_PROTECTED:'虚线间隔需要保留',MANUAL_LINE:'手工线需保留',EXISTING_GROUP_MEMBERSHIP:'已有逻辑编组',ALREADY_GROUPED:'已有编组',GEOLOGICAL_BOUNDARY:'地质分界需保留',GEOLOGICAL_SYMBOL:'地质符号线需保留',CROSSES_TEXT_REGION:'线跨出文字范围，需保留',NON_TEXT_STROKE_COLOR:'线条颜色不像文字笔画',CROSSES_TEXT_BOUNDS:'线延伸到文字框外',SELF_INTERSECTION:'线存在自相交',CYCLIC_CONNECTION:'接续会形成闭合环'};
const summaryLabels:Record<string,string>={join_gap_count:'断线接续',text_stroke_count:'疑似文字短线',dash_group_count:'虚线编组',scanned_line_count:'检查线数',candidate_count:'候选总数',returned_count:'返回候选数',dense_endpoint_count:'密集端点数',truncated:'候选截断'};
const reason=(code:string)=>explanations[code.toUpperCase()]??code;
const pageSize=25;
const actionLabels:Record<LineCheckAction,string>={join:'接续各组线',isolate:'移入隔离层',group:'分别建立编组'};
const successMessages:Record<LineCheckAction,string>={join:'线接续已完成，可撤销。',isolate:'所选短线已移入隔离层，可撤销。',group:'虚线编组已建立，可撤销。'};
const parameterFields:{key:keyof LineCheckParameters;label:string;min:number;max:number}[]=[{key:'max_gap_px',label:'最大接续间距',min:0,max:50},{key:'angle_tolerance_deg',label:'方向偏差上限',min:1,max:45},{key:'max_short_length_px',label:'文字短线长度上限',min:1,max:100}];

export function LineCheckTools({project,asset,active,busy,command,flush,onLocate,onSelect,onPreview}:Props){
 const [report,setReport]=useState<LineCheckReport|null>(null),[kind,setKind]=useState<LineCheckKind>('join_gap'),[filter,setFilter]=useState<Filter>('pending');
 const [checked,setChecked]=useState<string[]>([]),[verified,setVerified]=useState<string[]>([]),[highlighted,setHighlighted]=useState(''),[page,setPage]=useState(1),[parametersOpen,setParametersOpen]=useState(false);
 const [parameters,setParameters]=useState<Record<keyof LineCheckParameters,number|null>>({max_gap_px:8,angle_tolerance_deg:15,max_short_length_px:12});
 const [parameterDrafts,setParameterDrafts]=useState({max_gap_px:'8',angle_tolerance_deg:'15',max_short_length_px:'12'});
 const [status,setStatus]=useState<'idle'|'checking'|'checked'|'error'>('idle'),[pending,setPending]=useState(false),[error,setError]=useState(''),[reviewIds,setReviewIds]=useState<string[]>([]);
 const session=useWorkspace(state=>state.session),layer=useWorkspace(state=>state.layer);
 const context=JSON.stringify([project.project_id,asset.asset_id,session,layer,active]);
 const contextRef=useRef(context),reportRef=useRef(report),requestSerial=useRef(0),requestRef=useRef<{controller:AbortController;revision:number}|null>(null),inFlight=useRef(false),mounted=useRef(true);
 const idempotency=useRef<{payload:string;key:string}|null>(null);contextRef.current=context;reportRef.current=report;
 const parameterKey=JSON.stringify([parameters,parameterDrafts]);
 const validParameters=parameterFields.every(field=>{const value=parameters[field.key];return value!==null&&Number.isFinite(value)&&value>=field.min&&value<=field.max&&/^\+?(?:\d+|\d*\.\d+)$/.test(parameterDrafts[field.key].trim());});
 function clearReport(message=''){
  requestSerial.current++;requestRef.current?.controller.abort();requestRef.current=null;
  reportRef.current=null;setReport(null);setChecked([]);setVerified([]);setHighlighted('');setReviewIds([]);setPage(1);setStatus('idle');setError(message);onPreview(null);idempotency.current=null;
 }
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;requestSerial.current++;requestRef.current?.controller.abort();onPreview(null);};},[]);
 useEffect(()=>{clearReport();},[context,parameterKey]);
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
  const expected=contextRef.current;
  if(!sameContext(expected))return null;
  if(!await flush()){if(sameContext(expected))setError('属性草稿未能保存，请先修正或重试保存。');return null;}
  if(!sameContext(expected))return null;
  const state=useWorkspace.getState();
  if(currentReport&&(reportRef.current?.preview_id!==currentReport.preview_id||currentReport.asset_id!==asset.asset_id||currentReport.base_revision!==state.project?.working_revision||Date.parse(currentReport.expires_at)<=Date.now())){clearReport('项目或检查结果已更新，请重新检查当前线层。');return null;}
  return {expected,revision:state.project!.working_revision,report:currentReport};
 }
 async function inspect(){
  if(busy||inFlight.current||!active||!validParameters)return;
  const expected=contextRef.current;
  inFlight.current=true;setPending(true);setError('');setStatus('checking');
  try{
   const guard=await protect(null);if(!guard)return;
   requestRef.current?.controller.abort();setStatus('checking');
   const controller=new AbortController(),serial=++requestSerial.current;requestRef.current={controller,revision:guard.revision};
   const result=await inspectLines(project.project_id,asset.asset_id,guard.revision,parameters as LineCheckParameters,controller.signal);
   if(!sameContext(guard.expected)||serial!==requestSerial.current||controller.signal.aborted)return;
   if(result.asset_id!==asset.asset_id||result.base_revision!==guard.revision||useWorkspace.getState().project?.working_revision!==guard.revision||Date.parse(result.expires_at)<=Date.now())throw Error('检查结果已失效，请重新检查当前线层。');
   reportRef.current=result;setReport(result);setChecked([]);setVerified([]);setHighlighted('');setReviewIds([]);setPage(1);idempotency.current=null;setStatus('checked');
  }catch(e){if(sameContext(expected)&&!(e instanceof DOMException&&e.name==='AbortError')){setError(e instanceof Error?e.message:String(e));setStatus('error');}}
  finally{inFlight.current=false;if(mounted.current){setPending(false);setStatus(value=>value==='checking'?'idle':value);}requestRef.current=null;}
 }
 const allRows=[...(report?.candidates??[]),...(report?.history??[])];
 const typeRows=allRows.filter(item=>item.kind===kind),rows=typeRows.filter(item=>filter==='all'||item.status===filter);
 const chosen=(report?.candidates??[]).filter(item=>checked.includes(item.candidate_id));
 const withinBatchLimit=chosen.length<=2000;
 const chosenPending=chosen.length>0&&withinBatchLimit&&chosen.every(item=>item.status==='pending'),chosenKept=chosen.length>0&&withinBatchLimit&&chosen.every(item=>item.status==='kept');
 const reviewable=chosenPending&&chosen.every(item=>!item.blocked_reasons.length);
 const action=kinds.find(item=>item.key===kind)!.action;
 const applicable=reviewable&&chosen.every(item=>item.allowed_action===action&&verified.includes(item.candidate_id));
 const disabled=busy||pending||!active;
 const selectableRows=rows.filter(item=>filter==='kept'?item.status==='kept':item.status==='pending'&&!item.blocked_reasons.length);
 const allSelected=selectableRows.length>0&&selectableRows.every(item=>checked.includes(item.candidate_id));
 useEffect(()=>{setPage(current=>Math.min(current,Math.max(1,Math.ceil(rows.length/pageSize))));},[rows.length]);
 useEffect(()=>{
  if(!active||!report){onPreview(null);return;}
  const items=allRows.filter(item=>item.candidate_id===highlighted||checked.includes(item.candidate_id));
  onPreview(items.length?{items,checked,highlighted}:null);
 },[report,checked,highlighted,active]);
 async function choose(id:string,value:boolean){if(disabled||!await protect())return;setChecked(old=>value?[...new Set([...old,id])]:old.filter(item=>item!==id));setError('');}
 async function changeView(nextKind:LineCheckKind,nextFilter:Filter){if(disabled||!await protect())return;setKind(nextKind);setFilter(nextFilter);setChecked([]);setHighlighted('');setReviewIds([]);setPage(1);setError('');}
 async function locate(item:LineCheckCandidate){if(disabled||!await protect())return;setHighlighted(item.candidate_id);onLocate(item.bounds_px);}
 async function selectFeatures(item:LineCheckCandidate){if(disabled||!await protect())return;setHighlighted(item.candidate_id);onSelect(item.feature_ids);}
 async function selectAll(value:boolean){if(disabled||!await protect())return;setChecked(value?selectableRows.map(item=>item.candidate_id):[]);}
 async function review(){if(disabled||!reviewable||!await protect())return;setReviewIds([...checked]);}
 async function confirmReview(){const ids=[...reviewIds];if(disabled||!ids.length||!await protect())return;setVerified(old=>[...new Set([...old,...ids])]);setReviewIds([]);}
 async function decision(value:'keep'|'reopen'){
  if(disabled||inFlight.current||!report||(value==='keep'?!chosenPending:!chosenKept))return;
  const plan=report,ids=[...checked],expected=contextRef.current;inFlight.current=true;setPending(true);setError('');
  try{
   if(!await protect(plan))return;
   const controller=new AbortController(),serial=++requestSerial.current;requestRef.current={controller,revision:plan.base_revision};
   await decideLines(project.project_id,asset.asset_id,plan,ids,value,controller.signal);
   if(!sameContext(expected)||serial!==requestSerial.current||useWorkspace.getState().project?.working_revision!==plan.base_revision)return;
   const next={...plan,candidates:plan.candidates.map(item=>ids.includes(item.candidate_id)?{...item,status:value==='keep'?'kept' as const:'pending' as const}:item)};
   reportRef.current=next;setReport(next);setChecked([]);setVerified(old=>old.filter(id=>!ids.includes(id)));setHighlighted('');
  }catch(e){if(sameContext(expected)&&!(e instanceof DOMException&&e.name==='AbortError'))setError(e instanceof Error?e.message:String(e));}
  finally{inFlight.current=false;if(mounted.current)setPending(false);requestRef.current=null;}
 }
 async function apply(){
  if(disabled||inFlight.current||!report||!applicable)return;
  const plan=report,ids=[...checked],expected=contextRef.current;inFlight.current=true;setPending(true);setError('');
  try{
   if(!await protect(plan))return;
   const body:ApplyLineCheckInput={operation_type:'apply_line_check',preview_id:plan.preview_id,candidate_ids:ids,action,verified_candidate_ids:ids};
   const payload=JSON.stringify(body);
   if(idempotency.current?.payload!==payload)idempotency.current={payload,key:crypto.randomUUID()};
   const result=await command(body,{quiet:true,idempotencyKey:idempotency.current.key});
   if(result&&sameContext(expected)){clearReport();feedback.success(successMessages[action]);}
  }catch(e){if(sameContext(expected))setError(e instanceof Error?e.message:String(e));}
  finally{inFlight.current=false;if(mounted.current)setPending(false);}
 }
 return <section className="line-check-tools" aria-label="线检查工具">
  <div className="line-check-toolbar">
   <div className="line-check-options"><span className="line-check-state" role="status" aria-label="线检查状态" aria-live="polite" data-state={status}>{status==='checking'?'正在检查…':status==='checked'?'已检查':status==='error'?'检查失败':'等待检查'}</span><div className="property-operation-group"><Button disabled={disabled||!validParameters} onClick={()=>void inspect()}>{report?'重新检查':'检查当前线层'}</Button><Button disabled={pending} aria-expanded={parametersOpen} onClick={()=>setParametersOpen(value=>!value)}>检查设置</Button></div></div>
   <div className="line-check-actions"><span className="line-check-selection" aria-live="polite">已选 {chosen.length} 项 · 涉及 {new Set(chosen.flatMap(item=>item.feature_ids)).size} 条线</span><div className="property-operation-group"><Button disabled={disabled||!chosenPending} onClick={()=>void decision('keep')}>保留原状</Button><Button disabled={disabled||!chosenKept} onClick={()=>void decision('reopen')}>重新纳入核对</Button></div><div className="property-operation-group">{reviewable&&chosen.some(item=>!verified.includes(item.candidate_id))&&<Button disabled={disabled} onClick={()=>void review()}>核对所选</Button>}<Button disabled={disabled||!applicable} title={actionLabels[action]} onClick={()=>void apply()}>应用所选</Button></div></div>
  </div>
  {parametersOpen&&<div className="line-check-parameters">{parameterFields.map(field=><label key={field.key}>{field.label}（{field.key==='angle_tolerance_deg'?'°':'px'}）<InputNumber aria-label={field.label} min={field.min} max={field.max} disabled={pending} value={parameters[field.key]} onInput={value=>setParameterDrafts(old=>({...old,[field.key]:value}))} onChange={value=>{setParameters(old=>({...old,[field.key]:value===null?null:Number(value)}));setParameterDrafts(old=>({...old,[field.key]:value===null?'':String(value)}));}}/></label>)}</div>}
  <Tabs aria-label="线检查类型" activeKey={kind} onChange={value=>void changeView(value as LineCheckKind,'pending')} items={kinds.map(item=>({key:item.key,label:item.label+(report?' '+allRows.filter(row=>row.kind===item.key).length:'')}))}/>
  <Tabs aria-label="线检查状态筛选" activeKey={filter} size="small" onChange={value=>void changeView(kind,value as Filter)} items={filters.map(item=>({key:item.key,label:item.label}))}/>
  <div className="line-check-summary">候选仅供人工核对。{report?`当前检查 ${report.candidates.length} 项候选，历史 ${report.history.length} 项。`:'点击检查当前线层生成全图候选。'}{report&&Object.entries(report.summary).length>0&&<details className="line-check-details"><summary>检查数量</summary>{Object.entries(report.summary).map(([name,count])=><span key={name}>{summaryLabels[name]??kinds.find(item=>item.key===name)?.label??reason(name)} {typeof count==='boolean'?(count?'是':'否'):count}　</span>)}</details>}</div>
  {error&&<Alert type="error" showIcon message={error}/>}
  {!withinBatchLimit&&<Alert type="warning" showIcon message="每批最多 2000 项，请减少选择后分批核对、保留或应用。当前选择仍保留。"/>}
  {report&&report.summary.truncated===true&&<Alert type="warning" showIcon message={'候选较多，仅显示 '+String(report.summary.returned_count??report.candidates.length)+' / '+String(report.summary.candidate_count??'未知')+' 项；候选已截断，请调整参数后继续检查。密集端点 '+String(report.summary.dense_endpoint_count??0)+' 处已跳过自动建议。'}/>}
  {report&&typeof report.summary.dense_endpoint_count==='number'&&report.summary.dense_endpoint_count>0&&report.summary.truncated!==true&&<Alert type="info" showIcon message={'密集端点 '+report.summary.dense_endpoint_count+' 处已跳过自动建议，请人工核对。'}/>}
  {report&&<Checkbox checked={allSelected} indeterminate={!allSelected&&selectableRows.some(item=>checked.includes(item.candidate_id))} disabled={disabled||!selectableRows.length} onChange={event=>void selectAll(event.target.checked)}>{filter==='kept'?'全选已保留项':'全选可处理候选'}</Checkbox>}
  <div className="line-check-table-wrap"><table className="line-check-table" aria-label="线检查候选"><thead><tr><th>选择</th><th>对象数量</th><th>关键证据</th><th>依据与风险</th><th>核对状态</th><th>操作</th></tr></thead><tbody>{rows.slice((page-1)*pageSize,page*pageSize).map(item=><tr key={(item.operation_id??'')+item.candidate_id} data-candidate-id={item.candidate_id} data-operation-id={item.operation_id} className={highlighted===item.candidate_id?'is-highlighted':''}>
   <td><Checkbox aria-label={'选择线候选 '+item.candidate_id} disabled={disabled||item.status==='applied'} checked={item.status!=='applied'&&checked.includes(item.candidate_id)} onChange={event=>void choose(item.candidate_id,event.target.checked)}/></td>
   <td>{item.feature_ids.length} 条线{item.reference_text_ids.length>0&&<small>关联文字 {item.reference_text_ids.length}</small>}</td>
   <td><div className="line-check-evidence">{Object.entries(item.metrics).slice(0,5).map(([name,value])=><span key={name}>{({gap_px:'间距',angle_delta_deg:'方向偏差',length_px:'长度',segment_count:'线段数',spacing_cv:'间隔变异系数'} as Record<string,string>)[name]??name} {Number(value.toFixed(2))}{name.endsWith('_px')?' px':name.endsWith('_deg')?'°':''}</span>)}</div></td>
   <td><div className="line-check-evidence">{item.reason_codes.map(code=><span key={code}>{reason(code)}</span>)}{item.blocked_reasons.map(code=><Tag key={code} color="orange">{reason(code)}</Tag>)}</div></td>
   <td>{item.status==='applied'?'已处理':item.status==='kept'?'已保留':verified.includes(item.candidate_id)?'已核对':'待核对'}{item.result_revision!==undefined&&<small>修订 {item.result_revision}</small>}{item.blocked_reasons.length>0&&<small>受保护，不可直接应用</small>}</td>
   <td><div className="line-check-row-actions"><Button size="small" disabled={disabled} onClick={()=>void locate(item)}>定位</Button>{item.status!=='applied'&&<Button size="small" disabled={disabled} onClick={()=>void selectFeatures(item)}>加入选区</Button>}</div></td>
  </tr>)}</tbody></table>{!rows.length&&<div className="line-check-empty">{report?'当前筛选没有候选。':'尚未检查当前线层。'}</div>}</div>
  {rows.length>pageSize&&<div className="line-check-pagination"><Pagination size="small" current={page} pageSize={pageSize} total={rows.length} showSizeChanger={false} onChange={value=>{void protect().then(guard=>{if(guard)setPage(value);});}}/></div>}
  <Modal title={'核对所选 '+reviewIds.length+' 项候选'} open={reviewIds.length>0} okText="确认核对" cancelText="返回检查" onCancel={()=>setReviewIds([])} okButtonProps={{disabled}} onOk={()=>void confirmReview()}><p>请对照原图确认这些候选适合{actionLabels[action]}，并确认需保护的线与文字已保留。</p><p>确认后仍需点击“应用所选”执行。多个候选分别处理，存在共享对象时整批不执行。</p></Modal>
 </section>;
}

export function LineCheckOverlay({display,features}:{display:LineCheckDisplay;features:Record<string,Feature>}){
 return <g className="line-check-overlay" pointerEvents="none">{display.items.map(item=><g key={(item.operation_id??'')+item.candidate_id}>{item.feature_ids.map(id=>features[id]?.feature_type==='line'?<path key={id} data-line-check-feature={id} d={geometryPath(features[id].geometry)} fill="none" stroke={item.candidate_id===display.highlighted?'#d4380d':'#fa8c16'} strokeWidth={3} vectorEffect="non-scaling-stroke"/>:null)}{item.connectors.map((segment,index)=><path key={'connector-'+index} data-line-check-connector={item.candidate_id} d={'M '+segment[0].join(' ')+' L '+segment[1].join(' ')} fill="none" stroke="#722ed1" strokeWidth={3} strokeDasharray="5 3" vectorEffect="non-scaling-stroke"/>)}</g>)}</g>;
}

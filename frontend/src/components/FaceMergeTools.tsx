import {ReasonList} from './ReasonList';
import {useEffect,useId,useRef,useState} from 'react';
import {Alert,Button,Checkbox,Collapse,Empty,Radio,Tag,Tooltip} from 'antd';
import {useWorkspace} from '../stores/workspace';
import type {Asset,Command,Feature,Geometry,Preview,PreviewItem,Project,Work} from '../services/models';
import {createFaceMergePreview,faceMergeCapabilityReason,faceMergeReason} from '../services/faceMerges';
import type {FaceMergeMode,FaceMergePreview} from '../services/faceMerges';
import {InspectionStatus} from './InspectionStatus';
import './FaceMergeTools.css';

type Props={project:Project;asset:Asset;selected:string[];active:boolean;visible:boolean;busy:boolean;onApplied:()=>void;features:Record<string,Feature>;work:Work;command:Command;flush:()=>Promise<boolean>;preview:(kind:'merge_faces'|'merge_suggest',ids:string[])=>Promise<Preview|undefined>;onClearFocus:()=>void;onLocate:(bounds:number[],ids:string[],label:string,geometries?:Geometry[])=>void;onAdopt:(ids:string[])=>Promise<void>;info:(text:string)=>void;onPreview?:(preview:FaceMergePreview|null)=>void};
type InspectionMode='selected'|'neighbors';
type WorkspaceProps=Props&{mode:InspectionMode;nameFor:(id:string)=>string};
type Inspection={report:Preview;candidates:PreviewItem[]};
const modes:{mode:FaceMergeMode;label:string}[]=[{mode:'single',label:'合并为一个面'},{mode:'multipart',label:'合并为多部件面'},{mode:'gap_single',label:'修复缝隙并合并为一个面'}];
const riskLabels:Record<string,string>={not_connected_to_seed:'候选面与起始面不相连',nearby_gap:'近邻面之间存在缝隙',adjacent_unverified:'相邻面需核对归属',crosses_split_line:'可能跨越真实分界线',mixed_label:'候选识别标签不同',outside_roi:'涉及范围外的面',narrow_band:'包含狭长面'};
const idsKey=(ids:string[])=>JSON.stringify([...ids].sort());
const emptyReviews=():Record<FaceMergeMode,string[]>=>({single:[],multipart:[],gap_single:[]});
function geometryArea(coordinates:unknown,type:string):number{
 const ringArea=(ring:unknown)=>{if(!Array.isArray(ring))return 0;let area=0;for(let i=0;i<ring.length;i++){const a=ring[i],b=ring[(i+1)%ring.length];if(Array.isArray(a)&&Array.isArray(b)&&a.every(Number.isFinite)&&b.every(Number.isFinite))area+=a[0]*b[1]-b[0]*a[1];}return Math.abs(area)/2;};
 const polygonArea=(polygon:unknown)=>Array.isArray(polygon)?Math.max(0,ringArea(polygon[0])-polygon.slice(1).reduce((sum,ring)=>sum+ringArea(ring),0)):0;
 return type==='MultiPolygon'&&Array.isArray(coordinates)?coordinates.reduce((sum,polygon)=>sum+polygonArea(polygon),0):polygonArea(coordinates);
}
export function FaceMergeTools(props:Props){
 const session=useWorkspace(state=>state.session),context=JSON.stringify([props.project.project_id,props.asset.asset_id,session]);
 const [expandedGroup,setExpandedGroup]=useState<InspectionMode|null>(null);
 const groupRef=useRef(expandedGroup);groupRef.current=expandedGroup;
 const aliases=useRef({context,items:new Map<string,string>()});
 if(aliases.current.context!==context)aliases.current={context,items:new Map()};
 function nameFor(id:string){let name=aliases.current.items.get(id);if(!name){name='面'+(aliases.current.items.size+1);aliases.current.items.set(id,name);}return name;}
 [...props.selected].sort().forEach(nameFor);
 const callbacks=useRef(props);callbacks.current=props;
 useEffect(()=>{callbacks.current.onClearFocus();callbacks.current.onPreview?.(null);},[expandedGroup,props.visible,context]);
 function publish(mode:InspectionMode,preview:FaceMergePreview|null){if(groupRef.current===mode&&props.visible)props.onPreview?.(preview);}
 return <section className="face-merge-tools" aria-label="面合并工作区">
  <Collapse ghost accordion className="line-edit-groups face-merge-groups" activeKey={expandedGroup?[expandedGroup]:[]} onChange={value=>{const key=Array.isArray(value)?value[0]:value;setExpandedGroup(key==='selected'||key==='neighbors'?key:null);}} items={[
   {key:'selected',label:'检查所选面',forceRender:true,children:<FaceMergeInspection {...props} mode="selected" nameFor={nameFor} visible={props.visible&&expandedGroup==='selected'} onPreview={preview=>publish('selected',preview)}/>},
   {key:'neighbors',label:'查找相邻面',forceRender:true,children:<FaceMergeInspection {...props} mode="neighbors" nameFor={nameFor} visible={props.visible&&expandedGroup==='neighbors'} onPreview={preview=>publish('neighbors',preview)}/>}
  ]}/>
 </section>;
}
function FaceMergeInspection({project,asset,selected,active,visible,busy,onApplied,features,work,command,flush,preview,onClearFocus,onLocate,onAdopt,info,onPreview,mode:inspectionMode,nameFor}:WorkspaceProps){
 const [allowMixed,setAllowMixed]=useState(false),[hasChecked,setHasChecked]=useState(false);
 const title=inspectionMode==='selected'?'检查所选面':'查找相邻面';
 const session=useWorkspace(state=>state.session),layer=useWorkspace(state=>state.layer);
 const scope=JSON.stringify([project.project_id,asset.asset_id,session,layer,inspectionMode,idsKey(selected)]);
 const [inspection,setInspection]=useState<Inspection|null>(null),[checked,setChecked]=useState<string[]>([]),[pending,setPending]=useState(false),[error,setError]=useState(''),[expanded,setExpanded]=useState<string[]>([]),[located,setLocated]=useState('');
 const [plan,setPlan]=useState<FaceMergePreview|null>(null),[planLoading,setPlanLoading]=useState(false),[planError,setPlanError]=useState(''),[attributeSource,setAttributeSource]=useState(''),[gapIds,setGapIds]=useState<string[]>([]),[ownership,setOwnership]=useState<string[]>([]),[sourcePreview,setSourcePreview]=useState(''),[verified,setVerified]=useState(emptyReviews),[confirmedGap,setConfirmedGap]=useState('');
 const detailId=useId(),mounted=useRef(false),inFlight=useRef(false),planSequence=useRef(0),idempotency=useRef(new Map<string,string>());
 const currentScope=useRef({scope,visible,active,allowMixed,epoch:0});if(currentScope.current.scope!==scope||currentScope.current.visible!==visible||currentScope.current.active!==active||currentScope.current.allowMixed!==allowMixed)currentScope.current={scope,visible,active,allowMixed,epoch:currentScope.current.epoch+1};
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 function resetExact(){planSequence.current++;setPlan(null);setPlanError('');setGapIds([]);setOwnership([]);setSourcePreview('');setVerified(emptyReviews());setConfirmedGap('');}
 useEffect(()=>{onClearFocus();setInspection(null);setChecked([]);setExpanded([]);setLocated('');setError('');setAttributeSource('');setHasChecked(false);resetExact();},[scope]);
 const validReport=!!inspection&&inspection.report.base_revision===project.working_revision&&(!inspection.report.expires_at||Date.parse(inspection.report.expires_at)>Date.now());
 function same(expected:string){const state=useWorkspace.getState();return mounted.current&&JSON.stringify(currentScope.current)===expected&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id&&state.session===session&&state.layer==='face'&&idsKey(state.selected)===idsKey(selected)&&currentScope.current.active&&currentScope.current.visible;}
 const rows=(inspection?.report.legacy_report.groups??[]).map((group,index)=>{
  const ids=group.feature_ids??[],key=idsKey(ids),risks=[...new Set((inspection?.candidates??[]).filter(item=>ids.includes(item.feature_id??'')).flatMap(item=>item.risks??[]))];
  const bridges=ids.length<2?(group.bridge_feature_ids??[]).filter(id=>!selected.includes(id)):[];
  const reasons=[...(ids.length<2?[bridges.length?'中间隔着 '+bridges.length+' 个未选面':(group.corner_contact_feature_ids?.length?'只在角点接触，可检查多部件合并':'缺少共享边相连的其他面，可检查多部件合并')]:[]),...risks.map(code=>riskLabels[code]??(/^[A-Za-z][A-Za-z0-9_]*$/.test(code)?'存在其他待核对情况':code)),...(group.mixed_algorithm_labels?['识别标签不同']:[]),...((group.colour_conflict_share??0)>0?['原图颜色存在差异']:[])];
  return {group,index,ids,key,reasons,bridges};
 });
 const chosen=rows.filter(row=>checked.includes(row.key)),targetIds=[...new Set(chosen.flatMap(row=>row.ids))],targetKey=idsKey(targetIds);
 function defaultSource(ids:string[]){const area=(id:string)=>{const item=features[id];if(!item)return 0;const cached='area_px2' in item?item.area_px2:undefined;return typeof cached==='number'&&Number.isFinite(cached)&&cached>=0?cached:geometryArea(item.geometry.coordinates,item.geometry.type);};return [...ids].sort((a,b)=>area(b)-area(a)||(a<b?-1:a>b?1:0))[0];}
 const source=targetIds.includes(attributeSource)?attributeSource:defaultSource(targetIds);
 const binding=JSON.stringify([scope,targetKey,source,allowMixed,gapIds,ownership,sourcePreview,project.working_revision]);
 const planBinding=useRef(''),live=useRef({flush,onPreview});live.current={flush,onPreview};
 // Discovery is explicit. Only an already checked execution range is re-previewed.
 useEffect(()=>{
  const sequence=++planSequence.current;setPlan(null);setPlanError('');setVerified(emptyReviews());setConfirmedGap('');setPlanLoading(false);
  if(!inspection||!validReport||targetIds.length<2||targetIds.length>1000||!active||!visible)return;
  const expected=JSON.stringify(currentScope.current),controller=new AbortController();setPlanLoading(true);
  const timer=window.setTimeout(()=>{void(async()=>{try{
   if(!await live.current.flush()||!same(expected)||sequence!==planSequence.current)return;
   const revision=useWorkspace.getState().project?.working_revision;if(revision===undefined)return;
   const result=await createFaceMergePreview(project.project_id,{asset_id:asset.asset_id,base_revision:revision,feature_ids:targetIds,attribute_source_feature_id:source,allow_mixed_algorithm_labels:allowMixed,selected_gap_candidate_ids:gapIds,ownership_transfer_feature_ids:ownership,...(sourcePreview?{source_preview_id:sourcePreview}:{}),parameters:{max_added_area_px2:150}},controller.signal);
   if(!same(expected)||sequence!==planSequence.current)return;
   if(result.asset_id!==asset.asset_id||result.base_revision!==useWorkspace.getState().project?.working_revision||idsKey(result.feature_ids)!==targetKey||result.attribute_source_feature_id!==source||idsKey(result.selected_gap_candidate_ids??[])!==idsKey(gapIds)||!Number.isFinite(Date.parse(result.expires_at))||Date.parse(result.expires_at)<=Date.now())throw Error('合并检查范围已变化或过期，请重新检查。');
   planBinding.current=binding;setPlan(result);
  }catch(e){if(!controller.signal.aborted&&same(expected)&&sequence===planSequence.current)setPlanError(e instanceof Error?e.message:String(e));}finally{if(mounted.current&&sequence===planSequence.current)setPlanLoading(false);}})();},180);
  return()=>{window.clearTimeout(timer);controller.abort();};
 },[binding,inspection,validReport,active,visible]);
 const exact=!!plan&&planBinding.current===binding&&plan.base_revision===project.working_revision&&Date.parse(plan.expires_at)>Date.now()&&validReport;
 useEffect(()=>{if(!plan)return;const timer=window.setTimeout(()=>{planSequence.current++;setPlan(null);setPlanError('合并检查已过期，请重新检查。');setVerified(emptyReviews());setConfirmedGap('');},Math.min(2147483647,Math.max(0,Date.parse(plan.expires_at)-Date.now())));return()=>window.clearTimeout(timer);},[plan?.preview_id]);
 useEffect(()=>{live.current.onPreview?.(exact&&active&&visible?plan:null);return()=>live.current.onPreview?.(null);},[plan,exact,active,visible]);
 const disabled=busy||pending||!active||!visible,gapConfirmation=JSON.stringify([plan?.preview_id,gapIds,ownership]);
 function modeReason(mode:FaceMergeMode){
  if(disabled)return '当前操作不可用';if(planLoading)return '正在检查当前勾选范围';if(!exact)return planError||'请勾选至少两个面并等待检查完成';
  const cap=plan!.capabilities[mode],blocked=faceMergeCapabilityReason(mode,cap);if(blocked)return blocked;
  if(reviewModes.length>0||needsGapConfirmation)return '请先确认所选核对';
  if(mode==='gap_single'&&(!gapIds.length||confirmedGap!==gapConfirmation))return '请明确选择并确认本次局部补缝范围';return '';
 }
 const reviewModes=exact?modes.filter(({mode})=>{const cap=plan!.capabilities[mode];return !faceMergeCapabilityReason(mode,cap)&&cap.review_required&&(!cap.review_evidence_ids.length||!cap.review_evidence_ids.every(id=>verified[mode].includes(id)));}):[];
 const needsGapConfirmation=exact&&gapIds.length>0&&confirmedGap!==gapConfirmation;
 function run(action:(expected:string)=>Promise<void>){if(disabled||inFlight.current)return;const expected=JSON.stringify(currentScope.current);inFlight.current=true;setPending(true);setError('');void work(async()=>{try{await action(expected);}catch(e){if(same(expected))setError(e instanceof Error?e.message:String(e));}finally{inFlight.current=false;if(mounted.current)setPending(false);}});}
 function inspect(){const suggest=inspectionMode==='neighbors';run(async expected=>{
  setHasChecked(true);
  onClearFocus();setLocated('');setInspection(null);setChecked([]);setExpanded([]);resetExact();if(!selected.length||!await flush()||!same(expected))return;
  let ids=[...selected];const suggestions=await preview('merge_suggest',ids);if(!suggestions||!same(expected))return;const candidates=suggestions.legacy_report.candidates??[];if(suggest)ids=[...new Set([...ids,...candidates.map(item=>item.feature_id).filter((id):id is string=>!!id)])];
  const report=await preview('merge_faces',ids);if(!report||!same(expected))return;const members=(report.legacy_report.groups??[]).flatMap(group=>group.feature_ids??[]);
  if(report.preview_type!=='merge_faces'||report.base_revision!==useWorkspace.getState().project?.working_revision||idsKey(report.feature_ids)!==idsKey(ids)||members.length!==ids.length||new Set(members).size!==ids.length||idsKey(members)!==idsKey(ids))throw Error('合并检查结果不完整，请重新检查。');setInspection({report,candidates});setAttributeSource('');setExpanded([]);
 });}
 async function guardReport(expected:string){if(!inspection||!await flush()||!same(expected))return false;const expires=inspection.report.expires_at;if(useWorkspace.getState().project?.working_revision!==inspection.report.base_revision||expires&&(!Number.isFinite(Date.parse(expires))||Date.parse(expires)<=Date.now()))throw Error('合并检查已更新或过期，请重新检查。');return true;}
 function changeChecked(next:string[]){setChecked(next);resetExact();}
 function apply(mode:FaceMergeMode){run(async expected=>{
  if(modeReason(mode)||!plan||!await flush()||!same(expected))return;if(plan.base_revision!==useWorkspace.getState().project?.working_revision||Date.parse(plan.expires_at)<=Date.now()||planBinding.current!==binding)throw Error('项目或合并检查已更新，请重新检查。');
  const key=plan.preview_id+':'+mode;let id=idempotency.current.get(key);if(!id){id=crypto.randomUUID();idempotency.current.set(key,id);}
  const body={operation_type:'apply_face_merge' as const,feature_ids:targetIds,preview_id:plan.preview_id,mode,verified_review_evidence_ids:verified[mode],confirmed_gap_candidate_ids:mode==='gap_single'?gapIds:[],confirmed_ownership_transfer_feature_ids:mode==='gap_single'?ownership:[]};const result=await command(body,{idempotencyKey:id});
  if(result&&same(expected)){onApplied();setInspection(null);setChecked([]);resetExact();info('面合并已完成，可撤销。');}
 });}
 function confirmReview(){run(async expected=>{if(!exact||!plan||!await guardReport(expected)||Date.parse(plan.expires_at)<=Date.now())return;setVerified(Object.fromEntries(modes.map(({mode})=>[mode,[...(plan.capabilities[mode].review_evidence_ids??[])]])) as Record<FaceMergeMode,string[]>);setConfirmedGap(gapConfirmation);info('已确认当前所选范围的核对依据。');});}
 function locate(ids:string[],index:number){run(async expected=>{if(!await guardReport(expected))return;const points:number[][]=[];const visit=(value:unknown)=>{if(!Array.isArray(value))return;if(typeof value[0]==='number'&&typeof value[1]==='number')points.push(value as number[]);else value.forEach(visit);};ids.forEach(id=>{if(features[id])visit(features[id].geometry.coordinates);});if(points.length){setLocated(idsKey(ids));onLocate([Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))],ids,'合并第 '+(index+1)+' 组 · '+ids.length+' 个面');}});}
 function locateGap(geometry:Geometry,index:number){run(async expected=>{
  if(!exact||!plan||!await guardReport(expected)||Date.parse(plan.expires_at)<=Date.now())return;
  const bounds=[Infinity,Infinity,-Infinity,-Infinity];
  const visit=(value:unknown)=>{if(!Array.isArray(value))return;if(typeof value[0]==='number'&&typeof value[1]==='number'){if(Number.isFinite(value[0])&&Number.isFinite(value[1])){bounds[0]=Math.min(bounds[0],value[0]);bounds[1]=Math.min(bounds[1],value[1]);bounds[2]=Math.max(bounds[2],value[0]);bounds[3]=Math.max(bounds[3],value[1]);}}else for(const child of value)visit(child);};
  visit(geometry.coordinates);if(bounds.every(Number.isFinite))onLocate(bounds,[],'补缝连接口 '+(index+1),[geometry]);
 });}
 function selectOnCanvas(ids:string[],bridge=false){run(async expected=>{if(!await guardReport(expected))return;await onAdopt(ids);if(bridge)info('已选中中间面，请核对后点击“检查所选面”。');});}
 function changeGap(next:string[]){if(!plan)return;setSourcePreview(plan.preview_id);setGapIds(next);setOwnership([]);setPlan(null);setVerified(emptyReviews());setConfirmedGap('');}
 function changeOwnership(next:string[]){if(!plan)return;setSourcePreview(plan.preview_id);setOwnership(next);setPlan(null);setVerified(emptyReviews());setConfirmedGap('');}
 function faceReference(id:string){const feature=features[id],area=feature?.feature_type==='face'?feature.area_px2:null;return <span className="face-merge-reference" title={id}><i aria-hidden="true" style={{background:feature?.feature_type==='face'?feature.fill_color??'#d9d9d9':'#d9d9d9'}}/><span>{nameFor(id)}{typeof area==='number'&&Number.isFinite(area)?' · '+Number(area.toFixed(1))+' px²':''}</span></span>;}
 return <section className="face-merge-inspection" aria-label={title+'工作区'}>
  <div className="face-merge-controls">
   <div className="face-merge-toolbar"><InspectionStatus state={pending||planLoading?'checking':validReport&&!error&&!planError?'done':'waiting'} attempted={hasChecked} disabled={disabled||selected.length<(inspectionMode==='selected'?2:1)||planLoading} onCheck={inspect}/><Checkbox className="face-merge-settings" disabled={disabled} checked={allowMixed} onChange={event=>{setAllowMixed(event.target.checked);setSourcePreview('');setGapIds([]);setOwnership([]);}}>允许跨标签合并</Checkbox></div>
   {inspection&&<div className="face-merge-selection"><Checkbox aria-label="全选合并组" disabled={disabled||!validReport||!rows.length} checked={rows.length>0&&rows.every(row=>checked.includes(row.key))} indeterminate={chosen.length>0&&chosen.length<rows.length} onChange={event=>changeChecked(event.target.checked?rows.map(row=>row.key):[])}>全选</Checkbox><span>已选 {chosen.length} 组 · {targetIds.length} 个面</span></div>}
  </div>
  {error&&<Alert type="error" showIcon message={error}/>}{planError&&<Alert type="warning" showIcon message={planError}/>}{inspection&&!validReport&&<Alert type="warning" message="合并检查已更新，请重新检查。"/>}
  {inspection&&<>
   {exact&&plan!.truncated&&<span role="status" className="face-merge-truncation">候选过多，已截断，请缩小检查范围</span>}
   {rows.length?<ul className="face-merge-list" aria-label="合并候选组">{rows.map(row=>{const open=expanded.includes(row.key),panelId=detailId+'-group-'+row.index,isChecked=checked.includes(row.key),status=!isChecked?'待选择':planLoading?'检查中':planError?'检查失败':exact?(reviewModes.length||needsGapConfirmation?'待核对':'已检查'):'待检查';return <li key={row.key} className="face-merge-item" data-merge-group={row.index+1} aria-current={row.key===located?'true':undefined}>
    <div className="face-merge-item-summary"><Checkbox aria-label={'选择合并组 '+(row.index+1)} disabled={disabled||!validReport} checked={isChecked} onChange={event=>changeChecked(event.target.checked?[...checked,row.key]:checked.filter(key=>key!==row.key))}/><span className="face-merge-item-size">{row.ids.length} 个面 · {typeof row.group.area==='number'&&Number.isFinite(row.group.area)?Number(row.group.area.toFixed(1)):'—'} px²</span><Tag color={status==='检查失败'?'red':status==='待核对'?'orange':status==='已检查'?'blue':undefined}>{status}</Tag><div className="face-merge-row-actions"><Button disabled={disabled||!validReport} onClick={()=>locate(row.ids,row.index)}>定位</Button><Button aria-expanded={open} aria-controls={panelId} onClick={()=>setExpanded(old=>open?old.filter(key=>key!==row.key):[...old,row.key])}>{open?'收起':'详情'}</Button></div></div>
    {open&&<div id={panelId} role="region" aria-label={'合并组 '+(row.index+1)+' 详情'} className="face-merge-details">
     <table className="face-merge-detail-table" aria-label={'合并组 '+(row.index+1)+' 检查详情'}><colgroup><col className="face-merge-reason-column"/><col className="face-merge-object-column"/><col className="face-merge-source-column"/></colgroup><thead><tr><th scope="col">原因</th><th scope="col">涉及对象</th><th scope="col">属性来源</th></tr></thead><tbody><tr><td><ReasonList className="inspection-reasons" items={row.reasons.length?row.reasons:['未发现额外合并风险']}/></td><td><div className="face-merge-detail-objects">{row.ids.map(id=><span key={id}>{faceReference(id)}</span>)}</div></td><td>{isChecked&&targetIds.length?<Radio.Group value={source} onChange={event=>{setAttributeSource(event.target.value);resetExact();}}>{targetIds.map(id=><Radio key={id} value={id} aria-label={'使用 '+nameFor(id)+' 的属性'} disabled={disabled}>{faceReference(id)}{id===source?'（本面）':''}</Radio>)}</Radio.Group>:<span>{faceReference(defaultSource(row.ids))}（本面）</span>}</td></tr></tbody></table>
     {exact&&isChecked&&modes.some(({mode})=>!faceMergeCapabilityReason(mode,plan!.capabilities[mode]))&&<div><span className="face-merge-detail-label">合并结果</span><div className="face-merge-result-summary">{modes.map(({mode,label})=>{const cap=plan!.capabilities[mode];return !faceMergeCapabilityReason(mode,cap)&&<span key={mode} aria-label={label+'结果'}>{label}：{cap.output_component_count} 个部件 · {cap.hole_count} 个孔洞</span>;})}</div></div>}
     <div className="face-merge-detail-actions"><Button title="将本组面设为画布选区，不执行合并" disabled={disabled||!validReport} onClick={()=>selectOnCanvas(row.ids)}>在画布选中</Button>{row.bridges.length>0&&<Button title={'将间隔的 '+row.bridges.map(nameFor).join('、')+' 加入画布选区，供重新检查；不执行合并'} disabled={disabled||!validReport} onClick={()=>selectOnCanvas([...new Set([...selected,...row.bridges])],true)}>选中间隔面</Button>}</div>
    </div>}
   </li>;})}</ul>:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到合并候选"/>}
   {exact&&plan!.gap_candidates.length>0&&<div className="face-merge-gap-candidates" aria-label="局部补缝候选">{plan!.gap_candidates.map((candidate,index)=><div key={candidate.candidate_id} className="face-merge-gap-candidate"><div className="face-merge-gap-summary"><Checkbox aria-label={'选择补缝候选 '+(index+1)} title={candidate.candidate_id} disabled={disabled} checked={gapIds.includes(candidate.candidate_id)} onChange={event=>changeGap(event.target.checked?[...gapIds,candidate.candidate_id]:gapIds.filter(id=>id!==candidate.candidate_id))}>连接口 {index+1} · 宽 {Number(candidate.width_px.toFixed(2))} px · {Number(candidate.area_px2.toFixed(2))} px²</Checkbox><Button disabled={disabled||!exact} onClick={()=>locateGap(candidate.geometry,index)}>定位</Button></div>{candidate.occupying_feature_ids.length>0&&<><span>涉及 {candidate.occupying_feature_ids.length} 个第三方面，局部范围 {Number((candidate.transferred_area_px2??candidate.area_px2).toFixed(2))} px²；其余区域保留</span>{gapIds.includes(candidate.candidate_id)&&candidate.occupying_feature_ids.map(id=><Checkbox key={id} aria-label={'允许局部转移 '+nameFor(id)} disabled={disabled} checked={ownership.includes(id)} onChange={event=>changeOwnership(event.target.checked?[...new Set([...ownership,id])]:ownership.filter(item=>item!==id))}>允许从 {nameFor(id)} 局部转移</Checkbox>)}</>}{candidate.review_reason_codes?.map(code=><span key={code}>{faceMergeReason(code)}</span>)}{candidate.blocked_reasons?.map(code=><span key={code}>{faceMergeReason(code)}</span>)}</div>)}{gapIds.length>0&&<span>保留 {plan!.capabilities.gap_single.hole_count} 个孔洞</span>}</div>}
   {reviewModes.length>0&&<div className="face-merge-review-reasons">{reviewModes.map(({mode,label})=><div key={mode}><span>{label}：</span>{plan!.capabilities[mode].review_reason_codes.map(faceMergeReason).join('；')}</div>)}</div>}
   <div className="face-merge-footer">
    {(reviewModes.length>0||needsGapConfirmation)&&<Button disabled={disabled||!exact} onClick={confirmReview}>确认所选核对</Button>}
    <div className="face-merge-mode-actions">{modes.map(({mode,label})=>{const reason=modeReason(mode);return <Tooltip key={mode} title={reason||undefined} trigger={['hover','focus','click']}><span className="face-merge-disabled-wrapper" tabIndex={reason?0:undefined} role={reason?'group':undefined} aria-label={reason?label+'不可用：'+reason:undefined}><Button style={reason?{pointerEvents:'none'}:undefined} disabled={!!reason} onClick={()=>apply(mode)}>{label}</Button></span></Tooltip>;})}</div>
   </div>
  </>}
 </section>;
}

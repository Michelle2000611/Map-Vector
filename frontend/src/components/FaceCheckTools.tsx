import {ReasonList} from './ReasonList';
import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Checkbox,Pagination,Segmented,Select,Tabs,Tag} from 'antd';
import {InspectionStatus} from './InspectionStatus';
import {useWorkspace} from '../stores/workspace';
import {scanFaces} from '../services/faceChecks';
import type {FaceScanReport} from '../services/faceChecks';
import type {Asset,Command,Project} from '../services/models';
import {request} from '../services/client';
import {faceCandidateEvidence,faceCandidateSelectable,faceCandidateNeedsReview,faceRepairBatchCommand} from '../services/faceRepairBatch';
import type {FaceBatchCandidate,FaceBatchPlan} from '../services/faceRepairBatch';
import './FaceRepairTools.css';
import {statusColor} from './statusTags';

type Props={project:Project;asset:Asset;active:boolean;busy:boolean;onClearFocus:()=>void;onLocateFace:(featureId:string)=>Promise<boolean>;onSelectFace:(featureId:string)=>void;command?:Command;flush?:()=>Promise<boolean>};
const kindLabel:Record<string,string>={spur:'线状附着',void:'孔洞',occupied_hole:'孔洞',boundary_gap:'边界缺口'};

export function FaceCheckTools({project,asset,active,busy,onClearFocus,onLocateFace,onSelectFace,command,flush}:Props){
 const session=useWorkspace(state=>state.session);
 const [report,setReport]=useState<FaceScanReport|null>(null);
 const [status,setStatus]=useState<'idle'|'checking'|'checked'|'error'>('idle'),[error,setError]=useState(''),[located,setLocated]=useState('');
 const [checkAttempted,setCheckAttempted]=useState(false),[kind,setKind]=useState('all'),[page,setPage]=useState(1);
 const [selectedFaces,setSelectedFaces]=useState<string[]>([]),[batchPlans,setBatchPlans]=useState<FaceBatchPlan[]>([]),[batchChecked,setBatchChecked]=useState<string[]>([]),[batchConfirmed,setBatchConfirmed]=useState<string[]>([]),[batchAssignments,setBatchAssignments]=useState<Record<string,string>>({}),[batchPending,setBatchPending]=useState(false),[batchProgress,setBatchProgress]=useState('');
 const batchInFlight=useRef(false),batchSelectionSerial=useRef(0);
 const invalidateBatchConfirmation=()=>{batchSelectionSerial.current++;setBatchConfirmed([]);};
 const batchKey=(source:string,item:FaceBatchCandidate)=>source+':'+item.candidate_id;
 const batchRows=batchPlans.flatMap(plan=>plan.candidates.map(item=>({plan,item,key:batchKey(plan.feature_id,item)})));
 const batchSelected=batchRows.filter(row=>batchChecked.includes(row.key)&&faceCandidateSelectable(row.item));
 const batchReady=batchSelected.filter(row=>row.item.kind!=='spur'||row.item.receiver_options?.some(option=>option.feature_id===batchAssignments[row.key]));
 const batchActionable=batchReady.filter(row=>!faceCandidateNeedsReview(row.item)||batchConfirmed.includes(row.key));
 const rows=(report?.flagged_faces??[]).filter(item=>kind==='all'||(kind==='hole'?item.kinds.some(value=>value==='void'||value==='occupied_hole'):item.kinds.includes(kind)));
 const kindFilters=[{value:'all',label:'全部'},{value:'spur',label:'线状附着'},{value:'hole',label:'孔洞'},{value:'boundary_gap',label:'边界缺口'}];
 const context=JSON.stringify([project.project_id,asset.asset_id,session,active]);
 const contextRef=useRef(context),requestSerial=useRef(0),requestRef=useRef<AbortController|null>(null),mounted=useRef(true);
 contextRef.current=context;
 function sameContext(expected:string){const state=useWorkspace.getState();return mounted.current&&contextRef.current===expected&&state.session===session&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id&&active;}
 async function inspect(){
  if(busy||batchInFlight.current||!active||status==='checking')return;
  clearBatch();
  const expected=contextRef.current;setLocated('');onClearFocus();
  requestRef.current?.abort();
  const controller=new AbortController(),serial=++requestSerial.current;requestRef.current=controller;
  setKind('all');setPage(1);setStatus('checking');setCheckAttempted(true);setReport(null);setError('');
  try{
   const result=await scanFaces(project.project_id,asset.asset_id,controller.signal);
   if(!sameContext(expected)||serial!==requestSerial.current||controller.signal.aborted)return;
   if(result.base_revision!==useWorkspace.getState().project?.working_revision){setError('项目已更新，请重新检查全图。');setStatus('error');return;}
   setReport(result);setStatus('checked');
  }catch(e){
   if(sameContext(expected)&&!(e instanceof DOMException&&e.name==='AbortError')){setError(e instanceof Error?e.message:String(e));setStatus('error');}
  }
 }
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;requestSerial.current++;requestRef.current?.abort();};},[]);
 useEffect(()=>{
  requestRef.current?.abort();requestSerial.current++;
  clearBatch();setKind('all');setPage(1);setReport(null);setStatus('idle');setCheckAttempted(false);setError('');setLocated('');
 },[context]);
 useEffect(()=>{
  // The scan is read-only evidence from one project revision; a later edit
  // (including a repair applied from this same list) can change which faces
  // still need attention, so a stale list must not be presented as current.
  if(batchInFlight.current)return;
  clearBatch();requestRef.current?.abort();requestSerial.current++;
  if(report&&report.base_revision!==project.working_revision){setReport(null);setLocated('');setStatus('idle');setError('项目已更新，请重新检查。');onClearFocus();}
  else setStatus(value=>value==='checking'?'idle':value);
 },[project.working_revision]);
 function clearBatch(){batchSelectionSerial.current++;setSelectedFaces([]);setBatchPlans([]);setBatchChecked([]);setBatchConfirmed([]);setBatchAssignments({});setBatchProgress('');}
 async function prepareBatch(){
  if(busy||batchInFlight.current||!active||!report||!selectedFaces.length)return;
  const expected=contextRef.current;batchInFlight.current=true;setBatchPending(true);setError('');invalidateBatchConfirmation();setBatchPlans([]);setBatchChecked([]);setBatchAssignments({});
  try{
   if(flush&&!await flush())throw Error('属性草稿未能保存，请先修正或重试保存。');
   const revision=useWorkspace.getState().project?.working_revision;
   if(!sameContext(expected)||revision!==report.base_revision)throw Error('项目已更新，请重新检查。');
   const plans:FaceBatchPlan[]=[];
   for(const feature_id of selectedFaces){
    setBatchProgress('正在预览 '+(plans.length+1)+' / '+selectedFaces.length+' 个面');
    const plan=await request<FaceBatchPlan>('/projects/'+project.project_id+'/face-repair-previews',{asset_id:asset.asset_id,feature_id,width_px:2,min_length_px:12,max_area_px2:150});
    if(!sameContext(expected)||useWorkspace.getState().project?.working_revision!==revision)return;
    if(plan.base_revision!==revision||plan.feature_id!==feature_id)throw Error('面预览已变化，请重新检查。');
    plans.push(plan);
   }
   setBatchPlans(plans);setBatchChecked(plans.flatMap(plan=>plan.candidates.filter(faceCandidateSelectable).map(item=>batchKey(plan.feature_id,item))));setBatchAssignments({});setBatchProgress('');
  }catch(e){if(sameContext(expected))setError(e instanceof Error?e.message:String(e));}
  finally{batchInFlight.current=false;setBatchPending(false);}
 }
 function confirmBatch(){
  if(busy||batchInFlight.current||!batchSelected.length||batchReady.length!==batchSelected.length)return;
  setBatchConfirmed(batchSelected.map(row=>row.key));
 }
 async function cleanupBatch(){
  if(busy||batchInFlight.current||!command||!batchActionable.length)return;
  const expected=contextRef.current,chosen=[...batchActionable],remaining=batchSelected.length-batchActionable.length,assignments={...batchAssignments};
  let expectedRevision=useWorkspace.getState().project?.working_revision,completed=0;
  if(expectedRevision!==report?.base_revision){setError('项目已更新，请重新检查并核对。');return;}
  batchInFlight.current=true;setBatchPending(true);setError('');
  try{
   if(flush&&!await flush())throw Error('属性草稿未能保存，请先修正或重试保存。');
   for(const source of [...new Set(chosen.map(row=>row.plan.feature_id))]){
    if(!sameContext(expected)||useWorkspace.getState().project?.working_revision!==expectedRevision)throw Error('项目或影像已更新，剩余组尚未清理。');
    const selected=chosen.filter(row=>row.plan.feature_id===source);
    setBatchProgress('正在清理第 '+(completed+1)+' / '+new Set(chosen.map(row=>row.plan.feature_id)).size+' 组');
    const fresh=await request<FaceBatchPlan>('/projects/'+project.project_id+'/face-repair-previews',{asset_id:asset.asset_id,feature_id:source,width_px:2,min_length_px:12,max_area_px2:150});
    if(!sameContext(expected)||fresh.base_revision!==expectedRevision||useWorkspace.getState().project?.working_revision!==expectedRevision)throw Error('项目已更新，剩余组尚未清理。');
    for(const row of selected){const current=fresh.candidates.find(item=>item.candidate_id===row.item.candidate_id);if(!current||faceCandidateEvidence(current)!==faceCandidateEvidence(row.item))throw Error('后续候选的范围、保护原因或接收面已变化，请重新检查并核对。');}
    const localAssignments=Object.fromEntries(selected.filter(row=>row.item.kind==='spur').map(row=>[row.item.candidate_id,assignments[row.key]]));
    const result=await command(faceRepairBatchCommand(fresh,selected.map(row=>row.item.candidate_id),localAssignments),{quiet:true});
    if(!result)throw Error('清理未提交，剩余组尚未处理。');
    expectedRevision=result.result_revision;completed++;
   }
   if(sameContext(expected)){clearBatch();setReport(null);setStatus('idle');onClearFocus();setError('已清理 '+completed+' 组所选候选，可撤销。'+(remaining?'另有 '+remaining+' 项需先核对或选择接收面。':'')+'请重新检查查看剩余项。');}
  }catch(e){if(sameContext(expected)){setReport(null);setStatus('idle');clearBatch();setError((completed?'已清理 '+completed+' 组。':'')+(e instanceof Error?e.message:String(e)));invalidateBatchConfirmation();}}
  finally{batchInFlight.current=false;setBatchPending(false);setBatchProgress('');}
 }
 return <div className="face-check-panel">
  <InspectionStatus ariaLabel="全局面检查状态" state={status==='checking'?'checking':status==='checked'?'done':'waiting'} attempted={checkAttempted} disabled={busy||batchPending||!active} onCheck={()=>void inspect()} extra={report?<span className="inspection-total">共 {report.flagged_faces.length} 项</span>:undefined}/>
  {error&&<Alert type={status==='error'?'error':'info'} showIcon message={status==='error'?'面检查未完成':error} description={status==='error'?error:undefined}/>}
  {status==='checked'&&report&&<>
   <Tabs aria-label="面检查类型" activeKey="repair" items={[{key:'repair',label:'面修复 '+report.flagged_faces.length}]}/>
   <Segmented aria-label="面修复问题筛选" size="small" value={kind} options={kindFilters} onChange={value=>{setKind(String(value));setPage(1);}}/>
   <p className="review-note">共扫描 {report.scanned_face_count} 个面，{report.flagged_faces.length} 个存在待核对候选。{report.truncated&&'（本资产面数量较多，本次检查已达上限，结果可能不完整。）'}</p>
   <div className="inspection-row-actions"><Checkbox aria-label="全选待检查面" disabled={busy||batchPending||!rows.length} checked={rows.length>0&&rows.every(item=>selectedFaces.includes(item.feature_id))} indeterminate={rows.some(item=>selectedFaces.includes(item.feature_id))&&!rows.every(item=>selectedFaces.includes(item.feature_id))} onChange={event=>{setSelectedFaces(event.target.checked?rows.map(item=>item.feature_id):[]);invalidateBatchConfirmation();}}>全选面</Checkbox><Button size="small" disabled={busy||batchPending||!selectedFaces.length} onClick={()=>void prepareBatch()}>查看所选面候选</Button><span>已选 {selectedFaces.length} 个面</span></div>
   {rows.length===0
    ?<Alert type="success" showIcon message="当前类别未发现需要核对的面"/>
    :<div className="inspection-table-wrap"><table className="inspection-table" aria-label="全局面检查候选"><thead><tr><th scope="col">选择</th><th scope="col">序号</th><th scope="col">候选数</th><th scope="col">检查结果</th><th scope="col">原因</th><th scope="col">涉及对象</th><th scope="col">操作</th></tr></thead><tbody>{rows.slice((page-1)*10,page*10).map((item,index)=><tr key={item.feature_id} aria-selected={located===item.feature_id}>
     <td><Checkbox aria-label={'选择面 '+item.feature_id} checked={selectedFaces.includes(item.feature_id)} disabled={busy||batchPending} onChange={event=>{setSelectedFaces(old=>event.target.checked?[...new Set([...old,item.feature_id])]:old.filter(id=>id!==item.feature_id));invalidateBatchConfirmation();}}/></td><td>{(page-1)*10+index+1}</td><td>{item.candidate_count}</td><td><Tag color={statusColor('待核对')}>待核对</Tag></td><td><ReasonList className="inspection-reasons" items={item.kinds.map(kind=>kindLabel[kind]??kind)}/></td><td><div className="inspection-objects"><span title={item.feature_id}>面 {item.feature_id.slice(0,8)}</span></div></td>
     <td><div className="inspection-row-actions"><Button size="small" disabled={busy||batchPending} onClick={()=>{const expected=contextRef.current;void onLocateFace(item.feature_id).then(ok=>{if(ok&&sameContext(expected))setLocated(item.feature_id);});}}>定位</Button><Button size="small" disabled={busy||batchPending} onClick={()=>onSelectFace(item.feature_id)}>打开修复</Button></div></td>
    </tr>)}</tbody></table></div>}
   {rows.length>10&&<Pagination size="small" current={page} pageSize={10} total={rows.length} showSizeChanger={false} onChange={setPage}/>}
   {!!batchPlans.length&&<div className="face-repair-batch-review" aria-label="全局面批量复核">
    <div className="inspection-row-actions"><Checkbox aria-label="全选全局面候选" disabled={busy||batchPending} checked={batchRows.some(row=>faceCandidateSelectable(row.item))&&batchRows.filter(row=>faceCandidateSelectable(row.item)).every(row=>batchChecked.includes(row.key))} onChange={event=>{setBatchChecked(event.target.checked?batchRows.filter(row=>faceCandidateSelectable(row.item)).map(row=>row.key):[]);invalidateBatchConfirmation();}}>全选候选</Checkbox><span>已选 {batchSelected.length} 项，已确认 {batchSelected.filter(row=>batchConfirmed.includes(row.key)).length} 项</span><Button size="small" disabled={busy||batchPending||!batchSelected.length||batchReady.length!==batchSelected.length} onClick={confirmBatch}>确认核对</Button><Button size="small" danger type="primary" disabled={busy||batchPending||!command||!batchActionable.length} onClick={()=>void cleanupBatch()}>清理所选候选</Button></div>
    <p className="review-note">线状附着需要明确选择接收面。结构受限项需打开单面修复处理；多组按顺序校验和提交，每组可撤销。</p>
    {batchSelected.some(row=>faceCandidateNeedsReview(row.item)&&!batchConfirmed.includes(row.key))&&<Alert type="info" message="受保护、已保留或需核对归属的对象，请先确认核对后再清理；普通候选可直接清理。"/>}
    <div className="inspection-table-wrap"><table className="inspection-table" aria-label="全局面批量修复候选"><thead><tr><th>选择</th><th>来源面</th><th>类型</th><th>状态与原因</th><th>接收面</th><th>操作</th></tr></thead><tbody>{batchRows.map(({plan,item,key})=>{
     const selectable=faceCandidateSelectable(item),confirmed=batchConfirmed.includes(key);
     return <tr key={key}><td><Checkbox aria-label={'选择候选 '+key} disabled={busy||batchPending||!selectable} checked={batchChecked.includes(key)} onChange={event=>{setBatchChecked(old=>event.target.checked?[...new Set([...old,key])]:old.filter(id=>id!==key));invalidateBatchConfirmation();}}/></td><td title={plan.feature_id}>{plan.feature_id.slice(0,8)}</td><td>{kindLabel[item.kind]??item.kind}</td><td><Tag color={selectable?statusColor(confirmed?'可修复':'待核对'):undefined}>{selectable?(confirmed?'已确认':'待核对'):'结构受限'}</Tag><ReasonList items={[item.blocked_reason==='RESIDUE_KEPT'?'此前已保留，需明确重新确认':item.blocked_reason==='PROTECTED_LINE_OR_TEXT'?'涉及独立线或文字，需人工核对':item.blocked_reason==='NO_VALID_EDGE_RECEIVER'?'没有有效共边接收面':!selectable?'几何或覆盖条件不满足':item.review_required?'原图或地质归属需核对':''].filter(Boolean)}/></td><td>{item.kind==='spur'&&selectable?<Select aria-label={'批量接收面 '+key} style={{minWidth:150}} placeholder="选择接收面" disabled={busy||batchPending} value={batchAssignments[key]} onChange={value=>{setBatchAssignments(old=>({...old,[key]:value}));invalidateBatchConfirmation();}} options={item.receiver_options?.map(option=>({value:option.feature_id,label:(option.color??'面')+' · '+option.feature_id.slice(0,8)}))}/>:item.kind==='occupied_hole'||item.kind==='boundary_gap'?'并入来源面':'填补来源面'}</td><td><Button size="small" disabled={busy||batchPending} onClick={()=>void onLocateFace(plan.feature_id)}>定位</Button></td></tr>;
    })}</tbody></table></div>
   </div>}
  </>}
  {batchProgress&&<p role="status" aria-live="polite">{batchProgress}</p>}
 </div>;
}

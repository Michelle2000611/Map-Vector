import {ReasonList} from './ReasonList';
import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Input} from 'antd';
import {ApiError,request} from '../services/client';
import {feedback} from '../services/feedback';
import {useWorkspace} from '../stores/workspace';
import {InspectionStatus} from './InspectionStatus';
import type {Asset,Command,Feature,Preview,Project,Work} from '../services/models';
import './LineToFaceTools.css';

type Snapshot={preview:Preview;scope:string;width:number;color:string;faceIds:string[]};
type Props={project:Project;asset:Asset;selected:Feature[];fillColor:string;active:boolean;busy:boolean;command:Command;work:Work;flush:()=>Promise<boolean>;refreshRevision:()=>Promise<number>;
 onPreview:(preview:Preview|null,previousId?:string)=>void;onLocate:(feature:Feature,previewId:string)=>void};
const strings=(value:unknown):value is string[]=>Array.isArray(value)&&value.every(item=>typeof item==='string'&&item.length>0)&&new Set(value).size===value.length;

export function LineToFaceTools({project,asset,selected,fillColor,active,busy,command,work,flush,refreshRevision,onPreview,onLocate}:Props){
 const session=useWorkspace(state=>state.session),canvasPreview=useWorkspace(state=>state.preview);
 const [widthInput,setWidthInput]=useState(()=>String(selected[0]?.feature_type==='line'?selected[0].stroke_width_px:2));
 const [report,setReport]=useState<Snapshot|null>(null),[checking,setChecking]=useState(false),[applying,setApplying]=useState(false),[attempted,setAttempted]=useState(false),[error,setError]=useState('');
 const ids=selected.map(item=>item.feature_id),selectionKey=JSON.stringify([...ids].sort());
 const baseScope=JSON.stringify([project.project_id,asset.asset_id,session,selectionKey,fillColor]),context=JSON.stringify([baseScope,active]),scope=JSON.stringify([context,widthInput]);
 const current=useRef(scope),reportRef=useRef(report),mounted=useRef(false),serial=useRef(0),flight=useRef<'inspect'|'apply'|null>(null),requestRef=useRef<AbortController|null>(null),requestRevision=useRef<number|null>(null),published=useRef<string|null>(null);
 const idempotency=useRef<{previewId:string;key:string}|null>(null),publish=useRef(onPreview);current.current=scope;publish.current=onPreview;
 const width=Number(widthInput),validWidth=/^\+?(?:\d+|\d*\.\d+)$/.test(widthInput.trim())&&Number.isFinite(width)&&width>=.25&&width<=50;
 const validTargets=selected.length>0&&selected.every(item=>item.feature_type==='line'&&item.lifecycle_status==='active');
 function sameWorkspace(){const state=useWorkspace.getState();return state.session===session&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id;}
 function same(expected:string){const state=useWorkspace.getState();return mounted.current&&current.current===expected&&active&&sameWorkspace()&&state.layer==='line'&&JSON.stringify([...state.selected].sort())===selectionKey;}
 function clearPublished(){const owned=published.current;published.current=null;if(owned)publish.current(null,owned);}
 function invalidate(message=''){
  serial.current++;requestRef.current?.abort();requestRef.current=null;requestRevision.current=null;flight.current=null;reportRef.current=null;clearPublished();idempotency.current=null;
  if(mounted.current){setReport(null);setChecking(false);setApplying(false);setError(message);}
 }
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;serial.current++;requestRef.current?.abort();clearPublished();};},[]);
 useEffect(()=>{invalidate();},[context]);
 useEffect(()=>{setAttempted(false);},[baseScope]);
 useEffect(()=>{
  const revision=useWorkspace.getState().project?.working_revision;
  if(reportRef.current&&reportRef.current.preview.base_revision!==revision||flight.current==='inspect'&&requestRevision.current!==null&&requestRevision.current!==revision)invalidate('项目已更新，请重新检查线转面。');
 },[project.working_revision]);
 useEffect(()=>{
  if(reportRef.current&&canvasPreview?.preview_id!==reportRef.current.preview.preview_id)invalidate();
 },[canvasPreview,report]);
 useEffect(()=>{
  if(!report)return;
  const remaining=Date.parse(report.preview.expires_at??'')-Date.now();
  if(remaining>2147483647)return;
  const timer=window.setTimeout(()=>invalidate('检查结果已过期，请重新检查。'),Math.max(0,remaining));return()=>window.clearTimeout(timer);
 },[report]);
 function validSnapshot(snapshot:Snapshot){
  const state=useWorkspace.getState();
  return same(snapshot.scope)&&reportRef.current===snapshot&&state.preview?.preview_id===snapshot.preview.preview_id&&snapshot.preview.base_revision===state.project?.working_revision&&Date.parse(snapshot.preview.expires_at??'')>Date.now()&&snapshot.preview.feature_ids.every(id=>state.featuresById[id]?.feature_type==='line'&&state.featuresById[id]?.lifecycle_status==='active');
 }
 const valid=!!report&&validSnapshot(report),disabled=busy||applying||!active;
 function changeWidth(value:string){invalidate();setWidthInput(value);}
 async function inspect(){
  if(disabled||flight.current||!validTargets||!validWidth)return;
  invalidate();const ticket=++serial.current,expected=scope;flight.current='inspect';setAttempted(true);setChecking(true);
  const requested=()=>ticket===serial.current&&same(expected);
  try{
   if(!await flush()){if(requested())setError('属性草稿未能保存，请先修正或重试保存。');return;}
   if(!requested())return;
   let revision=useWorkspace.getState().project!.working_revision,result:Preview|undefined;
   for(let attempt=0;attempt<2;attempt++){
    if(!requested())return;
    const controller=new AbortController();requestRef.current=controller;requestRevision.current=revision;
    try{result=await request<Preview>('/projects/'+project.project_id+'/edit-previews',{asset_id:asset.asset_id,base_revision:revision,preview_type:'line_to_face',feature_ids:ids,stroke_width_px:width,fill_color:fillColor},controller.signal,{quiet:true});break;}
    catch(exc){if(attempt===0&&exc instanceof ApiError&&exc.code==='REVISION_CONFLICT'&&requested()){requestRevision.current=null;revision=await refreshRevision();continue;}throw exc;}
   }
   if(!requested())return;
   const faceIds=result?.legacy_report?.affected_face_feature_ids;
   if(!result||result.preview_type!=='line_to_face'||typeof result.preview_id!=='string'||!result.preview_id||result.base_revision!==revision||revision!==useWorkspace.getState().project?.working_revision||!strings(result.feature_ids)||result.feature_ids.length!==ids.length||result.feature_ids.some(id=>!ids.includes(id))||!strings(result.affected_feature_ids)||!strings(faceIds)||!Number.isFinite(Date.parse(result.expires_at??''))||Date.parse(result.expires_at??'')<=Date.now())throw Error('检查结果已失效或不完整，请重新检查。');
   const snapshot={preview:result,scope:expected,width,color:fillColor,faceIds};
   reportRef.current=snapshot;published.current=result.preview_id;publish.current(result);setReport(snapshot);
  }catch(exc){if(requested()&&!(exc instanceof DOMException&&exc.name==='AbortError'))setError(exc instanceof Error?exc.message:String(exc));}
  finally{if(ticket===serial.current){flight.current=null;requestRef.current=null;requestRevision.current=null;if(mounted.current)setChecking(false);}}
 }
 async function locate(featureId:string){
  const snapshot=reportRef.current;if(disabled||checking||flight.current||!snapshot||!validSnapshot(snapshot))return;
  if(!await flush()||!validSnapshot(snapshot))return;
  const feature=useWorkspace.getState().featuresById[featureId];if(feature)onLocate(feature,snapshot.preview.preview_id);
 }
 async function apply(){
  const snapshot=reportRef.current;if(disabled||flight.current||!snapshot||!validSnapshot(snapshot))return;
  const ticket=++serial.current;flight.current='apply';setApplying(true);setError('');
  try{await work(async()=>{
   try{
    if(!await flush()){if(same(snapshot.scope))setError('属性草稿未能保存，请先修正或重试保存。');return;}
    if(!validSnapshot(snapshot)){if(same(snapshot.scope))invalidate('检查结果已更新，请重新检查。');return;}
    if(idempotency.current?.previewId!==snapshot.preview.preview_id)idempotency.current={previewId:snapshot.preview.preview_id,key:crypto.randomUUID()};
    const result=await command({operation_type:'line_to_face',preview_id:snapshot.preview.preview_id,feature_ids:snapshot.preview.feature_ids,stroke_width_px:snapshot.width,fill_color:snapshot.color},{quiet:true,idempotencyKey:idempotency.current.key});
    if(result&&sameWorkspace()){invalidate();feedback.success('线转面已完成，可撤销。');}
   }catch(exc){if(same(snapshot.scope)){if(exc instanceof ApiError&&['PREVIEW_STALE','REVISION_CONFLICT','PREVIEW_TYPE_MISMATCH'].includes(exc.code))invalidate(exc.message);else setError(exc instanceof Error?exc.message:String(exc));}}
  },{quiet:true});}finally{if(ticket===serial.current){flight.current=null;if(mounted.current)setApplying(false);}}
 }
 const rows=valid&&report?[...report.preview.feature_ids.map(id=>({id,type:'line',effect:'生成面后移除原线',reason:'按 '+report.width+' px 线宽生成面'})),...report.faceIds.map(id=>({id,type:'face',effect:'可能局部裁切',reason:'与拟生成面的范围相交'}))]:[];
 return <section className="line-to-face-tools" aria-label="线转面工作区">
  <div className="line-to-face-width"><Input addonBefore="线宽（px）" aria-label="生成面的线宽" role="spinbutton" aria-valuemin={.25} aria-valuemax={50} aria-valuenow={validWidth?width:undefined} aria-invalid={!validWidth} status={validWidth?undefined:'error'} inputMode="decimal" value={widthInput} disabled={disabled} onChange={event=>changeWidth(event.target.value)}/></div>
  <InspectionStatus ariaLabel="线转面检查状态" state={checking?'checking':valid?'done':'waiting'} attempted={attempted} disabled={disabled||!validTargets||!validWidth} onCheck={()=>void inspect()}/>
  {error&&<Alert type="error" showIcon message={error}/>}
  {valid&&report&&<details key={report.preview.preview_id} className="line-to-face-details"><summary>检查明细（源线 {report.preview.feature_ids.length} 条 · 涉及已有面 {report.faceIds.length} 个）</summary>
   <div className="line-to-face-table-wrap"><table className="line-to-face-table" aria-label="线转面检查明细"><thead><tr><th scope="col">对象</th><th scope="col">预计处理</th><th scope="col">原因</th><th scope="col">操作</th></tr></thead><tbody>{rows.map(row=><tr key={row.type+row.id}>
    <td><span title={row.id}>{row.type==='line'?'线':'面'} {row.id.slice(0,8)}</span></td><td>{row.effect}</td><td><ReasonList items={[row.reason]}/></td><td><Button size="small" disabled={disabled||checking||!useWorkspace.getState().featuresById[row.id]} onClick={()=>void locate(row.id)}>定位</Button></td>
   </tr>)}</tbody></table></div>
  </details>}
  <Button aria-label="确认转换" disabled={disabled||checking||!valid} loading={applying} onClick={()=>void apply()}>确认转换</Button>
 </section>;
}

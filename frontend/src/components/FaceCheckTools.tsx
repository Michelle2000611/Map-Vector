import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Tag} from 'antd';
import {useWorkspace} from '../stores/workspace';
import {scanFaces} from '../services/faceChecks';
import type {FaceScanReport} from '../services/faceChecks';
import type {Asset,Project} from '../services/models';
import './FaceRepairTools.css';

type Props={project:Project;asset:Asset;active:boolean;busy:boolean;onClearFocus:()=>void;onLocateFace:(featureId:string)=>Promise<boolean>;onSelectFace:(featureId:string)=>void};
const kindLabel:Record<string,string>={spur:'线状附着',void:'孔洞',occupied_hole:'孔洞',boundary_gap:'边界缺口'};

export function FaceCheckTools({project,asset,active,busy,onClearFocus,onLocateFace,onSelectFace}:Props){
 const session=useWorkspace(state=>state.session);
 const [report,setReport]=useState<FaceScanReport|null>(null);
 const [status,setStatus]=useState<'idle'|'checking'|'checked'|'error'>('idle'),[error,setError]=useState(''),[located,setLocated]=useState('');
 const [checkAttempted,setCheckAttempted]=useState(false);
 const context=JSON.stringify([project.project_id,asset.asset_id,session,active]);
 const contextRef=useRef(context),requestSerial=useRef(0),requestRef=useRef<AbortController|null>(null),mounted=useRef(true);
 contextRef.current=context;
 function sameContext(expected:string){const state=useWorkspace.getState();return mounted.current&&contextRef.current===expected&&state.session===session&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id&&active;}
 async function inspect(){
  if(busy||!active||status==='checking')return;
  const expected=contextRef.current;setLocated('');onClearFocus();
  requestRef.current?.abort();
  const controller=new AbortController(),serial=++requestSerial.current;requestRef.current=controller;
  setStatus('checking');setCheckAttempted(true);setReport(null);setError('');
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
  setReport(null);setStatus('idle');setCheckAttempted(false);setError('');setLocated('');
 },[context]);
 useEffect(()=>{
  // The scan is read-only evidence from one project revision; a later edit
  // (including a repair applied from this same list) can change which faces
  // still need attention, so a stale list must not be presented as current.
  requestRef.current?.abort();requestSerial.current++;
  if(report&&report.base_revision!==project.working_revision){setReport(null);setLocated('');setStatus('idle');setError('项目已更新，请重新检查。');onClearFocus();}
  else setStatus(value=>value==='checking'?'idle':value);
 },[project.working_revision]);
 return <div className="face-check-panel">
  <div className="face-check-toolbar"><Button disabled={busy||!active||status==='checking'} onClick={()=>void inspect()}>{checkAttempted?'重新检查':'开始检查'}</Button><span role="status" aria-label="全局面检查状态" aria-live="polite">{status==='checking'?'正在检查…':status==='checked'?'已检查':status==='error'?'检查失败':''}</span></div>
  {error&&<Alert type={status==='error'?'error':'info'} showIcon message={status==='error'?'面检查未完成':error} description={status==='error'?error:undefined}/>}
  {status==='checked'&&report&&<>
   <p className="review-note">共扫描 {report.scanned_face_count} 个面，{report.flagged_faces.length} 个存在待核对候选。{report.truncated&&'（本资产面数量较多，本次检查已达上限，结果可能不完整。）'}</p>
   {report.flagged_faces.length===0
    ?<Alert type="success" showIcon message="未发现需要核对的面"/>
    :<div className="inspection-table-wrap"><table className="inspection-table" aria-label="全局面检查候选"><thead><tr><th scope="col">序号</th><th scope="col">候选数</th><th scope="col">检查结果</th><th scope="col">原因</th><th scope="col">涉及对象</th><th scope="col">操作</th></tr></thead><tbody>{report.flagged_faces.map((item,index)=><tr key={item.feature_id} aria-selected={located===item.feature_id}>
     <td>{index+1}</td><td>{item.candidate_count}</td><td><Tag color="orange">待核对</Tag></td><td><div className="inspection-reasons">{item.kinds.map(kind=><span key={kind}>{kindLabel[kind]??kind}</span>)}</div></td><td><div className="inspection-objects"><span title={item.feature_id}>面 {item.feature_id.slice(0,8)}</span></div></td>
     <td><div className="inspection-row-actions"><Button size="small" disabled={busy} onClick={()=>{const expected=contextRef.current;void onLocateFace(item.feature_id).then(ok=>{if(ok&&sameContext(expected))setLocated(item.feature_id);});}}>定位</Button><Button size="small" disabled={busy} onClick={()=>onSelectFace(item.feature_id)}>打开修复</Button></div></td>
    </tr>)}</tbody></table></div>}
  </>}
 </div>;
}

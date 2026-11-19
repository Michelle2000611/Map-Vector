import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Select} from 'antd';
import {snapshotScope,roiBounds} from '../services/deliveryChecks';
import type {ScopeMode,SnapshotScope} from '../services/deliveryChecks';
import './QualityPanel.css';
export type ExportScopeState={key:string;ready:boolean;roiId:string|null;scopeMode:ScopeMode};
type Props={projectId:string;assetId:string;snapshotId?:string;currentRevision:number;scopeMode:ScopeMode;busy:boolean;onScopeChange:(mode:ScopeMode)=>void;onReady:(state:ExportScopeState)=>void;onEdit:()=>void};
export function ExportScopeSummary({projectId,assetId,snapshotId,currentRevision,scopeMode,busy,onScopeChange,onReady,onEdit}:Props){
 const key=[projectId,assetId,snapshotId??''].join(':'),live=useRef(key);live.current=key;
 const [result,setResult]=useState<{key:string;data:SnapshotScope}|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0);
 const callbacks=useRef({onScopeChange,onReady});callbacks.current={onScopeChange,onReady};
 useEffect(()=>{setResult(null);setError('');callbacks.current.onReady({key,ready:false,roiId:null,scopeMode:'full'});if(!snapshotId)return;
  const c=new AbortController();void snapshotScope(projectId,snapshotId,c.signal).then(data=>{if(c.signal.aborted||live.current!==key)return;if(data.asset_id!==assetId)throw new Error('所选工作版本属于另一张原图，请重新选择。');setResult({key,data});const mode=data.roi?.scope_mode??'full';callbacks.current.onScopeChange(mode);callbacks.current.onReady({key,ready:true,roiId:data.roi?.roi_id??null,scopeMode:mode});}).catch(e=>{if(!c.signal.aborted&&live.current===key)setError(e instanceof Error?e.message:String(e));});return()=>c.abort();
 },[key,retry]);
 const data=result?.key===key?result.data:null,bounds=data?roiBounds(data.roi):null;
 const change=(mode:ScopeMode)=>{onScopeChange(mode);onReady({key,ready:!!data,roiId:data?.roi?.roi_id??null,scopeMode:mode});};
 return <section className="export-scope-summary" aria-label="导出范围摘要">
  {!snapshotId?<span>选择工作版本后显示其导出范围。</span>:error?<><Alert type="error" showIcon message={error}/><Button size="small" onClick={()=>setRetry(x=>x+1)}>重试读取范围</Button></>:!data?<span role="status">正在读取工作版本的导出范围…</span>:<>
   <strong>导出范围</strong><Select aria-label="导出范围" value={scopeMode} disabled={busy} onChange={change} style={{minWidth:160}} options={[{value:'full',label:'整张原图'},...(data.roi?[{value:'clip',label:'沿边界裁切'},{value:'keep_crossing',label:'保留跨界对象'}]:[])]}/>
   <span>工作版本：修订 {data.working_revision}</span><Button size="small" disabled={busy} onClick={onEdit}>修改范围</Button>
   {scopeMode!=='full'&&bounds&&<span>范围：{bounds.map(n=>Number(n.toFixed(1))).join('，')} px</span>}
   {data.working_revision!==currentRevision&&<p className="delivery-help">当前编辑内容已变化。本次导出使用所选工作版本的数据和范围；如需包含新修改，请先保存工作版本。</p>}
   <p className="delivery-help">{scopeMode==='full'?'导出所选工作版本的整张原图。':scopeMode==='clip'?'面和线沿范围边界裁切；文字按定位点保留。':'与范围相交的对象整件保留，可能超出范围边界。'} 修改范围后需保存新的工作版本。</p>
  </>}
 </section>;
}

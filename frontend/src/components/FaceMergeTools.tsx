import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Checkbox,Empty,Modal,Popover,Tag} from 'antd';
import {useWorkspace} from '../stores/workspace';
import type {Asset,Command,Feature,Preview,PreviewItem,Project,Work} from '../services/models';
import './FaceMergeTools.css';

type Props={project:Project;asset:Asset;selected:string[];active:boolean;busy:boolean;allowMixed:boolean;onAllowMixed:(value:boolean)=>void;onApplied:()=>void;features:Record<string,Feature>;work:Work;command:Command;flush:()=>Promise<boolean>;preview:(kind:'merge_faces'|'merge_suggest',ids:string[])=>Promise<Preview|undefined>;onLocate:(bounds:number[])=>void;onAdopt:(ids:string[])=>Promise<void>;info:(text:string)=>void};
type Inspection={report:Preview;candidates:PreviewItem[]};
const riskLabels:Record<string,string>={crosses_split_line:'可能跨越真实分界线',mixed_label:'候选识别标签不同',outside_roi:'涉及范围外的面',narrow_band:'包含狭长面'};
const evidence=(group:PreviewItem)=>JSON.stringify({ids:[...(group.feature_ids??[])].sort(),polygon:group.single_polygon,labels:[...(group.algorithm_labels??[])].sort(),mixed:group.mixed_algorithm_labels,conflict:group.colour_conflict_share});
const idsKey=(ids:string[])=>JSON.stringify([...ids].sort());

export function FaceMergeTools({project,asset,selected,active,busy,allowMixed,onAllowMixed,onApplied,features,work,command,flush,preview,onLocate,onAdopt,info}:Props){
 const session=useWorkspace(state=>state.session),layer=useWorkspace(state=>state.layer);
 const scope=JSON.stringify([project.project_id,asset.asset_id,session,layer,idsKey(selected)]);
 const [inspection,setInspection]=useState<Inspection|null>(null),[checked,setChecked]=useState<string[]>([]),[verified,setVerified]=useState<string[]>([]),[pending,setPending]=useState(false),[error,setError]=useState(''),[reviewIds,setReviewIds]=useState<string[]>([]);
 const currentScope=useRef({scope,epoch:0}),mounted=useRef(false),inFlight=useRef(false);if(currentScope.current.scope!==scope)currentScope.current={scope,epoch:currentScope.current.epoch+1};
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
 useEffect(()=>{setInspection(null);setChecked([]);setVerified([]);setReviewIds([]);setError('');},[scope]);
 const validReport=!!inspection&&inspection.report.base_revision===project.working_revision&&(!inspection.report.expires_at||Date.parse(inspection.report.expires_at)>Date.now());
 useEffect(()=>{
  if(!inspection?.report.expires_at)return;
  const remaining=Date.parse(inspection.report.expires_at)-Date.now();if(remaining>2147483647)return;
  const timer=window.setTimeout(()=>{setInspection(null);setChecked([]);setVerified([]);setReviewIds([]);setError('合并检查已过期，请重新预览。');},Math.max(0,remaining));return()=>window.clearTimeout(timer);
 },[inspection?.report.preview_id]);
 function same(expected:string){const state=useWorkspace.getState();return mounted.current&&JSON.stringify(currentScope.current)===expected&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id&&state.session===session&&state.layer==='face'&&idsKey(state.selected)===idsKey(selected)&&active;}
 const rows=(inspection?.report.legacy_report.groups??[]).map((group,index)=>{
  const ids=group.feature_ids??[],key=idsKey(ids),risks=[...new Set((inspection?.candidates??[]).filter(item=>ids.includes(item.feature_id??'')).flatMap(item=>item.risks??[]))];
  const mixed=group.mixed_algorithm_labels===true||(group.algorithm_labels?.length??0)>1;
  const possible=ids.length>1&&group.single_polygon===true;
  const allowed=possible&&(!mixed||allowMixed);
  const riskEvidence=ids.every(id=>(inspection?.candidates??[]).some(item=>item.feature_id===id&&Array.isArray(item.risks)));
  const colourEvidence=typeof group.colour_conflict_share==='number'&&Number.isFinite(group.colour_conflict_share);
  const needsReview=mixed||risks.length>0||!riskEvidence||!colourEvidence||(group.colour_conflict_share??0)>0;
  const reviewed=verified.includes(evidence(group));
  const reasons=[...(ids.length<2?['缺少共享边相连的其他面']:group.single_polygon!==true?['合并后不是单个有效面']:[]),...(mixed?['识别标签不同']:[]),...(!riskEvidence?['缺少完整的边界风险依据']:[]),...(!colourEvidence?['缺少原图颜色对照']:[]),...risks.map(code=>riskLabels[code]??'存在需人工核对的依据'),...((group.colour_conflict_share??0)>0?['原图颜色存在差异']:[])];
  return {group,index,ids,key,allowed,needsReview,reviewed,reasons};
 });
 const chosen=rows.filter(row=>checked.includes(row.key)),eligible=rows.filter(row=>row.allowed),needs=chosen.filter(row=>row.allowed&&row.needsReview&&!row.reviewed);
 const canApply=validReport&&chosen.length>0&&chosen.every(row=>row.allowed&&(!row.needsReview||row.reviewed));
 const disabled=busy||pending||!active;
 function run(action:(expected:string)=>Promise<void>){
  if(disabled||inFlight.current)return;
  const expected=JSON.stringify(currentScope.current);inFlight.current=true;setPending(true);setError('');
  void work(async()=>{try{await action(expected);}catch(e){if(same(expected))setError(e instanceof Error?e.message:String(e));}finally{inFlight.current=false;if(mounted.current)setPending(false);}});
 }
 async function checkedPreview(ids:string[],expected:string){
  const result=await preview('merge_faces',ids);if(!result||!same(expected))return;
  const state=useWorkspace.getState(),members=(result.legacy_report.groups??[]).flatMap(group=>group.feature_ids??[]);
  if(result.preview_type!=='merge_faces'||result.base_revision!==state.project?.working_revision||idsKey(result.feature_ids)!==idsKey(ids)||members.length!==ids.length||new Set(members).size!==ids.length||idsKey(members)!==idsKey(ids))throw Error('合并检查结果不完整，请重新预览。');
  return result;
 }
 function inspect(suggest=false){run(async expected=>{
  if(!selected.length||!await flush()||!same(expected))return;
  let ids=[...selected],candidates:PreviewItem[]=[];
  const suggestions=await preview('merge_suggest',ids);if(!suggestions||!same(expected))return;
  candidates=suggestions.legacy_report.candidates??[];
  if(suggest)ids=[...new Set([...ids,...candidates.map(item=>item.feature_id).filter((id):id is string=>!!id)])];
  const report=await checkedPreview(ids,expected);if(!report)return;
  if(report.base_revision!==suggestions.base_revision||(report.input_sha256&&suggestions.input_sha256&&report.input_sha256!==suggestions.input_sha256))throw Error('检查期间项目已更新，请重新预览。');
  setInspection({report,candidates});setChecked([]);setVerified([]);setReviewIds([]);
 });}
 function apply(grouped:boolean){run(async expected=>{
  if(!canApply||!inspection||!await flush()||!same(expected))return;
  const state=useWorkspace.getState();if(state.project?.working_revision!==inspection.report.base_revision||inspection.report.expires_at&&Date.parse(inspection.report.expires_at)<=Date.now())throw Error('项目或合并检查已更新，请重新预览。');
  if(!grouped&&chosen.length!==1)throw Error('已选多个相连组，请使用“分组合并”。');
  const ids=[...new Set(chosen.flatMap(row=>row.ids))],report=await checkedPreview(ids,expected);if(!report)return;
  if(report.base_revision!==inspection.report.base_revision)throw Error('项目版本已更新，请重新预览并核对。');
  const expectedEvidence=chosen.map(row=>evidence(row.group)).sort(),actualEvidence=(report.legacy_report.groups??[]).map(evidence).sort();
  if(JSON.stringify(expectedEvidence)!==JSON.stringify(actualEvidence)||(report.input_sha256&&inspection.report.input_sha256&&report.input_sha256!==inspection.report.input_sha256))throw Error('合并依据发生变化，请重新预览并核对。');
  const result=await command({operation_type:grouped?'merge_face_components':'merge_adjacent_faces',feature_ids:ids,preview_id:report.preview_id,allow_mixed_algorithm_labels:allowMixed});
  if(result&&useWorkspace.getState().session===session&&useWorkspace.getState().project?.project_id===project.project_id&&useWorkspace.getState().asset?.asset_id===asset.asset_id&&useWorkspace.getState().layer==='face'){onApplied();setInspection(null);setChecked([]);setVerified([]);setReviewIds([]);info('面合并已完成，可撤销。');}
 });}
 function locate(ids:string[]){run(async expected=>{
  if(!await flush()||!same(expected))return;
  const points:number[][]=[];const visit=(value:unknown)=>{if(!Array.isArray(value))return;if(typeof value[0]==='number'&&typeof value[1]==='number')points.push(value as number[]);else value.forEach(visit);};ids.forEach(id=>{if(features[id])visit(features[id].geometry.coordinates);});
  if(points.length)onLocate([Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))]);
 });}
 return <section className="face-merge-tools" aria-label="面合并工作区">
  <div className="face-merge-toolbar"><div className="property-operation-group"><Button disabled={disabled||!selected.length} onClick={()=>inspect(true)}>查找合并候选</Button><Button disabled={disabled||selected.length<2} onClick={()=>inspect()}>预览合并</Button></div>
   <Popover trigger="click" content={<Checkbox disabled={disabled} checked={allowMixed} onChange={event=>{onAllowMixed(event.target.checked);setChecked([]);setVerified([]);}}>允许跨标签合并</Checkbox>}><Button disabled={pending}>合并设置</Button></Popover>
  </div>
  {error&&<Alert type="error" showIcon message={error}/>}
  {inspection&&!validReport&&<Alert type="warning" message="项目或合并检查已更新，请重新预览。"/>}
  <div className="face-merge-selection"><Checkbox disabled={disabled||!validReport||!eligible.length} checked={eligible.length>0&&eligible.every(row=>checked.includes(row.key))} indeterminate={eligible.some(row=>checked.includes(row.key))&&!eligible.every(row=>checked.includes(row.key))} onChange={event=>setChecked(event.target.checked?eligible.map(row=>row.key):[])}>全选可处理组</Checkbox><span>已选 {chosen.length} 组 · 涉及 {chosen.reduce((sum,row)=>sum+row.ids.length,0)} 个面</span>
   <div className="property-operation-group">{needs.length>0&&<Button disabled={disabled||!validReport} onClick={()=>setReviewIds(needs.map(row=>evidence(row.group)))}>核对所选</Button>}<Button disabled={disabled||!canApply||chosen.length!==1} onClick={()=>apply(false)}>合并所选</Button><Button disabled={disabled||!canApply} onClick={()=>apply(true)}>分组合并</Button></div>
  </div>
  <div className="face-merge-table-wrap"><table className="face-merge-table" aria-label="合并候选组"><thead><tr><th>选择</th><th>合并组</th><th>面数</th><th>面积（px²）</th><th>检查结果</th><th>操作</th></tr></thead><tbody>{rows.map(row=><tr key={row.key} data-merge-group={row.index+1}>
   <td><Checkbox aria-label={'选择合并组 '+(row.index+1)} disabled={disabled||!validReport||!row.allowed} checked={checked.includes(row.key)} onChange={event=>setChecked(old=>event.target.checked?[...old,row.key]:old.filter(key=>key!==row.key))}/></td>
   <td>第 {row.index+1} 组</td><td>{row.ids.length}</td><td>{typeof row.group.area==='number'&&Number.isFinite(row.group.area)?Number(row.group.area.toFixed(1)):'—'}</td>
   <td><Tag color={!row.allowed?'default':row.needsReview&&!row.reviewed?'orange':'blue'}>{!row.allowed?'不可合并':row.needsReview&&!row.reviewed?'需核对':'可合并'}</Tag>{row.reasons.map(reason=><small key={reason}>{reason}</small>)}<details><summary>涉及对象</summary>{row.ids.map(id=><div key={id} title={id}>{id.slice(0,8)}</div>)}</details></td>
   <td><div className="face-merge-row-actions"><Button disabled={disabled||!validReport} onClick={()=>locate(row.ids)}>定位</Button><Button disabled={disabled||!validReport} onClick={()=>run(async expected=>{if(await flush()&&same(expected))await onAdopt(row.ids);})}>加入选区</Button></div></td>
  </tr>)}</tbody></table>{!rows.length&&<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={pending?'正在检查合并候选…':'尚无合并候选'}/>}</div>
  <Modal title={'核对 '+reviewIds.length+' 个合并组'} open={reviewIds.length>0} okText="确认核对" cancelText="取消" okButtonProps={{disabled:disabled||!validReport}} onCancel={()=>setReviewIds([])} onOk={()=>{if(validReport){setVerified(old=>[...new Set([...old,...reviewIds])]);setReviewIds([]);}}}><p>请对照原图确认所选面属于同一地质面，合并不会跨越应保留的分界线。</p></Modal>
 </section>;
}

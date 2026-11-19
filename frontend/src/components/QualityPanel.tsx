import {ReasonList} from './ReasonList';
import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Collapse,Descriptions,InputNumber,Radio,Table,Tag} from 'antd';
import {ApiError,request} from '../services/client';
import type {Asset,Command,Feature,Project,Roi,Style} from '../services/models';
import {checkQuality,checkRange,isBounds,roiBounds} from '../services/deliveryChecks';
import type {Bounds,DeliveryIssue,DeliveryRoi,QualityCheck,RangeAudit,RangePreview,ScopeMode} from '../services/deliveryChecks';
import {DeliveryPreview} from './DeliveryPreview';
import {InspectionStatus} from './InspectionStatus';
import './QualityPanel.css';
import {statusColor} from './statusTags';

type Props={project:Project;asset:Asset;roi:Roi|null;features:Feature[];busy:boolean;command:Command;onLocate:(bounds:number[])=>void;styles?:Style[]};
type Status='waiting'|'checking'|'done'|'stale'|'incomplete';
function CheckStatus({status,label,attempted,disabled,onCheck}:{status:Status;label:string;attempted:boolean;disabled:boolean;onCheck:()=>void;text?:string}){
 return <InspectionStatus ariaLabel={label} state={status==='checking'?'checking':status==='done'?'done':'waiting'} attempted={attempted} disabled={disabled} onCheck={onCheck}/>;
}
const format=(n:number)=>n.toLocaleString('zh-CN',{maximumFractionDigits:1});
export function QualityPanel({project,asset,roi,features,busy,command,onLocate,styles:givenStyles}:Props){
 const savedBounds=roiBounds(roi),savedMode:ScopeMode=roi?((roi as DeliveryRoi).scope_mode??'clip'):'full';
 const savedKey=JSON.stringify([project.project_id,asset.asset_id,roi?.roi_id,roi?.revision,savedBounds,savedMode]);
 const version=project.project_id+':'+asset.asset_id+':'+project.working_revision+':'+savedKey;
 const [mode,setMode]=useState<ScopeMode>(savedMode),[bounds,setBounds]=useState<(number|null)[]>(savedBounds??[0,0,asset.width_px,asset.height_px]);
 const [drawing,setDrawing]=useState(false),[saving,setSaving]=useState(false),[saveError,setSaveError]=useState('');
 const [quality,setQuality]=useState<QualityCheck|null>(null),[qState,setQState]=useState<Status>('waiting'),[qError,setQError]=useState(''),[qAttempted,setQAttempted]=useState(false);
 const [range,setRange]=useState<{audit:RangeAudit;preview:RangePreview}|null>(null),[rState,setRState]=useState<Status>('waiting'),[rError,setRError]=useState(''),[rAttempted,setRAttempted]=useState(false);
 const [focused,setFocused]=useState<DeliveryIssue|null>(null),[styles,setStyles]=useState<Style[]>(givenStyles??[]);
 const controllers=useRef<{quality?:AbortController;range?:AbortController}>({});
 const live=useRef(version);live.current=version;
 const busyRef=useRef(false),rangeBusy=useRef(false),saveBusy=useRef(false);
 const saveAttempt=useRef<{signature:string;key:string}|null>(null);
 useEffect(()=>{if(givenStyles){setStyles(givenStyles);return;}const c=new AbortController();void request<{items:Style[]}>(`/projects/${project.project_id}/styles`,undefined,c.signal,{quiet:true}).then(data=>{if(Array.isArray(data.items))setStyles(data.items);}).catch(()=>{});return()=>c.abort();},[project.project_id,project.working_revision,givenStyles]);
 useEffect(()=>{setBounds(savedBounds??[0,0,asset.width_px,asset.height_px]);setMode(savedMode);setDrawing(false);setSaveError('');},[savedKey]);
 useEffect(()=>{controllers.current.quality?.abort();controllers.current.range?.abort();busyRef.current=false;rangeBusy.current=false;setQuality(null);setRange(null);setFocused(null);setQState(qAttempted?'stale':'waiting');setRState(rAttempted?'stale':'waiting');setQError('');setRError('');return()=>{controllers.current.quality?.abort();controllers.current.range?.abort();};},[version]);
 const valid=mode==='full'||isBounds(bounds)&&bounds[0]>=0&&bounds[1]>=0&&bounds[2]<=asset.width_px&&bounds[3]<=asset.height_px;
 const dirty=mode!==savedMode||(mode!=='full'&&JSON.stringify(bounds)!==JSON.stringify(savedBounds));
 const locked=busy||saving;
 async function saveRange(){
  if(!valid||!dirty||locked||saveBusy.current)return;saveBusy.current=true;setSaving(true);setSaveError('');const token=live.current;
  const input={operation_type:'set_roi' as const,bounds_px:mode==='full'?null:bounds as Bounds,...(mode==='full'?{}:{scope_mode:mode as 'clip'|'keep_crossing'})};
  const signature=JSON.stringify([project.project_id,asset.asset_id,input]);
  if(saveAttempt.current?.signature!==signature)saveAttempt.current={signature,key:crypto.randomUUID()};
  try{await command(input,{idempotencyKey:saveAttempt.current.key});saveAttempt.current=null;}
  catch(e){if(e instanceof ApiError&&e.status&&e.status>=400&&e.status<500)saveAttempt.current=null;if(live.current===token)setSaveError(e instanceof Error?e.message:String(e));}
  finally{saveBusy.current=false;setSaving(false);}
 }
 async function inspectQuality(){
  if(locked||busyRef.current)return;const token=version,c=new AbortController();controllers.current.quality?.abort();controllers.current.quality=c;busyRef.current=true;setQAttempted(true);setQState('checking');setQError('');setQuality(null);setFocused(null);
  try{const result=await checkQuality(project.project_id,asset.asset_id,project.working_revision,c.signal);if(live.current===token&&!c.signal.aborted){setQuality(result);setQState(result.check_complete===false?'incomplete':'done');}}
  catch(e){if(live.current===token&&!c.signal.aborted){setQState('waiting');setQError(e instanceof Error?e.message:String(e));}}
  finally{if(controllers.current.quality===c)busyRef.current=false;}
 }
 async function inspectRange(){
  if(locked||dirty||!roi||rangeBusy.current)return;const token=version,c=new AbortController();controllers.current.range?.abort();controllers.current.range=c;rangeBusy.current=true;setRAttempted(true);setRState('checking');setRError('');setRange(null);
  try{const result=await checkRange(project.project_id,asset.asset_id,project.working_revision,roi,c.signal);if(live.current===token&&!c.signal.aborted){setRange(result);setRState('done');setFocused(null);}}
  catch(e){if(live.current===token&&!c.signal.aborted){setRState('waiting');setRError(e instanceof Error?e.message:String(e));}}
  finally{if(controllers.current.range===c)rangeBusy.current=false;}
 }
 const currentQuality=quality?.working_revision===project.working_revision?quality:null;
 const currentRange=range?.audit.working_revision===project.working_revision&&range.preview.roi_revision===roi?.revision?range:null;
 const rangeFeatures=currentRange&&!dirty&&mode!=='full'?currentRange.preview[mode]:undefined;
 const previewFeatures=focused?undefined:rangeFeatures;
 const q=currentQuality?.quality_report;
 const dataContent=<section aria-label="数据检查工具">
  <p className="delivery-help">检查整张原图的几何有效性和面覆盖情况。</p>
  <CheckStatus status={qState} attempted={qAttempted} label="数据检查状态" disabled={locked} onCheck={()=>void inspectQuality()}/>
  {qError&&<Alert type="error" showIcon message={qError}/>}
  {q&&<>
   <div className="delivery-result-summary">{currentQuality!.issue_count?<Tag color="orange">发现 {currentQuality!.issue_count_exact===false?'至少 ':''}{currentQuality!.issue_count} 项需处理或核对</Tag>:<Tag color="green">未发现已检查规则中的问题</Tag>}<span>数据版本 {currentQuality!.working_revision}</span></div>
   {currentQuality!.check_complete===false&&<Alert type="warning" showIcon message="检查未完成：相交候选较多，已达到本次计算上限。问题数为已发现数量，请先处理后重新检查。"/>}
   <Descriptions size="small" column={2} items={[{key:'faces',label:'面对象',children:q.face_count},{key:'invalid',label:'无效几何',children:q.invalid_geometry_count??currentQuality!.issues.filter(i=>i.code==='INVALID_GEOMETRY').length},{key:'overlap',label:'面重叠面积',children:format(q.overlap_area_px2)+' px²'},{key:'uncovered',label:'未覆盖面积',children:format(q.uncovered_area_px2)+' px²'}]}/>
   {q.area_statistics_complete===false&&<Alert type="warning" showIcon message="存在无效面，面积统计仅计算有效面，请修复后重新检查。"/>}
   <p className="delivery-help">未覆盖面积仅供参考，真实孔洞应保留；几何检查不能判断原图是否识别正确。</p>
   <details className="delivery-details"><summary>问题明细（{currentQuality!.issue_count_exact===false?'至少 ':''}{currentQuality!.issue_count}）</summary>
    {currentQuality!.issues_truncated&&currentQuality!.check_complete!==false&&<Alert type="info" message="问题较多，仅展示前 200 项，请处理后重新检查。"/>}
    <Table<DeliveryIssue> size="small" rowKey="issue_id" aria-label="数据检查问题" dataSource={currentQuality!.issues} pagination={{pageSize:10,hideOnSinglePage:true}} columns={[
     {title:'类型',key:'severity',width:76,render:(_,i)=><Tag color={i.severity==='error'?'red':statusColor('待核对')}>{i.severity==='error'?'数据问题':'待核对'}</Tag>},
     {title:'对象与原因',key:'reason',render:(_,i)=><><ReasonList items={[i.message]}/><small title={i.feature_ids.join('、')}>{i.feature_ids.map(id=>id.slice(0,8)).join('、')}</small></>},
     {title:'操作',key:'action',width:62,render:(_,i)=><Button size="small" disabled={!i.bounds_px} onClick={()=>setFocused(i)}>定位</Button>}
    ]}/>
    {focused?.bounds_px&&<Button size="small" onClick={()=>onLocate(focused.bounds_px!)}>到编辑器处理</Button>}
   </details>
   <details className="delivery-details"><summary>检查信息</summary><Descriptions size="small" column={1} items={[{key:'valid',label:'有效几何数',children:q.valid_geometry_count},{key:'all',label:'检查对象数',children:q.geometry_count??'—'},{key:'rule',label:'规则版本',children:currentQuality!.rule_version},{key:'extent',label:'检查范围',children:'整张原图有效区域'},{key:'covered',label:'已覆盖面积',children:format(q.covered_area_px2)+' px²'},{key:'area',label:'有效区域面积',children:format(q.target_area_px2)+' px²'}]}/></details>
  </>}
 </section>;
 const rangeContent=<section aria-label="导出范围工具">
  <Radio.Group aria-label="范围选择" value={mode==='full'?'full':'region'} disabled={locked} onChange={e=>{setMode(e.target.value==='full'?'full':'clip');setDrawing(false);}}><Radio value="full">整张原图</Radio><Radio value="region">指定区域</Radio></Radio.Group>
  {mode!=='full'&&<>
   <div className="delivery-range-actions"><Button disabled={locked} type={drawing?'primary':'default'} onClick={()=>setDrawing(v=>!v)}>{drawing?'取消画框':'在图上画框'}</Button><span className="delivery-help">矩形范围 · 单位 px</span></div>
   <details className="delivery-details"><summary>精确调整</summary><div className="delivery-bound-fields">{['左上 X','左上 Y','右下 X','右下 Y'].map((label,i)=><label key={label}><span>{label}</span><InputNumber aria-label={label} value={bounds[i]} disabled={locked} onChange={v=>setBounds(old=>old.map((x,j)=>i===j?v:x))}/></label>)}</div></details>
   <Radio.Group className="delivery-scope-options" aria-label="跨界处理" value={mode} disabled={locked} onChange={e=>setMode(e.target.value)}><Radio value="clip">沿边界裁切</Radio><Radio value="keep_crossing">保留跨界对象</Radio></Radio.Group>
   <p className="delivery-help">{mode==='clip'?'仅导出范围内的面和线；文字按定位点决定是否保留。':'与范围相交的对象整件保留，可能超出范围边界。'}</p>
  </>}
  {dirty&&<div className="delivery-draft-notice">范围有未应用的调整，应用后才会用于后续导出。</div>}
  {!valid&&<Alert type="warning" showIcon message="范围需位于原图内，且右下坐标必须大于左上坐标。"/>}
  <div className="delivery-range-actions"><Button type="primary" disabled={!dirty||!valid||locked} loading={saving} onClick={()=>void saveRange()}>{mode==='full'?'应用整图':'应用范围'}</Button>{dirty&&<Button disabled={locked} onClick={()=>{setBounds(savedBounds??[0,0,asset.width_px,asset.height_px]);setMode(savedMode);setDrawing(false);}}>撤销调整</Button>}</div>
  {saveError&&<Alert type="error" showIcon message={saveError}/>}
  {mode!=='full'&&<>
   <CheckStatus status={rState} attempted={rAttempted} label="范围检查状态" disabled={locked||dirty||!roi} onCheck={()=>void inspectRange()}/>
   {rError&&<Alert type="error" showIcon message={rError}/>}
   {currentRange&&!dirty&&<>
    <table className="quality-table" aria-label="范围统计"><thead><tr><th>图层</th><th>范围内</th><th>跨界</th><th>范围外</th></tr></thead><tbody>{(['face','line','text'] as const).map(kind=><tr key={kind}><td>{{face:'面',line:'线',text:'文字'}[kind]}</td><td>{currentRange.audit.counts[kind].inside}</td><td>{currentRange.audit.counts[kind].crossing}</td><td>{currentRange.audit.counts[kind].outside}</td></tr>)}</tbody></table>
    <span className="delivery-help">{focused?'左侧正在定位数据检查问题。':'左侧显示'+(mode==='clip'?'沿边界裁切':'保留跨界对象')+'预览。'}本次范围结果共 {rangeFeatures?.length??0} 个对象。</span>{focused&&<Button size="small" onClick={()=>setFocused(null)}>返回范围预览</Button>}
    <details className="delivery-details"><summary>预览对象（{rangeFeatures?.length??0}）</summary><Table<Feature> aria-label="范围预览对象" size="small" rowKey="feature_id" dataSource={rangeFeatures} pagination={{pageSize:10,hideOnSinglePage:true}} columns={[{title:'图层',dataIndex:'feature_type',render:v=>({face:'面',line:'线',text:'文字'}[v as 'face'|'line'|'text'])},{title:'对象',dataIndex:'feature_id',render:v=><span title={v}>{v.slice(0,8)}</span>}]}/></details>
   </>}
  </>}
 </section>;
 return <section className="quality-panel" aria-label="交付检查">
  <div className="delivery-summary"><span>数据检查：{qState==='incomplete'?'检查未完成':qState==='done'?'已检查':qState==='stale'?'需要重新检查':qState==='checking'?'正在检查':'未检查'}</span><span aria-label="已保存导出范围">已保存导出范围：{roi?'指定区域 · '+(savedMode==='clip'?'沿边界裁切':'保留跨界对象'):'整张原图'}</span></div>
  <div className="delivery-layout"><DeliveryPreview projectId={project.project_id} asset={asset} features={features} styles={styles} bounds={mode==='full'?null:isBounds(bounds)?bounds:null} drawing={drawing&&!locked} scopeMode={mode} previewFeatures={previewFeatures} highlightIds={focused?.feature_ids} focusBounds={focused?.bounds_px} onBoundsChange={b=>{setBounds(b);setDrawing(false);}}/>
   <div className="delivery-tools"><Collapse defaultActiveKey={[]} items={[{key:'quality',label:'数据检查',children:dataContent},{key:'range',label:'导出范围',children:rangeContent}]}/></div>
  </div>
 </section>;
}

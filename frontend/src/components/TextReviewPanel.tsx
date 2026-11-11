import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Checkbox,InputNumber,Modal,Popover,Table,Tabs,Tag,Tooltip} from 'antd';
import type {TableColumnsType} from 'antd';
import {request} from '../services/client';
import {useWorkspace} from '../stores/workspace';
import type {Asset,Candidate,Command,CommandInput,Page,Project,TextFeature,TextLayerAssessment as Assessment,TextLayerAssessmentReport as Report,Work} from '../services/models';
import './TextReviewPanel.css';
import {matchesTextReviewFilter,needsTextReview,useReviewPanelVisible,useTextReviewReveal} from './textReviewReveal';
import type {TextReviewFilter,TextReviewRevealRequest} from './textReviewReveal';

const labels:Record<string,string>={required:'待核对',auto_accepted_unverified:'自动通过（未人工确认）',confirmed:'已确认',manual_edited:'人工修改（待核对）',skipped:'稍后处理',pipeline_complete_unverified:'流程通过（未人工确认）'};
const reasons:Record<string,string>={script_position_uncertain:'上下标位置需核对',no_ocr_evidence:'缺少 OCR 依据',low_ocr_score:'OCR 分数偏低',stratigraphic_or_lithology_code:'地质代号需核对',sub_or_superscript:'上下标或字母数字组合',numeric_or_short:'数字注记需核对',rotated_or_vertical:'旋转或竖排文字',orientation_measurement:'方位或角度数值需核对',special_symbol:'特殊符号',ocr_engine_disagreement:'两种引擎结果不同',text_changed_from_ocr:'采用文字与原识别不同',empty_text:'内容为空',suspected_text_faces:'疑似文字碎面',suspected_text_lines:'疑似文字短线',protected_boundary_or_crossing_line:'存在需保护的跨框线或边界',no_detection_quad:'缺少检测范围，无法检查残影；请人工定位'};
type Props={project:Project;asset:Asset;busy:boolean;work:Work;command:Command;focus:(id:string,residue?:boolean)=>void;revealRequest?:TextReviewRevealRequest;onConfirmNext?:(id:string)=>void};
type Filter=TextReviewFilter;
const filters:{value:Filter;label:string}[]=[{value:'required',label:'待核对'},{value:'skipped',label:'稍后处理'},{value:'confirmed',label:'已确认'},{value:'all',label:'全部'}];
const needsReview=needsTextReview;
const score=(n:number|null|undefined)=>typeof n==='number'?(n*100).toFixed(1)+'%':'无依据';
type Inspection={ticket:string;report:Report};

function residueEvidence(item:Assessment|undefined){
 if(!item)return <span className="text-review-unchecked">未检查</span>;
 const detail=<div>{item.reasons.map(reason=><div key={reason}>{reasons[reason]??reason}</div>)}{item.protected_line_ids.length>0&&<div>保护线需保留，不能据此自动删除。</div>}</div>;
 if(item.region_source==='missing')return <Tooltip title={detail}><span>需人工定位</span></Tooltip>;
 if(item.cleanup_status!=='review_required'&&item.cleanup_status!=='no_suspects')return <span>检查结果不完整</span>;
 return <Tooltip title={item.reasons.length?detail:undefined}><div className="text-review-residue">
  {item.cleanup_status==='no_suspects'?<span>未发现疑似残影</span>:<div className="text-review-residue-counts"><span>碎面 {item.suspected_face_ids.length}</span><span>短线 {item.suspected_line_ids.length}</span></div>}
  {item.protected_line_ids.length>0&&<small>保护线 {item.protected_line_ids.length}</small>}
 </div></Tooltip>;
}

export function TextReviewPanel({project,asset,busy,work,command,focus,revealRequest,onConfirmNext}:Props){
 const session=useWorkspace(state=>state.session);
 const [filter,setFilter]=useState<Filter>('required'),[rows,setRows]=useState<TextFeature[]>([]),[candidates,setCandidates]=useState<Candidate[]>([]),[threshold,setThreshold]=useState(90),[moreOpen,setMoreOpen]=useState(false),[page,setPage]=useState(1),[inspection,setInspection]=useState<Inspection|null>(null),[onlySuspects,setOnlySuspects]=useState(false),[selected,setSelected]=useState<string[]>([]),[error,setError]=useState(''),[inspectionError,setInspectionError]=useState('');
 const prefix='/projects/'+project.project_id,scope=JSON.stringify([project.project_id,asset.asset_id,session]),ticket=JSON.stringify([scope,project.working_revision]);
 const panel=useRef<HTMLDivElement>(null),visible=useReviewPanelVisible(panel);
 const [loadedTicket,setLoadedTicket]=useState<string|null>(null),[showOriginal,setShowOriginal]=useState(false),[showScore,setShowScore]=useState(false);
 const autoInspection=useRef<string|null>(null);
 const currentScope=useRef(scope),currentTicket=useRef(ticket),currentRevision=useRef(project.working_revision),queueRequest=useRef(0),inspectionRequest=useRef(0),mounted=useRef(false);currentScope.current=scope;currentTicket.current=ticket;currentRevision.current=project.working_revision;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;queueRequest.current+=1;};},[]);
 useEffect(()=>{setFilter('required');setPage(1);setThreshold(90);setMoreOpen(false);setRows([]);setCandidates([]);setLoadedTicket(null);setOnlySuspects(false);setSelected([]);},[scope]);
 async function load(){
  if(!mounted.current||currentScope.current!==scope)return;
  const requestedTicket=currentTicket.current,requestedRevision=currentRevision.current,serial=++queueRequest.current;
  const [queue,ocr]=await Promise.all([request<Page<TextFeature>>(prefix+'/reviews?asset_id='+asset.asset_id+'&include_all=true'),request<Page<Candidate>>(prefix+'/ocr-candidates?asset_id='+asset.asset_id)]);
  if(!mounted.current||currentTicket.current!==requestedTicket||queueRequest.current!==serial)return;
  if(queue.working_revision!==undefined&&queue.working_revision!==requestedRevision){setRows([]);setCandidates([]);setLoadedTicket(null);setError('文字核对列表已过期，请刷新。');return;}
  setError('');
  setRows(queue.items);setCandidates(ocr.items);setLoadedTicket(requestedTicket);
 }
 useEffect(()=>{let active=true;setError('');void load().catch(e=>{if(active&&e.name!=='AbortError')setError(String(e));});return()=>{active=false;queueRequest.current+=1;};},[ticket]);
 useEffect(()=>{setInspection(null);setInspectionError('');inspectionRequest.current+=1;},[ticket]);
 async function runCommand(input:CommandInput){await work(async()=>{const result=await command(input);if(result&&mounted.current&&currentScope.current===scope)await load();});}
 async function inspectReport(){
  const requestedTicket=currentTicket.current,requestedRevision=currentRevision.current,serial=++inspectionRequest.current;
  setInspection(null);setInspectionError('');
  try{
   const result=await request<Report>(prefix+'/text-layer-assessments?asset_id='+asset.asset_id);
   if(!mounted.current||currentTicket.current!==requestedTicket||serial!==inspectionRequest.current)return;
   if(result.working_revision!==requestedRevision){setInspectionError('检查结果已过期，请重新检查全图残影。');return;}
   if(!result.items.length&&(rows.length||result.summary.text_count)){setInspectionError('检查结果缺少文字数据，请重新检查全图残影。');return;}
   setInspection({ticket:requestedTicket,report:result});
  }catch(e){if(mounted.current&&currentTicket.current===requestedTicket&&serial===inspectionRequest.current)setInspectionError('残影检查失败：'+String(e));}
 }
 async function inspect(){await work(inspectReport);}
 useEffect(()=>{if(visible&&autoInspection.current!==ticket){autoInspection.current=ticket;void inspectReport();}},[visible,ticket]);
 function changeFilter(next:Filter){setFilter(next);setPage(1);setSelected([]);}
 function deleteSelected(){
  const ids=[...selected],requestedScope=scope,requestedTicket=ticket;
  if(!ids.length)return;
  Modal.confirm({title:'删除 '+ids.length+' 项文字？',okText:'删除',cancelText:'取消',okButtonProps:{danger:true},content:'本次删除所选的 '+ids.length+' 项文字，记录进入历史，可通过一次撤销恢复。',onOk:()=>work(async()=>{
   if(!mounted.current||currentScope.current!==requestedScope)return;
   // The command passed by Workbench flushes its property draft before queuing deletion.
   const result=await command({operation_type:'delete_text',feature_ids:ids});
   if(!result||!mounted.current||currentScope.current!==requestedScope)return;
   const removed=new Set(result.removed_feature_ids);
   setSelected(current=>current.filter(id=>!removed.has(id)));
   setRows(current=>current.filter(row=>!removed.has(row.feature_id)));
   // load() captures the latest ticket after autosave/deletion advances the revision.
   if(currentTicket.current===requestedTicket||result.result_revision>=project.working_revision)await load();
  })});
 }
 const report=inspection?.ticket===ticket&&inspection.report.working_revision===project.working_revision?inspection.report:null;
 const assessments=new Map(report?.items.map(item=>[item.text_feature_id,item]));
 const counts:Record<Filter,number>={required:rows.filter(needsReview).length,skipped:rows.filter(f=>f.review_status==='skipped').length,confirmed:rows.filter(f=>f.review_status==='confirmed').length,all:rows.length};
 const visibleRows=rows.filter(f=>matchesTextReviewFilter(f,filter)&&(!report||!onlySuspects||assessments.get(f.feature_id)?.cleanup_status==='review_required'));
 const visiblePageKey=JSON.stringify(visibleRows.slice((page-1)*8,page*8).map(row=>row.feature_id));
 useEffect(()=>{const available=new Set<string>(JSON.parse(visiblePageKey));setSelected(current=>current.filter(id=>available.has(id)));},[visiblePageKey]);
 useEffect(()=>{setPage(current=>Math.min(current,Math.max(1,Math.ceil(visibleRows.length/8))));},[visibleRows.length]);
 const highlightedId=useTextReviewReveal({request:revealRequest,ticket,rows,loadedTicket,visible,panel,filter,setFilter,setOnlySuspects,setPage});
 const unused=candidates.filter(c=>!c.text_feature_id);
 const columns:TableColumnsType<TextFeature>=[
  {title:'文字',dataIndex:'text_value',width:240,fixed:'left',render:(value:string,f:TextFeature)=><div className="text-review-text-cell"><span className="text-review-value">{value||'（空文字）'}</span><div className="text-review-scripts">{(f.layout_runs??[]).filter(r=>r.script!=='normal'||r.review_required).map((r,i)=><Tag className={r.review_required?'text-review-script-warning':undefined} key={i} color={r.review_required?'orange':'blue'}>{r.script==='subscript'?'下标':r.script==='superscript'?'上标':'排版'} {r.text}{r.review_required?' · 待核对':''}</Tag>)}</div>{(f.review_reason_codes.some(r=>!r.startsWith('soft:'))||f.review_status==='manual_edited')&&<small className="text-review-reasons">{f.review_reason_codes.filter(r=>!r.startsWith('soft:')).map(r=>reasons[r]??r).join('；')||'修改后的文字需人工确认'}</small>}</div>},
  ...(showOriginal?[{title:'原始候选',dataIndex:'original_text',width:160,render:(value:string)=><span className="text-review-value">{value||'—'}</span>}]:[]),
  ...(showScore?[{title:'识别分数',width:100,render:(_:unknown,f:TextFeature)=>score(f.ocr_score)}]:[]),
  {title:'核对状态',width:170,render:(_,f)=>labels[f.review_status]??f.review_status},
  {title:'残影',width:180,render:(_,f)=>residueEvidence(assessments.get(f.feature_id))},
  {title:'操作',width:onConfirmNext?210:80,fixed:'right',render:(_,f)=><div className="text-review-row-actions"><Button disabled={busy} onClick={()=>focus(f.feature_id)}>查看</Button>{onConfirmNext&&f.review_status!=='confirmed'&&<Button disabled={busy} onClick={()=>onConfirmNext(f.feature_id)}>确认并下一条</Button>}</div>}
 ];
 return <div ref={panel} className="text-review-panel">
  <div className="text-review-toolbar" aria-label="文字核对工具">
   <Button disabled={busy} onClick={()=>void inspect()}>检查全图残影</Button>
   <Popover trigger="click" placement="bottomRight" content={<div className="text-review-column-options" role="group" aria-label="显示列"><Checkbox checked={showOriginal} onChange={event=>setShowOriginal(event.target.checked)}>原始候选</Checkbox><Checkbox checked={showScore} onChange={event=>setShowScore(event.target.checked)}>识别分数</Checkbox></div>}><Button>显示列</Button></Popover>
   <Button aria-expanded={moreOpen} aria-controls="text-review-more" onClick={()=>setMoreOpen(value=>!value)}>更多</Button>
   <Button disabled={busy} onClick={()=>void work(load)}>刷新</Button>
  </div>
  {error&&<Alert type="error" message={error}/>}
  <Tabs className="text-review-filters" aria-label="按核对状态筛选" type="line" size="small" activeKey={filter} onChange={key=>changeFilter(key as Filter)} items={filters.map(item=>({key:item.value,label:item.label+' '+counts[item.value]}))}/>
  {inspectionError&&<Alert type="error" message={inspectionError}/>}
  {report&&<div className="text-review-inspection-summary" aria-label="全图残影检查结果"><span>检查 {report.summary.text_count} 条 · 疑似 {report.summary.cleanup_review_required} 处</span><Checkbox checked={onlySuspects} onChange={e=>{setOnlySuspects(e.target.checked);setPage(1);setSelected([]);}}>仅看疑似残影</Checkbox></div>}
  {selected.length>0&&<div className="text-review-selection" aria-label="所选文字操作"><span>已选 {selected.length} 项</span><Button danger disabled={busy} onClick={deleteSelected}>删除所选文字</Button><Button disabled={busy} onClick={()=>setSelected([])}>清空选择</Button><small>仅选择当前页；翻页或切换筛选会清空选择。</small></div>}
  <div id="text-review-more" className="text-review-more" hidden={!moreOpen}>
   <div className="text-review-advanced-controls"><label htmlFor="text-review-threshold">自动通过分数</label><InputNumber id="text-review-threshold" aria-label="自动通过分数门槛" min={1} max={100} value={threshold} addonAfter="%" onChange={n=>setThreshold(Number(n??90))}/><Button disabled={busy} onClick={()=>void runCommand({operation_type:'classify_review',threshold:threshold/100})}>重新评估文字</Button><Button disabled={busy} onClick={()=>void runCommand({operation_type:'restore_ocr_layout'})}>恢复识别排版</Button></div>
   <p className="review-note">模型分数不是正确率；自动通过的文字仍未人工确认。</p>
   <details className="ocr-candidate-details"><summary>未采用的识别结果（{unused.length}）</summary><Table rowKey="candidate_id" size="small" dataSource={unused} pagination={{pageSize:8}} scroll={{x:650}} columns={[{title:'原文',dataIndex:'raw_text'},{title:'识别分数',render:(_,c:Candidate)=>score(c.score)},{title:'引擎 / 模型',render:(_:unknown,c:Candidate)=>(c.engine_id||'—')+' / '+(c.model_id||'—')},{title:'建议',render:(_:unknown,c:Candidate)=>c.rule_suggestions.map(r=>typeof r==='object'&&r!==null&&'reason_codes' in r&&Array.isArray(r.reason_codes)?r.reason_codes.join('；'):'').filter(Boolean).join('；')||'需对照原图'},{title:'操作',render:(_,c:Candidate)=><Button disabled={busy} onClick={()=>void runCommand({operation_type:'adopt_ocr_candidate',candidate_id:c.candidate_id})}>保存为文字</Button>}]}/></details>
  </div>
  <Table className="text-review-table" rowKey="feature_id" size="small" tableLayout="fixed" dataSource={visibleRows} rowClassName={row=>row.feature_id===highlightedId?'text-review-revealed':''} onRow={row=>({'aria-selected':row.feature_id===highlightedId})} rowSelection={{selectedRowKeys:selected,onChange:keys=>setSelected(keys.map(String)),columnWidth:40,fixed:true,getCheckboxProps:()=>({disabled:busy})}} pagination={{pageSize:8,current:page,onChange:next=>{setPage(next);setSelected([]);},showSizeChanger:false}} scroll={{x:(onConfirmNext?840:710)+(showOriginal?160:0)+(showScore?100:0)}} columns={columns}/>
 </div>;
}

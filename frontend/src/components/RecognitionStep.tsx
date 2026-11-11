import {useEffect,useRef,useState} from 'react';
import {LoadingImage} from './LoadingImage';
import {Alert,Button,Card,Collapse,Select,Space,Tabs,Tag} from 'antd';
import {request} from '../services/client';
import type {Asset,Candidate,JobEvent,Page,Project,Run,Work} from '../services/models';
import {formatRecognitionDuration,recognitionStageNames,recognitionTiming} from './recognitionTiming';
import './recognitionTiming.css';

type PluginStatus={available:boolean;reason_code?:string|null;missing_dependencies?:string[];missing_or_invalid?:string[]};
type Capabilities={recognition:PluginStatus;ocr:{rapid:PluginStatus;paddle:PluginStatus}};
type Props={project:Project;asset:Asset;hasEditingContent:boolean;task:Run|null;events:JobEvent[];busy:boolean;work:Work;elapsed:string;refresh:()=>Promise<void>;start:(pipeline:string)=>Promise<void>;cancel:()=>Promise<void>;retry:()=>Promise<void>;adopt:(mode:string)=>Promise<void>};
const statuses:Record<string,string>={queued:'等待识别',starting:'准备中',running:'正在识别',cancelling:'正在取消',completed:'识别完成',completed_with_warnings:'识别完成，部分内容需检查',failed:'识别失败',cancelled:'已取消',interrupted:'识别已中断'};
const stageNames=recognitionStageNames;
const activeStatuses=['queued','starting','running','cancelling'];
const resultChoices=[
 {value:'keep_current',label:'保存到本项目',help:'将识别结果保存为可编辑的面和线。本项目已有编辑内容时，请选择下面另外一种方式。'},
 {value:'replace',label:'替换本项目的编辑内容',help:'用这次识别结果替换已有编辑内容。替换前会自动备份，之后可以恢复。'},
 {value:'new_project',label:'另建项目保存',help:'把原图和这次识别结果保存为一个新项目，保留原项目中的编辑内容。'}
];

export function RecognitionStep({project,asset,hasEditingContent,task,events,busy,work,refresh,start,cancel,retry,adopt}:Props){
 const startPending=useRef(false);
 function startOnce(){if(startPending.current||busy||active)return;startPending.current=true;void work(()=>start(pipeline)).finally(()=>{startPending.current=false;});}
 const [content,setContent]=useState('vector'),[engine,setEngine]=useState('rapid'),[adoption,setAdoption]=useState('keep_current');
 const [capabilities,setCapabilities]=useState<Capabilities|null>(null),[checking,setChecking]=useState(false),[checkError,setCheckError]=useState('');
 const [candidates,setCandidates]=useState<Candidate[]>([]),[previewError,setPreviewError]=useState(false),[candidateError,setCandidateError]=useState(''),[previewLayer,setPreviewLayer]=useState<'all'|'face'|'line'|'text'>('all');
 const active=!!task&&activeStatuses.includes(task.run_status);
 const completed=!!task&&['completed','completed_with_warnings'].includes(task.run_status);
 const vector=!!task&&task.pipeline_id.startsWith('legacy_b2c');
 const adopted=!!task?.adopted_operation_id;
 const hasConflict=(c:Candidate)=>c.rule_suggestions.some(rule=>typeof rule==='object'&&rule!==null&&'reason_codes' in rule&&Array.isArray(rule.reason_codes)&&rule.reason_codes.includes('OCR_ENGINE_DISAGREEMENT'));
 const pipeline=content==='vector'?'legacy_b2c':content==='text'?'ocr_'+engine:'legacy_b2c_'+engine;
 const prefix='/projects/'+project.project_id;
 const [clock,setClock]=useState(Date.now),[restoredEvents,setRestoredEvents]=useState<JobEvent[]>([]);
 useEffect(()=>{setClock(Date.now());if(!active)return;const timer=window.setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);},[task?.run_id,active]);
 // Completed runs are not polled by App. Restore their event history here too,
 // so a page reload has the same measured stage duration as the live session.
 useEffect(()=>{let current=true;setRestoredEvents([]);if(task)void request<Page<JobEvent>>(prefix+'/runs/'+task.run_id+'/events').then(rows=>{if(current)setRestoredEvents(rows.items);}).catch(()=>{});return()=>{current=false;};},[prefix,task?.run_id,task?.run_status]);
 const timingEvents=[...new Map([...restoredEvents,...events].filter(event=>event.run_id===task?.run_id).map(event=>[event.event_id,event])).values()];
 const timing=task?recognitionTiming(task,timingEvents,clock):null;
 useEffect(()=>{let current=true;setCandidates([]);setCandidateError('');setPreviewError(false);if(completed&&task?.pipeline_id!=='legacy_b2c')void request<Page<Candidate>>(prefix+'/ocr-candidates?asset_id='+asset.asset_id).then(rows=>{if(current)setCandidates(rows.items.filter(c=>c.run_id===task?.run_id));}).catch(error=>{if(current)setCandidateError('文字预览加载失败：'+String(error));});return()=>{current=false;};},[project.project_id,asset.asset_id,task?.run_id,task?.run_status]);
 async function checkEnvironment(){setChecking(true);setCheckError('');try{setCapabilities(await request<Capabilities>('/capabilities'));}catch(error){setCheckError('环境检查失败：'+String(error));}finally{setChecking(false);}}
 const previewUrl='/api'+prefix+(vector&&previewLayer!=='text'?'/rasters/render_compare?asset_id='+asset.asset_id+'&run_id='+task?.run_id+(previewLayer==='all'?'':'&layer='+previewLayer):'/assets/'+asset.asset_id+'/raster');
 const packageStatus=(label:string,status:PluginStatus)=><Tag key={label} color={status.available?'success':'error'}>{label}：{status.available?'可用':'不可用'}</Tag>;
 return <section className="recognition-step">
  <Card title="识别任务" className="recognition-card">
   <div className="recognition-controls">
    <label className="recognition-field"><span>识别内容</span><Select aria-label="识别内容" value={content} disabled={busy||active} onChange={setContent} options={[{value:'vector',label:'面和线'},{value:'combined',label:'面、线和文字'},{value:'text',label:'仅文字'}]}/></label>
    {content!=='vector'&&<label className="recognition-field"><span>文字引擎</span><Select aria-label="文字引擎" value={engine} disabled={busy||active} onChange={setEngine} options={[{value:'rapid',label:'RapidOCR'},{value:'paddle',label:'PaddleOCR'},{value:'combined',label:'RapidOCR + PaddleOCR 联合识别'}]}/></label>}
   </div>
   <div className="recognition-buttons">
    <Button type="primary" disabled={busy||active} onClick={startOnce}>开始识别</Button>
    <Button loading={checking} disabled={busy} onClick={()=>void checkEnvironment()}>检查识别环境</Button>
    <Button disabled={busy} onClick={()=>void work(refresh)}>刷新任务</Button>
   </div>
   {(capabilities||checkError)&&<div className="recognition-environment" aria-label="识别环境状态">
    {checkError&&<Alert type="error" showIcon message={checkError}/>}
    {capabilities&&<><Space size={[12,12]} wrap>{packageStatus('面线识别',capabilities.recognition)}{packageStatus('RapidOCR',capabilities.ocr.rapid)}{packageStatus('PaddleOCR',capabilities.ocr.paddle)}</Space>
     {Object.entries({面线识别:capabilities.recognition,RapidOCR:capabilities.ocr.rapid,PaddleOCR:capabilities.ocr.paddle}).some(([,s])=>!s.available)&&<p>部分识别环境不可用，请展开诊断详情查看缺少的依赖或模型。</p>}
     <Collapse ghost size="small" items={[{key:'diagnostics',label:'诊断详情',children:<pre>{JSON.stringify(capabilities,null,2)}</pre>}]}/>
    </>}
   </div>}
   {task&&<div className="recognition-status">
    <Space size={[16,12]} wrap><Tag color={completed?'success':task.run_status==='failed'?'error':active?'processing':'default'}>{statuses[task.run_status]??task.run_status}</Tag>{adopted&&<Tag color="blue">识别结果已保存，可进入下一步编辑</Tag>}</Space>
    <dl className="recognition-timing" aria-label="识别计时">
     <dt>正在识别：</dt><dd>{active?timing?.currentLabel:timing?.currentLabel==='—'?'—':'最近阶段 · '+timing?.currentLabel}</dd>
     <dt>该类耗时：</dt><dd data-timing="stage">{timing&&timing.stages.length>1?timing.stages.map(stage=>stage.name+' '+formatRecognitionDuration(stage.elapsedMs)).join('；'):formatRecognitionDuration(timing?.stages[0]?.elapsedMs??null)}</dd>
     <dt>整体耗时：</dt><dd data-timing="overall">{formatRecognitionDuration(timing?.overallElapsedMs??null)}</dd>
    </dl>
    {timing?.stages.some(stage=>stage.name==='面线识别')&&<p className="recognition-timing-note">面和线由同一阶段识别，共用该阶段耗时。</p>}
    {timing&&timing.stages.length>1&&<p className="recognition-timing-note">各文字引擎按实际阶段分别计时；整体耗时为任务经过时间。</p>}
    <Space size={[16,12]} wrap>
     {active&&<Button disabled={busy||task.run_status==='cancelling'} onClick={()=>void work(cancel)}>取消任务</Button>}
     {['failed','cancelled','interrupted'].includes(task.run_status)&&<Button disabled={busy} onClick={()=>void work(retry)}>重新识别</Button>}
    </Space>
    {completed&&vector&&!adopted&&<div className="recognition-save">
     <label className="recognition-field"><span>识别结果保存方式</span><Select aria-label="结果保存方式" value={adoption} disabled={busy} onChange={setAdoption} options={resultChoices.map(({value,label})=>({value,label}))}/></label>
     {hasEditingContent&&<Alert type="info" showIcon message="本项目已有保存的编辑内容。要使用本次识别结果，请明确选择替换或另建项目；也可直接进入下一步编辑已保存的版本。"/>}<p className="recognition-save-help">{resultChoices.find(choice=>choice.value===adoption)?.help}</p>
     <Button type="primary" disabled={busy||(hasEditingContent&&adoption==='keep_current')} onClick={()=>void work(()=>adopt(adoption))}>保存识别结果</Button>
    </div>}
    {task.run_status==='failed'&&<Alert type="error" showIcon message="识别失败，可查看诊断日志后重试。"/>}
    {task.run_status==='completed_with_warnings'&&<Alert type="warning" showIcon message="识别已完成，部分文字引擎未完成；已保留成功结果，请查看运行详情。"/>}
    <Collapse ghost size="small" items={[{key:'logs',label:'运行详情',children:<><Space size={[16,12]} wrap><a target="_blank" rel="noreferrer" href={'/api'+prefix+'/runs/'+task.run_id+'/logs/stdout'}>运行日志</a><a target="_blank" rel="noreferrer" href={'/api'+prefix+'/runs/'+task.run_id+'/logs/stderr'}>诊断日志</a></Space><p>原图校验值：{task.input_raster_sha256}</p>{task.error_detail&&<pre>{JSON.stringify(task.error_detail,null,2)}</pre>}{timingEvents.map(e=><p key={e.event_id}>{stageNames[e.stage_name??'']??'任务'} · {e.event_type}</p>)}</>}]}/>
   </div>}
  </Card>
  {completed&&<Card title="识别结果预览" className="recognition-preview-card" extra={<span>只读预览</span>}>
   {vector&&<Tabs className="recognition-preview-tabs" aria-label="识别结果图层" activeKey={previewLayer} onChange={layer=>{setPreviewError(false);setPreviewLayer(layer as typeof previewLayer);}} items={[{key:'all',label:'全部'},{key:'face',label:'面'},{key:'line',label:'线'},{key:'text',label:'文字'}]}/>}
   {previewLayer==='text'&&!candidates.length&&<Alert type="info" message={task?.pipeline_id==='legacy_b2c'?'本次任务只识别了面和线，没有运行文字识别。':'本次任务未检出文字候选。'}/>}
   {candidateError&&<Alert type="warning" message={candidateError}/>}
   {previewError?<Alert type="warning" message="结果预览加载失败，请刷新任务重试。"/>:<div className="recognition-preview">
    <div className="recognition-preview-image"><LoadingImage key={previewUrl} src={previewUrl} alt="识别结果预览" onError={()=>setPreviewError(true)}/>
     {candidates.length>0&&(previewLayer==='all'||previewLayer==='text')&&<svg viewBox={'0 0 '+asset.width_px+' '+asset.height_px} aria-label="文字识别框">{candidates.filter(c=>c.detected_quad_px).map(c=><polygon key={c.candidate_id} points={c.detected_quad_px!.map(p=>p.join(',')).join(' ')} fill="rgba(22,119,255,.12)" stroke="#1677ff" strokeWidth="2"><title>{c.raw_text}</title></polygon>)}</svg>}
    </div>
   </div>}
   {(previewLayer==='text'||previewLayer==='all')&&task?.pipeline_id!=='legacy_b2c'&&<Collapse ghost items={[{key:'text',label:'文字候选（'+candidates.length+'）',children:candidates.length?<div className="recognition-candidates">{candidates.map(c=><span key={c.candidate_id}>{c.raw_text} {hasConflict(c)&&<Tag color="warning">待核对</Tag>}</span>)}</div>:<span>未检测到文字候选。</span>}]}/>}
  </Card>}
 </section>;
}

import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Checkbox,Collapse,InputNumber,Table,Tag} from 'antd';
import {ApiError,request} from '../services/client';
import {feedback} from '../services/feedback';
import {useWorkspace} from '../stores/workspace';
import type {Asset,Command,Feature,Geometry,Point,Project,Work} from '../services/models';
import {geometryPath} from './FeatureGlyph';
import './FaceSplitTools.css';

type Piece={piece_id:string;geometry:Geometry;area_px2:number;small_piece:boolean};
type Target={feature_id:string;original_area_px2:number;pieces:Piece[]};
export type FaceSplitDisplay={preview_id:string;base_revision:number;expires_at:string;input_sha256:string;targets:Target[];feature_ids:string[];cutter_geometry:Geometry;target_cutters?:Geometry[];warnings:{code:string;feature_id?:string;piece_id?:string}[]};
type Props={project:Project;asset:Asset;selected:Feature[];features:Feature[];busy:boolean;active:boolean;work:Work;command:Command;flush:()=>Promise<boolean>;path:Point[];onDraw:()=>void;onFinishDraw?:()=>Point[];onCancelDraw?:()=>void;onPreview:(display:FaceSplitDisplay|null)=>void;onLocate:(geometry:Geometry,label:string)=>void;onApplied:()=>void};
const palette=['#1677ff','#52c41a','#fa8c16','#722ed1','#13c2c2','#eb2f96'];
const splitErrors:Record<string,string>={SPLIT_PATH_INVALID:'切分路径无效，请避免自交，并绘制至少两个不同的节点。',SPLIT_PATH_OUTSIDE_ASSET:'切分路径超出原图范围，请重新绘制。',SPLIT_NO_PARTITION:'路径未切开所选面，请让路径穿过面的边界。',SPLIT_TOO_MANY_PARTS:'切分产生的子面过多，请缩小范围后重试。',SPLIT_SMALL_PIECE_REVIEW_REQUIRED:'请确认保留所有小片后再执行分割。'};
const describeError=(error:unknown)=>error instanceof ApiError?(error.code==='SPLIT_NO_PARTITION'&&typeof error.detail.reason==='string'?error.detail.reason:splitErrors[error.code]??error.message):String(error);
export function FaceSplitOverlay({display}:{display:FaceSplitDisplay}){return <g className="face-split-overlay" pointerEvents="none">{display.targets.flatMap(target=>target.pieces).map((piece,index)=><path key={piece.piece_id} data-split-piece={piece.piece_id} d={geometryPath(piece.geometry)} fill={palette[index%palette.length]} fillOpacity={.28} fillRule="evenodd" stroke={palette[index%palette.length]} strokeWidth={1.5} vectorEffect="non-scaling-stroke"/>)}{(display.target_cutters?.length?display.target_cutters:[display.cutter_geometry]).map((geometry,index)=><path key={index} data-split-cutter="true" d={geometryPath(geometry)} fill="none" stroke="#cf1322" strokeWidth={2.5} strokeDasharray="6 3" vectorEffect="non-scaling-stroke"/>)}</g>;}

function faceBounds(geometry:Geometry):[number,number,number,number]{
 const points:number[][]=[];const visit=(value:unknown)=>{if(!Array.isArray(value))return;if(value.length>=2&&typeof value[0]==='number'&&typeof value[1]==='number')points.push(value as number[]);else value.forEach(visit);};visit((geometry as {coordinates?:unknown}).coordinates);
 if(!points.length)return [0,0,0,0];
 return [Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))];
}
function boundsIntersect(a:[number,number,number,number],b:[number,number,number,number]){return a[0]<=b[2]&&b[0]<=a[2]&&a[1]<=b[3]&&b[1]<=a[3];}

export function FaceSplitTools({project,asset,selected,features,busy,active,work,command,flush,path,onDraw,onFinishDraw,onCancelDraw,onPreview,onLocate,onApplied}:Props){
 const session=useWorkspace(state=>state.session);
 const [mode,setMode]=useState<'draw'|'line'>('draw'),[lineId,setLineId]=useState<string>(),[snap,setSnap]=useState<number|null>(.5),[minArea,setMinArea]=useState<number|null>(1),[report,setReport]=useState<FaceSplitDisplay|null>(null),[error,setError]=useState(''),[pending,setPending]=useState(false),[confirmed,setConfirmed]=useState<string[]>([]);
 const baseScope=JSON.stringify([project.project_id,asset.asset_id,session,selected.map(item=>item.feature_id).sort()]),inputScope=JSON.stringify([baseScope,mode,lineId,snap,minArea,path]),scope=JSON.stringify([inputScope,project.working_revision]);
 const requestContext=JSON.stringify([baseScope,snap,minArea,active]);
 const currentPath=useRef(JSON.stringify(path));currentPath.current=JSON.stringify(path);
 const current=useRef(scope),currentInput=useRef(requestContext),mounted=useRef(false),inFlight=useRef(false),serial=useRef(0);current.current=scope;currentInput.current=requestContext;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;serial.current++;onPreview(null);};},[]);
 useEffect(()=>{setReport(null);setError('');setConfirmed([]);onPreview(null);},[scope]);
 useEffect(()=>{serial.current++;},[requestContext]);
 useEffect(()=>{setLineId(undefined);},[baseScope]);
 useEffect(()=>{if(!report)return;const expires=Date.parse(report.expires_at),remaining=expires-Date.now();const timer=window.setTimeout(()=>{setReport(null);setConfirmed([]);onPreview(null);setError('预览已过期，请重新检查。');},Number.isFinite(remaining)?Math.max(0,Math.min(remaining,2147483647)):0);return()=>window.clearTimeout(timer);},[report]);
 const selectedBounds=selected.length?selected.map(item=>faceBounds(item.geometry)).reduce((acc,b)=>[Math.min(acc[0],b[0]),Math.min(acc[1],b[1]),Math.max(acc[2],b[2]),Math.max(acc[3],b[3])] as [number,number,number,number]):[0,0,0,0] as [number,number,number,number];
 const candidateLines=selected.length?features.filter(item=>item.feature_type==='line'&&item.lifecycle_status==='active'&&boundsIntersect(faceBounds(item.geometry),selectedBounds)):[];
 const invalidTargets=!selected.length||selected.some(item=>item.feature_type!=='face'||item.lifecycle_status!=='active');
 const validPath=path.length>=2&&path.every(point=>point.length===2&&point.every(Number.isFinite));
 const validParameters=snap!==null&&Number.isFinite(snap)&&snap>=0&&snap<=2&&minArea!==null&&Number.isFinite(minArea)&&minArea>=0&&minArea<=10000;
 const valid=!!report&&report.base_revision===project.working_revision&&Date.parse(report.expires_at)>Date.now();
 const small=report?.targets.flatMap(target=>target.pieces).filter(piece=>piece.small_piece)??[];
 function beginDraw(){serial.current++;setReport(null);setConfirmed([]);setError('');onPreview(null);setMode('draw');onDraw();}
 function sameInput(expected:string){const state=useWorkspace.getState();return mounted.current&&currentInput.current===expected&&state.session===session&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id&&state.layer==='face'&&JSON.stringify([...state.selected].sort())===JSON.stringify(selected.map(item=>item.feature_id).sort())&&active;}
 function same(expected:string){return current.current===expected&&sameInput(requestContext)&&useWorkspace.getState().project?.working_revision===project.working_revision;}
 async function inspect(targetMode:'draw'|'line',targetLineId?:string,drawnPath:Point[]=path,complete=false){
  if(busy||inFlight.current||!active||invalidTargets||!validParameters||targetMode==='draw'&&drawnPath.length<2||targetMode==='line'&&!targetLineId)return;
  const expected=requestContext,pathSnapshot=drawnPath,ticket=++serial.current;inFlight.current=true;setPending(true);setError('');setReport(null);onPreview(null);setMode(targetMode);setLineId(targetMode==='line'?targetLineId:undefined);if(targetMode==='line')onCancelDraw?.();
  const stillRequested=()=>sameInput(expected)&&ticket===serial.current&&(targetMode==='line'||currentPath.current===JSON.stringify(pathSnapshot));
  try{await work(async()=>{try{
   if(!await flush()){if(stillRequested())setError('属性草稿未能保存，请先修正或重试保存。');return;}
   if(!stillRequested())return;
   const revision=useWorkspace.getState().project!.working_revision;
   const result=await request<FaceSplitDisplay>('/projects/'+project.project_id+'/face-split-previews',{asset_id:asset.asset_id,base_revision:revision,feature_ids:selected.map(item=>item.feature_id),snap_tolerance_px:snap,min_piece_area_px2:minArea,...(targetMode==='draw'?{cutter_points_px:pathSnapshot}:{line_feature_id:targetLineId})});
   if(!stillRequested())return;
   const ids=selected.map(item=>item.feature_id),returned=result.feature_ids;
   if(result.base_revision!==revision||revision!==useWorkspace.getState().project?.working_revision||!Number.isFinite(Date.parse(result.expires_at))||Date.parse(result.expires_at)<=Date.now()||!Array.isArray(returned)||returned.length!==ids.length||new Set(returned).size!==ids.length||returned.some(id=>!ids.includes(id))||!Array.isArray(result.targets)||!result.targets.length||new Set(result.targets.map(item=>item.feature_id)).size!==result.targets.length||result.targets.some(target=>!ids.includes(target.feature_id)||!Array.isArray(target.pieces)||target.pieces.length<2))throw Error('面分割预览已失效或不完整，请重新检查。');
   setReport(result);setConfirmed([]);onPreview(result);
   if(complete){
    if(result.targets.some(target=>target.pieces.some(piece=>piece.small_piece))){if(sameInput(expected))showSmallPieceNotice();return;}
    if(!stillRequested()||result.base_revision!==useWorkspace.getState().project?.working_revision)return;
    const applied=await command({operation_type:'split_selected_faces',feature_ids:result.feature_ids,preview_id:result.preview_id,confirmed_small_piece_ids:[]});
    finishApplied(applied);
   }
  }catch(e){if(stillRequested())setError(describeError(e));throw e;}});}finally{inFlight.current=false;if(mounted.current)setPending(false);}
 }
 async function apply(){
  if(busy||inFlight.current||!valid||!report||small.some(piece=>!confirmed.includes(piece.piece_id)))return;
  const expected=scope;inFlight.current=true;setPending(true);setError('');
  try{await work(async()=>{try{
   if(!await flush()){if(sameInput(requestContext))setError('属性草稿未能保存，请先修正或重试保存。');return;}
   if(!same(expected)||Date.parse(report.expires_at)<=Date.now()){if(sameInput(requestContext))setError('属性或预览已更新，请重新检查。');return;}
   const result=await command({operation_type:'split_selected_faces',feature_ids:report.feature_ids,preview_id:report.preview_id,confirmed_small_piece_ids:confirmed});
   finishApplied(result);
  }catch(e){if(same(expected))setError(describeError(e));throw e;}});}finally{inFlight.current=false;if(mounted.current)setPending(false);}
 }
 function showSmallPieceNotice(){feedback.info('分割结果含小片，请确认保留后完成分割。');}
 function finishApplied(result:unknown){const state=useWorkspace.getState();if(result&&mounted.current&&state.session===session&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id){setReport(null);onPreview(null);onApplied();}}
 async function completeDraw(){
  if(report&&mode==='draw'&&valid){await apply();return;}
  const points=onFinishDraw?.()??path;
  if(points.length<2)return;
  await inspect('draw',undefined,points,true);
 }
 const disabled=busy||pending||!active;
 const rows=report?.targets.flatMap(target=>target.pieces.map(piece=>({...piece,parent:target.feature_id})))??[];
 const resultTable=report&&<><div className="face-split-summary">涉及 {report.targets.length} 个面 · 生成 {rows.length} 个子面 · 总面积 {Number(rows.reduce((sum,piece)=>sum+piece.area_px2,0).toFixed(2))} px²</div>{report.warnings.some(item=>item.code==='TARGET_NOT_SPLIT')&&<Alert type="info" message="部分所选面未被路径切开，执行时将保持原样。"/>}
  <Table className="face-split-table" aria-label="分割子面预览" rowKey="piece_id" size="small" dataSource={rows} pagination={{pageSize:10,showSizeChanger:false}} scroll={{x:600}} columns={[{title:'原面',render:(_,row)=><span title={row.parent}>{row.parent.slice(0,8)}</span>},{title:'子面',render:(_,row)=><span title={row.piece_id}>{row.piece_id.slice(0,8)}</span>},{title:'面积（px²）',render:(_,row)=>Number(row.area_px2.toFixed(2))},{title:'检查结果',render:(_,row)=>row.small_piece?<Tag color="orange">小片需确认</Tag>:<Tag color="blue">有效子面</Tag>},{title:'操作',render:(_,row)=><div className="face-split-row-actions"><Button disabled={disabled||!valid} onClick={()=>onLocate(row.geometry,'分割子面 '+row.piece_id.slice(0,8))}>定位</Button>{row.small_piece&&<Checkbox disabled={disabled||!valid} checked={confirmed.includes(row.piece_id)} onChange={event=>setConfirmed(old=>event.target.checked?[...old,row.piece_id]:old.filter(id=>id!==row.piece_id))}>保留此小片</Checkbox>}</div>} ]}/>
  {mode==='line'&&<Button disabled={disabled||!valid||small.some(piece=>!confirmed.includes(piece.piece_id))} onClick={()=>void apply()}>执行分割</Button>}
 </>;
 return <section className="face-split-tools" aria-label="面分割工作区">
  <div className="face-split-settings face-split-settings-top"><InputNumber addonBefore="端点吸附（px）" aria-label="分割端点吸附" value={snap} min={0} max={2} step={.1} onChange={setSnap}/><InputNumber addonBefore="小片面积提醒（px²）" aria-label="分割小片面积提醒" value={minArea} min={0} max={10000} onChange={setMinArea}/></div>
  {error&&<Alert type="error" showIcon message={error}/>}
  <Collapse ghost className="line-edit-groups" defaultActiveKey={['draw']} items={[
   {key:'draw',label:'手绘路径切割',children:<div className="face-split-path">
    <div className="property-operation-group"><Button disabled={disabled||invalidTargets} onClick={beginDraw}>绘制切分路径</Button>
     <Button disabled={disabled||invalidTargets||!validParameters||!validPath||mode==='draw'&&valid&&small.some(piece=>!confirmed.includes(piece.piece_id))} onClick={()=>void completeDraw()}>完成分割</Button></div>
    {mode==='draw'&&resultTable}
   </div>},
   {key:'line',label:'沿已有线切割',children:<div className="face-split-line">
    {!candidateLines.length&&<p className="review-note">未在所选面范围内发现候选线，可切换图层核对或先框选相关线。</p>}
    {candidateLines.length>0&&<Table className="face-split-line-table" aria-label="候选切割线" rowKey="feature_id" size="small" dataSource={candidateLines} pagination={{pageSize:10,showSizeChanger:false}} columns={[
     {title:'线对象',render:(_,row)=><span title={row.feature_id}>线 {row.feature_id.slice(0,8)}</span>},
     {title:'宽度（px）',render:(_,row)=>row.feature_type==='line'?Number(row.stroke_width_px.toFixed(2)):'—'},
     {title:'操作',render:(_,row)=><div className="face-split-row-actions"><Button disabled={disabled} onClick={()=>onLocate(row.geometry,'候选切割线 '+row.feature_id.slice(0,8))}>定位</Button><Button disabled={disabled||!validParameters} onClick={()=>void inspect('line',row.feature_id)}>切割</Button></div>},
    ]}/>}
    {mode==='line'&&resultTable}
   </div>},
  ]}/>
 </section>;
}

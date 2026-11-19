import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Collapse,Input,Radio,Table,Tag} from 'antd';
import {InspectionStatus} from './InspectionStatus';
import {useWorkspace} from '../stores/workspace';
import {searchFaceColors} from '../services/faceColors';
import type {FaceColorMode,FaceColorReport,FaceColorInput,FaceColorMatch} from '../services/faceColors';
import type {Asset,Feature,Project} from '../services/models';
import {geometryPath} from './FeatureGlyph';
import './FaceColorSearch.css';

export type FaceColorDisplay={base_revision:number;selection_key:string;feature_ids:string[]};
type Props={project:Project;asset:Asset;selected:Feature[];active:boolean;busy:boolean;guard:()=>boolean;onDisplay:(display:FaceColorDisplay|null)=>void;onSelect:(ids:string[])=>void;onLocate:(feature:Feature)=>void};
type Result={inputKey:string;generation:number;report:FaceColorReport};

export function FaceColorSearch({project,asset,selected,active,busy,guard,onDisplay,onSelect,onLocate}:Props){
 const session=useWorkspace(state=>state.session),features=useWorkspace(state=>state.featuresById);
 const [mode,setMode]=useState<FaceColorMode>('similar'),[toleranceInput,setToleranceInput]=useState('15'),[expanded,setExpanded]=useState(false),[result,setResult]=useState<Result|null>(null),[checking,setChecking]=useState(false),[attempted,setAttempted]=useState(false),[error,setError]=useState('');
 const selectionKey=JSON.stringify(selected.map(item=>item.feature_id).sort()),anchor=useRef<string>(),adoptedSelection=useRef<string>();
 const single=selected.length===1&&selected[0].feature_type==='face'&&selected[0].lifecycle_status==='active'?selected[0]:undefined;
 if(single)anchor.current=single.feature_id;
 const sourceId=single?.feature_id??(adoptedSelection.current===selectionKey?anchor.current:undefined),source=sourceId?features[sourceId]:undefined;
 const sourceColor=source?.feature_type==='face'&&source.lifecycle_status==='active'?source.fill_color.toLowerCase():'';
 const tolerance=mode==='exact'?0:Number(toleranceInput),validTolerance=mode==='exact'||/^\+?(?:\d+|\d*\.\d+)$/.test(toleranceInput.trim())&&Number.isFinite(tolerance)&&tolerance>=0&&tolerance<=100;
 const inputKey=JSON.stringify([project.project_id,asset.asset_id,session,project.working_revision,sourceId,sourceColor,mode,toleranceInput,active]);
 const context=JSON.stringify([inputKey,selectionKey,expanded]),current=useRef(context),mounted=useRef(false),serial=useRef(0),flight=useRef(false),controller=useRef<AbortController|null>(null),publish=useRef(onDisplay),latestGuard=useRef(guard);current.current=context;publish.current=onDisplay;latestGuard.current=guard;
 const valid=!!result&&result.inputKey===inputKey&&active&&!!sourceColor;
 function cancel(){serial.current++;controller.current?.abort();controller.current=null;flight.current=false;if(mounted.current)setChecking(false);}
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;serial.current++;controller.current?.abort();publish.current(null);};},[]);
 useEffect(()=>{cancel();},[context]);
 useEffect(()=>{setResult(null);setError('');publish.current(null);},[inputKey]);
 useEffect(()=>{setAttempted(false);},[project.project_id,asset.asset_id,session,sourceId]);
 useEffect(()=>{publish.current(valid&&expanded&&result?{base_revision:result.report.base_revision,selection_key:selectionKey,feature_ids:result.report.matches.map(item=>item.feature_id)}:null);},[result,valid,expanded,selectionKey]);
 function same(expected:string){const state=useWorkspace.getState();return mounted.current&&current.current===expected&&active&&expanded&&state.session===session&&state.project?.project_id===project.project_id&&state.asset?.asset_id===asset.asset_id&&state.layer==='face'&&state.project?.working_revision===project.working_revision&&JSON.stringify([...state.selected].sort())===selectionKey;}
 async function read(expected:string,ticket:number,input:FaceColorInput){
  const abort=new AbortController();controller.current=abort;const report=await searchFaceColors(project.project_id,input,abort.signal);
  if(ticket!==serial.current||!same(expected))return;
  const state=useWorkspace.getState();
  if(report.asset_id!==input.asset_id||report.source_feature_id!==input.source_feature_id||report.base_revision!==input.base_revision||report.source_color!==sourceColor||report.mode!==input.mode||report.tolerance!==input.tolerance||report.matches.some(item=>state.featuresById[item.feature_id]?.feature_type!=='face'||state.featuresById[item.feature_id]?.lifecycle_status!=='active'))throw Error('颜色查找结果已变化，请重新检查。');
  return report;
 }
 function start(){if(busy||flight.current||!active||!expanded||!sourceId||!sourceColor||!validTolerance)return;const expected=context,ticket=++serial.current;flight.current=true;setChecking(true);setAttempted(true);setError('');return {expected,ticket,input:{asset_id:asset.asset_id,base_revision:project.working_revision,source_feature_id:sourceId,mode,tolerance}};}
 function finish(ticket:number){if(serial.current===ticket){flight.current=false;controller.current=null;if(mounted.current)setChecking(false);}}
 async function inspect(){
  const job=start();if(!job)return;setResult(null);publish.current(null);
  try{if(!guard()){setError('属性尚未保存或无效，请先完成属性保存后再查找。');return;}const report=await read(job.expected,job.ticket,job.input);if(report)setResult({inputKey,generation:job.ticket,report});}
  catch(exc){if(job.ticket===serial.current&&same(job.expected)&&!(exc instanceof DOMException&&exc.name==='AbortError'))setError(exc instanceof Error?exc.message:String(exc));}finally{finish(job.ticket);}
 }
 async function selectMatches(){
  if(!valid||!result)return;const snapshot=result,job=start();if(!job)return;
  try{if(!latestGuard.current()){setError('属性尚未保存或无效，请先完成属性保存后再选择。');return;}const fresh=await read(job.expected,job.ticket,job.input);if(!fresh)return;if(!latestGuard.current()){setError('属性尚未保存或无效，请先完成属性保存后再选择。');return;}const ids=fresh.matches.map(item=>item.feature_id);if(JSON.stringify(ids)!==JSON.stringify(snapshot.report.matches.map(item=>item.feature_id)))throw Error('匹配对象已变化，请重新检查。');anchor.current=fresh.source_feature_id;adoptedSelection.current=JSON.stringify([...ids].sort());onSelect(ids);}
  catch(exc){if(job.ticket===serial.current&&same(job.expected)){setResult(null);publish.current(null);setError(exc instanceof Error?exc.message:String(exc));}}finally{finish(job.ticket);}
 }
 function locate(item:FaceColorMatch){if(!valid||checking||busy||!result?.report.matches.some(row=>row.feature_id===item.feature_id))return;if(!guard()){setError('属性尚未保存或无效，请先完成属性保存后再定位。');return;}const feature=features[item.feature_id];if(feature?.feature_type==='face')onLocate(feature);}
 const columns=[{title:'面对象',render:(_:unknown,item:FaceColorMatch)=><span title={item.feature_id}>面 {item.feature_id.slice(0,8)}</span>},{title:'颜色',render:(_:unknown,item:FaceColorMatch)=><span className="face-color-value"><i style={{background:item.fill_color}}/>{item.fill_color}</span>},{title:'匹配类型',render:(_:unknown,item:FaceColorMatch)=><Tag color={item.match_type==='exact'?'green':'blue'}>{item.match_type==='exact'?'精确同色':'相似颜色'}</Tag>},{title:'色差 ΔE',render:(_:unknown,item:FaceColorMatch)=><span title="色差越小，颜色越接近；0 表示精确同色">{Number(item.delta_e.toFixed(2))}</span>},{title:'操作',render:(_:unknown,item:FaceColorMatch)=><Button size="small" disabled={busy||checking} onClick={()=>locate(item)}>定位</Button>}];
 return <Collapse ghost className="line-edit-groups face-color-search-group" activeKey={expanded?['search']:[]} onChange={keys=>setExpanded(keys.length>0)} items={[{key:'search',label:'颜色查找',children:<section className="face-color-search" aria-label="面颜色查找">
  {sourceColor?<Input className="property-color face-color-reference" addonBefore="参照色" aria-label="参照色" value={sourceColor} readOnly addonAfter={<span className="face-color-reference-swatch" aria-hidden="true"><i style={{background:sourceColor}}/></span>}/>:<span className="review-note">请选择单个面作为颜色参照。</span>}
  <Radio.Group aria-label="颜色匹配方式" value={mode} disabled={busy} onChange={event=>setMode(event.target.value)}><Radio value="exact">精确同色</Radio><Radio value="similar">相似颜色</Radio></Radio.Group>
  {mode==='similar'&&<div className="face-color-tolerance"><Input addonBefore="色差容差（ΔE）" aria-label="色差容差" role="spinbutton" aria-valuemin={0} aria-valuemax={100} aria-valuenow={validTolerance?tolerance:undefined} aria-invalid={!validTolerance} status={validTolerance?undefined:'error'} inputMode="decimal" disabled={busy} value={toleranceInput} onChange={event=>setToleranceInput(event.target.value)}/></div>}
  <InspectionStatus ariaLabel="颜色查找状态" state={checking?'checking':valid?'done':'waiting'} attempted={attempted} disabled={busy||!active||!sourceColor||!validTolerance} onCheck={()=>void inspect()}/>
  {error&&<Alert type="error" showIcon message={error}/>}
  {valid&&result&&<>{result.report.invalid_color_count>0&&<span className="review-note">另有 {result.report.invalid_color_count} 个面颜色无效，未参与匹配。</span>}
   <details key={result.generation} className="face-color-details"><summary title="查找范围：当前原图的全部有效面">匹配明细（{result.report.match_count} 个面，含参照面）</summary><Table className="face-color-table" aria-label="颜色匹配明细" rowKey="feature_id" size="small" columns={columns} dataSource={result.report.matches} pagination={{pageSize:25,showSizeChanger:false,hideOnSinglePage:true}} scroll={{x:570}}/></details>
   <Button disabled={busy||checking} onClick={()=>void selectMatches()}>选中匹配对象</Button></>}
 </section>}]} />;
}

export function FaceColorMatchOverlay({display,features}:{display:FaceColorDisplay;features:Record<string,Feature>}){return <g className="face-color-match-overlay" pointerEvents="none">{display.feature_ids.map(id=>{const feature=features[id];return feature?.feature_type==='face'&&feature.lifecycle_status==='active'?<path key={id} data-face-color-match={id} d={geometryPath(feature.geometry)} fill="none" stroke="#722ed1" strokeWidth={1.5} vectorEffect="non-scaling-stroke"/>:null;})}</g>;}

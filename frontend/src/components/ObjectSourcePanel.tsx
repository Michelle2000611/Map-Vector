import {useEffect,useState} from 'react';
import {request} from '../services/client';
import {useWorkspace} from '../stores/workspace';
import {useFeatureHistory} from '../hooks/useFeatureHistory';
import type {Feature,Page,Run,Candidate} from '../services/models';
import './ObjectSourcePanel.css';

type Evidence={key:string;run:Run|null;candidate:Candidate|null;candidateError:boolean;runError:boolean};
type Props={projectId:string;assetId:string;features:Feature[];active:boolean};
const kinds:Record<string,string>={face:'面对象',line:'线对象',text:'文字对象'};
const sources:Record<string,string>={algorithm:'算法识别',manual:'编辑生成',legacy_import:'旧项目导入',unknown:'未记录'};
const engines:Record<string,string>={rapid:'RapidOCR',rapidocr:'RapidOCR',paddle:'PaddleOCR',paddleocr:'PaddleOCR'};
const vectorPipelines=new Set(['legacy_b2c','legacy_b2c_rapid','legacy_b2c_paddle','legacy_b2c_combined']);
const pipelines:Record<string,string>={ocr_rapid:'RapidOCR 文字识别',ocr_paddle:'PaddleOCR 文字识别',ocr_joint:'联合文字识别',ocr_combined:'联合文字识别',legacy_b2c:'面线识别',legacy_b2c_rapid:'面线与文字识别',legacy_b2c_paddle:'面线与文字识别',legacy_b2c_combined:'面线与联合文字识别'};
function engineName(value:string){return value.split('+').map(part=>engines[part.toLowerCase()]??part).join(' + ');}
function engine(feature:Feature){return feature.feature_type==='text'&&feature.ocr_engine_id?engineName(feature.ocr_engine_id):feature.feature_type==='text'&&feature.primary_candidate_id?'待查看':'未记录';}
function time(value:string|null|undefined){if(!value)return '未记录';const date=new Date(value);return Number.isFinite(date.getTime())?date.toLocaleString('zh-CN',{hour12:false}):'未记录';}
function taskName(run:Run){return pipelines[run.pipeline_id]??(run.pipeline_id.startsWith('legacy_b2c')?'面线识别（'+run.pipeline_id+'）':run.pipeline_id);}

export function ObjectSourcePanel({projectId,assetId,features,active}:Props){
 const session=useWorkspace(state=>state.session),feature=features.length===1?features[0]:undefined;
 const {latestTime}=useFeatureHistory({projectId,assetId,featureId:feature?.feature_id,active});
 const key=JSON.stringify([projectId,assetId,session,feature?.feature_id,feature?.revision,feature?.origin_run_id,feature?.feature_type==='text'?feature.primary_candidate_id:null]);
 const [evidence,setEvidence]=useState<Evidence|null>(null);
 useEffect(()=>{
  if(!active||!feature)return;
  const controller=new AbortController();let live=true;
  const prefix='/projects/'+projectId;
  setEvidence(null);
  async function load(){
   const [run,candidates]=await Promise.allSettled([
    feature!.origin_run_id?request<Run>(prefix+'/runs/'+feature!.origin_run_id,undefined,controller.signal,{quiet:true}):Promise.resolve(null),
    feature!.feature_type==='text'&&feature!.primary_candidate_id?request<Page<Candidate>>(prefix+'/ocr-candidates?asset_id='+assetId,undefined,controller.signal,{quiet:true}):Promise.resolve(null)
   ]);
   if(!live)return;
   const origin=run.status==='fulfilled'?run.value:null;
   const runMatches=!origin||origin.run_id===feature!.origin_run_id&&origin.asset_id===assetId&&(!origin.project_id||origin.project_id===projectId);
   const candidateRows=candidates.status==='fulfilled'?candidates.value:null;
   const candidate=feature!.feature_type==='text'&&candidateRows?.items?.find(item=>item.candidate_id===feature!.primary_candidate_id&&item.project_id===projectId&&item.asset_id===assetId&&(!item.text_feature_id||item.text_feature_id===feature!.feature_id))||null;
   setEvidence({key,run:runMatches?origin:null,candidate,candidateError:candidates.status==='rejected'||!!candidateRows&&!Array.isArray(candidateRows.items),runError:run.status==='rejected'||!runMatches});
  }
  void load();return()=>{live=false;controller.abort();};
 },[active,key,projectId,assetId]);
 const loaded=evidence?.key===key?evidence:null;
 const vectorOrigin=!!loaded?.run&&vectorPipelines.has(loaded.run.pipeline_id);
 const vectorEngine=!feature?.origin_run_id?'未记录':!loaded?'读取中…':loaded.runError?'任务记录暂时无法读取':vectorOrigin?'B2c 面线提取':'未记录';
 const vectorModel=!feature?.origin_run_id?'未记录':!loaded?'读取中…':loaded.runError?'任务记录暂时无法读取':vectorOrigin?'传统图像算法，无独立模型':'未记录';
 return <div className="object-property-source object-source-panel">
  <table className="object-source-summary" aria-label="对象来源信息">
   {feature?<tbody>
    <tr><th>对象编号</th><td>{feature.feature_id}</td></tr>
    <tr><th>对象类型</th><td>{kinds[feature.feature_type]}</td></tr>
    <tr><th>来源类型</th><td>{sources[feature.source_type]??'未记录'}</td></tr>
    <tr><th>识别任务</th><td>{!feature.origin_run_id?'未记录':loaded?.run?taskName(loaded.run):loaded?.runError?'任务记录暂时无法读取':!loaded?'读取中…':'未记录'}</td></tr>
    <tr><th>识别引擎</th><td>{feature.feature_type==='text'?loaded?.candidate?.engine_id?engineName(loaded.candidate.engine_id):feature.ocr_engine_id?engineName(feature.ocr_engine_id):feature.primary_candidate_id?!loaded?'读取中…':loaded.candidateError?'候选记录暂时无法读取':'关联候选未找到':'未记录':vectorEngine}</td></tr>
    <tr><th>识别模型</th><td>{feature.feature_type==='text'?feature.primary_candidate_id?!loaded?'读取中…':loaded.candidateError?'候选记录暂时无法读取':loaded.candidate?.model_id||'未记录':'未记录':vectorModel}</td></tr>
    {feature.feature_type==='text'&&<tr><th>原始识别文字</th><td>{feature.original_text==null?'未记录':feature.original_text||'（空文字）'}</td></tr>}
    <tr><th>创建时间</th><td>{time(feature.created_at)}</td></tr><tr><th>更新时间</th><td>{time(latestTime??feature.updated_at)}</td></tr>
   </tbody>:<><thead><tr><th>对象</th><th>来源类型</th><th>识别引擎</th></tr></thead><tbody>{features.map(item=><tr key={item.feature_id}><td title={item.feature_id}>{kinds[item.feature_type]} · {item.feature_type==='text'?item.text_value:item.feature_id.slice(0,8)}</td><td>{sources[item.source_type]??'未记录'}</td><td>{engine(item)}</td></tr>)}</tbody></>}
  </table>
 </div>;
}

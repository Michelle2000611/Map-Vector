import type {JobEvent,Run} from '../services/models';

export const recognitionStageNames:Record<string,string>={vectorize:'面线识别',ocr:'文字识别',ocr_rapid:'RapidOCR 识别',ocr_paddle:'PaddleOCR 识别'};
const activeStatuses=new Set(['queued','starting','running','cancelling']);
type TimingRun=Pick<Run,'run_id'|'run_status'|'started_at'|'finished_at'|'elapsed_ms'|'stage_name'>;
type StageClock={id:string;startedAt:number|null;endedAt:number|null;measuredMs:number|null;ended:boolean;sequence:number};
function timestamp(value:unknown):number|null{if(typeof value!=='string')return null;const parsed=Date.parse(value);return Number.isFinite(parsed)?parsed:null;}
function duration(value:unknown):number|null{return typeof value==='number'&&Number.isFinite(value)&&value>=0?value:null;}
function difference(end:number|null,start:number|null):number|null{return end!==null&&start!==null?Math.max(0,end-start):null;}

// This is a projection of persisted run/stage events. It has no timer state, so
// refreshes and preview filters cannot reset it. A vector stage includes faces
// and lines; separate face/line durations cannot be derived from this contract.
export function recognitionTiming(run:TimingRun,events:JobEvent[],now:number){
 const active=activeStatuses.has(run.run_status),startedAt=timestamp(run.started_at);
 const ordered=events.filter(event=>event.run_id===run.run_id).sort((a,b)=>a.event_id-b.event_id);
 const terminalEvent=[...ordered].reverse().find(event=>!activeStatuses.has(String(event.event_data.run_status))&&typeof event.event_data.run_status==='string');
 const endedAt=timestamp(run.finished_at)??timestamp(terminalEvent?.created_at);
 const overallElapsedMs=active?difference(now,startedAt):difference(endedAt,startedAt)??((duration(run.elapsed_ms)??0)>0?run.elapsed_ms!:duration(terminalEvent?.event_data.elapsed_ms));
 const clocks=new Map<string,StageClock>();
 for(const event of ordered){
  const stage=event.stage_name;if(!stage||!['stage_started','stage_finished','error'].includes(event.event_type))continue;
  const at=timestamp(event.created_at);
  if(event.event_type==='stage_started')clocks.set(stage,{id:stage,startedAt:at,endedAt:null,measuredMs:null,ended:false,sequence:event.event_id});
  else{
   const clock=clocks.get(stage);if(!clock&&event.event_type==='error')continue;
   clocks.set(stage,{id:stage,startedAt:clock?.startedAt??null,endedAt:at,measuredMs:event.event_type==='stage_finished'?duration(event.event_data.stage_elapsed_ms):null,ended:true,sequence:event.event_id});
  }
 }
 const all=[...clocks.values()],running=all.filter(clock=>!clock.ended);
 const selected=active&&run.stage_name&&!clocks.has(run.stage_name)?[{id:run.stage_name,startedAt:null,endedAt:null,measuredMs:null,ended:false,sequence:0}]:running.length?running:all.length?[all.reduce((latest,clock)=>clock.sequence>latest.sequence?clock:latest)]:[];
 const stages=selected.map(clock=>({name:recognitionStageNames[clock.id]??'未知阶段',elapsedMs:clock.measuredMs??difference(clock.ended?clock.endedAt:active?now:endedAt,clock.startedAt)}));
 const currentLabel=stages.map(stage=>stage.name).join(' + ')||(run.stage_name?recognitionStageNames[run.stage_name]??'未知阶段':'—');
 return {currentLabel,stages,overallElapsedMs:overallElapsedMs??null};
}

export function formatRecognitionDuration(value:number|null){return duration(value)===null?'—':(value!/1000).toFixed(1)+' 秒';}

import {useEffect,useRef,useState} from 'react';
import {TextReviewPanel} from './TextReviewPanel';
import type {TextReviewRevealRequest} from './textReviewReveal';
import {Workbench} from './Workbench';
import {useWorkspace} from '../stores/workspace';
import type {Asset,Command,Feature,Project,Work} from '../services/models';
import type {EditingMode} from '../app/workflow';
type Props={project:Project;asset:Asset;features:Feature[];focus:{feature_id:string;ticket:number;residue?:boolean}|null;mode:EditingMode;onMode:(mode:EditingMode)=>void;onFocus:(id:string,residue?:boolean)=>void;stage:number;onReturnToRecognition:()=>void;busy:boolean;command:Command;work:Work;info:(message:string)=>void;refresh:()=>Promise<void>};
export function EditingWorkspace({mode,onMode,onFocus,...props}:Props){
 const layer=useWorkspace(state=>state.layer);
 const context=JSON.stringify([props.project.project_id,props.asset.asset_id]);
 const [loadedContext,setLoadedContext]=useState<string|null>(mode==='review'?context:null);
 const initializedContext=useRef<string|null>(null);
 const modeSync=useRef({mode,onMode});modeSync.current={mode,onMode};
 useEffect(()=>{
  // The child restores its initial layer before this effect. Ignore that render's old layer.
  const currentLayer=useWorkspace.getState().layer;
  if(initializedContext.current!==context){initializedContext.current=context;if(currentLayer!==layer)return;}
  if(currentLayer==='text')setLoadedContext(context);
  const nextMode:EditingMode=currentLayer==='text'?'review':'geometry';
  if(nextMode!==modeSync.current.mode)modeSync.current.onMode(nextMode);
 },[context,layer]);
 const queue=loadedContext===context?(reviewCommand:Command,revealRequest?:TextReviewRevealRequest,onConfirmNext?:(id:string)=>void)=><TextReviewPanel key={context} project={props.project} asset={props.asset} busy={props.busy} work={props.work} command={reviewCommand} focus={onFocus} revealRequest={revealRequest} onConfirmNext={onConfirmNext}/>:undefined;
 return <section className="editing-workspace" aria-label="编辑与审核工作区">
 <Workbench {...props} initialTextLayer={mode==='review'} belowCanvas={queue} belowCanvasVisible={layer==='text'}/>
 </section>;
}


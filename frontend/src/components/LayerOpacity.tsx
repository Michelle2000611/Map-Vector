import {useRef,useState} from 'react';
import {Slider} from 'antd';

type Props={value:number;busy:boolean;layerName:string;onPreview:(value:number|null)=>void;onCommit:(value:number)=>Promise<unknown>};

/** Preview a drag immediately and persist once the pointer is released. */
export function LayerOpacity({value,busy,layerName,onPreview,onCommit}:Props){
 const [draft,setDraft]=useState<number|null>(null);
 const [saving,setSaving]=useState(false),inFlight=useRef(false);
 // Ant Design forwards these RC Slider handle attributes; its wrapper types omit them.
 const handleAccessibility={ariaLabelForHandle:'图层不透明度'};
 async function commit(next:number){
  if(busy||inFlight.current)return;
  const percentage=Math.min(100,Math.max(0,next));
  if(percentage===value){setDraft(null);onPreview(null);return;}
  inFlight.current=true;setSaving(true);
  try{await onCommit(percentage);}
  finally{inFlight.current=false;setSaving(false);setDraft(null);onPreview(null);}
 }
 return <div className="toolbar-opacity-control" role="group" aria-label="当前图层不透明度" title={layerName+'图层不透明度'}>
  <span>不透明度</span>
  <Slider {...handleAccessibility} min={0} max={100} step={1} disabled={busy||saving} value={draft??value} tooltip={{formatter:percentage=>percentage+'%'}} onChange={next=>{setDraft(next);onPreview(next);}} onChangeComplete={next=>void commit(next)}/>
  <output aria-label="不透明度百分比">{Math.round(draft??value)}%</output>
 </div>;
}

import {useEffect,useId,useRef} from 'react';
import {App as AntApp,Button} from 'antd';

export const sourceTextOverlayExplanation='原图底图会叠加已显示的识别文字；切换为“白底”可单独查看矢量结果。';

/** Explain text editing once per project/asset session without occupying the canvas. */
export function SourceTextOverlayHint({active,onViewVectors}:{active:boolean;onViewVectors:()=>void}){
 const {notification}=AntApp.useApp(),id=useId(),shown=useRef(false),viewVectors=useRef(onViewVectors);
 viewVectors.current=onViewVectors;
 useEffect(()=>{
  if(!active)return;
  const key='source-text-overlay-'+id;
  // Schedule after effect setup so StrictMode's trial cleanup cannot consume the notice.
  const timer=window.setTimeout(()=>{
   if(shown.current)return;
   shown.current=true;
   notification.info({key,className:'app-feedback',message:'原图叠加文字',description:sourceTextOverlayExplanation,duration:6,pauseOnHover:false,role:'status',
    closable:{closeIcon:<span aria-hidden="true">×</span>,'aria-label':'关闭原图叠加提示'},btn:<Button size="small" onClick={()=>viewVectors.current()}>查看矢量结果</Button>});
  },0);
  return()=>{window.clearTimeout(timer);notification.destroy(key);};
 },[active,id,notification]);
 return null;
}

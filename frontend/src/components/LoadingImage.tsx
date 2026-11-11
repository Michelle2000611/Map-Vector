import {useLayoutEffect,useRef} from 'react';
import type {ImgHTMLAttributes,SVGProps} from 'react';
import {beginLoading} from '../services/loading';
function useImageLoading(source:string|undefined){
 const stop=useRef<(()=>void)|null>(null);
 useLayoutEffect(()=>{stop.current=beginLoading('正在加载图像，请稍候…');return()=>{stop.current?.();stop.current=null;};},[source]);
 return ()=>{stop.current?.();stop.current=null;};
}
export function LoadingImage(props:ImgHTMLAttributes<HTMLImageElement>){const done=useImageLoading(props.src);return <img {...props} onLoad={event=>{done();props.onLoad?.(event);}} onError={event=>{done();props.onError?.(event);}}/>;}
export function LoadingSvgImage(props:SVGProps<SVGImageElement>){const done=useImageLoading(props.href);return <image {...props} onLoad={event=>{done();props.onLoad?.(event);}} onError={event=>{done();props.onError?.(event);}}/>;}

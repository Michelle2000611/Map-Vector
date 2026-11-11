import {create} from 'zustand';

type LoadingItem={id:number;label:string};
let serial=0;
export const useLoading=create<{items:LoadingItem[]}>((()=>({items:[]})));
export function beginLoading(label='正在处理，请稍候…'){
 const id=++serial;useLoading.setState(state=>({items:[...state.items,{id,label}]}));let finished=false;
 return ()=>{if(finished)return;finished=true;useLoading.setState(state=>({items:state.items.filter(item=>item.id!==id)}));};
}
export function requestLoadingLabel(path:string,body?:unknown):string|null{
 if(path.includes('/runs')&&body===undefined||path.includes('/exports')&&body===undefined)return null;
 if(path.includes('/export-jobs'))return '正在生成导出成果，请稍候…';
 if(path.includes('/runs')&&body!==undefined)return '正在启动识别任务…';
 if(path.includes('/selections'))return null;
 if(path.includes('/text-layer-assessments'))return '正在检查文字残影，请稍候…';
 if(path.includes('/edit-previews')){const preview=body as {preview_type?:string;complete_region?:boolean}|undefined;return preview?.preview_type==='text_residue'?(preview.complete_region?'正在清理文字残影，请稍候…':'正在查看残影范围，请稍候…'):'正在生成编辑预览，请稍候…';}
 if(path.includes('/edit-commands'))return (body as {operation_type?:string}|undefined)?.operation_type==='cleanup_text_residue'?'正在清理文字残影，请稍候…':'正在保存本次操作，请稍候…';
 if(path==='/capabilities')return '正在检查识别环境…';
 if(path.includes('/import')||body instanceof FormData)return '正在导入原图，请稍候…';
 if(path.includes('/adopt'))return '正在保存识别结果，请稍候…';
 return body===undefined?'正在加载数据，请稍候…':'正在处理，请稍候…';
}

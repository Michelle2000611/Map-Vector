import {useEffect} from 'react';
import {App as AntApp} from 'antd';
import {useLoading} from '../services/loading';
import {useFeedback} from '../services/feedback';
import './AppFeedback.css';

// One viewport outlet for operation results and the latest active request.
export function LoadingFeedback(){
 const {notification}=AntApp.useApp();
 const label=useLoading(state=>state.items.at(-1)?.label??null),notice=useFeedback(state=>state.notice);
 useEffect(()=>{
  if(label)notification.open({key:'workspace-loading',className:'app-feedback',message:label,icon:<span className="app-feedback-loading-icon" aria-hidden="true"/>,duration:0,closeIcon:false,role:'status'});
  else notification.destroy('workspace-loading');
 },[label,notification]);
 useEffect(()=>{
  if(!notice)return;
  notification.open({key:'operation-result',className:'app-feedback',type:notice.type,message:notice.details?'查询结果':notice.message,description:notice.details?<pre className="app-feedback-details">{notice.details}</pre>:undefined,duration:10,closable:{'aria-label':'关闭通知',closeIcon:<span aria-hidden="true">×</span>},role:notice.type==='error'?'alert':'status'});
 },[notice,notification]);
 useEffect(()=>()=>{notification.destroy('workspace-loading');notification.destroy('operation-result');},[notification]);
 return null;
}

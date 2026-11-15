import {Tag,Tooltip} from 'antd';
import {useFeatureHistory} from '../hooks/useFeatureHistory';
import {operationLabel,operationStatusLabel} from '../services/operationLabels';
import './FeatureHistoryPanel.css';

type Props={projectId:string;featureId:string;active:boolean};

const statusTone:Record<string,'success'|'warning'|'default'>={applied:'success',undone:'warning',abandoned:'default'};

function fullTime(value:string|null|undefined){if(!value)return '未记录';const date=new Date(value);return Number.isFinite(date.getTime())?date.toLocaleString('zh-CN',{hour12:false}):'未记录';}
function relativeTime(value:string|null|undefined){
 if(!value)return '未记录';
 const date=new Date(value);if(!Number.isFinite(date.getTime()))return '未记录';
 const seconds=Math.round((Date.now()-date.getTime())/1000);
 if(seconds<5)return '刚刚';
 if(seconds<60)return seconds+' 秒前';
 const minutes=Math.round(seconds/60);
 if(minutes<60)return minutes+' 分钟前';
 const hours=Math.round(minutes/60);
 if(hours<24)return hours+' 小时前';
 const days=Math.round(hours/24);
 if(days<30)return days+' 天前';
 return fullTime(value);
}

export function FeatureHistoryPanel({projectId,featureId,active}:Props){
 const {items,error}=useFeatureHistory({projectId,featureId,active});
 return <section className="feature-history-panel" aria-label="对象操作历史">
  {!items&&!error&&<div className="feature-history-skeleton" aria-hidden="true">{[0,1,2].map(index=><div key={index} className="feature-history-skeleton-row"><span className="feature-history-skeleton-line feature-history-skeleton-title"/><span className="feature-history-skeleton-line feature-history-skeleton-meta"/></div>)}</div>}
  {error&&<p className="feature-history-empty">操作历史暂时无法读取</p>}
  {items&&!items.length&&<p className="feature-history-empty">暂无该对象的操作记录</p>}
  {items&&items.length>0&&<ul className="feature-history-list">{items.map((item,index)=><li key={item.operation_id} className="feature-history-row">
   <div className="feature-history-row-head">
    <span className="feature-history-row-title">{operationLabel(item.operation_type)}</span>
    {index===0&&<Tag className="feature-history-latest-tag">最新</Tag>}
    <Tag color={statusTone[item.operation_status]??'default'}>{operationStatusLabel(item.operation_status)}</Tag>
   </div>
   <div className="feature-history-row-meta">
    <span>修订 {item.result_revision}</span>
    <Tooltip title={fullTime(item.created_at)}><span>{relativeTime(item.created_at)}</span></Tooltip>
   </div>
  </li>)}</ul>}
 </section>;
}

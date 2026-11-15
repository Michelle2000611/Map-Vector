import {Fragment,useId,useState} from 'react';
import {Button,Checkbox,Tag} from 'antd';
import type {LineCheckCandidate,LineCheckParameters} from '../services/lineChecks';

type Props={items:LineCheckCandidate[];checked:string[];verified:string[];highlighted:string;disabled:boolean;parameters:LineCheckParameters;reason:(code:string)=>string;
 onCheck:(id:string,checked:boolean)=>void;onLocate:(item:LineCheckCandidate)=>void;onSelect:(item:LineCheckCandidate)=>void};
const rasterLabels:Record<string,string>={supported:'原图支持连接路径',unsupported:'原图不支持连接路径',ambiguous:'原图依据不明确',unavailable:'原图依据暂不可用',source_mismatch:'原图与当前资产不一致',outside_raster:'连接路径超出原图'};
// Keep related measurements together, independent of the API object's property order.
const metricLabels:Record<string,string>={gap_px:'间距',angle_delta_deg:'方向偏差',gap_stroke_ratio:'间距 / 线宽',connector_length_px:'连接路径长度',attachment_distance_px:'端点贴合距离',tangent_scale_count:'方向采样尺度数',tangent_spread_deg:'多尺度方向差',raster_support_fraction:'原图支持比例',length_px:'长度',segment_count:'线段数',spacing_cv:'间隔变异系数'};
function metricValue(name:string,value:number){
 const rounded=(number:number)=>Number(number.toFixed(2));
 if(name==='raster_support_fraction')return rounded(value*100)+'%';
 return rounded(value)+(name.endsWith('_px')?' px':name.endsWith('_deg')?'°':'');
}
function connectionLabel(item:LineCheckCandidate){return (item.connection_mode==='manual'?'人工接续':'自动建议')+' · '+(item.connector_kind==='manual'?'人工路径':item.connector_kind==='smooth'?'曲线连接':'直线连接');}

export function LineCheckTable({items,checked,verified,highlighted,disabled,parameters,reason,onCheck,onLocate,onSelect}:Props){
 const [expanded,setExpanded]=useState<string|null>(null),id=useId();
 return <div className="line-check-table-wrap"><table className="line-check-table" aria-label="线检查候选">
  <colgroup><col className="line-check-select-column"/><col className="line-check-object-column"/><col/><col className="line-check-status-column"/><col className="line-check-action-column"/></colgroup>
  <thead><tr><th scope="col">选择</th><th scope="col">对象</th><th scope="col">原因</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
  <tbody>{items.map((item,index)=>{
   const key=(item.operation_id??'')+':'+item.candidate_id,open=expanded===key,detailsId=id+'-details-'+index;
   const status=item.status==='applied'?'已处理':item.status==='kept'?'已保留':item.blocked_reasons.length?'受保护':verified.includes(item.candidate_id)?'已核对':'待核对';
   const color=status==='受保护'?'orange':status==='已核对'?'blue':status==='已处理'?'green':undefined;
   const metrics=[...Object.keys(metricLabels).filter(name=>name in item.metrics),...Object.keys(item.metrics).filter(name=>!(name in metricLabels)).sort()];
   return <Fragment key={key}>
    <tr data-candidate-id={item.candidate_id} data-operation-id={item.operation_id} className={highlighted===item.candidate_id?'is-highlighted':''}>
     <td><Checkbox aria-label={'选择线候选 '+item.candidate_id} disabled={disabled||item.status==='applied'} checked={item.status!=='applied'&&checked.includes(item.candidate_id)} onChange={event=>onCheck(item.candidate_id,event.target.checked)}/></td>
     <td><span className="line-check-object-count">{item.feature_ids.length} 条线</span>{item.reference_text_ids.length>0&&<small>关联文字 {item.reference_text_ids.length}</small>}</td>
     <td><div className="line-check-reasons">{item.reason_codes.map(code=><span key={code}>{reason(code)}</span>)}{item.blocked_reasons.map(code=><Tag key={code} color="orange">{reason(code)}</Tag>)}{!item.reason_codes.length&&!item.blocked_reasons.length&&<span>需对照原图核对</span>}</div></td>
     <td><Tag className="line-check-status-tag" color={color}>{status}</Tag></td>
     <td><div className="line-check-row-actions"><Button size="small" disabled={disabled} onClick={()=>onLocate(item)}>定位</Button><Button size="small" disabled={disabled} aria-expanded={open} aria-controls={detailsId} onClick={()=>setExpanded(open?null:key)}>{open?'收起':'详情'}</Button></div></td>
    </tr>
    {open&&<tr className="line-check-details-row"><td colSpan={5}>
     <section id={detailsId} className="line-check-candidate-details" aria-label={'线候选详情 '+item.candidate_id}>
      <div className="line-check-detail-summary">{item.kind==='join_gap'&&<span>{connectionLabel(item)}</span>}{item.evidence?.raster?.status&&<span>{rasterLabels[item.evidence.raster.status]??'原图依据需核对'}</span>}{item.result_revision!==undefined&&<span>修订 {item.result_revision}</span>}</div>
      {item.status!=='applied'&&item.kind==='join_gap'&&<p className="line-check-detail-settings">检查设置：最大接续间距 {parameters.max_gap_px} px · 方向偏差上限 {parameters.angle_tolerance_deg}°</p>}
      {item.status!=='applied'&&item.kind==='text_stroke'&&<p className="line-check-detail-settings">检查设置：文字短线长度上限 {parameters.max_short_length_px} px</p>}
      {metrics.length>0&&<dl className="line-check-metrics">{metrics.map(name=><div key={name}><dt>{metricLabels[name]??name}</dt><dd>{metricValue(name,item.metrics[name])}</dd></div>)}</dl>}
      <div className="line-check-detail-objects"><span className="line-check-detail-label">涉及对象</span><div className="inspection-objects">{item.feature_ids.map(featureId=><span key={featureId}>线 {featureId}</span>)}{item.reference_text_ids.map(featureId=><span key={featureId}>文字 {featureId}</span>)}</div></div>
      {item.status!=='applied'&&<Button size="small" disabled={disabled} onClick={()=>onSelect(item)}>加入选区</Button>}
     </section>
    </td></tr>}
   </Fragment>;
  })}</tbody>
 </table>{!items.length&&<div className="line-check-empty">当前筛选没有候选。</div>}</div>;
}

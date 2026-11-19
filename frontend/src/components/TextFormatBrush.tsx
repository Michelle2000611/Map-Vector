import {useEffect,useRef,useState} from 'react';
import {Alert,Button,Checkbox,Collapse,Input,Modal,Select,Tag} from 'antd';
import type {Feature,Style} from '../services/models';
import type {TextFormatSource} from '../services/textFormat';
import {nextTextStyleName,textStyleSummary} from '../services/textStyles';
import {PropertyField} from './PropertyField';
import './TextFormatBrush.css';

type Props={source:TextFormatSource|null;styles:Style[];styleId?:string;selected:Feature[];copySize:boolean;copyColor:boolean;copyRotation:boolean;copyText:boolean;pending:boolean;busy:boolean;error:string;onCopySize:(value:boolean)=>void;onCopyColor:(value:boolean)=>void;onCopyRotation:(value:boolean)=>void;onCopyText:(value:boolean)=>void;onChooseStyle:(id:string|undefined)=>void;onSave:(name:string)=>Promise<boolean>;onApply:()=>void;onClearOverride:()=>void};
export function TextFormatBrush({source,styles,styleId,selected,copySize,copyColor,copyRotation,copyText,pending,busy,error,onCopySize,onCopyColor,onCopyRotation,onCopyText,onChooseStyle,onSave,onApply,onClearOverride}:Props){
 const [saving,setSaving]=useState<{name:string;size?:number;color?:string;angle?:number}|null>(null),[savingPending,setSavingPending]=useState(false),flight=useRef(false);
 const selectedKey=JSON.stringify(selected.map(item=>item.feature_id).sort());useEffect(()=>{setSaving(null);setSavingPending(false);},[selectedKey]);
 const items=styles.filter(style=>style.feature_type==='text'),chosen=items.find(style=>style.style_id===styleId),bound=selected.length>0&&selected.every(item=>item.style_id===selected[0].style_id)?items.find(style=>style.style_id===selected[0].style_id):undefined;
 const overridden=selected.some(item=>!!item.style_override&&Object.keys(item.style_override).length>0),disabled=busy||pending||savingPending,hasFormat=copySize||copyColor||copyRotation;
 const current=selected.length===1&&selected[0].feature_type==='text'?selected[0]:undefined;
 const openSave=()=>{setSaving({name:nextTextStyleName(styles),size:copySize?(current?.font_size_px??source?.sample.font_size_px):undefined,color:copyColor?(current?.text_color??source?.sample.text_color):undefined,angle:copyRotation?(current?.rotation_deg??source?.sample.rotation_deg):undefined});};
 const fields=[{label:'字号',value:copySize,set:onCopySize,available:!chosen||chosen.font_size_px!=null},{label:'颜色',value:copyColor,set:onCopyColor,available:!chosen||chosen.text_color!=null},{label:'旋转角度',value:copyRotation,set:onCopyRotation,available:!chosen||chosen.rotation_deg!=null},{label:'文字内容',value:copyText,set:onCopyText,available:!!source}];
 return <>
  <Collapse ghost className="line-edit-groups text-format-brush-group" items={[{key:'brush',label:<span className="property-brush-heading">格式刷{bound&&<Tag color="blue">已绑定</Tag>}</span>,children:<section className="text-format-brush" aria-label="文字格式刷">
   <div className="text-format-brush-options">{fields.map(field=><Checkbox key={field.label} checked={field.value} disabled={disabled||!field.available} title={field.label==='文字内容'?'仅本次复制，包含来源上下标结构；需要先在全局格式刷取样文字':undefined} onChange={event=>field.set(event.target.checked)}>{field.label}</Checkbox>)}</div>
   <div className="property-style-buttons"><Button disabled={disabled||!hasFormat||!(current||source)} onClick={openSave}>保存为新样式</Button><Button disabled={disabled||!selected.length||(!chosen&&!source)||(!hasFormat&&!(copyText&&source))} onClick={onApply}>应用到已选对象</Button></div>
   <PropertyField label="文字样式"><Select aria-label="文字样式" allowClear disabled={disabled||!items.length} value={styleId} placeholder={items.length?'选择样式':'暂无样式'} onChange={value=>onChooseStyle(value)} options={items.map(style=>({value:style.style_id,label:<span className="style-option">{style.text_color&&<i className="style-swatch" style={{background:style.text_color}}/>}{style.style_name}</span>,title:style.style_name+' · '+textStyleSummary(style)}))}/></PropertyField>
   {overridden&&bound&&<div className="property-style-buttons"><Tag color="orange">已单独调整</Tag><Button disabled={disabled} onClick={onClearOverride}>恢复图例样式</Button></div>}
   {error&&<Alert type="error" showIcon message={error}/>}
  </section>}]} />
  <Modal title="保存为新样式" open={!!saving} okText="保存" cancelText="取消" destroyOnClose confirmLoading={savingPending} okButtonProps={{disabled:busy||!saving?.name.trim()}} onCancel={()=>{if(!savingPending)setSaving(null);}} onOk={async()=>{if(!saving||flight.current)return;flight.current=true;setSavingPending(true);try{if(await onSave(saving.name.trim()))setSaving(null);}finally{flight.current=false;setSavingPending(false);}}}>
   {saving&&<div className="style-save-form"><Input addonBefore="名称" aria-label="样式名称" value={saving.name} maxLength={200} onChange={event=>setSaving({...saving,name:event.target.value})}/><span className="text-style-save-summary">包含：{[saving.size!=null?'字号 '+saving.size+' px':null,saving.color?'颜色 '+saving.color:null,saving.angle!=null?'角度 '+saving.angle+'°':null].filter(Boolean).join('、')}</span><span className="property-group-note">不包含文字内容</span>{error&&<Alert type="error" message={error}/>}</div>}
  </Modal>
 </>;
}

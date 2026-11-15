import {Button,Collapse,Input,Modal,Select,Tag} from 'antd';
import {useEffect,useRef,useState} from 'react';
import type {Feature,Style} from '../services/models';
import type {DraftField,usePropertyDrafts} from '../stores/propertyDrafts';
import {FeaturePreview} from './FeaturePreview';
import {PropertyColor} from './PropertyColor';
import {PropertyField} from './PropertyField';
import {PropertyNumber} from './PropertyNumber';
import {TextPositionFields} from './TextPositionFields';

type Props={layer:string;feature?:Feature;selectedFeatures:Feature[];previewFeatures?:Feature[];drafts:ReturnType<typeof usePropertyDrafts>;cropSrc?:string;disabled?:boolean;styles?:Style[];onSaveStyle?:(styleName:string,color:string)=>Promise<boolean>;onApplyStyle?:(styleId:string)=>void;onClearOverride?:(featureIds:string[])=>void};

export function StyleSwatch({style}:{style:Style}){
 return style.feature_type==='face'
  ?<span className="style-swatch" style={{background:style.fill_color??undefined,borderColor:style.stroke_color&&style.stroke_width_px?style.stroke_color:undefined}}/>
  :<span className="style-swatch style-swatch-line" style={{borderTopColor:style.stroke_color??undefined,borderTopWidth:Math.min(Math.max(style.stroke_width_px??2,2),5),borderTopStyle:style.line_pattern==='dashed'?'dashed':'solid'}}/>;
}

/** Shared appearance controls keep mixed values empty until the user edits a field. */
export function ObjectAppearanceProperties({layer,feature,selectedFeatures,previewFeatures,drafts,disabled=false,styles=[],onSaveStyle,onApplyStyle,onClearOverride}:Props){
 const [styleToApply,setStyleToApply]=useState<string|undefined>();
 const [saving,setSaving]=useState<{name:string;color:string}|null>(null);
 const [savePending,setSavePending]=useState(false);
 const selectionKey=JSON.stringify([layer,selectedFeatures.map(item=>item.feature_id).sort()]);
 const currentSelection=useRef(selectionKey),saveInFlight=useRef(false);currentSelection.current=selectionKey;
 useEffect(()=>{setStyleToApply(undefined);setSaving(null);setSavePending(false);},[selectionKey]);
 const overridden=selectedFeatures.filter(item=>item.feature_type!=='text'&&item.style_id&&item.style_override);
 const values=drafts.values,submitted=drafts.capture();
 const input=(field:DraftField)=>({draftValue:drafts.inputValue(field),onDraftChange:(value:string|undefined)=>drafts.input(field,value)});
 function mixed(field:DraftField,read:(feature:Feature)=>unknown){
  if(submitted&&(field in submitted||field in (submitted.inputs??{})))return false;
  return selectedFeatures.length>1&&selectedFeatures.some(item=>!Object.is(read(item),read(selectedFeatures[0])));
 }
 const edited=(field:DraftField)=>!!submitted&&field in submitted;
 const layerStyles=styles.filter(item=>item.feature_type===layer);
 const bindingIds=new Set(selectedFeatures.map(item=>item.style_id));
 const boundStyle=selectedFeatures.length>0&&bindingIds.size===1&&selectedFeatures.every(item=>!!item.style_id)?layerStyles.find(style=>style.style_id===selectedFeatures[0].style_id):undefined;
 const brush=(layer==='face'||layer==='line')&&(onSaveStyle||onApplyStyle);
 return <section className={'object-appearance-properties'+(layer==='text'?' text-appearance-properties':'')} aria-label="外观属性编辑">
  <FeaturePreview features={previewFeatures??selectedFeatures} styles={styles} color={edited('color')?values.color:undefined} width={edited('width')?values.width:undefined}/>
  {layer==='text'&&<>
   <h4 className="property-group-heading property-group-heading-full">外观</h4>
   <Input disabled={disabled} className="property-text" addonBefore="内容" aria-label="编辑文字" placeholder="文字内容" value={values.text} onChange={event=>drafts.set('text',event.target.value)}/>
   <PropertyColor disabled={disabled} label="颜色" value={values.color} {...input('color')} onChange={value=>drafts.set('color',value)}/>
   <>
    <PropertyNumber disabled={disabled} label="字号" ariaLabel="文字字号" min={1} max={200} value={values.fontSize} {...input('fontSize')} onChange={value=>drafts.set('fontSize',value)}/>
    <PropertyNumber disabled={disabled} label="旋转角度" ariaLabel="文字角度" min={-180} max={180} value={values.angle} {...input('angle')} onChange={value=>drafts.set('angle',value)}/>
   </>
   <TextPositionFields disabled={disabled} feature={feature?.feature_type==='text'?feature:undefined} x={values.moveX} y={values.moveY} onXChange={value=>drafts.set('moveX',value)} onYChange={value=>drafts.set('moveY',value)} xDraft={input('moveX')} yDraft={input('moveY')}/>
  </>}
  {layer!=='text'&&<PropertyColor disabled={disabled} label="颜色" value={values.color} {...input('color')} onChange={value=>drafts.set('color',value)} mixed={mixed('color',item=>item.feature_type==='face'?item.fill_color:item.feature_type==='line'?item.stroke_color:item.text_color)}/>}
  {(layer==='line'||layer==='isolated_line')&&<>
   <PropertyNumber disabled={disabled} label="宽度（px）" ariaLabel="线宽" min={.25} max={50} value={values.width} {...input('width')} onChange={value=>drafts.set('width',value)} mixed={mixed('width',item=>item.feature_type==='line'?item.stroke_width_px:undefined)}/>
   <PropertyField label="用途"><Select disabled={disabled} value={mixed('role',item=>item.feature_type==='line'?item.line_role:undefined)?undefined:values.role} placeholder="多个值" aria-label="线用途" onChange={value=>drafts.set('role',value)} options={[{value:'unknown',label:'待定'},{value:'cover',label:'覆盖线'},{value:'split',label:'分割线'}]}/></PropertyField>
  </>}
  {brush&&<Collapse ghost defaultActiveKey={['brush']} className="line-edit-groups property-style-actions" items={[{key:'brush',label:<span className="property-brush-heading">格式刷{boundStyle&&<Tag color="blue">已绑定 {boundStyle.style_name}</Tag>}</span>,children:<div className="property-style-body">
   <div className="property-style-buttons">
    <Button disabled={disabled||mixed('color',item=>item.feature_type==='face'?item.fill_color:item.feature_type==='line'?item.stroke_color:undefined)} onClick={()=>setSaving({name:(layer==='face'?'面样式 ':'线样式 ')+(layerStyles.length+1),color:values.color})}>保存为新样式</Button>
    <Button disabled={disabled||!styleToApply} onClick={()=>{if(styleToApply)onApplyStyle?.(styleToApply);}}>应用到已选对象</Button>
   </div>
   <PropertyField label="图例样式"><Select disabled={disabled||!layerStyles.length} value={styleToApply} placeholder={layerStyles.length?'选择样式':'暂无样式'} aria-label="选择样式应用" options={layerStyles.map(item=>({value:item.style_id,label:<span className="style-option"><StyleSwatch style={item}/>{item.style_name}</span>}))} onChange={setStyleToApply}/></PropertyField>
   {overridden.length>0&&onClearOverride&&<div className="property-style-buttons">
    <Tag color="orange">已单独调整 {overridden.length} 个</Tag>
    <Button disabled={disabled} onClick={()=>onClearOverride(overridden.map(item=>item.feature_id))}>恢复图例样式</Button>
   </div>}
  </div>}]}/>}
  <Modal open={!!saving} title="保存为新样式" okText="保存" cancelText="取消" destroyOnClose confirmLoading={savePending} okButtonProps={{disabled:disabled||!saving?.name.trim()||!/^#[0-9a-f]{6}$/i.test(saving?.color??'')}} onCancel={()=>{if(!savePending)setSaving(null);}} onOk={async()=>{if(!saving||!onSaveStyle||saveInFlight.current)return;const expected=selectionKey;saveInFlight.current=true;setSavePending(true);try{const saved=await onSaveStyle(saving.name.trim(),saving.color);if(saved&&currentSelection.current===expected)setSaving(null);}finally{saveInFlight.current=false;if(currentSelection.current===expected)setSavePending(false);}}}>
   {saving&&<div className="style-save-form">
    <PropertyColor label="色块" value={saving.color} onChange={color=>setSaving({...saving,color})}/>
    <Input addonBefore="名称" aria-label="样式名称" placeholder="样式名称" maxLength={64} value={saving.name} onChange={event=>setSaving({...saving,name:event.target.value})}/>
   </div>}
  </Modal>
 </section>;
}

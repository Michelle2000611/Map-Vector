import {Input,Select} from 'antd';
import type {Feature} from '../services/models';
import type {DraftField,usePropertyDrafts} from '../stores/propertyDrafts';
import {LoadingImage} from './LoadingImage';
import {PropertyColor} from './PropertyColor';
import {PropertyField} from './PropertyField';
import {PropertyNumber} from './PropertyNumber';
import {TextPositionFields} from './TextPositionFields';

type Props={layer:string;feature?:Feature;selectedFeatures:Feature[];drafts:ReturnType<typeof usePropertyDrafts>;cropSrc?:string;disabled?:boolean};

/** Shared appearance controls keep mixed values empty until the user edits a field. */
export function ObjectAppearanceProperties({layer,feature,selectedFeatures,drafts,cropSrc,disabled=false}:Props){
 const values=drafts.values,submitted=drafts.capture();
 const input=(field:DraftField)=>({draftValue:drafts.inputValue(field),onDraftChange:(value:string|undefined)=>drafts.input(field,value)});
 function mixed(field:DraftField,read:(feature:Feature)=>unknown){
  if(submitted&&(field in submitted||field in (submitted.inputs??{})))return false;
  return selectedFeatures.length>1&&selectedFeatures.some(item=>!Object.is(read(item),read(selectedFeatures[0])));
 }
 return <section className={'object-appearance-properties'+(layer==='text'?' text-appearance-properties':'')} aria-label="外观属性编辑">
  {layer==='text'&&<>
   {cropSrc&&<div className="property-source-crop"><LoadingImage alt="所选文字原图裁剪" style={{maxWidth:'100%',maxHeight:180,objectFit:'contain'}} src={cropSrc}/></div>}
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
 </section>;
}

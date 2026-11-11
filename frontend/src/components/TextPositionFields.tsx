import {Input} from 'antd';
import type {TextFeature} from '../services/models';
import {formatPropertyNumber,PropertyNumber} from './PropertyNumber';
import './TextPositionFields.css';

type PositionDraft={draftValue?:string;onDraftChange?:(value:string|undefined)=>void};
type TextPositionFieldsProps={
 feature?:TextFeature;
 x:number;
 y:number;
 onXChange:(value:number)=>void;
 onYChange:(value:number)=>void;
 xDraft?:PositionDraft;
 yDraft?:PositionDraft;
 disabled?:boolean;
};

export function TextPositionFields({feature,x,y,onXChange,onYChange,xDraft,yDraft,disabled=false}:TextPositionFieldsProps){
 const box=feature?.display_bbox_px;
 const width=box?.length===4?box[2]-box[0]:NaN,height=box?.length===4?box[3]-box[1]:NaN;
 const valid=box?.length===4&&box.every(Number.isFinite)&&Number.isFinite(width)&&Number.isFinite(height)&&width>=0&&height>=0;
 return <section className="text-position-fields" aria-label="文字位置与边界框">
  <div className="text-position-grid">
   <PropertyNumber label="X" ariaLabel="文字X位置" value={x} onChange={onXChange} {...xDraft} disabled={disabled}/>
   <PropertyNumber label="Y" ariaLabel="文字Y位置" value={y} onChange={onYChange} {...yDraft} disabled={disabled}/>
   <Input addonBefore="W" aria-label="文字边界框宽度" value={valid?formatPropertyNumber(width):'—'} readOnly/>
   <Input addonBefore="H" aria-label="文字边界框高度" value={valid?formatPropertyNumber(height):'—'} readOnly/>
  </div>
 </section>;
}

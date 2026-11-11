import {useEffect,useRef,useState} from 'react';
import {Input} from 'antd';

export function formatPropertyNumber(value:number,decimals=1){return Number(value.toFixed(decimals)).toString();}
/** Display rounding is never a write: only an explicitly edited draft is committed. */
export function PropertyNumber({label,ariaLabel,value,onChange,min,max,decimals=1,draftValue,onDraftChange,mixed=false,disabled=false}:{label:string;ariaLabel:string;value:number;onChange:(value:number)=>void;min?:number;max?:number;decimals?:number;draftValue?:string;onDraftChange?:(value:string|undefined)=>void;mixed?:boolean;disabled?:boolean}){
 const [draft,setDraft]=useState(draftValue??(mixed?'':formatPropertyNumber(value,decimals)));const dirty=useRef(draftValue!==undefined);
 useEffect(()=>{setDraft(draftValue??(mixed?'':formatPropertyNumber(value,decimals)));dirty.current=draftValue!==undefined;},[value,decimals,draftValue,mixed]);
 const number=Number(draft),invalid=!(mixed&&!dirty.current&&!draft)&&(!draft.trim()||!Number.isFinite(number)||(min!==undefined&&number<min)||(max!==undefined&&number>max));
 function commit(){if(!dirty.current||invalid)return;dirty.current=false;onChange(number);setDraft(formatPropertyNumber(number,decimals));onDraftChange?.(undefined);}
 return <Input className="property-number" disabled={disabled} addonBefore={label} aria-label={ariaLabel} role="spinbutton" aria-valuenow={mixed?undefined:value} aria-valuemin={min} aria-valuemax={max} aria-invalid={invalid} status={invalid?'error':undefined} inputMode="decimal" placeholder={mixed?'多个值':undefined} value={draft} onChange={event=>{dirty.current=true;setDraft(event.target.value);onDraftChange?.(event.target.value);}} onBlur={commit} onPressEnter={event=>event.currentTarget.blur()}/>;
}

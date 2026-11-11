import {useEffect,useState} from 'react';
import {Input} from 'antd';

export function PropertyColor({value,onChange,draftValue,onDraftChange,label='颜色',mixed=false,disabled=false}:{value:string;onChange:(color:string)=>void;draftValue?:string;onDraftChange?:(value:string|undefined)=>void;label?:string;mixed?:boolean;disabled?:boolean}){
 const [draft,setDraft]=useState(draftValue??(mixed?'':value));
 useEffect(()=>setDraft(draftValue??(mixed?'':value)),[value,draftValue,mixed]);
 const invalid=!(mixed&&!draft&&draftValue===undefined)&&!/^#[0-9a-f]{6}$/i.test(draft.trim());
 function commit(){if(invalid||(mixed&&!draft&&draftValue===undefined))return;const next=draft.trim();if(next!==value||draftValue!==undefined)onChange(next);setDraft(next);onDraftChange?.(undefined);}
 return <Input className="property-color" disabled={disabled} addonBefore={label} aria-label="颜色值" placeholder={mixed?'多个值':undefined} value={draft} maxLength={7} aria-invalid={invalid} status={invalid?'error':undefined} onChange={event=>{setDraft(event.target.value);onDraftChange?.(event.target.value);}} onBlur={commit} onPressEnter={event=>event.currentTarget.blur()} addonAfter={<input aria-label="对象颜色" title={mixed?'多个值；选择新颜色':'选择颜色'} type="color" disabled={disabled} value={value} onChange={event=>{setDraft(event.target.value);onChange(event.target.value);onDraftChange?.(undefined);}}/>}/>;
}

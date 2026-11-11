import {useEffect,useId,useState} from 'react';
import {theme} from 'antd';
import type {TabsProps} from 'antd';
import type {CSSProperties,KeyboardEvent,ReactNode} from 'react';
import './PropertySectionTabs.css';

type PropertySection=Omit<NonNullable<TabsProps['items']>[number],'children'>&{visible?:boolean;children:ReactNode|((active:boolean)=>ReactNode)};
type Props={items:PropertySection[];contextKey?:string;revealRequest?:{key:string;ticket:number};onActiveChange?:(key:string)=>void};

// Navigation includes only available sections. All bodies stay mounted so drafts,
// IME composition, table filters and review decisions survive navigation.
export function PropertySectionTabs({items,contextKey='',revealRequest,onActiveChange}:Props){
 const {token}=theme.useToken(),id=useId();
 const [active,setActive]=useState({contextKey,key:'appearance'});
 useEffect(()=>{if(revealRequest)setActive({contextKey,key:revealRequest.key});},[contextKey,revealRequest?.key,revealRequest?.ticket]);
 const available=items.filter(item=>item.visible!==false);
 const selected=active.contextKey===contextKey&&available.some(item=>item.key===active.key)?active.key:'appearance';
 useEffect(()=>{onActiveChange?.(selected);},[selected,onActiveChange]);
 function navigate(event:KeyboardEvent<HTMLDivElement>){
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const tabs=Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)'));
  const index=tabs.indexOf(document.activeElement as HTMLButtonElement);if(index<0||!tabs.length)return;
  event.preventDefault();
  const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  tabs[next].focus();tabs[next].click();
 }
 return <div className="property-section-tabs" data-reveal-key={revealRequest?.key} style={{'--property-tab-active':token.colorPrimary,'--property-tab-border':token.colorBorderSecondary} as CSSProperties}>
  <div className="ant-tabs-nav"><div role="tablist" aria-label="属性操作分类" className="ant-tabs-nav-list" onKeyDown={navigate}>{available.map(item=><div key={item.key} className={'ant-tabs-tab'+(item.key===selected?' ant-tabs-tab-active':'')}>
   <button type="button" role="tab" className="ant-tabs-tab-btn" id={id+'-tab-'+item.key} aria-controls={id+'-panel-'+item.key} aria-selected={item.key===selected} tabIndex={item.key===selected?0:-1} disabled={item.disabled} onClick={()=>setActive({contextKey,key:item.key})}>{item.label}</button>
  </div>)}</div></div>
  <div className="ant-tabs-content-holder"><div className="ant-tabs-content">{items.map(item=>{
   const visible=item.visible!==false&&item.key===selected;
   return <div key={item.key} role="tabpanel" className={'ant-tabs-tabpane'+(visible?' ant-tabs-tabpane-active':'')} id={id+'-panel-'+item.key} aria-labelledby={id+'-tab-'+item.key} hidden={!visible}>{typeof item.children==='function'?item.children(visible):item.children}</div>;
  })}</div></div>
 </div>;
}

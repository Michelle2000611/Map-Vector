import type {ReactNode} from 'react';
import './ReasonList.css';

/** Keep wrapped lines aligned with their reason rather than the bullet. */
export function ReasonList({items,className=''}:{items:ReactNode[];className?:string}){
 if(!items.length)return null;
 return <ul className={'reason-list '+className}>{items.map((item,index)=><li key={index}>{item}</li>)}</ul>;
}

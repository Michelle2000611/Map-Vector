import type {ReactNode} from 'react';
import {Button,theme} from 'antd';

type Props={title:string;onClose:()=>void;children:ReactNode};

export function GlobalToolPanel({title,onClose,children}:Props){
 const {token}=theme.useToken();
 return <div className="global-tool-panel" aria-label={title+'面板'}>
  <div className="global-tool-body">
   <div className="global-tool-header"><span className="global-tool-title" style={{fontFamily:token.fontFamily,fontSize:token.fontSizeLG,fontWeight:token.fontWeightStrong,lineHeight:token.lineHeight,color:token.colorTextHeading}}>{title}</span><Button size="small" onClick={onClose}>关闭</Button></div>
   <div className="global-tool-content">{children}</div>
  </div>
 </div>;
}

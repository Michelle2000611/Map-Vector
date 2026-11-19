import {Button} from 'antd';
import type {ReactNode} from 'react';

type Props={busy:boolean;onAdd:()=>void;formatBrush:ReactNode};

export function TextActions({busy,onAdd,formatBrush}:Props){
 return <div className="property-action-section">
   <Button block disabled={busy} onClick={onAdd}>补录文字</Button>
   {formatBrush}
  </div>;
}

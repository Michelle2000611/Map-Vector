import {Button} from 'antd';

type Props={busy:boolean;selected:boolean;onSkip:()=>void;onAdd:()=>void};

export function TextActions({busy,selected,onSkip,onAdd}:Props){
 return <div className="property-action-section">
   <div className="property-button-grid">
    <Button disabled={busy||!selected} onClick={onSkip}>标记为待处理</Button>
    <Button disabled={busy} onClick={onAdd}>补录文字</Button>
   </div>
  </div>;
}

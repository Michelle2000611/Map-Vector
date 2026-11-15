import {Button,Collapse} from 'antd';

type Props={busy:boolean;selected:boolean;onSkip:()=>void;onAdd:()=>void;hasCopiedAppearance:boolean;onCopyAppearance:()=>void;onPasteAppearance:()=>void};

export function TextActions({busy,selected,onSkip,onAdd,hasCopiedAppearance,onCopyAppearance,onPasteAppearance}:Props){
 return <div className="property-action-section">
   <Button block disabled={busy||!selected} onClick={onSkip}>标记为待处理</Button>
   <Button block disabled={busy} onClick={onAdd}>补录文字</Button>
   <Collapse ghost className="text-appearance-copy-group" items={[
    {key:'copy_appearance',label:'外观复制',children:<div className="property-button-grid">
     <Button disabled={busy||!selected} onClick={onCopyAppearance}>复制外观</Button>
     <Button disabled={busy||!hasCopiedAppearance} onClick={onPasteAppearance}>粘贴外观</Button>
    </div>}
   ]}/>
  </div>;
}

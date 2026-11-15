import {Button} from 'antd';
import './InspectionStatus.css';

type Props={state:'waiting'|'checking'|'done';attempted:boolean;disabled?:boolean;onCheck:()=>void;ariaLabel?:string};
const labels={waiting:'等待检查',checking:'正在检查',done:'检查完成'};

export function InspectionStatus({state,attempted,disabled,onCheck,ariaLabel}:Props){
 return <div className="inspection-status" data-state={state}>
  <span className="inspection-status-text" aria-live="polite" aria-atomic="true" aria-label={ariaLabel}><i className="inspection-status-dot" aria-hidden="true"/>{labels[state]}</span>
  <Button disabled={disabled||state==='checking'} onClick={onCheck}>{attempted?'重新检查':'开始检查'}</Button>
 </div>;
}

import {create} from 'zustand';

export type FeedbackType='success'|'info'|'warning'|'error';
export type FeedbackNotice={id:number;type:FeedbackType;message:string;details?:string};
let serial=0;
export const useFeedback=create<{notice:FeedbackNotice|null}>(()=>({notice:null}));
function publish(type:FeedbackType,message:string){
 // Empty callbacks reset local operations; they must not dismiss an earlier error.
 if(!message.trim())return;
 let details:string|undefined;
 if(type==='info'&&(/^[{[]/.test(message.trim())||message.length>180)){
  details=message;
  try{details=JSON.stringify(JSON.parse(message),null,2);}catch{/* Keep non-JSON diagnostic text readable too. */}
 }
 useFeedback.setState({notice:{id:++serial,type,message,details}});
}
export const feedback={
 success:(message:string)=>publish('success',message),
 info:(message:string)=>publish('info',message),
 warning:(message:string)=>publish('warning',message),
 error:(message:string)=>publish('error',message),
};

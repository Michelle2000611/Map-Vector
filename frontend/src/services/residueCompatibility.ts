/** Explain a known old-server contract rejection without hiding other validation failures. */
export function residueCompatibilityMessage(path:string,body:unknown,code:string,detail:Record<string,unknown>):string|undefined{
 if(code!=='VALIDATION_ERROR'||!/^\/projects\/[^/]+\/(?:text-residue|line-check|heal-residue)-decisions$/.test(path)||!body||typeof body!=='object'||!('decision' in body)||body.decision!=='confirm'||!Array.isArray(detail.errors))return;
 const oldDecision=detail.errors.some(item=>{
  if(!item||typeof item!=='object')return false;
  const error=item as Record<string,unknown>;
  return Array.isArray(error.loc)&&error.loc.join('.')==='body.decision'&&error.type==='literal_error'&&typeof error.message==='string'&&error.message.includes('keep')&&error.message.includes('reopen')&&!error.message.includes('confirm');
 });
 return oldDecision?'当前后端尚未加载“确认核对”功能。请重新加载后端后再检查，所选对象未被修改。':undefined;
}

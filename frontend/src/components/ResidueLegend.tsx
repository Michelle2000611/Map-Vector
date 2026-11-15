type Props={shown:{faces:boolean;lines:boolean;protected:boolean;context:boolean}};

/** Static schematic icons, not a render of the current asset — colors only teach what each toggle means. */
export function ResidueLegend({shown}:Props){
 return <svg className="residue-legend" viewBox="0 0 200 60" aria-hidden="true">
  <rect width={200} height={60} fill="#fff"/>
  {shown.context&&<rect x={14} y={10} width={30} height={40} fill="none" stroke="#bfbfbf" strokeWidth={1.5}/>}
  {shown.faces&&<path d="M58 14 L82 18 L78 42 L54 38 Z" fill="#fa8c16" fillOpacity={.38} stroke="#d46b08" strokeWidth={1.5}/>}
  {shown.lines&&<path d="M96 44 L108 20 L120 30 L132 14" fill="none" stroke="#c41d7f" strokeWidth={2.5}/>}
  {shown.protected&&<path d="M146 44 L186 16" fill="none" stroke="#1677ff" strokeWidth={2.5} strokeDasharray="5 3"/>}
 </svg>;
}

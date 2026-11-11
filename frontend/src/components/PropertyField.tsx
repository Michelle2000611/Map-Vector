import type {ReactNode} from 'react';

/** Matches the joined label/input layout for controls without an addonBefore API. */
export function PropertyField({label,children}:{label:string;children:ReactNode}){
 return <div className="property-labeled-field"><span className="property-field-label">{label}</span><div className="property-field-control">{children}</div></div>;
}

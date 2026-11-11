import {useEffect,useRef,useSyncExternalStore} from 'react';
import {PropertyAutosave,buildPropertyPatch} from '../stores/propertyAutosave';
import type {AutosaveInput} from '../stores/propertyAutosave';
export {buildPropertyPatch};

export function usePropertyAutosave(input:AutosaveInput){
 const ref=useRef<PropertyAutosave>();
 if(!ref.current)ref.current=new PropertyAutosave();
 const controller=ref.current;
 const lifecycle=useRef(0);
 const state=useSyncExternalStore(controller.subscribe,controller.getSnapshot,controller.getSnapshot);
 useEffect(()=>{controller.update(input);});
 useEffect(()=>{const ticket=++lifecycle.current;return()=>{queueMicrotask(()=>{if(lifecycle.current===ticket)controller.dispose();});};},[controller]);
 const {previewFeature}=buildPropertyPatch(input.scope,input.features,input.drafts.values,input.drafts.capture(),input.drafts.invalidFields,input.assetSize);
 return {...state,previewFeature,flush:controller.flush,retry:controller.retry,onCompositionStart:controller.onCompositionStart,onCompositionEnd:controller.onCompositionEnd,onBlur:controller.onBlur};
}

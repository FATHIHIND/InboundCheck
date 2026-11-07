import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { registerHooks } from 'node:module';
import ts from 'typescript';
import React, { act } from 'react';
import { renderToString } from 'react-dom/server';
import { hydrateRoot } from 'react-dom/client';
import { JSDOM } from 'jsdom';
const hooks=registerHooks({load(url,context,nextLoad){
 if(url.endsWith('.tsx'))return {shortCircuit:true,format:'module',source:ts.transpileModule(fs.readFileSync(fileURLToPath(url),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText};
 return nextLoad(url,context);
}});
const {default:EnvConfigAlert}=await import('../src/components/ui/EnvConfigAlert.tsx');
test('React 19 hydrates the real global environment alert without recoverable errors',async()=>{
 const element=React.createElement(EnvConfigAlert);const html=renderToString(element);assert.equal(html,'');
 const dom=new JSDOM('<!doctype html><html><body><div id="root">'+html+'</div></body></html>',{url:'https://example.invalid/'});
 const oldWindow=globalThis.window,oldDocument=globalThis.document,oldAct=globalThis.IS_REACT_ACT_ENVIRONMENT;
 globalThis.window=dom.window;globalThis.document=dom.window.document;globalThis.IS_REACT_ACT_ENVIRONMENT=true;
 const errors=[];let root;
 try {
  await act(async()=>{root=hydrateRoot(document.getElementById('root'),element,{onRecoverableError:error=>errors.push(error.message)})});
  assert.deepEqual(errors,[]);assert.match(document.body.textContent,/Configuration Notice:/);
  await act(async()=>{document.querySelector('button[aria-label="Dismiss banner"]').dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}))});
  assert.equal(document.getElementById('root').textContent,'');
 }finally{if(root)await act(async()=>root.unmount());dom.window.close();globalThis.window=oldWindow;globalThis.document=oldDocument;globalThis.IS_REACT_ACT_ENVIRONMENT=oldAct;}
});
test.after(()=>hooks.deregister());

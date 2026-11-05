import test from 'node:test';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
const key = '__nextAuthMigration';
const hooks = registerHooks({resolve(specifier, context, nextResolve) {
 if (specifier === 'next/headers') return {shortCircuit:true,url:'data:text/javascript,export async function cookies(){return globalThis.__nextAuthMigration.store}'};
 if (specifier === '@supabase/ssr') return {shortCircuit:true,url:'data:text/javascript,export function createServerClient(url,key,options){globalThis.__nextAuthMigration.options=options;return {auth:{async exchangeCodeForSession(code){globalThis.__nextAuthMigration.code=code;return {error:globalThis.__nextAuthMigration.error}}}}}'};
 if (specifier === 'next/server') return nextResolve('next/server.js', context);
 return nextResolve(specifier, context);
}});
const { createClient } = await import('../src/lib/supabase/server.ts');
const { GET } = await import('../src/app/auth/callback/route.ts');
test('Next async request cookies preserve Supabase session get/set/remove', async()=>{
 const writes=[];globalThis[key]={store:{get:n=>({value:'session:'+n}),set:v=>writes.push(v)}};
 await createClient();const {cookies}=globalThis[key].options;
 assert.equal(cookies.get('token'),'session:token');cookies.set('token','new',{httpOnly:true});cookies.remove('token',{path:'/'});
 assert.deepEqual(writes,[{name:'token',value:'new',httpOnly:true},{name:'token',value:'',path:'/'}]);
});
test('OAuth callback awaits cookie store and keeps canonical safe redirects',async()=>{
 const writes=[];globalThis[key]={store:{get:()=>undefined,set:v=>writes.push(v)},error:null};
 const response=await GET(new Request('https://inboundcheck.com/auth/callback?code=test-code&next=//attacker.invalid'));
 assert.equal(globalThis[key].code,'test-code');assert.equal(response.headers.get('location'),'https://inboundcheck.com/dashboard');
 globalThis[key].options.cookies.remove('token',{httpOnly:true});assert.equal(writes[0].maxAge,0);
 globalThis[key].error={message:'rejected'};
 const failure=await GET(new Request('https://inboundcheck.com/auth/callback?code=bad&next=/dashboard/settings'));
 assert.equal(failure.headers.get('location'),'https://inboundcheck.com/auth/login?error=auth_callback_failed');
});
test.after(()=>{hooks.deregister();delete globalThis[key]});

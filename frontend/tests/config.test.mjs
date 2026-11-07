import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const read = name => readFile(new URL(name, import.meta.url), 'utf8');
async function csp(mode) {
 const previous=process.env.NODE_ENV;
 try { process.env.NODE_ENV=mode; const {default:config}=await import('../next.config.mjs?mode='+mode); const routes=await config.headers(); return routes[0].headers.find(h=>h.key==='Content-Security-Policy').value; }
 finally { if(previous===undefined) delete process.env.NODE_ENV; else process.env.NODE_ENV=previous; }
}
test('production CSP forbids eval while retaining static hydration compatibility', async()=>{
 const policy=await csp('production');
 assert.ok(!policy.includes("'unsafe-eval'"));
 assert.ok(!policy.includes("*.supabase.co"), "Supabase connections require an exact configured project origin");
 assert.ok(policy.includes("script-src 'self' 'unsafe-inline'"));
 for(const directive of ["object-src 'none'", "base-uri 'self'", "default-src 'self'"]) assert.ok(policy.includes(directive));
});
test('CSP frame-ancestors and X-Frame-Options both forbid framing (FE-2 clickjacking)', async()=>{
 for(const mode of ['production','development']) {
  const directives=(await csp(mode)).split(';').map(s=>s.trim());
  assert.ok(directives.includes("frame-ancestors 'none'"), mode+": frame-ancestors 'none'");
 }
 const {default:config}=await import('../next.config.mjs?mode=frame');
 const [route]=await config.headers();
 assert.equal(route.source,'/:path*');
 assert.equal(route.headers.find(h=>h.key==='X-Frame-Options')?.value,'DENY');
});
test('development CSP explicitly permits Next development eval only', async()=>{
 assert.ok((await csp('development')).includes("'unsafe-eval'"));
});
test('both Docker contexts exclude real dotenv files at every depth', async()=>{
 for(const name of ['../.dockerignore','../../.dockerignore']) {
  const lines=(await read(name)).split(/\r?\n/).map(s=>s.trim());
  for(const pattern of ['.env','.env.*','**/.env','**/.env.*','.phase5-verification','**/.phase5-verification']) assert.ok(lines.includes(pattern), name+': '+pattern);
  assert.ok(!lines.some(s=>s.startsWith('!') && s.includes('.env')));
 }
});
test('Docker consumes root lock, Node 24 and non-root standalone output', async()=>{
 const docker=await read('../Dockerfile');
 assert.equal((docker.match(/FROM node:24-alpine/g)||[]).length,2);
 assert.ok(docker.includes('COPY package.json package-lock.json ./'));
 assert.ok(docker.includes('COPY frontend/package.json ./frontend/package.json'));
 assert.ok(docker.includes('npm ci --ignore-scripts'));
 assert.ok(docker.includes('USER node'));
 assert.ok(docker.includes('"frontend/server.js"'));
 assert.ok(!docker.includes('COPY . .'));
});
test('workspace has a single lockfile and no root duplicated dependencies', async()=>{
 const root=JSON.parse(await read('../../package.json'));
 const frontend=JSON.parse(await read('../package.json'));
 const lock=JSON.parse(await read('../../package-lock.json'));
 assert.equal(root.dependencies,undefined);assert.equal(root.devDependencies,undefined);
 assert.equal(root.engines.node,'24.x');assert.equal(frontend.engines.node,'24.x');
 assert.equal(lock.lockfileVersion,3);
 assert.deepEqual(lock.packages.frontend.dependencies,frontend.dependencies);
 for(const name of ['lint','typecheck','test','build']) assert.ok(frontend.scripts[name]);
});

test('root layout builds without third-party font downloads', async()=>{
 const layout=await read('../src/app/layout.tsx');
 assert.ok(!layout.includes('next/font/google'));
 const css=await read('../src/app/globals.css');
 assert.ok(css.includes('--font-sans: "Plus Jakarta Sans", Arial, system-ui, sans-serif'));
});

test('public API and Supabase configuration contributes exact safe CSP origins', async()=>{
 const {getConfiguredConnectSources}=await import('../next.config.mjs');
 assert.deepEqual(getConfiguredConnectSources({NEXT_PUBLIC_API_URL:'https://staging-api.example.test/api/v1',NEXT_PUBLIC_SUPABASE_URL:'https://example-project.supabase.co'}),['https://staging-api.example.test','https://example-project.supabase.co','wss://example-project.supabase.co']);
 assert.deepEqual(getConfiguredConnectSources({NEXT_PUBLIC_API_URL:'http://127.0.0.1:8080'}),['http://127.0.0.1:8080']);
 for(const value of ['http://remote.example.test','javascript:alert(1)','https://user:password@example.test',"https://example.test;script-src/'unsafe-eval'",'https://*.example.test']) assert.deepEqual(getConfiguredConnectSources({NEXT_PUBLIC_API_URL:value}),[]);
});

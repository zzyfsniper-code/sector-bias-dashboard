import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { Miniflare, convertV4MiniflareOptions } from 'miniflare';

const config = readFileSync(new URL('./wrangler.toml', import.meta.url), 'utf8');
const previous = { id: 1, status: 'completed', conclusion: 'success',
  created_at: '2026-10-15T00:25:00Z', updated_at: '2026-10-15T00:26:00Z' };
const stamp = '2026-10-15T15:17:00+08:00';
let runs, listStatus, dispatchStatus, calls;
const runtime = new Miniflare(convertV4MiniflareOptions({
  compatibilityDate: config.match(/compatibility_date = "([^"]+)"/)[1],
  compatibilityFlags: [],
  bindings: { GITHUB_TOKEN: 'test-only' },
  modules: [
    { type: 'ESModule', path: fileURLToPath(new URL('./runtime-harness.mjs', import.meta.url)),
      contents: `import { checkAndTrigger } from './worker.mjs';
        export default { async fetch(request, env) {
          try { return Response.json(await checkAndTrigger(env, new Date('2026-10-15T15:30:00+08:00'))); }
          catch (error) { return Response.json({ error: error.message }, { status: 500 }); }
        } };` },
    { type: 'ESModule', path: fileURLToPath(new URL('./worker.mjs', import.meta.url)),
      contents: readFileSync(new URL('./worker.mjs', import.meta.url), 'utf8') }
  ],
  // All outbound requests terminate here: no production API or credential is used.
  outboundService: async request => {
    calls.push({ url: request.url, method: request.method });
    if (request.url.startsWith('https://api.github.com/')) {
      assert.equal(request.headers.get('Authorization'), 'Bearer test-only');
      if (request.method === 'POST') {
        assert.deepEqual(await request.json(), { ref: 'main' });
        return new Response(null, { status: dispatchStatus, headers: { Location: 'https://not-allowed.invalid/' } });
      }
      return Response.json({ workflow_runs: runs }, { status: listStatus, headers: { Location: 'https://not-allowed.invalid/' } });
    }
    assert.ok(request.url.startsWith('https://zzyfsniper-code.github.io/sector-bias-dashboard/earnings-gap/data/'));
    assert.equal(request.headers.get('Authorization'), null);
    return Response.json(request.url.includes('live.json') ? { version: 'test', updated_at: stamp }
      : { version: 'test', status: 'PASS', source_status: 'PASS', source_asof: '2026-10-15',
        financial_asof: '2026-10-15', data_updated_at: stamp, counts: { pending: 0 },
        attempt: { status: 'success', run_id: '1' } });
  }
}));
after(() => runtime.dispose());

async function check(options = {}) {
  runs = options.runs ?? [previous];
  listStatus = options.listStatus ?? 200;
  dispatchStatus = options.dispatchStatus ?? 204;
  calls = [];
  const response = await runtime.dispatchFetch('http://localhost/');
  return { status: response.status, body: await response.json() };
}

test('workerd performs native fetch and skips a fresh close publication', async () => {
  assert.deepEqual(await check(), { status: 200, body: { status: 'fresh', phase: 'close', run_id: 1 } });
  assert.equal(calls.length, 3);
});

test('workerd sends exactly one dispatch for a failed publication', async () => {
  assert.equal((await check({ runs: [{ ...previous, conclusion: 'failure' }] })).body.status, 'dispatched');
  assert.equal(calls.filter(c => c.method === 'POST').length, 1);
});

test('workerd prevents duplicate dispatch while a task is active', async () => {
  assert.equal((await check({ runs: [{ ...previous, status: 'queued' }] })).body.status, 'active');
  assert.equal(calls.length, 1);
});

test('workerd rejects GitHub redirects and authentication failures without dispatch', async () => {
  for (const status of [301, 302, 307, 308, 401, 403]) {
    const result = await check({ listStatus: status });
    assert.equal(result.status, 500);
    assert.match(result.body.error, new RegExp('HTTP ' + status));
    assert.equal(calls.length, 1);
  }
});

test('workerd refuses dispatch redirects without following or retrying them', async () => {
  const result = await check({ runs: [], dispatchStatus: 307 });
  assert.equal(result.status, 500);
  assert.match(result.body.error, /Workflow dispatch HTTP 307/);
  assert.equal(calls.filter(c => c.method === 'POST').length, 1);
  assert.ok(calls.every(c => !c.url.includes('not-allowed.invalid')));
});

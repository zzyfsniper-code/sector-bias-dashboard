import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import worker, { checkAndTrigger, phaseAt } from './worker.mjs';

const now = new Date('2026-10-15T08:40:00+08:00');
const previous = { id: 1, status: 'completed', conclusion: 'success', created_at: '2026-10-14T00:25:00Z', updated_at: '2026-10-14T00:26:00Z' };
const freshRun = { ...previous, id: 2, created_at: '2026-10-15T00:25:00Z', updated_at: '2026-10-15T00:26:00Z' };
const live = { version: 'test', updated_at: '2026-10-15T08:26:00+08:00' };
const monitor = { version: 'test', status: 'PASS', source_status: 'PASS', source_asof: '2026-10-15', financial_asof: '2026-10-15',
  data_updated_at: live.updated_at, counts: { pending: 0 }, attempt: { status: 'success', run_id: '2' } };

function mock({ runs = [previous], data = live, status = monitor, pagesFail = false, listFail = false, dispatchStatus = 204, timeout = false } = {}) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    if (url.includes('api.github.com')) {
      assert.equal(options.headers.Authorization, 'Bearer test-only');
      assert.equal(options.redirect, 'manual');
      if (url.includes('/runs?')) return new Response(JSON.stringify({ workflow_runs: runs }), { status: listFail ? 403 : 200 });
      assert.equal(url, 'https://api.github.com/repos/zzyfsniper-code/sector-bias-dashboard/actions/workflows/earnings-gap-data.yml/dispatches');
      assert.equal(options.method, 'POST');
      assert.deepEqual(JSON.parse(options.body), { ref: 'main' });
      if (timeout) throw Error('test-only must not leak');
      return new Response(null, { status: dispatchStatus });
    }
    assert.equal(options.headers, undefined);
    assert.equal(options.redirect, 'manual');
    if (pagesFail) return new Response(null, { status: 503 });
    return new Response(JSON.stringify(url.includes('live.json') ? data : status));
  };
  return { calls, fetcher, posts: () => calls.filter(c => c.options.method === 'POST') };
}

const run = (m, time = now) => checkAndTrigger({ GITHUB_TOKEN: 'test-only' }, time, m.fetcher);

test('stale snapshot dispatches exactly once to the fixed workflow', async () => {
  const m = mock();
  assert.equal((await run(m)).status, 'dispatched');
  assert.equal(m.posts().length, 1);
});
test('matched fresh publication skips dispatch', async () => {
  const m = mock({ runs: [freshRun] });
  assert.equal((await run(m)).status, 'fresh');
  assert.equal(m.posts().length, 0);
});
test('queued, running or waiting jobs prevent another dispatch', async () => {
  for (const status of ['queued', 'in_progress', 'waiting', 'pending', 'requested']) {
    const m = mock({ runs: [{ ...freshRun, status }] });
    assert.equal((await run(m)).status, 'active');
    assert.equal(m.calls.length, 1);
  }
});
test('a recent completed job gets time for Pages propagation', async () => {
  const m = mock({ runs: [{ ...freshRun, updated_at: '2026-10-15T00:38:00Z' }], pagesFail: true });
  assert.equal((await run(m)).status, 'cooldown');
  assert.equal(m.posts().length, 0);
});
test('morning freshness does not satisfy close archival', async () => {
  const m = mock({ runs: [freshRun] });
  assert.equal((await run(m, new Date('2026-10-15T15:20:00+08:00'))).status, 'dispatched');
});
test('close publication can satisfy the afternoon check', async () => {
  const updated_at = '2026-10-15T15:17:00+08:00';
  const m = mock({ runs: [freshRun], data: { ...live, updated_at }, status: { ...monitor, data_updated_at: updated_at } });
  assert.equal((await run(m, new Date('2026-10-15T15:20:00+08:00'))).status, 'fresh');
});
test('partial, failed, unsynchronized or future snapshots are not fresh', async () => {
  for (const change of [
    { status: 'PARTIAL' }, { status: 'FAILED' }, { source_status: 'FAILED' },
    { source_asof: '2026-10-14' }, { financial_asof: '2026-10-14' }, { counts: { pending: 1 } },
    { version: 'other' }, { data_updated_at: 'invalid' }, { data_updated_at: '2026-10-15T09:00:00+08:00' },
    { attempt: { status: 'success', run_id: '3' } }, { attempt: { status: 'failed', run_id: '2' } }
  ]) {
    const m = mock({ runs: [freshRun], status: { ...monitor, ...change } });
    assert.equal((await run(m)).status, 'dispatched');
    assert.equal(m.posts().length, 1);
  }
  const m = mock({ runs: [freshRun], data: { ...live, updated_at: 'older' } });
  assert.equal((await run(m)).status, 'dispatched');
});
test('a failed latest job can recover even if an older publication looks fresh', async () => {
  const m = mock({ runs: [{ ...freshRun, conclusion: 'failure' }] });
  assert.equal((await run(m)).status, 'dispatched');
});
test('Pages failure allows bounded recovery, GitHub read failure does not dispatch', async () => {
  const pages = mock({ pagesFail: true });
  assert.equal((await run(pages)).status, 'dispatched');
  const github = mock({ listFail: true });
  await assert.rejects(run(github), /HTTP 403/);
  assert.equal(github.posts().length, 0);
});
test('invalid workflow response fails closed; an empty valid list can dispatch', async () => {
  const invalid = mock({ runs: [{ status: 'completed' }] });
  await assert.rejects(run(invalid), /Invalid workflow run list/);
  assert.equal(invalid.posts().length, 0);
  assert.equal((await run(mock({ runs: [] }))).status, 'dispatched');
});
test('dispatch authentication failure is reported without retry', async () => {
  const m = mock({ dispatchStatus: 401 });
  await assert.rejects(run(m), /Workflow dispatch HTTP 401/);
  assert.equal(m.posts().length, 1);
});
test('ambiguous POST timeout never replays within the invocation or leaks credentials', async () => {
  const m = mock({ timeout: true });
  await assert.rejects(run(m), e => !e.message.includes('test-only') && e.message.includes('no immediate retry'));
  assert.equal(m.posts().length, 1);
  const after = mock({ runs: [{ ...freshRun, status: 'queued' }] });
  assert.equal((await run(after)).status, 'active');
  assert.equal(after.posts().length, 0);
});
test('missing secret performs no network requests', async () => {
  const m = mock();
  await assert.rejects(checkAndTrigger({}, now, m.fetcher), /secret is missing/);
  assert.equal(m.calls.length, 0);
});
test('weekends and times outside the bounded check windows perform no requests', async () => {
  for (const time of ['2026-10-17T08:40:00+08:00', '2026-10-18T15:30:00+08:00',
    '2026-10-15T08:29:00+08:00', '2026-10-15T09:00:00+08:00',
    '2026-10-15T15:19:00+08:00', '2026-10-15T15:50:00+08:00']) {
    const m = mock();
    assert.equal((await run(m, new Date(time))).status, 'outside_window');
    assert.equal(m.calls.length, 0);
  }
});
test('scheduled handler disables platform retries and rejects configuration failure', async () => {
  let disabled = false;
  const original = console.error;
  console.error = () => {};
  try {
    // Missing credentials are checked only in a valid clock window.
    const RealDate = globalThis.Date;
    globalThis.Date = class extends RealDate { constructor(...args) { super(...(args.length ? args : [now.getTime()])); } };
    try {
      await assert.rejects(worker.scheduled({ noRetry: () => { disabled = true; } }, {}), /secret is missing/);
    } finally { globalThis.Date = RealDate; }
  } finally { console.error = original; }
  assert.equal(disabled, true);
});
test('config uses unambiguous Cloudflare weekday names and both Beijing windows', () => {
  const config = readFileSync(new URL('./wrangler.toml', import.meta.url), 'utf8');
  assert.ok(config.includes('"30,40,50 0 * * MON-FRI"'));
  assert.ok(config.includes('"20,30,40 7 * * MON-FRI"'));
  assert.ok(config.includes('workers_dev = false'));
  assert.equal(phaseAt(new Date('2026-10-15T08:30:00+08:00')).floor, Date.parse('2026-10-15T08:25:00+08:00'));
  assert.equal(phaseAt(new Date('2026-10-15T15:40:00+08:00')).phase, 'close');
});

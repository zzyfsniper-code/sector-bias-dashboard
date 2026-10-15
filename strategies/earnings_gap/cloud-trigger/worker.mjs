const WORKFLOW = 'https://api.github.com/repos/zzyfsniper-code/sector-bias-dashboard/actions/workflows/earnings-gap-data.yml';
const DATA = 'https://zzyfsniper-code.github.io/sector-bias-dashboard/earnings-gap/data/';

export function phaseAt(now) {
  const china = new Date(now.getTime() + 8 * 3600000).toISOString();
  const day = china.slice(0, 10), weekday = new Date(day).getUTCDay();
  const minutes = Number(china.slice(11, 13)) * 60 + Number(china.slice(14, 16));
  if (weekday === 0 || weekday === 6) return null;
  const phase = minutes >= 510 && minutes < 540 ? 'morning'
    : minutes >= 920 && minutes < 950 ? 'close' : null;
  return phase && { day, phase, floor: Date.parse(day + (phase === 'morning' ? 'T08:25:00+08:00' : 'T15:15:00+08:00')) };
}

async function request(fetcher, url, options = {}) {
  try {
    return await fetcher(url, { ...options, redirect: 'error', signal: AbortSignal.timeout(15000) });
  } catch {
    throw Error('Request failed or timed out; no immediate retry');
  }
}

async function readJson(fetcher, url, options) {
  const response = await request(fetcher, url, options);
  if (!response.ok) throw Error('Snapshot or workflow list HTTP ' + response.status);
  try { return await response.json(); } catch { throw Error('Invalid JSON response'); }
}

export async function checkAndTrigger(env, now = new Date(), fetcher = fetch) {
  const phase = phaseAt(now);
  if (!phase) return { status: 'outside_window' };
  if (!env.GITHUB_TOKEN) throw Error('GITHUB_TOKEN secret is missing');
  const headers = { Authorization: 'Bearer ' + env.GITHUB_TOKEN, Accept: 'application/vnd.github+json',
    'User-Agent': 'earnings-gap-cloud-trigger', 'X-GitHub-Api-Version': '2022-11-28' };
  const { workflow_runs: runs } = await readJson(fetcher, WORKFLOW + '/runs?branch=main&per_page=20', { headers });
  if (!Array.isArray(runs) || runs.some(r => !r.id || !r.status || !Number.isFinite(Date.parse(r.created_at)))) {
    throw Error('Invalid workflow run list');
  }
  const active = runs.find(r => r.status !== 'completed');
  if (active) return { status: 'active', phase: phase.phase, run_id: active.id };
  const latest = runs[0];
  let fresh = false, snapshot = 'unavailable';
  try {
    // Credentials are sent only to the fixed GitHub API, never to Pages.
    const [live, monitor] = await Promise.all(['live.json', 'monitor.json'].map(name =>
      readJson(fetcher, DATA + name + '?t=' + now.getTime(), { cache: 'no-store' })));
    snapshot = monitor.status || 'invalid';
    const timestamp = Date.parse(monitor.data_updated_at);
    fresh = monitor.status === 'PASS' && monitor.source_status === 'PASS'
      && monitor.financial_asof === phase.day && monitor.source_asof === phase.day
      && timestamp >= phase.floor && timestamp <= now.getTime()
      && monitor.version && monitor.version === live.version
      && monitor.data_updated_at === live.updated_at && monitor.counts?.pending === 0
      && monitor.attempt?.status === 'success' && latest?.conclusion === 'success'
      && String(monitor.attempt.run_id) === String(latest.id);
  } catch {
    // A failed Pages read cannot be treated as a successful publication.
  }
  if (fresh) return { status: 'fresh', phase: phase.phase, run_id: latest.id };
  const completedAt = Date.parse(latest?.updated_at || latest?.created_at);
  if (completedAt <= now.getTime() && now.getTime() - completedAt < 5 * 60000) {
    return { status: 'cooldown', phase: phase.phase, run_id: latest.id };
  }
  const response = await request(fetcher, WORKFLOW + '/dispatches', {
    method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ ref: 'main' })
  });
  if (response.status !== 204) throw Error('Workflow dispatch HTTP ' + response.status);
  return { status: 'dispatched', day: phase.day, phase: phase.phase, snapshot };
}

export default {
  async scheduled(controller, env) {
    // A timed-out POST may have succeeded. The next cron checks GitHub before another dispatch.
    controller.noRetry();
    try {
      const result = await checkAndTrigger(env);
      console.log(JSON.stringify(result));
    } catch (error) {
      console.error(JSON.stringify({ status: 'error', message: error.message }));
      throw error;
    }
  }
};

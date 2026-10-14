"""Scoped GitHub commit + Pages verification; never stages the user's worktree."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import requests

ROOT = Path(__file__).resolve().parents[2]
API = 'https://api.github.com/repos/zzyfsniper-code/sector-bias-dashboard'
SITE = 'https://zzyfsniper-code.github.io/sector-bias-dashboard/'
NIGHTLY = ['tri-momentum-vol-control/data/live.json', 'tri-momentum-vol-control/data/history.json',
           'tri-momentum-vol-control/data/rebalances.csv']


def token():
    value = os.environ.get('GITHUB_TOKEN')
    if value:
        return value
    p = subprocess.run(['git','credential','fill'], input='protocol=https\nhost=github.com\n\n',
        capture_output=True, text=True, cwd=ROOT, timeout=15,
        env={**os.environ, 'GIT_TERMINAL_PROMPT':'0', 'GCM_INTERACTIVE':'never'})
    values = dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)
    if p.returncode != 0 or not values.get('password'):
        raise RuntimeError('GitHub credential unavailable; no credential is saved by this updater')
    return values['password']


def release_paths():
    result = ['strategies/index.html','strategies/app.js','earnings_gap.html',
              'growth-value-five-dim/index.html','csi500-flow-leverage/index.html','all-weather-risk-parity/index.html']
    for directory in ['tri-momentum-vol-control','strategies/tri_momentum_vol_control']:
        for p in sorted((ROOT/directory).rglob('*')):
            rel = p.relative_to(ROOT).as_posix()
            if p.is_file() and not any(part in ['__pycache__','logs','data'] for part in p.relative_to(ROOT/directory).parts[:-1]):
                result.append(rel)
            elif p.is_file() and directory=='tri-momentum-vol-control' and p.parent.name=='data':
                result.append(rel)
    return sorted(set(result))


def publish(paths, message, release=False):
    allowed = release_paths() if release else NIGHTLY
    if not paths or any(p not in allowed for p in paths):
        raise ValueError('Publish scope rejected')
    payloads = {p:(ROOT/p).read_bytes() for p in paths}
    headers = {'Authorization':'Bearer '+token(), 'Accept':'application/vnd.github+json',
               'X-GitHub-Api-Version':'2022-11-28','User-Agent':'tri-momentum-nightly'}
    session = requests.Session()
    session.trust_env = False
    session.headers.update(headers)

    def api(method, endpoint, **kwargs):
        response = session.request(method, API+endpoint, timeout=60, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f'GitHub {method} {endpoint}: HTTP {response.status_code}')
        return response.json()

    parent = api('GET','/git/ref/heads/main')['object']['sha']
    commit = api('GET','/git/commits/'+parent)
    tree = api('GET','/git/trees/'+commit['tree']['sha']+'?recursive=1')
    if tree.get('truncated'):
        raise RuntimeError('Remote tree truncated; refusing to publish')
    remote = {item['path']:item for item in tree['tree']}
    changed = []
    for p, data in payloads.items():
        blob_sha = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if remote.get(p,{}).get('sha') == blob_sha:
            continue
        # Existing shared files may have other owners. Compare with the local base first.
        if release and not p.startswith(('tri-momentum-vol-control/','strategies/tri_momentum_vol_control/')):
            base = subprocess.run(['git','show','HEAD:'+p], cwd=ROOT, capture_output=True, check=True).stdout
            if p in remote:
                actual = base64.b64decode(api('GET','/git/blobs/'+remote[p]['sha'])['content'])
                if actual.replace(b'\r\n',b'\n') != base.replace(b'\r\n',b'\n'):
                    raise RuntimeError('Remote shared file changed; merge explicitly before publishing: '+p)
        changed.append(p)
    if not changed:
        return dict(status='UNCHANGED',commit=parent)

    def blob(p):
        # Each worker has its own request, not the shared Session's mutable state.
        worker = requests.Session()
        worker.trust_env = False
        response = worker.post(API+'/git/blobs', headers=headers,
            json={'content':base64.b64encode(payloads[p]).decode('ascii'),'encoding':'base64'}, timeout=60)
        if response.status_code >= 400:
            raise RuntimeError('GitHub blob upload failed: '+p+' HTTP '+str(response.status_code))
        return dict(path=p, mode='100644', type='blob', sha=response.json()['sha'])
    with ThreadPoolExecutor(max_workers=3) as pool:
        entries = list(pool.map(blob, changed))
    new_tree = api('POST','/git/trees',json={'base_tree':commit['tree']['sha'],'tree':entries})
    new_commit = api('POST','/git/commits',json={'message':message,'tree':new_tree['sha'],'parents':[parent]})
    sha = new_commit['sha']
    # force=false rejects concurrent branch updates. No overwrite/retry of another publisher.
    api('PATCH','/git/refs/heads/main',json={'sha':sha,'force':False})
    deadline = time.monotonic()+720
    built = False
    while time.monotonic() < deadline:
        builds = api('GET','/pages/builds?per_page=20')
        matching = [b for b in builds if b.get('commit') == sha]
        if matching and matching[0]['status']=='built':
            built = True
            break
        if matching and matching[0]['status']=='errored':
            raise RuntimeError('Pages build errored for '+sha)
        time.sleep(15)
    if not built:
        raise RuntimeError('Pages build timeout for '+sha)
    # CDN may lag a completed build. Verify the complete changed public surface.
    public = [p for p in paths if p.startswith('tri-momentum-vol-control/')]
    if release:
        public += ['strategies/index.html','strategies/app.js','earnings_gap.html']
    pending = set(public)
    verify_until = time.monotonic()+180
    while pending and time.monotonic()<verify_until:
        for p in list(pending):
            r = session.get(SITE+p+'?verify='+sha, timeout=30,
                headers={'Authorization':None})
            if r.status_code==200 and r.content.replace(b'\r\n',b'\n')==payloads[p].replace(b'\r\n',b'\n'):
                pending.remove(p)
        if pending:
            time.sleep(10)
    if pending:
        raise RuntimeError('Online assets not matched: '+', '.join(sorted(pending)))
    result = dict(status='PASS',commit=sha,parent=parent,pages_build='built',online_assets_verified=len(public),
                  files=changed,url=SITE+'tri-momentum-vol-control/')
    log = Path(__file__).resolve().parent/'logs'
    log.mkdir(exist_ok=True)
    (log/'publish_latest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',action='store_true');p.add_argument('--dry-run',action='store_true');a=p.parse_args()
    paths=release_paths() if a.release else NIGHTLY
    print(json.dumps({'status':'DRY_RUN','files':paths} if a.dry_run else publish(paths,'Launch 三元动量波控策略 V1.0' if a.release else 'Update three-asset strategy data',a.release),ensure_ascii=False))

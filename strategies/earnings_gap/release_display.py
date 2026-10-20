"""Scoped release with a remote-vs-local-base preflight; no trading data overwritten."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import requests
from publish import ROOT, API, publish

FILES = ['earnings_gap.html','.github/workflows/earnings-gap-data.yml',
    'earnings-gap/app.js','earnings-gap/monitor.js','earnings-gap/style.css','earnings-gap/context.js',
    'earnings-gap/data/display_context.json','earnings-gap/data/display_cache.json'] + [
    'strategies/earnings_gap/'+name for name in ['display_context.py','test_display_context.py',
    'test_display_browser.py','test_position_browser.py','test_calendar_browser.py','prepare_display_history.py',
    'DISPLAY_CONTEXT.md','publish.py','release_display.py']]


def main():
    session = requests.Session()
    session.headers.update(Authorization='Bearer '+os.environ['GITHUB_TOKEN'], Accept='application/vnd.github+json')
    def get(path):
        response=session.get(API+path,timeout=30)
        response.raise_for_status()
        return response.json()
    parent=get('/git/ref/heads/main')['object']['sha']
    tree=get('/git/trees/'+parent+'?recursive=1')
    assert not tree.get('truncated')
    remote={r['path']:r['sha'] for r in tree['tree']}
    for name in FILES:
        old=subprocess.run(['git','show','HEAD:'+name],cwd=ROOT,capture_output=True)
        if old.returncode == 0:
            lf=old.stdout.replace(b'\r\n',b'\n')
            variants=[old.stdout,lf,lf.replace(b'\n',b'\r\n')]
            expected={hashlib.sha1(f'blob {len(value)}\0'.encode()+value).hexdigest() for value in variants}
        else:
            expected={None}
        if remote.get(name) not in expected:
            raise RuntimeError('Remote file differs from reviewed base: '+name)
    # These files must remain outside the write list.
    assert not {'earnings-gap/data/live.json','earnings-gap/data/history.json',
                'strategies/earnings_gap/strategy_core.py','strategies/earnings_gap/update_data.py'} & set(FILES)
    context=json.loads((ROOT/'earnings-gap/data/display_context.json').read_text('utf-8'))
    assert context['version']==1 and len(context['features'])>=3003 and context['seasons']
    proof=dict(status='PREFLIGHT_PASS',parent=parent,files=FILES,remote_base_verified=True,
               trading_files_untouched=True,history_rows=3003)
    (ROOT/'strategies/earnings_gap/logs/display-release-preflight.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),'utf-8')
    publish(scoped_files=FILES,expected_parent=parent)


if __name__=='__main__':
    main()

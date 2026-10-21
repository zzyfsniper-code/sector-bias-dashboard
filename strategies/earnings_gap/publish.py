"""Scoped GitHub publication, preserving the current remote tree and Pages mode."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import os
import requests

ROOT=Path(__file__).resolve().parents[2]
API='https://api.github.com/repos/zzyfsniper-code/sector-bias-dashboard'


def publish(data_only=False,monitor_only=False,scoped_files=None,expected_parent=None):
    files=['earnings-gap/data/monitor.json'] if monitor_only else ['earnings-gap/data/live.json','earnings-gap/data/monitor.json'] if data_only else ['earnings_gap.html','strategies/index.html','strategies/app.js',
        '.github/workflows/earnings-gap-data.yml']+[p.relative_to(ROOT).as_posix() for p in (ROOT/'earnings-gap').rglob('*') if p.is_file()]+[
        'strategies/earnings_gap/'+n for n in ['strategy_core.py','volume_data.py','test_volume.py','test_volume.js','update_data.py','monitoring.py','financial_sources.py','profit_reasons.py','publish.py','display_context.py','test_display_context.py','test_strategy.py','test_signal.js','test_monitoring.py','test_profit_reasons.py','test_monitor.js','test_financial_sources.py']]
    if data_only:
        files += [name for name in ['earnings-gap/data/display_context.json','earnings-gap/data/display_cache.json','earnings-gap/data/volume_model.json','earnings-gap/data/volume_cache.json'] if (ROOT/name).exists()]
    if scoped_files:
        if any(not (name=='earnings_gap.html' or name=='.github/workflows/earnings-gap-data.yml' or name.startswith(('earnings-gap/','strategies/earnings_gap/'))) or '..' in Path(name).parts for name in scoped_files):
            raise RuntimeError('Publication outside earnings gap scope')
        files=scoped_files
    files=sorted(set(files));token=os.environ.get('GITHUB_TOKEN')
    if not token:raise RuntimeError('GITHUB_TOKEN is missing; nothing published')
    session=requests.Session();session.headers.update({'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'earnings-gap-publisher'})
    def call(method,path,**kwargs):
        r=session.request(method,API+path,timeout=40,**kwargs)
        if r.status_code>=400:raise RuntimeError(f'GitHub {method} {path}: {r.status_code} '+str(r.json().get('message','')))
        return r.json() if r.content else {}
    pages=call('GET','/pages')
    if pages.get('source')!={'branch':'main','path':'/'}:raise RuntimeError('Unexpected Pages source; no publication')
    parent=call('GET','/git/ref/heads/main')['object']['sha'];commit=call('GET','/git/commits/'+parent)
    if expected_parent and parent!=expected_parent:raise RuntimeError('Remote changed since preflight; no publication')
    if not data_only and not monitor_only and not scoped_files:
        current={x['path']:x['sha'] for x in call('GET','/git/trees/'+commit['tree']['sha'],params={'recursive':1})['tree']}
        for name in ['strategies/index.html','strategies/app.js']:
            baseline=ROOT/'strategies/earnings_gap/logs'/('remote-'+Path(name).name)
            if baseline.exists():
                b=baseline.read_bytes();expected=hashlib.sha1(f'blob {len(b)}\0'.encode()+b).hexdigest()
                prior=ROOT/'strategies/earnings_gap/logs/publication.json'
                accepted={expected}
                if prior.exists():
                    previous=json.loads(prior.read_text('utf-8'))
                    local=(ROOT/name).read_bytes()
                    if previous.get('files',{}).get(name)==hashlib.sha256(local).hexdigest():
                        accepted.add(hashlib.sha1(f'blob {len(local)}\0'.encode()+local).hexdigest())
                if current.get(name) not in accepted:raise RuntimeError('Strategy overview changed remotely; review required before overwriting '+name)
    tree=[];hashes={}
    for name in files:
        blob=(ROOT/name).read_bytes();hashes[name]=hashlib.sha256(blob).hexdigest()
        sha=call('POST','/git/blobs',json={'content':base64.b64encode(blob).decode(),'encoding':'base64'})['sha']
        tree.append({'path':name,'mode':'100644','type':'blob','sha':sha})
    newtree=call('POST','/git/trees',json={'base_tree':commit['tree']['sha'],'tree':tree})['sha']
    child=call('POST','/git/commits',json={'message':'Publish earnings gap update failure status' if monitor_only else 'Update earnings gap strategy data and monitoring' if data_only else 'Publish frozen earnings gap strategy with live public quotes','tree':newtree,'parents':[parent]})['sha']
    # No force updates or stale parent retries: preserve concurrent remote work.
    call('PATCH','/git/refs/heads/main',json={'sha':child,'force':False})
    build=call('POST','/pages/builds') if pages['build_type']=='legacy' else {}
    result=dict(status='PUSHED',commit=child,parent=parent,page_url=pages['html_url']+'earnings_gap.html',
                pages_mode=pages['build_type'],build_status=build.get('status'),files=hashes)
    log=ROOT/'strategies/earnings_gap/logs';log.mkdir(exist_ok=True)
    (log/'publication.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();mode=p.add_mutually_exclusive_group();mode.add_argument('--data-only',action='store_true');mode.add_argument('--monitor-only',action='store_true');mode.add_argument('--files',nargs='+');p.add_argument('--expected-parent');a=p.parse_args();publish(a.data_only,a.monitor_only,a.files,a.expected_parent)

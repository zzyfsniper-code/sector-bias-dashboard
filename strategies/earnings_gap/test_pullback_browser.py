"""Isolated browser fixtures for the new entry rule; no persisted ledger writes."""
from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
from pathlib import Path
import sys
from threading import Thread
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
LOG=Path(__file__).resolve().parent/'logs'


def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    url=sys.argv[1] if len(sys.argv)>1 else f'http://127.0.0.1:{server.server_port}/earnings_gap.html'
    live=json.loads((ROOT/'earnings-gap/data/live.json').read_text('utf-8'))
    holdings=[r for r in live['records'] if r.get('entry_date')]
    day='2026-10-23';stamp=day+'T08:30:00+08:00'
    candidate=dict(id='pullback-fixture',ts_code='600000.SH',name='冲高回落测试',origin='forward',ann_date=day,reaction_date=day,
                   end_date='2026-09-30',report_period='Q3',quarter_profit=100000000,quarter_yoy=50,list_date='2000-01-01',
                   status='等待开盘',volume_previous_shares=1000,volume_previous_date='2026-10-22',volume_reference_day=day)
    live.update(financial_asof=day,updated_at=stamp,status='PASS',issues=[],records=holdings+[candidate])
    report=dict(candidate,complete=True,financial_eligible=True,result='等待开盘',reason='进入行情筛选',url=None)
    monitor=dict(version=live['version'],status='PASS',source_status='PASS',financial_asof=day,data_updated_at=stamp,
                 window_start=day,checked_at=stamp,reports=[report],counts=dict(announcements=1,processed=1,pending=0,companies=1,financial_candidates=1))
    fixture={'last':102.99,'high':108,'time':'145000'};errors=[]
    LOG.mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1080))
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.clock.set_fixed_time(datetime.fromisoformat(day+'T14:50:10+08:00'))
            page.route('**/earnings-gap/data/live.json?*',lambda route:route.fulfill(json=live))
            page.route('**/earnings-gap/data/monitor.json?*',lambda route:route.fulfill(json=monitor))
            page.route('https://api.github.com/**',lambda route:route.fulfill(json={'workflow_runs':[dict(id=1,status='completed',conclusion='success',created_at=day+'T00:25:00Z',event='schedule')]}))
            def quote(route):
                lines=[]
                for symbol in route.request.url.split('q=')[1].split('&')[0].split(','):
                    fields=['']*40
                    selected=symbol=='sh600000'
                    held=next((r for r in holdings if symbol==r['ts_code'][-2:].lower()+r['ts_code'][:6]),None)
                    previous=100 if not held else held.get('basis_last_close') or held['entry_price']
                    last=fixture['last'] if selected else previous
                    for i,v in {1:'冲高回落测试' if selected else '行情测试',3:last,4:previous,5:104 if selected else previous,
                                6:15,30:'20261023'+fixture['time'],33:fixture['high'] if selected else last*1.001,34:101 if selected else last*.999}.items():fields[i]=str(v)
                    lines.append('v_'+symbol+'="'+'~'.join(fields)+'";')
                route.fulfill(body='\n'.join(lines).encode('gbk'),headers={'Access-Control-Allow-Origin':'*'})
            page.route('https://qt.gtimg.cn/**',quote)
            page.goto(url,wait_until='domcontentloaded')
            page.wait_for_function("document.querySelector('#dailyCandidates .current-state').textContent.includes('最高 +8.00%')")
            row=page.locator('#dailyCandidates tr').filter(has_text='600000.SH')
            assert row.locator('.current-state .pill').inner_text()=='冲高回落'
            assert 'selected' not in (row.get_attribute('class') or '')
            assert page.locator('#tableBody tr').count()==len(holdings)
            for r in holdings:assert page.locator('#tableBody tr').filter(has_text=r['ts_code']).count()==1
            page.locator('.daily-list').first.screenshot(path=str(LOG/'pullback-candidate.png'))
            page.locator('#detailsButton').click()
            assert '2026-10-23' in page.locator('#rulesPanel').inner_text()
            assert '收盘涨幅严格<3%' in page.locator('#rulesPanel').inner_text()
            page.locator('[data-tab=backtest]').click()
            page.wait_for_function("document.querySelector('#pullbackResearch').textContent.includes('1958')")
            assert '未重算新规则组合净值' in page.locator('#pullbackResearch').inner_text()
            page.locator('#detailsDialog').screenshot(path=str(LOG/'pullback-details.png'))
            page.locator('#closeDetails').click()
            fixture['last']=103
            page.locator('#refreshButton').click()
            page.wait_for_function("document.querySelector('#dailyCandidates .pill').textContent==='当前符合'")
            assert page.locator('#tableBody tr').count()==len(holdings)
            # A new data version must load independently of the unchanged backtest.
            live['version']=monitor['version']='eg-20261023-v5-pullback83'
            page.reload(wait_until='domcontentloaded')
            page.wait_for_function("document.querySelector('#dailyCandidates .pill').textContent==='当前符合'")
            fixture.update(last=102.99,time='150000')
            page.clock.set_fixed_time(datetime.fromisoformat(day+'T15:01:00+08:00'))
            page.locator('#refreshButton').click()
            page.wait_for_function("document.querySelector('#dailyCandidates .current-state').textContent.includes('收盘 2.99%')")
            assert page.locator('#dailyMarket').inner_text().strip().startswith('0')
            assert page.locator('#tableBody tr').count()==len(holdings)
            page.set_viewport_size(dict(width=390,height=844))
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(LOG/'pullback-mobile.png'),full_page=True)
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown();server.server_close()
    result=dict(status='PASS',url=url,existing_entries=len(holdings),checks=['rejection reason','intraday recovery','close exclusion','legacy and new snapshots','unchanged existing rows','rule and research details','mobile layout'],errors=errors)
    (LOG/'pullback-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()

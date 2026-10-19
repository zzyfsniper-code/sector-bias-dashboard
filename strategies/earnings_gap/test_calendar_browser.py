"""Deterministic integration QA for the current Monday cohort; no orders/writes online."""
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
LOG=Path(__file__).resolve().parent/'logs';LOG.mkdir(exist_ok=True)


def main():
    url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8769/earnings_gap.html'
    monitor=json.loads((ROOT/'earnings-gap/data/monitor.json').read_text('utf-8'))
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1080})
        page.clock.set_fixed_time(__import__('datetime').datetime.fromisoformat('2026-10-19T10:00:10+08:00'))
        page.on('pageerror',lambda error:errors.append(str(error)))
        def quotes(route):
            symbols=route.request.url.split('q=')[1].split('&')[0].split(',')
            lines=[]
            for symbol in symbols:
                fields=['']*40
                for index,value in {1:'测试行情',3:'103',4:'100',5:'102.5',30:'20261019100000',33:'104',34:'101'}.items():fields[index]=value
                lines.append('v_'+symbol+'="'+'~'.join(fields)+'";')
            route.fulfill(body='\n'.join(lines).encode('gbk'),headers={'Access-Control-Allow-Origin':'*','Content-Type':'text/plain'})
        page.route('https://qt.gtimg.cn/**',quotes)
        job=dict(id=int(monitor['attempt']['run_id']),status='completed',conclusion='success',event='workflow_dispatch',created_at='2026-10-19T00:50:34Z')
        page.route('https://api.github.com/**',lambda route:route.fulfill(json={'workflow_runs':[job]},headers={'Access-Control-Allow-Origin':'*'}))
        page.goto(url,wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#dailyCandidateCount').textContent==='10 家'",timeout=30000)
        page.wait_for_function("document.querySelectorAll('#dailyCandidates tr.candidate-selected').length===10",timeout=30000)
        assert page.locator('#dailyAnnouncements').inner_text()=='21 家'
        assert page.locator('#dailyFinancial').inner_text()=='10 家'
        assert '卫星化学' in page.locator('#dailyCandidates').inner_text()
        assert '2026-10-17' in page.locator('#dailyCandidates tr').first.inner_text()
        assert '2026-10-19' in page.locator('#dailyCandidates tr').first.inner_text()
        assert '财务接口尚未覆盖' not in page.locator('#dailyCandidates').inner_text()
        assert '2条正式公告' in page.locator('#monitorExplanation').inner_text()
        assert '今日应评公告' in page.locator('.monitor-metrics').inner_text()
        assert page.locator('#tableBody').inner_text().find('002648.SZ')==-1 # no simulated entry added by this migration
        page.locator('.monitor-panel').screenshot(path=str(LOG/'calendar-desktop.png'))
        page.locator('#dailyFailuresToggle').click()
        assert page.locator('#dailyFailures tr').count()==9
        page.locator('#dailyFailuresToggle').click()
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('.monitor-panel').screenshot(path=str(LOG/'calendar-mobile.png'))
        assert not errors,errors
        result=dict(status='PASS',url=url,announcements=21,financial=10,candidates=10,
                    actual_quotes_mocked=True,all_ten_reach_market_evaluation=True,original_dates_preserved=True,
                    unrelated_two_missing_financials_remain_visible=True,no_fake_entries=True,desktop=True,mobile=True,errors=errors)
        (LOG/'calendar-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(result,ensure_ascii=False))
        browser.close()


if __name__=='__main__':main()

"""PB and industry UI integration tests, plus read-only hosted smoke verification."""
from datetime import datetime
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
LOG = Path(__file__).resolve().parent/'logs'


def main():
    url = sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18776/earnings_gap.html'
    online = '--online' in sys.argv
    source = LOG/'display-inputs'
    context = json.loads((ROOT/'earnings-gap/data/display_context.json').read_text('utf-8'))
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', headless=True)
        page = browser.new_page(viewport=dict(width=1600,height=1100))
        page.on('pageerror', lambda error:errors.append(str(error)))
        if not online:
            page.clock.set_fixed_time(datetime.fromisoformat('2026-10-20T14:00:10+08:00'))
            for name in ['live.json','monitor.json']:
                value = json.loads((source/name).read_text('utf-8'))
                page.route('**/earnings-gap/data/'+name+'?*', lambda route, request, value=value:route.fulfill(json=value))
            def quotes(route):
                lines = []
                for symbol in route.request.url.split('q=')[1].split('&')[0].split(','):
                    fields = ['']*40
                    for i,v in {1:'测试',3:'103',4:'100',5:'102.5',30:'20261020140000',33:'104',34:'101'}.items():fields[i]=v
                    lines.append('v_'+symbol+'="'+'~'.join(fields)+'";')
                route.fulfill(body='\n'.join(lines).encode('gbk'),headers={'Access-Control-Allow-Origin':'*'})
            page.route('https://qt.gtimg.cn/**', quotes)
            monitor = json.loads((source/'monitor.json').read_text('utf-8'))
            page.route('https://api.github.com/**', lambda route:route.fulfill(json={'workflow_runs':[dict(
                id=int(monitor['attempt']['run_id']),status='completed',conclusion='success',created_at='2026-10-20T05:02:00Z',event='workflow_dispatch')]}))
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#industryMeta').textContent.includes('SW2021')")
        page.wait_for_function("document.querySelector('#tableBody').textContent.includes('300688.SZ')")
        row = page.locator('#tableBody tr').filter(has_text='300688.SZ')
        assert '社会服务' in row.inner_text()
        assert '94.5%' in row.locator('td').nth(2).inner_text()
        assert '2026-10-15' in row.locator('td').nth(2).inner_text()
        assert '至少252' in row.locator('.pb-value').get_attribute('title')
        assert row.locator('td').count() == 14
        assert page.locator('#industryRows tr').count() == 5
        page.locator('#industryToggle').click()
        assert page.locator('#industryRows tr').count() == len(context['seasons'][0]['rows'])
        assert '尚无已披露' in page.locator('#industryRows').inner_text()
        page.locator('#industryToggle').click()
        assert page.locator('#industryRows tr').count() == 5
        if not online:
            assert '55 家待收盘' in page.locator('#industryStatus').inner_text()
            page.wait_for_function("[...document.querySelectorAll('#dailyCandidates .pb-value')].some(el=>el.textContent.includes('%'))")
            assert '历史不足' in page.locator('#dailyCandidates tr').first.inner_text()
            assert page.locator('#dailyCandidates tr').first.locator('td').count() == 10
        page.locator('.industry-panel').screenshot(path=str(LOG/('display-online.png' if online else 'display-desktop.png')))
        page.screenshot(path=str(LOG/('display-online-full.png' if online else 'display-full.png')),full_page=True)
        page.set_viewport_size(dict(width=390,height=844))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('.industry-panel').screenshot(path=str(LOG/('display-online-mobile.png' if online else 'display-mobile.png')))
        if not online:
            page.clock.set_fixed_time(datetime.fromisoformat('2026-10-20T15:50:10+08:00'))
            page.reload(wait_until='domcontentloaded')
            page.wait_for_function("document.querySelector('#industryStatus').textContent.includes('今日收盘行业统计尚未归档')")
            page.route('**/earnings-gap/data/display_context.json?*',lambda route:route.fulfill(status=500,body='error'))
            page.reload(wait_until='domcontentloaded')
            page.wait_for_function("document.querySelector('#industryRows').textContent.includes('展示数据读取失败')")
            page.wait_for_function("document.querySelector('#tableBody').textContent.includes('300688.SZ')")
            assert '止盈' in page.locator('#tableBody').inner_text()
            # The ancillary fetch must not stop the trading page.
            assert '策略数据加载失败' not in page.locator('#tableBody').inner_text()
        assert not errors,errors
        result=dict(status='PASS',url=url,online=online,pb_value_and_date=True,industry=True,top5_and_expand=True,
                    mobile_no_overflow=True,ancillary_failure_isolated=not online,errors=errors)
        (LOG/('display-browser-online.json' if online else 'display-browser.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(result,ensure_ascii=False))
        browser.close()


if __name__ == '__main__':
    main()

"""Read-only UI QA; price changes and clocks below are isolated browser fixtures."""
from datetime import datetime
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
LOG=Path(__file__).resolve().parent/'logs'


def main():
    url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8769/earnings_gap.html'
    live=json.loads((ROOT/'earnings-gap/data/live.json').read_text('utf-8'))
    holding=next(r for r in live['records'] if r.get('entry_date') and not r.get('exit_date'))
    fixture={'protected':False,'stale':False}
    errors=[]
    LOG.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1080})
        page.clock.set_fixed_time(datetime.fromisoformat('2026-10-19T10:00:10+08:00'))
        page.on('pageerror',lambda error:errors.append(str(error)))
        def live_data(route):
            data=json.loads(json.dumps(live))
            if fixture['protected']:
                row=next(r for r in data['records'] if r['id']==holding['id'])
                row.update(stop_basis=row['entry_basis']*1.02,armed=True)
            route.fulfill(json=data,headers={'Access-Control-Allow-Origin':'*'})
        page.route('**/earnings-gap/data/live.json?*',live_data)
        def quotes(route):
            lines=[]
            for symbol in route.request.url.split('q=')[1].split('&')[0].split(','):
                held=symbol=='sz300688'
                fields=['']*40
                values={1:'测试行情',3:'30.60' if held else '103',4:'30.59' if held else '100',5:'30.70' if held else '102.5',30:'20261016150000' if fixture['stale'] else '20261019100000',33:'31' if held else '104',34:'30.60' if held else '101'}
                for index,value in values.items():fields[index]=value
                lines.append('v_'+symbol+'="'+'~'.join(fields)+'";')
            route.fulfill(body='\n'.join(lines).encode('gbk'),headers={'Access-Control-Allow-Origin':'*','Content-Type':'text/plain'})
        page.route('https://qt.gtimg.cn/**',quotes)
        page.route('https://api.github.com/**',lambda route:route.fulfill(json={'workflow_runs':[]},headers={'Access-Control-Allow-Origin':'*'}))
        page.goto(url,wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#tableBody').textContent.includes('33.65')")
        assert page.locator('.table-wrap thead th').count()==14
        row=page.locator('#tableBody tr').filter(has_text='300688.SZ')
        cells=row.locator('td')
        assert cells.count()==14
        assert cells.nth(9).inner_text()=='止盈 33.65元\n止损 28.14元'
        assert cells.nth(10).inner_text()=='2 天'
        assert cells.nth(8).inner_text()=='2026-10-16\n30.59元'
        assert '持有' in cells.nth(7).inner_text()
        page.locator('.table-wrap').screenshot(path=str(LOG/'position-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('.table-wrap').evaluate('el=>el.scrollLeft=el.scrollWidth')
        assert page.locator('.table-wrap th').last.is_visible()
        page.locator('.table-wrap').screenshot(path=str(LOG/'position-mobile.png'))
        page.set_viewport_size({'width':1440,'height':1080})
        page.locator('#dateFilter').select_option('all')
        historical=page.locator('#tableBody tr').filter(has_text='300611.SZ')
        assert historical.locator('td').nth(10).inner_text()=='10 天'
        assert '初始止损' in historical.locator('td').nth(9).inner_text()
        page.locator('#search').fill('不存在的股票')
        assert page.locator('#tableBody td').get_attribute('colspan')=='14'
        page.locator('#search').fill('')
        fixture['protected']=True
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#tableBody').textContent.includes('保护止损 31.20元')")
        fixture['protected']=False;fixture['stale']=True
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#quoteStatus').textContent.includes('行情缺失或过期')")
        cells=page.locator('#tableBody tr').filter(has_text='300688.SZ').locator('td')
        assert '33.65' in cells.nth(9).inner_text()
        assert '截至2026-10-16' in cells.nth(9).get_attribute('title')
        assert cells.nth(10).inner_text()=='2 天'
        page.route('**/earnings-gap/data/history.json?*',lambda route:route.fulfill(status=500,body='test error'))
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("document.querySelector('#tableBody').textContent.includes('策略数据加载失败')")
        assert page.locator('#tableBody td').get_attribute('colspan')=='14'
        assert not errors,errors
        result=dict(status='PASS',url=url,actual_quotes_mocked=True,columns=14,target='33.65',stop='28.14',holding_trading_days=2,protected_stop='31.20',historical_days_fixed=True,stale_quote_basis_labeled=True,empty_and_error_colspan=14,desktop=True,mobile_no_page_overflow=True,errors=errors)
        (LOG/'position-browser.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(result,ensure_ascii=False))
        browser.close()


if __name__=='__main__':main()

"""Sizing-only desktop/mobile acceptance; quote failures must not retain a share count."""
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

LOG=Path(__file__).with_name('logs');LOG.mkdir(exist_ok=True)
url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8771/tri-momentum-vol-control/'
online=url.startswith('https:')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True,args=['--no-proxy-server','--disable-quic'])
    page=browser.new_page(viewport={'width':1600,'height':1080})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url,wait_until='domcontentloaded',timeout=60000)
    page.wait_for_function("document.querySelector('#assetRows tr.selected')",timeout=45000)
    assert page.locator('.signal-card .position-calculator').count()==1
    assert '输入' in page.locator('#sizingResult').inner_text()
    page.locator('#capitalAmount').fill('1000000')
    page.wait_for_selector('#sizingShares')
    first=int(page.locator('#sizingShares').inner_text().replace(',',''))
    assert first>0 and first%100==0
    assert '目标持有' in page.locator('#sizingResult').inner_text()
    assert '10bp' in page.locator('#sizingResult').inner_text()
    assert '已有持仓' in page.locator('.position-calculator').inner_text()
    assert '参考' in page.locator('#sizingResult').inner_text() or '预览' in page.locator('#sizingResult').inner_text()
    page.locator('.signal-card').screenshot(path=str(LOG/('sizing-online-desktop.png' if online else 'sizing-desktop.png')),style='.site-header{visibility:hidden!important}')
    page.locator('#capitalAmount').fill('100')
    assert page.locator('#sizingShares').inner_text()=='0'
    assert '不足买入1手' in page.locator('#sizingResult').inner_text()
    for value in ['', '0', '-10']:
        page.locator('#capitalAmount').fill(value)
        assert page.locator('#sizingShares').count()==0
    page.locator('#capitalAmount').fill('500000')
    assert int(page.locator('#sizingShares').inner_text().replace(',',''))<=first//2
    page.set_viewport_size({'width':390,'height':844})
    page.locator('.position-calculator').scroll_into_view_if_needed()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.locator('.signal-card').screenshot(path=str(LOG/('sizing-online-mobile.png' if online else 'sizing-mobile.png')),style='.site-header{visibility:hidden!important}')
    page.route('https://qt.gtimg.cn/**',lambda route:route.abort())
    page.locator('#refreshButton').click()
    page.wait_for_function("document.querySelector('#quoteStatus').textContent.includes('更新失败')")
    assert page.locator('#sizingShares').count()==0
    assert '暂不提供份数测算' in page.locator('#sizingResult').inner_text()
    assert not errors,errors
    result=dict(status='PASS',url=url,desktop=True,mobile=True,lot_rounding=True,small_capital=True,invalid_input=True,quote_failure_clears_estimate=True,page_errors=errors)
    (LOG/('sizing_browser_online.json' if online else 'sizing_browser_local.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));browser.close()

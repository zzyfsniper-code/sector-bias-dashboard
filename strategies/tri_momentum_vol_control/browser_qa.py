"""Real browser acceptance, including public quotes, stale gating and mobile charts."""
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
LOG=Path(__file__).with_name('logs');LOG.mkdir(exist_ok=True)
url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8771/tri-momentum-vol-control/'
online=url.startswith('https:')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
    page=browser.new_page(viewport={'width':1600,'height':1050})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url,wait_until='domcontentloaded')
    page.wait_for_function("document.querySelector('#assetRows tr.selected')",timeout=45000)
    status=page.locator('#quoteStatus').inner_text()
    assert '更新失败' not in status,status
    assert page.title()=='三元动量波控策略'
    assert page.locator('#signalStatus').inner_text()!='可执行参考'
    assert page.locator('#historyRows tr').count()==25
    assert page.locator('#assetRows tr').count()==3
    assert page.locator('#assetRows').inner_text().count('2026-')==3
    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
    page.screenshot(path=str(LOG/('online-desktop.png' if online else 'desktop.png')),full_page=True)
    page.locator('#detailsButton').click()
    assert '19段收益' in page.locator('#rulesPanel').inner_text()
    page.locator('[data-tab=backtest]').click()
    assert '25.38%' in page.locator('#backtestSummary').inner_text()
    assert '18.87%' in page.locator('#backtestSummary').inner_text()
    assert page.locator('#navChart svg').count()==1
    for id in ['navChart','drawdownChart','riskChart']:
        page.locator('#'+id).scroll_into_view_if_needed()
        box=page.locator('#'+id).bounding_box()
        page.mouse.move(box['x']+box['width']*.6,box['y']+box['height']*.5)
        assert page.locator('#chartTooltip').is_visible(),id
        assert '策略回撤' in page.locator('#chartTooltip').inner_text()
    page.locator('#detailsDialog').screenshot(path=str(LOG/('online-details.png' if online else 'details.png')))
    old=page.locator('#rangeLabel').inner_text()
    page.locator('#rangeStart').evaluate("e=>{e.value=400;e.dispatchEvent(new Event('input',{bubbles:true}));}")
    assert page.locator('#rangeLabel').inner_text()!=old
    page.locator('#chartPeriod').select_option('2025')
    assert '2025-01-' in page.locator('#rangeLabel').inner_text()
    downloads=page.locator('#backtestPanel a[download]')
    assert downloads.count()==3
    for a in downloads.all():
        assert page.request.get(a.get_attribute('href') if a.get_attribute('href').startswith('http') else url+a.get_attribute('href')).ok
    page.locator('#closeDetails').click()
    page.locator('#originFilter').select_option('frozen_model')
    assert '暂无模型记录' in page.locator('#historyRows').inner_text()
    page.locator('#originFilter').select_option('all')
    page.locator('#assetFilter').select_option('518880.SH')
    assert '黄金ETF' in page.locator('#historyRows').inner_text()
    page.locator('#assetFilter').select_option('')
    page.locator('#nextPage').click();assert '26—50' in page.locator('#pageInfo').inner_text()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(LOG/('online-mobile.png' if online else 'mobile.png')),full_page=True)
    page.locator('#detailsButton').click();page.locator('[data-tab=backtest]').click()
    page.locator('#drawdownChart').scroll_into_view_if_needed()
    box=page.locator('#drawdownChart').bounding_box();page.mouse.move(box['x']+box['width']*.5,box['y']+45)
    assert page.locator('#chartTooltip').is_visible()
    page.locator('#detailsDialog').screenshot(path=str(LOG/('online-mobile-details.png' if online else 'mobile-details.png')))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.locator('#closeDetails').click()
    # API failure must suppress executable references, not silently reuse an old quote.
    page.route('https://qt.gtimg.cn/**',lambda route:route.abort())
    page.locator('#refreshButton').click()
    page.wait_for_function("document.querySelector('#quoteStatus').textContent.includes('更新失败')")
    assert page.locator('#signalStatus').inner_text()!='可执行参考'
    assert not errors,errors
    center=url.replace('tri-momentum-vol-control/','strategies/')
    page.goto(center,wait_until='domcontentloaded')
    page.wait_for_function("document.querySelector('#tri-signal').textContent !== '—'",timeout=30000)
    assert page.locator('#strategy-count').inner_text()=='5'
    assert '三元动量波控策略' in page.locator('[data-id=tri]').inner_text()
    assert page.locator('[data-id=tri] a').get_attribute('href')=='../tri-momentum-vol-control/'
    assert not errors,errors
    result=dict(status='PASS',url=url,public_quote_status=status,page_errors=errors,desktop=True,mobile=True,
                details=True,charts_and_hover=True,range_drag=True,downloads=True,history_filters=True,network_failure_gate=True,strategy_center=True)
    (LOG/('browser_online.json' if online else 'browser_local.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False));browser.close()

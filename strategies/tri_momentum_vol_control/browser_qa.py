"""Real browser acceptance, including public quotes, stale gating and mobile charts."""
import json
from copy import deepcopy
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
LOG=Path(__file__).with_name('logs');LOG.mkdir(exist_ok=True)
url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8771/tri-momentum-vol-control/'
online=url.startswith('https:')
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True,args=['--no-proxy-server','--disable-quic'])
    page=browser.new_page(viewport={'width':1600,'height':1050})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url,wait_until='domcontentloaded',timeout=60000)
    page.wait_for_function("document.querySelector('#assetRows tr.selected')",timeout=45000)
    status=page.locator('#quoteStatus').inner_text()
    assert '更新失败' not in status,status
    assert page.title()=='三元动量波控策略'
    assert page.locator('#signalStatus').inner_text()!='可执行参考'
    assert page.locator('#historyRows tr').count()==25
    assert page.locator('#assetRows tr').count()==3
    assert '159696.SZ' in page.locator('#assetRows').inner_text()
    assert '513100.SH' not in page.locator('main').inner_text()
    assert page.locator('.asset-section th').count()==6
    assert '买一' not in page.locator('.asset-section').inner_text()
    assert page.locator('#assetRows tr').first.locator('td').count()==6
    for cell in page.locator('#assetRows td:nth-child(2), #assetRows td:nth-child(5)').all():
        value=cell.inner_text()
        if value.startswith('+'):
            assert cell.locator('.up').count()==1
            assert cell.locator('.up').evaluate('e=>getComputedStyle(e).color')=='rgb(139, 46, 36)'
        elif value.startswith('-'):
            assert cell.locator('.down').count()==1
            assert cell.locator('.down').evaluate('e=>getComputedStyle(e).color')=='rgb(31, 107, 84)'
    assert page.locator('#assetRows').inner_text().count('2026-')==3
    assert page.locator('#trackingSummary .metric-grid>div').count()==8
    assert '38.64%' in page.locator('#trackingSummary').inner_text()
    assert page.evaluate("!!(document.querySelector('.asset-section').compareDocumentPosition(document.querySelector('#dailyPerformance')) & Node.DOCUMENT_POSITION_FOLLOWING)")
    assert page.evaluate("!!(document.querySelector('#dailyPerformance').compareDocumentPosition(document.querySelector('.history-section')) & Node.DOCUMENT_POSITION_FOLLOWING)")
    for id in ['trackingnavChart','trackingdrawdownChart','trackingriskChart']:
        assert page.locator('#'+id+' svg').count()==1
        page.locator('#'+id).scroll_into_view_if_needed()
        box=page.locator('#'+id).bounding_box()
        page.mouse.move(box['x']+box['width']*.6,box['y']+box['height']*.5)
        assert page.locator('#trackingchartTooltip').is_visible(),id
        assert '策略回撤' in page.locator('#trackingchartTooltip').inner_text()
    page.locator('#dailyPerformance').screenshot(path=str(LOG/('online-main-performance.png' if online else 'main-performance.png')),style='.site-header{visibility:hidden!important}')
    initial=page.locator('#trackingrangeLabel').inner_text()
    page.locator('#trackingrangeStart').evaluate("e=>{e.value=400;e.dispatchEvent(new Event('input',{bubbles:true}));}")
    assert page.locator('#trackingrangeLabel').inner_text()!=initial
    page.locator('#trackingchartPeriod').select_option('2025')
    assert '2025-01-' in page.locator('#trackingrangeLabel').inner_text()
    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
    page.screenshot(path=str(LOG/('online-desktop.png' if online else 'desktop.png')),full_page=True)
    page.locator('#detailsButton').click()
    assert '19段收益' in page.locator('#rulesPanel').inner_text()
    page.locator('[data-tab=backtest]').click()
    assert '38.64%' in page.locator('#backtestSummary').inner_text()
    assert '14.25%' in page.locator('#backtestSummary').inner_text()
    assert page.locator('#navChart svg').count()==1
    assert '2023-09-28' in page.locator('#rangeLabel').inner_text()
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
    assert '2025-01-' in page.locator('#trackingrangeLabel').inner_text()
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
    page.locator('#trackingdrawdownChart').scroll_into_view_if_needed()
    box=page.locator('#trackingdrawdownChart').bounding_box()
    page.mouse.move(box['x']+box['width']*.5,box['y']+45)
    assert page.locator('#trackingchartTooltip').is_visible()
    page.locator('#dailyPerformance').screenshot(path=str(LOG/('online-mobile-main-performance.png' if online else 'mobile-main-performance.png')),style='.site-header{visibility:hidden!important}')
    page.locator('#detailsButton').click();page.locator('[data-tab=backtest]').click()
    page.locator('#drawdownChart').scroll_into_view_if_needed()
    box=page.locator('#drawdownChart').bounding_box();page.mouse.move(box['x']+box['width']*.5,box['y']+45)
    assert page.locator('#chartTooltip').is_visible()
    page.locator('#detailsDialog').screenshot(path=str(LOG/('online-mobile-details.png' if online else 'mobile-details.png')))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.locator('#closeDetails').click()
    # Synthetic next-day responses exercise browser refresh only; never saved or published.
    daily=page.request.get(url+'data/performance.json').json()
    model=page.request.get(url+'data/live.json').json()
    next_day=next(d for d in model['calendar'] if d>daily['end'])
    revised=deepcopy(daily);revised.update(run_id='BROWSER_TEST_ONLY',end=next_day,data_as_of=next_day)
    revised['dates'].append(next_day);revised['risk_exposure'].append(revised['risk_exposure'][-1])
    revised['metrics']['annual_return']+=.001
    for curve in revised['curves'].values():
        curve['nav'].append(curve['nav'][-1]*1.01)
        curve['drawdown'].append(curve['nav'][-1]/max(1,max(curve['nav']))-1)
    revised_live=deepcopy(model);revised_live.update(run_id='BROWSER_TEST_ONLY',data_as_of=next_day)
    page.route('**/data/live.json?*',lambda route:route.fulfill(json=revised_live))
    page.route('**/data/performance.json?*',lambda route:route.fulfill(json=revised))
    page.locator('#refreshButton').click()
    page.wait_for_function("date=>document.querySelector('#trackingDate').textContent.includes(date)",arg=next_day)
    assert f"{revised['metrics']['annual_return']*100:.2f}%" in page.locator('#trackingSummary').inner_text()
    assert next_day in page.locator('#trackingrangeLabel').inner_text()
    page.unroute('**/data/performance.json?*')
    revised_live['run_id']='MISMATCH_BROWSER_TEST_ONLY'
    page.locator('#refreshButton').click()
    page.wait_for_function("document.querySelector('#quoteStatus').textContent.includes('批次不一致')")
    assert next_day in page.locator('#trackingDate').inner_text()
    assert page.locator('#signalStatus').inner_text()!='可执行参考'
    page.unroute('**/data/live.json?*')
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
                details=True,charts_and_hover=True,range_drag=True,downloads=True,history_filters=True,network_failure_gate=True,strategy_center=True,
                main_page_metrics_and_charts=True,daily_refresh_simulated=True,batch_mismatch_gate=True)
    (LOG/('browser_online.json' if online else 'browser_local.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False));browser.close()

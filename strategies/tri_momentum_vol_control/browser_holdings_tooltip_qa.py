"""Four linked plots, actual daily holdings, and pointer-safe tooltip placement."""
import json
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

LOG=Path(__file__).with_name('logs');LOG.mkdir(exist_ok=True)
url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8771/tri-momentum-vol-control/'
online=url.startswith('https:')
labels={'159696.SZ':'纳指ETF易方达','510300.SH':'沪深300ETF','518880.SH':'黄金ETF','cash':'现金'}
checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True,args=['--no-proxy-server','--disable-quic'])
    page=browser.new_page(viewport={'width':1600,'height':1080})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(url,wait_until='domcontentloaded',timeout=60000)
    page.wait_for_selector('#trackingassetChart .asset-area',timeout=45000)
    packets={False:page.request.get(url+'data/performance.json').json(),True:page.request.get(url+'data/backtest.json').json()}
    for mobile in [False,True]:
        page.set_viewport_size({'width':390,'height':844} if mobile else {'width':1600,'height':1080})
        for detail in [False,True]:
            if detail:
                page.locator('#detailsButton').click()
                page.locator('[data-tab=backtest]').click()
            prefix='' if detail else 'tracking'
            stack=page.locator('#'+prefix+'chartStack')
            tooltip=page.locator('#'+prefix+'chartTooltip')
            assert stack.locator('.plot svg').count()==4
            assert page.locator('#'+prefix+'assetChart .asset-area').count()==4
            for plot_name in ['navChart','drawdownChart','riskChart','assetChart']:
                plot=page.locator('#'+prefix+plot_name)
                plot.evaluate("el=>el.scrollIntoView({block:'center'})")
                for fraction in [.02,.5,.98]:
                    box=plot.bounding_box();left=42 if box['width']<500 else 50
                    mx=box['x']+left+(box['width']-left-15)*fraction
                    my=box['y']+box['height']*.5
                    page.mouse.move(mx,my)
                    assert tooltip.is_visible(),(mobile,detail,plot_name,fraction)
                    t=tooltip.bounding_box();s=stack.bounding_box()
                    assert t['x']>=s['x']-1 and t['x']+t['width']<=s['x']+s['width']+1
                    assert t['y']>=s['y']-1 and t['y']+t['height']<=s['y']+s['height']+1
                    separated=(mx<t['x']-10 or mx>t['x']+t['width']+10 or my<t['y']-10 or my>t['y']+t['height']+10)
                    assert separated,dict(mobile=mobile,detail=detail,plot=plot_name,fraction=fraction,tooltip=t,pointer=[mx,my])
                    if fraction==.98:
                        assert t['x']+t['width']<mx-10
                    assert stack.locator('.crosshair:not([hidden])').count()==4
                    text=tooltip.inner_text();assert '收盘持仓（模型）' in text
                    day=tooltip.locator('strong').inner_text();packet=packets[detail];i=packet['dates'].index(day)
                    for code,label in labels.items():
                        weight=packet['asset_weights'][code][i]
                        if weight>1e-8 or code=='cash':
                            row=tooltip.locator('div').filter(has=page.locator('span',has_text=label))
                            assert row.count()==1,(label,text)
                            assert f'{weight*100:.2f}%' in row.inner_text()
                    checks.append(dict(mobile=mobile,detail=detail,plot=plot_name,fraction=fraction))
            page.locator('#'+prefix+'navChart').evaluate("el=>el.scrollIntoView({block:'center'})")
            box=page.locator('#'+prefix+'navChart').bounding_box()
            page.mouse.move(box['x']+box['width']*.97,box['y']+box['height']*.5)
            file=f"{'online-' if online else ''}holdings-{'mobile' if mobile else 'desktop'}-{'details' if detail else 'main'}.png"
            stack.screenshot(path=str(LOG/file),style='.site-header{visibility:hidden!important}')
            page.locator('#'+prefix+'chartPeriod').select_option('2025')
            assert '2025-01-' in page.locator('#'+prefix+'rangeLabel').inner_text()
            assert page.locator('#'+prefix+'assetChart .asset-area').count()==4
            page.mouse.move(2,2);assert tooltip.is_hidden()
            page.locator('#'+prefix+'chartPeriod').select_option('all')
            if detail:
                page.locator('#closeDetails').click()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert not errors,errors
    result=dict(status='PASS',url=url,geometry_checks=len(checks),four_charts=True,holdings_match_daily_ledger=True,
                tooltip_avoids_pointer=True,tooltip_within_chart=True,desktop=True,mobile=True,details=True,page_errors=errors)
    (LOG/('holdings_tooltip_online.json' if online else 'holdings_tooltip_local.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False));browser.close()

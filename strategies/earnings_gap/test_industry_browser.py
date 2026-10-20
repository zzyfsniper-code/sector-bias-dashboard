"""Industry drilldown integration: complete denominator list, not just passed stocks."""
from datetime import datetime
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
LOG=Path(__file__).resolve().parent/'logs'


def main():
    url=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:18776/earnings_gap.html'
    online='--online' in sys.argv
    source=LOG/'industry-drilldown-inputs'
    context=json.loads((ROOT/'earnings-gap/data/display_context.json').read_text('utf-8'))
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
        page=browser.new_page(viewport=dict(width=1440,height=1100))
        page.on('pageerror',lambda error:errors.append(str(error)))
        if not online:
            page.clock.set_fixed_time(datetime.fromisoformat('2026-10-20T16:00:10+08:00'))
            for name in ['live.json','monitor.json']:
                value=json.loads((source/name).read_text('utf-8'))
                page.route('**/earnings-gap/data/'+name+'?*',lambda route,request,value=value:route.fulfill(json=value))
            page.route('https://api.github.com/**',lambda route:route.fulfill(json={'workflow_runs':[]}))
            page.route('https://qt.gtimg.cn/**',lambda route:route.fulfill(body='',headers={'Access-Control-Allow-Origin':'*'}))
        page.goto(url,wait_until='domcontentloaded')
        page.wait_for_selector('#industryRows tr[data-industry="801210.SI"]')
        page.locator('#industryRows tr[data-industry="801210.SI"] button').click()
        page.wait_for_function("document.querySelector('#industryCompanies').textContent.includes('创业黑马')")
        assert page.locator('#industryCompanies tr').count()==3
        assert page.locator('#industryCompanies tr.candidate-selected').count()==1
        assert '社会服务' in page.locator('#industryCompaniesTitle').inner_text()
        assert page.locator('#industryRows tr[data-industry="801210.SI"] button').get_attribute('aria-expanded')=='true'
        assert '133.79%' in page.locator('#industryCompanies').inner_text()
        assert page.locator('#industryCompanies a').count()==3
        assert page.locator('#industryCompanies tr').first.locator('td').count()==8
        page.locator('.industry-panel').screenshot(path=str(LOG/('industry-online.png' if online else 'industry-desktop.png')))
        page.locator('#industryCompaniesClose').click()
        assert page.locator('#industryCompaniesPanel').is_hidden()
        page.locator('#industryRows tr').first.click()
        assert page.locator('#industryCompaniesPanel').is_visible()
        page.locator('#industryRows tr').first.click()
        assert page.locator('#industryCompaniesPanel').is_hidden()
        page.locator('#industryToggle').click()
        for sector in context['seasons'][0]['rows']:
            key=sector['industry_code'] or 'UNKNOWN'
            page.locator('#industryRows tr[data-industry="'+key+'"] button').click()
            assert sector['industry'] in page.locator('#industryCompaniesTitle').inner_text()
            if sector['disclosed']:
                assert page.locator('#industryCompanies tr').count()==sector['disclosed']
                assert page.locator('#industryCompanies tr.candidate-selected').count()==sector['confirmed']
                assert len(set(page.locator('#industryCompanies .sub').all_text_contents()[::2]))==sector['disclosed']
            else:
                assert '尚无已披露公司' in page.locator('#industryCompanies').inner_text()
        page.locator('#industryRows tr[data-industry="801210.SI"] button').click()
        page.locator('#industryToggle').click()
        page.set_viewport_size(dict(width=390,height=844))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.locator('.industry-panel').screenshot(path=str(LOG/('industry-online-mobile.png' if online else 'industry-mobile.png')))
        page.set_viewport_size(dict(width=1440,height=1100))
        if not online:
            # Older or failed data must never look like a zero-company denominator.
            legacy=json.loads(json.dumps(context))
            for s in legacy['seasons']:
                for r in s['rows']:r.pop('companies',None)
            page.route('**/earnings-gap/data/display_context.json?*',lambda route:route.fulfill(json=legacy))
            page.reload(wait_until='domcontentloaded')
            page.wait_for_selector('#industryRows tr[data-industry="801210.SI"]')
            page.locator('#industryRows tr[data-industry="801210.SI"] button').click()
            assert '明细尚未齐备' in page.locator('#industryCompanies').inner_text()
        assert not errors,errors
        result=dict(status='PASS',url=url,online=online,industries_checked=31,denominators_match=True,
            financial_failures_included=True,one_row_per_company=True,confirmed_highlight=True,original_links=True,
            open_close_switch=True,mobile_no_overflow=True,legacy_missing_not_zero=not online,errors=errors)
        (LOG/('industry-browser-online.json' if online else 'industry-browser.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(result,ensure_ascii=False));browser.close()


if __name__=='__main__':main()

"""Daily public-source financial discovery and persistent independent paper ledger.

Quotes refresh in the browser. This script runs before the open and after the close;
it does not call Tushare/Wind or place orders. A failed critical fetch preserves live.json.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time

import requests

from strategy_core import number, quarter_profit, report_kind, simulate

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'earnings-gap/data'
TZ = timezone(timedelta(hours=8))
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'})


def get_json(url, **kwargs):
    r = SESSION.get(url, timeout=25, **kwargs); r.raise_for_status()
    return r.json()


def finance(filters, columns='ALL'):
    rows = []; page = 1
    while True:
        d = get_json('https://datacenter-web.eastmoney.com/api/data/v1/get', params={
            'reportName': 'RPT_LICO_FN_CPD', 'columns': columns, 'filter': filters,
            'pageSize': 500, 'pageNumber': page, 'sortColumns': 'NOTICE_DATE', 'sortTypes': '-1'})
        if not d.get('success') or d.get('result') is None:
            raise RuntimeError('公开财务接口未返回有效结果，保留上次成功数据')
        result = d['result']; rows.extend(result['data'])
        if page >= result['pages']: return rows
        page += 1; time.sleep(.15)


def daily(code, start, end, adjusted=True):
    symbol = code[-2:].lower() + code[:6]
    param = f'{symbol},day,{start},{end},320,{"qfq" if adjusted else ""}'
    d = get_json('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get', params={'param': param})
    if d.get('code') != 0 or symbol not in d.get('data', {}):
        raise RuntimeError(f'{code}日线缺失')
    part = d['data'][symbol]
    values = part.get('qfqday', part.get('day', []))
    return [dict(date=x[0], open=float(x[1]), close=float(x[2]), high=float(x[3]), low=float(x[4])) for x in values]


def report_title(title, end):
    title = re.sub('<[^>]*>', '', title or '')
    if end[:4] not in title or any(s in title for s in ['摘要', '预告', '快报', '说明会', '审计', '英文', '取消', '提示性']):
        return False
    word = {'Q1': ['第一季度', '一季度'], 'H1': ['半年度', '半年'],
            'Q3': ['第三季度', '三季度'], 'FY': ['年度报告', '年报']}[report_kind(end)]
    return '报告' in title and any(s in title for s in word)


def cninfo(start, end):
    result = []; page = 1
    while True:
        r = SESSION.post('https://www.cninfo.com.cn/new/hisAnnouncement/query', data={
            'pageNum': page, 'pageSize': 30, 'tabName': 'fulltext', 'column': 'szse',
            'category': 'category_ndbg_szsh;category_bndbg_szsh;category_yjdbg_szsh;category_sjdbg_szsh',
            'seDate': start + '~' + end}, headers={'Referer':'https://www.cninfo.com.cn/'}, timeout=25)
        r.raise_for_status(); d = r.json()
        if 'announcements' not in d: raise RuntimeError('巨潮公告结果结构变化')
        result.extend(d.get('announcements') or [])
        if not d.get('hasMore'): return result
        page += 1; time.sleep(.15)


def enrich(record, notices):
    choices = [x for x in notices if x['secCode'] == record['ts_code'][:6]
               and report_title(x['announcementTitle'], record['end_date'])
               and record['ann_date'] in x.get('adjunctUrl', '')]
    if choices:
        a = sorted(choices, key=lambda x: '更正' in x['announcementTitle'], reverse=True)[0]
        record['announcement_url'] = 'https://static.cninfo.com.cn/' + a['adjunctUrl']
        record['announcement_title'] = re.sub('<[^>]*>', '', a['announcementTitle'])


def update():
    now = datetime.now(TZ); today = now.date().isoformat(); yesterday = (now.date() - timedelta(days=1)).isoformat()
    old = json.loads((DATA/'live.json').read_text('utf-8')) if (DATA/'live.json').exists() else {}
    meta = json.loads((DATA/'stock_metadata.json').read_text('utf-8'))
    existing = {x['id']: x for x in old.get('records', [])}
    start = max('2026-10-10', (now.date()-timedelta(days=40)).isoformat())
    current = finance(f"(NOTICE_DATE>='{start}')(NOTICE_DATE<='{today}')")
    # The financial source contains cumulative profits. Never use SJLTZ as quarter YoY.
    issues = []; fetched = {}; published = []
    for r in current:
        code = r['SECUCODE']; end = r['REPORTDATE'][:10]; ann = r['NOTICE_DATE'][:10]
        if code[-2:] not in ['SH','SZ'] or not report_kind(end): continue
        if r['SECURITY_NAME_ABBR'].upper().startswith(('ST','*ST')): continue
        key = (code,end,ann)
        if key in fetched: continue
        fetched[key] = r
        if f'live-{code}-{end}-{ann}' not in existing: published.append(r)
    for r in published:
        code = r['SECUCODE']; end = r['REPORTDATE'][:10]; ann = r['NOTICE_DATE'][:10]
        if code not in meta or not meta[code].get('list_date'):
            issues.append(code+'：上市日期缺失，暂不确认买入'); continue
        history = finance(f'''(SECUCODE="{code}")(REPORTDATE>='{int(end[:4])-1}-01-01')(NOTICE_DATE<='{ann}')''')
        lookup = {}
        for x in history:
            lookup.setdefault(x['REPORTDATE'][:10], x['PARENT_NETPROFIT'])
        y = int(end[:4]); month = int(end[5:7]); prev = {3: None,6: '03-31',9:'06-30',12:'09-30'}[month]
        profit,yoy = quarter_profit(r['PARENT_NETPROFIT'], lookup.get(f'{y}-{prev}'),
            lookup.get(f'{y-1}-{end[5:]}'), lookup.get(f'{y-1}-{prev}'), end)
        if profit is None or yoy is None:
            issues.append(code+'：单季还原数据不足'); continue
        if profit < 0 or yoy < 30: continue
        record = dict(id=f'live-{code}-{end}-{ann}',ts_code=code,name=r['SECURITY_NAME_ABBR'],
            industry=meta[code].get('industry') or r.get('BOARD_NAME') or '—',
            list_date=meta[code]['list_date'],ann_date=ann,end_date=end,report_period=report_kind(end),
            quarter_profit=profit,quarter_yoy=yoy,origin='forward',status='等待开盘',
            financial_source='东方财富定期财报累计金额还原单季',financial_observed_at=now.isoformat(),
            financial_notice_date=ann,announcement_url=None)
        existing[record['id']] = record
    notices = []
    try: notices = cninfo(start,today)
    except Exception: issues.append('巨潮原文暂不可用，可在页面逐条查询原文')
    # Benchmark dates establish actual market sessions; weekdays alone are insufficient.
    market = daily('000001.SH',start,today,False)
    final_day = today if (now.hour, now.minute) >= (15,10) else yesterday
    market = [b for b in market if b['date'] <= final_day]
    calendar = sorted(set(json.loads((DATA/'calendar.json').read_text('utf-8'))) | {x['date'] for x in market})
    records = []
    for record in sorted(existing.values(),key=lambda x:x['ann_date']):
        enrich(record,notices)
        if record.get('exit_date') or record.get('status') in ['未入选','剔除']:
            records.append(record); continue
        try:
            record.pop('data_pending',None)
            begin=(datetime.fromisoformat(record['ann_date'])-timedelta(days=14)).date().isoformat()
            adjusted=daily(record['ts_code'],begin,today); raw=daily(record['ts_code'],begin,today,False)
            adjusted=[b for b in adjusted if b['date']<=final_day];raw=[b for b in raw if b['date']<=final_day]
            records.append(simulate(record,adjusted,raw,calendar))
        except Exception:
            issues.append(record['ts_code']+'：日线暂不可用，保留记录但暂停确认信号')
            records.append(dict(record,data_pending=True))
        time.sleep(.12)
    payload=dict(version='eg-20261013-v1',updated_at=now.isoformat(),financial_asof=today,
        financial_source='东方财富公开定期财报',quote_source='腾讯公开行情',
        status='PARTIAL' if issues else 'PASS',issues=issues,records=records,
        calendar=calendar[-120:],records_count=len(records),financial_reports_checked=len(fetched))
    target=DATA/'live.json'; temp=target.with_suffix('.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')),'utf-8');temp.replace(target)
    print(json.dumps({k:payload[k] for k in ['status','updated_at','records_count','financial_reports_checked','issues']},ensure_ascii=False))


if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    update()

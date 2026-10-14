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
from concurrent.futures import ThreadPoolExecutor

import requests

from strategy_core import number, quarter_profit, report_kind, simulate, qualifies, net_return

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


def newest_reports(rows,calendar):
    # Same company/reaction day: select the newest period BEFORE the YoY filter.
    chosen={}
    for row in sorted(rows,key=lambda x:(x['REPORTDATE'],x['NOTICE_DATE']),reverse=True):
        reaction=next((d for d in calendar if d>=row['NOTICE_DATE'][:10]),'pending')
        chosen.setdefault((row['SECUCODE'],reaction),row)
    return list(chosen.values())


def financial_histories(rows):
    histories={};codes=sorted({r['SECUCODE'] for r in rows})
    if not codes:return histories
    year=min(int(r['REPORTDATE'][:4]) for r in rows)-1
    end=max(r['NOTICE_DATE'][:10] for r in rows)
    for i in range(0,len(codes),60):
        values=','.join('"'+c+'"' for c in codes[i:i+60])
        fetched=finance(f'''(SECUCODE in ({values}))(REPORTDATE>='{year}-01-01')(NOTICE_DATE<='{end}')''')
        for row in fetched:histories.setdefault(row['SECUCODE'],[]).append(row)
    return histories


def original_links(rows):
    # Metadata batches keep peak reporting days bounded; no browser API requests.
    result={}
    for i in range(0,len(rows),60):
        batch=rows[i:i+60];lo=min(r['ann_date'] for r in batch);hi=max(r['ann_date'] for r in batch);page=1;notices=[]
        while True:
            d=get_json('https://np-anotice-stock.eastmoney.com/api/security/ann',params={
                'sr':-1,'page_size':100,'page_index':page,'ann_type':'A','client_source':'web','f_node':'1','s_node':'0',
                'stock_list':','.join(sorted({r['ts_code'][:6] for r in batch})),'begin_time':lo,'end_time':hi})
            if d.get('success')!=1:raise RuntimeError('公告接口结果异常')
            a=d['data'];notices.extend(a['list'])
            if page*100>=a['total_hits']:break
            page+=1
        for row in batch:
            options=[a for a in notices if a['notice_date'][:10]==row['ann_date'] and report_title(a['title'],row['end_date']) and any(c.get('stock_code')==row['ts_code'][:6] for c in a.get('codes',[]))]
            if options:
                a=options[0];result[row['id']]=dict(announcement_url=f"https://data.eastmoney.com/notices/detail/{row['ts_code'][:6]}/{a['art_code']}.html",announcement_title=a['title'])
    return result


def closing_quotes(rows,today):
    quotes={};codes=sorted({r['ts_code'] for r in rows})
    for i in range(0,len(codes),80):
        symbols=','.join(c[-2:].lower()+c[:6] for c in codes[i:i+80])
        r=SESSION.get('https://qt.gtimg.cn/q='+symbols,timeout=25);r.raise_for_status()
        for symbol,text in re.findall(r'v_([a-z]+\d+)="([^"]*)"',r.content.decode('gbk')):
            f=text.split('~')
            if len(f)<35 or not re.fullmatch(r'\d{14}',f[30]):continue
            if f[30][:8]!=today.replace('-','') or f[30][8:12]<'1500':continue
            values=[number(f[j]) for j in [3,4,5,33,34]]
            if not all(v is not None and v>0 for v in values):continue
            quotes[symbol]=dict(zip(['close','previous','open','high','low'],values))
    return quotes


def update():
    now = datetime.now(TZ); today = now.date().isoformat(); yesterday = (now.date() - timedelta(days=1)).isoformat()
    old = json.loads((DATA/'live.json').read_text('utf-8')) if (DATA/'live.json').exists() else {}
    meta = json.loads((DATA/'stock_metadata.json').read_text('utf-8'))
    existing = {x['id']: x for x in old.get('records', [])}
    processed=set(old.get('checked_financial_ids',[]))|set(existing)
    start = max('2026-10-10', (now.date()-timedelta(days=40)).isoformat())
    current = finance(f"(NOTICE_DATE>='{start}')(NOTICE_DATE<='{today}')")
    market=daily('000001.SH',start,today,False)
    final_day=today if (now.hour,now.minute)>=(15,10) else yesterday
    market=[b for b in market if b['date']<=final_day]
    calendar=sorted(set(json.loads((DATA/'calendar.json').read_text('utf-8'))) | {x['date'] for x in market})
    finance_rows=current
    current=newest_reports(current,calendar)
    # The financial source contains cumulative profits. Never use SJLTZ as quarter YoY.
    issues = []; fetched = {}; published = []
    for r in current:
        code = r['SECUCODE']; end = r['REPORTDATE'][:10]; ann = r['NOTICE_DATE'][:10]
        if code[-2:] not in ['SH','SZ'] or not report_kind(end): continue
        if r['SECURITY_NAME_ABBR'].upper().startswith(('ST','*ST')): continue
        key = (code,end,ann)
        if key in fetched: continue
        fetched[key] = r
        if f'live-{code}-{end}-{ann}' not in processed: published.append(r)
    historical=financial_histories(published)
    for r in published:
        code = r['SECUCODE']; end = r['REPORTDATE'][:10]; ann = r['NOTICE_DATE'][:10]
        if code not in meta or not meta[code].get('list_date'):
            issues.append(code+'：上市日期缺失，暂不确认买入'); continue
        history=[x for x in historical.get(code,[]) if x['NOTICE_DATE'][:10]<=ann]
        lookup = {}
        for x in history:
            lookup.setdefault(x['REPORTDATE'][:10], x['PARENT_NETPROFIT'])
        y = int(end[:4]); month = int(end[5:7]); prev = {3: None,6: '03-31',9:'06-30',12:'09-30'}[month]
        profit,yoy = quarter_profit(r['PARENT_NETPROFIT'], lookup.get(f'{y}-{prev}'),
            lookup.get(f'{y-1}-{end[5:]}'), lookup.get(f'{y-1}-{prev}'), end)
        if profit is None or yoy is None:
            issues.append(code+'：单季还原数据不足'); continue
        processed.add(f'live-{code}-{end}-{ann}')
        if profit < 0 or yoy < 30: continue
        record = dict(id=f'live-{code}-{end}-{ann}',ts_code=code,name=r['SECURITY_NAME_ABBR'],
            industry=meta[code].get('industry') or r.get('BOARD_NAME') or '—',
            list_date=meta[code]['list_date'],ann_date=ann,end_date=end,report_period=report_kind(end),
            quarter_profit=profit,quarter_yoy=yoy,origin='forward',status='等待开盘',
            financial_source='东方财富定期财报累计金额还原单季',financial_observed_at=now.isoformat(),
            financial_notice_date=ann,announcement_url=None)
        existing[record['id']] = record
    for record in existing.values():
        if record.get('entry_date'):continue
        key=(record['ts_code'],next((d for d in calendar if d>=record['ann_date']),'pending'))
        newer=[r for r in current if (r['SECUCODE'],next((d for d in calendar if d>=r['NOTICE_DATE'][:10]),'pending'))==key and r['REPORTDATE'][:10]>record['end_date']]
        if newer:record.update(status='剔除',status_note='同日采用更新报告期')
    needs=[r for r in existing.values() if not r.get('announcement_url') and not r.get('exit_date')]
    notices=[]
    # Prefer CNINFO for small daily cohorts. Large cohorts use the validated batch interface.
    if needs and len(needs)<=20:
        try:notices=cninfo(min(r['ann_date'] for r in needs),max(r['ann_date'] for r in needs))
        except Exception:issues.append('巨潮暂不可用，尝试公告接口备用源')
    for record in existing.values():enrich(record,notices)
    needs=[r for r in needs if not r.get('announcement_url')]
    try:
        matched=original_links(needs)
        for record in existing.values():record.update(matched.get(record['id'],{}))
    except Exception:issues.append('部分原文暂缺，保留已有链接并提供巨潮检索')
    final_quotes={}
    if final_day==today:
        try:final_quotes=closing_quotes([r for r in existing.values() if not r.get('entry_date') and next((d for d in calendar if d>=r['ann_date']),None)==today],today)
        except Exception:issues.append('收盘快照暂不可用，改用日线核验')
    def replay(record):
        if record.get('exit_date') or record.get('status') in ['未入选','剔除']:
            return record
        reaction=next((d for d in calendar if d>=record['ann_date']),None)
        if reaction is None:return dict(record,status='等待开盘',reaction_date=None)
        if not record.get('entry_date') and (datetime.fromisoformat(reaction)-datetime.fromisoformat(record['list_date'])).days<90:
            return dict(record,status='剔除',status_note='上市不足90日',reaction_date=reaction)
        q=final_quotes.get(record['ts_code'][-2:].lower()+record['ts_code'][:6])
        if not record.get('entry_date') and reaction==today and q:
            out=dict(record,reaction_date=today,signal_return_pct=(q['close']/q['previous']-1)*100,open_gap_pct=(q['open']/q['previous']-1)*100)
            if q['open']<q['previous']*1.02-1e-8:return dict(out,status='未入选',status_note='高开不足2%')
            if q['low']<=q['previous']:return dict(out,status='剔除',status_note='已补缺口')
            if not qualifies(q['open'],q['low'],q['close'],q['previous'],record['report_period']):return dict(out,status='剔除',status_note='收盘涨幅不符')
            return dict(out,status='持有',entry_date=today,entry_price=q['close'],entry_basis=q['close'],
                stop_basis=q['close']*.92,target_basis=q['close']*1.10,basis_last_close=q['close'],basis_date=today,
                profit_pct=net_return(q['close'],q['close']),hold_days=1,armed=False)
        try:
            record.pop('data_pending',None)
            begin=(datetime.fromisoformat(record['ann_date'])-timedelta(days=14)).date().isoformat()
            adjusted=daily(record['ts_code'],begin,today); raw=daily(record['ts_code'],begin,today,False)
            adjusted=[b for b in adjusted if b['date']<=final_day];raw=[b for b in raw if b['date']<=final_day]
            return simulate(record,adjusted,raw,calendar)
        except Exception:
            issues.append(record['ts_code']+'：日线暂不可用，保留记录但暂停确认信号')
            return dict(record,data_pending=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        records=list(executor.map(replay,sorted(existing.values(),key=lambda x:x['ann_date'])))
    payload=dict(version='eg-20261013-v1',updated_at=datetime.now(TZ).isoformat(),financial_asof=today,
        financial_source='东方财富公开定期财报',quote_source='腾讯公开行情',
        status='PARTIAL' if issues else 'PASS',issues=issues,records=records,
        checked_financial_ids=sorted(processed),
        calendar=calendar[-120:],records_count=len(records),financial_reports_checked=len(fetched))
    target=DATA/'live.json'; temp=target.with_suffix('.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')),'utf-8');temp.replace(target)
    print(json.dumps({k:payload[k] for k in ['status','updated_at','records_count','financial_reports_checked','issues']},ensure_ascii=False))
    return payload,finance_rows,list(fetched.values())


def monitored_update():
    import monitoring
    old,started_at=monitoring.begin()
    try:
        payload,finance_rows,selected=update()
        meta=json.loads((DATA/'stock_metadata.json').read_text('utf-8'))
        monitor=monitoring.finish(payload,finance_rows,selected,old,started_at,cninfo,financial_histories,meta)
        print(json.dumps(dict(monitor_status=monitor['status'],counts=monitor['counts']),ensure_ascii=False))
    except Exception as exc:
        monitoring.failure(exc,started_at)
        raise


if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    monitored_update()

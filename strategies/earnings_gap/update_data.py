"""Daily public-source financial discovery and persistent independent paper ledger.

Quotes refresh in the browser. This script runs before the open and after the close;
Financial gaps use Tushare, then validated local Wind Excel data; no orders are placed.
A failed critical fetch preserves live.json.
"""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests
import pdfplumber
from monitoring import is_a_share, original_unchanged_report

from strategy_core import number, quarter_profit, report_kind, simulate, qualifies, net_return, reaction_day, VERSION, VOLUME_EFFECTIVE, PULLBACK_EFFECTIVE, PULLBACK_REASON, pullback_excluded

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'earnings-gap/data'
TZ = timezone(timedelta(hours=8))
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'})


def get_json(url, **kwargs):
    for attempt in range(3):
        try:
            r = SESSION.get(url, timeout=25, **kwargs)
            break
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2: raise
            delay = 2 ** (attempt + 1)
            print(f'公开数据请求暂时失败，{delay}秒后进行第{attempt + 2}/3次尝试', flush=True)
            time.sleep(delay)
    r.raise_for_status()
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


def fill_listing_dates(meta, codes, today):
    changed = False
    for code in sorted(set(codes)):
        if not is_a_share(code) or meta.get(code, {}).get('list_date'): continue
        try:
            url = 'https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax'
            profile = get_json(url, params={'code': code[-2:]+code[:6]})
            if not isinstance(profile, dict): continue
            rows = profile.get('fxxg', [])
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get('SECUCODE') != code or rows[0].get('SECURITY_CODE') != code[:6]: continue
            listed = datetime.strptime(str(rows[0].get('LISTING_DATE'))[:10], '%Y-%m-%d').date().isoformat()
            if listed > today: continue
            meta.setdefault(code, {}).update(list_date=listed, listing_source='东方财富公司资料（发行相关）',
                listing_source_url=url+'?code='+code[-2:]+code[:6], listing_observed_at=datetime.now(TZ).isoformat())
            changed = True
        except (requests.RequestException, ValueError, TypeError, KeyError):
            continue
    if changed:
        target=DATA/'stock_metadata.json';temp=target.with_suffix('.tmp')
        temp.write_text(json.dumps(meta,ensure_ascii=False,allow_nan=False,separators=(',',':')),'utf-8');temp.replace(target)
    return meta


def daily(code, start, end, adjusted=True):
    symbol = code[-2:].lower() + code[:6]
    param = f'{symbol},day,{start},{end},320,{"qfq" if adjusted else ""}'
    d = get_json('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get', params={'param': param})
    if d.get('code') != 0 or symbol not in d.get('data', {}):
        raise RuntimeError(f'{code}日线缺失')
    part = d['data'][symbol]
    values = part.get('qfqday', part.get('day', []))
    return [dict(date=x[0], open=float(x[1]), close=float(x[2]), high=float(x[3]), low=float(x[4]), volume_shares=float(x[5])*(1 if code.startswith('68') else 100) if len(x)>5 else None) for x in values]


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
        if not d.get('hasMore'):
            for item in result: resolve_report_year(item)
            return result
        page += 1; time.sleep(.15)


def resolve_report_year(item):
    title = re.sub('<[^>]*>', '', item.get('announcementTitle') or '')
    code = str(item.get('secCode', ''))
    if re.search(r'20\d{2}\s*年', title) or not re.fullmatch(r'[036]\d{5}', code): return
    if '报告' not in title or any(s in title for s in ['摘要', '预告', '快报', '说明会', '审计', '英文', '取消', '提示性']): return
    periods = [('第三季度','09-30'),('三季度','09-30'),('第一季度','03-31'),('一季度','03-31'),('半年度','06-30'),('半年','06-30'),('年度报告','12-31'),('年报','12-31')]
    end = next((suffix for word,suffix in periods if word in title), None)
    if not end: return
    path = item.get('adjunctUrl', '')
    if not re.fullmatch(r'finalpage/20\d{2}-\d{2}-\d{2}/\d+\.[Pp][Dd][Ff]', path): raise ValueError('缺少年份的公告原文地址待核验')
    response = SESSION.get('https://static.cninfo.com.cn/'+path, timeout=25);response.raise_for_status()
    if len(response.content)>5_000_000 or not response.content.startswith(b'%PDF'): raise ValueError('公告原文格式或大小异常')
    with pdfplumber.open(BytesIO(response.content)) as doc: text = ''.join((p.extract_text() or '') for p in doc.pages[:2])
    compact = re.sub(r'\s+', '', text)
    years = {match[1] for match in re.finditer(r'(20\d{2})年(?:第三季度|三季度|第一季度|一季度|半年度|半年|年度)报告', compact) if any(word in match[0] and suffix==end for word,suffix in periods)}
    if not re.search(r'证券代码[:：]'+code, compact) or len(years)!=1: raise ValueError(code+'公告年份未能与原文身份核对')
    item['report_identity'] = dict(code=code, year=int(years.pop()), period_end=end, sha256=hashlib.sha256(response.content).hexdigest(), pages=[1,2])


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
        reaction=reaction_day(row['NOTICE_DATE'][:10],calendar) or 'pending'
        chosen.setdefault((row['SECUCODE'],reaction),row)
    return list(chosen.values())


def load_trading_calendar(today, completed):
    value=json.loads((DATA/'trading_calendar.json').read_text('utf-8'))
    if not value['coverage_start']<=today<=value['coverage_end']:
        raise RuntimeError('交易日历未覆盖今天，保留上次数据并暂停反应日确认；请更新交易日历')
    opened=value['open_dates']
    if opened!=sorted(set(opened)) or any(not value['coverage_start']<=d<=value['coverage_end'] for d in opened):
        raise RuntimeError('交易日历结构异常')
    if any(value['coverage_start']<=d<=value['coverage_end'] and d not in opened for d in completed):
        raise RuntimeError('交易日历与已完成行情日期冲突')
    return value


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
            volume=number(f[6])
            quotes[symbol]['volume_shares']=volume*(1 if symbol.startswith('sh68') else 100) if volume is not None and f[6].strip() else None
    return quotes


def update(sources=None):
    now = datetime.now(TZ); today = now.date().isoformat(); yesterday = (now.date() - timedelta(days=1)).isoformat()
    old = json.loads((DATA/'live.json').read_text('utf-8')) if (DATA/'live.json').exists() else {}
    meta = json.loads((DATA/'stock_metadata.json').read_text('utf-8'))
    existing = {x['id']: x for x in old.get('records', [])}
    processed=set(old.get('checked_financial_ids',[]))|set(existing)
    start = max('2026-10-10', (now.date()-timedelta(days=40)).isoformat())
    current = sources.discover(start,today) if sources else finance(f"(NOTICE_DATE>='{start}')(NOTICE_DATE<='{today}')")
    market=daily('000001.SH',start,today,False)
    final_day=today if (now.hour,now.minute)>=(15,10) else yesterday
    market=[b for b in market if b['date']<=final_day]
    calendar=sorted(set(json.loads((DATA/'calendar.json').read_text('utf-8'))) | {x['date'] for x in market})
    schedule=load_trading_calendar(today,calendar)
    reaction_calendar=sorted(set(calendar)|set(schedule['open_dates']))
    finance_rows=current
    current=newest_reports(current,reaction_calendar)
    # The financial source contains cumulative profits. Never use SJLTZ as quarter YoY.
    issues = []; fetched = {}; published = []
    for r in current:
        code = r['SECUCODE']; end = r['REPORTDATE'][:10]; ann = r['NOTICE_DATE'][:10]
        if not is_a_share(code) or not report_kind(end): continue
        if r['SECURITY_NAME_ABBR'].upper().startswith(('ST','*ST')): continue
        key = (code,end,ann)
        if key in fetched: continue
        fetched[key] = r
        if report_kind(end) == 'FY':
            processed.add(f'live-{code}-{end}-{ann}')
            continue
        if f'live-{code}-{end}-{ann}' not in processed: published.append(r)
    fill_listing_dates(meta,[r['SECUCODE'] for r in published],today)
    historical=sources.histories(published) if sources else financial_histories(published)
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
            financial_source=r.get('FINANCIAL_SOURCE','东方财富定期财报')+'累计金额还原单季',financial_observed_at=now.isoformat(),
            financial_notice_date=ann,announcement_url=r.get('ANNOUNCEMENT_URL'))
        record['financial_components']=[dict(report_period=x['REPORTDATE'][:10],notice_date=x['NOTICE_DATE'][:10],
            source=x.get('FINANCIAL_SOURCE','东方财富定期财报')) for x in history if x['REPORTDATE'][:10] in
            [end,f'{y}-{prev}',f'{y-1}-{end[5:]}',f'{y-1}-{prev}']]
        existing[record['id']] = record
    for record in existing.values():
        if record.get('entry_date'):continue
        if record.get('report_period') == 'FY':
            record.update(status='剔除',status_note='年报不参与策略')
            continue
        reaction=reaction_day(record['ann_date'],reaction_calendar,record.get('available_at'))
        if reaction and (datetime.fromisoformat(reaction)-datetime.fromisoformat(record['list_date'])).days<90:
            record.update(status='剔除',status_note='上市不足90日',reaction_date=reaction)
            continue
        key=(record['ts_code'],reaction_day(record['ann_date'],reaction_calendar,record.get('available_at')) or 'pending')
        newer=[r for r in current if (r['SECUCODE'],reaction_day(r['NOTICE_DATE'][:10],reaction_calendar) or 'pending')==key and r['REPORTDATE'][:10]>record['end_date']]
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
    proof_path=DATA/'announcement_checks.json'
    verified=json.loads(proof_path.read_text('utf-8')) if proof_path.exists() else {}
    for record in existing.values():
        original=original_unchanged_report(record,existing.values(),verified)
        if original:record.update(status='剔除',status_note='更正财务值未变，沿用首次财报反应日',
            reaction_date=original.get('reaction_date'),original_signal_id=original['id'])
    volume_records=[r for r in existing.values() if not r.get('entry_date') and (reaction_day(r['ann_date'],reaction_calendar,r.get('available_at')) or '')>=VOLUME_EFFECTIVE and r.get('status') not in ['未入选','剔除']]
    if volume_records:
        try:
            from volume_data import prepare
            prepare(DATA,volume_records,today,reaction_calendar)
        except Exception:
            issues.append('量能数据更新失败；未核验记录暂停入场，已有持仓按原退出规则处理')
    final_quotes={}
    if final_day==today:
        try:final_quotes=closing_quotes([r for r in existing.values() if not r.get('entry_date') and reaction_day(r['ann_date'],reaction_calendar,r.get('available_at'))==today],today)
        except Exception:issues.append('收盘快照暂不可用，改用日线核验')
    def replay(record):
        if record.get('exit_date') or record.get('status') in ['未入选','剔除']:
            return record
        # Today's confirmed close entry cannot exit under T+1. An incomplete
        # daily-bar response must not erase an already persisted entry.
        if record.get('entry_date')==today:return record
        reaction=reaction_day(record['ann_date'],reaction_calendar,record.get('available_at'))
        if reaction is None:return dict(record,status='等待开盘',reaction_date=None)
        if not record.get('entry_date') and (datetime.fromisoformat(reaction)-datetime.fromisoformat(record['list_date'])).days<90:
            return dict(record,status='剔除',status_note='上市不足90日',reaction_date=reaction)
        q=final_quotes.get(record['ts_code'][-2:].lower()+record['ts_code'][:6])
        if not record.get('entry_date') and reaction==today and q:
            out=dict(record,reaction_date=today,signal_return_pct=(q['close']/q['previous']-1)*100,open_gap_pct=(q['open']/q['previous']-1)*100)
            actual=number(q.get('volume_shares'));previous=number(record.get('volume_previous_shares'))
            verified=actual is not None and actual>=0 and previous is not None and previous>0 and record.get('volume_reference_day')==today
            if verified:out.update(volume_actual_shares=actual,volume_ratio=actual/previous,volume_forecast_shares=actual,volume_forecast_ratio=actual/previous,volume_state='confirmed' if actual+1e-8>=previous*1.45 else 'failed')
            if q['open']<q['previous']*1.02-1e-8:return dict(out,status='未入选',status_note='高开不足2%')
            if q['low']<=q['previous']:return dict(out,status='剔除',status_note='已补缺口')
            if not qualifies(q['open'],q['low'],q['close'],q['previous'],record['report_period']):return dict(out,status='剔除',status_note='收盘涨幅不符')
            if reaction>=PULLBACK_EFFECTIVE:
                excluded=pullback_excluded(q.get('high'),q['close'],q['previous'])
                if excluded is None:return dict(out,status='待核验',status_note='冲高回落条件待核验：缺少有效最高价')
                out.update(signal_high_pct=(q['high']/q['previous']-1)*100,pullback_excluded=excluded)
                if excluded:return dict(out,status='剔除',status_note=PULLBACK_REASON)
            if reaction>=VOLUME_EFFECTIVE:
                if not verified:
                    return dict(out,status='待核验',status_note='量能待核验')
                if actual+1e-8<previous*1.45:return dict(out,status='剔除',status_note='收盘量能不足1.45倍')
            return dict(out,status='持有',entry_date=today,entry_price=q['close'],entry_basis=q['close'],
                stop_basis=q['close']*.92,target_basis=q['close']*1.10,basis_last_close=q['close'],basis_date=today,
                profit_pct=net_return(q['close'],q['close']),hold_days=1,armed=False)
        try:
            record.pop('data_pending',None)
            begin=(datetime.fromisoformat(record['ann_date'])-timedelta(days=14)).date().isoformat()
            adjusted=daily(record['ts_code'],begin,today); raw=daily(record['ts_code'],begin,today,False)
            adjusted=[b for b in adjusted if b['date']<=final_day];raw=[b for b in raw if b['date']<=final_day]
            if record.get('entry_date') and (not any(b['date']==record['entry_date'] for b in adjusted) or not any(b['date']==record['entry_date'] for b in raw)):
                issues.append(record['ts_code']+'：买入日行情尚未齐备，保留已有成交记录')
                return dict(record,data_pending=True)
            return simulate(record,adjusted,raw,calendar,reaction_calendar)
        except Exception:
            issues.append(record['ts_code']+'：日线暂不可用，保留记录但暂停确认信号')
            return dict(record,data_pending=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        records=list(executor.map(replay,sorted(existing.values(),key=lambda x:x['ann_date'])))
    payload=dict(version=VERSION,updated_at=datetime.now(TZ).isoformat(),financial_asof=today,
        financial_source='东方财富公开定期财报',quote_source='腾讯公开行情',
        status='PARTIAL' if issues else 'PASS',issues=issues,records=records,
        checked_financial_ids=sorted(processed),
        calendar=calendar[-120:],records_count=len(records),financial_reports_checked=len(fetched))
    payload.update(reaction_calendar=schedule['open_dates'],reaction_calendar_start=schedule['coverage_start'],
                   reaction_calendar_end=schedule['coverage_end'],reaction_calendar_source=schedule['source'])
    if sources:payload.update(financial_source='东财优先；Tushare备选1；Wind Excel本机补数备选2',
        financial_source_order=['Eastmoney','Tushare','Wind Excel'],financial_fallback_audit=sources.audit,
        wind_financial_pending=sources.pending_wind)
    target=DATA/'live.json'; temp=target.with_suffix('.tmp');temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')),'utf-8');temp.replace(target)
    print(json.dumps({k:payload[k] for k in ['status','updated_at','records_count','financial_reports_checked','issues']},ensure_ascii=False))
    return payload,finance_rows,list(fetched.values())


def monitored_update():
    import monitoring
    from financial_sources import FinancialSources
    old,started_at=monitoring.begin()
    try:
        sources=FinancialSources(DATA,finance,financial_histories,cninfo)
        payload,finance_rows,selected=update(sources)
        meta=json.loads((DATA/'stock_metadata.json').read_text('utf-8'))
        monitor=monitoring.finish(payload,finance_rows,selected,old,started_at,sources.notices,sources.histories,meta)
        print(json.dumps(dict(monitor_status=monitor['status'],counts=monitor['counts']),ensure_ascii=False))
    except Exception as exc:
        monitoring.failure(exc,started_at)
        raise


if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    monitored_update()

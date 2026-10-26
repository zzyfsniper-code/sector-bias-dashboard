"""Fill missing cumulative parent profits: Eastmoney -> Tushare -> Wind Excel cache."""
from datetime import datetime
import json
import math
import os
from pathlib import Path
import requests
from strategy_core import quarter_profit
from monitoring import is_a_share


def date(value):
    text=str(value or '')[:10].replace('-','')
    try:return datetime.strptime(text,'%Y%m%d').date().isoformat()
    except ValueError:return None


def valid(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def latest_rows(rows):
    result=[]
    for end in sorted({r['REPORTDATE'] for r in rows}):
        part=[r for r in rows if r['REPORTDATE']==end];latest=max(r['NOTICE_DATE'] for r in part)
        chosen=[r for r in part if r['NOTICE_DATE']==latest]
        if len({r['PARENT_NETPROFIT'] for r in chosen})==1:result.append(chosen[0])
    return result


def required(end):
    year=int(end[:4]);prev={'03':None,'06':'03-31','09':'06-30','12':'09-30'}[end[5:7]]
    return [end,f'{year-1}-{end[5:]}']+([f'{year}-{prev}',f'{year-1}-{prev}'] if prev else [])


def amounts(row,history):
    end=row['REPORTDATE'][:10];ann=row['NOTICE_DATE'][:10];lookup={}
    for item in sorted(history,key=lambda x:x['NOTICE_DATE'],reverse=True):
        if item['NOTICE_DATE'][:10]<=ann and valid(item.get('PARENT_NETPROFIT')):
            lookup.setdefault(item['REPORTDATE'][:10],item['PARENT_NETPROFIT'])
    year=int(end[:4]);prev={'03':None,'06':'03-31','09':'06-30','12':'09-30'}[end[5:7]]
    return quarter_profit(row.get('PARENT_NETPROFIT'),lookup.get(f'{year}-{prev}'),lookup.get(f'{year-1}-{end[5:]}'),lookup.get(f'{year-1}-{prev}'),end)


def tushare_income(code,anchor):
    token=os.environ.get('TUSHARE_TOKEN')
    if not token:raise RuntimeError('TUSHARE_TOKEN_MISSING')
    try:
        response=requests.post('https://api.tushare.pro',json=dict(api_name='income',token=token,
            params=dict(ts_code=code,start_date=f'{int(anchor[:4])-1}0101',end_date=anchor.replace('-',''),report_type='1'),
            fields='ts_code,ann_date,f_ann_date,end_date,report_type,n_income_attr_p'),timeout=25)
        if response.status_code!=200:raise RuntimeError('TUSHARE_HTTP_'+str(response.status_code))
        payload=response.json()
    except (requests.RequestException,ValueError):raise RuntimeError('TUSHARE_REQUEST_FAILED') from None
    if payload.get('code')!=0:raise RuntimeError('TUSHARE_API_'+str(payload.get('code')))
    data=payload.get('data') or {};fields=data.get('fields',[]);rows=[]
    for values in data.get('items') or []:
        item=dict(zip(fields,values));ann=date(item.get('ann_date'));actual=date(item.get('f_ann_date'))
        # No date subtraction, quarterly report types, parent-only statements or forecasts.
        if item.get('ts_code')!=code or str(item.get('report_type'))!='1' or not ann:continue
        available=max(ann,actual or ann);end=date(item.get('end_date'));profit=item.get('n_income_attr_p')
        if available<=anchor and end and valid(profit):
            rows.append(dict(SECUCODE=code,REPORTDATE=end,NOTICE_DATE=available,PARENT_NETPROFIT=profit,FINANCIAL_SOURCE='Tushare合并利润表'))
    # Same-day conflicting versions must not be resolved by arbitrary row order.
    return latest_rows(rows)


def wind_excel_cache(data,code,anchor):
    path=Path(data)/'wind_financial_fallback.json'
    if not path.exists():raise RuntimeError('WIND_EXCEL_LOCAL_REQUIRED')
    payload=json.loads(path.read_text('utf-8'))
    if payload.get('source')!='Wind Excel WDF.Addin' or payload.get('basis')!='cumulative_parent_profit' or payload.get('unit')!='CNY':
        raise RuntimeError('WIND_EXCEL_CACHE_INVALID')
    rows=[]
    for item in payload.get('rows',[]):
        ann=date(item.get('NOTICE_DATE'));end=date(item.get('REPORTDATE'))
        if item.get('SECUCODE')==code and ann and ann<=anchor and end and valid(item.get('PARENT_NETPROFIT')):
            rows.append(dict(item,FINANCIAL_SOURCE='Wind Excel累计归母净利润'))
    return latest_rows(rows)


class FinancialSources:
    def __init__(self,data,primary,primary_histories,notices):
        self.data=Path(data);self.primary=primary;self.primary_histories=primary_histories;self.fetch_notices=notices
        self.catalog={};self.notice_cache={};self.history_cache={};self.income_cache={};self.audit=[];self.pending_wind=[];self.tushare_blocked=None

    def tushare(self,code,anchor):
        key=(code,anchor)
        if key not in self.income_cache:
            if self.tushare_blocked:raise RuntimeError(self.tushare_blocked)
            if len(self.income_cache)>=60:raise RuntimeError('TUSHARE_BATCH_LIMIT')
            try:self.income_cache[key]=tushare_income(code,anchor)
            except Exception as exc:
                self.income_cache[key]=exc
                if str(exc).startswith(('TUSHARE_API_','TUSHARE_TOKEN_','TUSHARE_HTTP_401','TUSHARE_HTTP_403','TUSHARE_HTTP_429')):
                    self.tushare_blocked=str(exc)
        if isinstance(self.income_cache[key],Exception):raise self.income_cache[key]
        return self.income_cache[key]

    def notices(self,start,end):
        key=(start,end)
        if key not in self.notice_cache:self.notice_cache[key]=self.fetch_notices(start,end)
        return self.notice_cache[key]

    def discover(self,start,today):
        from monitoring import notice_record, report_scope_exclusion
        proof_path=self.data/'announcement_checks.json'
        verified=json.loads(proof_path.read_text('utf-8')) if proof_path.exists() else {}
        primary_error=None
        try:rows=self.primary(f"(NOTICE_DATE>='{start}')(NOTICE_DATE<='{today}')")
        except Exception as exc:rows=[];primary_error=exc
        old_path=self.data/'monitor.json';old=json.loads(old_path.read_text('utf-8')) if old_path.exists() else {}
        self.catalog={n['id']:n for n in old.get('catalog',[]) if start<=n['ann_date']<=today and not report_scope_exclusion(n,verified)}
        if primary_error and not self.catalog:raise primary_error
        try:
            for raw in self.notices(start,today):
                notice=notice_record(raw)
                if notice and start<=notice['ann_date']<=today:
                    if report_scope_exclusion(notice,verified):self.catalog.pop(notice['id'],None)
                    else:self.catalog[notice['id']]=notice
        except Exception:
            if primary_error:raise RuntimeError('东财与公告清单均不可用，保留上次数据') from None
        existing={(r['SECUCODE'],r['REPORTDATE'][:10]) for r in rows if valid(r.get('PARENT_NETPROFIT'))}
        missing={}
        for notice in sorted(self.catalog.values(),key=lambda n:n['ann_date'],reverse=True):
            key=(notice['ts_code'],notice['end_date'])
            if key in existing or key in missing or not is_a_share(notice['ts_code']) or notice['name'].upper().startswith(('ST','*ST')):continue
            missing[key]=dict(SECUCODE=notice['ts_code'],REPORTDATE=notice['end_date'],NOTICE_DATE=notice['ann_date'],
                              SECURITY_NAME_ABBR=notice['name'],PARENT_NETPROFIT=None,ANNOUNCEMENT_URL=notice['url'])
        for row in missing.values():
            self.histories([row]);history=self.history_cache[(row['SECUCODE'],row['NOTICE_DATE'],row['REPORTDATE'])]
            current=next((r for r in history if r['REPORTDATE'][:10]==row['REPORTDATE']),None)
            if current and valid(current.get('PARENT_NETPROFIT')):
                row.update(PARENT_NETPROFIT=current['PARENT_NETPROFIT'],FINANCIAL_SOURCE=current.get('FINANCIAL_SOURCE','东方财富公开定期财报'),
                           SOURCE_NOTICE_DATE=current['NOTICE_DATE']);rows.append(row)
        if primary_error and not rows:raise RuntimeError('东财不可用且备用源未补齐，保留上次数据') from None
        # An invalid primary row must not hide an actually filled fallback row.
        return [r for r in rows if valid(r.get('PARENT_NETPROFIT'))]

    def histories(self,rows):
        missing=[r for r in rows if (r['SECUCODE'],r['NOTICE_DATE'][:10],r['REPORTDATE'][:10]) not in self.history_cache]
        try:primary=self.primary_histories(missing) if missing else {}
        except Exception:primary={}
        for row in missing:
            code=row['SECUCODE'];anchor=row['NOTICE_DATE'][:10];needed=required(row['REPORTDATE'][:10])
            history=[r for r in primary.get(code,[]) if r['NOTICE_DATE'][:10]<=anchor and valid(r.get('PARENT_NETPROFIT'))]
            if valid(row.get('PARENT_NETPROFIT')):history.insert(0,row)
            chosen={}
            for item in sorted(history,key=lambda x:x['NOTICE_DATE'],reverse=True):chosen.setdefault(item['REPORTDATE'][:10],item)
            for source,fetch in [('Tushare',lambda:self.tushare(code,anchor)),('Wind Excel',lambda:wind_excel_cache(self.data,code,anchor))]:
                absent=[end for end in needed if end not in chosen]
                if not absent:break
                try:
                    fetched=fetch()
                    for item in fetched:
                        end=item['REPORTDATE'][:10]
                        if end in absent and item['SECUCODE']==code and item['NOTICE_DATE'][:10]<=anchor and valid(item.get('PARENT_NETPROFIT')):
                            chosen[end]=item
                    self.audit.append(dict(ts_code=code,ann_date=anchor,source=source,status='used' if any(e in chosen for e in absent) else 'empty'))
                except Exception as exc:
                    reason=str(exc) if str(exc).startswith(('TUSHARE_','WIND_EXCEL_')) else source.upper().replace(' ','_')+'_FAILED'
                    self.audit.append(dict(ts_code=code,ann_date=anchor,source=source,status='unavailable',reason=reason))
            absent=[end for end in needed if end not in chosen]
            if absent:self.pending_wind.append(dict(ts_code=code,ann_date=anchor,end_date=row['REPORTDATE'][:10],missing_periods=absent))
            self.history_cache[(code,anchor,row['REPORTDATE'][:10])]=list(chosen.values())
        result={}
        for row in rows:
            for item in self.history_cache[(row['SECUCODE'],row['NOTICE_DATE'][:10],row['REPORTDATE'][:10])]:
                if item not in result.setdefault(row['SECUCODE'],[]):result[row['SECUCODE']].append(item)
        return {code:sorted(part,key=lambda x:x['NOTICE_DATE'],reverse=True) for code,part in result.items()}

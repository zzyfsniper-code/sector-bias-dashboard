"""Read-only display enrichment. Never writes live.json or changes trading decisions."""
from bisect import bisect_left
from datetime import date, datetime, timedelta
import json
import os
import time

import requests

from financial_sources import FinancialSources, amounts, date as iso_date
from strategy_core import number, qualifies, reaction_day, report_kind
import update_data as u

DATA = u.DATA


def read(name, default):
    path = DATA / name
    return json.loads(path.read_text('utf-8')) if path.exists() else default


def write(name, value):
    target = DATA / name
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')), 'utf-8')
    temp.replace(target)


class Tushare:
    def __init__(self):
        self.calls = 0

    def __call__(self, api, fields, **params):
        token = os.environ.get('TUSHARE_TOKEN')
        if not token:
            raise RuntimeError('TUSHARE_TOKEN_MISSING')
        time.sleep(.35)
        self.calls += 1
        try:
            response = requests.post('https://api.tushare.pro', json=dict(
                api_name=api, token=token, fields=fields, params=params), timeout=25)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError('TUSHARE_REQUEST_FAILED') from None
        if payload.get('code') != 0:
            raise RuntimeError('TUSHARE_API_' + str(payload.get('code')))
        data = payload.get('data') or {}
        if not set(fields.split(',')).issubset(data.get('fields', [])):
            raise RuntimeError('TUSHARE_FIELDS_MISSING')
        return [dict(zip(data['fields'], row)) for row in data.get('items', [])]

    def pages(self, api, fields, limit, **params):
        output = []
        for offset in range(0, 100000, limit):
            rows = self(api, fields, limit=limit, offset=offset, **params)
            if rows and rows[0] in output:
                raise RuntimeError('TUSHARE_PAGINATION_REPEATED')
            output.extend(rows)
            if len(rows) < limit:
                return output
        raise RuntimeError('TUSHARE_PAGINATION_LIMIT')


def prior_date(reaction, calendar):
    index = bisect_left(calendar, reaction) if reaction else 0
    return calendar[index-1] if index else None


def pb_feature(rows, anchor):
    result = dict(pb_date=anchor, pb=None, pb_percentile=None, pb_observations=0,
                  pb_status='待补数据', pb_source='Tushare daily_basic')
    if not anchor:
        return result
    day = date.fromisoformat(anchor)
    try:
        start = day.replace(year=day.year-3).isoformat()
    except ValueError:
        start = day.replace(year=day.year-3, day=28).isoformat()
    values = {}
    for row in rows:
        stamp = iso_date(row.get('trade_date'))
        if stamp and start < stamp <= anchor:
            value = number(row.get('pb'))
            if stamp in values and values[stamp] != value:
                raise ValueError('PB同日冲突')
            values[stamp] = value
    current = values.get(anchor)
    positive = [x for x in values.values() if x is not None and x > 0]
    result.update(pb=current, pb_observations=len(positive))
    if anchor not in values:
        return result
    if current is None or current <= 0:
        return dict(result, pb_status='无有效正PB')
    if len(positive) < 252:
        return dict(result, pb_status='历史不足')
    rank = 100 * (sum(x < current for x in positive) + .5*sum(x == current for x in positive)) / len(positive)
    return dict(result, pb_percentile=rank, pb_status='有效')


def industry_at(members, code, day):
    matches = {(r['l1_code'], r['l1_name']) for r in members if r['ts_code'] == code
               and (iso_date(r.get('in_date')) or '9999') <= day
               and (not iso_date(r.get('out_date')) or day < iso_date(r['out_date']))}
    if len(matches) != 1:
        return dict(industry_l1='行业待核验', industry_code=None, industry_date=day)
    code, name = matches.pop()
    return dict(industry_l1=name, industry_code=code, industry_date=day)


def industry_summary(disclosures, checks, members, cutoff):
    groups = {r['l1_code']: dict(industry_code=r['l1_code'], industry=r['l1_name'],
              disclosed=0, confirmed=0, pending=0, waiting_close=0) for r in members}
    for code in disclosures:
        sector = industry_at(members, code, cutoff)
        key = sector['industry_code'] or 'UNKNOWN'
        group = groups.setdefault(key, dict(industry_code=sector['industry_code'],
            industry=sector['industry_l1'], disclosed=0, confirmed=0, pending=0, waiting_close=0))
        group['disclosed'] += 1
        check = checks.get(code, {})
        group['confirmed'] += check.get('state') == 'confirmed'
        group['pending'] += check.get('state') not in ['confirmed', 'rejected']
        group['waiting_close'] += check.get('state') == 'pending' and check.get('reason') == '待收盘确认'
    rows = []
    for group in groups.values():
        group['ratio_pct'] = 100*group['confirmed']/group['disclosed'] if group['disclosed'] else None
        rows.append(group)
    return sorted(rows, key=lambda r: (r['industry_code'] is None, r['ratio_pct'] is None,
                                      -(r['ratio_pct'] or 0), -r['confirmed'], r['industry']))


def active_periods(today):
    year, month = int(today[:4]), int(today[5:7])
    if month < 4:
        return [f'{year-1}-12-31']
    if month <= 6:
        return [f'{year}-03-31'] + ([f'{year-1}-12-31'] if month == 4 else [])
    return [f'{year}-06-30' if month <= 9 else f'{year}-09-30']


def season_check(row, history, meta, calendar, cutoff, fetch_daily):
    code, ann, end = row['SECUCODE'], row['NOTICE_DATE'][:10], row['REPORTDATE'][:10]
    reaction = reaction_day(ann, calendar)
    result = dict(ann_date=ann, reaction_date=reaction, state='pending')
    if not reaction or reaction > cutoff:
        return dict(result, reason='待收盘确认')
    profit, growth = amounts(row, history)
    if profit is None or growth is None:
        return dict(result, reason='单季财务数据待补')
    listed = meta.get(code, {}).get('list_date')
    if row['SECURITY_NAME_ABBR'].upper().startswith(('ST', '*ST')) or profit < 0 or growth < 30:
        return dict(result, state='rejected', reason='财务或ST条件不符')
    if not listed:
        return dict(result, reason='上市资料待补')
    if (date.fromisoformat(reaction)-date.fromisoformat(listed)).days < 90:
        return dict(result, state='rejected', reason='上市不足90日')
    before = prior_date(reaction, calendar)
    try:
        bars = {b['date']: b for b in fetch_daily(code, before, reaction)}
        if before not in bars or reaction not in bars:
            return dict(result, reason='反应日或前日行情待补')
        bar, previous = bars[reaction], bars[before]['close']
        passed = qualifies(bar['open'], bar['low'], bar['close'], previous, report_kind(end))
        return dict(result, state='confirmed' if passed else 'rejected', reason='收盘断层确认' if passed else '行情条件不符')
    except Exception:
        return dict(result, reason='反应日日线待补')


def refresh(input_dir=None):
    now = datetime.now(u.TZ)
    today = now.date().isoformat()
    closed = today if (now.hour, now.minute) >= (15, 10) else (now.date()-timedelta(days=1)).isoformat()
    live = json.loads((input_dir/'live.json').read_text('utf-8')) if input_dir else read('live.json', {})
    history = read('history.json', [])
    calendar = sorted(set(read('calendar.json', [])) | set(live.get('reaction_calendar', [])))
    if not calendar or not live.get('reaction_calendar_start', '9999') <= today <= live.get('reaction_calendar_end', ''):
        raise RuntimeError('展示数据所需交易日历未覆盖今天')
    closed = max(d for d in calendar if d <= closed)
    client = Tushare()
    cache = read('display_cache.json', {})
    members = cache.get('members', [])
    if cache.get('industry_asof') != today:
        members = []
        for flag in ['Y', 'N']:
            members += client.pages('index_member_all', 'ts_code,l1_code,l1_name,in_date,out_date', 2000, is_new=flag)
        if len({r['ts_code'] for r in members}) < 4000:
            raise RuntimeError('行业覆盖异常，保留上次展示快照')
        cache.update(members=members, industry_asof=today)
        write('display_cache.json', cache)
    print(json.dumps(dict(stage='industry_ready', members=len(members))), flush=True)
    old = read('display_context.json', {})
    features = dict(old.get('features', {}))
    pb_pairs = {(r.get('ts_code'), v.get('pb_date')): v for r in history + live.get('records', [])
                if (v := features.get(r['id'])) and v.get('pb_status') != '待补数据'}
    monitor = json.loads((input_dir/'monitor.json').read_text('utf-8')) if input_dir else read('monitor.json', {})
    records = history + live.get('records', []) + monitor.get('reports', [])
    pb_requests = 0
    for row in records:
        ident = row['id']
        reaction = row.get('reaction_date') or reaction_day(row['ann_date'], calendar)
        anchor = prior_date(reaction, calendar)
        current = features.get(ident, {})
        # Historical values remain anchored to the original signal, never today's PB.
        if (row['ts_code'], anchor) in pb_pairs:
            current = pb_pairs[(row['ts_code'], anchor)]
        elif current.get('pb_date') != anchor or current.get('pb_status') == '待补数据':
            if row in history:
                current = dict(pb_feature([], anchor), **industry_at(members, row['ts_code'], anchor or today))
            elif row.get('financial_eligible') is False or not anchor or anchor >= today or pb_requests >= 60:
                current = pb_feature([], anchor)
            else:
                start = (date.fromisoformat(anchor)-timedelta(days=1097)).isoformat() if anchor else today
                pb_requests += 1
                values = client('daily_basic', 'ts_code,trade_date,pb', ts_code=row['ts_code'],
                                start_date=start.replace('-', ''), end_date=(anchor or today).replace('-', ''))
                current = pb_feature(values, anchor)
                pb_pairs[(row['ts_code'], anchor)] = current
        features[ident] = dict(current, **industry_at(members, row['ts_code'], anchor or today))
    print(json.dumps(dict(stage='features_ready', features=len(features), calls=client.calls)), flush=True)
    write('display_context.json', dict(old, features=features))
    meta = read('stock_metadata.json', {})
    seasons = []
    sources = FinancialSources(DATA, u.finance, u.financial_histories, u.cninfo)
    for end in active_periods(today):
        # Actual publication dates only; never count reservations/pre_date as disclosed.
        dates = client.pages('disclosure_date', 'ts_code,end_date,actual_date', 3000, end_date=end.replace('-', ''))
        disclosures = {}
        for row in dates:
            stamp = iso_date(row.get('actual_date'))
            if row['ts_code'].endswith(('.SH', '.SZ')) and row['ts_code'][0] in '036' and stamp and stamp <= today:
                disclosures[row['ts_code']] = min(stamp, disclosures.get(row['ts_code'], stamp))
        # Include independently verified formal reports if disclosure_date is lagging.
        start = (date.fromisoformat(end)+timedelta(days=1)).isoformat()
        financial = sources.discover(start, today)
        financial = [r for r in financial if r['REPORTDATE'][:10] == end]
        first = {}
        for row in sorted(financial, key=lambda r:r['NOTICE_DATE']):
            first.setdefault(row['SECUCODE'], row)
            code, stamp = row['SECUCODE'], row['NOTICE_DATE'][:10]
            if code.endswith(('.SH', '.SZ')) and code[0] in '036':
                disclosures[code] = min(stamp, disclosures.get(code, stamp))
        for notice in sources.catalog.values():
            if notice['end_date'] == end:
                code, stamp = notice['ts_code'], notice['ann_date']
                disclosures[code] = min(stamp, disclosures.get(code, stamp))
        previous = cache.get('seasons', {}).get(end, {})
        checks = {}
        missing = []
        for code, stamp in disclosures.items():
            row, prior = first.get(code), previous.get(code, {})
            if row and row['NOTICE_DATE'][:10] == stamp:
                if prior.get('state') in ['confirmed', 'rejected'] and prior.get('ann_date') == stamp:
                    checks[code] = prior
                else:
                    missing.append(row)
            else:
                checks[code] = dict(ann_date=stamp, state='pending', reason='首次披露版本待核验')
        histories = sources.histories(missing)
        print(json.dumps(dict(stage='season_financial_ready', end_date=end, disclosed=len(disclosures), check=len(missing))), flush=True)
        for row in missing:
            checks[row['SECUCODE']] = season_check(row, histories.get(row['SECUCODE'], []), meta, calendar, closed, u.daily)
        # The forward ledger is the authority for already verified close entries.
        for trade in live.get('records', []):
            code = trade['ts_code']
            if trade['end_date'] == end and trade.get('entry_date') and not trade.get('data_pending') and code in disclosures:
                if trade['ann_date'] == disclosures[code] and trade['entry_date'] <= closed:
                    checks[code] = dict(ann_date=trade['ann_date'], reaction_date=trade['entry_date'], state='confirmed', reason='线上收盘归档')
        rows = industry_summary(disclosures, checks, members, today)
        pending = sum(r['pending'] for r in rows)
        waiting = sum(r['waiting_close'] for r in rows)
        unknown = sum(r['disclosed'] for r in rows if r['industry_code'] is None)
        seasons.append(dict(end_date=end, disclosure_asof=today, close_asof=closed, industry_date=today,
            rows=rows, disclosed=len(disclosures), confirmed=sum(r['confirmed'] for r in rows),
            pending=pending, waiting_close=waiting, missing=pending-waiting, unknown_industry=unknown,
            status='PARTIAL' if pending or unknown else 'PASS'))
        cache.setdefault('seasons', {})[end] = checks
        write('display_cache.json', cache)
    result = dict(version=1, updated_at=now.isoformat(), asof=today, features=features, seasons=seasons,
        industry_basis='申万一级 SW2021；按成员纳入/剔除日期匹配，历史分类可能回溯修订',
        pb_basis='反应日前一市场交易日；自身近3个日历年正PB，含锚点；至少252个观测；相等值半权重',
        source='Tushare daily_basic / index_member_all / disclosure_date；东财→Tushare→Wind Excel单季财务；腾讯日线',
        source_live_updated_at=live.get('updated_at'), calls=client.calls)
    if old.get('history_import'):
        result['history_import'] = old['history_import']
    write('display_context.json', result)
    print(json.dumps(dict(status='PASS',features=len(features),seasons=seasons,calls=client.calls), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', type=Path, help='Read an isolated current live/monitor snapshot; never overwrite the ledger')
    args = parser.parse_args()
    try:
        refresh(args.input_dir)
    except Exception as exc:
        old = read('display_context.json', {})
        write('display_context.json', dict(old, refresh_status='FAILED', refresh_error=str(exc)[:120],
            refresh_attempt_at=datetime.now(u.TZ).isoformat()))
        raise

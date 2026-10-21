"""Read-only display enrichment. Never writes live.json or changes trading decisions."""
from bisect import bisect_left
from datetime import date, datetime, timedelta
import json
import os
import time

import requests

from financial_sources import FinancialSources, amounts, date as iso_date
from strategy_core import number, reaction_day
import update_data as u

DATA = u.DATA
INDUSTRY_RULE = 'financial_gap_no_close_cap_v1'
PB_YEARS = 5
PB_MINIMUM = 500


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
                  pb_status='待补数据', pb_source='Tushare daily_basic', pb_window_years=PB_YEARS, pb_minimum=PB_MINIMUM)
    if not anchor:
        return result
    day = date.fromisoformat(anchor)
    try:
        start = day.replace(year=day.year-PB_YEARS).isoformat()
    except ValueError:
        start = day.replace(year=day.year-PB_YEARS, day=28).isoformat()
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
    if len(positive) < PB_MINIMUM:
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
        return []
    if month <= 6:
        return [f'{year}-03-31']
    return [f'{year}-06-30' if month <= 9 else f'{year}-09-30']


def ledger_check(trade, stamp, end, cutoff):
    if not trade or trade.get('data_pending') or trade['ann_date'] != stamp or trade['end_date'] != end:
        return None
    reaction = trade.get('reaction_date')
    if not reaction or reaction > cutoff:
        return None
    if trade.get('entry_date') == reaction:
        state = 'confirmed'
    elif not trade.get('entry_date') and trade.get('status') in ['未入选', '剔除']:
        if trade.get('status_note') == '收盘涨幅不符':
            # This archived reason is emitted only after the opening gap and
            # unfilled-gap checks pass; confirm its remaining financial limits.
            profit, growth = number(trade.get('quarter_profit')), number(trade.get('quarter_yoy'))
            gap, gain = number(trade.get('open_gap_pct')), number(trade.get('signal_return_pct'))
            listed, name = iso_date(trade.get('list_date')), trade.get('name') or ''
            if (profit is None or profit < 0 or growth is None or growth < 30 or
                gap is None or gap < 2-1e-7 or gain is None or not listed or not name or
                name.upper().startswith(('ST','*ST')) or
                (date.fromisoformat(reaction)-date.fromisoformat(listed)).days < 90):
                return None
            return dict(ann_date=stamp, reaction_date=reaction, state='confirmed', industry_rule=INDUSTRY_RULE,
                        reason='涨幅超买入上限，仅计入行业断层统计')
        state = 'rejected'
    else:
        return None
    return dict(ann_date=stamp, reaction_date=reaction, state=state, reason='线上首次反应日已归档', industry_rule=INDUSTRY_RULE)


def cached_check(prior, stamp):
    if prior.get('ann_date') != stamp or prior.get('state') not in ['confirmed','rejected']:
        return None
    if prior.get('industry_rule') == INDUSTRY_RULE or prior.get('reason') in ['财务或ST条件不符','上市不足90日']:
        return dict(prior, industry_rule=INDUSTRY_RULE)
    return None


def industry_gap(open_price, low, previous):
    o, l, p = [round(float(x)*100) for x in [open_price,low,previous]]
    return p > 0 and o*100 >= p*102 and l > p


def financial_detail(code, end, stamp, trade, monitor, previous, row=None, history=None):
    """Exact first-disclosure values only; never borrow a later correction."""
    key = f'live-{code}-{end}-{stamp}'
    check = monitor.get('financial_checks', {}).get(key, {})
    reports = [r for r in monitor.get('reports', []) if r['ts_code'] == code and r['end_date'] == end
               and r['ann_date'] == stamp and r.get('complete')]
    exact_trade = trade if trade and trade.get('ann_date') == stamp and trade.get('end_date') == end else {}
    candidates = [exact_trade, previous if previous.get('ann_date') == stamp else {},
                  check if check.get('complete') else {}] + reports
    for candidate in candidates:
        profit, growth = number(candidate.get('quarter_profit')), number(candidate.get('quarter_yoy'))
        if profit is not None and growth is not None:
            return dict(quarter_profit=profit, quarter_yoy=growth,
                        financial_result='通过' if profit >= 0 and growth >= 30 else '未通过',
                        financial_source=candidate.get('financial_source') or '已有单季财务核验')
    if row and row['NOTICE_DATE'][:10] == stamp and history is not None:
        profit, growth = amounts(row, history)
        return dict(quarter_profit=profit, quarter_yoy=growth,
                    financial_result='待核验' if profit is None or growth is None else
                    '通过' if profit >= 0 and growth >= 30 else '未通过',
                    financial_source=row.get('FINANCIAL_SOURCE', '东财优先，既有备用源补缺'))
    return dict(quarter_profit=None, quarter_yoy=None, financial_result='待核验', financial_source=None)


def industry_companies(disclosures, checks, details, members, cutoff, end, first, ledger, monitor, catalog, meta, calendar):
    result = []
    notices = list(catalog) + monitor.get('reports', [])
    for code, stamp in disclosures.items():
        trade = ledger.get((code,end,stamp), {})
        row = first.get(code, {})
        exact = row if row.get('NOTICE_DATE', '')[:10] == stamp else {}
        choices = [r for r in notices if r['ts_code'] == code and r['end_date'] == end and r['ann_date'] == stamp]
        choices.sort(key=lambda r: bool(r.get('corrected')))
        notice = choices[0] if choices else {}
        check = checks.get(code, {})
        result.append(dict(ts_code=code, name=notice.get('name') or trade.get('name') or
            exact.get('SECURITY_NAME_ABBR') or meta.get(code, {}).get('name') or code,
            end_date=end, ann_date=stamp, reaction_date=check.get('reaction_date') or reaction_day(stamp, calendar),
            state=check.get('state', 'pending'), reason=check.get('reason', '待核验'),
            announcement_url=notice.get('url') or trade.get('announcement_url') or exact.get('ANNOUNCEMENT_URL'),
            **details.get(code, dict(quarter_profit=None, quarter_yoy=None, financial_result='待核验', financial_source=None)),
            **industry_at(members, code, cutoff)))
    return sorted(result, key=lambda r:(r['state']!='confirmed',r['financial_result']!='通过',r['ann_date'],r['ts_code']))


def market_detail(company, cutoff, calendar, trade, previous, fetch_daily):
    reaction = company.get('reaction_date')
    result = dict(market_date=reaction, open_gap_pct=None, close_return_pct=None,
                  market_source=None, market_note='反应日日线待核验')
    if not reaction or reaction > cutoff:
        return dict(result, market_note='待收盘确认')
    if previous.get('ann_date') == company['ann_date'] and previous.get('market_date') == reaction:
        gap, gain = number(previous.get('open_gap_pct')), number(previous.get('close_return_pct'))
        if gap is not None and gain is not None:
            return dict(result, open_gap_pct=gap, close_return_pct=gain,
                        market_source=previous.get('market_source'), market_note='已收盘')
    if (trade and not trade.get('data_pending') and trade.get('ann_date') == company['ann_date'] and
        trade.get('end_date') == company['end_date'] and trade.get('reaction_date') == reaction):
        gap, gain = number(trade.get('open_gap_pct')), number(trade.get('signal_return_pct'))
        if gap is not None and gain is not None:
            return dict(result, open_gap_pct=gap, close_return_pct=gain,
                        market_source='线上首次反应日日线归档', market_note='已收盘')
    before = prior_date(reaction, calendar)
    if not before:
        return result
    try:
        bars = {r['date']: r for r in fetch_daily(company['ts_code'], before, reaction)}
        bar = bars.get(reaction, {})
        previous_close, opening, close = [number(v) for v in
            [bars.get(before, {}).get('close'), bar.get('open'), bar.get('close')]]
        if any(v is None or v <= 0 for v in [previous_close, opening, close]):
            return result
        return dict(result, open_gap_pct=(opening/previous_close-1)*100,
                    close_return_pct=(close/previous_close-1)*100,
                    market_source='腾讯日线；反应日与前一市场交易日同口径', market_note='已收盘')
    except Exception:
        return result


def season_check(row, history, meta, calendar, cutoff, fetch_daily):
    code, ann, end = row['SECUCODE'], row['NOTICE_DATE'][:10], row['REPORTDATE'][:10]
    reaction = reaction_day(ann, calendar)
    result = dict(ann_date=ann, reaction_date=reaction, state='pending', industry_rule=INDUSTRY_RULE)
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
        passed = industry_gap(bar['open'], bar['low'], previous)
        market = market_detail(dict(ts_code=code,ann_date=ann,end_date=end,reaction_date=reaction),
                               cutoff,calendar,None,{},lambda *_:list(bars.values()))
        return dict(result, state='confirmed' if passed else 'rejected',
                    reason='收盘断层确认' if passed else '行情条件不符', **market)
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
                if (v := features.get(r['id'])) and v.get('pb_window_years') == PB_YEARS and v.get('pb_status') != '待补数据'}
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
        elif current.get('pb_window_years') != PB_YEARS or current.get('pb_date') != anchor or current.get('pb_status') == '待补数据':
            if row in history:
                current = dict(pb_feature([], anchor), **industry_at(members, row['ts_code'], anchor or today))
            elif row.get('financial_eligible') is False or not anchor or anchor >= today or pb_requests >= 60:
                current = pb_feature([], anchor)
            else:
                start = (date.fromisoformat(anchor)-timedelta(days=1830)).isoformat() if anchor else today
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
        details = {}
        detail_missing = []
        ledger = {(r['ts_code'],r['end_date'],r['ann_date']):r for r in live.get('records', [])}
        for code, stamp in disclosures.items():
            row, prior = first.get(code), previous.get(code, {})
            trade = ledger.get((code,end,stamp))
            details[code] = financial_detail(code,end,stamp,trade,monitor,prior)
            if details[code]['financial_result'] == '待核验' and row and row['NOTICE_DATE'][:10] == stamp:
                detail_missing.append(row)
            archived = ledger_check(trade,stamp,end,closed)
            if archived:
                checks[code] = archived
            elif row and row['NOTICE_DATE'][:10] == stamp:
                reused = cached_check(prior,stamp)
                if reused:
                    checks[code] = reused
                else:
                    missing.append(row)
            else:
                checks[code] = dict(ann_date=stamp, state='pending', reason='首次披露版本待核验')
        required_rows = {u_row['SECUCODE']:u_row for u_row in missing + detail_missing}
        histories = sources.histories(list(required_rows.values()))
        print(json.dumps(dict(stage='season_financial_ready', end_date=end, disclosed=len(disclosures), check=len(missing))), flush=True)
        for row in missing:
            checks[row['SECUCODE']] = season_check(row, histories.get(row['SECUCODE'], []), meta, calendar, closed, u.daily)
        for row in detail_missing:
            code = row['SECUCODE']
            details[code] = financial_detail(code,end,disclosures[code],ledger.get((code,end,disclosures[code])),
                monitor,previous.get(code,{}),row,histories.get(code,[]))
        for code in disclosures:
            checks[code].update(details[code])
        companies = industry_companies(disclosures,checks,details,members,today,end,first,ledger,monitor,
            sources.catalog.values(),meta,calendar)
        for company in companies:
            code, stamp = company['ts_code'], company['ann_date']
            prior = checks[code] if checks[code].get('market_date') else previous.get(code,{})
            market = market_detail(company,closed,calendar,ledger.get((code,end,stamp)),prior,u.daily)
            company.update(market)
            checks[code].update(market)
        rows = industry_summary(disclosures, checks, members, today)
        for group in rows:
            group['companies'] = [r for r in companies if r['industry_code'] == group['industry_code']]
            assert len(group['companies']) == group['disclosed'], '行业明细与分母不一致'
            assert sum(r['state']=='confirmed' for r in group['companies']) == group['confirmed'], '行业明细与分子不一致'
        pending = sum(r['pending'] for r in rows)
        waiting = sum(r['waiting_close'] for r in rows)
        unknown = sum(r['disclosed'] for r in rows if r['industry_code'] is None)
        seasons.append(dict(end_date=end, disclosure_asof=today, close_asof=closed, industry_date=today, industry_rule=INDUSTRY_RULE,
            rows=rows, disclosed=len(disclosures), confirmed=sum(r['confirmed'] for r in rows),
            pending=pending, waiting_close=waiting, missing=pending-waiting, unknown_industry=unknown,
            status='PARTIAL' if pending or unknown else 'PASS'))
        cache.setdefault('seasons', {})[end] = checks
        write('display_cache.json', cache)
    result = dict(version=1, industry_rule=INDUSTRY_RULE, updated_at=now.isoformat(), asof=today, features=features, seasons=seasons,
        industry_basis='申万一级 SW2021；按成员纳入/剔除日期匹配，历史分类可能回溯修订',
        pb_window_years=PB_YEARS, pb_minimum=PB_MINIMUM,
        pb_basis='反应日前一市场交易日；自身近5个日历年正PB，含锚点；至少500个观测；相等值半权重；上市不足5年按可得历史',
        source='Tushare daily_basic / index_member_all / disclosure_date；东财→Tushare→Wind Excel单季财务；腾讯日线',
        source_live_updated_at=live.get('updated_at'), calls=client.calls)
    if old.get('history_import'):
        result['history_import'] = old['history_import']
    write('display_context.json', result)
    print(json.dumps(dict(status='PASS',features=len(features),seasons=[{k:v for k,v in s.items() if k!='rows'}
        for s in seasons],calls=client.calls), ensure_ascii=False), flush=True)


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

"""Frozen earnings gap rules; daily bars are adjusted, displayed entry prices are raw."""
from __future__ import annotations

from datetime import date
import math

COST = .003
REASONS = {'target': '止盈', 'stop': '止损', 'time': '10日到期'}


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def net_return(price, entry):
    return (price / entry * (1 - COST) / (1 + COST) - 1) * 100


def report_kind(end):
    return {'03': 'Q1', '06': 'H1', '09': 'Q3', '12': 'FY'}.get(end[5:7])


def quarter_profit(current, previous, prior, prior_previous, end):
    values = [number(x) for x in [current, previous, prior, prior_previous]]
    if end[5:7] == '03':
        values[1] = values[3] = 0
    if any(x is None for x in values):
        return None, None
    profit, last = values[0] - values[1], values[2] - values[3]
    return profit, (profit - last) / abs(last) * 100 if last else None


def qualifies(open_price, low, close, previous, period):
    # Yuan-cent integer checks preserve strict <5/<7 and the gap boundary.
    o, l, c, p = [round(float(x) * 100) for x in [open_price, low, close, previous]]
    cap = 105 if period == 'H1' else 107
    return p > 0 and o * 100 >= p * 102 and l > p and c * 100 < p * cap


def simulate(record, bars, raw, calendar):
    """Rebuild one independent paper trade, including T+1 and prior-close protection."""
    byday = {b['date']: b for b in bars}; rawday = {b['date']: b for b in raw}
    reaction = next((d for d in calendar if d >= record['ann_date']), None)
    out = dict(record, reaction_date=reaction, origin='forward', status='等待开盘', entry_date=None,
               entry_price=None, exit_date=None, exit_price=None, profit_pct=None, exit_reason=None)
    if not reaction or reaction not in byday:
        return out
    index = calendar.index(reaction); bar = byday[reaction]; r = rawday.get(reaction, bar)
    before = [d for d in byday if d < reaction]
    if not before:
        return dict(out, status='待核验', status_note='缺少前收盘价')
    previous = byday[max(before)]['close']
    out.update(signal_return_pct=(bar['close'] / previous - 1) * 100,
               open_gap_pct=(bar['open'] / previous - 1) * 100)
    if bar['open'] < previous * 1.02 - 1e-8:
        return dict(out, status='未入选', status_note='高开不足2%')
    if bar['low'] <= previous + 1e-8:
        return dict(out, status='剔除', status_note='已补缺口')
    if not qualifies(r['open'], r['low'], r['close'], previous * r['close'] / bar['close'], record['report_period']):
        return dict(out, status='剔除', status_note='收盘涨幅不符')
    if record['name'].upper().startswith(('ST', '*ST')):
        return dict(out, status='剔除', status_note='ST股票')
    if (date.fromisoformat(reaction) - date.fromisoformat(record['list_date'])).days < 90:
        return dict(out, status='剔除', status_note='上市不足90日')
    entry = bar['close']; stop = entry * .92; target = entry * 1.10; peak = entry
    out.update(status='持有', entry_date=reaction, entry_price=r['close'], entry_basis=entry)
    for day in calendar[index + 1:]:
        if day not in byday:
            continue
        b = byday[day]; held = calendar.index(day) - index + 1
        if peak >= entry * 1.05 - 1e-8:
            stop = max(stop, entry * 1.02)
        price = reason = None
        # A locked limit down has no conservative sell fill; timeout rolls forward.
        rate = .2 if record['ts_code'].startswith(('688', '300', '301')) else .1
        earlier = [d for d in byday if d < day]
        prev = byday[max(earlier)]['close']; lower = round(prev * (1 - rate), 2)
        sellable = b['open'] > 0 and not (b['high'] <= lower + .005 and b['low'] >= lower - .005)
        if sellable:
            if b['open'] <= stop: price, reason = b['open'], 'stop'
            elif b['open'] >= target: price, reason = target, 'target'
            elif b['low'] <= stop: price, reason = stop, 'stop'
            elif b['high'] >= target: price, reason = target, 'target'
            elif held >= 10: price, reason = b['close'], 'time'
        if reason:
            display = price / b['close'] * rawday.get(day, b)['close']
            return dict(out, status='已卖出', exit_date=day, exit_price=display,
                        profit_pct=net_return(price, entry), exit_reason='保护止损' if reason=='stop' and stop>entry else REASONS[reason], hold_days=held)
        peak = max(peak, b['close'])
    last = byday[max(byday)]
    if peak >= entry * 1.05 - 1e-8:
        stop = max(stop, entry * 1.02)
    return dict(out, stop_basis=stop, target_basis=target, basis_last_close=last['close'],
                basis_date=last['date'], profit_pct=net_return(last['close'], entry),
                hold_days=sum(d >= reaction for d in calendar), armed=peak >= entry * 1.05 - 1e-8)

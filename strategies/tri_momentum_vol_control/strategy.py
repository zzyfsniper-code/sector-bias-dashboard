"""Frozen cash_t14_v20 rules. Quotes never enter the close-based signal."""
from __future__ import annotations

import numpy as np
import pandas as pd

VERSION = 'tri-momentum-vol-v1.1-20261015'
NAME = '三元动量波控策略'
CODES = ['159696.SZ', '510300.SH', '518880.SH']
NAMES = dict(zip(CODES, ['纳指ETF易方达', '沪深300ETF', '黄金ETF']))
INCEPTION = '2023-08-17'
LISTING = '2023-08-25'
BACKTEST_START = '2023-09-28'
BACKTEST_END = '2026-10-14'
FROZEN_ON = '2026-10-15'
TARGET = .14
COST = .001


def validate_prices(prices):
    if list(prices) != CODES or not prices.index.is_unique or not prices.index.is_monotonic_increasing:
        raise ValueError('Price columns/calendar invalid')
    if not np.isfinite(prices.to_numpy()).all() or not prices.gt(0).all().all():
        raise ValueError('Prices must be complete, finite and positive')


def signal(prices):
    validate_prices(prices)
    if len(prices) < 21:
        raise ValueError('21 closed prices required')
    scores = prices.iloc[-1] / prices.iloc[-20] - 1
    vol = prices.pct_change(fill_method=None).iloc[-20:].std(ddof=1) * np.sqrt(252)
    winner = str(scores.idxmax())
    sigma = float(vol[winner])
    if not np.isfinite(sigma):
        raise ValueError('Volatility unavailable')
    weight = min(1., TARGET / sigma) if sigma > 0 else 1.
    return dict(information_date=str(prices.index[-1].date()), selected_code=winner,
                selected_name=NAMES[winner], selected_score=float(scores[winner]),
                estimated_volatility=sigma, risk_weight=weight, cash_weight=1-weight,
                scores={c: float(scores[c]) for c in CODES},
                volatilities={c: float(vol[c]) for c in CODES})


def weekly_last(calendar):
    days = pd.DatetimeIndex(calendar).sort_values().unique()
    f = pd.Series(days, index=days)
    return set(f.groupby(days.to_period('W-FRI')).max())


def trade_fee(assets, equity, target, cost=COST):
    fee = 0.
    for _ in range(40):
        fee = float(cost * np.abs(target * (equity-fee) - assets).sum())
    return fee


def simulate(prices, calendar, start=BACKTEST_START, target_vol=TARGET, cost=COST):
    validate_prices(prices)
    weekly = weekly_last(calendar)
    changes = prices.pct_change(fill_method=None).fillna(0.)
    scores = prices / prices.shift(19) - 1
    vols = changes.rolling(20).std(ddof=1) * np.sqrt(252)
    weights = np.zeros(3)
    rows, records = [], []
    for i, day in enumerate(prices.index):
        beginning = weights.copy()
        contribution = beginning * changes.iloc[i].to_numpy()
        assets = beginning * (1 + changes.iloc[i].to_numpy())
        equity = 1 + contribution.sum()
        target = assets / equity
        fee = turnover = 0.
        if day >= pd.Timestamp(start) and day in weekly and i >= 21:
            s = scores.iloc[i-1]
            winner = int(np.argmax(s.to_numpy()))
            sigma = float(vols.iloc[i-1, winner])
            if not np.isfinite(sigma):
                raise ValueError('Incomplete volatility warmup')
            weight = min(1., target_vol / sigma) if target_vol is not None and sigma > 0 else 1.
            target = np.zeros(3)
            target[winner] = weight
            fee = trade_fee(assets, equity, target, cost)
            turnover = float(np.abs(target * (equity-fee)-assets).sum() / equity)
            before = assets / equity
            records.append(dict(execution_date=str(day.date()), information_date=str(prices.index[i-1].date()),
                                selected_code=CODES[winner], selected_name=NAMES[CODES[winner]],
                                selected_score=float(s.iloc[winner]), estimated_volatility=sigma,
                                risk_weight=weight, cash_weight=1-weight, turnover=turnover, fee=float(fee),
                                previous_weights={c: float(before[j]) for j, c in enumerate(CODES)},
                                target_weights={c: float(target[j]) for j, c in enumerate(CODES)},
                                record_type='历史模型调仓（非实际成交）'))
        weights = target
        if day >= pd.Timestamp(start):
            rows.append(dict(date=str(day.date()), **{'return': float(equity-fee-1)},
                             fee_return=-float(fee), turnover=turnover, risk_weight=float(weights.sum()),
                             cash_weight=float(1-weights.sum()),
                             **{f'contrib_{c}': float(contribution[j]) for j, c in enumerate(CODES)},
                             **{f'weight_{c}': float(weights[j]) for j, c in enumerate(CODES)}))
    frame = pd.DataFrame(rows).set_index('date')
    frame['nav'] = (1+frame['return']).cumprod()
    frame['drawdown'] = frame.nav / frame.nav.cummax().clip(lower=1) - 1
    return frame, records


def next_execution(calendar, today):
    days = pd.DatetimeIndex(calendar)
    if not len(days) or days.max() < pd.Timestamp(today)+pd.Timedelta(days=7):
        raise ValueError('Forward trading calendar unavailable')
    return min(d for d in weekly_last(days) if d >= pd.Timestamp(today)).strftime('%Y-%m-%d')

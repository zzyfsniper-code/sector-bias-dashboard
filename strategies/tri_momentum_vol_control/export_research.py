"""Export only the user-selected verified version, never the whole parameter search."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from strategy import (BACKTEST_END, BACKTEST_START, CODES, INCEPTION, LISTING,
                      NAME, VERSION, simulate, trade_fee, validate_prices)

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT/'tri-momentum-vol-control/data'
LOCAL = Path(__file__).resolve().parent/'data'


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', 'utf-8')
    temp.replace(path)


def measure(frame):
    returns = frame['return']
    nav = (1+returns).cumprod()
    dd = nav / nav.cummax().clip(lower=1) - 1
    growth = float(nav.iloc[-1]**(252/len(frame))-1)
    vol = float(returns.std(ddof=1)*np.sqrt(252))
    start, longest = None, 0
    for date, value in dd.items():
        if start is None and value <= -1e-10:
            start = pd.Timestamp(date)
        if start is not None and value > -1e-10:
            longest = max(longest, (pd.Timestamp(date)-start).days)
            start = None
    if start is not None:
        longest = max(longest, (pd.Timestamp(dd.index[-1])-start).days)
    return dict(annual_return=growth, cumulative_return=float(nav.iloc[-1]-1),
                annual_volatility=vol, max_drawdown=float(dd.min()),
                sharpe_rf0=float(returns.mean()*252/vol) if vol else None,
                calmar=growth/abs(float(dd.min())) if dd.min() else None,
                longest_underwater_days_exact=longest,
                mean_core_exposure=float(frame.risk_weight.mean()))


def attribution(frame, frequency):
    index = pd.DatetimeIndex(frame.index)
    keys = index.year if frequency == 'year' else index.to_period('M')
    columns = ['contrib_'+c for c in CODES]+['fee_return']
    rows = []
    for key, group in frame.groupby(keys):
        prior = (1+group['return']).cumprod().shift(fill_value=1)
        contributions = group[columns].mul(prior, axis=0).sum()
        total = float((1+group['return']).prod()-1)
        assert abs(contributions.sum()-total) < 1e-10
        rows.append(dict(id='cash_t14_v20', period=str(key), net_return=total,
                         start=group.index[0], end=group.index[-1],
                         **{c: float(contributions[c]) for c in columns}))
    return rows


def build_performance(prices, calendar, model, live, frozen):
    """Daily full-path model performance; never reset positions at the freeze boundary."""
    if live['version'] != VERSION or frozen['version'] != VERSION:
        raise ValueError('Performance version mismatch')
    dates = model.index.tolist()
    if dates[0] != BACKTEST_START or dates[-1] != live['data_as_of']:
        raise ValueError('Performance dates do not match the daily signal')
    frames = {'cash_t14_v20': model, 'baseline_three': simulate(prices, calendar, target_vol=None)[0]}
    for code in CODES:
        returns = prices[code].pct_change(fill_method=None).loc[BACKTEST_START:dates[-1]].copy()
        returns.iloc[0] = 1/1.001-1
        nav = (1+returns).cumprod()
        frames['hold_'+code] = pd.DataFrame({'nav':nav, 'drawdown':nav/nav.cummax().clip(lower=1)-1})
    curves = {key:dict(nav=frame.nav.tolist(), drawdown=frame.drawdown.tolist()) for key, frame in frames.items()}
    count = len(frozen['dates'])
    if dates[:count] != frozen['dates']:
        raise ValueError('Daily performance is missing frozen-history dates')
    for key in curves:
        for field in ['nav', 'drawdown']:
            np.testing.assert_allclose(curves[key][field][:count], frozen['curves'][key][field],
                                       atol=1e-8, rtol=0, err_msg='Frozen performance changed; review source differences')
    np.testing.assert_allclose(model.risk_weight.iloc[:count], frozen['risk_exposure'], atol=1e-8, rtol=0)
    return dict(version=VERSION, name=NAME, run_id=live['run_id'], status=live['status'],
                updated_at=live['updated_at'], data_as_of=live['data_as_of'], start=dates[0], end=dates[-1],
                frozen_end=frozen['end'], metrics=measure(model), dates=dates, curves=curves,
                risk_exposure=model.risk_weight.tolist(), source=live['history_source'],
                actual_fills_recorded=False, independent_out_of_sample=False)


def independent_ledger(prices, records):
    units, cash, previous, values = np.zeros(3), 1., 1., []
    orders = {r['execution_date']: r for r in records}
    for day, row in prices.loc[BACKTEST_START:BACKTEST_END].iterrows():
        equity = cash+float(units@row.to_numpy())
        order = orders.get(str(day.date()))
        if order:
            target = np.array([order['target_weights'][c] for c in CODES])
            fee = trade_fee(units*row.to_numpy(), equity, target)
            units = target*(equity-fee)/row.to_numpy()
            cash = (equity-fee)*(1-target.sum())
            equity -= fee
        values.append(equity/previous-1)
        previous = equity
    return np.array(values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--research', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    args = parser.parse_args()
    source = args.research
    result = json.loads((source/'research.json').read_text('utf-8'))
    verification = json.loads((source/'verification.json').read_text('utf-8'))
    assert verification['status'] == 'PASS'
    assert result['plan']['target_volatility'] == .14 and result['plan']['cost_bps_one_way'] == 10
    snapshot = json.loads(args.snapshot.read_text('utf-8-sig'))
    assert snapshot['status'] == 'PASS' and 'WDF.Addin' in snapshot['source']
    series = {}
    hashes = {}
    # Explicit release from the already verified research cache, not an updater fallback.
    for path, digest in result['input_hashes'].items():
        p = Path(path)
        if p.name not in ['etf_510300.csv', 'etf_518880.csv'] and not (
            p.name.startswith(('fund_daily_159696_', 'fund_adj_159696_'))):
            continue
        assert hashlib.sha256(p.read_bytes()).hexdigest() == digest
        hashes[str(p)] = digest
        if p.name.startswith('etf_'):
            f = pd.read_csv(p)
            code = str(f.code.iloc[0])
            assert f.code.eq(code).all() and not f.date.duplicated().any()
            series[code] = pd.Series(f.close.to_numpy(), index=pd.to_datetime(f.date))
    daily_parts, factor_parts = [], []
    for prefix, parts in [('fund_daily_159696_', daily_parts), ('fund_adj_159696_', factor_parts)]:
        for path in hashes:
            if Path(path).name.startswith(prefix):
                try:
                    parts.append(pd.read_csv(path, dtype={'trade_date':str}))
                except pd.errors.EmptyDataError:
                    continue
    raw = pd.concat(daily_parts).set_index('trade_date').sort_index()
    factors = pd.concat(factor_parts).set_index('trade_date').sort_index()
    assert raw.index.is_unique and factors.index.is_unique and raw.ts_code.eq(CODES[0]).all()
    factor = factors.adj_factor.reindex(raw.index)
    assert factor.notna().all() and factor.gt(0).all()
    adjusted = raw.close*factor/factor.iloc[-1]
    series[CODES[0]] = pd.Series(adjusted.to_numpy(), index=pd.to_datetime(adjusted.index))
    prices = pd.DataFrame({c: series[c] for c in CODES}).loc[LISTING:BACKTEST_END].astype(float)
    validate_prices(prices)
    assert str(prices.index[0].date()) == LISTING and str(prices.index[-1].date()) == BACKTEST_END
    calendar = sorted(set(snapshot['calendar']) | set(prices.index.strftime('%Y-%m-%d')))
    daily, records = simulate(prices, calendar)
    expected = pd.read_csv(source/'replace_159696_daily.csv.gz', index_col=0)
    assert list(daily.index) == list(expected.index)
    for col in ['return', 'nav', 'drawdown', 'fee_return', 'turnover']:
        np.testing.assert_allclose(daily[col], expected[col], atol=1e-9, rtol=0)
    np.testing.assert_allclose(daily['return'], independent_ledger(prices, records), atol=2e-12, rtol=0)
    signals = pd.read_csv(source/'replace_159696_trades.csv')
    assert len(signals) == len(records)
    for i, r in enumerate(records):
        assert r['execution_date'] == signals.iloc[i].execution_date
        assert r['information_date'] == signals.iloc[i].information_date
        assert r['selected_code'] == signals.iloc[i].selected_code
        np.testing.assert_allclose(r['risk_weight'], signals.iloc[i].risk_weight, atol=1e-9, rtol=0)
        r['origin'] = 'backtest'
    WEB.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    # Complete raw warmup stays local; public assets contain strategy output only.
    prices.to_csv(LOCAL/'seed_prices.csv', index_label='date', encoding='utf-8')
    daily.to_csv(WEB/'nav.csv', index_label='date', encoding='utf-8-sig')
    pd.DataFrame([{k: v for k, v in r.items() if not isinstance(v, dict)} for r in records]).to_csv(WEB/'rebalances.csv', index=False, encoding='utf-8-sig')
    curves = {}
    frames = {'cash_t14_v20': daily, 'baseline_three': simulate(prices, calendar, target_vol=None)[0]}
    for c in CODES:
        returns = prices[c].pct_change(fill_method=None).loc[BACKTEST_START:BACKTEST_END].copy()
        returns.iloc[0] = 1/1.001-1
        nav = (1+returns).cumprod()
        frames['hold_'+c] = pd.DataFrame({'nav':nav, 'drawdown':nav/nav.cummax().clip(lower=1)-1})
    for id, f in frames.items():
        curves[id] = dict(nav=f.nav.tolist(), drawdown=f.drawdown.tolist())
    metrics = measure(daily)
    backtest = dict(version=VERSION, name=NAME, variant='cash_t14_v20', start=BACKTEST_START, end=BACKTEST_END,
                    inception=INCEPTION, listing=LISTING, warmup_start=LISTING,
                    metrics=metrics, costs=[dict(cost_bps=bps, **measure(simulate(prices, calendar, cost=bps/10000)[0])) for bps in [0,10,20,30]],
                    annual=attribution(daily, 'year'), monthly=attribution(daily, 'month'),
                    dates=daily.index.tolist(), curves=curves, risk_exposure=daily.risk_weight.tolist(),
                    references=[],
                    source='Verified research cache: 159696 Tushare close + adjustment factor; 510300/518880 Wind Excel WDF.Addin WSD PriceAdj=F',
                    source_by_asset={CODES[0]:'Tushare historical close + adjustment factor (verified cached research)',
                                     **{c:'Wind Excel WDF.Addin WSD PriceAdj=F' for c in CODES[1:]}}, input_sha256=hashes,
                    research_batch=source.name, independent_out_of_sample=False,
                    verification=dict(status='PASS', daily_ledger_reconciled=True, weekly_signals_reconciled=True),
                    rules=[['资产池','纳指ETF易方达159696、沪深300 510300、黄金518880。现金仅承接余仓，不参与排名。'],
                           ['历史起点','易方达159696成立于2023-08-17、上市于2023-08-25。仅使用上市后真实价格，预热后自2023-09-28开始组合计账，不拼接上市前数据。'],
                           ['动量排名','20个收盘价格点（19段收益），P[t]/P[t−19]−1；最高者胜出。并列按纳指、沪深300、黄金顺序；全负仍选最高者。'],
                           ['波动率','赢家最近20段日收益的样本标准差（ddof=1）×√252，需要21个收盘价格点。'],
                           ['仓位','min(100%,14%/赢家年化波动率)，其余现金；零波动按满仓，缺失则拒绝计算。无杠杆，现金收益按0。'],
                           ['调仓时点','每周最后一个实际交易日14:50展示执行参考；前一交易日收盘数据决定标的和目标权重，收盘附近人工成交。'],
                           ['历史计账','历史以调仓日收盘成交，成交日收益归旧仓；同标的也按新目标权重调节，非调仓日自然漂移。'],
                           ['交易费用','按实际买卖金额各计单边10bp，现金不收证券交易费；仓位与费用闭合计算。'],
                           ['盘中行情','网页直接获取腾讯公开报价，只作参考与时效检查，不参与动量或目标仓位计算，不自动下单。']])
    save(WEB/'backtest.json', backtest)
    save(WEB/'history.json', dict(version=VERSION, backtest_end=backtest['end'], records=records, actual_fills_recorded=False))
    save(LOCAL/'export_verification.json', dict(status='PASS', version=VERSION, rows=len(daily), rebalances=len(records), input_sha256=hashes))
    print(json.dumps(dict(status='PASS', rows=len(daily), rebalances=len(records), metrics=metrics), ensure_ascii=False))


if __name__ == '__main__':
    main()

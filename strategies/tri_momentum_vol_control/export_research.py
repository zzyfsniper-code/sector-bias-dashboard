"""Export only the user-selected verified version, never the whole parameter search."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from strategy import CODES, NAMES, NAME, VERSION, simulate

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT/'tri-momentum-vol-control/data'
LOCAL = Path(__file__).resolve().parent/'data'


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', 'utf-8')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--research', type=Path, required=True)
    args = parser.parse_args()
    source = args.research
    result = json.loads((source/'research.json').read_text('utf-8'))
    verification = json.loads((source/'verification.json').read_text('utf-8'))
    assert verification['status'] == 'PASS'
    row = next(r for r in result['grid'] if r['id'] == 'cash_t14_v20')
    assert row['target_vol'] == .14 and row['volatility_window'] == 20 and row['cost_bps'] == 10
    series = {}
    hashes = {}
    for path, digest in result['input_hashes'].items():
        p = Path(path)
        assert hashlib.sha256(p.read_bytes()).hexdigest() == digest
        f = pd.read_csv(p)
        code = str(f.code.iloc[0])
        if code in CODES:
            series[code] = pd.Series(f.close.to_numpy(), index=pd.to_datetime(f.date))
            hashes[code] = digest
    prices = pd.DataFrame({c: series[c] for c in CODES}).loc['2018-07-01':'2026-09-18']
    daily, records = simulate(prices, prices.index)
    expected = pd.read_csv(source/'cash_t14_v20_daily.csv.gz', index_col=0)
    for col in ['return', 'nav', 'drawdown', 'fee_return', 'turnover']:
        np.testing.assert_allclose(daily[col], expected[col], atol=2e-12, rtol=0)
    signals = pd.read_csv(source/'cash_t14_v20_signals.csv')
    assert len(signals) == len(records)
    for i, r in enumerate(records):
        assert r['execution_date'] == signals.iloc[i].execution_date
        assert r['information_date'] == signals.iloc[i].information_date
        assert r['selected_code'] == signals.iloc[i].selected_code
        np.testing.assert_allclose(r['risk_weight'], signals.iloc[i].risk_weight, atol=1e-12)
    WEB.mkdir(parents=True, exist_ok=True)
    LOCAL.mkdir(parents=True, exist_ok=True)
    # Complete raw warmup stays local; public assets contain strategy output only.
    prices.to_csv(LOCAL/'seed_prices.csv', index_label='date', encoding='utf-8')
    daily.to_csv(WEB/'nav.csv', index_label='date', encoding='utf-8-sig')
    pd.DataFrame([{k: v for k, v in r.items() if not isinstance(v, dict)} for r in records]).to_csv(WEB/'rebalances.csv', index=False, encoding='utf-8-sig')
    curves = {}
    for id in ['cash_t14_v20', 'baseline_three', 'hold_513100.SH', 'hold_510300.SH', 'hold_518880.SH']:
        f = pd.read_csv(source/(id+'_daily.csv.gz'), index_col=0)
        curves[id] = dict(nav=f.nav.tolist(), drawdown=f.drawdown.tolist())
    backtest = dict(version=VERSION, name=NAME, variant='cash_t14_v20', start='2019-01-02', end='2026-09-18',
                    metrics=row['full'], costs=[r for r in result['stress'] if r['id']=='cash_t14_v20'],
                    annual=[r for r in result['annual'] if r['id']=='cash_t14_v20'],
                    monthly=[r for r in result['monthly'] if r['id']=='cash_t14_v20'],
                    dates=result['dates'], curves=curves, risk_exposure=daily.risk_weight.tolist(),
                    references=[r for r in result['references'] if r['id'] in curves],
                    source='Wind Excel WDF.Addin WSD PriceAdj=F', input_sha256=hashes,
                    research_batch=source.name, independent_out_of_sample=False,
                    verification=dict(status='PASS', daily_ledger_reconciled=True, weekly_signals_reconciled=True),
                    rules=[['资产池','纳指513100、沪深300 510300、黄金518880。现金仅承接余仓，不参与排名。'],
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
    print(json.dumps(dict(status='PASS', rows=len(daily), rebalances=len(records), metrics=row['full']), ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Independent nightly updater: Wind Excel only, no Codex or LLM calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from export_research import LOCAL, WEB, build_performance, save
from strategy import BACKTEST_END, CODES, FROZEN_ON, LISTING, NAME, VERSION, next_execution, signal, simulate

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'wind_excel'))
from wind_excel_provider import run_wsd_batch

TZ = timezone(timedelta(hours=8))


def build_live(prices, snapshot, now):
    calendar = sorted(set(snapshot['calendar']) | set(prices.index.strftime('%Y-%m-%d')))
    today = now.date().isoformat()
    expected = max(d for d in snapshot['calendar'] if d <= today)
    if now.hour < 16 and expected == today:
        expected = max(d for d in snapshot['calendar'] if d < today)
    if prices.index[-1].strftime('%Y-%m-%d') != expected:
        raise ValueError(f'Closed history incomplete: expected {expected}, got {prices.index[-1]}')
    frame, records = simulate(prices, calendar)
    # After a completed last-of-week session, show the next week's execution date.
    upcoming_from = today if now.hour < 16 else (now.date()+timedelta(days=1)).isoformat()
    execution = next_execution(calendar, upcoming_from)
    candidate = signal(prices)
    final_information = max(d for d in calendar if d < execution)
    candidate.update(execution_date=execution, required_information_date=final_information,
                     is_final=candidate['information_date'] == final_information,
                     status='FINAL' if candidate['information_date'] == final_information else 'PREVIEW')
    history = []
    for r in records:
        r['origin'] = 'backtest' if r['execution_date'] <= BACKTEST_END else 'frozen_model'
        if r['execution_date'] > BACKTEST_END:
            history.append(r)
    current = frame.iloc[-1]
    live = dict(status='PASS', version=VERSION, name=NAME, updated_at=now.isoformat(), data_as_of=expected,
                history_source='Wind Excel WDF.Addin WSD PriceAdj=F',
                intraday_source='腾讯公开报价（浏览器直连，不进入信号计算）',
                calendar=snapshot['calendar'], calendar_start=snapshot['calendar_start'], calendar_end=snapshot['calendar_end'],
                signal=candidate, model_current=dict(as_of=expected, last_execution_date=records[-1]['execution_date'],
                  weights={c: float(current['weight_'+c]) for c in CODES}, cash_weight=float(current.cash_weight),
                  note='历史规则推演持仓，非用户实际持仓'),
                frozen_on=FROZEN_ON, actual_fills_recorded=False, auto_order=False,
                execution_window='14:50:00-15:00:00 Asia/Shanghai',
                schedule=dict(time='18:10', engine='Windows Task Scheduler; no Codex dependency'),
                record_count=len(history), issues=[])
    return live, history, frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--reuse-run', type=Path)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    LOCAL.mkdir(parents=True, exist_ok=True)
    now = datetime.now(TZ)
    run_id = 'tri_'+now.strftime('%Y%m%d_%H%M%S')
    run = LOCAL/'runs'/run_id
    run.mkdir(parents=True, exist_ok=False)
    try:
        if args.snapshot:
            snapshot = json.loads(args.snapshot.read_text('utf-8-sig'))
        else:
            output = run/'wind_snapshot.json'
            subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                            str(Path(__file__).with_name('wind_snapshot.ps1')), '-OutputFile',str(output)],
                           check=True, timeout=100, capture_output=True)
            snapshot = json.loads(output.read_text('utf-8-sig'))
        if snapshot['status'] != 'PASS' or 'WDF.Addin' not in snapshot['source']:
            raise ValueError('Wind Excel calendar snapshot failed')
        if abs((now-datetime.fromisoformat(snapshot['observed_at'])).total_seconds()) > 1800:
            raise ValueError('Wind calendar snapshot is stale')
        end = max(d for d in snapshot['calendar'] if d <= now.date().isoformat())
        if now.hour < 16 and end == now.date().isoformat():
            end = max(d for d in snapshot['calendar'] if d < end)
        if args.reuse_run:
            manifest = json.loads((args.reuse_run/'run_manifest.json').read_text('utf-8-sig'))
            if manifest.get('status') != 'PASS' or manifest.get('source') != 'Wind Excel add-in WDF.Addin':
                raise ValueError('Reused history is not a passed Wind Excel batch')
            frames = {q['code']: pd.read_csv(args.reuse_run/q['output_file']) for q in manifest['queries']}
        else:
            manifest, named = run_wsd_batch([dict(name='etf_'+c[:6], code=c, fields=['close'],
                start_date=LISTING, end_date=end, options='PriceAdj=F') for c in CODES],
                output_root=LOCAL/'wind', timeout_seconds=90)
            frames = {c: named['etf_'+c[:6]] for c in CODES}
        series = {}
        for c in CODES:
            q = next(q for q in manifest['queries'] if q['code'] == c)
            if 'PriceAdj=F' not in q['requested_formula']:
                raise ValueError('Adjusted history required')
            f = frames[c]
            if not f.code.eq(c).all() or f.date.duplicated().any():
                raise ValueError('History identity/duplicates invalid')
            series[c] = pd.Series(pd.to_numeric(f.close, errors='raise').to_numpy(), index=pd.to_datetime(f.date)).sort_index()
        prices = pd.DataFrame({c: series[c] for c in CODES}).loc[LISTING:end]
        # No forward filling, partial rows, or substitution of old latest.json.
        live, history, model = build_live(prices, snapshot, now)
        live['run_id'] = run_id
        live['wind_run_id'] = manifest['run_id']
        live['price_sha256'] = hashlib.sha256(prices.to_csv().encode()).hexdigest()
        frozen_history = json.loads((WEB/'history.json').read_text('utf-8'))
        if frozen_history['version'] != VERSION or frozen_history['backtest_end'] != BACKTEST_END:
            raise ValueError('Frozen history version mismatch; release the matching backtest first')
        records = [r for r in frozen_history['records'] if r['execution_date'] <= BACKTEST_END] + history
        live['total_history_records'] = len(records)
        frozen = json.loads((WEB/'backtest.json').read_text('utf-8'))
        performance = build_performance(prices, sorted(set(snapshot['calendar']) | set(prices.index.strftime('%Y-%m-%d'))), model, live, frozen)
        # Immutable frozen curves remain separate from the nightly model ledger.
        prices.to_csv(run/'prices.csv', index_label='date')
        model.to_csv(run/'model_daily.csv', index_label='date')
        save(run/'live.json', live)
        save(run/'performance.json', performance)
        save(WEB/'live.json', live)
        save(WEB/'performance.json', performance)
        save(WEB/'history.json', dict(version=VERSION, backtest_end=BACKTEST_END, records=records, actual_fills_recorded=False))
        pd.DataFrame([{k: v for k, v in r.items() if not isinstance(v, dict)} for r in records]).to_csv(WEB/'rebalances.csv', index=False, encoding='utf-8-sig')
        report = dict(status='PASS', run_id=run_id, version=VERSION, data_as_of=live['data_as_of'],
                      calendar_end=live['calendar_end'], signal=live['signal'], publish='NOT_REQUESTED')
        if args.publish:
            from publish import publish
            report['publish'] = publish(['tri-momentum-vol-control/data/live.json',
                'tri-momentum-vol-control/data/history.json','tri-momentum-vol-control/data/rebalances.csv',
                'tri-momentum-vol-control/data/performance.json'],
                'Update three-asset momentum volatility signal '+live['data_as_of'])
        save(LOCAL/'latest.json', report)
        print(json.dumps(report, ensure_ascii=False))
    except Exception as error:
        save(run/'failure.json', dict(status='FAIL', run_id=run_id, error=str(error), failed_at=datetime.now(TZ).isoformat()))
        print(json.dumps(dict(status='FAIL', run_id=run_id, error=str(error)), ensure_ascii=False), file=sys.stderr)
        raise


if __name__ == '__main__':
    main()

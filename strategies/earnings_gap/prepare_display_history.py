"""One-time verified import of existing research PB values; no new historical API fetch."""
import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd
import display_context as d


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--research', type=Path, required=True)
    args = parser.parse_args()
    path = args.research / 'research_20261020_v24_pb5/results/events.parquet'
    events = pd.read_parquet(path).set_index('event_id', verify_integrity=True)
    assert len(events) == 3003
    payload = d.read('display_context.json', {})
    features = payload.setdefault('features', {})
    history = d.read('history.json', [])
    assert len(history) <= len(events) and len({r['id'] for r in history}) == len(history)
    for row in history:
        event = events.loc[int(row['id'].removeprefix('hist-'))]
        assert row['ts_code'] == event.ts_code
        assert row['reaction_date'] == event.gap_date.strftime('%Y-%m-%d')
        assert row['end_date'] == event.end_date.strftime('%Y-%m-%d')
        anchor = event.prev_date.strftime('%Y-%m-%d')
        pb = None if pd.isna(event.pb_prev) else float(event.pb_prev)
        rank = None if pd.isna(event.pb5) else float(event.pb5)
        status = '有效' if rank is not None else '待补数据' if pd.isna(event.pb_prev) else '无有效正PB' if pb <= 0 else '历史不足'
        features[row['id']] = dict(features.get(row['id'], {}), pb_date=anchor, pb=pb, pb_percentile=rank,
            pb_observations=int(event.pb_n5_prev), pb_window_years=5, pb_minimum=500, pb_status=status, pb_source='Tushare daily_basic；既有研究核验快照')
    payload.update(pb_window_years=5,pb_minimum=500,pb_basis='自身近5年正PB，至少500个观测；反应日前一交易日，等值半权重')
    payload['history_import'] = dict(rows=len(history), source=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    d.write('display_context.json', payload)
    print(json.dumps(dict(status='PASS', imported=len(history)), ensure_ascii=False))


if __name__ == '__main__':
    main()

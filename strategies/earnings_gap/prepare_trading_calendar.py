"""Export the existing local SSE calendar; no remote calls or source DB writes."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = Path('D:/agent工作目录/A股数据库/data/a_stock.duckdb')
    with duckdb.connect(str(source), read_only=True) as connection:
        rows = connection.execute("select cal_date,is_open from t_trade_cal where exchange='SSE' and cal_date between '2026-01-01' and '2026-12-31' order by cal_date").fetchall()
    expected = [date(2026, 1, 1) + timedelta(days=i) for i in range(365)]
    assert [r[0] for r in rows] == expected and all(str(r[1]) in ['0', '1'] for r in rows)
    opened = [d.isoformat() for d, flag in rows if str(flag) == '1']
    historical = json.loads((ROOT / 'earnings-gap/data/calendar.json').read_text('utf-8'))
    assert [d for d in historical if d.startswith('2026')] == [d for d in opened if d <= historical[-1]]
    result = dict(source='Tushare trade_cal SSE / existing local t_trade_cal read-only snapshot',
                  prepared_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                  coverage_start='2026-01-01', coverage_end='2026-12-31', open_dates=opened)
    (ROOT / 'earnings-gap/data/trading_calendar.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(status='PASS', coverage_start=result['coverage_start'], coverage_end=result['coverage_end'], open_dates=len(opened))))


if __name__ == '__main__': main()

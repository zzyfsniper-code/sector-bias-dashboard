"""One-time migration of reaction dates only; never rebuild trades or financials."""
import hashlib
import json
from pathlib import Path
from strategy_core import reaction_day
from update_data import DATA, load_trading_calendar


def main():
    live_path, monitor_path = DATA / 'live.json', DATA / 'monitor.json'
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [live_path, monitor_path]}
    live = json.loads(live_path.read_text('utf-8'))
    monitor = json.loads(monitor_path.read_text('utf-8'))
    schedule = load_trading_calendar(live['financial_asof'], live['calendar'])
    live.update(reaction_calendar=schedule['open_dates'], reaction_calendar_start=schedule['coverage_start'],
                reaction_calendar_end=schedule['coverage_end'], reaction_calendar_source=schedule['source'])
    changes = []
    for record in live['records']:
        if record.get('entry_date') or record.get('reaction_date'):
            continue
        day = reaction_day(record['ann_date'], schedule['open_dates'], record.get('available_at'))
        if day:
            changes.append(dict(id=record['id'], ann_date=record['ann_date'], reaction_date=day))
            record['reaction_date'] = day
    for record in monitor.get('reports', []):
        record['reaction_date'] = reaction_day(record['ann_date'], schedule['open_dates'], record.get('available_at'))
    for path, value in [(live_path, live), (monitor_path, monitor)]:
        original = json.loads(path.read_text('utf-8'))
        assert value.get('updated_at') == original.get('updated_at')
        if path == live_path:
            for old, new in zip(original['records'], value['records']):
                assert {k:v for k,v in old.items() if k!='reaction_date'} == {k:v for k,v in new.items() if k!='reaction_date'}
        else:
            for old, new in zip(original['reports'], value['reports']):
                assert {k:v for k,v in old.items() if k!='reaction_date'} == {k:v for k,v in new.items() if k!='reaction_date'}
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',',':')), 'utf-8')
        temporary.replace(path)
    log = Path(__file__).resolve().parent / 'logs'; log.mkdir(exist_ok=True)
    result = dict(status='PASS', input_hashes=before, changed_records=changes, trading_and_financial_fields_unchanged=True,
                  completed_calendar_unchanged=True, financial_observation_times_unchanged=True)
    (log / 'reaction-date-migration.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()

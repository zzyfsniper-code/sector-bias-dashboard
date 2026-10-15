"""Announcement coverage and processing evidence; never changes trading rules."""
from datetime import datetime, timedelta, timezone
import argparse
import json
import os
from pathlib import Path
import re

from strategy_core import quarter_profit

DATA = Path(__file__).resolve().parents[2] / 'earnings-gap/data'
TZ = timezone(timedelta(hours=8))


def read_monitor():
    path = DATA / 'monitor.json'
    return json.loads(path.read_text('utf-8')) if path.exists() else {}


def write_monitor(value):
    path = DATA / 'monitor.json'; temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')), 'utf-8')
    temp.replace(path)


def attempt(status, started_at=None):
    now = datetime.now(TZ).isoformat(); run = os.environ.get('GITHUB_RUN_ID')
    return dict(status=status, started_at=started_at or now, finished_at=now if status != 'running' else None,
                run_id=run, event=os.environ.get('GITHUB_EVENT_NAME', 'local'),
                run_url=f'https://github.com/zzyfsniper-code/sector-bias-dashboard/actions/runs/{run}' if run else None)


def begin():
    old = read_monitor(); value = dict(old, status='RUNNING', attempt=attempt('running'))
    write_monitor(value)
    return old, value['attempt']['started_at']


def failure(message, started_at=None):
    value = read_monitor()
    value.update(status='FAILED', attempt=attempt('failed', started_at or value.get('attempt', {}).get('started_at')), error=str(message)[:500])
    write_monitor(value)


def notice_record(item):
    title = re.sub('<[^>]*>', '', item.get('announcementTitle') or '')
    if any(word in title for word in ['摘要', '预告', '快报', '说明会', '审计', '英文', '取消', '提示性']):
        return None
    year = re.search(r'(20\d{2})\s*年', title)
    periods = [('第三季度', '09-30'), ('三季度', '09-30'), ('第一季度', '03-31'),
               ('一季度', '03-31'), ('半年度', '06-30'), ('半年', '06-30'), ('年度报告', '12-31'), ('年报', '12-31')]
    end = next((suffix for word, suffix in periods if word in title), None)
    code = str(item.get('secCode', ''))
    if not year or not end or '报告' not in title or len(code) != 6 or code[0] not in '036':
        return None
    url = item.get('adjunctUrl') or ''; date = re.search(r'/((?:20)\d{2}-\d{2}-\d{2})/', url)
    if not date:
        raise ValueError('正式报告缺少可核验的公告日期')
    return dict(id=str(item.get('announcementId') or url), ts_code=code + ('.SH' if code[0] == '6' else '.SZ'),
                name=item.get('secName') or code, ann_date=date[1], end_date=year[1] + '-' + end,
                title=title, url='https://static.cninfo.com.cn/' + url, corrected='更正' in title or '修订' in title)


def report_id(row):
    return f"live-{row['SECUCODE']}-{row['REPORTDATE'][:10]}-{row['NOTICE_DATE'][:10]}"


def financial_check(row, history, meta, checked_at):
    code = row['SECUCODE']; end = row['REPORTDATE'][:10]; ann = row['NOTICE_DATE'][:10]
    lookup = {}
    for item in history:
        if item['NOTICE_DATE'][:10] <= ann:
            lookup.setdefault(item['REPORTDATE'][:10], item['PARENT_NETPROFIT'])
    year = int(end[:4]); previous = {'03': None, '06': '03-31', '09': '06-30', '12': '09-30'}[end[5:7]]
    profit, yoy = quarter_profit(row['PARENT_NETPROFIT'], lookup.get(f'{year}-{previous}'),
                                lookup.get(f'{year-1}-{end[5:]}'), lookup.get(f'{year-1}-{previous}'), end)
    ready = profit is not None and yoy is not None and bool(meta.get(code, {}).get('list_date'))
    reason = '单季还原或上市资料不足' if not ready else '单季净利润为负' if profit < 0 else '单季同比不足30%' if yoy < 30 else '财务条件符合'
    return dict(cumulative_profit=row['PARENT_NETPROFIT'], quarter_profit=profit, quarter_yoy=yoy,
                complete=ready, eligible=ready and profit >= 0 and yoy >= 30, reason=reason, checked_at=checked_at)


def build(payload, finance_rows, selected_rows, previous, fetch_notices, fetch_histories, meta, verified):
    today = payload['financial_asof']; start = max('2026-10-10', (datetime.fromisoformat(today) - timedelta(days=40)).date().isoformat())
    catalog = {n['id']: n for n in previous.get('catalog', []) if start <= n['ann_date'] <= today}
    source_start = max(start, (datetime.fromisoformat(previous['source_asof']) - timedelta(days=2)).date().isoformat()) if previous.get('source_asof') else start
    issues = []; source_ok = False
    try:
        for item in fetch_notices(source_start, today):
            notice = notice_record(item)
            if notice and start <= notice['ann_date'] <= today: catalog[notice['id']] = notice
        source_ok = True
    except Exception as exc:
        issues.append('巨潮公告清单未完成核对：' + str(exc)[:180])
    selected_ids = {report_id(r) for r in selected_rows}
    checks = {k: v for k, v in previous.get('financial_checks', {}).items() if k in selected_ids}
    missing = [r for r in selected_rows if report_id(r) not in checks or checks[report_id(r)].get('cumulative_profit') != r['PARENT_NETPROFIT'] or not checks[report_id(r)].get('complete')]
    try:
        histories = fetch_histories(missing)
        for row in missing:
            checks[report_id(row)] = financial_check(row, histories.get(row['SECUCODE'], []), meta, payload['updated_at'])
    except Exception as exc:
        for row in missing: checks.pop(report_id(row), None)
        issues.append('筛选记录核验失败：' + str(exc)[:180])
    by_period = {}
    for row in sorted(finance_rows, key=lambda r: r['NOTICE_DATE'], reverse=True):
        if row['SECUCODE'][-2:] not in ['SH', 'SZ'] or row['SECUCODE'][0] not in '036': continue
        by_period.setdefault((row['SECUCODE'], row['REPORTDATE'][:10]), row)
    records = {r['id']: r for r in payload['records']}; rows = []
    for notice in sorted(catalog.values(), key=lambda n: (n['ann_date'], n['id']), reverse=True):
        item = dict(notice, complete=False, quarter_yoy=None, financial_eligible=False)
        row = by_period.get((notice['ts_code'], notice['end_date']))
        if notice['name'].upper().startswith(('ST', '*ST')):
            item.update(complete=True, result='已排除', reason='ST股票')
        elif row is None:
            item.update(result='待补数据', reason='巨潮已有正式公告，财务接口尚未覆盖')
        elif report_id(row) not in selected_ids:
            item.update(complete=True, result='已排除', reason='同日采用更新报告期')
        else:
            check = checks.get(report_id(row), {})
            item.update(complete=check.get('complete', False), quarter_yoy=check.get('quarter_yoy'),
                        financial_eligible=check.get('eligible', False), result='已筛选' if check.get('complete') else '待补数据',
                        reason=check.get('reason', '缺少可核验的单季财务数据'))
            if notice['corrected']:
                proof = verified.get(notice['url'], {})
                same = check.get('complete') and proof and abs(proof['quarter_profit'] - check['quarter_profit']) <= .011 and abs(proof['quarter_yoy'] - check['quarter_yoy']) <= .011
                if not same: item.update(complete=False, result='待复核', reason='更正公告尚未与单季财务值核对')
                else: item['reason'] += '；更正原文已核验'
            trade = records.get(report_id(row))
            if trade and item['complete'] and item['financial_eligible']:
                item.update(result=trade['status'], reason=trade.get('status_note') or trade.get('exit_reason') or '进入行情筛选')
                if trade.get('data_pending') or abs(trade.get('quarter_profit', check['quarter_profit']) - check['quarter_profit']) > .011:
                    item.update(complete=False, result='待复核', reason='行情数据待补或财务值已变化，信号记录需核验')
            elif item['complete'] and item['financial_eligible']:
                item.update(complete=False, result='待复核', reason='财务条件符合，但尚未建立行情跟踪记录')
        if notice['corrected'] and item['complete'] and '更正原文已核验' not in item['reason']:
            item['reason'] += '；更正原文已核验'
        rows.append(item)
    covered = {(n['ts_code'], n['end_date']) for n in catalog.values()}
    unmatched = [r for r in finance_rows if r['SECUCODE'][-2:] in ['SH', 'SZ'] and start <= r['NOTICE_DATE'][:10] <= today and (r['SECUCODE'], r['REPORTDATE'][:10]) not in covered]
    if unmatched: issues.append(f'{len(unmatched)}份财务记录未与巨潮正式公告清单对应')
    pending = sum(not r['complete'] for r in rows)
    if pending: issues.append(f'{pending}条正式公告尚未完成筛选或更正核验')
    if payload.get('issues'): issues.extend(payload['issues'])
    return dict(version=payload['version'], status='PARTIAL' if issues else 'PASS', checked_at=datetime.now(TZ).isoformat(),
                data_updated_at=payload['updated_at'], financial_asof=today, window_start=start,
                source_asof=today if source_ok else previous.get('source_asof'), source_status='PASS' if source_ok else 'FAILED',
                catalog=list(catalog.values()), financial_checks=checks, reports=rows, issues=issues,
                counts=dict(announcements=len(rows), companies=len({r['ts_code'] for r in rows}),
                            processed=len(rows)-pending, pending=pending, finance_records=len(by_period),
                            financial_candidates=sum(c.get('eligible', False) for c in checks.values()),
                            today_announcements=sum(r['ann_date'] == today for r in rows)))


def finish(payload, finance_rows, selected_rows, previous, started_at, fetch_notices, fetch_histories, meta):
    path = DATA / 'announcement_checks.json'
    verified = json.loads(path.read_text('utf-8')) if path.exists() else {}
    value = build(payload, finance_rows, selected_rows, previous, fetch_notices, fetch_histories, meta, verified)
    from profit_reasons import enrich
    value['profit_reason_counts'] = enrich(value['reports'], previous.get('reports', []))
    value['attempt'] = attempt('success', started_at)
    write_monitor(value)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--fail', required=True); args = parser.parse_args()
    failure(args.fail)

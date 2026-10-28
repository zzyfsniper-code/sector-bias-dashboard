"""Announcement coverage and processing evidence; never changes trading rules."""
from datetime import datetime, timedelta, timezone
import argparse
import json
import os
from pathlib import Path
import re

from strategy_core import quarter_profit, reaction_day, number

DATA = Path(__file__).resolve().parents[2] / 'earnings-gap/data'
TZ = timezone(timedelta(hours=8))


def is_a_share(code):
    return bool(re.fullmatch(r'(?:6\d{5}\.SH|[03]\d{5}\.SZ)', str(code)))


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
    if not end or '报告' not in title or len(code) != 6 or code[0] not in '036':
        return None
    identity = item.get('report_identity', {})
    if not year:
        if identity.get('code') != code or identity.get('period_end') != end or not re.fullmatch(r'[0-9a-f]{64}', identity.get('sha256', '')):
            return None
        year = re.fullmatch(r'(20\d{2})', str(identity.get('year', '')))
        if not year: return None
    url = item.get('adjunctUrl') or ''; date = re.search(r'/((?:20)\d{2}-\d{2}-\d{2})/', url)
    if not date:
        raise ValueError('正式报告缺少可核验的公告日期')
    return dict(id=str(item.get('announcementId') or url), ts_code=code + ('.SH' if code[0] == '6' else '.SZ'),
                name=item.get('secName') or code, ann_date=date[1], end_date=year[1] + '-' + end,
                title=title, url='https://static.cninfo.com.cn/' + url, corrected='更正' in title or '修订' in title,
                **({'report_identity': identity} if identity else {}))


def report_id(row):
    return f"live-{row['SECUCODE']}-{row['REPORTDATE'][:10]}-{row['NOTICE_DATE'][:10]}"


def report_scope_exclusion(notice, verified):
    proof = verified.get(notice.get('url'), {})
    if (proof.get('scope') != 'other_entity' or proof.get('publisher_code') != notice.get('ts_code') or
        not proof.get('report_subject_code') or proof['report_subject_code'] == notice.get('ts_code') or
        not re.fullmatch(r'[0-9a-f]{64}', proof.get('sha256', ''))):
        return None
    return dict(ts_code=notice['ts_code'], name=notice['name'], end_date=notice['end_date'], ann_date=notice['ann_date'],
                url=notice['url'], scope='other_entity', report_subject_code=proof['report_subject_code'],
                sha256=proof['sha256'], reason='报告主体为'+proof['company']+'，非本上市公司自身财报')


def financial_check(row, history, meta, checked_at):
    code = row['SECUCODE']; end = row['REPORTDATE'][:10]; ann = row['NOTICE_DATE'][:10]
    if end[5:7] == '12':
        return dict(cumulative_profit=row['PARENT_NETPROFIT'], quarter_profit=None, quarter_yoy=None,
                    complete=True, eligible=False, strategy_excluded=True, reason='年报不参与策略', checked_at=checked_at)
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
                financial_source=row.get('FINANCIAL_SOURCE','东方财富定期财报'),
                financial_components=[dict(report_period=x['REPORTDATE'][:10],notice_date=x['NOTICE_DATE'][:10],
                    source=x.get('FINANCIAL_SOURCE','东方财富定期财报')) for x in history if x['NOTICE_DATE'][:10]<=ann],
                complete=ready, eligible=ready and profit >= 0 and yoy >= 30, reason=reason, checked_at=checked_at)


def original_unchanged_report(record, records, verified):
    proof = verified.get(record.get('announcement_url'), {})
    if proof.get('document_kind') != 'corrected_report':
        proof = next((p for p in verified.values() if p.get('document_kind')=='corrected_report' and
                      all(p.get(k) is not None and p.get(k)==record.get(k) for k in ['ts_code','end_date','ann_date'])), {})
    if record.get('entry_date') or proof.get('document_kind') != 'corrected_report' or not re.fullmatch(r'[0-9a-f]{64}', proof.get('sha256', '')):
        return None
    def same(row):
        return all(number(row.get(k)) is not None and number(proof.get(k)) is not None and abs(number(row[k])-number(proof[k]))<=.011 for k in ['quarter_profit','quarter_yoy'])
    if not same(record): return None
    prior = [r for r in records if r['ts_code']==record['ts_code'] and r['end_date']==record['end_date'] and r['ann_date']<record['ann_date'] and same(r)]
    return min(prior, key=lambda r:r['ann_date']) if prior else None


def build(payload, finance_rows, selected_rows, previous, fetch_notices, fetch_histories, meta, verified):
    today = payload['financial_asof']; start = max('2026-10-10', (datetime.fromisoformat(today) - timedelta(days=40)).date().isoformat())
    excluded = {n['url']:n for n in previous.get('scope_exclusions', []) if n.get('scope')=='other_entity' and report_scope_exclusion(n, verified)}
    catalog = {}
    for notice in previous.get('catalog', []):
        if not start <= notice['ann_date'] <= today: continue
        outside = report_scope_exclusion(notice, verified)
        if outside: excluded[notice['url']] = outside
        else: catalog[notice['id']] = notice
    source_start = max(start, (datetime.fromisoformat(previous['source_asof']) - timedelta(days=2)).date().isoformat()) if previous.get('source_asof') else start
    issues = []; source_ok = False
    try:
        for item in fetch_notices(source_start, today):
            notice = notice_record(item)
            if notice and start <= notice['ann_date'] <= today:
                outside = report_scope_exclusion(notice, verified)
                if outside:
                    excluded[notice['url']] = outside
                    catalog.pop(notice['id'], None)
                else: catalog[notice['id']] = notice
        source_ok = True
    except Exception as exc:
        issues.append('巨潮公告清单未完成核对：' + str(exc)[:180])
    selected_ids = {report_id(r) for r in selected_rows}
    checks = {k: v for k, v in previous.get('financial_checks', {}).items() if k in selected_ids}
    for row in selected_rows:
        if row['REPORTDATE'][5:7] == '12':
            checks[report_id(row)] = financial_check(row, [], meta, payload['updated_at'])
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
        if not is_a_share(row['SECUCODE']): continue
        by_period.setdefault((row['SECUCODE'], row['REPORTDATE'][:10]), row)
    records = {r['id']: r for r in payload['records']}; rows = []; latest_notice = {}
    for notice in catalog.values():
        day=reaction_day(notice['ann_date'],payload.get('reaction_calendar',payload.get('calendar',[])),notice.get('available_at'))
        if day:latest_notice[(notice['ts_code'],day)]=max(latest_notice.get((notice['ts_code'],day),''),notice['end_date'])
    for notice in sorted(catalog.values(), key=lambda n: (n['ann_date'], n['id']), reverse=True):
        item = dict(notice, complete=False, quarter_profit=None, quarter_yoy=None, financial_eligible=False,
                    reaction_date=reaction_day(notice['ann_date'], payload.get('reaction_calendar', payload.get('calendar', [])), notice.get('available_at')))
        row = by_period.get((notice['ts_code'], notice['end_date']))
        correction_verified = False
        if notice['end_date'][5:7] == '12':
            item.update(complete=True, financial_eligible=False, strategy_excluded=True, result='已排除', reason='年报不参与策略')
        elif notice['name'].upper().startswith(('ST', '*ST')):
            item.update(complete=True, result='已排除', reason='ST股票')
        elif latest_notice.get((notice['ts_code'],item['reaction_date']),'')>notice['end_date']:
            item.update(complete=True, result='已排除', reason='同日采用更新报告期')
        elif row is None:
            reason='巨潮已有正式公告，东财/Tushare未补齐，待本机Wind Excel补数' if payload.get('financial_source_order') else '巨潮已有正式公告，财务接口尚未覆盖'
            item.update(result='待补数据', reason=reason)
        elif report_id(row) not in selected_ids:
            item.update(complete=True, result='已排除', reason='同日采用更新报告期')
        else:
            check = checks.get(report_id(row), {})
            item.update(complete=check.get('complete', False), quarter_profit=check.get('quarter_profit'), quarter_yoy=check.get('quarter_yoy'),
                        financial_source=check.get('financial_source',row.get('FINANCIAL_SOURCE','东方财富定期财报')),
                        financial_components=check.get('financial_components',[]),
                        financial_eligible=check.get('eligible', False), result='已筛选' if check.get('complete') else '待补数据',
                        reason=check.get('reason', '缺少可核验的单季财务数据'))
            if notice['corrected']:
                proof = verified.get(notice['url'], {})
                same = check.get('complete') and proof and abs(proof['quarter_profit'] - check['quarter_profit']) <= .011 and abs(proof['quarter_yoy'] - check['quarter_yoy']) <= .011
                correction_verified = bool(same)
                if not same: item.update(complete=False, result='待复核', reason='更正公告尚未与单季财务值核对')
                else: item['reason'] += '；更正原文已核验'
            trade = records.get(report_id(row))
            if trade and item['complete'] and item['financial_eligible']:
                item.update(result=trade['status'], reason=trade.get('status_note') or trade.get('exit_reason') or '进入行情筛选')
                if trade.get('data_pending') or abs(trade.get('quarter_profit', check['quarter_profit']) - check['quarter_profit']) > .011:
                    item.update(complete=False, result='待复核', reason='行情数据待补或财务值已变化，信号记录需核验')
                elif notice['corrected'] and trade.get('reaction_date') and (trade.get('ann_date')!=notice['ann_date'] or trade.get('original_signal_id')) and abs(trade.get('quarter_yoy', check['quarter_yoy'])-check['quarter_yoy'])<=.011:
                    detail='更正财务值未变，沿用首次财报反应日'
                    item.update(reaction_date=trade['reaction_date'], reason=item['reason']+('；'+detail if detail not in item['reason'] else ''))
            elif item['complete'] and item['financial_eligible']:
                item.update(complete=False, result='待复核', reason='财务条件符合，但尚未建立行情跟踪记录')
        if correction_verified and item['complete'] and '更正原文已核验' not in item['reason']:
            item['reason'] += '；更正原文已核验'
        rows.append(item)
    covered = {(n['ts_code'], n['end_date']) for n in catalog.values()}
    unmatched = []; exclusions = list(excluded.values())
    for row in finance_rows:
        code, end, ann = row['SECUCODE'], row['REPORTDATE'][:10], row['NOTICE_DATE'][:10]
        if not start <= ann <= today: continue
        reason = None
        if code.startswith(('200', '900')) and code.endswith(('.SZ', '.SH')): reason = 'B股不参与策略'
        elif is_a_share(code) and (code, end) not in covered:
            if str(row.get('ISNEW')) == '0' and any(n['ts_code'] == code and n['ann_date'] == ann and n['end_date'] > end for n in catalog.values()):
                reason = '本期正式报告的历史比较数据，不是独立公告'
            else: unmatched.append(row)
        if reason: exclusions.append(dict(ts_code=code, name=row.get('SECURITY_NAME_ABBR'), end_date=end, ann_date=ann, reason=reason))
    if unmatched: issues.append(f'{len(unmatched)}份财务记录未与巨潮正式公告清单对应')
    pending = sum(not r['complete'] for r in rows)
    if pending: issues.append(f'{pending}条正式公告尚未完成筛选或更正核验')
    if payload.get('issues'): issues.extend(payload['issues'])
    return dict(version=payload['version'], status='PARTIAL' if issues else 'PASS', checked_at=datetime.now(TZ).isoformat(),
                data_updated_at=payload['updated_at'], financial_asof=today, window_start=start,
                source_asof=today if source_ok else previous.get('source_asof'), source_status='PASS' if source_ok else 'FAILED',
                catalog=list(catalog.values()), financial_checks=checks, reports=rows, issues=issues, scope_exclusions=exclusions,
                counts=dict(announcements=len(rows), companies=len({r['ts_code'] for r in rows}),
                            processed=len(rows)-pending, pending=pending, finance_records=len(by_period),
                            financial_candidates=sum(c.get('eligible', False) for c in checks.values()),
                            today_announcements=sum(r['ann_date'] == today for r in rows)))


def finish(payload, finance_rows, selected_rows, previous, started_at, fetch_notices, fetch_histories, meta):
    path = DATA / 'announcement_checks.json'
    verified = json.loads(path.read_text('utf-8')) if path.exists() else {}
    value = build(payload, finance_rows, selected_rows, previous, fetch_notices, fetch_histories, meta, verified)
    value['attempt'] = attempt('success', started_at)
    write_monitor(value)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--fail', required=True); args = parser.parse_args()
    failure(args.fail)

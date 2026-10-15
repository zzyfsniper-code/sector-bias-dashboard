"""Extract company-stated profit explanations, separately from signal selection."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
import re
import time

import pdfplumber
import requests

TZ = timezone(timedelta(hours=8))
EXTRACTOR = 'profit-reason-v1'
CAUSE = re.compile(r'主要系|主要是|主要原因|所致|得益于')


def clean(value):
    return re.sub(r'\s+', '', value or '')


def profit_rank(label):
    label = clean(label)
    if any(x in label for x in ['扣除', '少数', '分配', '投资', '每股', '所得税']): return 0
    if '净利润' in label and ('归属于' in label or '归属母' in label): return 3
    if re.match(r'^(?:[一二三四五六七八九十\d、.（）()]+)?净利润', label): return 2
    return 1 if label.startswith('利润总额') else 0


def scope(label, header, end):
    month = end[5:7]
    cumulative = {'03': '第一季度', '06': '上半年累计', '09': '前三季度累计', '12': '全年累计'}[month]
    quarter = {'03': '第一季度', '06': '第二季度', '09': '第三季度', '12': '第四季度'}[month]
    if '年初' in label: return cumulative
    if '_本报告期' in label: return quarter if month in ['03', '09'] else cumulative
    if '年初' in header or re.search(r'1[-—~至－～][369]|1[-—~至－～]12', header): return cumulative
    if month == '03': return cumulative
    return '报告口径（未明确单季或累计）'


def explanation(label, reason, header, end, page, method):
    reason = clean(reason)
    if not CAUSE.search(reason) or len(reason) < 8: return None
    if re.fullmatch(r'主要系(?:报告期内|本期)?(?:净利润|利润总额|营业利润)(?:增加|减少|下降|上升)所致[。]?', reason): return None
    # Keep the company's first complete causal sentence; never infer causality from numbers.
    sentence = re.split(r'[。；]', reason, maxsplit=1)[0].rstrip('，,') + '。'
    if method == 'company-prose': sentence = sentence[sentence.index('主要'):]
    if len(sentence) > 500: return None
    return dict(status='FOUND', summary=sentence, scope=scope(clean(label), clean(header), end),
                page=page, metric=clean(label), evidence=clean(label) + '：' + reason,
                method=method, extractor=EXTRACTOR)


def table_explanations(tables, end, page):
    found = []
    for table in tables:
        column = None; header = ''; shared = None; period_hint = ''
        for row in table:
            cells = [clean(v) for v in row]
            if not cells: continue
            if '年初' in ''.join(cells): period_hint = ''.join(cells)
            cause_column = next((i for i, cell in enumerate(cells) if cell in ['变动原因', '主要原因', '原因说明', '变动原因说明']), None)
            if cause_column is not None:
                column = cause_column; header = period_hint + ''.join(cells); shared = None; continue
            if column is None and profit_rank(cells[0]) and CAUSE.search(cells[-1]): column = len(cells) - 1
            if column is None or column >= len(cells): continue
            label, reason = cells[0], cells[column]; rank = profit_rank(label)
            # A vertically merged cause may cover adjacent profit metrics, but not unrelated rows.
            if rank and not reason and shared:
                reason = shared
            elif reason in ['同上', '同上。'] and shared:
                reason = shared
            result = explanation(label, reason, header, end, page, 'company-table') if rank else None
            if result: found.append((rank, result))
            shared = reason if rank and CAUSE.search(reason) else None
    return found


def extract(content, end):
    candidates = []; text_chars = 0; scanned = 0
    with pdfplumber.open(BytesIO(content)) as doc:
        # Large annual reports are bounded; absence here never means the company did not explain.
        limit = min(len(doc.pages), 60)
        for index in range(limit):
            page = doc.pages[index]; text = page.extract_text() or ''; text_chars += len(text)
            if not text.strip(): scanned += 1
            if not CAUSE.search(clean(text)): continue
            if any(profit_rank(clean(line).split('主要')[0]) for line in text.splitlines()) or '变动' in text:
                candidates.extend(table_explanations(page.extract_tables(), end, index + 1))
            # Numbered prose explanations, e.g. "18、净利润较去年同期减少...主要系...".
            for line in text.splitlines():
                normalized = clean(line)
                match = re.match(r'^(?:\d+[、.])?(净利润|归属于(?:上市公司|母公司)股东的净利润)(.{0,100}?(?:主要系|主要是).+)', normalized)
                if match and ('。' in match[2] or match[2].endswith('所致')):
                    result = explanation(match[1], match[2], clean(text[:700]), end, index + 1, 'company-prose')
                    if result: candidates.append((profit_rank(match[1]), result))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        status = 'SCANNED' if text_chars < 100 and scanned else 'NOT_EXTRACTED'
        return dict(status=status, summary='扫描版报告，暂未自动提取原因' if status == 'SCANNED' else '未自动提取到明确的利润变动原因，请查原文',
                    scope='已检查前60页' if len(doc.pages) > limit else '已检查报告全文', extractor=EXTRACTOR)


def download(url):
    if not re.fullmatch(r'https://static\.cninfo\.com\.cn/finalpage/\d{4}-\d{2}-\d{2}/\d+\.PDF', url, re.I):
        raise ValueError('unsupported report source')
    with requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=(8, 20), stream=True) as response:
        response.raise_for_status(); chunks = []; size = 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 24 * 1024 * 1024: raise ValueError('report exceeds 24 MB')
            chunks.append(chunk)
        return b''.join(chunks)


def enrich(reports, previous=(), fetch=download, budget_seconds=180):
    """Cache by immutable report URL; corrections have a different URL and are re-read."""
    cached = {r['url']: r['profit_reason'] for r in previous if r.get('profit_reason', {}).get('extractor') == EXTRACTOR}
    deadline = time.monotonic() + budget_seconds
    for row in sorted(reports, key=lambda r: (not r.get('financial_eligible'), r['ann_date'])):
        prior = cached.get(row['url'])
        if prior and prior.get('status') not in ['ERROR', 'PENDING']:
            row['profit_reason'] = prior; continue
        if time.monotonic() >= deadline:
            row['profit_reason'] = dict(status='PENDING', summary='原因摘要待提取', extractor=EXTRACTOR); continue
        try:
            value = extract(fetch(row['url']), row['end_date'])
        except Exception as exc:
            value = dict(status='ERROR', summary='原文读取失败，待后续更新重试', error=type(exc).__name__, extractor=EXTRACTOR)
        value['checked_at'] = datetime.now(TZ).isoformat(); row['profit_reason'] = value
    return {status: sum(r['profit_reason']['status'] == status for r in reports) for status in ['FOUND', 'NOT_EXTRACTED', 'SCANNED', 'ERROR', 'PENDING']}

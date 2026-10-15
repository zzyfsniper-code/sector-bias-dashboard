import unittest
from unittest.mock import patch

from profit_reasons import EXTRACTOR, enrich, table_explanations, explanation


class ProfitReasonsTest(unittest.TestCase):
    def test_cumulative_company_explanation_is_not_relabelled_as_quarter(self):
        tables = [[['项目', '2026年1-9月', '2025年1-9月', '变动比例', '原因说明'],
                   ['归属于上市公司股东\n的净利润', '241', '200', '20.11%', '主要系特种纤维及电子布利润大幅增长所致']]]
        result = table_explanations(tables, '2026-09-30', 4)[0][1]
        self.assertEqual(result['scope'], '前三季度累计')
        self.assertEqual(result['summary'], '主要系特种纤维及电子布利润大幅增长所致。')
        self.assertEqual(result['page'], 4)

    def test_merged_cause_applies_to_adjacent_profit_but_not_cash_flow(self):
        tables = [[['项目名称', '变动比例（%）', '主要原因'],
                   ['利润总额_本报告期', '-34.83', '主要是上年同期转让股权增加投资收益影响。'],
                   ['归属于上市公司股东的净利润_本报告期', '-40.59', None],
                   ['经营活动产生的现金流量净额', '50', None]]]
        rows = table_explanations(tables, '2026-09-30', 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1][1]['scope'], '第三季度')
        self.assertEqual(rows[0][1]['summary'], rows[1][1]['summary'])

    def test_cash_revenue_and_minority_explanations_are_not_net_profit_cause(self):
        table = [['项目', '变动原因'], ['营业收入', '主要系销量增加所致'],
                 ['所得税费用', '主要系利润增加所致'], ['少数股东损益', '主要系子公司盈利所致']]
        self.assertEqual(table_explanations([table], '2026-09-30', 3), [])

    def test_no_inference_from_numeric_growth_or_ambiguous_scope(self):
        self.assertIsNone(explanation('净利润', '增长30%', '', '2026-09-30', 1, 'table'))
        self.assertIsNone(explanation('净利润', '主要系报告期内净利润增加所致。', '', '2026-09-30', 1, 'table'))
        value = explanation('净利润', '主要系销售价格上涨所致。', '', '2026-09-30', 1, 'table')
        self.assertIn('未明确', value['scope'])

    def test_continued_table_without_header_and_multiline_period_header(self):
        table = [['利润总额', '3.70', '主要系参股公司投资收益增加所致。']]
        self.assertEqual(table_explanations([table], '2026-09-30', 4)[0][1]['page'], 4)
        table = [['', '年初到报告期末', ''], ['利润表项目', '上年同期', '变动原因'],
                 ['利润总额', '60%', '主要系营业成本及销售费用减少所致。']]
        self.assertEqual(table_explanations([table], '2026-09-30', 3)[0][1]['scope'], '前三季度累计')

    def test_half_year_and_annual_report_period_is_cumulative(self):
        for end, expected in [('2026-06-30', '上半年累计'), ('2026-12-31', '全年累计')]:
            value = explanation('净利润_本报告期', '主要系销售价格上涨所致。', '', end, 2, 'table')
            self.assertEqual(value['scope'], expected)

    def test_daily_monitor_finish_persists_causes_without_changing_signal_counts(self):
        import json
        import tempfile
        from pathlib import Path
        import monitoring
        from test_monitoring import build, NOW
        snapshot = build(); expected = dict(snapshot['counts'])
        def add_reasons(rows, previous):
            rows[0]['profit_reason'] = {'status': 'FOUND', 'summary': '主要系销量增加所致。'}
            return {'FOUND': 1}
        with tempfile.TemporaryDirectory() as folder, patch.object(monitoring, 'DATA', Path(folder)), patch.object(monitoring, 'build', return_value=snapshot), patch('profit_reasons.enrich', side_effect=add_reasons):
            monitoring.finish({}, [], [], {}, NOW, None, None, {})
            saved = json.loads((Path(folder)/'monitor.json').read_text('utf-8'))
            self.assertEqual(saved['counts'], expected)
            self.assertEqual(saved['profit_reason_counts'], {'FOUND': 1})
            self.assertEqual(saved['reports'][0]['profit_reason']['status'], 'FOUND')

    def test_cache_keeps_report_and_correction_separate(self):
        previous = [{'url': 'old', 'profit_reason': {'status': 'FOUND', 'summary': '已核验', 'extractor': EXTRACTOR}}]
        rows = [dict(url=url, end_date='2026-09-30', ann_date='2026-10-14') for url in ['old', 'corrected']]
        fetched = []
        with patch('profit_reasons.extract', return_value={'status': 'FOUND', 'summary': '更正后', 'extractor': EXTRACTOR}):
            counts = enrich(rows, previous, fetch=lambda url: fetched.append(url))
        self.assertEqual(fetched, ['corrected']); self.assertEqual(counts['FOUND'], 2)
        self.assertEqual(rows[0]['profit_reason']['summary'], '已核验')

    def test_failed_report_fetch_is_explicit_and_retried_next_time(self):
        rows = [dict(url='report', end_date='2026-09-30', ann_date='2026-10-14', financial_eligible=True)]
        def unavailable(url): raise OSError('source offline')
        self.assertEqual(enrich(rows, fetch=unavailable)['ERROR'], 1)
        previous = [dict(rows[0])]
        with patch('profit_reasons.extract', return_value={'status': 'FOUND', 'extractor': EXTRACTOR}):
            self.assertEqual(enrich(rows, previous, fetch=lambda url: b'PDF')['FOUND'], 1)
        self.assertTrue(rows[0]['financial_eligible'])

    def test_budget_is_explicit_instead_of_silently_skipping(self):
        rows = [dict(url='report', end_date='2026-09-30', ann_date='2026-10-14')]
        self.assertEqual(enrich(rows, fetch=lambda url: self.fail('no budget'), budget_seconds=-1)['PENDING'], 1)


if __name__ == '__main__': unittest.main()

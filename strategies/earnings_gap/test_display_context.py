from datetime import date, timedelta
import unittest
from unittest.mock import Mock
import display_context as d


class DisplayTest(unittest.TestCase):
    def test_pb_ties_and_future_excluded(self):
        anchor = date(2026, 10, 19)
        rows = [dict(trade_date=(anchor-timedelta(days=i)).isoformat(), pb=2) for i in range(252)]
        rows += [dict(trade_date='2026-10-20', pb=100), dict(trade_date='2023-10-19', pb=100)]
        result = d.pb_feature(rows, anchor.isoformat())
        self.assertEqual(result['pb_percentile'], 50)
        self.assertEqual(result['pb_observations'], 252)

    def test_insufficient_nonpositive_and_missing_anchor_not_forward_filled(self):
        self.assertEqual(d.pb_feature([dict(trade_date='20261019', pb=2)], '2026-10-19')['pb_status'], '历史不足')
        self.assertEqual(d.pb_feature([dict(trade_date='20261019', pb=-2)], '2026-10-19')['pb_status'], '无有效正PB')
        self.assertIsNone(d.pb_feature([dict(trade_date='20261016', pb=2)], '2026-10-19')['pb'])
        self.assertEqual(d.prior_date('2026-10-19', ['2026-10-16','2026-10-19']), '2026-10-16')

    def test_industry_intervals_conflict_and_unknown(self):
        rows = [dict(ts_code='X', l1_code='A', l1_name='甲', in_date='20200101', out_date='20261019'),
                dict(ts_code='X', l1_code='B', l1_name='乙', in_date='20261019', out_date=None)]
        self.assertEqual(d.industry_at(rows, 'X', '2026-10-16')['industry_l1'], '甲')
        self.assertEqual(d.industry_at(rows, 'X', '2026-10-19')['industry_l1'], '乙')
        self.assertIsNone(d.industry_at(rows, 'Z', '2026-10-19')['industry_code'])
        rows.append(dict(rows[-1], l1_code='C'))
        self.assertIsNone(d.industry_at(rows, 'X', '2026-10-19')['industry_code'])

    def test_counts_deduplicated_subset_pending_and_unknown(self):
        members = [dict(ts_code=c, l1_code='A', l1_name='甲', in_date='20200101') for c in ['X','Y']]
        rows = d.industry_summary({'X':'2026-10-16','Y':'2026-10-17','Z':'2026-10-19'},
            {'X':dict(state='confirmed'), 'EXTRA':dict(state='confirmed')}, members, '2026-10-19')
        self.assertEqual(rows[0]['ratio_pct'], 50)
        self.assertEqual(rows[0]['disclosed'], 2)
        self.assertEqual(rows[0]['pending'], 1)
        self.assertEqual(rows[1]['industry'], '行业待核验')
        self.assertEqual(sum(r['confirmed'] for r in rows), 1)

    def test_intraday_not_confirmed_weekend_reacts_monday(self):
        row = dict(SECUCODE='600000.SH', NOTICE_DATE='2026-10-17', REPORTDATE='2026-03-31',
                   SECURITY_NAME_ABBR='测试', PARENT_NETPROFIT=200)
        history = [row,dict(SECUCODE='600000.SH', NOTICE_DATE='2025-04-01', REPORTDATE='2025-03-31', PARENT_NETPROFIT=100)]
        meta = {'600000.SH':dict(list_date='2000-01-01')}
        calendar = ['2026-10-16','2026-10-19']
        fetch = Mock(return_value=[dict(date='2026-10-16', close=100),dict(date='2026-10-19',open=102,low=101,close=103)])
        result = d.season_check(row,history,meta,calendar,'2026-10-16',fetch)
        self.assertEqual(result['state'], 'pending')
        fetch.assert_not_called()
        self.assertEqual(d.season_check(row,history,meta,calendar,'2026-10-19',fetch)['state'], 'confirmed')
        fetch.return_value[-1]['low'] = 100
        self.assertEqual(d.season_check(row,history,meta,calendar,'2026-10-19',fetch)['state'], 'rejected')

    def test_separate_annual_and_q1_periods(self):
        self.assertEqual(d.active_periods('2026-04-20'), ['2026-03-31','2025-12-31'])
        self.assertEqual(d.active_periods('2026-10-20'), ['2026-09-30'])


if __name__ == '__main__':
    unittest.main()

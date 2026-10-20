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

    def test_only_exact_first_reaction_final_ledger_result_reused(self):
        trade = dict(ann_date='2026-10-17', end_date='2026-09-30', reaction_date='2026-10-19', status='剔除')
        check = lambda **extra:d.ledger_check(dict(trade, **extra),'2026-10-17','2026-09-30','2026-10-19')
        self.assertEqual(check()['state'], 'rejected')
        self.assertEqual(check(entry_date='2026-10-19')['state'], 'confirmed')
        self.assertIsNone(check(data_pending=True))
        self.assertIsNone(check(status='观察'))
        self.assertIsNone(check(ann_date='2026-10-20'))
        self.assertIsNone(check(reaction_date='2026-10-20'))

    def test_financial_detail_does_not_borrow_later_correction(self):
        monitor=dict(financial_checks={},reports=[dict(ts_code='X',end_date='2026-09-30',ann_date='2026-10-20',
            complete=True,quarter_profit=100,quarter_yoy=50)])
        previous=dict(ann_date='2026-10-20',quarter_profit=100,quarter_yoy=50)
        value=d.financial_detail('X','2026-09-30','2026-10-17',None,monitor,previous)
        self.assertIsNone(value['quarter_profit'])
        self.assertEqual(value['financial_result'],'待核验')

    def test_exact_monitor_check_and_zero_profit_preserved(self):
        monitor=dict(financial_checks={'live-X-2026-09-30-2026-10-17':dict(complete=True,quarter_profit=0,quarter_yoy=30)},reports=[])
        value=d.financial_detail('X','2026-09-30','2026-10-17',None,monitor,{})
        self.assertEqual(value['quarter_profit'],0)
        self.assertEqual(value['financial_result'],'通过')

    def test_detail_financials_are_quarter_not_cumulative(self):
        row=dict(SECUCODE='X',NOTICE_DATE='2026-10-17',REPORTDATE='2026-09-30',PARENT_NETPROFIT=300)
        history=[row]+[dict(NOTICE_DATE=ann,REPORTDATE=end,PARENT_NETPROFIT=profit) for ann,end,profit in
            [('2026-08-01','2026-06-30',200),('2025-10-01','2025-09-30',150),('2025-08-01','2025-06-30',100)]]
        value=d.financial_detail('X','2026-09-30','2026-10-17',None,{}, {},row,history)
        self.assertEqual(value['quarter_profit'],100)
        self.assertEqual(value['quarter_yoy'],100)

    def test_industry_details_include_failures_unknown_and_one_company_once(self):
        disclosures={'X':'2026-10-17','Y':'2026-10-17','Z':'2026-10-17'}
        members=[dict(ts_code=c,l1_code='A',l1_name='甲',in_date='20200101') for c in ['X','Y']]
        checks={'X':dict(state='confirmed'),'Y':dict(state='rejected'),'Z':dict(state='pending')}
        details={'X':dict(quarter_profit=50,quarter_yoy=100,financial_result='通过'),
                 'Y':dict(quarter_profit=-10,quarter_yoy=-50,financial_result='未通过')}
        companies=d.industry_companies(disclosures,checks,details,members,'2026-10-20','2026-09-30',{}, {},{},[],{},['2026-10-16','2026-10-19'])
        self.assertEqual(len(companies),3)
        self.assertEqual(len({r['ts_code'] for r in companies}),3)
        self.assertEqual(companies[0]['state'],'confirmed')
        self.assertTrue(any(r['financial_result']=='未通过' for r in companies))
        self.assertTrue(any(r['industry_code'] is None for r in companies))
        self.assertTrue(all(r['reaction_date']=='2026-10-19' for r in companies))


if __name__ == '__main__':
    unittest.main()

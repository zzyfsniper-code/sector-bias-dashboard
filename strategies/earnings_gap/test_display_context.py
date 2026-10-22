from datetime import date, timedelta
import unittest
from unittest.mock import Mock
import display_context as d


class DisplayTest(unittest.TestCase):
    def test_pb_ties_and_future_excluded(self):
        anchor = date(2026, 10, 19)
        rows = [dict(trade_date=(anchor-timedelta(days=i)).isoformat(), pb=2) for i in range(500)]
        rows += [dict(trade_date='2026-10-20', pb=100), dict(trade_date='2021-10-19', pb=100)]
        result = d.pb_feature(rows, anchor.isoformat())
        self.assertEqual(result['pb_percentile'], 50)
        self.assertEqual(result['pb_observations'], 500)

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
        self.assertEqual(d.active_periods('2026-04-20'), ['2026-03-31'])
        self.assertEqual(d.active_periods('2026-02-20'), [])
        self.assertEqual(d.active_periods('2026-10-20'), ['2026-09-30'])

    def test_display_gap_has_no_close_gain_cap_but_keeps_gap_boundaries(self):
        from strategy_core import qualifies
        for end,previous,current in [('2026-03-31','2025-03-31',200),('2026-06-30','2025-06-30',300),('2026-09-30','2025-09-30',400)]:
            row=dict(SECUCODE='600000.SH',NOTICE_DATE='2026-10-19',REPORTDATE=end,SECURITY_NAME_ABBR='测试',PARENT_NETPROFIT=current)
            history=[row,dict(NOTICE_DATE='2025-01-01',REPORTDATE=previous,PARENT_NETPROFIT=current/2)]
            if end[5:7] != '03':
                prior='03-31' if end[5:7]=='06' else '06-30'
                history += [dict(NOTICE_DATE='2026-01-01',REPORTDATE='2026-'+prior,PARENT_NETPROFIT=100),
                            dict(NOTICE_DATE='2025-01-01',REPORTDATE='2025-'+prior,PARENT_NETPROFIT=50)]
            fetch=Mock(return_value=[dict(date='2026-10-16',close=100),dict(date='2026-10-19',open=103,low=102,close=120)])
            result=d.season_check(row,history,{'600000.SH':dict(list_date='2000-01-01')},['2026-10-16','2026-10-19'],'2026-10-19',fetch)
            self.assertEqual(result['state'],'confirmed');self.assertEqual(result['industry_rule'],d.INDUSTRY_RULE)
        self.assertFalse(qualifies(103,102,107,100,'Q3'))
        self.assertFalse(qualifies(103,102,105,100,'H1'))
        self.assertTrue(d.industry_gap(102,100.01,100))
        self.assertFalse(d.industry_gap(101.99,100.01,100))
        self.assertFalse(d.industry_gap(103,100,100))

    def test_only_cap_rejected_archive_is_promoted_for_display(self):
        trade=dict(ann_date='2026-10-17',end_date='2026-09-30',reaction_date='2026-10-19',status='剔除',
            status_note='收盘涨幅不符',quarter_profit=100,quarter_yoy=30,open_gap_pct=3,signal_return_pct=20,
            list_date='2000-01-01',name='测试')
        check=lambda **extra:d.ledger_check(dict(trade,**extra),'2026-10-17','2026-09-30','2026-10-19')
        self.assertEqual(check()['state'],'confirmed');self.assertIn('仅计入',check()['reason'])
        self.assertEqual(check(status_note='收盘量能不足1.45倍')['state'],'confirmed')
        self.assertEqual(check(status_note='已补缺口')['state'],'rejected')
        self.assertEqual(check(status_note='已补缺口')['reason'],'已补缺口')
        self.assertEqual(check(status_note='高开不足2%')['state'],'rejected')
        for extra in [dict(quarter_profit=-1),dict(quarter_yoy=29.99),dict(list_date='2026-10-01'),dict(name='ST测试'),dict(data_pending=True),dict(open_gap_pct=1.99)]:
            self.assertIsNone(check(**extra))
            self.assertIsNone(check(**dict(extra,status_note='收盘量能不足1.45倍')))

    def test_rejection_reason_uses_exact_finance_and_archive_without_guessing(self):
        row=dict(ts_code='X',ann_date='2026-10-17',end_date='2026-09-30',name='测试',state='rejected',
                 reason='线上首次反应日已归档',quarter_profit=100,quarter_yoy=50)
        trade=dict(row,status_note='已补缺口')
        self.assertEqual(d.rejection_reason(row,trade),'已补缺口')
        self.assertEqual(d.rejection_reason(dict(row,quarter_profit=-1),trade),'单季净利润为负')
        self.assertEqual(d.rejection_reason(dict(row,quarter_yoy=29.99),trade),'单季同比不足30%')
        self.assertEqual(d.rejection_reason(dict(row,name='*ST测试'),trade),'ST股票不参与')
        self.assertEqual(d.rejection_reason(dict(row,open_gap_pct=1.99)),'高开不足2%')
        self.assertEqual(d.rejection_reason(row,dict(trade,ann_date='2026-10-20')),'排除原因待核验')
        self.assertEqual(d.rejection_reason(row,dict(trade,data_pending=True)),'排除原因待核验')
        self.assertEqual(d.rejection_reason(dict(row,reason='上市不足90日')),'上市不足90日')

    def test_old_generic_market_cache_is_not_reused_as_no_cap(self):
        old=dict(ann_date='2026-10-17',state='rejected',reason='行情条件不符')
        self.assertIsNone(d.cached_check(old,'2026-10-17'))
        self.assertEqual(d.cached_check(dict(old,industry_rule=d.INDUSTRY_RULE),'2026-10-17')['state'],'rejected')
        self.assertEqual(d.cached_check(dict(old,reason='财务或ST条件不符'),'2026-10-17')['industry_rule'],d.INDUSTRY_RULE)
        self.assertIsNone(d.cached_check(dict(old,industry_rule=d.INDUSTRY_RULE),'2026-10-18'))

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

    def test_market_detail_weekend_reaction_and_both_returns_use_previous_close(self):
        company=dict(ts_code='X',ann_date='2026-10-17',end_date='2026-09-30',reaction_date='2026-10-19',financial_result='未通过')
        fetch=Mock(return_value=[dict(date='2026-10-16',close=100),dict(date='2026-10-19',open=103,close=107)])
        result=d.market_detail(company,'2026-10-19',['2026-10-16','2026-10-19'],None,{},fetch)
        self.assertAlmostEqual(result['open_gap_pct'],3)
        self.assertAlmostEqual(result['close_return_pct'],7)
        self.assertEqual(result['market_date'],'2026-10-19')
        fetch.assert_called_once_with('X','2026-10-16','2026-10-19')

    def test_market_detail_never_uses_unclosed_reaction_even_if_cache_has_prices(self):
        company=dict(ts_code='X',ann_date='2026-10-21',end_date='2026-09-30',reaction_date='2026-10-21')
        prior=dict(ann_date='2026-10-21',market_date='2026-10-21',open_gap_pct=3,close_return_pct=7)
        fetch=Mock()
        result=d.market_detail(company,'2026-10-20',['2026-10-20','2026-10-21'],None,prior,fetch)
        self.assertIsNone(result['open_gap_pct']);self.assertIsNone(result['close_return_pct'])
        self.assertEqual(result['market_note'],'待收盘确认');fetch.assert_not_called()

    def test_market_detail_reuses_exact_archive_and_zero_cached_return(self):
        company=dict(ts_code='X',ann_date='2026-10-17',end_date='2026-09-30',reaction_date='2026-10-19')
        trade=dict(company,open_gap_pct=3,signal_return_pct=8)
        fetch=Mock()
        result=d.market_detail(company,'2026-10-20',[],trade,{},fetch)
        self.assertEqual(result['close_return_pct'],8);fetch.assert_not_called()
        prior=dict(ann_date='2026-10-17',market_date='2026-10-19',open_gap_pct=0,close_return_pct=0)
        result=d.market_detail(company,'2026-10-20',[],trade,prior,fetch)
        self.assertEqual(result['open_gap_pct'],0);self.assertEqual(result['close_return_pct'],0);fetch.assert_not_called()

    def test_market_detail_does_not_borrow_other_reaction_or_missing_bar(self):
        company=dict(ts_code='X',ann_date='2026-10-17',end_date='2026-09-30',reaction_date='2026-10-19')
        fetch=Mock(return_value=[dict(date='2026-10-16',close=100),dict(date='2026-10-20',open=103,close=107)])
        prior=dict(ann_date='2026-10-18',market_date='2026-10-19',open_gap_pct=3,close_return_pct=7)
        trade=dict(company,reaction_date='2026-10-20',open_gap_pct=3,signal_return_pct=7)
        result=d.market_detail(company,'2026-10-20',['2026-10-16','2026-10-19'],trade,prior,fetch)
        self.assertIsNone(result['open_gap_pct']);self.assertIsNone(result['close_return_pct']);fetch.assert_called_once()
        fetch.side_effect=RuntimeError('offline')
        self.assertIsNone(d.market_detail(company,'2026-10-20',['2026-10-16','2026-10-19'],None,{},fetch)['close_return_pct'])

    def rows(self,n=500):
        anchor=date(2026,10,20)
        return [dict(trade_date=(anchor-timedelta(days=i)).isoformat(),pb=2) for i in range(n)]
    def test_uses_five_years_and_excludes_future_and_exact_left_boundary(self):
        rows=self.rows()+[dict(trade_date='2022-01-01',pb=1),dict(trade_date='2021-10-20',pb=100),dict(trade_date='2026-10-21',pb=100)]
        result=d.pb_feature(rows,'2026-10-20')
        self.assertEqual(result['pb_observations'],501)
        self.assertAlmostEqual(result['pb_percentile'],251/501*100)
        self.assertEqual(result['pb_window_years'],5);self.assertEqual(result['pb_minimum'],500)
    def test_minimum_is_500_positive_values(self):
        self.assertEqual(d.pb_feature(self.rows(499),'2026-10-20')['pb_status'],'历史不足')
        self.assertEqual(d.pb_feature(self.rows(),'2026-10-20')['pb_percentile'],50)
        rows=self.rows();rows[-1]['pb']=-1
        self.assertEqual(d.pb_feature(rows,'2026-10-20')['pb_status'],'历史不足')
    def test_conflicting_duplicate_is_not_averaged(self):
        with self.assertRaisesRegex(ValueError,'PB同日冲突'):
            d.pb_feature(self.rows()+[dict(trade_date='2026-10-20',pb=3)],'2026-10-20')
    def test_missing_anchor_is_not_forward_filled(self):
        rows=self.rows();rows[0]['trade_date']='2022-01-01'
        self.assertIsNone(d.pb_feature(rows,'2026-10-20')['pb_percentile'])


if __name__ == '__main__':
    unittest.main()

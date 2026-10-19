import unittest
from unittest.mock import patch

from strategy_core import qualifies, quarter_profit, simulate, net_return, reaction_day

CAL=['2026-10-08','2026-10-09','2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16','2026-10-19','2026-10-20','2026-10-21','2026-10-22']
RECORD=dict(id='test',ts_code='600000.SH',name='测试公司',list_date='2000-01-01',ann_date='2026-10-09',end_date='2026-09-30',report_period='Q3')
def bar(day,o,c,h,l):return dict(date=day,open=o,close=c,high=h,low=l)
def base():return [bar(CAL[0],100,100,101,99),bar(CAL[1],103,104,108,102)]


class RulesTest(unittest.TestCase):
    def test_strict_caps(self):
        self.assertFalse(qualifies(102,101,107,100,'Q3'))
        self.assertTrue(qualifies(102,101,106.99,100,'Q3'))
        self.assertFalse(qualifies(102,101,105,100,'H1'))
        self.assertTrue(qualifies(102,101,104.99,100,'H1'))
    def test_gap_boundaries(self):
        self.assertTrue(qualifies(102,100.01,103,100,'Q1'))
        self.assertFalse(qualifies(101.99,100.01,103,100,'Q1'))
        self.assertFalse(qualifies(102,100,103,100,'Q1'))
    def test_quarter_not_cumulative(self):
        # cumulative +10%, but quarter (110-70)/(100-80)-1 = +100%
        self.assertEqual(quarter_profit(110,70,100,80,'2026-09-30'),(40.0,100.0))
    def test_turnaround_and_zero_prior(self):
        self.assertEqual(quarter_profit(10,0,-10,0,'2026-03-31'),(10.0,200.0))
        self.assertIsNone(quarter_profit(10,0,0,0,'2026-03-31')[1])
    def test_missing_prior_fails_closed(self):
        self.assertEqual(quarter_profit(100,None,50,20,'2026-09-30'),(None,None))
    def test_t_plus_one(self):
        bars=base();bars[1]['high']=130
        self.assertEqual(simulate(RECORD,bars,bars,CAL[:2])['status'],'持有')
    def test_protection_effective_next_day(self):
        bars=base()+[bar(CAL[2],105,110,111,103),bar(CAL[3],108,107,108,105)]
        result=simulate(RECORD,bars,bars,CAL[:4])
        self.assertEqual(result['exit_date'],CAL[3]);self.assertEqual(result['exit_reason'],'保护止损')
        self.assertAlmostEqual(result['profit_pct'],net_return(104*1.02,104))
    def test_intraday_five_does_not_arm(self):
        bars=base()+[bar(CAL[2],105,106,110,103),bar(CAL[3],103,104,106,100)]
        result=simulate(RECORD,bars,bars,CAL[:4])
        self.assertEqual(result['status'],'持有');self.assertAlmostEqual(result['stop_basis'],104*.92)
    def test_open_target_precedes_later_low(self):
        bars=base()+[bar(CAL[2],120,100,121,90)]
        result=simulate(RECORD,bars,bars,CAL[:3]);self.assertEqual(result['exit_reason'],'止盈')
        self.assertAlmostEqual(result['profit_pct'],net_return(114.4,104))
    def test_daily_dual_touch_stop_first(self):
        bars=base()+[bar(CAL[2],104,105,120,90)]
        self.assertEqual(simulate(RECORD,bars,bars,CAL[:3])['exit_reason'],'止损')
    def test_ten_market_days_including_entry(self):
        bars=base()+[bar(day,104,104,105,103) for day in CAL[2:]]
        r=simulate(RECORD,bars,bars,CAL);self.assertEqual(r['exit_date'],CAL[10]);self.assertEqual(r['hold_days'],10)
    def test_locked_limit_down_defers_fill(self):
        bars=base()+[bar(CAL[2],93.6,93.6,93.6,93.6)]
        self.assertEqual(simulate(RECORD,bars,bars,CAL[:3])['status'],'持有')
    def test_no_critical_fetch_overwrite(self):
        import update_data
        path=update_data.DATA/'live.json';before=path.read_bytes()
        with patch.object(update_data,'finance',side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):update_data.update()
        self.assertEqual(path.read_bytes(),before)
    def test_latest_report_selected_before_financial_filter(self):
        from update_data import newest_reports
        a=dict(SECUCODE='600000.SH',REPORTDATE='2025-12-31',NOTICE_DATE='2026-04-25',PARENT_NETPROFIT=100)
        b=dict(SECUCODE='600000.SH',REPORTDATE='2026-03-31',NOTICE_DATE='2026-04-26',PARENT_NETPROFIT=-1)
        selected=newest_reports([a,b],['2026-04-24','2026-04-27'])
        self.assertEqual(selected,[b])
        self.assertEqual(newest_reports([a,b],['2026-04-24']),[b])

    def test_weekend_and_national_holiday_reaction_days(self):
        calendar=['2026-09-30','2026-10-08','2026-10-09','2026-10-12','2026-10-16','2026-10-19']
        for day in ['2026-10-17','2026-10-18']:
            self.assertEqual(reaction_day(day,calendar),'2026-10-19')
        for day in ['2026-10-01','2026-10-02','2026-10-07']:
            self.assertEqual(reaction_day(day,calendar),'2026-10-08')
        self.assertEqual(reaction_day('2026-10-10',calendar),'2026-10-12')
        self.assertEqual(reaction_day('2026-10-19',calendar),'2026-10-19')

    def test_verified_post_close_and_open_time_boundary(self):
        calendar=['2026-09-30','2026-10-08','2026-10-16','2026-10-19']
        self.assertEqual(reaction_day('2026-10-16',calendar,'2026-10-16T18:00:00+08:00'),'2026-10-19')
        self.assertEqual(reaction_day('2026-10-16',calendar,'2026-10-16T09:29:59+08:00'),'2026-10-16')
        self.assertEqual(reaction_day('2026-10-16',calendar,'2026-10-16T09:30:00+08:00'),'2026-10-19')
        self.assertEqual(reaction_day('2026-09-30',calendar,'2026-09-30T15:01:00+08:00'),'2026-10-08')
        self.assertEqual(reaction_day('2026-10-17',calendar,'2026-10-16T18:00:00+08:00'),'2026-10-19')
        self.assertEqual(reaction_day('2026-10-16',calendar,'2026-10-16T10:00:00Z'),'2026-10-19')
        with self.assertRaises(ValueError):reaction_day('2026-10-16',calendar,'2026-10-16T18:00:00')

    def test_unknown_next_session_is_not_guessed(self):
        self.assertIsNone(reaction_day('2026-10-17',['2026-10-16']))
        self.assertIsNone(reaction_day('2026-10-19',[]))

    def test_scheduled_sessions_do_not_inflate_holding_days(self):
        bars=base()
        full=CAL+['2026-10-23','2026-10-26']
        old=simulate(RECORD,bars,bars,CAL[:2])
        new=simulate(RECORD,bars,bars,CAL[:2],full)
        self.assertEqual(new,old);self.assertEqual(new['hold_days'],1)
        pending=simulate(dict(RECORD,ann_date='2026-10-17'),bars,bars,CAL[:2],full)
        self.assertEqual(pending['reaction_date'],'2026-10-19')
        self.assertEqual(pending['status'],'等待开盘');self.assertIsNone(pending['entry_date'])


if __name__=='__main__':unittest.main()

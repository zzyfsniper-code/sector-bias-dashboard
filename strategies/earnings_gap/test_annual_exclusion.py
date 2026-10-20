import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from datetime import datetime
import strategy_core as c
import update_data as u
import monitoring as m
from test_strategy import RECORD,CAL,base,bar

class AnnualExclusionTest(unittest.TestCase):
    def test_annual_cannot_open_even_with_perfect_gap(self):
        self.assertFalse(c.qualifies(103,102,104,100,'FY'))
        bars=base()
        result=c.simulate(dict(RECORD,report_period='FY'),bars,bars,CAL[:2])
        self.assertEqual(result['status'],'剔除');self.assertIsNone(result['entry_date'])
        self.assertEqual(result['status_note'],'年报不参与策略')

    def test_existing_annual_position_keeps_its_exit(self):
        bars=base()+[bar(CAL[2],120,100,121,90)]
        record=dict(RECORD,report_period='FY',entry_date=CAL[1],entry_price=104)
        result=c.simulate(record,bars,bars,CAL[:3])
        self.assertEqual(result['exit_reason'],'止盈');self.assertEqual(result['exit_date'],CAL[2])

    def test_q1_wins_same_day_selection_before_profit_filter(self):
        annual=dict(SECUCODE='600000.SH',REPORTDATE='2025-12-31',NOTICE_DATE='2026-04-20',PARENT_NETPROFIT=1000)
        q1=dict(annual,REPORTDATE='2026-03-31',PARENT_NETPROFIT=-1)
        self.assertEqual(u.newest_reports([annual,q1],['2026-04-20']),[q1])
        self.assertTrue(c.qualifies(103,102,104,100,'Q1'))

    def test_annual_finance_needs_no_prior_profit_or_metadata(self):
        row=dict(SECUCODE='600000.SH',REPORTDATE='2025-12-31',NOTICE_DATE='2026-10-20',PARENT_NETPROFIT=100)
        result=m.financial_check(row,[],{},'2026-10-20T08:25:00+08:00')
        self.assertTrue(result['complete']);self.assertFalse(result['eligible'])
        self.assertEqual(result['reason'],'年报不参与策略')

    def test_annual_is_covered_without_false_missing_data_or_correction_proof(self):
        payload=dict(version=c.VERSION,financial_asof='2026-10-20',updated_at='2026-10-20T08:25:00+08:00',
            records=[],issues=[],calendar=['2026-10-20'])
        notice=dict(secCode='600000',secName='测试',announcementId='annual',
            announcementTitle='2025年年度报告（更正后）',adjunctUrl='finalpage/2026-10-20/annual.PDF')
        histories=Mock(return_value={})
        result=m.build(payload,[],[],{},lambda *_:[notice],histories,{}, {})
        self.assertEqual(result['status'],'PASS');self.assertEqual(result['counts']['pending'],0)
        self.assertEqual(result['reports'][0]['reason'],'年报不参与策略')
        self.assertTrue(result['reports'][0]['complete']);self.assertFalse(result['reports'][0]['financial_eligible'])

    def test_update_does_not_create_or_fetch_annual_trade(self):
        annual=dict(SECUCODE='600000.SH',REPORTDATE='2025-12-31',NOTICE_DATE='2026-10-20',
                    PARENT_NETPROFIT=100,SECURITY_NAME_ABBR='测试')
        class Morning(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,10,20,8,25,tzinfo=u.TZ)
        sources=Mock();sources.discover.return_value=[annual];sources.histories.return_value={}
        sources.audit=[];sources.pending_wind=[]
        schedule=json.loads((u.DATA/'trading_calendar.json').read_text('utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)
            for name,value in [('live.json',{'records':[]}),('stock_metadata.json',{}),
                ('calendar.json',['2026-10-19']),('trading_calendar.json',schedule)]:
                (data/name).write_text(json.dumps(value),'utf-8')
            with patch.object(u,'DATA',data),patch.object(u,'datetime',Morning),patch.object(u,'daily',return_value=[]) as daily:
                payload,_,_=u.update(sources)
            self.assertEqual(payload['records'],[]);self.assertEqual(payload['version'],c.VERSION)
            sources.histories.assert_called_once_with([]);self.assertEqual(daily.call_count,1)
            self.assertIn('live-600000.SH-2025-12-31-2026-10-20',payload['checked_financial_ids'])

if __name__=='__main__':unittest.main()

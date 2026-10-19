import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock,patch
import financial_sources as f

ROW=dict(SECUCODE='601059.SH',REPORTDATE='2026-09-30',NOTICE_DATE='2026-10-19',PARENT_NETPROFIT=110,SECURITY_NAME_ABBR='测试')
HISTORY=[ROW,dict(SECUCODE=ROW['SECUCODE'],REPORTDATE='2026-06-30',NOTICE_DATE='2026-08-01',PARENT_NETPROFIT=70),
    dict(SECUCODE=ROW['SECUCODE'],REPORTDATE='2025-09-30',NOTICE_DATE='2025-10-20',PARENT_NETPROFIT=100),
    dict(SECUCODE=ROW['SECUCODE'],REPORTDATE='2025-06-30',NOTICE_DATE='2025-08-01',PARENT_NETPROFIT=80)]
NOTICE=dict(secCode='601059',secName='测试',announcementId='1',announcementTitle='2026年第三季度报告',adjunctUrl='finalpage/2026-10-19/1.PDF')


class SourcesTest(unittest.TestCase):
    def source(self,folder,primary=None,history=None):
        return f.FinancialSources(folder,Mock(return_value=[ROW] if primary is None else primary),
            Mock(return_value={ROW['SECUCODE']:HISTORY if history is None else history}),Mock(return_value=[NOTICE]))

    def test_complete_primary_never_calls_backups(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'tushare_income') as ts,patch.object(f,'wind_excel_cache') as wind:
            s=self.source(folder);hist=s.histories([ROW]);self.assertEqual(f.amounts(ROW,hist[ROW['SECUCODE']]),(40,100))
            ts.assert_not_called();wind.assert_not_called()

    def test_missing_current_is_discovered_from_formal_notice(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'tushare_income',return_value=HISTORY) as ts,patch.object(f,'wind_excel_cache') as wind:
            s=self.source(folder,primary=[],history=HISTORY[1:]);rows=s.discover('2026-10-10','2026-10-19')
            self.assertEqual(rows[0]['PARENT_NETPROFIT'],110);self.assertEqual(rows[0]['NOTICE_DATE'],'2026-10-19')
            self.assertEqual(rows[0]['ANNOUNCEMENT_URL'],'https://static.cninfo.com.cn/finalpage/2026-10-19/1.PDF')
            s.histories(rows);ts.assert_called_once();wind.assert_not_called()

    def test_partial_primary_is_not_overwritten(self):
        changed=[dict(x,PARENT_NETPROFIT=999) for x in HISTORY]
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'tushare_income',return_value=changed):
            s=self.source(folder,history=HISTORY[:2]);hist=s.histories([ROW])[ROW['SECUCODE']]
            chosen={r['REPORTDATE']:r['PARENT_NETPROFIT'] for r in hist}
            self.assertEqual(chosen['2026-09-30'],110);self.assertEqual(chosen['2026-06-30'],70)
            self.assertEqual(chosen['2025-09-30'],999)

    def test_wind_only_after_tushare_failure_and_never_retries(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'tushare_income',side_effect=RuntimeError('TUSHARE_API_403')) as ts,patch.object(f,'wind_excel_cache',return_value=HISTORY) as wind:
            s=self.source(folder,history=[]);s.histories([ROW]);s.histories([ROW])
            ts.assert_called_once();wind.assert_called_once();self.assertEqual([a['source'] for a in s.audit],['Tushare','Wind Excel'])

    def test_missing_all_stays_pending_not_zero(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'tushare_income',return_value=[]):
            s=self.source(folder,primary=[],history=[]);self.assertEqual(s.discover('2026-10-10','2026-10-19'),[])
            self.assertTrue(s.pending_wind);self.assertIn('2026-09-30',s.pending_wind[0]['missing_periods'])

    def test_future_source_rows_are_not_used(self):
        future=[dict(x,NOTICE_DATE='2026-10-20') for x in HISTORY]
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'tushare_income',return_value=future),patch.object(f,'wind_excel_cache',return_value=[]):
            s=self.source(folder,primary=[],history=[]);self.assertEqual(s.discover('2026-10-10','2026-10-19'),[])

    def test_tushare_only_consolidated_cumulative_and_available_dates(self):
        fields=['ts_code','ann_date','f_ann_date','end_date','report_type','n_income_attr_p']
        values=[['601059.SH','20261019','20261019','20260930','1',110],
            ['601059.SH','20261019','20261019','20260930','2',40],
            ['601059.SH','20261019','20261020','20260930','1',999],
            ['601059.SH','20261019','20261019','20260930','6',800],
            ['601198.SH','20261019','20261019','20260930','1',777]]
        response=Mock(status_code=200);response.json.return_value=dict(code=0,data=dict(fields=fields,items=values))
        with patch.dict('os.environ',TUSHARE_TOKEN='test-token'),patch.object(f.requests,'post',return_value=response) as post:
            rows=f.tushare_income('601059.SH','2026-10-19')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['PARENT_NETPROFIT'],110)
        self.assertEqual(post.call_args.kwargs['json']['params']['report_type'],'1')

    def test_conflicting_same_day_versions_are_unknown(self):
        response=Mock(status_code=200);response.json.return_value=dict(code=0,data=dict(fields=['ts_code','ann_date','end_date','report_type','n_income_attr_p'],
            items=[['601059.SH','20261019','20260930','1',100],['601059.SH','20261019','20260930','1',200]]))
        with patch.dict('os.environ',TUSHARE_TOKEN='test-token'),patch.object(f.requests,'post',return_value=response):
            self.assertEqual(f.tushare_income('601059.SH','2026-10-19'),[])

    def test_error_does_not_reveal_provider_message_or_token(self):
        response=Mock(status_code=200);response.json.return_value=dict(code=403,msg='secret-should-not-appear')
        with patch.dict('os.environ',TUSHARE_TOKEN='test-token'),patch.object(f.requests,'post',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'^TUSHARE_API_403$'):f.tushare_income('601059.SH','2026-10-19')

    def test_zero_profit_is_valid_and_kept(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'tushare_income') as ts:
            s=self.source(folder,history=HISTORY);zero=dict(ROW,PARENT_NETPROFIT=0)
            hist=s.histories([zero])[ROW['SECUCODE']]
            self.assertEqual(next(x for x in hist if x['REPORTDATE']=='2026-09-30')['PARENT_NETPROFIT'],0);ts.assert_not_called()

    def test_wind_cache_rejects_other_basis(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'wind_financial_fallback.json').write_text(json.dumps(dict(source='Wind Excel WDF.Addin',basis='deducted_profit',unit='CNY',rows=HISTORY)),'utf-8')
            with self.assertRaisesRegex(RuntimeError,'CACHE_INVALID'):f.wind_excel_cache(folder,'601059.SH','2026-10-19')

    def test_primary_outage_without_catalog_cannot_publish_empty_success(self):
        with tempfile.TemporaryDirectory() as folder:
            s=self.source(folder);s.primary.side_effect=RuntimeError('offline')
            with self.assertRaisesRegex(RuntimeError,'offline'):s.discover('2026-10-10','2026-10-19')
            s.fetch_notices.assert_not_called()

    def test_quota_or_auth_failure_stops_calls_for_other_codes(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'tushare_income',side_effect=RuntimeError('TUSHARE_API_403')) as ts:
            s=self.source(folder)
            for code in ['601059.SH','601198.SH']:
                with self.assertRaisesRegex(RuntimeError,'TUSHARE_API_403'):s.tushare(code,'2026-10-19')
            ts.assert_called_once()

    def test_repaired_notice_reconciles_monitor_and_preserves_primary(self):
        import monitoring as m
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'tushare_income',return_value=[dict(x,FINANCIAL_SOURCE='Tushare合并利润表') for x in HISTORY]):
            s=self.source(folder,primary=[],history=[]);rows=s.discover('2026-10-10','2026-10-19')
            payload=dict(version='test',financial_asof='2026-10-19',updated_at='2026-10-19T08:25:00+08:00',
                records=[dict(id=m.report_id(rows[0]),status='未入选',quarter_profit=40,status_note='高开不足2%')],issues=[])
            result=m.build(payload,rows,rows,{},s.notices,s.histories,{'601059.SH':{'list_date':'2000-01-01'}},{})
            self.assertEqual(result['status'],'PASS');self.assertEqual(result['counts']['pending'],0)
            self.assertEqual(result['reports'][0]['quarter_profit'],40);self.assertEqual(result['reports'][0]['quarter_yoy'],100)
            self.assertEqual(result['reports'][0]['financial_source'],'Tushare合并利润表')

    def test_existing_close_entry_survives_incomplete_same_day_bars(self):
        import update_data as u
        schedule=json.loads((u.DATA/'trading_calendar.json').read_text('utf-8'))
        record=dict(id='test',ts_code='601059.SH',name='测试',ann_date='2026-10-17',end_date='2026-09-30',
                    entry_date='2026-10-19',entry_price=17.17,status='持有',profit_pct=-.5982053838484491,announcement_url='https://example.invalid/report')
        class Closing(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,10,19,15,30,tzinfo=u.TZ)
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)
            for name,value in [('live.json',dict(records=[record])),('stock_metadata.json',{}),('calendar.json',['2026-10-16']),('trading_calendar.json',schedule)]:
                (data/name).write_text(json.dumps(value),'utf-8')
            with patch.object(u,'DATA',data),patch.object(u,'datetime',Closing),patch.object(u,'finance',return_value=[]), \
                 patch.object(u,'daily',return_value=[dict(date='2026-10-16',close=100)]),patch.object(u,'closing_quotes',return_value={}),patch.object(u,'simulate') as simulate:
                result,_,_=u.update()
            simulate.assert_not_called();self.assertEqual(result['records'][0],record)


if __name__=='__main__':unittest.main()

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch
from datetime import datetime

import requests
import update_data as u
import monitoring as m


class FetchTest(unittest.TestCase):
    def test_new_ipo_metadata_repair_excludes_before_volume_and_quotes(self):
        row=dict(SECUCODE='301718.SZ',SECURITY_NAME_ABBR='测试新股',REPORTDATE='2026-09-30',NOTICE_DATE='2026-10-28',PARENT_NETPROFIT=110,ANNOUNCEMENT_URL='https://example.invalid/report')
        history=[row]+[dict(row,REPORTDATE=end,NOTICE_DATE=ann,PARENT_NETPROFIT=amount) for end,ann,amount in [('2026-06-30','2026-09-23',70),('2025-09-30','2026-09-23',100),('2025-06-30','2026-09-23',80)]]
        profile={'fxxg':[dict(SECUCODE='301718.SZ',SECURITY_CODE='301718',LISTING_DATE='2026-10-22')]}
        schedule=json.loads((u.DATA/'trading_calendar.json').read_text('utf-8'))
        class Morning(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,10,28,8,30,tzinfo=u.TZ)
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)
            for name,value in [('live.json',dict(records=[])),('stock_metadata.json',{}),('calendar.json',['2026-10-27']),('trading_calendar.json',schedule)]:
                (data/name).write_text(json.dumps(value),'utf-8')
            with patch.object(u,'DATA',data),patch.object(u,'datetime',Morning),patch.object(u,'finance',return_value=[row]),patch.object(u,'financial_histories',return_value={'301718.SZ':history}),patch.object(u,'daily',return_value=[]),patch.object(u,'get_json',return_value=profile),patch('volume_data.prepare') as volume,patch.object(u,'closing_quotes') as quotes:
                payload,_,_=u.update()
            self.assertEqual(payload['issues'],[])
            self.assertEqual(payload['records'][0]['status_note'],'上市不足90日')
            self.assertFalse(payload['records'][0].get('entry_date'));volume.assert_not_called();quotes.assert_not_called()

    def test_missing_listing_date_is_filled_once_and_persisted(self):
        profile={'fxxg':[dict(SECUCODE='301718.SZ',SECURITY_CODE='301718',LISTING_DATE='2026-10-22 00:00:00')]}
        with tempfile.TemporaryDirectory() as folder,patch.object(u,'DATA',Path(folder)),patch.object(u,'get_json',return_value=profile) as fetch:
            meta={'600000.SH':dict(list_date='1999-11-10',industry='银行')}
            u.fill_listing_dates(meta,['301718.SZ','301718.SZ','600000.SH','200530.SZ'],'2026-10-28')
            self.assertEqual(meta['301718.SZ']['list_date'],'2026-10-22');fetch.assert_called_once()
            self.assertEqual(meta['600000.SH'],dict(list_date='1999-11-10',industry='银行'))
            self.assertEqual(json.loads((Path(folder)/'stock_metadata.json').read_text('utf-8')),meta)
            u.fill_listing_dates(meta,['301718.SZ'],'2026-10-28');self.assertEqual(fetch.call_count,1)

    def test_invalid_listing_identity_date_and_fetch_failure_stay_unconfirmed(self):
        good=dict(SECUCODE='301718.SZ',SECURITY_CODE='301718',LISTING_DATE='2026-10-22')
        cases=[[],{}, {'fxxg':[]},{'fxxg':['bad']},{'fxxg':[dict(good,SECUCODE='301717.SZ')]},
               {'fxxg':[dict(good,LISTING_DATE='2026-10-29')]},{'fxxg':[dict(good,LISTING_DATE='invalid')]}]
        for profile in cases:
            with self.subTest(profile=profile),tempfile.TemporaryDirectory() as folder,patch.object(u,'DATA',Path(folder)),patch.object(u,'get_json',return_value=profile):
                meta={};u.fill_listing_dates(meta,['301718.SZ'],'2026-10-28');self.assertEqual(meta,{})
                self.assertFalse((Path(folder)/'stock_metadata.json').exists())
        with tempfile.TemporaryDirectory() as folder,patch.object(u,'DATA',Path(folder)),patch.object(u,'get_json',side_effect=requests.ReadTimeout('offline')):
            self.assertEqual(u.fill_listing_dates({},['301718.SZ'],'2026-10-28'),{})

    def test_pullback_closing_quote_and_daily_fallback_keep_old_entries(self):
        record=dict(id='live-test',ts_code='600000.SH',name='测试',ann_date='2026-10-23',list_date='2000-01-01',
                    report_period='Q3',end_date='2026-09-30',quarter_profit=100,quarter_yoy=30,status='等待开盘',
                    announcement_url='https://example.invalid/report',volume_previous_shares=1000,volume_reference_day='2026-10-23')
        schedule=json.loads((u.DATA/'trading_calendar.json').read_text('utf-8'))
        class Close(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,10,23,15,30,tzinfo=u.TZ)
        for snapshot in [True,False]:
            for high,close,expected,bought in [(108,102.99,'剔除',False),(107.99,102.99,'持有',False),(108,103,'持有',False),(None,102.99,'待核验',False),(108,102.99,'持有',True)]:
                with self.subTest(snapshot=snapshot,high=high,close=close,bought=bought),tempfile.TemporaryDirectory() as folder:
                    data=Path(folder);candidate=dict(record)
                    if bought:candidate.update(status='持有',entry_date='2026-10-23',entry_price=close,armed=False,stop_basis=close*.92,profit_pct=-.6)
                    for name,value in [('live.json',dict(records=[candidate])),('stock_metadata.json',{}),('calendar.json',['2026-10-22']),('trading_calendar.json',schedule)]:
                        (data/name).write_text(json.dumps(value),'utf-8')
                    quote=dict(close=close,previous=100,open=104,high=high,low=101,volume_shares=1500)
                    bars=[dict(date='2026-10-22',open=100,close=100,high=101,low=99,volume_shares=1000),dict(quote,date='2026-10-23')]
                    with patch.object(u,'DATA',data),patch.object(u,'datetime',Close),patch.object(u,'finance',return_value=[]),patch.object(u,'financial_histories',return_value={}),patch.object(u,'daily',return_value=bars),patch.object(u,'closing_quotes',return_value={'sh600000':quote} if snapshot else {}),patch('volume_data.prepare'):
                        payload,_,_=u.update()
                    result=payload['records'][0]
                    self.assertEqual(result['status'],expected)
                    self.assertEqual(bool(result.get('entry_date')),expected=='持有')
                    if expected=='剔除':self.assertEqual(result['status_note'],'冲高回落：最高≥8%，收盘<3%')
                    if bought:self.assertEqual(result,candidate)

    def test_b_shares_never_reach_financial_history_or_listing_checks(self):
        rows=[dict(SECUCODE=code,REPORTDATE='2026-09-30',NOTICE_DATE='2026-10-22',PARENT_NETPROFIT=100,SECURITY_NAME_ABBR='测试B') for code in ['200530.SZ','900906.SH']]
        schedule=json.loads((u.DATA/'trading_calendar.json').read_text('utf-8'))
        class Morning(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,10,22,8,30,tzinfo=u.TZ)
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)
            for name,value in [('live.json',dict(records=[])),('stock_metadata.json',{}),('calendar.json',['2026-10-21']),('trading_calendar.json',schedule)]:
                (data/name).write_text(json.dumps(value),'utf-8')
            with patch.object(u,'DATA',data),patch.object(u,'datetime',Morning),patch.object(u,'finance',return_value=rows),patch.object(u,'daily',return_value=[]),patch.object(u,'financial_histories',return_value={}) as histories:
                payload,finance,selected=u.update()
            histories.assert_called_once_with([])
            self.assertEqual(payload['issues'],[]);self.assertEqual(payload['records'],[]);self.assertEqual(selected,[])
            self.assertEqual(finance,rows)
    def test_yearless_report_fetch_is_bounded_and_checks_document_identity(self):
        item=dict(secCode='600000',announcementTitle='测试第三季度报告',adjunctUrl='finalpage/2026-10-22/1.PDF')
        response=Mock(content=b'%PDF dummy')
        doc=Mock();doc.pages=[Mock(),Mock()]
        doc.pages[0].extract_text.return_value='证券代码：600000 测试股份有限公司 2026年第三季度报告'
        doc.pages[1].extract_text.return_value='本报告期财务指标'
        context=Mock();context.__enter__=Mock(return_value=doc);context.__exit__=Mock(return_value=False)
        with patch.object(u.SESSION,'get',return_value=response) as get,patch.object(u.pdfplumber,'open',return_value=context):
            u.resolve_report_year(item)
        self.assertEqual(item['report_identity']['year'],2026);get.assert_called_once()
        doc.pages[0].extract_text.return_value='证券代码：600001 2026年第三季度报告'
        with patch.object(u.SESSION,'get',return_value=response),patch.object(u.pdfplumber,'open',return_value=context):
            with self.assertRaisesRegex(ValueError,'身份核对'):u.resolve_report_year(dict(item))
        with patch.object(u.SESSION,'get') as get:
            for title in ['2026年第三季度报告','第三季度报告摘要','第三季度业绩预告']:
                u.resolve_report_year(dict(item,announcementTitle=title))
            get.assert_not_called()
    def test_monday_update_assigns_weekend_without_using_future_bars(self):
        real_schedule=json.loads((u.DATA/'trading_calendar.json').read_text('utf-8'))
        record=dict(id='live-600000.SH-2026-09-30-2026-10-17',ts_code='600000.SH',name='测试',
                    ann_date='2026-10-17',end_date='2026-09-30',report_period='Q3',list_date='2000-01-01',
                    status='等待开盘',quarter_profit=40,quarter_yoy=100,announcement_url='https://example.invalid/report')
        row=dict(SECUCODE='600000.SH',REPORTDATE='2026-09-30',NOTICE_DATE='2026-10-17',PARENT_NETPROFIT=110,SECURITY_NAME_ABBR='测试')
        class Monday(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,10,19,8,25,tzinfo=u.TZ)
        bars=[dict(date='2026-10-16',open=100,high=101,low=99,close=100)]
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)
            for name,value in [('live.json',dict(records=[record])),('stock_metadata.json',{'600000.SH':{'list_date':'2000-01-01'}}),
                               ('calendar.json',['2026-10-16']),('trading_calendar.json',real_schedule)]:
                (data/name).write_text(json.dumps(value),encoding='utf-8')
            with patch.object(u,'DATA',data),patch.object(u,'datetime',Monday),patch.object(u,'finance',return_value=[row]),patch.object(u,'daily',return_value=bars) as daily:
                result,_,_=u.update()
            daily.assert_called_once_with('000001.SH','2026-10-10','2026-10-19',False)
            self.assertEqual(result['records'][0]['reaction_date'],'2026-10-19')
            self.assertIsNone(result['records'][0]['entry_date'])
            self.assertEqual(result['calendar'],['2026-10-16'])
            self.assertIn('2026-12-31',result['reaction_calendar'])

    def test_calendar_coverage_and_completed_price_days(self):
        schedule=json.loads((u.DATA/'trading_calendar.json').read_text('utf-8'))
        self.assertIn('2026-10-19',schedule['open_dates'])
        self.assertIn('2026-10-08',schedule['open_dates'])
        self.assertNotIn('2026-10-05',schedule['open_dates'])
        self.assertNotIn('2026-10-10',schedule['open_dates'])
        self.assertEqual(u.load_trading_calendar('2026-10-19',['2026-10-16']),schedule)
        with self.assertRaisesRegex(RuntimeError,'未覆盖'):u.load_trading_calendar('2027-01-04',[])
        with self.assertRaisesRegex(RuntimeError,'冲突'):u.load_trading_calendar('2026-10-19',['2026-10-17'])

    def test_success_is_not_repeated(self):
        response = Mock()
        response.json.return_value = {'ok': True}
        with patch.object(u.SESSION, 'get', return_value=response) as get, patch.object(u.time, 'sleep') as sleep:
            self.assertEqual(u.get_json('https://example.invalid/', params={'page': 2}), {'ok': True})
        get.assert_called_once_with('https://example.invalid/', timeout=25, params={'page': 2})
        sleep.assert_not_called()

    def test_transient_failures_repeat_only_the_same_read(self):
        response = Mock()
        response.json.return_value = {'rows': [1]}
        failures = [requests.ReadTimeout('slow'), requests.ConnectionError('disconnected'), response]
        with patch.object(u.SESSION, 'get', side_effect=failures) as get, patch.object(u.time, 'sleep') as sleep:
            self.assertEqual(u.get_json('https://example.invalid/', params={'page': 2}), {'rows': [1]})
        self.assertEqual(get.call_args_list, [call('https://example.invalid/', timeout=25, params={'page': 2})] * 3)
        self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    def test_continuous_timeout_stops_after_three_attempts(self):
        error = requests.ReadTimeout('still unavailable')
        with patch.object(u.SESSION, 'get', side_effect=error) as get, patch.object(u.time, 'sleep') as sleep:
            with self.assertRaises(requests.ReadTimeout) as result:
                u.get_json('https://example.invalid/')
        self.assertIs(result.exception, error)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    def test_http_errors_including_rate_limits_are_not_retried(self):
        for status in [403, 429, 500]:
            with self.subTest(status=status):
                response = Mock()
                response.raise_for_status.side_effect = requests.HTTPError(str(status))
                with patch.object(u.SESSION, 'get', return_value=response) as get, patch.object(u.time, 'sleep') as sleep:
                    with self.assertRaises(requests.HTTPError): u.get_json('https://example.invalid/')
                self.assertEqual(get.call_count, 1)
                sleep.assert_not_called()

    def test_invalid_json_is_not_retried_or_accepted(self):
        response = Mock()
        response.json.side_effect = ValueError('invalid JSON')
        with patch.object(u.SESSION, 'get', return_value=response) as get, patch.object(u.time, 'sleep') as sleep:
            with self.assertRaises(ValueError): u.get_json('https://example.invalid/')
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_exhausted_fetch_preserves_live_and_records_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            (data / 'live.json').write_text('{"records":[]}', encoding='utf-8')
            (data / 'stock_metadata.json').write_text('{}', encoding='utf-8')
            before = (data / 'live.json').read_bytes()
            with patch.object(u, 'DATA', data), patch.object(m, 'DATA', data), patch.object(u.time, 'sleep'), \
                 patch.object(u.SESSION, 'get', side_effect=requests.ReadTimeout('offline')) as get:
                with self.assertRaises(requests.ReadTimeout): u.monitored_update()
            self.assertEqual(get.call_count, 3)
            self.assertEqual((data / 'live.json').read_bytes(), before)
            self.assertEqual(json.loads((data / 'monitor.json').read_text('utf-8'))['status'], 'FAILED')


if __name__ == '__main__': unittest.main()

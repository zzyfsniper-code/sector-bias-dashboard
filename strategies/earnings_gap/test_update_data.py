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
            with patch.object(u,'DATA',data),patch.object(u,'datetime',Monday),patch.object(u,'finance',return_value=[row]),patch.object(u,'daily',return_value=bars):
                result,_,_=u.update()
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

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import monitoring as m

NOW='2026-10-14T10:00:00+08:00'
ROW=dict(SECUCODE='600000.SH',REPORTDATE='2026-09-30',NOTICE_DATE='2026-10-14',PARENT_NETPROFIT=110)
NOTICE=dict(secCode='600000',secName='测试公司',announcementId='1',announcementTitle='2026年第三季度报告',adjunctUrl='finalpage/2026-10-14/1.PDF')
META={'600000.SH':{'list_date':'2000-01-01'}}
HISTORY=[ROW,dict(REPORTDATE='2026-06-30',NOTICE_DATE='2026-08-01',PARENT_NETPROFIT=70),dict(REPORTDATE='2025-09-30',NOTICE_DATE='2025-10-15',PARENT_NETPROFIT=100),dict(REPORTDATE='2025-06-30',NOTICE_DATE='2025-08-01',PARENT_NETPROFIT=80)]


def build(notices=None, finance=None, selected=None, previous=None, verified=None, records=None):
    rows=[ROW] if finance is None else finance
    payload=dict(version='test',financial_asof='2026-10-14',updated_at=NOW,records=records if records is not None else [dict(id=m.report_id(ROW),status='等待开盘',quarter_profit=40)],issues=[])
    return m.build(payload,rows,rows if selected is None else selected,previous or {},lambda a,b:[NOTICE] if notices is None else notices,
                   lambda rows:{'600000.SH':HISTORY},META,verified or {})


class MonitoringTest(unittest.TestCase):
    def test_full_coverage_and_quarter_not_cumulative(self):
        result=build();self.assertEqual(result['status'],'PASS');self.assertEqual(result['counts']['processed'],1)
        self.assertEqual(result['reports'][0]['quarter_yoy'],100);self.assertEqual(result['counts']['financial_candidates'],1)
    def test_announcement_without_finance_is_not_zero_signals_success(self):
        result=build(finance=[]);self.assertEqual(result['status'],'PARTIAL');self.assertEqual(result['counts']['pending'],1)
        self.assertEqual(result['reports'][0]['result'],'待补数据')
    def test_finance_without_announcement_is_unreconciled(self):
        result=build(notices=[]);self.assertEqual(result['status'],'PARTIAL');self.assertTrue(result['issues'])
    def test_st_is_explicitly_accounted_for(self):
        notice=dict(NOTICE,secName='*ST测试');result=build(notices=[notice],finance=[])
        self.assertEqual(result['status'],'PASS');self.assertEqual(result['counts']['processed'],1);self.assertEqual(result['reports'][0]['reason'],'ST股票')
    def test_corrected_report_requires_document_check(self):
        result=build(notices=[dict(NOTICE,announcementTitle='2026年第三季度报告（更正后）')])
        self.assertEqual(result['counts']['pending'],1);self.assertEqual(result['reports'][0]['result'],'待复核')
    def test_matching_document_check_completes_correction(self):
        result=build(notices=[dict(NOTICE,announcementTitle='2026年第三季度报告（更正后）')],verified={'https://static.cninfo.com.cn/finalpage/2026-10-14/1.PDF':{'quarter_profit':40,'quarter_yoy':100}})
        self.assertEqual(result['counts']['pending'],0);self.assertIn('更正原文已核验',result['reports'][0]['reason'])
    def test_changed_numbers_invalidate_document_check(self):
        result=build(notices=[dict(NOTICE,announcementTitle='2026年第三季度报告（更正后）')],verified={'https://static.cninfo.com.cn/finalpage/2026-10-14/1.PDF':{'quarter_profit':39,'quarter_yoy':100}})
        self.assertEqual(result['counts']['pending'],1)
    def test_incremental_catalog_is_deduplicated(self):
        first=build();second=build(previous=first);self.assertEqual(second['counts']['announcements'],1)
    def test_source_failure_preserves_catalog_but_is_not_pass(self):
        previous=build();payload=dict(version='test',financial_asof='2026-10-14',updated_at=NOW,records=[],issues=[])
        def unavailable(a,b):raise RuntimeError('source offline')
        result=m.build(payload,[ROW],[ROW],previous,unavailable,lambda rows:{},META,{})
        self.assertEqual(result['source_status'],'FAILED');self.assertEqual(len(result['catalog']),1);self.assertEqual(result['status'],'PARTIAL')
    def test_signal_rejection_reason_is_retained(self):
        result=build(records=[dict(id=m.report_id(ROW),status='未入选',status_note='高开不足2%')])
        self.assertEqual(result['reports'][0]['reason'],'高开不足2%')
    def test_eligible_finance_without_quote_tracking_is_pending(self):
        result=build(records=[]);self.assertEqual(result['counts']['pending'],1)
        self.assertIn('尚未建立行情跟踪记录',result['reports'][0]['reason'])
    def test_changed_finance_does_not_silently_accept_old_signal(self):
        result=build(records=[dict(id=m.report_id(ROW),status='未入选',quarter_profit=30)])
        self.assertEqual(result['counts']['pending'],1);self.assertIn('信号记录需核验',result['reports'][0]['reason'])
    def test_summary_and_forecast_are_not_formal_reports(self):
        for title in ['2026年第三季度业绩预告','2026年第三季度报告摘要','2026年业绩快报']:
            self.assertIsNone(m.notice_record(dict(NOTICE,announcementTitle=title)))
    def test_failed_collection_preserves_live_and_records_failure(self):
        import update_data as u
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);(data/'live.json').write_text('{"records":[]}',encoding='utf-8');(data/'stock_metadata.json').write_text('{}',encoding='utf-8')
            before=(data/'live.json').read_bytes()
            with patch.object(u,'DATA',data),patch.object(m,'DATA',data),patch.object(u,'finance',side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):u.monitored_update()
            self.assertEqual((data/'live.json').read_bytes(),before);self.assertEqual(json.loads((data/'monitor.json').read_text('utf-8'))['status'],'FAILED')


if __name__=='__main__':unittest.main()

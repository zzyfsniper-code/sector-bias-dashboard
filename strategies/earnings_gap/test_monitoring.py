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
    def test_verified_other_entity_does_not_create_missing_parent_financials(self):
        notice=m.notice_record(NOTICE);url=notice['url']
        proof={url:dict(scope='other_entity',publisher_code='600000.SH',report_subject_code='000001.SZ',company='子公司',sha256='a'*64)}
        result=build(finance=[],verified=proof,previous={'catalog':[notice]})
        self.assertEqual(result['status'],'PASS');self.assertEqual(result['counts']['pending'],0)
        self.assertEqual(result['counts']['announcements'],0);self.assertEqual(result['catalog'],[])
        self.assertEqual(result['scope_exclusions'][0]['report_subject_code'],'000001.SZ')
        self.assertIsNone(m.report_scope_exclusion(notice,{url:dict(proof[url],publisher_code='600001.SH')}))
        self.assertIsNone(m.report_scope_exclusion(notice,{url:dict(proof[url],sha256='invalid')}))
        again=build(finance=[],notices=[],verified=proof,previous=result)
        self.assertEqual(again['scope_exclusions'],result['scope_exclusions'])

    def test_verified_unchanged_correction_keeps_original_reaction_day(self):
        notice=dict(NOTICE,adjunctUrl='finalpage/2026-10-15/2.PDF',announcementId='2',announcementTitle='2026年第三季度报告（更正后）')
        trade=dict(id=m.report_id(ROW),ann_date='2026-10-14',reaction_date='2026-10-14',status='未入选',status_note='高开不足2%',quarter_profit=40,quarter_yoy=100)
        payload=dict(version='test',financial_asof='2026-10-15',updated_at=NOW,records=[trade],issues=[],calendar=['2026-10-14','2026-10-15'])
        proof={'https://static.cninfo.com.cn/finalpage/2026-10-15/2.PDF':{'quarter_profit':40,'quarter_yoy':100}}
        result=m.build(payload,[ROW],[ROW],{},lambda a,b:[notice],lambda rows:{'600000.SH':HISTORY},META,proof)
        self.assertEqual(result['counts']['pending'],0)
        self.assertEqual(result['reports'][0]['reaction_date'],'2026-10-14')
        self.assertIn('财务值未变',result['reports'][0]['reason'])

    def test_full_coverage_and_quarter_not_cumulative(self):
        result=build();self.assertEqual(result['status'],'PASS');self.assertEqual(result['counts']['processed'],1)
        self.assertEqual(result['reports'][0]['quarter_yoy'],100);self.assertEqual(result['counts']['financial_candidates'],1)
        self.assertEqual(result['reports'][0]['quarter_profit'],40)
    def test_announcement_without_finance_is_not_zero_signals_success(self):
        result=build(finance=[]);self.assertEqual(result['status'],'PARTIAL');self.assertEqual(result['counts']['pending'],1)
        self.assertEqual(result['reports'][0]['result'],'待补数据')
    def test_finance_without_announcement_is_unreconciled(self):
        result=build(notices=[]);self.assertEqual(result['status'],'PARTIAL');self.assertTrue(result['issues'])
    def test_b_shares_are_explicitly_excluded_from_coverage(self):
        for code in ['200530.SZ','900906.SH']:
            result=build(finance=[ROW,dict(ROW,SECUCODE=code,SECURITY_NAME_ABBR='测试B')],selected=[ROW])
            self.assertEqual(result['status'],'PASS')
            self.assertEqual(result['scope_exclusions'][0]['reason'],'B股不参与策略')
            self.assertNotIn(code,{r['ts_code'] for r in result['reports']})
    def test_comparative_finance_needs_matching_newer_formal_notice(self):
        comparative=dict(ROW,REPORTDATE='2025-09-30',ISNEW='0')
        result=build(finance=[ROW,comparative],selected=[ROW]);self.assertEqual(result['status'],'PASS')
        self.assertIn('历史比较数据',result['scope_exclusions'][0]['reason'])
        result=build(notices=[],finance=[ROW,comparative],selected=[ROW])
        self.assertEqual(result['status'],'PARTIAL');self.assertFalse(result['scope_exclusions'])
        self.assertEqual(build(finance=[ROW,dict(comparative,ISNEW='1')],selected=[ROW])['status'],'PARTIAL')
    def test_yearless_title_requires_verified_original_identity(self):
        item=dict(NOTICE,announcementTitle='测试公司第三季度报告')
        self.assertIsNone(m.notice_record(item))
        identity=dict(code='600000',year=2026,period_end='09-30',sha256='a'*64)
        self.assertEqual(m.notice_record(dict(item,report_identity=identity))['end_date'],'2026-09-30')
        for bad in [dict(identity,code='600001'),dict(identity,period_end='06-30'),dict(identity,sha256='invalid')]:
            self.assertIsNone(m.notice_record(dict(item,report_identity=bad)))
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

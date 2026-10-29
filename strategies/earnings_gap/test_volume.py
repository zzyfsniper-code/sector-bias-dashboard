import unittest
from copy import deepcopy
from unittest.mock import patch,Mock
import update_data as updater
from datetime import datetime
from pathlib import Path
import tempfile,json
from volume_data import TIMES, POOL, build_model, profile_from_tencent, prepare
from strategy_core import simulate

class VolumeTest(unittest.TestCase):
    def test_profile_budget_preserves_verified_curve_and_fresh_required_baseline(self):
        rows=[dict(date=day,volume_shares=1000,fractions=[(i+1)/len(TIMES) for i in range(len(TIMES))]) for day in ['2026-10-14','2026-10-15','2026-10-16','2026-10-19','2026-10-20']]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            cache=dict(daily_asof='2026-10-21',baselines={POOL[0]:dict(date='2026-10-21',volume_shares=2000)},profiles={POOL[0]:rows})
            (root/'volume_cache.json').write_text(json.dumps(cache),'utf-8')
            client=Mock();client.minutes.side_effect=RuntimeError('slow minute source')
            records=[dict(ts_code=POOL[0])]
            with patch('volume_data.time.monotonic',side_effect=[0,0,91]):
                model=prepare(root,records,'2026-10-22',['2026-10-21','2026-10-22'],client)
            client.assert_not_called();client.minutes.assert_called_once_with(POOL[0])
            self.assertEqual(records[0]['volume_reference_day'],'2026-10-22')
            self.assertEqual(records[0]['volume_previous_shares'],2000)
            self.assertEqual(model['stock_profiles'][POOL[0]]['through'],'2026-10-20')
            self.assertTrue(any('90秒' in error for error in model['issues']))

    def test_daily_accumulation_switches_to_own_profile_and_reuses_cache(self):
        rows=[dict(date=day,volume_shares=24200,fractions=[(i+1)/len(TIMES) for i in range(len(TIMES))]) for day in ['2026-10-15','2026-10-16','2026-10-19','2026-10-20']]
        class Client:
            calls=0
            def __call__(self,api,fields,**params):
                self.calls+=1
                return [dict(ts_code=f'{i:06}.SZ',trade_date='20261021',vol=242) for i in range(3000)] if 'trade_date' in params else [dict(trade_date='20261021',vol=242)]
            def minutes(self,code):
                self.calls+=1;symbol=code[-2:].lower()+code[:6];scale=100 if code.startswith('68') else 1
                values=[f'{m//60:02}{m%60:02} 10 {(i+1)*scale}' for i,m in enumerate(TIMES)]
                return {'data':{symbol:{'data':[dict(date='20261021',data=values),dict(date='20261022',data=values)]}}}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'volume_cache.json').write_text(json.dumps(dict(daily_asof='2026-10-20',profiles={code:rows for code in POOL})),'utf-8')
            client=Client();records=[dict(ts_code=POOL[0])]
            model=prepare(root,records,'2026-10-22',['2026-10-20','2026-10-21','2026-10-22'],client)
            self.assertEqual(model['stock_profiles'][POOL[0]]['stock_days'],5)
            self.assertEqual(model['stock_profiles'][POOL[0]]['through'],'2026-10-21')
            self.assertEqual(model['global_profile']['stock_days'],80)
            self.assertEqual(records[0]['volume_previous_shares'],24200)
            self.assertEqual(records[0]['volume_reference_day'],'2026-10-22')
            count=client.calls;prepare(root,records,'2026-10-22',['2026-10-20','2026-10-21','2026-10-22'],client)
            self.assertEqual(client.calls,count)
    def test_update_archives_only_actual_close_volume(self):
        record=dict(id='live-test',ts_code='600000.SH',name='测试',ann_date='2026-10-21',list_date='2000-01-01',report_period='Q3',end_date='2026-09-30',status='等待开盘',announcement_url='https://example.invalid/report')
        schedule=json.loads((updater.DATA/'trading_calendar.json').read_text('utf-8'))
        class Close(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,10,21,15,30,tzinfo=updater.TZ)
        def prepare(root,records,today,calendar):
            for r in records:r.update(volume_previous_shares=1000,volume_previous_date='2026-10-20',volume_reference_day=today)
        for amount,expected in [(1449,'剔除'),(1450,'持有'),(None,'待核验')]:
            with self.subTest(amount=amount),tempfile.TemporaryDirectory() as directory:
                data=Path(directory)
                for name,value in [('live.json',dict(records=[record])),('stock_metadata.json',{}),('calendar.json',['2026-10-20']),('trading_calendar.json',schedule)]:
                    (data/name).write_text(json.dumps(value),'utf-8')
                quote=dict(close=104,previous=100,open=102,high=105,low=101,volume_shares=amount)
                bars=[dict(date='2026-10-20',open=100,close=100,high=101,low=99)]
                with patch.object(updater,'DATA',data),patch.object(updater,'datetime',Close),patch.object(updater,'finance',return_value=[]),patch.object(updater,'daily',return_value=bars),patch.object(updater,'closing_quotes',return_value={'sh600000':quote}),patch('volume_data.prepare',side_effect=prepare):
                    payload,_,_=updater.update()
                self.assertEqual(payload['records'][0]['status'],expected)
                self.assertEqual(bool(payload['records'][0].get('entry_date')),amount==1450)
                if amount is not None:self.assertEqual(payload['records'][0]['volume_forecast_shares'],amount)
    def test_closing_quote_units_and_missing_volume(self):
        lines=[]
        for symbol,vol in [('sz300839','100'),('sh688146','100'),('sh600000','')]:
            fields=['']*40
            for i,value in {1:'测试',3:'104',4:'100',5:'102',6:vol,30:'20261021150000',33:'105',34:'101'}.items():fields[i]=value
            lines.append('v_'+symbol+'="'+'~'.join(fields)+'";')
        records=[{'ts_code':code} for code in ['300839.SZ','688146.SH','600000.SH']]
        class Response:
            content='\n'.join(lines).encode('gbk')
            def raise_for_status(self):pass
        with patch.object(updater.SESSION,'get',return_value=Response()):
            q=updater.closing_quotes(records,'2026-10-21')
        self.assertEqual(q['sz300839']['volume_shares'],10000)
        self.assertEqual(q['sh688146']['volume_shares'],100)
        self.assertIsNone(q['sh600000']['volume_shares'])
    def test_cumulative_units_and_incomplete_days(self):
        for code,scale in [('300839.SZ',100),('688146.SH',1)]:
            symbol=code[-2:].lower()+code[:6]
            values=[f'{m//60:02}{m%60:02} 10 {i+1}' for i,m in enumerate(TIMES)]
            value={'data':{symbol:{'data':[dict(date='20261020',data=values)]}}}
            rows=profile_from_tencent(value,code,{'2026-10-20':len(TIMES)*scale})
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['fractions'][-1],1)
            bad=deepcopy(value);bad['data'][symbol]['data'][0]['data']=values[:-1]
            self.assertEqual(profile_from_tencent(bad,code,{'2026-10-20':len(TIMES)*scale}),[])
            self.assertEqual(profile_from_tencent(value,code,{'2026-10-20':10}),[])
    def test_model_never_uses_current_or_future(self):
        rows=[dict(date=f'2026-10-{d:02}',fractions=[d/30]*len(TIMES)) for d in range(10,23)]
        model=build_model({'profiles':{POOL[0]:rows}},'2026-10-21')
        self.assertEqual(model['global_profile']['through'],'2026-10-20')
        self.assertEqual(model['global_profile']['stock_days'],11)
        self.assertLess(model['global_profile']['median'][0],21/30)
    def test_final_threshold_and_legacy_positions(self):
        cal=['2026-10-20','2026-10-21']
        record=dict(ts_code='600000.SH',name='测试',ann_date=cal[1],list_date='2000-01-01',report_period='Q3')
        bars=[dict(date=cal[0],open=100,close=100,high=101,low=99,volume_shares=1000),
              dict(date=cal[1],open=102,close=104,high=105,low=101,volume_shares=1450)]
        self.assertEqual(simulate(record,bars,bars,cal)['status'],'持有')
        bars[1]['volume_shares']=1449
        self.assertEqual(simulate(record,bars,bars,cal)['status_note'],'收盘量能不足1.45倍')
        self.assertEqual(simulate(dict(record,entry_date=cal[1]),bars,bars,cal)['status'],'持有')
        del bars[0]['volume_shares']
        self.assertEqual(simulate(record,bars,bars,cal)['status_note'],'量能待核验')
    def test_old_reaction_days_are_not_rewritten(self):
        cal=['2026-10-19','2026-10-20']
        record=dict(ts_code='600000.SH',name='测试',ann_date=cal[1],list_date='2000-01-01',report_period='Q3')
        bars=[dict(date=cal[0],open=100,close=100,high=101,low=99),dict(date=cal[1],open=102,close=104,high=105,low=101)]
        self.assertEqual(simulate(record,bars,bars,cal)['status'],'持有')

if __name__=='__main__':unittest.main()

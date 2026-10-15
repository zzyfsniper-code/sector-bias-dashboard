"""Offline daily-update acceptance. Synthetic new closes never enter public data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from export_research import LOCAL, WEB, build_performance, measure
from strategy import CODES, simulate
import update

TZ = timezone(timedelta(hours=8))


class DailyPerformanceTest(unittest.TestCase):
    def setUp(self):
        self.prices = pd.read_csv(LOCAL/'seed_prices.csv', index_col=0, parse_dates=True)
        self.frozen = json.loads((WEB/'backtest.json').read_text('utf-8'))
        self.snapshot = json.loads((LOCAL/'snapshot_159696_release.json').read_text('utf-8-sig'))
        self.calendar = sorted(set(self.snapshot['calendar']) | set(self.prices.index.strftime('%Y-%m-%d')))

    def extended_prices(self):
        extra = pd.DataFrame([self.prices.iloc[-1].to_numpy()*[1.01, .99, 1.005]],
                             columns=CODES, index=pd.to_datetime(['2026-10-15']))
        return pd.concat([self.prices, extra])

    def package(self, prices, day):
        live, _, model = update.build_live(prices, self.snapshot, datetime(2026,10,day,18,10,tzinfo=TZ))
        live['run_id'] = 'OFFLINE_TEST_ONLY'
        return build_performance(prices, self.calendar, model, live, self.frozen), live, model

    def test_initial_metrics_and_all_curves_equal_frozen(self):
        packet, _, _ = self.package(self.prices, 14)
        self.assertEqual(packet['metrics'], self.frozen['metrics'])
        self.assertEqual(packet['curves'], self.frozen['curves'])
        self.assertEqual(packet['dates'], self.frozen['dates'])

    def test_new_day_extends_model_and_recomputes_all_metrics(self):
        packet, live, model = self.package(self.extended_prices(), 15)
        self.assertEqual(len(packet['dates']),733)
        self.assertEqual(packet['end'],'2026-10-15')
        self.assertEqual(packet['run_id'],live['run_id'])
        self.assertEqual(packet['metrics'],measure(model))
        self.assertNotEqual(packet['metrics']['annual_return'],self.frozen['metrics']['annual_return'])
        for key in packet['curves']:
            for field in ['nav','drawdown']:
                np.testing.assert_allclose(packet['curves'][key][field][:-1],self.frozen['curves'][key][field],atol=1e-12,rtol=0)
        previous = model.iloc[-2]
        expected = sum(previous['weight_'+c]*r for c,r in zip(CODES,[.01,-.01,.005]))
        self.assertAlmostEqual(model['return'].iloc[-1],expected)
        self.assertEqual(model.turnover.iloc[-1],0)
        self.assertFalse(packet['actual_fills_recorded'])

    def test_changed_frozen_history_is_rejected(self):
        packet, live, model = self.package(self.prices,14)
        changed = deepcopy(self.frozen)
        changed['curves']['cash_t14_v20']['nav'][20] += .01
        with self.assertRaises(AssertionError):
            build_performance(self.prices,self.calendar,model,live,changed)
        with self.assertRaises(ValueError):
            build_performance(self.prices,self.calendar,model,{**live,'data_as_of':'2026-10-15'},self.frozen)

    def test_full_updater_writes_daily_output_but_not_frozen_backtest(self):
        prices = self.extended_prices()
        fixed = datetime(2026,10,15,18,10,tzinfo=TZ)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return fixed
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); local = root/'local'; web = root/'web'
            local.mkdir(); web.mkdir()
            for name in ['backtest.json','nav.csv','history.json']:
                (web/name).write_bytes((WEB/name).read_bytes())
            frozen_bytes = {name:(web/name).read_bytes() for name in ['backtest.json','nav.csv']}
            snapshot = self.snapshot | dict(observed_at=fixed.isoformat())
            snapshot_path = root/'snapshot.json'
            snapshot_path.write_text(json.dumps(snapshot),encoding='utf-8')
            frames = {'etf_'+c[:6]:pd.DataFrame(dict(code=c,date=prices.index.strftime('%Y-%m-%d'),close=prices[c].to_numpy())) for c in CODES}
            manifest = dict(run_id='SYNTHETIC_OFFLINE_TEST_ONLY',queries=[dict(code=c,requested_formula='WSD PriceAdj=F') for c in CODES])
            with patch.object(update,'LOCAL',local),patch.object(update,'WEB',web),patch.object(update,'datetime',Clock),patch.object(sys,'argv',['update','--snapshot',str(snapshot_path)]),patch.object(update,'run_wsd_batch',return_value=(manifest,frames)):
                update.main()
            performance = json.loads((web/'performance.json').read_text('utf-8'))
            live = json.loads((web/'live.json').read_text('utf-8'))
            self.assertEqual(performance['end'],'2026-10-15')
            self.assertEqual(performance['run_id'],live['run_id'])
            self.assertEqual(performance['status'],'PASS')
            for name,data in frozen_bytes.items():
                self.assertEqual((web/name).read_bytes(),data)

    def test_failed_wind_request_preserves_all_public_outputs_and_latest(self):
        fixed = datetime(2026,10,15,18,10,tzinfo=TZ)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return fixed
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); local = root/'local'; web = root/'web'
            local.mkdir(); web.mkdir()
            (local/'latest.json').write_text('previous successful batch',encoding='utf-8')
            for name in ['live.json','history.json','rebalances.csv','performance.json']:
                (web/name).write_text('last good '+name,encoding='utf-8')
            snapshot_path = root/'snapshot.json'
            snapshot_path.write_text(json.dumps(self.snapshot | dict(observed_at=fixed.isoformat())),encoding='utf-8')
            before = {p:p.read_bytes() for p in [local/'latest.json',*web.iterdir()]}
            with patch.object(update,'LOCAL',local),patch.object(update,'WEB',web),patch.object(update,'datetime',Clock),patch.object(sys,'argv',['update','--snapshot',str(snapshot_path)]),patch.object(update,'run_wsd_batch',side_effect=RuntimeError('SYNTHETIC Wind quota exceeded')) as request:
                with self.assertRaises(RuntimeError):
                    update.main()
                self.assertEqual(request.call_count,1)
            self.assertEqual(before,{p:p.read_bytes() for p in before})


if __name__=='__main__':
    unittest.main()

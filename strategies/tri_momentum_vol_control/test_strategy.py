import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from strategy import BACKTEST_START, CODES, LISTING, VERSION, signal, simulate, trade_fee, weekly_last, next_execution

ROOT = Path(__file__).resolve().parents[2]


class RulesTest(unittest.TestCase):
    def prices(self):
        return pd.DataFrame({c:100*np.exp(np.arange(60)*(.001+j*.0002)) for j,c in enumerate(CODES)},
                            index=pd.bdate_range('2026-01-01', periods=60))

    def test_exact_momentum_and_volatility_windows(self):
        p=self.prices();p.iloc[-1,2]*=1.03
        s=signal(p)
        self.assertEqual(s['selected_code'],CODES[2])
        self.assertAlmostEqual(s['selected_score'],p.iloc[-1,2]/p.iloc[-20,2]-1)
        expected=np.std(np.diff(p.iloc[-21:,2])/p.iloc[-21:-1,2].to_numpy(),ddof=1)*np.sqrt(252)
        self.assertAlmostEqual(s['estimated_volatility'],expected)
        self.assertAlmostEqual(s['risk_weight'],min(1,.14/expected))

    def test_tie_order_and_zero_volatility(self):
        p=self.prices()*0+100;s=signal(p)
        self.assertEqual(s['selected_code'],CODES[0]);self.assertEqual(s['risk_weight'],1)

    def test_all_negative_still_selects(self):
        p=200-self.prices();s=signal(p)
        self.assertLess(s['selected_score'],0);self.assertGreater(s['risk_weight'],0)

    def test_missing_rejected(self):
        p=self.prices();p.iloc[-1,0]=np.nan
        with self.assertRaises(ValueError):signal(p)
        with self.assertRaises(ValueError):signal(self.prices().iloc[:20])

    def test_holiday_and_partial_week(self):
        cal=pd.to_datetime(['2026-09-28','2026-09-29','2026-09-30','2026-10-08','2026-10-09','2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16','2026-10-19'])
        weekly=weekly_last(cal)
        self.assertIn(pd.Timestamp('2026-09-30'),weekly)
        self.assertNotIn(pd.Timestamp('2026-10-14'),weekly)
        self.assertEqual(next_execution(cal,'2026-10-09'),'2026-10-09')
        with self.assertRaises(ValueError):next_execution(cal[:3],'2026-09-30')

    def test_fees_self_financing(self):
        for assets,target in [(np.array([1.,0,0]),np.array([0,.7,0])),(np.array([.4,0,0]),np.array([.6,0,0]))]:
            f=trade_fee(assets,1.,target)
            self.assertAlmostEqual(f,.001*np.abs(target*(1-f)-assets).sum())

    def test_no_execution_day_price_in_signal(self):
        p=self.prices();calendar=p.index.union(pd.bdate_range(p.index[-1],periods=7))
        f,s=simulate(p,calendar,start='2026-02-01');day=s[1]['execution_date'];changed=p.copy();changed.loc[day,CODES[1]]*=1.5
        _,new=simulate(changed,calendar,start='2026-02-01');a=next(r for r in s if r['execution_date']==day);b=next(r for r in new if r['execution_date']==day)
        for k in ['selected_code','selected_score','estimated_volatility','risk_weight']:
            self.assertEqual(a[k],b[k])

    def test_frozen_ledger_and_daily_weights(self):
        seed=Path(__file__).with_name('data')/'seed_prices.csv'
        p=pd.read_csv(seed,index_col=0,parse_dates=True)
        snap=json.loads((Path(__file__).with_name('data')/'snapshot_159696_release.json').read_text('utf-8-sig'))
        calendar=p.index.union(pd.to_datetime(snap['calendar']))
        actual,records=simulate(p,calendar)
        expected=pd.read_csv(ROOT/'tri-momentum-vol-control/data/nav.csv',index_col=0)
        for col in actual.columns:
            np.testing.assert_allclose(actual[col],expected[col],atol=2e-12,rtol=0)
        self.assertEqual(len(records),156)
        self.assertEqual(str(p.index[0].date()),LISTING)
        self.assertEqual(actual.index[0],BACKTEST_START)
        self.assertEqual(records[0]['information_date'],'2023-09-27')
        self.assertNotIn('2026-10-14',[r['execution_date'] for r in records])
        self.assertEqual(CODES[0],'159696.SZ')
        self.assertTrue(all(set(r['target_weights'])==set(CODES) for r in records))
        np.testing.assert_allclose(actual[['contrib_'+c for c in CODES]].sum(axis=1)+actual.fee_return,actual['return'],atol=2e-12,rtol=0)
        backtest=json.loads((ROOT/'tri-momentum-vol-control/data/backtest.json').read_text('utf-8'))
        self.assertEqual(backtest['version'],VERSION)
        self.assertNotIn('hold_513100.SH',backtest['curves'])
        self.assertTrue(actual.risk_weight.between(0,1).all())
        self.assertTrue((actual.cash_weight>=-1e-12).all())

    def test_live_candidate_matches_history_and_frozen_not_overwritten(self):
        from update import build_live
        from datetime import datetime,timezone,timedelta
        seed=Path(__file__).with_name('data')/'seed_prices.csv';p=pd.read_csv(seed,index_col=0,parse_dates=True)
        calendar=pd.bdate_range('2026-09-01','2026-10-30').strftime('%Y-%m-%d').tolist()
        snap=dict(calendar=calendar,calendar_start='2026-09-01',calendar_end='2026-10-30')
        now=datetime(2026,10,14,18,10,tzinfo=timezone(timedelta(hours=8)))
        live,_,_=build_live(p,snap,now)
        self.assertFalse(live['signal']['is_final'])
        self.assertEqual(live['signal']['execution_date'],'2026-10-16')
        np.testing.assert_allclose(live['signal']['risk_weight'],signal(p)['risk_weight'])
        with self.assertRaises(ValueError):build_live(p,snap,now+timedelta(days=3))


if __name__=='__main__':unittest.main()

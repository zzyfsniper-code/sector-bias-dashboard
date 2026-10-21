"""Export the user-confirmed no-FY frozen assets; leave daily tracking untouched."""
from pathlib import Path
import hashlib,json,shutil

ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path('D:/agent工作目录/A股趋势看板/交易策略回测/strategies/earnings_gap_robustness/research_20261021_v29_volume145/frozen_public')
FILES={'history.json','backtest.json','nav.json','year_report.json','event_history.csv','portfolio_fills.csv','nav.csv','operation_contract.json'}

def main():
    manifest=json.loads((SOURCE/'manifest.json').read_text('utf-8'))
    assert set(manifest)==FILES
    for name,digest in manifest.items():assert hashlib.sha256((SOURCE/name).read_bytes()).hexdigest()==digest,name
    backtest=json.loads((SOURCE/'backtest.json').read_text('utf-8'))
    history=json.loads((SOURCE/'history.json').read_text('utf-8'))
    assert backtest['version']=='eg-20261021-v4-volume145' and len(history)==backtest['independent']['n']==2080
    assert all(row['report_period']!='FY' and row['volume_ratio']>=1.45 for row in history)
    target=ROOT/'earnings-gap/data';target.mkdir(parents=True,exist_ok=True)
    for name in sorted(FILES):shutil.copyfile(SOURCE/name,target/name)
    print('VOLUME145_FROZEN_EXPORT_PASS',len(history),'events',backtest['portfolio']['filled_trades'],'portfolio fills')

if __name__=='__main__':main()

"""Point-in-time volume baselines and empirical intraday cumulative profiles."""
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import json,math,os,time
import requests

TZ=timezone(timedelta(hours=8))
POOL=['001301.SZ','002083.SZ','000001.SZ','000858.SZ','600233.SH','600235.SH','600519.SH','601318.SH',
      '300839.SZ','300846.SZ','300750.SZ','300059.SZ','688146.SH','688234.SH','688981.SH','688012.SH']
TIMES=list(range(570,691))+list(range(780,901))

def quantile(values,p):
    a=sorted(values);x=(len(a)-1)*p;i=int(x);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(x-i)

def profile_from_tencent(value,code,daily):
    symbol=code[-2:].lower()+code[:6];result=[]
    days=value.get('data',{}).get(symbol,{}).get('data',[])
    if not isinstance(days,list) or not days:raise ValueError('公开分钟数据缺失')
    for row in days:
        stamp=row['date'];day=stamp[:4]+'-'+stamp[4:6]+'-'+stamp[6:];points={}
        for item in row.get('data',[]):
            a=item.split();point=int(a[0][:2])*60+int(a[0][2:]);volume=float(a[2])*(1 if code.startswith('68') else 100)
            if point not in TIMES:continue
            if point in points:raise ValueError('重复分钟成交量')
            if not math.isfinite(volume) or volume<0:raise ValueError('分钟成交量无效')
            points[point]=volume
        total=daily.get(day)
        if not total or len(points)<240 or 900 not in points:continue
        if abs(points[900]-total)>max(200,total*.002):continue
        values=[points[k] for k in sorted(points)]
        if any(b<a for a,b in zip(values,values[1:])):continue
        last=0;fractions=[]
        for point in TIMES:
            last=points.get(point,last);fractions.append(min(1,last/total))
        fractions[-1]=1.;result.append(dict(date=day,volume_shares=total,fractions=fractions))
    return result

def curve(rows):
    return {name:[round(quantile([r['fractions'][i] for r in rows],p),8) for i in range(len(TIMES))]
            for name,p in [('p25',.25),('median',.5),('p75',.75)]}

def build_model(cache,asof):
    latest={code:[r for r in rows if r['date']<asof][-20:] for code,rows in cache.get('profiles',{}).items()}
    pooled=[r for code in POOL for r in latest.get(code,[])]
    if not pooled:raise ValueError('量能曲线没有已完成历史样本')
    global_curve=dict(curve(pooled),stock_days=len(pooled),stocks=sum(bool(latest.get(code)) for code in POOL),
                      through=max(r['date'] for r in pooled))
    own={code:dict(curve(rows),stock_days=len(rows),through=rows[-1]['date']) for code,rows in latest.items() if len(rows)>=5}
    return dict(version=1,asof=asof,times=TIMES,global_profile=global_curve,stock_profiles=own,
        unit='shares',method='median_cumulative_fraction_prior_20_complete_days',
        source='Tencent public cumulative minutes / Tushare daily; totals and units cross-checked',
        updated_at=datetime.now(TZ).isoformat())

class Client:
    def minutes(self,code):
        file=self.raw_dir/('tencent_'+code+'.json') if self.raw_dir else None
        if file and file.exists():return json.loads(file.read_text('utf-8'))
        time.sleep(.25);self.calls+=1
        try:
            r=requests.get('https://web.ifzq.gtimg.cn/appstock/app/day/query',params={'code':code[-2:].lower()+code[:6]},headers={'User-Agent':'Mozilla/5.0','Referer':'https://gu.qq.com/'},timeout=20)
            r.raise_for_status();value=r.json()
            if value.get('code')!=0:raise ValueError()
        except (requests.RequestException,ValueError):raise RuntimeError('公开分钟量能请求失败') from None
        if file:file.parent.mkdir(parents=True,exist_ok=True);file.write_text(json.dumps(value,ensure_ascii=False),'utf-8')
        return value
    def __init__(self,raw_dir=None):self.raw_dir=Path(raw_dir) if raw_dir else None;self.calls=0
    def __call__(self,api,fields,**params):
        key=api+'_'+params.get('ts_code',params.get('trade_date','all'))+'_'+params.get('start_date','').replace(' ','_').replace(':','')+'_'+params.get('end_date','').replace(' ','_').replace(':','')
        file=self.raw_dir/(key+'.json') if self.raw_dir else None
        if file and file.exists():value=json.loads(file.read_text('utf-8'))
        else:
            token=os.environ.get('TUSHARE_TOKEN')
            if not token:raise RuntimeError('TUSHARE_TOKEN_MISSING')
            time.sleep(.25);self.calls+=1
            try:
                r=requests.post('https://api.tushare.pro',json=dict(api_name=api,token=token,fields=fields,params=params),timeout=30)
                r.raise_for_status();value=r.json()
            except (requests.RequestException,ValueError):raise RuntimeError('量能数据请求失败') from None
            if value.get('code')!=0:raise RuntimeError('量能数据接口未授权或请求失败')
            if file:file.parent.mkdir(parents=True,exist_ok=True);file.write_text(json.dumps(value,ensure_ascii=False),'utf-8')
        data=value.get('data') or {}
        if not set(fields.split(',')).issubset(data.get('fields',[])):raise RuntimeError('量能数据字段不完整')
        if len(data.get('items',[]))>=8000:raise RuntimeError('分钟数据达到单次上限，禁止把截断窗口当完整')
        return [dict(zip(data['fields'],r)) for r in data.get('items',[])]

def prepare(data_dir,records,today,calendar,client=None):
    root=Path(data_dir);cache_file=root/'volume_cache.json';model_file=root/'volume_model.json'
    cache=json.loads(cache_file.read_text('utf-8')) if cache_file.exists() else {}
    client=client or Client();prior=max(d for d in calendar if d<today)
    if cache.get('daily_asof')!=prior:
        rows=client('daily','ts_code,trade_date,vol',trade_date=prior.replace('-',''))
        current={r['ts_code']:dict(date=prior,volume_shares=float(r['vol'])*100) for r in rows if r.get('vol') is not None and float(r['vol'])>0}
        if len(current)<3000:raise RuntimeError('前日成交量覆盖异常')
        cache.update(daily_asof=prior,baselines=current)
    codes=sorted({r['ts_code'] for r in records if not r.get('entry_date')})
    requests=list(dict.fromkeys(POOL+codes))[:60]
    profiles=cache.setdefault('profiles',{});errors=[];started=time.monotonic()
    for code in requests:
        known=profiles.get(code,[])
        if known and known[-1]['date']>=prior:continue
        if time.monotonic()-started>=90:
            errors.append('量能曲线补充达到90秒预算，沿用已核验历史曲线；前日成交量基准已更新')
            break
        start=(date.fromisoformat(today)-timedelta(days=45)).isoformat() if len(known)<20 else (date.fromisoformat(known[-1]['date'])+timedelta(days=1)).isoformat()
        if start>prior:continue
        try:
            base=cache['baselines'].get(code)
            if known and base and base['date']==prior:
                daily={r['date']:r['volume_shares'] for r in known}
                daily[prior]=base['volume_shares']
            else:
                daily_rows=client('daily','trade_date,vol',ts_code=code,start_date=start.replace('-',''),end_date=prior.replace('-',''))
                daily={r['trade_date'][:4]+'-'+r['trade_date'][4:6]+'-'+r['trade_date'][6:]:float(r['vol'])*100 for r in daily_rows if r.get('vol') is not None}
            minutes=client.minutes(code)
            new=profile_from_tencent(minutes,code,daily)
            combined={r['date']:r for r in known+new if r['date']<today};profiles[code]=[combined[k] for k in sorted(combined)][-20:]
            if code not in cache['baselines'] and daily:
                stamp=max(d for d,v in daily.items() if v>0);cache['baselines'][code]=dict(date=stamp,volume_shares=daily[stamp])
        except Exception as exc:errors.append(code+'：'+str(exc))
    for record in records:
        base=cache.get('baselines',{}).get(record['ts_code'])
        if base:record.update(volume_previous_shares=base['volume_shares'],volume_previous_date=base['date'],volume_reference_day=today)
    try:model=build_model(cache,today)
    except ValueError:
        cache_file.write_text(json.dumps(cache,ensure_ascii=False,separators=(',',':')),'utf-8');raise
    model['issues']=errors
    profiles={code:rows for code,rows in profiles.items() if code in set(POOL+codes)};cache['profiles']=profiles
    for path,value in [(cache_file,cache),(model_file,model)]:
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')),'utf-8');temp.replace(path)
    return model

if __name__=='__main__':
    raise SystemExit('Use prepare() inside the existing data update; this module does not start a scheduler.')
